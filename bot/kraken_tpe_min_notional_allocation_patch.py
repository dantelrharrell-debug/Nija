"""Safely reconcile Kraken risk sizing with the executable venue minimum.

Kraken rejects entries below its effective minimum notional.  The strategy can
therefore approve a risk-sized allocation that can never be submitted.  This
repair lifts an approved entry only when the venue minimum remains inside the
configured account-level position cap and available balance.  Otherwise it
fails closed without bypassing risk controls.
"""
from __future__ import annotations

import logging
import os
from functools import wraps
from typing import Any

logger = logging.getLogger("nija.kraken_tpe_min_notional_allocation")
_MARKER = "20260719-kraken-tpe-min-notional-v3"
_PATCH_ATTR = "_nija_kraken_tpe_min_notional_v3"
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
        os.environ.get("KRAKEN_MIN_NOTIONAL_USD"),
        os.environ.get("NIJA_KRAKEN_MIN_NOTIONAL_USD"),
    )
    return max(23.10, *(_f(value, 0.0) for value in values))


def _available_balance(decision: Any, kwargs: dict[str, Any]) -> float:
    candidates = (
        kwargs.get("balance"), kwargs.get("account_balance"), kwargs.get("available_balance"),
        getattr(decision, "balance", None), getattr(decision, "account_balance", None),
        getattr(decision, "available_balance", None), getattr(decision, "capital", None),
    )
    return max((_f(value, 0.0) for value in candidates), default=0.0)


def _max_position_pct() -> float:
    values = (
        os.environ.get("NIJA_MAX_POSITION_SIZE_PCT"),
        os.environ.get("MAX_POSITION_PCT"),
        os.environ.get("MAX_POSITION_SIZE_PCT"),
    )
    pct = max((_f(value, 0.0) for value in values), default=0.0)
    if pct > 1.0:
        pct /= 100.0
    return min(1.0, max(0.0, pct or 0.10))


def _set_skip(decision: Any, reason: str) -> Any:
    for attr, value in (
        ("final_decision", "SKIP"), ("decision", "SKIP"), ("risk_allowed", False),
        ("passed_gate", False), ("reason_blocked", reason), ("reason", reason),
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

        balance = _available_balance(decision, kwargs)
        max_pct = _max_position_pct()
        cap = balance * max_pct if balance > 0 else 0.0
        cash_cap = balance * 0.98 if balance > 0 else 0.0
        bounded_lift = (
            _truthy("NIJA_KRAKEN_TPE_MIN_NOTIONAL_SAFE_LIFT_ENABLED", "true")
            and balance > 0.0
            and target <= cap + 1e-9
            and target <= cash_cap + 1e-9
        )

        if bounded_lift:
            try:
                decision.capital_allocated = target
                decision.reason_blocked = ""
                decision.reason = "kraken_minimum_notional_safely_reconciled"
            except Exception:
                pass
            logger.critical(
                "KRAKEN_TPE_MIN_NOTIONAL_SAFE_LIFT marker=%s symbol=%s old_allocation=$%.2f target=$%.2f balance=$%.2f max_position_pct=%.4f cap=$%.2f",
                _MARKER, symbol, allocated, target, balance, max_pct, cap,
            )
            return decision

        reason = (
            f"kraken_risk_sized_allocation_below_minimum:allocated={allocated:.2f}:required={target:.2f}:"
            f"balance={balance:.2f}:position_cap={cap:.2f}"
        )
        logger.critical(
            "KRAKEN_TPE_MIN_NOTIONAL_FAIL_CLOSED marker=%s symbol=%s allocated=$%.2f required=$%.2f balance=$%.2f cap=$%.2f action=skip",
            _MARKER, symbol, allocated, target, balance, cap,
        )
        return _set_skip(decision, reason)

    setattr(evaluate, _PATCH_ATTR, True)
    setattr(evaluate, "__wrapped__", original)
    cls.evaluate = evaluate
    logger.warning(
        "KRAKEN_TPE_MIN_NOTIONAL_SAFE_RECONCILIATION_PATCHED marker=%s target=$%.2f safe_lift=%s max_position_pct=%.4f",
        _MARKER, _target_notional(), _truthy("NIJA_KRAKEN_TPE_MIN_NOTIONAL_SAFE_LIFT_ENABLED", "true"), _max_position_pct(),
    )
    return True


def install() -> bool:
    try:
        from bot import trade_permission_engine as module
    except Exception:
        import trade_permission_engine as module  # type: ignore
    os.environ.setdefault("NIJA_KRAKEN_TPE_MIN_NOTIONAL_SAFE_LIFT_ENABLED", "true")
    result = patch_trade_permission_engine(module)
    os.environ["NIJA_KRAKEN_TPE_MIN_NOTIONAL_ALLOCATION_INSTALLED"] = "1" if result else "0"
    return result


install()

__all__ = ["install", "patch_trade_permission_engine", "_target_notional"]
