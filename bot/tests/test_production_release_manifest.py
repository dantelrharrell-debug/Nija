"""Offline manifest regressions using disposable Git fixtures inside the project."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import stat
import subprocess
import unittest
import uuid

from scripts.nija_production_release_manifest import (
    BINDINGS, build_manifest, create_manifest, main, verify_manifest,
)


ROOT = Path(__file__).resolve().parents[2]


class ProductionReleaseManifestTests(unittest.TestCase):
    """Release content is deterministic, complete and fail-closed."""

    def setUp(self) -> None:
        self.root = ROOT / (".manifest-regression-" + uuid.uuid4().hex)
        self.root.mkdir(mode=0o700)
        self.addCleanup(shutil.rmtree, self.root)
        self.git("init", "--quiet")
        self.git("config", "user.email", "offline-fixture@example.invalid")
        self.git("config", "user.name", "Offline fixture")
        self.git("config", "commit.gpgsign", "false")
        self.git("config", "core.hooksPath", "/dev/null")
        self.files = {
            "bot/commissioning_gate.py": "gate = 1\n",
            "bot/commissioning_runtime.py": "runtime = 1\n",
            "bot/kraken_risk_evidence.py": "risk = 1\n",
            "bot/kraken_evidence_composition.py": "composition = 1\n",
            "bot/old_route.py": "route = 1\n",
            "requirements.txt": "# no fixture dependencies\n",
            "requirements-extra.txt": "# no extra fixture dependencies\n",
            ".github/workflows/ci.yml": "name: offline-fixture\n",
            "k8s/components/redis/deployment.yaml": "kind: Deployment\n",
            "Dockerfile": "FROM scratch\n",
            "Dockerfile.worker": "FROM scratch\n",
            ".dockerignore": ".git\n",
            "railway.json": "{}\n",
            "render.yaml": "services: []\n",
            "runtime.txt": "python-3.11\n",
            "main.py": "pass\n",
            "bot.py": "pass\n",
            "start.sh": "#!/bin/sh\nexit 0\n",
        }
        for name, raw in self.files.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(raw, encoding="utf-8")
        self.base = self.commit()
        (self.root / "bot/old_route.py").unlink()
        (self.root / "bot/new_route.py").write_text("route = 2\n", encoding="utf-8")
        (self.root / "scripts").mkdir()
        (self.root / "scripts/run_trivy_scan.sh").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        (self.root / "k8s/components/redis/deployment.yaml").write_text(
            "kind: Deployment\n# reviewed hardening fixture\n", encoding="utf-8",
        )
        self.source = self.commit()
        self.output = self.root / "release.json"
        self.bindings = {
            "source_commit": self.source, "base_commit": self.base,
            "image": "registry.example.invalid/nija@sha256:" + "a" * 64,
            "previous_release": "registry.example.invalid/nija@sha256:" + "b" * 64,
            "reviewed_bindings": {name: "sha256:" + "c" * 64 for name in BINDINGS},
        }

    def git(self, *args: str) -> str:
        """Run local Git against the fixture, never a remote."""
        return subprocess.check_output(
            ["git", "-C", str(self.root), *args], stderr=subprocess.PIPE,
        ).decode().strip()

    def commit(self) -> str:
        """Commit fixture content, not the actual working repository."""
        self.git("add", ".")
        self.git("commit", "--quiet", "-m", "Offline fixture")
        return self.git("rev-parse", "HEAD")

    def create(self) -> str:
        """Create the fixture manifest."""
        return create_manifest(self.output, self.root, **self.bindings)

    def verify(self, digest: str) -> dict:
        """Verify against the externally supplied digest and exact source."""
        return verify_manifest(
            self.output, self.root, expected_sha256=digest, source_commit=self.source,
        )

    def test_deterministic_inventory_binds_sources_requirements_workflows_and_deletions(self) -> None:
        digest = self.create()
        raw = self.output.read_bytes()
        second = self.root / "second.json"
        self.assertEqual(create_manifest(second, self.root, **self.bindings), digest)
        self.assertEqual(second.read_bytes(), raw)
        manifest = self.verify(digest)
        self.assertEqual(manifest["source_commit"], self.source)
        self.assertEqual(manifest["base_commit"], self.base)
        self.assertEqual(manifest["deleted_files"], ["bot/old_route.py"])
        expected = set(self.files) - {"bot/old_route.py"} | {"bot/new_route.py", "scripts/run_trivy_scan.sh"}
        self.assertEqual(set(manifest["files_sha256"]), expected)
        for name, sha in manifest["files_sha256"].items():
            self.assertEqual(sha, hashlib.sha256((self.root / name).read_bytes()).hexdigest())
        self.assertFalse(manifest["independent_approval_verified"])
        self.assertFalse(manifest["production_mutation_authorized"])
        self.assertEqual(stat.S_IMODE(self.output.stat().st_mode), 0o600)

    def test_refuses_overwrite_without_altering_existing_bytes(self) -> None:
        self.create()
        before = self.output.read_bytes()
        with self.assertRaises(FileExistsError):
            self.create()
        self.assertEqual(self.output.read_bytes(), before)

    def test_rejects_source_tampering_at_create_and_verify(self) -> None:
        digest = self.create()
        (self.root / "bot/commissioning_gate.py").write_text("gate = 2\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "uncommitted_production_changes"):
            self.verify(digest)
        with self.assertRaisesRegex(ValueError, "uncommitted_production_changes"):
            create_manifest(self.root / "new.json", self.root, **self.bindings)
        self.assertFalse((self.root / "new.json").exists())

    def test_rejects_manifest_tampering_even_with_recomputed_digest(self) -> None:
        digest = self.create()
        manifest = json.loads(self.output.read_bytes())
        manifest["files_sha256"].pop("requirements.txt")
        raw = (json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n").encode()
        self.output.write_bytes(raw)
        with self.assertRaisesRegex(ValueError, "manifest_digest_mismatch"):
            self.verify(digest)
        with self.assertRaisesRegex(ValueError, "manifest_content_mismatch"):
            self.verify(hashlib.sha256(raw).hexdigest())

    def test_rejects_missing_or_unpinned_bindings(self) -> None:
        for name in BINDINGS:
            bindings = dict(self.bindings)
            bindings["reviewed_bindings"] = dict(bindings["reviewed_bindings"])
            del bindings["reviewed_bindings"][name]
            with self.subTest(missing=name), self.assertRaises(ValueError):
                build_manifest(self.root, **bindings)
        for field in ("image", "previous_release"):
            with self.subTest(field=field), self.assertRaises(ValueError):
                build_manifest(self.root, **{**self.bindings, field: "nija:latest"})
        with self.assertRaises(ValueError):
            build_manifest(self.root, **{**self.bindings, "reviewed_bindings": {
                name: "https://review.invalid/?credential=not-permitted" for name in BINDINGS
            }})
        self.assertFalse(self.output.exists())

    def test_requires_exact_source_and_external_manifest_pin(self) -> None:
        digest = self.create()
        with self.assertRaises(ValueError):
            build_manifest(self.root, **{**self.bindings, "source_commit": "HEAD"})
        with self.assertRaisesRegex(ValueError, "expected_source_commit_mismatch"):
            verify_manifest(self.output, self.root, expected_sha256=digest, source_commit=self.base)
        with self.assertRaisesRegex(ValueError, "external_manifest_digest_required"):
            self.verify("")

    def test_rejects_symlink_source_and_output(self) -> None:
        source = self.root / "bot/commissioning_gate.py"
        source.rename(self.root / "saved.py")
        source.symlink_to(self.root / "saved.py")
        with self.assertRaisesRegex(ValueError, "uncommitted_production_changes"):
            self.create()
        source.unlink()
        (self.root / "saved.py").rename(source)
        self.output.symlink_to(source)
        with self.assertRaises(FileExistsError):
            self.create()
        self.assertEqual(source.read_text(), self.files["bot/commissioning_gate.py"])

    def test_refuses_manifest_already_in_committed_source(self) -> None:
        with self.assertRaisesRegex(ValueError, "tracked_manifest_output_refused"):
            create_manifest(self.root / "requirements.txt", self.root, **self.bindings)
        with self.assertRaisesRegex(ValueError, "tracked_manifest_output_refused"):
            create_manifest(self.root / ".github/workflows/release.json", self.root, **self.bindings)

    def test_requirements_and_workflow_tampering_fail_closed(self) -> None:
        digest = self.create()
        for name in (
            "requirements.txt", ".github/workflows/ci.yml",
            "scripts/run_trivy_scan.sh", "k8s/components/redis/deployment.yaml",
        ):
            original = (self.root / name).read_bytes()
            (self.root / name).write_bytes(original + b"# changed\n")
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.verify(digest)
            (self.root / name).write_bytes(original)
        self.verify(digest)

    def test_missing_required_source_refuses_creation(self) -> None:
        (self.root / "bot/commissioning_runtime.py").unlink()
        self.bindings["source_commit"] = self.commit()
        with self.assertRaises(ValueError):
            self.create()
        self.assertFalse(self.output.exists())

    def test_root_release_surface_tampering_fails_create_and_verify(self) -> None:
        digest = self.create()
        for name in (
            "Dockerfile", "Dockerfile.worker", ".dockerignore", "railway.json", "render.yaml",
            "runtime.txt", "main.py", "bot.py", "start.sh",
        ):
            original = (self.root / name).read_bytes()
            (self.root / name).write_bytes(original + b"\n")
            with self.subTest(name=name):
                with self.assertRaisesRegex(ValueError, "uncommitted_production_changes"):
                    self.verify(digest)
                with self.assertRaisesRegex(ValueError, "uncommitted_production_changes"):
                    create_manifest(self.root / "other.json", self.root, **self.bindings)
            (self.root / name).write_bytes(original)
        self.verify(digest)

    def test_untracked_root_release_surface_is_refused(self) -> None:
        path = self.root / "Dockerfile.uncommitted"
        path.write_text("FROM scratch\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "uncommitted_production_source"):
            self.create()
        path.unlink()
        (self.root / "runtime.txt").unlink()
        self.bindings["source_commit"] = self.commit()
        (self.root / "runtime.txt").write_text("python-3.11\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "uncommitted_production_source"):
            self.create()

    def test_changed_root_web_policy_and_compose_are_bound(self) -> None:
        names = ("web_cors_policy.py", "docker-compose.yml")
        for name in names:
            (self.root / name).write_text("# offline release fixture\n", encoding="utf-8")
        self.source = self.commit()
        self.bindings["source_commit"] = self.source
        digest = self.create()
        manifest = self.verify(digest)
        for name in names:
            self.assertIn(name, manifest["files_sha256"])
            original = (self.root / name).read_bytes()
            (self.root / name).write_bytes(original + b"# changed\n")
            with self.assertRaises(ValueError):
                self.verify(digest)
            (self.root / name).write_bytes(original)
    def test_repository_root_is_not_a_valid_manifest_output(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid_source_path"):
            create_manifest(self.root, self.root, **self.bindings)

    def test_deleted_source_cannot_reappear(self) -> None:
        digest = self.create()
        (self.root / "bot/old_route.py").write_text("route = 1\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "uncommitted_production_source"):
            self.verify(digest)

    def test_untracked_even_ignored_production_sources_must_be_committed_first(self) -> None:
        (self.root / ".git/info/exclude").write_text("bot/kraken_*.py\n", encoding="utf-8")
        (self.root / "bot/kraken_new_provider.py").write_text("provider = 1\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "uncommitted_production_source"):
            self.create()
        self.assertFalse(self.output.exists())

    def test_duplicate_cli_bindings_fail_closed_without_file_creation(self) -> None:
        args = [
            "create", "--repository", str(self.root), "--manifest", str(self.output),
            "--source-commit", self.source, "--base-commit", self.base,
            "--image", self.bindings["image"], "--previous-release", self.bindings["previous_release"],
        ]
        for name in ("account", "account"):
            args += ["--reviewed-binding", name + "=sha256:" + "c" * 64]
        self.assertEqual(main(args), 1)
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
