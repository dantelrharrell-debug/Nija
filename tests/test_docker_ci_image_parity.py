"""Ensure CI image builds match the scanned Dockerfile and never forward GH_TOKEN.

These checks inspect repository text only; no Docker, credentials or network calls.
"""

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
DOCKERFILES = ("Dockerfile", "Dockerfile.api", "Dockerfile.dashboard", "Dockerfile.gateway")
ARTIFACT_SCAN = ".github/workflows/artifact-scanning.yml"
BUILD_IMAGE = ".github/workflows/build-image.yml"


def image_default(path: str) -> str:
    source = (ROOT / path).read_text(encoding="utf-8")
    matches = re.findall(r"(?m)^ARG PYTHON_BASE=(\S+)$", source)
    if len(matches) != 1:
        raise AssertionError(f"{path}: expected exactly one image base default")
    return matches[0]


def build_overrides(path: str) -> list[str]:
    source = (ROOT / path).read_text(encoding="utf-8")
    return re.findall(r"--build-arg PYTHON_BASE=(\S+)", source)


class DockerCiImageParityTests(unittest.TestCase):
    """CI images stay aligned with the production Docker recipe."""

    def test_all_four_dockerfiles_have_same_default_base(self) -> None:
        expected = image_default("Dockerfile")
        for path in DOCKERFILES:
            with self.subTest(path=path):
                self.assertEqual(image_default(path), expected)

    def test_security_scan_builds_one_exact_production_base(self) -> None:
        expected = image_default("Dockerfile")
        self.assertEqual(build_overrides(ARTIFACT_SCAN), [expected])
        source = (ROOT / ARTIFACT_SCAN).read_text(encoding="utf-8")
        self.assertIn("Run Trivy vulnerability scanner", source)
        self.assertIn("Run Grype vulnerability scanner", source)
        self.assertIn("fail-build: true", source)

    def test_diagnostic_build_and_fallback_match_scanned_os(self) -> None:
        expected = image_default("Dockerfile")
        self.assertTrue(expected.startswith("python:"))
        mirrored = "public.ecr.aws/docker/library/" + expected
        self.assertEqual(build_overrides(BUILD_IMAGE), [mirrored, expected])
        self.assertIn(
            "Enforce Docker build success",
            (ROOT / BUILD_IMAGE).read_text(encoding="utf-8"),
        )

    def test_each_sidecar_has_one_global_setuptools_install_and_keeps_guards(self) -> None:
        for path in DOCKERFILES[1:]:
            with self.subTest(path=path):
                source = (ROOT / path).read_text(encoding="utf-8")
                self.assertEqual(source.count("/usr/local/bin/python -m pip install"), 1)
                self.assertIn("m.version('setuptools') == '84.1.0'", source)
                self.assertIn("jaraco.context-5.3.0.dist-info/METADATA", source)
                self.assertIn("wheel-0.45.1.dist-info/METADATA", source)

    def test_build_workflows_never_forward_unused_gh_token(self) -> None:
        for path in (ARTIFACT_SCAN, BUILD_IMAGE):
            with self.subTest(path=path):
                source = (ROOT / path).read_text(encoding="utf-8")
                self.assertNotIn("--build-arg GH_TOKEN", source)
                self.assertNotIn("secrets.GH_TOKEN", source)


if __name__ == "__main__":
    unittest.main()
