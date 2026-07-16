"""Fail-closed guard for Kraken TPE allocations below the broker minimum.

A prior runtime repair lifted approved allocations to Kraken's executable minimum.
That could contradict an upstream strategy decision that had already logged SKIP
because its risk-sized position was smaller than the broker minimum. This version
never increases entry risk. It converts such contradictory EXECUTE decisions to
SKIP unless an operator explicitly enables the legacy lift behavior.
"""
from __future__ import annotations

import logging
import os
from functools import wraps
from typing import Any

logger = logging.getLogger("nija.kraken_tpe_min_notional_allocation")
_MARKER = "20260716-kraken-tpe-min-notional-v2"
_PATCH_ATTR = "_nija_kraken_tpe_min_notional_v2"
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}


def _f(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
        return default if parsed != parsed else parsed
    except Exception:
        return default


def _truthy(name: str, default: str = "false") -> bool:
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


def _set_skip(decision: Any, reason: str) -> Any:
    for attr, value in (
        ("final_decision", "SKIP"),
        ("decision", "SKIP"),
        ("risk_allowed", False),
        ("passed_gate", False),
        ("reason_blocked", reason),
        ("reason", reason),
        ("capital_allocated", 0.0),
    ):
        try:
            setattr(decision, attr, value)
        except Exception:
            pass
    return decision


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
        broker = kwargs.get("broker", getattr(decision, "broker", ""))
        side = kwargs.get("side", getattr(decision, "side", "long"))
        final = str(getattr(decision, "final_decision", getattr(decision, "decision", "")) or "").upper()
        risk_allowed = bool(getattr(decision, "risk_allowed", final == "EXECUTE"))
        allocated = _f(getattr(decision, "capital_allocated", 0.0), 0.0)
        target = _target_notional()
        symbol = getattr(decision, "symbol", kwargs.get("symbol", "UNKNOWN"))

        if final != "EXECUTE" or not risk_allowed or not _is_kraken(broker) or not _entry_side(side):
            return decision
        if allocated + 1e-9 >= target:
            return decision

        if _truthy("NIJA_KRAKEN_TPE_MIN_NOTIONAL_LIFT_ENABLED", "false"):
            logger.critical(
                "KRAKEN_TPE_MIN_NOTIONAL_LEGACY_LIFT_ALLOWED marker=%s symbol=%s old_allocation=$%.2f target=$%.2f operator_override=true",
                _MARKER, symbol, allocated, target,
            )
            try:
                decision.capital_allocated = target
            except Exception:
                pass
            return decision

        reason = f"kraken_risk_sized_allocation_below_minimum:allocated={allocated:.2f}:required={target:.2f}"
        logger.critical(
            "KRAKEN_TPE_MIN_NOTIONAL_FAIL_CLOSED marker=%s symbol=%s allocated=$%.2f required=$%.2f action=skip",
            _MARKER, symbol, allocated, target,
        )
        return _set_skip(decision, reason)

    setattr(evaluate, _PATCH_ATTR, True)
    setattr(evaluate, "__wrapped__", original)
    cls.evaluate = evaluate
    logger.warning("KRAKEN_TPE_MIN_NOTIONAL_FAIL_CLOSED_PATCHED marker=%s target=$%.2f", _MARKER, _target_notional())
    return True


def install() -> bool:
    try:
        from bot import trade_permission_engine as module
    except Exception:
        import trade_permission_engine as module  # type: ignore
    os.environ.setdefault("NIJA_KRAKEN_TPE_MIN_NOTIONAL_LIFT_ENABLED", "false")
    result = patch_trade_permission_engine(module)
    os.environ["NIJA_KRAKEN_TPE_MIN_NOTIONAL_ALLOCATION_INSTALLED"] = "1" if result else "0"
    return result


install()

__all__ = ["install", "patch_trade_permission_engine", "_target_notional"]