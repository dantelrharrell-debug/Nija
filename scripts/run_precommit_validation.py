"""Retain value-free hook diagnostics without changing pre-commit enforcement."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess

HOOKS = {
    "Verify reviewed secret source context": "reviewed-secret-context",
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
    "Check for large files": "check-added-large-files",
    "Check mixed line endings": "mixed-line-ending",
    "Check Python AST": "check-ast",
    "Check docstring is first": "check-docstring-first",
    "Check for debug statements": "debug-statements",
    "Check test naming": "name-tests-test",
    "Bandit security check": "bandit",
    "Prevent committing .env files with secrets": "check-env-files",  # pragma: allowlist secret - fixed public hook identifier
    "Check for hardcoded API keys": "check-api-keys",  # pragma: allowlist secret - fixed public hook identifier
    "Prevent committing PEM/certificate files": "check-pem-files",
    "Check for prohibited hierarchical terminology": "check-terminology",
    "Check for database schema changes without migration": "check-schema-changes",
    "Enforce ExecutionPipeline routing": "check-direct-broker-execution",
    "🔒 RISK FREEZE - Check for unauthorized risk parameter changes": "risk_freeze_check",
}
COMMAND = ["pre-commit", "run", "--all-files", "--show-diff-on-failure"]


def summarize(output: str, error_output: str = "") -> dict:
    """Emit only fixed allowlisted hook IDs and diagnostic categories."""
    diagnostics = []
    failed = set()
    categories = set()
    for stream in (output, error_output):
        clean = re.sub(r"\x1b\[[0-9;]*m", "", stream)
        lines = clean.splitlines()
        # Source diffs cannot classify errors. Keep streams separate so a
        # stdout diff cannot hide a real pre-commit error sent to stderr.
        boundary = next((i for i, line in enumerate(lines)
                         if line.strip() == "All changes made by hooks:"), None)
        diagnostics.extend(lines if boundary is None else lines[:boundary])
        if boundary is not None:
            # A contradictory zero exit must still fail closed.
            categories.add("source_diff_emitted")
    for line in diagnostics:
        for title, identifier in HOOKS.items():
            if re.fullmatch(re.escape(title) + r"\.+Failed\s*", line):
                failed.add(identifier)
        if line.strip() == "- files were modified by this hook":
            categories.add("hook_modified_files")
        error = re.match(r"^An (?:unexpected )?error has occurred: "
                         r"(InvalidManifestError|InvalidConfigError|CalledProcessError):", line)
        if error:
            categories.add({
                "InvalidManifestError": "hook_manifest_error",
                "InvalidConfigError": "hook_configuration_error",
                "CalledProcessError": "hook_initialization_error",
            }[error.group(1)])
    if ("hook_initialization_error" in categories
            and any("tokeninternal" in line for line in diagnostics)):
        categories.add("go_toolchain_compatibility_error")
    return {"failed_hooks": sorted(failed), "categories": sorted(categories)}


def formatting_paths() -> list[str]:
    """Locate tracked hook edits without copying hook output or file contents."""
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "--no-renames", "-z", "--"],
            capture_output=True, timeout=15, check=False, shell=False,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode:
        return []
    paths = result.stdout.decode("utf-8", errors="replace").split("\0")
    # Keep unusual names, terminal escape sequences, and private-key files out
    # of this report. Never consume or forward a filename supplied by a hook.
    return sorted({
        path for path in paths
        if re.fullmatch(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*\.(?:py|sh|yml|yaml|md|mjs|js|ts|tsx|json|toml|txt|html|css)", path)
        and not any(part.startswith(".") for part in path.split("/"))
    })[:250]


# Only documented path labels inside a known failed hook are recognized.
# Never retain an entire finding, secret, source line or arbitrary hook text.
PATH_LABELS = {
    "bandit": re.compile(r"^\s*Location:\s*(.+?):[0-9]+(?::[0-9]+)?\s*$"),
    "detect-secrets": re.compile(r"^\s*Location:\s*(.+?):[0-9]+\s*$"),  # pragma: allowlist secret - fixed public hook identifier
    "detect-private-key": re.compile(r"^\s*Private key found:\s*(.+?)\s*$"),
    "gitleaks": re.compile(r"^\s*File:\s*(.+?)\s*$"),
}


def tracked_finding_candidates() -> set[str]:
    """Get tracked ordinary source paths, without reading their contents."""
    try:
        result = subprocess.run(
            ["git", "ls-files", "-z", "--"], capture_output=True, timeout=15,
            check=False, shell=False, stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return set()
    if result.returncode:
        return set()
    return {
        path for path in result.stdout.decode("utf-8", errors="replace").split("\0")
        if re.fullmatch(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*\.(?:py|sh|yml|yaml|md|mjs|js|ts|tsx|json|toml|txt|html|css)", path)
        and not any(part.startswith(".") for part in path.split("/"))
    }


def finding_paths(output: str, error_output: str, tracked: set[str]) -> dict:
    """Return bounded tracked paths only; absence of attribution is not a pass."""
    found: dict[str, set[str]] = {}
    for stream in (output, error_output):
        current = None
        for line in re.sub(r"\x1b\[[0-9;]*m", "", stream).splitlines():
            if line.strip() == "All changes made by hooks:":
                break
            # End attribution at any hook result, including unknown hooks.
            if re.fullmatch(r".+\.{2,}(?:Passed|Failed|Skipped)\s*", line):
                current = next((
                    identifier for title, identifier in HOOKS.items()
                    if identifier in PATH_LABELS
                    and re.fullmatch(re.escape(title) + r"\.+Failed\s*", line)
                ), None)
                continue
            if current is None:
                continue
            match = PATH_LABELS[current].fullmatch(line)
            if match:
                path = match.group(1)
                if path.startswith("./"):
                    path = path[2:]
                if path in tracked:
                    found.setdefault(current, set()).add(path)
    return {hook: sorted(paths)[:100] for hook, paths in sorted(found.items())}


def run(report_path: Path) -> int:
    """Run the unchanged all-file command; findings and runner errors fail closed."""
    report = {"schema_version": 1, "failed_hooks": [], "categories": []}
    try:
        result = subprocess.run(COMMAND, capture_output=True, text=True,
                                timeout=1200, check=False, shell=False, stdin=subprocess.DEVNULL)
        report.update(summarize(result.stdout, result.stderr))
        status = result.returncode if 0 <= result.returncode <= 255 else 2
        if status == 0 and (report["failed_hooks"] or report["categories"]):
            status = 2
        report["outcome"] = "passed" if status == 0 else "failed"
        if {"trailing-whitespace", "end-of-file-fixer"} & set(report["failed_hooks"]) \
                and "hook_modified_files" in report["categories"]:
            report["tracked_hook_edits"] = formatting_paths()
        if set(report["failed_hooks"]) & set(PATH_LABELS):
            report["tracked_finding_paths"] = finding_paths(
                result.stdout, result.stderr, tracked_finding_candidates(),
            )
    except subprocess.TimeoutExpired:
        status = 124
        report.update(outcome="runner_error", categories=["timeout"])
    except (OSError, subprocess.SubprocessError):
        status = 2
        report.update(outcome="runner_error", categories=["runner_unavailable"])
    report["exit_code"] = status
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    console_report = {key: value for key, value in report.items() if key not in {"tracked_hook_edits", "tracked_finding_paths"}}
    print(json.dumps(console_report, sort_keys=True))
    return status


def main() -> int:
    """Write a structured report, never raw scanner output or source diffs."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    return run(parser.parse_args().report)


if __name__ == "__main__":
    raise SystemExit(main())
