"""Universal profit-target policy for platform and every live user account (v239).

NIJA already has adaptive profit-target logic and a universal live exit supervisor,
but legacy/open positions can reach the supervisor without explicit take_profit_1/2/3
fields. This patch closes that gap at the shared supervisor boundary so the same policy
covers platform brokers and every registered user broker without copy-trading or
account-specific assumptions.

For positions with a verified entry price and quantity, missing targets are synthesized
from configurable percentages. Existing explicit targets are never overwritten.
Defaults mirror NIJA's established adaptive target ladder: 0.5%, 1.0%, and 2.0% for
TP1/TP2/TP3. live_broker_profit_exit_convergence_v25 remains authoritative for fee,
slippage, and minimum-net-profit floors, so a profit exit cannot be triggered below the
configured economic reserve. Stop-loss and trailing-profit logic remain unchanged.

Profit is not guaranteed. This patch only ensures every eligible position has a
consistent profit-taking target policy and that the existing fill-confirmed exit path
can act on it.
"""
from __future__ import annotations

import importlib
import logging
import os
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.runtime_all_account_profit_targets_v239")
MARKER = "20260826-all-account-profit-targets-v239"
_PATCH_ATTR = "_nija_all_account_profit_targets_v239"


def _f(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        return default if number != number else number
    except Exception:
        return default


def _pct(name: str, default: float) -> float:
    return max(0.0005, min(0.25, _f(os.environ.get(name), default)))


def _targets() -> tuple[float, float, float]:
    tp1 = _pct("NIJA_PROFIT_TARGET_TP1_PCT", 0.005)
    tp2 = max(tp1, _pct("NIJA_PROFIT_TARGET_TP2_PCT", 0.010))
    tp3 = max(tp2, _pct("NIJA_PROFIT_TARGET_TP3_PCT", 0.020))
    return tp1, tp2, tp3


def _quantity(pos: dict[str, Any]) -> float:
    for key in ("quantity", "qty", "size", "amount", "units", "balance"):
        if pos.get(key) is not None:
            return abs(_f(pos.get(key)))
    return 0.0


def _entry(pos: dict[str, Any]) -> float:
    for key in ("entry_price", "avg_entry_price", "average_price", "cost_basis_price", "avg_price"):
        if pos.get(key) is not None:
            value = _f(pos.get(key))
            if value > 0:
                return value
    return 0.0


def _side(pos: dict[str, Any]) -> str:
    raw = str(pos.get("side") or "").strip().lower()
    if raw in {"short", "sell"}:
        return "short"
    return "long"


def _with_profit_targets(raw: Any) -> Any:
    if not isinstance(raw, dict):
        return raw
    pos = dict(raw)
    entry = _entry(pos)
    qty = _quantity(pos)
    if entry <= 0 or qty <= 0:
        return pos

    tp1, tp2, tp3 = _targets()
    short = _side(pos) == "short"
    synthesized = []
    for key, pct in (("take_profit_1", tp1), ("take_profit_2", tp2), ("take_profit_3", tp3)):
        if _f(pos.get(key)) > 0:
            continue
        pos[key] = entry * (1.0 - pct if short else 1.0 + pct)
        synthesized.append(key)

    if synthesized:
        LOGGER.info(
            "ALL_ACCOUNT_PROFIT_TARGETS_V239_APPLIED marker=%s account=%s symbol=%s side=%s "
            "entry=%.8f quantity=%.8f synthesized=%s tp1_pct=%.4f tp2_pct=%.4f tp3_pct=%.4f "
            "existing_targets_preserved=true fee_aware_floor_preserved=true",
            MARKER,
            str(pos.get("account_id") or pos.get("user_id") or pos.get("account") or "platform"),
            str(pos.get("symbol") or "unknown"),
            _side(pos), entry, qty, ",".join(synthesized), tp1, tp2, tp3,
        )
    return pos


def _patch_supervisor() -> bool:
    supervisor = importlib.import_module("bot.universal_broker_exit_supervisor_patch")
    current = getattr(supervisor, "_tracker_positions", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    @wraps(current)
    def tracker_positions_v239(broker: Any):
        rows = current(broker)
        if not isinstance(rows, list):
            return rows
        return [_with_profit_targets(row) for row in rows]

    setattr(tracker_positions_v239, _PATCH_ATTR, True)
    setattr(tracker_positions_v239, "__wrapped__", current)
    supervisor._tracker_positions = tracker_positions_v239

    # v25 imports the supervisor module object and calls supervisor._tracker_positions
    # dynamically, so one canonical patch covers platform and all user broker scans.
    return True


def _reassert_profit_exit_stack() -> bool:
    try:
        v25 = importlib.import_module("bot.live_broker_profit_exit_convergence_v25")
        install = getattr(v25, "install", None)
        return bool(callable(install) and install())
    except Exception as exc:
        LOGGER.error(
            "ALL_ACCOUNT_PROFIT_TARGETS_V239_V25_ERROR marker=%s error=%s:%s",
            MARKER, type(exc).__name__, exc,
        )
        return False


def install() -> bool:
    try:
        patched = _patch_supervisor()
        v25_ready = _reassert_profit_exit_stack()
        ready = bool(patched and v25_ready)
    except Exception as exc:
        LOGGER.error(
            "ALL_ACCOUNT_PROFIT_TARGETS_V239_INSTALL_ERROR marker=%s error=%s:%s trading_fail_closed=true",
            MARKER, type(exc).__name__, exc,
        )
        ready = False
    os.environ["NIJA_ALL_ACCOUNT_PROFIT_TARGETS_V239_READY"] = "1" if ready else "0"
    if ready:
        tp1, tp2, tp3 = _targets()
        LOGGER.critical(
            "ALL_ACCOUNT_PROFIT_TARGETS_V239_READY marker=%s ready=true scope=platform_and_all_registered_users "
            "tp1_pct=%.4f tp2_pct=%.4f tp3_pct=%.4f existing_targets_preserved=true "
            "fee_slippage_min_net_floor_preserved=true fill_confirmation_preserved=true stop_loss_unchanged=true "
            "trailing_profit_unchanged=true execution_authority_unchanged=true safety_gates_bypassed=false",
            MARKER, tp1, tp2, tp3,
        )
    return ready


def install_import_hook() -> bool:
    return install()


__all__ = ["MARKER", "install", "install_import_hook", "_with_profit_targets", "_targets"]
