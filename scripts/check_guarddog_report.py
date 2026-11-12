"""Require complete pinned GuardDog coverage; export identifiers, never payloads."""
from __future__ import annotations

import json
from pathlib import Path
import re
import sys

NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
RULE = re.compile(r"[a-z][a-z0-9_-]{0,127}\Z")
PIN = re.compile(r"([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[A-Za-z0-9_,.-]+\])?"
                 r"==([A-Za-z0-9][A-Za-z0-9.!+_-]*)\Z")


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def _name(value):
    if not isinstance(value, str) or not NAME.fullmatch(value):
        raise ValueError("invalid_package_name")
    return re.sub(r"[-_.]+", "-", value).lower()


def required_packages(path: Path) -> dict[str, str]:
    """Read only unconditional exact pins; unsupported syntax denies coverage."""
    expected = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        match = PIN.fullmatch(line)
        if not match:
            raise ValueError("unsupported_requirement")
        name, version = _name(match[1]), match[2]
        if name in expected:
            raise ValueError("duplicate_requirement")
        expected[name] = version
    if not expected:
        raise ValueError("empty_requirements")
    return expected


def check_report(path: Path, scanner_status: int, requirements: Path) -> int:
    """Deny missing/wrong packages, findings, scanner errors and malformed data."""
    try:
        if type(scanner_status) is not int or not 0 <= scanner_status <= 255:
            raise ValueError("invalid_status")
        expected = required_packages(requirements)
        if path.stat().st_size > 16 * 1024 * 1024:
            raise ValueError("oversized_report")
        rows = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique)
        if not isinstance(rows, list) or not rows:
            raise ValueError("missing_package_results")
        issues = errors = 0
        observed = set()
        summaries = []
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("invalid_package_result")
            name = _name(row.get("dependency"))
            if (name in observed or name not in expected
                    or row.get("version") != expected[name]):
                raise ValueError("unexpected_package_or_version")
            observed.add(name)
            result = row.get("result")
            if not isinstance(result, dict):
                raise ValueError("invalid_package_result")
            count, failures = result.get("issues"), result.get("errors")
            rules, risks = result.get("results"), result.get("risks", [])
            if (type(count) is not int or count < 0 or not isinstance(failures, dict)
                    or not isinstance(rules, dict) or not isinstance(risks, list)
                    or any(not isinstance(key, str) or not RULE.fullmatch(key) for key in rules)
                    or any(value is not None and type(value) not in (str, list, dict)
                           for value in rules.values())):
                raise ValueError("invalid_package_summary")
            active = sorted(key for key, value in rules.items() if value)
            # Never let an inconsistent zero count conceal actual rule findings.
            if not count and (active or risks):
                raise ValueError("inconsistent_package_summary")
            issues += count
            errors += len(failures)
            if count or failures:
                summaries.append((name, count, len(failures), active))
        if observed != set(expected):
            raise ValueError("incomplete_package_coverage")
    except (OSError, ValueError, TypeError, RecursionError):
        print("GuardDog: missing, incomplete or invalid report; scan denied.")
        return scanner_status if type(scanner_status) is int and 0 < scanner_status <= 255 else 2
    print(f"GuardDog: packages={len(rows)} findings={issues} "
          f"error_entries={errors} scanner_exit={scanner_status}")
    for name, count, failures, active in summaries:
        print(f"GuardDog package={name} findings={count} error_entries={failures} "
              f"rules={','.join(active)}")
    if scanner_status:
        return scanner_status
    return 1 if issues else 2 if errors else 0


if __name__ == "__main__":
    if len(sys.argv) != 4 or not sys.argv[2].isdigit():
        print("GuardDog: report path, scanner status and requirements required; scan denied.")
        raise SystemExit(2)
    raise SystemExit(check_report(Path(sys.argv[1]), int(sys.argv[2]), Path(sys.argv[3])))
