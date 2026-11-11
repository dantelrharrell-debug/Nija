"""Retain value-free hook diagnostics without changing pre-commit enforcement."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess

HOOKS = {
    "Detect secrets": "detect-secrets",  # pragma: allowlist secret - fixed public hook identifier
    "Gitleaks secret scanner": "gitleaks",
    "TruffleHog secret scanner": "trufflehog",
    "Detect private keys": "detect-private-key",
    "Detect AWS credentials": "detect-aws-credentials",
    "Trim trailing whitespace": "trailing-whitespace",
    "Fix End of Files": "end-of-file-fixer",
    "Fix end of files": "end-of-file-fixer",
    "Check Yaml": "check-yaml",
    "Check YAML syntax": "check-yaml",
    "Check JSON": "check-json",
    "Check JSON syntax": "check-json",
    "Check for added large files": "check-added-large-files",
    "Check for case conflicts": "check-case-conflict",
    "Check for merge conflicts": "check-merge-conflict",
    "Mixed line ending": "mixed-line-ending",
    "Check Executables have shebangs": "check-executables-have-shebangs",
    "Check that scripts with shebangs are executable": "check-shebang-scripts-are-executable",
}
COMMAND = ["pre-commit", "run", "--all-files", "--show-diff-on-failure"]


def summarize(output: str) -> dict:
    """Emit only fixed allowlisted hook IDs and diagnostic categories."""
    clean = re.sub(r"\x1b\[[0-9;]*m", "", output)
    failed = set()
    for line in clean.splitlines():
        for title, identifier in HOOKS.items():
            if re.fullmatch(re.escape(title) + r"\.+Failed\s*", line):
                failed.add(identifier)
    categories = set()
    for marker, category in (
        ("InvalidManifestError", "hook_manifest_error"),
        ("InvalidConfigError", "hook_configuration_error"),
        ("CalledProcessError", "hook_initialization_error"),
        ("tokeninternal", "go_toolchain_compatibility_error"),
        ("files were modified by this hook", "hook_modified_files"),
    ):
        if marker in clean:
            categories.add(category)
    return {"failed_hooks": sorted(failed), "categories": sorted(categories)}


def run(report_path: Path) -> int:
    """Run the unchanged all-file command; findings and runner errors fail closed."""
    report = {"schema_version": 1, "failed_hooks": [], "categories": []}
    try:
        result = subprocess.run(COMMAND, capture_output=True, text=True,
                                timeout=1200, check=False, shell=False, stdin=subprocess.DEVNULL)
        report.update(summarize(result.stdout + "\n" + result.stderr))
        status = result.returncode if 0 <= result.returncode <= 255 else 2
        if status == 0 and (report["failed_hooks"] or report["categories"]):
            status = 2
        report["outcome"] = "passed" if status == 0 else "failed"
    except subprocess.TimeoutExpired:
        status = 124
        report.update(outcome="runner_error", categories=["timeout"])
    except (OSError, subprocess.SubprocessError):
        status = 2
        report.update(outcome="runner_error", categories=["runner_unavailable"])
    report["exit_code"] = status
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return status


def main() -> int:
    """Write a structured report, never raw scanner output or source diffs."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    return run(parser.parse_args().report)


if __name__ == "__main__":
    raise SystemExit(main())
