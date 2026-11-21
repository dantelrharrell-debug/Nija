"""One bounded private inventory observation on the selected live broker."""
import json
import math
import time
from typing import Any

from bot.kraken_authenticated_balance_provider import _snapshot_digest
from bot.kraken_cursor_read_wire_v490 import cursor_read_params
from scripts.nija_kraken_readonly_history_collector_v441 import PAGE_SIZE, _broker_account_scope


class InventoryDenied(ValueError):
    """Fixed diagnostic reason safe to persist without exchange payloads."""


def read_current_inventory(broker: Any, monitoring_category: Any) -> dict:
    """Read balances, a single exhausted open-order page and unconsolidated positions.

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
        ("OpenOrders", {"with_cursor": True, "limit": PAGE_SIZE, "trades": True}),
        ("OpenPositions", {}),
    ):
        check_owner()
        start = time.time()
        payload = read(endpoint, cursor_read_params(broker, endpoint, params), category=monitoring_category)
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
            cursor = result.get("cursor")
            if (set(result) != {"open", "cursor"} or not isinstance(cursor, dict)
                    or set(cursor) - {"next"} or cursor.get("next") not in (None, "")
                    or not isinstance(result["open"], dict) or len(result["open"]) > PAGE_SIZE):
                raise InventoryDenied("inventory_open_orders_incomplete")
        if endpoint != "BalanceEx":
            rows = result["open"] if endpoint == "OpenOrders" else result
            if any(not key or not isinstance(row, dict) or not row for key, row in rows.items()):
                raise InventoryDenied("inventory_rows_invalid")
        observations[endpoint] = {"started_at": start, "finished_at": end, "result": result}
    return {"inventory_read_succeeded": True, "observations": observations}
