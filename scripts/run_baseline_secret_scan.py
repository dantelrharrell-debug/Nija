#!/usr/bin/env python3
"""Enforce the complete tracked-file scan and retain value-free failure evidence."""
from __future__ import annotations

import argparse
from contextlib import redirect_stderr, redirect_stdout
from importlib.metadata import version
import io
import json
from pathlib import Path
import subprocess
import tempfile


def scan(report_path: Path) -> int:
    """Run the pinned hook without changing or automatically approving the baseline."""
    report = {"scanner": "detect-secrets", "required_version": "1.5.0", "findings": []}
    status = 2
    try:
        report["version"] = version("detect-secrets")
        if report["version"] != report["required_version"]:
            raise ValueError("scanner_version_mismatch")
        baseline = Path(".secrets.baseline").read_bytes()
        if json.loads(baseline)["version"] != report["required_version"]:
            raise ValueError("baseline_version_mismatch")
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
        if status == 1:
            findings = json.loads(captured.getvalue())["results"]
            # Deliberately omit hashes, candidate values and raw scanner output.
            report["findings"] = [
                {"path": path, "line": item["line_number"], "type": item["type"]}
                for path, items in sorted(findings.items()) for item in items
            ]
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
