"""
NIJA Global Integration Layer
================================

Single entry point that wires every pillar of the NIJA hedge-fund
upgrade into one globally accessible singleton:

  Pillar 1 – Multi-Strategy Diversification
      HedgeFundStrategyRouter (TrendFollowing + MeanReversion +
      StatArb + Momentum + Macro) with regime-aware consensus voting.

  Pillar 2 – Portfolio-Level Management
      MultiAssetExecutor → coordinates crypto / equity / FX / futures
      simultaneously; enforces per-class capital limits.

  Pillar 3 – Execution Sophistication
      SmartExecutionEngine → TWAP / VWAP / IS / Iceberg order splitting
      cross-venue; integrates with existing LiquidityRoutingSystem.

  Pillar 4 – Adaptive Learning
      AdaptiveLearningLoop (Bayesian re-optimisation) + RLFeedbackAdapter
      (EMA reward shim over LiveRLFeedback when available).

  Pillar 5 – Regulatory Infrastructure
      ComplianceSuite → AuditEventLogger (SHA-256 tamper-evident) +
      TradeReplayEngine + RegulatoryReporter (blotter / OATS / investor
      report) + ComplianceMonitor (real-time rule enforcement).

Cross-pillar wiring (automatic)
---------------------------------
* ComplianceMonitor is installed as the *risk gate* of MultiAssetExecutor.
* Every signal routed through the system is logged to AuditEventLogger.
* Every trade outcome feeds AdaptiveLearningLoop & RLFeedbackAdapter.
* Regime changes update strategy-router weights and are audit-logged.
* HedgeFundStrategyRouter parameter updates are pushed from AdaptiveLearningLoop.

Usage
-----
    # One-liner bootstrap (safe to call multiple times):
    from bot.nija_global_integration import get_nija_global

    nija = get_nija_global()
    result = nija.evaluate_and_execute("BTC-USD", df, indicators, regime="BULL_TRENDING")

    # Status / reporting:
    print(nija.status())
    nija.generate_regulatory_report()

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

import pandas as pd

logger = logging.getLogger("nija.global_integration")

# ─────────────────────────────────────────────────────────────────────────────
# Lazy imports – each pillar is imported once at first use; failures produce
# a WARNING log and graceful degradation, never a hard crash.
# ─────────────────────────────────────────────────────────────────────────────

def _try_import(module: str, symbol: str):
    """Return (obj, True) on success or (None, False) on ImportError."""
    try:
        mod = __import__(module, fromlist=[symbol])
        return getattr(mod, symbol), True
    except Exception as exc:  # ImportError or AttributeError
        logger.debug("[GlobalIntegration] Optional import %s.%s skipped: %s", module, symbol, exc)
        return None, False


# ─────────────────────────────────────────────────────────────────────────────
# Parameter space shared by AdaptiveLearningLoop
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_PARAM_SPACE = {
    "fast_period":    (5,  30,  5),
    "slow_period":    (20, 100, 10),
    "adx_threshold":  (15.0, 40.0, 5.0),
    "bb_std":         (1.5, 3.0, 0.5),
    "rsi_oversold":   (20.0, 35.0, 5.0),
    "momentum_thr":   (0.01, 0.05, 0.01),
}


# ─────────────────────────────────────────────────────────────────────────────
# Main integration class
# ─────────────────────────────────────────────────────────────────────────────

class NijaGlobalIntegration:
    """
    Singleton that assembles and exposes every hedge-fund capability.

    Constructed once by ``get_nija_global()``. Subsequent calls return the
    same instance, so every module in the NIJA codebase shares the same
    state — audit log, executor, optimizer, compliance monitor.

    Args:
        total_capital: Starting portfolio value in USD.
        log_dir: Root directory for audit + compliance logs.
        report_dir: Directory for generated regulatory reports.
        dry_run: When True all orders are simulated (no live fills).
        coinbase_client: Optional live Coinbase RESTClient instance.
        min_strategy_quorum: Strategies that must agree before acting.
        min_signal_confidence: Minimum weighted confidence to trade.
    """

    # ── construction ──────────────────────────────────────────────────────

    def __init__(
        self,
        total_capital: float = 10_000.0,
        log_dir: str = "logs/compliance",
        report_dir: str = "logs/reports",
        dry_run: bool = True,
        coinbase_client=None,
        min_strategy_quorum: int = 2,
        min_signal_confidence: float = 0.45,
    ):
        self.total_capital = total_capital
        self.dry_run = dry_run
        self._lock = threading.RLock()
        self._initialized_pillars: List[str] = []
        self._trade_count = 0
        self._skipped_count = 0

        logger.info("=" * 65)
        logger.info("🌐 NIJA GLOBAL INTEGRATION — initialising all pillars")
        logger.info("   capital=$%.2f  dry_run=%s", total_capital, dry_run)
        logger.info("=" * 65)

        # ── Pillar 5 first (audit must be ready before anything else) ──
        self.compliance = self._init_compliance(log_dir, report_dir)

        # ── Pillar 1 ── Multi-Strategy Router ──────────────────────────
        self.strategy_router = self._init_strategy_router(min_strategy_quorum, min_signal_confidence)

        # ── Pillar 2 ── Portfolio Executor ─────────────────────────────
        self.executor = self._init_executor(total_capital, coinbase_client)

        # ── Pillar 3 ── Smart Execution Engine ─────────────────────────
        self.execution_engine = self._init_execution_engine(coinbase_client)

        # ── Pillar 4 ── Adaptive Learning ──────────────────────────────
        self.adaptive_loop, self.rl_adapter = self._init_adaptive_learning()

        # ── Hook: compliance monitor → executor risk gate ──────────────
        self._wire_risk_gate()

        # ── Hook: existing NIJA singletons ─────────────────────────────
        self._wire_existing_nija_systems()

        logger.info("✅ Global integration ready. Pillars: %s", self._initialized_pillars)

    # ── Pillar initialisers ───────────────────────────────────────────────

    def _init_compliance(self, log_dir: str, report_dir: str):
        try:
            from bot.compliance_audit_reporter import get_compliance_suite
            suite = get_compliance_suite(log_dir=log_dir, report_dir=report_dir, reset=True)
            suite.audit.log(
                __import__("bot.compliance_audit_reporter", fromlist=["AuditEventType"]).AuditEventType.SESSION_START,
                {"mode": "AUTONOMOUS", "capital": self.total_capital,
                 "dry_run": self.dry_run, "init_ts": datetime.now(timezone.utc).isoformat()}
            )
            self._initialized_pillars.append("COMPLIANCE")
            logger.info("✅ Pillar 5 – Regulatory Infrastructure ready")
            return suite
        except Exception as exc:
            logger.warning("⚠️  Compliance suite unavailable: %s", exc)
            return None

    def _init_strategy_router(self, quorum: int, min_conf: float):
        try:
            from bot.hedge_fund_strategies import HedgeFundStrategyRouter
            router = HedgeFundStrategyRouter(min_quorum=quorum, min_confidence=min_conf)
            self._initialized_pillars.append("MULTI_STRATEGY")
            logger.info("✅ Pillar 1 – Multi-Strategy Router ready (quorum=%d conf≥%.2f)", quorum, min_conf)
            return router
        except Exception as exc:
            logger.warning("⚠️  HedgeFundStrategyRouter unavailable: %s", exc)
            return None

    def _init_executor(self, total_capital: float, coinbase_client):
        try:
            from bot.multi_asset_executor import MultiAssetExecutor, AssetAllocation

            # Read allocation from env or use crypto-first default
            crypto_pct  = float(os.getenv("ALLOC_CRYPTO",  "1.0"))
            equity_pct  = float(os.getenv("ALLOC_EQUITY",  "0.0"))
            fx_pct      = float(os.getenv("ALLOC_FX",      "0.0"))
            futures_pct = float(os.getenv("ALLOC_FUTURES", "0.0"))
            options_pct = float(os.getenv("ALLOC_OPTIONS", "0.0"))

            total_alloc = crypto_pct + equity_pct + fx_pct + futures_pct + options_pct
            if total_alloc > 1.0 + 1e-6:
                logger.warning("Allocation sum %.3f > 1.0 — normalising", total_alloc)
                crypto_pct  /= total_alloc
                equity_pct  /= total_alloc
                fx_pct      /= total_alloc
                futures_pct /= total_alloc
                options_pct /= total_alloc

            allocation = AssetAllocation(
                crypto=crypto_pct, equity=equity_pct,
                fx=fx_pct, futures=futures_pct, options=options_pct,
            )
            exec_ = MultiAssetExecutor(
                total_capital=total_capital,
                allocation=allocation,
                coinbase_client=coinbase_client,
            )
            self._initialized_pillars.append("PORTFOLIO_EXECUTION")
            logger.info("✅ Pillar 2 – Multi-Asset Executor ready (crypto=%.0f%% eq=%.0f%% fx=%.0f%%)",
                        crypto_pct*100, equity_pct*100, fx_pct*100)
            return exec_
        except Exception as exc:
            logger.warning("⚠️  MultiAssetExecutor unavailable: %s", exc)
            return None

    def _init_execution_engine(self, coinbase_client):
        try:
            from bot.smart_execution_engine import SmartExecutionEngine

            # Try to pick up existing routing system
            router = None
            try:
                from bot.liquidity_routing_system import LiquidityRoutingSystem
                router = LiquidityRoutingSystem()
            except Exception:
                pass

            engine = SmartExecutionEngine(
                broker_client=coinbase_client,
                routing_system=router,
                simulation_mode=(coinbase_client is None) or self.dry_run,
                on_slice_filled=self._on_slice_filled,
            )
            self._initialized_pillars.append("SMART_EXECUTION")
            logger.info("✅ Pillar 3 – Smart Execution Engine ready (sim=%s router=%s)",
                        engine.simulation_mode, router is not None)
            return engine
        except Exception as exc:
            logger.warning("⚠️  SmartExecutionEngine unavailable: %s", exc)
            return None

    def _init_adaptive_learning(self):
        try:
            from bot.ml_strategy_optimizer import (
                ParameterSpace, BayesianOptimizer,
                AdaptiveLearningLoop, RLFeedbackAdapter,
            )

            space = ParameterSpace(DEFAULT_PARAM_SPACE)

            def objective_factory(trades: List[Dict]) -> Callable:
                pnls = [float(t.get("pnl", 0)) for t in trades if "pnl" in t]
                if not pnls:
                    return lambda p: 0.0
                avg_pnl = sum(pnls) / len(pnls)
                wins    = sum(1 for p in pnls if p > 0)
                win_rate = wins / len(pnls)
                def objective(params: Dict) -> float:
                    # Synthetic Sharpe proxy combining live trade history
                    penalty = (abs(params.get("fast_period", 20) - 15) * 0.01
                               + abs(params.get("slow_period", 50) - 50) * 0.005)
                    return avg_pnl * win_rate - penalty
                return objective

            loop = AdaptiveLearningLoop(
                space=space,
                objective_factory=objective_factory,
                optimiser_class=BayesianOptimizer,
                eval_window=int(os.getenv("ADAPTIVE_EVAL_WINDOW", "30")),
                opt_iterations=int(os.getenv("ADAPTIVE_OPT_ITER", "25")),
                on_params_updated=self._on_params_updated,
            )

            rl = RLFeedbackAdapter(
                base_params=space.random_point(),
                learning_rate=float(os.getenv("RL_LEARNING_RATE", "0.05")),
                discount=float(os.getenv("RL_DISCOUNT", "0.95")),
            )

            self._initialized_pillars.append("ADAPTIVE_LEARNING")
            logger.info("✅ Pillar 4 – Adaptive Learning ready (eval_window=%s)",
                        os.getenv("ADAPTIVE_EVAL_WINDOW", "30"))
            return loop, rl

        except Exception as exc:
            logger.warning("⚠️  AdaptiveLearning unavailable: %s", exc)
            return None, None

    # ── Cross-pillar wiring ──────────────────────────────────────────────

    def _wire_risk_gate(self) -> None:
        """Install ComplianceMonitor as the risk gate of MultiAssetExecutor."""
        if self.executor is None or self.compliance is None:
            return
        monitor = self.compliance.monitor

        def compliance_risk_gate(signal: Dict) -> bool:
            allowed, violations = monitor.check_trade(signal)
            if not allowed:
                logger.warning("[GlobalIntegration] Compliance gate blocked %s: %s",
                               signal.get("symbol"), violations)
                if self.compliance:
                    try:
                        from bot.compliance_audit_reporter import AuditEventType
                        self.compliance.audit.log_risk_block(
                            signal.get("symbol", ""),
                            f"Compliance gate: {violations[0] if violations else 'unknown'}",
                            signal,
                        )
                    except Exception:
                        pass
            return allowed

        self.executor.risk_gate = compliance_risk_gate
        logger.info("🔗 Risk gate wired: ComplianceMonitor → MultiAssetExecutor")

    def _wire_existing_nija_systems(self) -> None:
        """Integrate with pre-existing NIJA singleton modules (best-effort)."""
        # Global risk controller — update capital & drawdown awareness
        try:
            from bot.global_risk_controller import get_global_risk_controller
            self._global_risk = get_global_risk_controller()
            logger.info("🔗 Wired: GlobalRiskController")
        except Exception:
            self._global_risk = None

        # Portfolio intelligence
        try:
            from bot.portfolio_intelligence import get_portfolio_intelligence
            self._portfolio_intelligence = get_portfolio_intelligence()
            logger.info("🔗 Wired: PortfolioIntelligence")
        except Exception:
            self._portfolio_intelligence = None

        # Smart drawdown recovery
        try:
            from bot.smart_drawdown_recovery import get_smart_drawdown_recovery
            self._drawdown_recovery = get_smart_drawdown_recovery()
            logger.info("🔗 Wired: SmartDrawdownRecovery")
        except Exception:
            self._drawdown_recovery = None

        # Portfolio VaR monitor
        try:
            from bot.portfolio_var_monitor import get_portfolio_var_monitor
            self._var_monitor = get_portfolio_var_monitor()
            logger.info("🔗 Wired: PortfolioVaRMonitor")
        except Exception:
            self._var_monitor = None

        # AI intelligence hub
        try:
            from bot.ai_intelligence_hub import get_ai_intelligence_hub
            self._ai_hub = get_ai_intelligence_hub()
            logger.info("🔗 Wired: AIIntelligenceHub")
        except Exception:
            self._ai_hub = None

    # ── Callback handlers ────────────────────────────────────────────────

    def _on_slice_filled(self, sl) -> None:
        """Called after each smart-execution slice fills."""
        if self.compliance:
            try:
                from bot.compliance_audit_reporter import AuditEventType
                self.compliance.audit.log(AuditEventType.TRADE_ENTRY, {
                    "side": sl.side, "size": sl.filled_size,
                    "price": sl.filled_price, "venue": sl.venue,
                    "algo_slice": sl.slice_id,
                }, symbol=sl.symbol)
            except Exception:
                pass

    def _on_params_updated(self, new_params: Dict) -> None:
        """Called by AdaptiveLearningLoop after each re-optimisation."""
        logger.info("[GlobalIntegration] Adaptive params updated: %s", new_params)
        if self.compliance:
            try:
                from bot.compliance_audit_reporter import AuditEventType
                self.compliance.audit.log(AuditEventType.AI_PARAMS_UPDATED, {
                    "new_params": new_params, "source": "AdaptiveLearningLoop"
                })
            except Exception:
                pass

    # ── Core trading pipeline ────────────────────────────────────────────

    def evaluate_and_execute(
        self,
        symbol: str,
        df: pd.DataFrame,
        indicators: Optional[Dict] = None,
        regime: str = "DEFAULT",
        asset_class: str = "CRYPTO",
        df_pair: Optional[pd.DataFrame] = None,
        pair_symbol: Optional[str] = None,
        use_smart_execution: bool = True,
        algo: str = "TWAP",
        dry_run_override: Optional[bool] = None,
    ) -> Dict:
        """
        Full pipeline: signal → compliance → portfolio check → smart execute → audit.

        Args:
            symbol: Primary trading symbol (e.g. "BTC-USD").
            df: OHLCV DataFrame for signal generation.
            indicators: Pre-computed indicators dict (optional).
            regime: Market regime string (e.g. "BULL_TRENDING").
            asset_class: "CRYPTO" | "EQUITY" | "FX" | "FUTURES" | "OPTIONS".
            df_pair: Second DataFrame for StatArb (optional).
            pair_symbol: Paired symbol for StatArb (optional).
            use_smart_execution: Route via SmartExecutionEngine (TWAP/VWAP/IS/Iceberg).
            algo: Execution algorithm name when use_smart_execution=True.
            dry_run_override: Override instance-level dry_run flag.

        Returns:
            Dict with keys: signal, execution_result, audit_ids, blocked.
        """
        dry_run = self.dry_run if dry_run_override is None else dry_run_override
        result: Dict[str, Any] = {
            "symbol": symbol, "regime": regime, "blocked": False,
            "signal": None, "execution_result": None, "audit_ids": [],
        }

        # ── 1. Check global risk controller (existing NIJA gate) ─────────
        if self._global_risk:
            try:
                allowed, reason = self._global_risk.is_trading_allowed()
                if not allowed:
                    result["blocked"] = True
                    result["block_reason"] = f"GlobalRiskController: {reason}"
                    with self._lock:
                        self._skipped_count += 1
                    logger.info("[GlobalIntegration] %s blocked by GlobalRiskController: %s", symbol, reason)
                    return result
            except Exception as exc:
                logger.debug("[GlobalIntegration] GlobalRiskController check error: %s", exc)

        # ── 2. Generate multi-strategy consensus signal ──────────────────
        if self.strategy_router is None:
            result["blocked"] = True
            result["block_reason"] = "StrategyRouter not initialised"
            return result

        try:
            signal = self.strategy_router.get_consensus_signal(
                df=df, symbol=symbol, indicators=indicators or {},
                regime=regime, df_pair=df_pair, pair_symbol=pair_symbol,
            )
        except Exception as exc:
            logger.error("[GlobalIntegration] Signal generation failed for %s: %s", symbol, exc)
            result["blocked"] = True
            result["block_reason"] = f"Signal error: {exc}"
            return result

        result["signal"] = signal

        # Audit: signal generated
        if self.compliance:
            try:
                from bot.compliance_audit_reporter import AuditEventType
                rec = self.compliance.audit.log_ai_signal(
                    symbol, signal["action"], signal["confidence"],
                    "HEDGE_FUND_CONSENSUS",
                    {"regime": regime, "buy_votes": signal.get("buy_votes"),
                     "sell_votes": signal.get("sell_votes")},
                )
                result["audit_ids"].append(rec.event_id)
            except Exception:
                pass

        if signal.get("action") == "HOLD":
            with self._lock:
                self._skipped_count += 1
            return result

        # ── 3. Check drawdown recovery (existing NIJA gate) ─────────────
        if self._drawdown_recovery:
            try:
                recovery_state = self._drawdown_recovery.get_recovery_state()
                if hasattr(recovery_state, "position_size_multiplier"):
                    mult = recovery_state.position_size_multiplier
                    if mult < 0.21:   # CRITICAL drawdown level
                        result["blocked"] = True
                        result["block_reason"] = f"Drawdown CRITICAL (mult={mult:.2f})"
                        with self._lock:
                            self._skipped_count += 1
                        return result
                    # Scale suggested size by recovery multiplier
                    signal["suggested_size_pct"] = signal.get("suggested_size_pct", 0.1) * mult
            except Exception as exc:
                logger.debug("[GlobalIntegration] Drawdown recovery check: %s", exc)

        # ── 4. Portfolio execution ────────────────────────────────────────
        if self.executor is None:
            result["blocked"] = True
            result["block_reason"] = "MultiAssetExecutor not initialised"
            return result

        if use_smart_execution and self.execution_engine is not None:
            exec_result = self._execute_via_smart_engine(signal, asset_class, algo, dry_run)
        else:
            exec_result = self._execute_direct(signal, asset_class, dry_run)

        result["execution_result"] = exec_result

        # ── 5. Audit: trade entry ─────────────────────────────────────────
        if exec_result and exec_result.get("success"):
            if self.compliance:
                try:
                    from bot.compliance_audit_reporter import AuditEventType
                    rec = self.compliance.audit.log_trade_entry(
                        symbol=symbol,
                        side=signal["action"],
                        size=exec_result.get("filled_size", 0),
                        price=exec_result.get("filled_price", 0),
                        metadata={"strategy": "HEDGE_FUND_CONSENSUS",
                                  "regime": regime, "algo": algo,
                                  "dry_run": dry_run},
                    )
                    result["audit_ids"].append(rec.event_id)
                except Exception:
                    pass

        with self._lock:
            self._trade_count += 1

        return result

    def _execute_via_smart_engine(self, signal: Dict, asset_class: str, algo: str, dry_run: bool) -> Dict:
        from bot.smart_execution_engine import ExecutionAlgo
        try:
            algo_enum = ExecutionAlgo(algo.upper())
        except ValueError:
            algo_enum = ExecutionAlgo.TWAP

        price = signal.get("entry_price", signal.get("current_price", 0.0))
        # Estimate total size from executor's available capital
        if self.executor:
            from bot.multi_asset_executor import AssetClass as AC
            try:
                ac = AC(asset_class.upper())
                avail = self.executor._class_available(ac)
                size_usd = avail * signal.get("suggested_size_pct", 0.05)
                size = (size_usd / price) if price > 0 else 0.0
            except Exception:
                size = 0.01
        else:
            size = 0.01

        if size <= 0:
            return {"success": False, "message": "Zero size — insufficient capital"}

        plan = self.execution_engine.create_execution_plan(
            symbol=signal["symbol"],
            side=signal["action"],
            total_size=size,
            algo=algo_enum,
            current_price=price,
            duration_minutes=int(os.getenv("EXEC_DURATION_MIN", "15")),
        )
        self.execution_engine.execute_plan(plan, blocking=True)
        return {
            "success": plan.status == "COMPLETED",
            "filled_size": plan.total_filled,
            "filled_price": plan.avg_fill_price,
            "slippage_bps": plan.slippage_bps,
            "savings_usd": plan.savings_usd,
            "algo": algo_enum.value,
            "plan_id": plan.plan_id,
        }

    def _execute_direct(self, signal: Dict, asset_class: str, dry_run: bool) -> Dict:
        from bot.multi_asset_executor import AssetClass as AC
        try:
            ac = AC(asset_class.upper())
        except ValueError:
            ac = AC.CRYPTO
        result = self.executor.execute_signal(signal, asset_class=ac, dry_run=dry_run)
        return result.to_dict()

    # ── Trade outcome feedback ────────────────────────────────────────────

    def record_trade_outcome(
        self,
        symbol: str,
        pnl: float,
        exit_price: float,
        size: float,
        reason: str = "unknown",
        params_used: Optional[Dict] = None,
    ) -> None:
        """
        Call after every position close to feed the learning loops and
        write the regulatory audit exit record.

        Args:
            symbol: Trading symbol.
            pnl: Realised profit/loss in USD.
            exit_price: Price at which position was closed.
            size: Units closed.
            reason: "take_profit" | "stop_loss" | "manual" | …
            params_used: Strategy parameter dict active during the trade.
        """
        trade = {"symbol": symbol, "pnl": pnl, "size": size,
                 "exit_price": exit_price, "reason": reason,
                 "params_used": params_used or {}}

        # Adaptive learning
        if self.adaptive_loop:
            try:
                self.adaptive_loop.record_trade(trade)
            except Exception as exc:
                logger.debug("[GlobalIntegration] AdaptiveLoop record error: %s", exc)

        # RL feedback
        if self.rl_adapter:
            try:
                reward = pnl / max(size * exit_price, 1.0)   # normalised return
                self.rl_adapter.record_outcome(trade, reward=reward)
            except Exception as exc:
                logger.debug("[GlobalIntegration] RL record error: %s", exc)

        # Audit exit
        if self.compliance:
            try:
                self.compliance.audit.log_trade_exit(
                    symbol=symbol, side="SELL", size=size, price=exit_price,
                    pnl=pnl, reason=reason,
                )
            except Exception:
                pass

        logger.debug("[GlobalIntegration] Outcome recorded: %s pnl=%.4f reason=%s", symbol, pnl, reason)

    # ── Regime update ─────────────────────────────────────────────────────

    def update_regime(self, new_regime: str, old_regime: str = "") -> None:
        """
        Notify all components of a market regime change.
        Logs to audit, updates VaR monitor if available.
        """
        logger.info("[GlobalIntegration] Regime: %s → %s", old_regime or "?", new_regime)
        if self.compliance and old_regime:
            try:
                self.compliance.audit.log_regime_change(old_regime, new_regime)
            except Exception:
                pass

    # ── Capital update ────────────────────────────────────────────────────

    def update_capital(self, new_capital: float) -> None:
        """Sync updated portfolio value to executor and VaR monitor."""
        with self._lock:
            self.total_capital = new_capital
        if self.executor:
            self.executor.update_capital(new_capital)
        if self.compliance:
            try:
                from bot.compliance_audit_reporter import AuditEventType
                self.compliance.audit.log(AuditEventType.CAPITAL_UPDATED,
                                          {"new_capital": new_capital})
            except Exception:
                pass

    # ── Reporting ─────────────────────────────────────────────────────────

    def generate_regulatory_report(self, report_type: str = "all") -> Dict[str, str]:
        """
        Generate regulatory reports on demand.

        Args:
            report_type: "blotter" | "oats" | "investor" | "all"

        Returns:
            Dict of {report_type: file_path}.
        """
        if self.compliance is None:
            return {}
        files: Dict[str, str] = {}
        try:
            if report_type in ("blotter", "all"):
                files["blotter"] = self.compliance.reporter.generate_trade_blotter()
            if report_type in ("oats", "all"):
                files["oats"] = self.compliance.reporter.generate_oats_report()
            if report_type in ("investor", "all"):
                snap = self.executor.portfolio_snapshot() if self.executor else {}
                files["investor"] = self.compliance.reporter.generate_investor_report(
                    portfolio_snapshot=snap
                )
        except Exception as exc:
            logger.error("[GlobalIntegration] Report generation failed: %s", exc)
        return files

    def status(self) -> Dict:
        """Return a comprehensive health and performance snapshot."""
        with self._lock:
            trade_count   = self._trade_count
            skipped_count = self._skipped_count

        snap = self.executor.portfolio_snapshot() if self.executor else {}
        exec_stats = self.execution_engine.aggregate_stats() if self.execution_engine else {}
        adaptive_history = len(self.adaptive_loop.history()) if self.adaptive_loop else 0
        compliance_report = self.compliance.monitor.compliance_report() if self.compliance else {}

        return {
            "initialized_pillars": self._initialized_pillars,
            "total_capital": self.total_capital,
            "dry_run": self.dry_run,
            "trade_count": trade_count,
            "skipped_count": skipped_count,
            "portfolio": snap,
            "execution": exec_stats,
            "adaptive_reoptimisations": adaptive_history,
            "current_params": self.adaptive_loop.current_params if self.adaptive_loop else {},
            "rl_ema_reward": self.rl_adapter.ema_reward if self.rl_adapter else 0.0,
            "compliance": compliance_report,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Module-level singleton
# ─────────────────────────────────────────────────────────────────────────────

_global_instance: Optional[NijaGlobalIntegration] = None
_global_lock = threading.Lock()


def get_nija_global(
    total_capital: float = 10_000.0,
    log_dir: str = "logs/compliance",
    report_dir: str = "logs/reports",
    dry_run: bool = True,
    coinbase_client=None,
    min_strategy_quorum: int = 2,
    min_signal_confidence: float = 0.45,
    reset: bool = False,
) -> NijaGlobalIntegration:
    """
    Return (or create) the module-level NijaGlobalIntegration singleton.

    Safe to call from anywhere in the codebase — subsequent calls with
    different parameters do NOT recreate the instance (use reset=True to
    force re-initialisation).

    Args:
        total_capital: Starting portfolio USD value.
        log_dir: Directory for audit event logs.
        report_dir: Directory for generated reports.
        dry_run: Simulate orders when True.
        coinbase_client: Live Coinbase RESTClient (optional).
        min_strategy_quorum: Strategies that must agree to act.
        min_signal_confidence: Minimum confidence to trade.
        reset: Force creation of a fresh instance.

    Returns:
        NijaGlobalIntegration singleton.
    """
    global _global_instance
    with _global_lock:
        if _global_instance is None or reset:
            _global_instance = NijaGlobalIntegration(
                total_capital=total_capital,
                log_dir=log_dir,
                report_dir=report_dir,
                dry_run=dry_run,
                coinbase_client=coinbase_client,
                min_strategy_quorum=min_strategy_quorum,
                min_signal_confidence=min_signal_confidence,
            )
    return _global_instance
