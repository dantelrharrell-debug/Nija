"""One bounded private inventory observation on the selected live broker."""
import json
import math
import time
from typing import Any

from bot.kraken_authenticated_balance_provider import _snapshot_digest
from scripts.nija_kraken_readonly_history_collector_v441 import PAGE_SIZE, _broker_account_scope


class InventoryDenied(ValueError):
    """Fixed diagnostic reason safe to persist without exchange payloads."""


def read_current_inventory(broker: Any, monitoring_category: Any) -> dict:
    """Read balances, all unfiltered default-wallet open orders and unconsolidated positions.

    Preserve the exact responses and their individual observation intervals privately.
    Sequential reads do not prove atomicity, independent identity, or ledger ownership.
    """
    api = getattr(broker, "api", None)
    read = getattr(broker, "_kraken_private_call", None)

    def check_owner() -> None:
        if (api is None or not callable(read) or monitoring_category is None
                or broker.api is not api or broker._kraken_private_call != read
                or broker.connected is not True or _broker_account_scope(broker) != "platform:kraken"
                or getattr(broker, "_gateway_url", None) != ""
                or getattr(broker, "_gateway_only_mode", None) is not False):
            raise InventoryDenied("inventory_owner_changed")

    observations = {}
    previous = 0.0
    for endpoint, params in (
        ("BalanceEx", {}),
        ("OpenOrders", {}),
        ("OpenPositions", {}),
    ):
        check_owner()
        start = time.time()
        payload = read(endpoint, dict(params), category=monitoring_category)
        end = time.time()
        check_owner()
        if (not math.isfinite(end) or not 0 < start <= end or start < previous or not isinstance(payload, dict)
                or set(payload) != {"error", "result"} or payload["error"] != []
                or not isinstance(payload["result"], dict)):
            raise InventoryDenied("inventory_response_invalid")
        previous = end
        result = json.loads(json.dumps(payload["result"], allow_nan=False))
        if endpoint == "BalanceEx":
            _snapshot_digest(result)
        elif endpoint == "OpenOrders":
            # Without filters, a limit or cursor mode, Kraken returns all open orders.
            # A pagination marker on this request is unexpected; never discard it.
            if "cursor" in result:
                raise InventoryDenied("inventory_unexpected_pagination")
            if set(result) != {"open"} or not isinstance(result["open"], dict):
                raise InventoryDenied("inventory_open_orders_shape_invalid")
            if len(result["open"]) > PAGE_SIZE:
                raise InventoryDenied("inventory_order_budget_exceeded")
        if endpoint != "BalanceEx":
            rows = result["open"] if endpoint == "OpenOrders" else result
            if any(not key or not isinstance(row, dict) or not row for key, row in rows.items()):
                raise InventoryDenied("inventory_rows_invalid")
        observations[endpoint] = {"started_at": start, "finished_at": end, "result": result}
        if endpoint == "OpenOrders":
            observations[endpoint]["request_mode"] = "all_unfiltered_no_limit"
    return {"inventory_read_succeeded": True, "observations": observations}
