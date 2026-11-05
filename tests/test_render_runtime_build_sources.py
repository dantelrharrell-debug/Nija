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

from scripts.nija_kraken_instance_diagnostic import SOURCE_PATHS
from scripts.render_runtime_build_sources import (
    BuildRecipeDenied, RECIPE_PATHS, derive_runtime_source_sha256,
)
from scripts.nija_render_recovery_verification import (
    VerificationDenied, _verify_render_instance_app_logs,
)


class RuntimeBuildSourcesTests(unittest.TestCase):
    """Known transformations are reproduced; unknown bytes remain denied."""

    def setUp(self) -> None:
        root = Path(__file__).resolve().parents[1]
        self.sources = {path: (root / path).read_bytes() for path in SOURCE_PATHS}
        self.recipe = {path: (root / path).read_bytes() for path in RECIPE_PATHS}

    def test_reproduce_build_outputs_without_touching_files_or_approval_inputs(self) -> None:
        original = copy.deepcopy(self.sources)
        with patch.object(Path, "write_text", side_effect=AssertionError("must not write")):
            built = derive_runtime_source_sha256(self.sources, self.recipe)
        self.assertEqual(self.sources, original)
        self.assertEqual(set(built), set(SOURCE_PATHS))
        self.assertEqual(
            built["start.sh"],
            "40be05c6a4cc21f42bba1a755b3dfad6c33746588800563284013a00f7faf0ca",  # pragma: allowlist secret
        )
        # Public Git-input -> reproduced-output digests for release and main.
        broker_outputs = {
            "2fe509fa53fc0ceafae78467f6121473ce43bd5832e9438705c19aa2c5a97990":  # pragma: allowlist secret
                "8faa145d08faf258cd327054e4f7b3430efe134bd801858235943d322c5dd508",  # pragma: allowlist secret
            "5d7bb04fa40579819c421847e0104db6662a9fd904e7a74c532c9030fbca560c":  # pragma: allowlist secret
                "5206b66b572c9ff4fe198d5781b053fa037ff8a0c5d72542781c8937afe97ccc",  # pragma: allowlist secret
        }
        self.assertEqual(
            built["bot/broker_manager.py"],
            broker_outputs[hashlib.sha256(self.sources["bot/broker_manager.py"]).hexdigest()],
        )
        for path in set(SOURCE_PATHS) - {"start.sh", "bot/broker_manager.py"}:
            self.assertEqual(built[path], hashlib.sha256(self.sources[path]).hexdigest())

    def test_any_unrecognized_recipe_bytes_fail_closed(self) -> None:
        for path in RECIPE_PATHS:
            with self.subTest(path=path), self.assertRaisesRegex(BuildRecipeDenied, "runtime_build_recipe_unreviewed"):
                derive_runtime_source_sha256(self.sources, {**self.recipe, path: self.recipe[path] + b"\n"})

    def test_derivation_matches_actual_build_script_file_rewrites(self) -> None:
        root = Path(__file__).resolve().parents[1]
        scripts = (
            "scripts/apply_startup_handoff_fix.py",
            "scripts/apply_canonical_launcher_v26.py",
            "scripts/apply_render_signal_forwarding_v262.py",
        )
        paths = set(SOURCE_PATHS) | set(scripts) | {
            "scripts/canonical_runtime_launcher_v26.py", "bot/startup_position_sync.py",
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
