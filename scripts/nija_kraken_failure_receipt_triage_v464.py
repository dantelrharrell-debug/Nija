#!/usr/bin/env python3
"""Read-only, redacted triage of a previously FAILED Kraken history receipt.

This offline/on-host operation reads ONLY the claimed request and its failed
receipt for one operator-selected request ID. It never touches a broker,
ledger, balances, orders, environment settings, or trading authority.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import re
import stat
from typing import Any

REQUEST_ID = re.compile(r"[a-f0-9]{32}\Z")
MAX_CLAIM_BYTES = 4096
MAX_RECEIPT_BYTES = 8192
ENDPOINTS = frozenset({"TradesHistory", "ClosedOrders", "Ledgers", "OpenOrders", "Balance"})
FAILURE_CODES = frozenset({
    "api_failure", "malformed_result", "invalid_amount", "invalid_balance",
    "invalid_count", "oversized_page", "pagination_count_changed",
    "invalid_record", "duplicate_record", "non_json_record",
    "empty_page_before_completion", "page_limit", "record_count_mismatch",
    "invalid_cursor", "repeated_cursor", "invalid_observation_clock",
    "repeat_history_changed", "balance_changed", "open_orders_changed",
    "history_incomplete_unknown",
})


class TriageFailure(ValueError):
    """A fixed redacted error; never render source JSON, filenames or exceptions."""


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise TriageFailure("duplicate_json_key")
        result[key] = value
    return result


def _nonfinite(_value: str) -> None:
    raise TriageFailure("nonfinite_json_value")


def _private_read(path: Path, limit: int) -> dict[str, Any]:
    if path.is_symlink():
        raise TriageFailure("unsafe_receipt_file")
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        raise TriageFailure("receipt_missing_or_unreadable") from None
    try:
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode)
                or before.st_uid != os.geteuid()
                or stat.S_IMODE(before.st_mode) & 0o077
                or before.st_nlink != 1
                or before.st_size < 1 or before.st_size > limit):
            raise TriageFailure("unsafe_receipt_file")
        raw = os.read(fd, limit + 1)
        after = os.fstat(fd)
        if (len(raw) != before.st_size or len(raw) > limit
                or before.st_dev != after.st_dev
                or before.st_ino != after.st_ino
                or before.st_size != after.st_size
                or before.st_mtime_ns != after.st_mtime_ns
                or before.st_ctime_ns != after.st_ctime_ns):
            raise TriageFailure("receipt_changed_or_oversized")
    finally:
        os.close(fd)
    try:
        data = json.loads(raw, object_pairs_hook=_unique_keys, parse_constant=_nonfinite)
    except TriageFailure:
        raise
    except (UnicodeDecodeError, ValueError, TypeError):
        raise TriageFailure("invalid_receipt_json") from None
    if not isinstance(data, dict):
        raise TriageFailure("invalid_receipt_schema")
    return data


def inspect_failure(root: Path, request_id: str) -> dict[str, Any]:
    """Validate exactly one existing private claim + failed receipt; no writes."""
    if not isinstance(request_id, str) or not REQUEST_ID.fullmatch(request_id):
        raise TriageFailure("invalid_request_id")
    if not root.is_absolute() or root.is_symlink():
        raise TriageFailure("unsafe_recovery_directory")
    try:
        if root.resolve(strict=True) != root:
            raise TriageFailure("unsafe_recovery_directory")
        info = root.stat()
    except (OSError, RuntimeError):
        raise TriageFailure("unsafe_recovery_directory") from None
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) & 0o077):
        raise TriageFailure("unsafe_recovery_directory")

    claim = _private_read(root / (request_id + ".claimed.json"), MAX_CLAIM_BYTES)
    receipt = _private_read(root / (request_id + ".evidence.json"), MAX_RECEIPT_BYTES)

    if (set(claim) != {"request_id", "account_scope", "created_at", "max_pages"}
            or claim["request_id"] != request_id
            or claim["account_scope"] != "platform:kraken"
            or type(claim["max_pages"]) is not int
            or not 1 <= claim["max_pages"] <= 100
            or type(claim["created_at"]) not in (int, float)
            or not math.isfinite(claim["created_at"])
            or claim["created_at"] <= 0):
        raise TriageFailure("claim_schema_or_scope_invalid")
    if (receipt.get("request_id") != request_id
            or receipt.get("collection_succeeded") is not False
            or receipt.get("trading_authorized") is not False):
        raise TriageFailure("receipt_identity_or_outcome_invalid")

    code = receipt.get("error_code")
    endpoint = receipt.get("error_endpoint")
    if (type(code) is not str or code not in FAILURE_CODES
            or (endpoint is not None and endpoint not in ENDPOINTS and endpoint != "history")):
        raise TriageFailure("receipt_failure_label_invalid")
    allowed = {"request_id", "collection_succeeded", "trading_authorized",
               "error_type", "error_code", "error_endpoint",
               "requested_pages", "required_pages"}
    if set(receipt) - allowed:
        raise TriageFailure("receipt_contains_unexpected_fields")

    result: dict[str, Any] = {
        "status": "FAILED_COLLECTION_TRIAGED",
        "account_scope": "platform_only",
        "failure_code": code,
        "failure_endpoint": endpoint if endpoint is not None else "unknown",
        "claimed_request_page_budget": claim["max_pages"],
        "broker_reads_performed_by_triage": False,
        "retries_performed": False,
        "ledger_writes_performed": False,
        "rate_budget_approved": False,
        "historical_fill_completeness_verified": False,
        "protective_exit_coverage_verified": False,
        "execution_authorized": False,
    }
    requested, required = receipt.get("requested_pages"), receipt.get("required_pages")
    if requested is None and required is None:
        result["complete_page_budget_known"] = False
    elif (code == "page_limit"
          and type(requested) is int and type(required) is int
          and requested == claim["max_pages"]
          and requested < required <= 10_000_000):
        result.update({"complete_page_budget_known": True,
                       "requested_pages": requested, "required_pages": required})
    else:
        raise TriageFailure("page_budget_claim_mismatch")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recovery-dir", type=Path, required=True)
    parser.add_argument("--request-id", required=True)
    args = parser.parse_args()
    try:
        output = inspect_failure(args.recovery_dir, args.request_id)
    except TriageFailure as exc:
        print(json.dumps({"status": "FAILED_CLOSED", "failure_code": str(exc),
                          "broker_reads_performed_by_triage": False,
                          "execution_authorized": False}, sort_keys=True))
        return 1
    except Exception:
        print(json.dumps({"status": "FAILED_CLOSED", "failure_code": "unexpected_failure",
                          "broker_reads_performed_by_triage": False,
                          "execution_authorized": False}, sort_keys=True))
        return 1
    print(json.dumps(output, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())