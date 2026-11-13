#!/usr/bin/env python3
"""Enforce the complete tracked-file scan and retain value-free failure evidence."""
from __future__ import annotations

import argparse
from contextlib import redirect_stderr, redirect_stdout
from importlib.metadata import version
import io
import json
import os
import re
from pathlib import Path
import subprocess
import tempfile


def _checkout_revision() -> list[str]:
    subprocess.run(["git", "diff", "--quiet", "HEAD", "--"], check=True, capture_output=True)
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD", "HEAD^{tree}"], check=True, capture_output=True,
    ).stdout.decode().splitlines()
    if len(revision) != 2 or any(not re.fullmatch(r"[0-9a-f]{40}", item) for item in revision):
        raise ValueError("checkout_identity_invalid")
    return revision
PRIORITY_TYPES = ("Private Key", "Basic Auth Credentials")


def priority_review_locations(findings: list[dict]) -> list[dict]:
    """Return review coordinates only, with private-key markers first."""
    rank = {name: index for index, name in enumerate(PRIORITY_TYPES)}
    return [
        {"path": item["path"], "line": item["line"], "type": item["type"]}
        for item in sorted(
            (item for item in findings if item["type"] in rank),
            key=lambda item: (rank[item["type"]], item["path"], item["line"]),
        )
    ]


def scan(report_path: Path) -> int:
    """Run the pinned hook without changing or automatically approving the baseline."""
    report = {"scanner": "detect-secrets", "required_version": "1.5.0", "findings": [], "category_counts": {}, "priority_review_locations": []}
    status = 2
    try:
        report["version"] = version("detect-secrets")
        if report["version"] != report["required_version"]:
            raise ValueError("scanner_version_mismatch")
        baseline = Path(".secrets.baseline").read_bytes()
        baseline_data = json.loads(baseline)
        if baseline_data["version"] != report["required_version"]:
            raise ValueError("baseline_version_mismatch")
        # Bind marker-only detector exceptions to complete reviewed source.
        # A new PEM payload can share the old delimiter's detector identity.
        if "reviewed_context_manifest" in baseline_data:
            from check_reviewed_secret_context import MANIFEST, check_context
            if (baseline_data["reviewed_context_manifest"] != MANIFEST
                    or not check_context(Path.cwd())):
                raise ValueError("reviewed_source_context_changed")
        revision = _checkout_revision()
        report["checked_out_commit"], report["checked_out_tree"] = revision
        event = os.environ.get("GITHUB_EVENT_NAME")
        report["ci_event"] = event if event in {
            "push", "pull_request", "schedule", "workflow_dispatch", "workflow_call",
        } else None
        expected = os.environ.get("GITHUB_SHA")
        if expected is not None and expected != revision[0]:
            raise ValueError("checkout_differs_from_ci_revision")
        paths = subprocess.run(
            ["git", "ls-files", "-z"], check=True, capture_output=True,
        ).stdout.decode().split("\0")
        paths = [path for path in paths if path]
        if not paths:
            raise ValueError("no_tracked_files")
        report["tracked_file_count"] = len(paths)
        # The hook automatically excludes its baseline input. Because that input
        # is a temporary copy, also exclude the original metadata file explicitly.
        paths = [path for path in paths if path != ".secrets.baseline"]
        from detect_secrets.pre_commit_hook import main as hook_main

        # The hook can refresh line numbers and return 3. Keep that failure,
        # but write only to a temporary baseline, never the reviewed source.
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory) / ".secrets.baseline"
            temporary.write_bytes(baseline)
            captured = io.StringIO()
            with redirect_stdout(captured), redirect_stderr(io.StringIO()):
                status = hook_main(["--json", "--baseline", str(temporary), *paths])
            report["baseline_would_change"] = temporary.read_bytes() != baseline
        if _checkout_revision() != revision:
            raise ValueError("checkout_changed_during_scan")
        if status == 1:
            findings = json.loads(captured.getvalue())["results"]
            # Deliberately omit hashes, candidate values and raw scanner output.
            report["findings"] = [
                {"path": path, "line": item["line_number"], "type": item["type"]}
                for path, items in sorted(findings.items()) for item in items
            ]
        # Summarize only detector names and counts, never secret values or hashes.
        counts = {}
        for finding in report["findings"]:
            category = finding["type"]
            counts[category] = counts.get(category, 0) + 1
        report["category_counts"] = dict(sorted(counts.items()))
        report["priority_review_locations"] = priority_review_locations(report["findings"])
        report["outcome"] = (
            "clean" if status == 0 else "unbaselined_candidates" if status == 1
            else "baseline_refresh_required" if status == 3 else "scanner_error"
        )
    except Exception:
        # Errors may contain input snippets. Publish no exception text or secrets.
        status = 2
        report["outcome"] = "scanner_error"
    report["exit_code"] = status
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Secret scan: {report['outcome']}; candidates={len(report['findings'])}; exit={status}")
    return status


def main() -> int:
    """Scan from the repository root; a failed scan always has a nonzero status."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    return scan(parser.parse_args().report)


if __name__ == "__main__":
    raise SystemExit(main())
