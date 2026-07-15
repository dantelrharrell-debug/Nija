"""Align approved Kraken TPE allocations with the executable broker minimum.

TradePermissionEngine historically defaulted approved trades to five percent of
account balance.  For small Kraken accounts this produced an EXECUTE decision
with a non-executable allocation (for example $11.71 against a $23.10 minimum),
forcing Phase 3 into its deliberately disabled fallback-entry path.

This patch changes only the approved allocation.  It never turns a blocked trade
into an executable trade and never bypasses downstream risk, writer authority,
position caps, broker validation, or exchange minimum checks.
"""
from __future__ import annotations

import logging
import os
from functools import wraps
from typing import Any

logger = logging.getLogger("nija.kraken_tpe_min_notional_allocation")
_MARKER = "20260715-kraken-tpe-min-notional-v1"
_PATCH_ATTR = "_nija_kraken_tpe_min_notional_v1"
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}


def _f(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
        return default if parsed != parsed else parsed
    except Exception:
        return default


def _truthy(name: str, default: str = "true") -> bool:
    return str(os.environ.get(name, default) or "").strip().lower() in _TRUE


def _is_kraken(value: Any) -> bool:
    return "kraken" in str(value or "").strip().lower()


def _entry_side(value: Any) -> bool:
    return str(value or "long").strip().lower() in {"buy", "long", "enter_long", "open_long"}


def _target_notional() -> float:
    values = (
        os.environ.get("NIJA_KRAKEN_TARGET_ORDER_USD"),
        os.environ.get("KRAKEN_TARGET_ORDER_USD"),
        os.environ.get("MIN_TRADE_USD"),
        os.environ.get("MIN_NOTIONAL_OVERRIDE"),
        os.environ.get("KRAKEN_MIN_NOTIONAL_USD"),
        os.environ.get("NIJA_KRAKEN_MIN_NOTIONAL_USD"),
    )
    return max(23.10, *(_f(value, 0.0) for value in values))


def _max_position_pct() -> float:
    values = (
        os.environ.get("NIJA_MAX_POSITION_SIZE_PCT"),
        os.environ.get("MAX_POSITION_PCT"),
        os.environ.get("MAX_POSITION_SIZE_PCT"),
    )
    parsed = [value for value in (_f(raw, 0.0) for raw in values) if value > 0.0]
    pct = min(parsed) if parsed else 0.50
    if pct > 1.0:
        pct /= 100.0
    return max(0.01, min(pct, 0.50))


def _lift_allowed(balance: float, target: float) -> tuple[bool, float]:
    cap = max(0.0, balance) * _max_position_pct()
    return balance >= target and target <= cap + 1e-9, cap


def patch_trade_permission_engine(module: Any) -> bool:
    cls = getattr(module, "TradePermissionEngine", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "evaluate", None)
    if not callable(original) or getattr(original, _PATCH_ATTR, False):
        return bool(getattr(original, _PATCH_ATTR, False))

    @wraps(original)
    def evaluate(self: Any, *args: Any, **kwargs: Any):
        decision = original(self, *args, **kwargs)
        if not _truthy("NIJA_KRAKEN_TPE_MIN_NOTIONAL_LIFT_ENABLED", "true"):
            return decision

        broker = kwargs.get("broker", getattr(decision, "broker", ""))
        side = kwargs.get("side", getattr(decision, "side", "long"))
        final = str(getattr(decision, "final_decision", "") or "").upper()
        risk_allowed = bool(getattr(decision, "risk_allowed", final == "EXECUTE"))
        balance = _f(kwargs.get("balance", getattr(decision, "capital_balance", 0.0)), 0.0)
        allocated = _f(getattr(decision, "capital_allocated", 0.0), 0.0)
        target = _target_notional()

        if final != "EXECUTE" or not risk_allowed or not _is_kraken(broker) or not _entry_side(side):
            return decision
        if allocated + 1e-9 >= target:
            return decision

        allowed, risk_cap = _lift_allowed(balance, target)
        if not allowed:
            logger.warning(
                "KRAKEN_TPE_MIN_NOTIONAL_LIFT_BLOCKED marker=%s symbol=%s balance=$%.2f allocated=$%.2f target=$%.2f risk_cap=$%.2f",
                _MARKER,
                getattr(decision, "symbol", kwargs.get("symbol", "UNKNOWN")),
                balance,
                allocated,
                target,
                risk_cap,
            )
            return decision

        decision.capital_allocated = target
        try:
            decision.risk_allowed = True
        except Exception:
            pass
        logger.critical(
            "KRAKEN_TPE_MIN_NOTIONAL_LIFT_APPLIED marker=%s symbol=%s balance=$%.2f old_allocation=$%.2f final_allocation=$%.2f risk_cap=$%.2f downstream_risk_recheck=true",
            _MARKER,
            getattr(decision, "symbol", kwargs.get("symbol", "UNKNOWN")),
            balance,
            allocated,
            target,
            risk_cap,
        )
        return decision

    setattr(evaluate, _PATCH_ATTR, True)
    setattr(evaluate, "__wrapped__", original)
    cls.evaluate = evaluate
    logger.warning("KRAKEN_TPE_MIN_NOTIONAL_ALLOCATION_PATCHED marker=%s target=$%.2f", _MARKER, _target_notional())
    return True


def install() -> bool:
    try:
        from bot import trade_permission_engine as module
    except Exception:
        import trade_permission_engine as module  # type: ignore
    os.environ.setdefault("NIJA_KRAKEN_TPE_MIN_NOTIONAL_LIFT_ENABLED", "true")
    result = patch_trade_permission_engine(module)
    os.environ["NIJA_KRAKEN_TPE_MIN_NOTIONAL_ALLOCATION_INSTALLED"] = "1" if result else "0"
    return result


install()

__all__ = ["install", "patch_trade_permission_engine", "_target_notional", "_max_position_pct"]
