"""Profit-harvest realization guard v66.

``ProfitHarvestLayer`` computes useful *unrealized* profit-lock candidates from
price movement.  The underlying ``PortfolioProfitEngine`` is explicitly a
ledger of realised P&L from closed trades.  Feeding a tier-derived candidate
into that ledger before a broker confirms a position reduction conflates market
value with realised cash and can overstate harvested/compoundable profit.

v66 keeps tier/floor logic as a candidate generator while making realization an
explicit, fill-proven operation:

* tier upgrades add to ``harvestable_balance_usd`` but are not counted as
  cumulative harvested profit;
* floor hits do not silently move virtual dollars into the realised ledger;
* legacy ``partial_harvest`` is fail-closed because it has no broker execution
  proof;
* ``confirm_realized_harvest`` requires a non-empty broker fill/order proof and
  only then routes an amount into ``PortfolioProfitEngine.harvest_profits``;
* the realised amount can never exceed the candidate balance nor the realised
  profit actually available in ``PortfolioProfitEngine``.

This module does not place orders.  Broker-native exit supervisors remain
responsible for reducing/closing positions and must call the confirmation API
only after execution acknowledgement/fill reconciliation.
"""
from __future__ import annotations

import builtins
import importlib
import logging
import os
import sys
import threading
from datetime import datetime
from functools import wraps
from types import ModuleType
from typing import Any, Optional

LOGGER = logging.getLogger("nija.profit_harvest_realization_guard_v66")
MARKER = "20260809-profit-harvest-realization-v66"
_PATCH_ATTR = "_nija_profit_harvest_realization_v66"
_INSTALL_LOCK = threading.RLock()
_CONFIRM_CONTEXT = threading.local()


def _confirmation_active() -> bool:
    return bool(getattr(_CONFIRM_CONTEXT, "active", False))


def _patch(module: ModuleType) -> bool:
    cls = getattr(module, "ProfitHarvestLayer", None)
    if not isinstance(cls, type):
        return False
    original_process = getattr(cls, "process_price_update", None)
    original_partial = getattr(cls, "partial_harvest", None)
    original_route = getattr(cls, "_route_to_profit_engine", None)
    if not all(callable(value) for value in (original_process, original_partial, original_route)):
        return False
    if getattr(original_process, _PATCH_ATTR, False):
        return True

    @wraps(original_route)
    def _route_realized_only(self: Any, symbol: str, amount_usd: float, note: str = "") -> float:
        amount = max(0.0, float(amount_usd or 0.0))
        if amount <= 0.0:
            return 0.0
        if not _confirmation_active():
            LOGGER.warning(
                "PROFIT_HARVEST_V66_REALIZATION_BLOCKED marker=%s symbol=%s amount=%.4f "
                "reason=broker_fill_proof_missing candidate_only=true",
                MARKER,
                symbol,
                amount,
            )
            return 0.0
        try:
            engine = module.get_portfolio_profit_engine()
            actual = float(engine.harvest_profits(amount=amount, note=note) or 0.0)
        except Exception as exc:
            LOGGER.error(
                "PROFIT_HARVEST_V66_REALIZATION_FAILED marker=%s symbol=%s amount=%.4f error=%s:%s",
                MARKER,
                symbol,
                amount,
                type(exc).__name__,
                exc,
            )
            return 0.0
        return max(0.0, min(amount, actual))

    @wraps(original_process)
    def _process_candidate_only(self: Any, symbol: str, current_price: float):
        with getattr(self, "_lock", threading.RLock()):
            before_state = getattr(self, "_positions", {}).get(symbol)
            before_available = float(
                getattr(before_state, "harvestable_balance_usd", 0.0) or 0.0
            ) if before_state is not None else 0.0
            before_harvested = float(
                getattr(before_state, "cumulative_harvested_usd", 0.0) or 0.0
            ) if before_state is not None else 0.0
            before_harvested_pct = float(
                getattr(before_state, "cumulative_harvested_pct", 0.0) or 0.0
            ) if before_state is not None else 0.0

        decision = original_process(self, symbol, current_price)

        with getattr(self, "_lock", threading.RLock()):
            state = getattr(self, "_positions", {}).get(symbol)
            if state is None:
                return decision

            candidate_amount = max(0.0, float(getattr(decision, "harvest_amount_usd", 0.0) or 0.0))
            # The legacy method increments cumulative harvested at tier upgrade.
            # Restore the realised counters to their pre-update values.
            state.cumulative_harvested_usd = before_harvested
            state.cumulative_harvested_pct = before_harvested_pct

            # The legacy floor-hit branch clears the candidate balance after
            # attempting to route it.  Since routing is blocked without fill
            # proof, preserve the unrealised candidate instead.
            expected_candidate = before_available + candidate_amount
            if bool(getattr(decision, "floor_hit", False)):
                state.harvestable_balance_usd = max(
                    float(getattr(state, "harvestable_balance_usd", 0.0) or 0.0),
                    expected_candidate,
                )

            # Mark the just-created legacy event as a candidate rather than a
            # realised harvest for audit clarity.
            log = getattr(state, "harvest_log", None)
            if candidate_amount > 0.0 and isinstance(log, list) and log:
                event = log[-1]
                if isinstance(event, dict):
                    note = str(event.get("note", "") or "").strip()
                    event["note"] = (
                        f"UNREALIZED_CANDIDATE {note}".strip()
                    )

            saver = getattr(self, "_save_state", None)
            if callable(saver):
                saver()

        if candidate_amount > 0.0:
            LOGGER.info(
                "PROFIT_HARVEST_V66_CANDIDATE marker=%s symbol=%s candidate_usd=%.4f "
                "realized_usd=0.0 fill_proof=false",
                MARKER,
                symbol,
                candidate_amount,
            )
            try:
                decision.harvest_triggered = False
                decision.harvest_amount_usd = 0.0
                decision.message = (
                    f"{getattr(decision, 'message', '')} | candidate=${candidate_amount:.2f} "
                    "awaiting confirmed broker reduction"
                ).strip(" |")
            except Exception:
                pass
        return decision

    @wraps(original_partial)
    def _partial_requires_execution_proof(
        self: Any,
        symbol: str,
        fraction: float = 1.0,
        note: str = "",
    ) -> float:
        LOGGER.warning(
            "PROFIT_HARVEST_V66_PARTIAL_BLOCKED marker=%s symbol=%s fraction=%.4f "
            "reason=legacy_partial_harvest_has_no_broker_fill_proof",
            MARKER,
            symbol,
            float(fraction or 0.0),
        )
        return 0.0

    def confirm_realized_harvest(
        self: Any,
        symbol: str,
        amount_usd: float,
        *,
        broker_fill_id: str,
        broker_name: str = "",
        account_id: str = "",
        note: str = "",
    ) -> float:
        """Realize a harvest only after a broker-confirmed position reduction."""
        fill_id = str(broker_fill_id or "").strip()
        if not fill_id:
            raise ValueError("broker_fill_id is required")
        requested = max(0.0, float(amount_usd or 0.0))
        if requested <= 0.0:
            return 0.0

        with getattr(self, "_lock", threading.RLock()):
            state = getattr(self, "_positions", {}).get(symbol)
            if state is None:
                LOGGER.warning(
                    "PROFIT_HARVEST_V66_CONFIRM_BLOCKED marker=%s symbol=%s reason=position_not_registered fill_id=%s",
                    MARKER,
                    symbol,
                    fill_id,
                )
                return 0.0
            available = max(0.0, float(getattr(state, "harvestable_balance_usd", 0.0) or 0.0))
            candidate = min(requested, available)
        if candidate <= 0.0:
            return 0.0

        previous = _confirmation_active()
        _CONFIRM_CONTEXT.active = True
        try:
            actual = float(
                _route_realized_only(
                    self,
                    symbol,
                    candidate,
                    note=(
                        f"confirmed_exit broker={broker_name or 'unknown'} account={account_id or 'unknown'} "
                        f"fill_id={fill_id} {note}"
                    ).strip(),
                )
                or 0.0
            )
        finally:
            _CONFIRM_CONTEXT.active = previous

        if actual <= 0.0:
            return 0.0

        with getattr(self, "_lock", threading.RLock()):
            state = getattr(self, "_positions", {}).get(symbol)
            if state is None:
                return 0.0
            state.harvestable_balance_usd = max(
                0.0,
                float(getattr(state, "harvestable_balance_usd", 0.0) or 0.0) - actual,
            )
            state.cumulative_harvested_usd = float(
                getattr(state, "cumulative_harvested_usd", 0.0) or 0.0
            ) + actual
            event_cls = getattr(module, "HarvestEvent", None)
            event = {
                "timestamp": datetime.now().isoformat(),
                "symbol": symbol,
                "tier": str(getattr(state, "last_harvested_tier", "")),
                "locked_increment_pct": 0.0,
                "harvest_fraction": 0.0,
                "harvest_pct": 0.0,
                "harvest_usd": round(actual, 4),
                "note": (
                    f"REALIZED_CONFIRMED broker={broker_name or 'unknown'} "
                    f"account={account_id or 'unknown'} fill_id={fill_id} {note}"
                ).strip(),
            }
            if event_cls is not None:
                try:
                    event = event_cls(**event).__dict__
                except Exception:
                    pass
            log = getattr(state, "harvest_log", None)
            if isinstance(log, list):
                log.append(event)
            state.last_updated = datetime.now().isoformat()
            saver = getattr(self, "_save_state", None)
            if callable(saver):
                saver()

        LOGGER.critical(
            "PROFIT_HARVEST_V66_REALIZED marker=%s symbol=%s amount=%.4f broker=%s account=%s "
            "fill_id=%s broker_fill_proof=true",
            MARKER,
            symbol,
            actual,
            broker_name or "unknown",
            account_id or "unknown",
            fill_id,
        )
        return round(actual, 4)

    setattr(_route_realized_only, _PATCH_ATTR, True)
    setattr(_process_candidate_only, _PATCH_ATTR, True)
    setattr(_partial_requires_execution_proof, _PATCH_ATTR, True)
    cls._route_to_profit_engine = _route_realized_only
    cls.process_price_update = _process_candidate_only
    cls.partial_harvest = _partial_requires_execution_proof
    cls.confirm_realized_harvest = confirm_realized_harvest
    LOGGER.critical(
        "PROFIT_HARVEST_REALIZATION_V66_PATCHED marker=%s module=%s fill_proof_required=true",
        MARKER,
        module.__name__,
    )
    return True


def _patch_loaded() -> bool:
    changed = False
    for name in ("bot.profit_harvest_layer", "profit_harvest_layer"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            changed = _patch(module) or changed
    return changed


def install_import_hook() -> bool:
    with _INSTALL_LOCK:
        _patch_loaded()
        flag = "_NIJA_PROFIT_HARVEST_REALIZATION_V66_IMPORT_HOOK"
        if getattr(builtins, flag, False):
            return True
        original_import = builtins.__import__

        @wraps(original_import)
        def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
            result = original_import(name, globals, locals, fromlist, level)
            if "profit_harvest_layer" in str(name):
                _patch_loaded()
            return result

        builtins.__import__ = guarded_import
        setattr(builtins, flag, True)
        os.environ["NIJA_PROFIT_HARVEST_REALIZATION_V66_INSTALLED"] = "1"
        LOGGER.critical(
            "PROFIT_HARVEST_REALIZATION_V66_INSTALLED marker=%s fill_proof_required=true",
            MARKER,
        )
        return True


def install() -> bool:
    return install_import_hook()


__all__ = ["MARKER", "install", "install_import_hook", "_patch"]
