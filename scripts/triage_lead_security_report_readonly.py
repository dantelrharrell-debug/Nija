#!/usr/bin/env python3
"""Offline, value-free reviewer summary for existing fail-closed CI scan reports.

Never changes input reports, the secret baseline, Git state, or CI security
checks. No sensitive values are emitted or approved by this tool.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sys

KNOWN_TYPES = {
    "Base64 High Entropy String",
    "Basic Auth Credentials",
    "Hex High Entropy String",
    "Private Key",
    "Secret Keyword",
}
SAFE_PATH = re.compile(r"[a-zA-Z0-9_./-]+\Z")


def _safe_path(value: object) -> str:
    if not isinstance(value, str) or not value or not SAFE_PATH.fullmatch(value):
        raise ValueError("unsafe_candidate_path")
    if value.startswith("/") or any(segment in {"", ".."} for segment in value.split("/")):
        raise ValueError("unsafe_candidate_path")
    return value


def _read_changes(path: Path | None) -> set[str]:
    if path is None:
        return set()
    entries = path.read_text(encoding="utf-8").splitlines()
    return {_safe_path(entry) for entry in entries if entry}


def classify(path: str) -> str:
    if path.startswith(".github/") or path.startswith(".pre-commit"):
        return "ci_or_configuration"
    if path.startswith("docs/") or path.endswith(".md") or path.endswith(".txt"):
        return "documentation"
    if path.startswith("tests/") or "/tests/" in path or path.startswith("test_"):
        return "test_code"
    return "runtime_or_tooling"


def summarize(data: object, changed: set[str]) -> dict:
    if not isinstance(data, dict) or data.get("scanner") != "detect-secrets":
        raise ValueError("untrusted_scan_format")
    if data.get("exit_code") not in (0, 1, 2, 3):
        raise ValueError("missing_authoritative_scan_exit")
    findings = data.get("findings")
    if not isinstance(findings, list):
        raise ValueError("invalid_findings")
    reviewed = []
    for item in findings:
        if not isinstance(item, dict):
            raise ValueError("invalid_finding")
        path = _safe_path(item.get("path"))
        detector = item.get("type")
        line = item.get("line")
        if detector not in KNOWN_TYPES or type(line) is not int or line < 1:
            raise ValueError("invalid_finding_metadata")
        reviewed.append({"path": path, "line": line, "type": detector})
    if data["exit_code"] == 0 and reviewed:
        raise ValueError("scanner_status_conflicts_with_findings")
    changed_hits = [item for item in reviewed if item["path"] in changed]
    priority = [item for item in reviewed if item["type"] in {"Private Key", "Basic Auth Credentials"}]
    return {
        "certification": "BLOCKED" if data["exit_code"] or reviewed else "SCANNER_CLEAN_ONLY",
        "baseline_changed": bool(data.get("baseline_would_change", False)),
        "scanner_exit_code": data["exit_code"],
        "scanned_commit": data.get("checked_out_commit")
        if re.fullmatch(r"[0-9a-f]{40}", str(data.get("checked_out_commit"))) else None,
        "candidate_count": len(reviewed),
        "affected_file_count": len({x["path"] for x in reviewed}),
        "changed_file_count": len(changed),
        "changed_file_candidate_count": len(changed_hits),
        "category_counts": dict(sorted(Counter(x["type"] for x in reviewed).items())),
        "location_group_counts": dict(sorted(Counter(classify(x["path"]) for x in reviewed).items())),
        "priority_candidate_count": len(priority),
        "priority_review_coordinates": sorted(
            priority, key=lambda x: (x["path"], x["line"], x["type"])
        ),
        "requires_independent_review": True,
        "production_pipeline_certified": False,
        "changed_file_scan_not_a_waiver": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--changed-paths", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        data = json.loads(args.report.read_text(encoding="utf-8"))
        result = summarize(data, _read_changes(args.changed_paths))
        payload = json.dumps(result, indent=2, sort_keys=True) + "\n"
        if args.output:
            args.output.write_text(payload, encoding="utf-8")
        else:
            sys.stdout.write(payload)
        # Preserve any scanner failure: diagnostic reporting cannot clear a gate.
        return 1 if result["certification"] == "BLOCKED" else 0
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        print("triage_failed_closed", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
