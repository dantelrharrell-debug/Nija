"""Bounded read-only Kraken historical evidence collection.

Requires an already authenticated account-scoped private API callable supplied by
the operator's trusted runtime. Never instantiates credentials or places orders.
Results are evidence for independent reconciliation, NOT trading authorization.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from typing import Any

ENDPOINTS = (("TradesHistory", "trades"), ("ClosedOrders", "closed"))
PAGE_SIZE = 50


class IncompleteHistory(RuntimeError):
    """Stop rather than silently certify a partial account history."""


def collect_history(
    private_read: Callable[[str, dict[str, Any]], Mapping[str, Any]],
    *,
    account_scope: str,
    max_pages: int = 200,
) -> dict[str, Any]:
    if not (account_scope == "platform:kraken" or (
        account_scope.startswith("user:")
        and account_scope.endswith(":kraken")
        and len(account_scope.split(":")) == 3
        and bool(account_scope.split(":")[1])
    )):
        raise ValueError("Explicit Kraken account scope required")
    if not callable(private_read) or not 1 <= max_pages <= 1000:
        raise ValueError("Trusted read callable and bounded max_pages required")

    collected: dict[str, dict[str, Any]] = {}
    for endpoint, field in ENDPOINTS:
        records: dict[str, Any] = {}
        expected: int | None = None
        for index in range(max_pages):
            payload = private_read(endpoint, {"ofs": index * PAGE_SIZE})
            if not isinstance(payload, Mapping) or payload.get("error"):
                raise IncompleteHistory(f"{endpoint}: API failure")
            result = payload.get("result")
            if not isinstance(result, Mapping) or not isinstance(result.get(field), Mapping):
                raise IncompleteHistory(f"{endpoint}: malformed result")
            batch = result[field]
            count = result.get("count")
            if not isinstance(count, int) or isinstance(count, bool) or count < 0:
                raise IncompleteHistory(f"{endpoint}: invalid count")
            if expected is None:
                expected = count
            elif count != expected:
                raise IncompleteHistory(f"{endpoint}: count changed during pagination")
            for identifier, row in batch.items():
                if not isinstance(identifier, str) or not identifier or not isinstance(row, Mapping):
                    raise IncompleteHistory(f"{endpoint}: invalid record")
                if identifier in records:
                    raise IncompleteHistory(f"{endpoint}: duplicate identifier across pages")
                records[identifier] = dict(row)
            if len(records) >= expected:
                break
            if not batch:
                raise IncompleteHistory(f"{endpoint}: incomplete empty page")
        else:
            raise IncompleteHistory(f"{endpoint}: page limit before all records")
        if len(records) != expected:
            raise IncompleteHistory(f"{endpoint}: expected count mismatch")
        collected[field] = records

    canonical = json.dumps(collected, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return {
        "account_scope_asserted_by_caller": account_scope,
        "history": collected,
        "evidence_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "authenticated_identity_independently_verified": False,
        "ledger_links_verified": False,
        "entry_exit_reconciliation_verified": False,
        "trading_authorized": False,
        "side_effects": "read_only_api_calls",
    }
