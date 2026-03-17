"""
NIJA Execution Pipeline
========================

The final connected flow that ties every coordination layer together:

    1. Detect market regime
    2. Update evolution engine
    3. Receive MASTER signal from MasterStrategyRouter
    4. Risk check (global 6 % ceiling via GlobalCapitalManager)
    5. Execute across all accounts via SignalBroadcaster
    6. Record results in AccountPerformanceDashboard & ProfitSplitter

Call ``ExecutionPipeline.run(signal)`` once per valid signal inside the
existing ``TradingStrategy.run_cycle()`` loop — after
``MasterStrategyRouter.update()`` has already stored the signal.

Usage
-----
::

    from bot.execution_pipeline import get_execution_pipeline

    pipeline = get_execution_pipeline()
    pipeline.run(signal=analysis, account_id="coinbase", account_balance=5000.0)

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nija.execution_pipeline")


# ---------------------------------------------------------------------------
# Optional subsystem imports
# ---------------------------------------------------------------------------

def _try_import(primary: str, fallback: str):
    """Import a module by primary path, falling back to fallback path."""
    try:
        import importlib
        return importlib.import_module(primary)
    except ImportError:
        try:
            import importlib
            return importlib.import_module(fallback)
        except ImportError:
            return None


_gcm_mod  = _try_import("global_capital_manager",           "bot.global_capital_manager")
_msr_mod  = _try_import("master_strategy_router",           "bot.master_strategy_router")
_sb_mod   = _try_import("signal_broadcaster",               "bot.signal_broadcaster")
_dash_mod = _try_import("account_performance_dashboard",    "bot.account_performance_dashboard")
_ps_mod   = _try_import("profit_splitter",                  "bot.profit_splitter")
_evo_mod  = _try_import("regime_specific_strategy_evolution","bot.regime_specific_strategy_evolution")
_aic_mod  = _try_import("ai_capital_allocator",             "bot.ai_capital_allocator")

get_global_capital_manager      = getattr(_gcm_mod,  "get_global_capital_manager",      None)
get_master_strategy_router      = getattr(_msr_mod,  "get_master_strategy_router",      None)
get_signal_broadcaster          = getattr(_sb_mod,   "get_signal_broadcaster",          None)
get_account_performance_dashboard = getattr(_dash_mod, "get_account_performance_dashboard", None)
get_profit_splitter             = getattr(_ps_mod,   "get_profit_splitter",             None)
get_regime_specific_strategy_evolution = getattr(_evo_mod, "get_regime_specific_strategy_evolution", None)
get_ai_capital_allocator        = getattr(_aic_mod,  "get_ai_capital_allocator",        None)


# ---------------------------------------------------------------------------
# ExecutionPipeline
# ---------------------------------------------------------------------------

class ExecutionPipeline:
    """
    Orchestrates the full signal-to-execution flow across all accounts.

    Pipeline steps
    --------------
    1. Detect market regime (passed in from caller)
    2. Update evolution engine with current regime
    3. Read master signal from MasterStrategyRouter
    4. Global risk check — block if 6 % ceiling would be breached
    5. Fan-out execution via SignalBroadcaster
    6. Record results in dashboard + profit splitter
    7. Trigger AI capital reallocation
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._run_count: int = 0
        self._blocked_count: int = 0
        self._last_run: Optional[str] = None

    def run(
        self,
        signal: Dict[str, Any],
        account_id: str = "platform",
        account_balance: float = 0.0,
        regime: str = "RANGING",
        pnl_usd: float = 0.0,
        is_win: bool = False,
    ) -> Dict[str, Any]:
        """
        Execute the full pipeline for the given signal.

        Args:
            signal:          Analysis dict (must contain 'action' and 'symbol').
            account_id:      ID of the calling (master) account.
            account_balance: Current balance of the master account.
            regime:          Current market regime label (e.g. 'BULL_TRENDING').
            pnl_usd:         P&L of the just-closed trade, if any (0 = entry).
            is_win:          Whether the last closed trade was a win.

        Returns:
            Result dict with 'status', 'broadcast_results', and metadata.
        """
        with self._lock:
            self._run_count += 1

        result: Dict[str, Any] = {
            "status": "ok",
            "signal_action": signal.get("action", "hold"),
            "symbol": signal.get("symbol", ""),
            "regime": regime,
            "broadcast_results": [],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        action = signal.get("action", "hold")
        if action not in ("enter_long", "enter_short"):
            result["status"] = "hold"
            return result

        # ── Step 2: Update regime-specific evolution engine ───────────────────
        if get_regime_specific_strategy_evolution:
            try:
                evo = get_regime_specific_strategy_evolution()
                # Prefer set_regime(); fall back to evolve(regime) for older API
                if callable(getattr(evo, "set_regime", None)):
                    evo.set_regime(regime)
                elif callable(getattr(evo, "evolve", None)):
                    evo.evolve(regime)
            except Exception as exc:
                logger.debug("[Pipeline] evo update skipped: %s", exc)

        # ── Step 3: Confirm master signal ─────────────────────────────────────
        if get_master_strategy_router:
            try:
                master_signal = get_master_strategy_router().get_signal()
                if master_signal and master_signal.get("symbol") == signal.get("symbol"):
                    signal = master_signal          # use authoritative master copy
            except Exception as exc:
                logger.debug("[Pipeline] master router read skipped: %s", exc)

        # ── Step 4: Global risk check ─────────────────────────────────────────
        if get_global_capital_manager:
            try:
                gcm = get_global_capital_manager()
                position_size = signal.get("position_size") or 0.0
                requested_risk = (
                    position_size / account_balance
                    if account_balance > 0 and position_size > 0
                    else 0.0
                )
                if requested_risk > 0 and not gcm.can_open_trade(requested_risk):
                    logger.warning(
                        "[Pipeline] BLOCKED_GLOBAL_RISK for %s "
                        "(requested=%.2f%%, total would exceed 6%%)",
                        signal.get("symbol"), requested_risk * 100,
                    )
                    with self._lock:
                        self._blocked_count += 1
                    result["status"] = "BLOCKED_GLOBAL_RISK"
                    return result
                gcm.update_account_risk(account_id, requested_risk)
            except Exception as exc:
                logger.debug("[Pipeline] risk check skipped: %s", exc)

        # ── Step 5: Fan-out execution across accounts ─────────────────────────
        broadcast_results: List[Dict] = []
        if get_signal_broadcaster:
            try:
                sb = get_signal_broadcaster()
                raw_results = sb.execute_across_accounts(signal)
                broadcast_results = [
                    {
                        "account_id": r.account_id,
                        "status": r.status,
                        "size_usd": r.size_usd,
                        "error": r.error,
                    }
                    for r in raw_results
                ]
            except Exception as exc:
                logger.warning("[Pipeline] signal broadcaster error: %s", exc)

        result["broadcast_results"] = broadcast_results

        # ── Step 6: Record performance & profit ───────────────────────────────
        if pnl_usd != 0.0:
            if get_account_performance_dashboard:
                try:
                    get_account_performance_dashboard().record_trade(
                        account_id=account_id,
                        pnl_usd=pnl_usd,
                        is_win=is_win,
                        equity_usd=account_balance,
                    )
                except Exception as exc:
                    logger.debug("[Pipeline] dashboard record skipped: %s", exc)

            if get_profit_splitter:
                try:
                    get_profit_splitter().record_profit(gross_pnl_usd=pnl_usd)
                except Exception as exc:
                    logger.debug("[Pipeline] profit splitter skipped: %s", exc)

        # ── Step 7: AI capital reallocation ───────────────────────────────────
        if get_ai_capital_allocator:
            try:
                get_ai_capital_allocator().update()
            except Exception as exc:
                logger.debug("[Pipeline] AI allocator update skipped: %s", exc)

        with self._lock:
            self._last_run = result["timestamp"]

        logger.info(
            "[Pipeline] ✅ %s %s → %d accounts executed (regime=%s)",
            action, signal.get("symbol", ""), len(broadcast_results), regime,
        )
        return result

    def get_stats(self) -> Dict:
        with self._lock:
            return {
                "run_count": self._run_count,
                "blocked_count": self._blocked_count,
                "last_run": self._last_run,
            }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_PIPELINE: Optional[ExecutionPipeline] = None
_PIPELINE_LOCK = threading.Lock()


def get_execution_pipeline() -> ExecutionPipeline:
    """Return the process-wide ExecutionPipeline singleton."""
    global _PIPELINE
    with _PIPELINE_LOCK:
        if _PIPELINE is None:
            _PIPELINE = ExecutionPipeline()
            logger.info("[Pipeline] singleton created — full execution pipeline ENABLED")
    return _PIPELINE
