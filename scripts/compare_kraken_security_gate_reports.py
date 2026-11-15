#!/usr/bin/env python3
"""Compare redacted security gate reports without relaxing any blocking scan."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

_ALLOWED_OUTCOMES = {"clean", "unbaselined_candidates", "baseline_refresh_required", "scanner_error"}
_ALLOWED_HOOK_OUTCOMES = {"passed", "failed", "runner_error"}


def _load(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("report_must_be_object")
    return data


def compare(base_secret: dict, head_secret: dict, base_hooks: dict, head_hooks: dict) -> dict:
    """Classify report deltas; never interpret historical failures as approved."""
    for report in (base_secret, head_secret):
        if report.get("scanner") != "detect-secrets" or report.get("outcome") not in _ALLOWED_OUTCOMES:
            raise ValueError("invalid_secret_report")
        if not isinstance(report.get("findings"), list):
            raise ValueError("missing_secret_findings")
    for report in (base_hooks, head_hooks):
        if report.get("outcome") not in _ALLOWED_HOOK_OUTCOMES:
            raise ValueError("invalid_hook_report")
        if not isinstance(report.get("failed_hooks"), list):
            raise ValueError("missing_hook_findings")

    def fingerprints(report: dict) -> Counter:
        result = Counter()
        for item in report["findings"]:
            if not isinstance(item, dict) or not isinstance(item.get("path"), str) or not isinstance(item.get("type"), str):
                raise ValueError("invalid_finding")
            # Aggregate by path and detector, not line: source edits can move lines.
            result[(item["path"], item["type"])] += 1
        return result

    old = fingerprints(base_secret)
    new = fingerprints(head_secret)
    added = new - old
    removed = old - new
    old_hooks = base_hooks["failed_hooks"]
    new_hooks = head_hooks["failed_hooks"]
    if any(not isinstance(x, str) for x in old_hooks + new_hooks):
        raise ValueError("invalid_hook_name")
    return {
        "schema_version": 1,
        "comparison_is_diagnostic_only": True,
        "secret_gate_still_required": True,
        "precommit_gate_still_required": True,
        "base_secret_outcome": base_secret["outcome"],
        "head_secret_outcome": head_secret["outcome"],
        "base_candidate_count": sum(old.values()),
        "head_candidate_count": sum(new.values()),
        "new_candidate_count": sum(added.values()),
        "resolved_candidate_count": sum(removed.values()),
        "new_candidate_locations": [
            {"path": path, "detector": detector, "count": count}
            for (path, detector), count in sorted(added.items())
        ],
        "newly_failing_hooks": sorted(set(new_hooks) - set(old_hooks)),
        "previously_failing_hooks": sorted(set(old_hooks) & set(new_hooks)),
        "resolved_hooks": sorted(set(old_hooks) - set(new_hooks)),
        "head_is_certified": head_secret["outcome"] == "clean" and head_hooks["outcome"] == "passed",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-secret", type=Path, required=True)
    parser.add_argument("--head-secret", type=Path, required=True)
    parser.add_argument("--base-hooks", type=Path, required=True)
    parser.add_argument("--head-hooks", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = compare(*(_load(path) for path in (
            args.base_secret, args.head_secret, args.base_hooks, args.head_hooks
        )))
    except (ValueError, OSError, json.JSONDecodeError):
        print("Security report comparison failed closed: missing or invalid input")
        return 2
    args.report.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print("Security report comparison written; original gates remain authoritative")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
