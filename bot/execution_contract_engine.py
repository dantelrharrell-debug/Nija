"""Strategy and execution-engine enforcement for NIJA's final contract."""
from __future__ import annotations

import logging
from functools import wraps
from types import ModuleType
from typing import Any

from .execution_contract_primitives import (
    LAST_ACK, MARKER, broker_from_object, broker_name, extract_order_id,
    minimum_notional, number, venue_cash,
)

logger = logging.getLogger("nija.execution_contract_engine")


def patch_apex(module: ModuleType) -> bool:
    cls = getattr(module, "NIJAApexStrategyV71", None)
    current = getattr(cls, "execute_action", None) if isinstance(cls, type) else None
    if not callable(current) or getattr(current, "_nija_apex_contract_20260710a", False):
        return False
    @wraps(current)
    def execute_action(self: Any, payload: Any, symbol: str, *args: Any, **kwargs: Any):
        if not isinstance(payload, dict) or str(payload.get("action") or "").lower() not in {"enter_long", "enter_short", "buy", "sell"}:
            return current(self, payload, symbol, *args, **kwargs)
        client = getattr(self, "broker_client", None) or getattr(self, "broker", None)
        broker = broker_from_object(client)
        engine = getattr(self, "execution_engine", None)
        if client is not None and engine is not None:
            engine.broker_client = client
            engine._nija_bound_route_broker = broker
        out, size = dict(payload), number(payload.get("position_size"))
        meta = dict(out.get("metadata") or {}) if isinstance(out.get("metadata"), dict) else {}
        meta.update({"execution_broker": broker, "dispatch_broker": broker, "balance_broker": broker, "symbol_broker": broker, "canonical_order_notional_usd": size, "execution_contract_marker": MARKER})
        out.update({"metadata": meta, "broker_selected": broker, "preferred_broker": broker, "execution_broker": broker, "broker": broker, "intended_broker": broker, "order_notional": size, "capital_allocated": size, "final_order_notional": size, "raw_size": size, "final_size": size, "min_notional": minimum_notional(broker)})
        if size >= minimum_notional(broker) and (str(out.get("filter_stage") or "").lower() == "min_notional" or "broker_min_notional_block" in str(out.get("reason") or "").lower()):
            out.update({"filter_stage": "canonical_order_ready", "reason": "canonical_order_notional_resolved", "reason_code": "canonical_order_notional_resolved"})
        return current(self, out, symbol, *args, **kwargs)
    execute_action._nija_apex_contract_20260710a = True
    cls.execute_action = execute_action
    return True


def patch_engine(module: ModuleType) -> bool:
    cls = getattr(module, "ExecutionEngine", None)
    if not isinstance(cls, type):
        return False
    changed = False
    entry = getattr(cls, "execute_entry", None)
    if callable(entry) and not getattr(entry, "_nija_entry_contract_20260710a", False):
        @wraps(entry)
        def execute_entry(self: Any, symbol: str, side: str, size: float, price: float, stop: float, levels: Any, *args: Any, **kwargs: Any):
            levels = dict(levels or {})
            actual, intended = broker_from_object(getattr(self, "broker_client", None)), broker_name(levels.get("intended_broker"))
            if actual and (not intended or (actual != intended and broker_name(getattr(self, "_nija_bound_route_broker", "")) == actual)):
                levels["intended_broker"] = actual
            levels.update({"canonical_order_notional_usd": number(size), "execution_contract_marker": MARKER})
            return entry(self, symbol, side, size, price, stop, levels, *args, **kwargs)
        execute_entry._nija_entry_contract_20260710a = True
        cls.execute_entry = execute_entry
        changed = True

    submit = getattr(cls, "_submit_market_order_via_pipeline", None)
    if callable(submit) and not getattr(submit, "_nija_submit_contract_20260710a", False):
        @wraps(submit)
        def submit_order(self: Any, client: Any, symbol: str, side: str, size: float, *args: Any, **kwargs: Any):
            actual, selected = broker_from_object(client), broker_name(kwargs.get("preferred_broker"))
            if actual and selected and actual != selected:
                return {"status": "error", "error": f"execution_route_object_mismatch:selected={selected}:broker_client={actual}", "symbol": symbol, "side": side, "broker": selected}
            if actual:
                kwargs["preferred_broker"] = actual
            cash, canonical, floor = venue_cash(client), number(size), minimum_notional(actual or selected)
            if canonical < floor and cash is not None and cash >= floor * 1.02:
                canonical = floor
            if cash is not None:
                kwargs["available_balance_usd"] = cash
            LAST_ACK.set(None)
            recorder = getattr(self, "record_trade_execution", None)
            had_instance = "record_trade_execution" in getattr(self, "__dict__", {})
            prior = getattr(self, "__dict__", {}).get("record_trade_execution")
            deferred: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
            if callable(recorder):
                setattr(self, "record_trade_execution", lambda *a, **k: deferred.append((a, dict(k))))
            try:
                result = submit(self, client, symbol, side, canonical, *args, **kwargs)
            finally:
                if callable(recorder):
                    try:
                        setattr(self, "record_trade_execution", prior) if had_instance else delattr(self, "record_trade_execution")
                    except Exception:
                        pass
            ack = LAST_ACK.get() or {}; LAST_ACK.set(None)
            status = str(result.get("status") if isinstance(result, dict) else getattr(result, "status", "") or "").lower()
            if status != "filled":
                return result
            order_id, ack_broker = extract_order_id(ack.get("order_id")), broker_name(ack.get("broker"))
            fill_price, filled_size = number(ack.get("fill_price")), number(ack.get("filled_size_usd"))
            if not order_id or (actual and ack_broker and actual != ack_broker) or fill_price <= 0 or filled_size <= 0:
                return {"status": "error", "error": "broker_ack_not_verified_at_engine_boundary", "symbol": symbol, "side": side, "broker": actual or selected}
            if isinstance(result, dict):
                result.update({"order_id": order_id, "broker": ack_broker or actual or selected, "filled_price": fill_price, "filled_size_usd": filled_size})
            if callable(recorder):
                for record_args, record_kwargs in deferred:
                    record_kwargs.update({"order_id": order_id, "broker": ack_broker or actual or selected, "fill_price": fill_price, "fill_amount_usd": filled_size})
                    recorder(*record_args, **record_kwargs)
            logger.critical("ENGINE_BROKER_ACK_COMMITTED marker=%s symbol=%s broker=%s order_id=%s", MARKER, symbol, ack_broker or actual or selected, order_id)
            return result
        submit_order._nija_submit_contract_20260710a = True
        cls._submit_market_order_via_pipeline = submit_order
        changed = True
    return changed
