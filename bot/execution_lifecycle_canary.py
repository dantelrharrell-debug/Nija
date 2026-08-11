"""Deterministic, non-live entry/fill/exit/reconciliation canary.

The canary is safe to run during production startup because it refuses any
broker that is not explicitly marked simulated.  Its purpose is to prove the
order/fill lifecycle contract before live dispatch is enabled; it never claims
that a strategy will be profitable and never sends an exchange order.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass(frozen=True)
class LifecycleCanaryResult:
    """Result of one simulated round-trip lifecycle."""

    passed: bool
    first_blocker: str
    entry_order_id: str = ""
    exit_order_id: str = ""
    filled_base_size: float = 0.0
    final_position_size: float = 0.0


def _payload_order_id(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    order = payload.get("order") if isinstance(payload.get("order"), dict) else {}
    return str(
        payload.get("order_id")
        or payload.get("id")
        or order.get("order_id")
        or order.get("id")
        or ""
    )


def _filled(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    status = str(payload.get("status") or payload.get("state") or "").lower()
    return status in {"filled", "closed", "done", "complete", "completed"}


def _filled_base(payload: Any) -> float:
    if not isinstance(payload, dict):
        return 0.0
    order = payload.get("order") if isinstance(payload.get("order"), dict) else {}
    for source in (payload, order):
        for key in ("filled_base_size", "filled_qty", "filled_quantity", "base_size"):
            try:
                value = float(source.get(key) or 0.0)
            except (TypeError, ValueError):
                value = 0.0
            if value > 0.0:
                return value
    return 0.0


def run_simulated_trade_lifecycle(
    broker: Any,
    *,
    symbol: str = "BTC-USD",
    entry_quote_size: float = 10.0,
) -> LifecycleCanaryResult:
    """Run a filled entry and exit against an explicitly simulated broker."""

    if not bool(
        getattr(broker, "is_simulated", False)
        or getattr(broker, "paper_mode", False)
    ):
        return LifecycleCanaryResult(False, "live_broker_canary_forbidden")
    submit = getattr(broker, "place_market_order", None)
    if not callable(submit):
        return LifecycleCanaryResult(False, "terminal_order_route_missing")

    try:
        entry = submit(symbol, "buy", float(entry_quote_size), size_type="quote")
    except Exception:
        return LifecycleCanaryResult(False, "entry_submit_exception")
    if not _filled(entry):
        return LifecycleCanaryResult(False, "entry_not_filled")
    base_size = _filled_base(entry)
    if base_size <= 0.0:
        return LifecycleCanaryResult(False, "entry_fill_size_missing")

    try:
        exit_order = submit(symbol, "sell", base_size, size_type="base")
    except Exception:
        return LifecycleCanaryResult(False, "exit_submit_exception")
    if not _filled(exit_order):
        return LifecycleCanaryResult(False, "exit_not_filled")

    final_position = float(getattr(broker, "position_size", 0.0) or 0.0)
    if abs(final_position) > 1e-12:
        return LifecycleCanaryResult(
            False,
            "position_reconciliation_nonzero",
            entry_order_id=_payload_order_id(entry),
            exit_order_id=_payload_order_id(exit_order),
            filled_base_size=base_size,
            final_position_size=final_position,
        )
    return LifecycleCanaryResult(
        True,
        "none",
        entry_order_id=_payload_order_id(entry),
        exit_order_id=_payload_order_id(exit_order),
        filled_base_size=base_size,
        final_position_size=final_position,
    )


class _BuiltinCanaryBroker:
    is_simulated = True

    def __init__(self) -> None:
        self.position_size = 0.0
        self._orders: List[Dict[str, Any]] = []

    def place_market_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        *,
        size_type: str,
    ) -> Dict[str, Any]:
        price = 100.0
        if side.lower() == "buy" and size_type == "quote":
            filled_base = float(quantity) / price
            self.position_size += filled_base
        elif side.lower() == "sell" and size_type == "base":
            filled_base = float(quantity)
            self.position_size = max(0.0, self.position_size - filled_base)
        else:
            return {"status": "rejected", "reason": "unsupported_canary_order"}
        order_id = f"canary-{len(self._orders) + 1}"
        payload = {
            "status": "filled",
            "order_id": order_id,
            "symbol": symbol,
            "side": side,
            "filled_base_size": filled_base,
            "fill_price": price,
        }
        self._orders.append(payload)
        return payload


def run_builtin_execution_lifecycle_canary() -> LifecycleCanaryResult:
    """Run the production-safe in-memory lifecycle canary."""

    return run_simulated_trade_lifecycle(_BuiltinCanaryBroker())


__all__ = [
    "LifecycleCanaryResult",
    "run_builtin_execution_lifecycle_canary",
    "run_simulated_trade_lifecycle",
]
