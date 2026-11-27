"""Offline build/source attestation; no production or exchange requests."""
import copy
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import nija_render_recovery_verification as verification
from scripts.nija_kraken_instance_diagnostic import SOURCE_PATHS
from scripts.render_runtime_build_sources import (
    BuildRecipeDenied, RECIPE_PATHS, derive_runtime_source_sha256,
)
from scripts.nija_render_recovery_verification import (
    VerificationDenied, _verify_render_instance_app_logs,
)


# Immutable already-reviewed Git inputs and the existing expected output
# digests. They are test fixtures, never sources of production approval.
_REVIEWED_BROKER_FIXTURES = (
    ("68c566204312a9cabe328ad3f3504cadc1d8736c",
     "5d7bb04fa40579819c421847e0104db6662a9fd904e7a74c532c9030fbca560c",  # pragma: allowlist secret
     "5206b66b572c9ff4fe198d5781b053fa037ff8a0c5d72542781c8937afe97ccc"),  # pragma: allowlist secret
    ("63d63c7e2746c3d7f0aabd39bd6b2a3c853f77c8",
     "2fe509fa53fc0ceafae78467f6121473ce43bd5832e9438705c19aa2c5a97990",  # pragma: allowlist secret
     "8faa145d08faf258cd327054e4f7b3430efe134bd801858235943d322c5dd508"),  # pragma: allowlist secret
)
_BROKER_SOURCE = "bot/broker_manager.py"


class RuntimeBuildSourcesTests(unittest.TestCase):
    """Known transformations are reproduced; unknown bytes remain denied."""

    def setUp(self) -> None:
        root = Path(__file__).resolve().parents[1]
        self.sources = {path: (root / path).read_bytes() for path in SOURCE_PATHS}
        self.recipe = {path: (root / path).read_bytes() for path in RECIPE_PATHS}
        from scripts.render_runtime_build_sources import DOCKER_SHA256
        current = self.recipe["Dockerfile"]
        self.current_unreviewed_dockerfile = current
        # Load immutable, reviewed historical bytes rather than reversing a
        # growing sequence of production Dockerfile changes. This fixture is
        # only used by offline positive tests, never by production recovery.
        fixture = (root / "tests/fixtures/render_reviewed_dockerfile_6e34c616").read_bytes()
        self.assertNotEqual(current, fixture)
        self.assertIn(hashlib.sha256(fixture).hexdigest(), DOCKER_SHA256)
        self.recipe["Dockerfile"] = fixture

    def test_current_pinned_trixie_build_recipe_stays_denied(self) -> None:
        with self.assertRaisesRegex(BuildRecipeDenied, "runtime_build_recipe_unreviewed"):
            derive_runtime_source_sha256(
                self.sources, {**self.recipe, "Dockerfile": self.current_unreviewed_dockerfile},
            )


    def test_reproduce_build_outputs_without_touching_files_or_approval_inputs(self) -> None:
        root = Path(__file__).resolve().parents[1]
        for commit, expected_source, expected_output in _REVIEWED_BROKER_FIXTURES:
            with self.subTest(commit=commit):
                reviewed = subprocess.check_output(
                    ["git", "show", commit + ":" + _BROKER_SOURCE], cwd=root,
                )
                self.assertEqual(hashlib.sha256(reviewed).hexdigest(), expected_source)
                sources = {**self.sources, _BROKER_SOURCE: reviewed}
                original = copy.deepcopy(sources)
                with patch.object(Path, "write_text", side_effect=AssertionError("must not write")):
                    built = derive_runtime_source_sha256(sources, self.recipe)
                self.assertEqual(sources, original)
                self.assertEqual(set(built), set(SOURCE_PATHS))
                self.assertEqual(
                    built["start.sh"],
                    "be868922a649560144d6e178489e8e955f2b537a3e95c8c74053e2317e8a6866",  # pragma: allowlist secret
                )
                self.assertEqual(built[_BROKER_SOURCE], expected_output)
                for path in set(SOURCE_PATHS) - {
                    "start.sh", _BROKER_SOURCE, "bot/canonical_broker_startup_convergence_v24.py",
                }:
                    self.assertEqual(built[path], hashlib.sha256(sources[path]).hexdigest())

    def test_current_unreviewed_broker_bytes_denied_before_runtime_access(self) -> None:
        commit, approved_hash, _ = _REVIEWED_BROKER_FIXTURES[0]
        current = self.sources[_BROKER_SOURCE]
        self.assertNotEqual(hashlib.sha256(current).hexdigest(), approved_hash)
        approval = {"commit": commit, "source_sha256": {_BROKER_SOURCE: approved_hash}}
        ref = "refs/heads/" + verification.RELEASE_BRANCH
        with patch.dict(os.environ, {"GITHUB_REF": ref}, clear=True), \
             patch.object(verification, "load_reviewed_approval", return_value=approval), \
             patch.object(verification, "inspect_render_api", return_value={"failures": []}), \
             patch.object(verification, "verify_baseline"), \
             patch.object(verification, "_command", side_effect=[commit.encode(), b"", current]), \
             patch.object(verification, "_runtime") as runtime:
            report = verification.run_verification()
        self.assertEqual(report["failures"], ["reviewed_source_digest_mismatch"])
        self.assertFalse(report["SOURCE_INTEGRITY_VERIFIED"])
        self.assertFalse(report["allow_new_orders"])
        runtime.assert_not_called()

    def test_any_unrecognized_recipe_bytes_fail_closed(self) -> None:
        for path in RECIPE_PATHS:
            with self.subTest(path=path), self.assertRaisesRegex(BuildRecipeDenied, "runtime_build_recipe_unreviewed"):
                derive_runtime_source_sha256(self.sources, {**self.recipe, path: self.recipe[path] + b"\n"})

    def test_security_upgrade_variant_does_not_allow_unreviewed_package_flags(self) -> None:
        """Recognize exact public bytes, not any recipe containing an upgrade."""
        recipe = self.recipe["Dockerfile"]
        self.assertIn(b"apt-get upgrade -y &&", recipe)
        for flag in (b"--allow-unauthenticated", b"--allow-downgrades"):
            changed = recipe.replace(b"apt-get upgrade -y &&", b"apt-get upgrade -y " + flag + b" &&", 1)
            with self.subTest(flag=flag), self.assertRaisesRegex(
                BuildRecipeDenied, "runtime_build_recipe_unreviewed",
            ):
                derive_runtime_source_sha256(self.sources, {**self.recipe, "Dockerfile": changed})

    def test_derivation_matches_actual_build_script_file_rewrites(self) -> None:
        root = Path(__file__).resolve().parents[1]
        scripts = (
            "scripts/apply_startup_handoff_fix.py",
            "scripts/apply_canonical_launcher_v26.py",
            "scripts/apply_render_signal_forwarding_v262.py",
            "scripts/apply_kraken_recovery_coordinator_single_owner_v400.py",
        )
        paths = set(SOURCE_PATHS) | set(scripts) | {
            "scripts/canonical_runtime_launcher_v26.py", "bot/startup_position_sync.py",
            "bot/kraken_connection_convergence_v44_patch.py",
        }
        with tempfile.TemporaryDirectory() as directory:
            isolated = Path(directory)
            for path in paths:
                target = isolated / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((root / path).read_bytes())
            for script in scripts:
                subprocess.run(
                    [sys.executable, "-B", "-S", str(isolated / script)],
                    cwd=isolated, env={"PATH": os.defpath, "NIJA_DEFER_RUNTIME_SITE_HOOKS": "1"},
                    check=True, capture_output=True, timeout=15,
                )
            actual = {
                path: hashlib.sha256((isolated / path).read_bytes()).hexdigest() for path in SOURCE_PATHS
            }
        self.assertEqual(actual, derive_runtime_source_sha256(self.sources, self.recipe))

    def test_build_only_coordinator_bytes_cannot_stand_in_for_post_entrypoint_bytes(self) -> None:
        expected = derive_runtime_source_sha256(self.sources, self.recipe)
        path = "bot/canonical_broker_startup_convergence_v24.py"
        original = hashlib.sha256(self.sources[path]).hexdigest()
        self.assertNotEqual(expected[path], original)
        approval = {"source_sha256": expected}
        with self.assertRaisesRegex(VerificationDenied, "runtime_source_digest_mismatch"):
            _verify_render_instance_app_logs(
                approval, {"source_sha256": {**expected, path: original}}, expected_source_sha256=expected,
            )

    def test_coordinator_rewrite_is_idempotent_and_rejects_ambiguous_inputs(self) -> None:
        from scripts.render_runtime_build_sources import _coordinator_runtime_text, coordinator
        path = "bot/canonical_broker_startup_convergence_v24.py"
        original = self.sources[path].decode()
        rewritten = _coordinator_runtime_text(original)
        self.assertEqual(_coordinator_runtime_text(rewritten), rewritten)
        for invalid in (
            original.replace(coordinator.V24_OLD, ""),
            original + coordinator.V24_OLD,
            original + coordinator.MARKER,
            rewritten.replace(coordinator.V24_NEW, ""),
        ):
            with self.assertRaises(RuntimeError):
                _coordinator_runtime_text(invalid)

    def test_missing_or_extra_build_inputs_fail_closed(self) -> None:
        for sources, recipe in (
            ({}, self.recipe), (self.sources, {}),
            ({**self.sources, "extra": b""}, self.recipe),
            (self.sources, {**self.recipe, "extra": b""}),
        ):
            with self.assertRaisesRegex(BuildRecipeDenied, "runtime_build_inputs_incomplete"):
                derive_runtime_source_sha256(sources, recipe)

    def test_bad_source_encoding_or_patch_anchors_fail_closed(self) -> None:
        for path, value in (("start.sh", b"\xff"), ("start.sh", b"#!/bin/bash\nexit 0\n"),
                            ("bot/broker_manager.py", b"# no reviewed anchors")):
            with self.subTest(path=path), self.assertRaisesRegex(BuildRecipeDenied, "runtime_build_transform_failed"):
                derive_runtime_source_sha256({**self.sources, path: value}, self.recipe)

    def test_verification_checkout_cannot_change_transform_silently(self) -> None:
        original = Path.read_bytes
        def read(path):
            if path.name == "apply_startup_handoff_fix.py":
                return b"changed verification implementation"
            return original(path)
        with patch.object(Path, "read_bytes", read), self.assertRaisesRegex(
            BuildRecipeDenied, "runtime_build_verifier_recipe_changed",
        ):
            derive_runtime_source_sha256(self.sources, self.recipe)

    def test_runtime_tampering_is_denied_before_log_api_access(self) -> None:
        expected = derive_runtime_source_sha256(self.sources, self.recipe)
        approval = {"commit": "a" * 40, "source_sha256": {
            path: hashlib.sha256(source).hexdigest() for path, source in self.sources.items()
        }}
        for path in SOURCE_PATHS:
            tampered = {**expected, path: "0" * 64}
            with self.subTest(path=path), patch(
                "scripts.nija_render_recovery_verification._read_render_instance_logs",
            ) as logs, self.assertRaisesRegex(VerificationDenied, "runtime_source_digest_mismatch"):
                _verify_render_instance_app_logs(approval, {"source_sha256": tampered}, expected_source_sha256=expected)
            logs.assert_not_called()
        # Original Git bytes cannot stand in for the deployed, transformed bytes.
        with self.assertRaisesRegex(VerificationDenied, "runtime_source_digest_mismatch"):
            _verify_render_instance_app_logs(
                approval, {"source_sha256": approval["source_sha256"]}, expected_source_sha256=expected,
            )


if __name__ == "__main__":
    unittest.main()
