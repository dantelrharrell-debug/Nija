"""Bounded read-only Kraken historical evidence collection.

Requires an already authenticated account-scoped private API callable supplied by
the operator's trusted runtime. Never instantiates credentials or places orders.
Results are evidence for independent reconciliation, NOT trading authorization.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from collections.abc import Callable, Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

ENDPOINTS = (("TradesHistory", "trades"), ("ClosedOrders", "closed"), ("Ledgers", "ledger"))
PAGE_SIZE = 50


class IncompleteHistory(RuntimeError):
    """Stop rather than silently certify a partial account history."""


def history_failure_diagnostic(exc: BaseException) -> dict[str, str]:
    """Return fixed labels for known failures without serializing broker data."""
    if type(exc) is not IncompleteHistory:
        return {}
    reasons = {
        "API failure": "api_failure",
        "malformed result": "malformed_result",
        "invalid amount": "invalid_amount",
        "invalid asset or amount": "invalid_balance",
        "invalid count": "invalid_count",
        "oversized page": "oversized_page",
        "count changed during pagination": "pagination_count_changed",
        "invalid record": "invalid_record",
        "duplicate identifier across pages": "duplicate_record",
        "non-JSON record": "non_json_record",
        "incomplete empty page": "empty_page_before_completion",
        "page limit before all records": "page_limit",
        "expected count mismatch": "record_count_mismatch",
        "invalid cursor": "invalid_cursor",
        "repeated cursor": "repeated_cursor",
        "invalid observation clock": "invalid_observation_clock",
    }
    if len(exc.args) != 1 or type(exc.args[0]) is not str:
        return {"error_code": "history_incomplete_unknown"}
    message = exc.args[0]
    for endpoint in ("Balance", "TradesHistory", "ClosedOrders", "Ledgers", "OpenOrders"):
        for suffix, reason in reasons.items():
            if message == f"{endpoint}: {suffix}":
                return {"error_code": reason, "error_endpoint": endpoint}
    if message == "history changed between verification passes":
        return {"error_code": "repeat_history_changed", "error_endpoint": "history"}
    if message == "balance changed during history collection":
        return {"error_code": "balance_changed", "error_endpoint": "Balance"}
    if message == "open orders changed between verification passes":
        return {"error_code": "open_orders_changed", "error_endpoint": "OpenOrders"}
    return {"error_code": "history_incomplete_unknown"}


def collect_history(
    private_read: Callable[[str, dict[str, Any]], Mapping[str, Any]],
    *,
    account_scope: str,
    max_pages: int = 200,
    include_balance: bool = False,
    include_open_orders: bool = False,
) -> dict[str, Any]:
    """Collect repeat-checked history, optionally bracketed by private balances."""
    if not (account_scope == "platform:kraken" or (
        account_scope.startswith("user:")
        and account_scope.endswith(":kraken")
        and len(account_scope.split(":")) == 3
        and bool(account_scope.split(":")[1])
    )):
        raise ValueError("Explicit Kraken account scope required")
    if not callable(private_read) or type(max_pages) is not int or not 1 <= max_pages <= 1000:
        raise ValueError("Trusted read callable and bounded max_pages required")

    def read_open_orders() -> tuple[dict[str, Any], dict[str, float]]:
        """Read every cursor page without account, symbol or client-ID filters.

        Request-start time is a conservative observation bound, not broker event
        time. Re-reading unchanged rows must never refresh historical fill times.
        """
        records: dict[str, Any] = {}
        seen_cursors: set[str] = set()
        params: dict[str, Any] = {"with_cursor": True, "limit": PAGE_SIZE, "trades": True}
        started = time.time()
        previous = started
        for _ in range(max_pages):
            payload = private_read("OpenOrders", params)
            finished = time.time()
            if not all(math.isfinite(x) and x > 0 for x in (started, finished)) or finished < previous:
                raise IncompleteHistory("OpenOrders: invalid observation clock")
            previous = finished
            if not isinstance(payload, Mapping) or payload.get("error") != []:
                raise IncompleteHistory("OpenOrders: API failure")
            result = payload.get("result")
            if not isinstance(result, Mapping) or not isinstance(result.get("open"), Mapping):
                raise IncompleteHistory("OpenOrders: malformed result")
            batch = result["open"]
            if len(batch) > PAGE_SIZE:
                raise IncompleteHistory("OpenOrders: oversized page")
            for identifier, row in batch.items():
                if not isinstance(identifier, str) or not identifier or not isinstance(row, Mapping):
                    raise IncompleteHistory("OpenOrders: invalid record")
                if identifier in records:
                    raise IncompleteHistory("OpenOrders: duplicate identifier across pages")
                try:
                    records[identifier] = json.loads(
                        json.dumps(dict(row), sort_keys=True, separators=(",", ":"), allow_nan=False)
                    )
                except (TypeError, ValueError) as exc:
                    raise IncompleteHistory("OpenOrders: non-JSON record") from exc
            cursor = result.get("cursor", {})
            if not isinstance(cursor, Mapping):
                raise IncompleteHistory("OpenOrders: invalid cursor")
            next_cursor = cursor.get("next")
            if next_cursor is None or next_cursor == "":
                return records, {"request_started_at": started, "response_finished_at": finished}
            if not isinstance(next_cursor, str) or not next_cursor.strip():
                raise IncompleteHistory("OpenOrders: invalid cursor")
            if next_cursor in seen_cursors:
                raise IncompleteHistory("OpenOrders: repeated cursor")
            if not batch:
                raise IncompleteHistory("OpenOrders: incomplete empty page")
            seen_cursors.add(next_cursor)
            params = {**params, "cursor": next_cursor}
        raise IncompleteHistory("OpenOrders: page limit before all records")

    def read_balance() -> dict[str, str]:
        payload = private_read("Balance", {})
        if not isinstance(payload, Mapping) or payload.get("error"):
            raise IncompleteHistory("Balance: API failure")
        result = payload.get("result")
        if not isinstance(result, Mapping):
            raise IncompleteHistory("Balance: malformed result")
        balances: dict[str, str] = {}
        for asset, value in result.items():
            try:
                amount = Decimal(str(value))
            except (InvalidOperation, TypeError, ValueError) as exc:
                raise IncompleteHistory("Balance: invalid amount") from exc
            if not isinstance(asset, str) or not asset or not amount.is_finite() or amount < 0:
                raise IncompleteHistory("Balance: invalid asset or amount")
            balances[asset] = str(amount)
        return balances

    def read_all_endpoints() -> dict[str, dict[str, Any]]:
        """Collect one bounded pass without assuming Kraken provides an atomic snapshot."""
        output: dict[str, dict[str, Any]] = {}
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
                if len(batch) > PAGE_SIZE:
                    raise IncompleteHistory(f"{endpoint}: oversized page")
                if expected is None:
                    expected = count
                    # Reject an insufficient operator budget before exhausting
                    # the shared, rate-limited private history API allowance.
                    if expected > max_pages * PAGE_SIZE:
                        raise IncompleteHistory(f"{endpoint}: page limit before all records")
                elif count != expected:
                    raise IncompleteHistory(f"{endpoint}: count changed during pagination")
                for identifier, row in batch.items():
                    if not isinstance(identifier, str) or not identifier or not isinstance(row, Mapping):
                        raise IncompleteHistory(f"{endpoint}: invalid record")
                    if identifier in records:
                        raise IncompleteHistory(f"{endpoint}: duplicate identifier across pages")
                    # Freeze broker response objects: do not trust later mutation of a
                    # nested mapping to silently change already-collected evidence.
                    try:
                        records[identifier] = json.loads(
                            json.dumps(dict(row), sort_keys=True, separators=(",", ":"), allow_nan=False)
                        )
                    except (TypeError, ValueError) as exc:
                        raise IncompleteHistory(f"{endpoint}: non-JSON record") from exc
                if len(records) >= expected:
                    break
                if not batch:
                    raise IncompleteHistory(f"{endpoint}: incomplete empty page")
            else:
                raise IncompleteHistory(f"{endpoint}: page limit before all records")
            if len(records) != expected:
                raise IncompleteHistory(f"{endpoint}: expected count mismatch")
            output[field] = records
        return output

    # Offset pagination is not a broker-provided atomic snapshot. A second full
    # read catches a stable count with changed IDs or changed row contents.
    # This reduces inconsistent evidence; it does not prove absence of ABA churn.
    balance = read_balance() if include_balance else None
    collected = read_all_endpoints()
    if read_all_endpoints() != collected:
        raise IncompleteHistory("history changed between verification passes")
    # Capture current orders after potentially long historical reads. Keep both
    # observation intervals; report assembly is not a new observation.
    open_orders = None
    if include_open_orders:
        open_orders, first_observation = read_open_orders()
        repeated_orders, second_observation = read_open_orders()
        if second_observation["request_started_at"] < first_observation["response_finished_at"]:
            raise IncompleteHistory("OpenOrders: invalid observation clock")
        if repeated_orders != open_orders:
            raise IncompleteHistory("open orders changed between verification passes")
    if include_balance and read_balance() != balance:
        raise IncompleteHistory("balance changed during history collection")
    envelope = {"account_scope_asserted_by_caller": account_scope, "history": collected}
    if include_balance:
        envelope["balance"] = balance
    if include_open_orders:
        envelope["open_orders"] = open_orders
        envelope["open_orders_observations"] = [first_observation, second_observation]
    canonical = json.dumps(envelope, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return {
        **envelope,
        "repeat_read_consistent": True,
        "atomic_broker_snapshot_verified": False,
        "evidence_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "authenticated_identity_independently_verified": False,
        "ledger_links_verified": False,
        "protective_exit_coverage_verified": False,
        "entry_exit_reconciliation_verified": False,
        "trading_authorized": False,
        "side_effects": "read_only_api_calls",
    }

def _broker_account_scope(broker: Any) -> str:
    """Resolve software routing metadata, not authenticated brokerage ownership."""
    broker_type = getattr(broker, "broker_type", None)
    account_type = getattr(broker, "account_type", None)
    broker_type = getattr(broker_type, "value", broker_type)
    account_type = getattr(account_type, "value", account_type)
    user_id = getattr(broker, "user_id", object())
    if broker_type == "kraken":
        if account_type == "platform" and user_id is None:
            return "platform:kraken"
        if (account_type == "user" and isinstance(user_id, str)
                and user_id and user_id == user_id.strip() and ":" not in user_id):
            return f"user:{user_id}:kraken"
    raise ValueError("Unambiguous Kraken broker account metadata required")


def collect_from_existing_broker(broker: Any, *, account_scope: str,
                                 monitoring_category: Any, max_pages: int = 200,
                                 include_balance: bool = False,
                                 include_open_orders: bool = False) -> dict[str, Any]:
    """Reuse Kraken read controls without relabeling another software account."""
    def require_matching_scope() -> None:
        if _broker_account_scope(broker) != account_scope:
            raise ValueError("Requested scope does not match selected Kraken broker")

    require_matching_scope()
    private_call = getattr(broker, "_kraken_private_call", None)
    if not callable(private_call) or monitoring_category is None:
        raise ValueError("Authenticated private call and monitoring category required")

    def read(endpoint: str, params: dict[str, Any]) -> Mapping[str, Any]:
        history_read = endpoint in {"TradesHistory", "ClosedOrders", "Ledgers"} and set(params) == {"ofs"}
        balance_read = include_balance and endpoint == "Balance" and not params
        open_orders_read = (
            include_open_orders and endpoint == "OpenOrders"
            and set(params) in ({"with_cursor", "limit", "trades"}, {"with_cursor", "limit", "trades", "cursor"})
            and params.get("with_cursor") is True and params.get("trades") is True
            and type(params.get("limit")) is int and params["limit"] == PAGE_SIZE
            and ("cursor" not in params or isinstance(params["cursor"], str) and bool(params["cursor"].strip()))
        )
        if not (history_read or balance_read or open_orders_read):
            raise ValueError("Non-read-only request rejected")
        require_matching_scope()
        payload = private_call(endpoint, params, category=monitoring_category)
        require_matching_scope()
        return payload

    return collect_history(
        read, account_scope=account_scope, max_pages=max_pages, include_balance=include_balance,
        include_open_orders=include_open_orders,
    )
