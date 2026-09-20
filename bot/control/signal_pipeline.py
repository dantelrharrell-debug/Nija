"""
NIJA Control Layer — Signal Pipeline
======================================

Integrates all control-layer components into a single callable unit:

    1. Detect regime        (RegimeEngine)
    2. Compile signal       (ControlCompiler)
    3. Validate risk        (RiskEngine)
    4. Return execution-ready CompiledSignal or None

Every signal — approved or rejected — is stored in Redis for a full
audit trail.

Usage
-----
::

    from bot.control.signal_pipeline import get_signal_pipeline
    from bot.control.control_compiler import RawSignal

    pipeline = get_signal_pipeline()

    result = pipeline.process_signal(
        raw_signal=RawSignal(
            symbol="BTC-USD",
            side="buy",
            action="enter_long",
            size_usd=500.0,
            confidence=0.72,
            regime="trending",
            strategy="swing",
        ),
        df=price_df,
        current_positions=[],
        portfolio_value_usd=10_000.0,
    )

    if result:
        execute(result)

Author: NIJA Trading Systems
Phase:  1 — Control Layer
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import threading
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

import pandas as pd

from bot.control.control_compiler import (
    ControlCompiler,
    CompiledSignal,
    RawSignal,
    get_control_compiler,
)
from bot.control.isolation_guards import ScopedRiskSnapshot, verify_snapshot_ownership
from bot.control.trading_context import TradingContext
from bot.control.regime_engine import (
    RegimeEngine,
    RegimeResult,
    get_regime_engine,
)
from bot.control.risk_engine import (
    RiskEngine,
    get_risk_engine,
)
from bot.control.confirmation_engine import ConfirmationEngine
from bot.control.decision_context import (
    PROTECTION_FAILED,
    PROTECTION_UNVERIFIED,
    IdempotencyReservationHandle,
    UserDecisionContext,
    UserPortfolioSnapshot,
    UserScopedIdempotencyRegistry,
    get_user_scoped_idempotency_registry,
)
from bot.control.signal_scoring import SignalScoringEngine
from bot.control.situation_analysis import SituationAnalysisEngine
from bot.control.strategy_registry import StrategyDetectorRegistry
from bot.control.strategy_signal import StrategySignal

logger = logging.getLogger("nija.control.pipeline")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_SIGNAL_REDIS_TTL: int = int(os.getenv("NIJA_SIGNAL_REDIS_TTL_SECONDS", "3600"))

# When True, the pipeline injects the detected regime into the raw signal
# before compilation so the compiler can perform regime-compatibility checks.
_INJECT_DETECTED_REGIME: bool = (
    os.getenv("NIJA_PIPELINE_INJECT_REGIME", "true").lower() == "true"
)

# When True, the pipeline injects a minimal synthetic test signal whenever no
# signal has been approved in the last NIJA_DIAG_TRADE_IDLE_SECONDS seconds.
# This surfaces execution-path wiring issues without requiring a real market signal.
_DIAGNOSTIC_TRADE_ENABLED: bool = (
    os.getenv("NIJA_DIAGNOSTIC_TRADE_ENABLED", "false").lower() in ("1", "true", "yes")
)
_DIAGNOSTIC_TRADE_IDLE_SECONDS: float = float(
    os.getenv("NIJA_DIAG_TRADE_IDLE_SECONDS", "300")
)
# Symbol and size used for the forced diagnostic signal
_DIAGNOSTIC_TRADE_SYMBOL: str = os.getenv("NIJA_DIAG_TRADE_SYMBOL", "BTC-USD")
_DIAGNOSTIC_TRADE_SIZE_USD: float = float(os.getenv("NIJA_DIAG_TRADE_SIZE_USD", "10.0"))


# ---------------------------------------------------------------------------
# SignalPipeline
# ---------------------------------------------------------------------------

class SignalPipeline:
    """
    End-to-end signal processing pipeline.

    Thread-safe.  Use ``get_signal_pipeline()`` for the process singleton.
    """

    def __init__(
        self,
        compiler: Optional[ControlCompiler] = None,
        regime_engine: Optional[RegimeEngine] = None,
        risk_engine: Optional[RiskEngine] = None,
        redis_client=None,
        context_authorizer: Optional[Callable[[TradingContext], bool]] = None,
    ) -> None:
        self._compiler      = compiler      or get_control_compiler(redis_client)
        self._regime_engine = regime_engine or get_regime_engine(redis_client)
        self._risk_engine   = risk_engine   or get_risk_engine(redis_client)
        self._detector_registry = StrategyDetectorRegistry()
        self._scoring_engine = SignalScoringEngine()
        self._confirmation_engine = ConfirmationEngine()
        self._situation_engine = SituationAnalysisEngine()
        self._redis         = redis_client
        self._context_authorizer = context_authorizer
        self._lock          = threading.Lock()
        self._idempotency_registry = get_user_scoped_idempotency_registry(redis_client)

        # Session counters
        self._total:    int = 0
        self._approved: int = 0
        self._rejected: int = 0

        # Diagnostic trade tracking
        self._last_approved_ts: Dict[str, float] = {}

        logger.info(
            "SignalPipeline initialised | diagnostic_trade=%s idle_threshold=%.0fs",
            _DIAGNOSTIC_TRADE_ENABLED, _DIAGNOSTIC_TRADE_IDLE_SECONDS,
        )

    def process_market_snapshot(
        self,
        *,
        symbol: str,
        broker: str,
        df: pd.DataFrame,
        trading_context: TradingContext,
        risk_snapshot: ScopedRiskSnapshot,
        checks: Optional[Dict[str, bool]] = None,
        score_context: Optional[Dict[str, float]] = None,
        requested_size_usd: Optional[float] = None,
        authoritative_position_proven: bool = True,
    ) -> Optional[CompiledSignal]:
        """
        Run the detector-driven strategy flow for one market snapshot.

        Parameters
        ----------
        symbol, broker:
            Target instrument and venue label for detector context.
        df:
            OHLCV frame used by regime detection and strategy detectors.
        trading_context:
            Immutable owner/account identity for the entire decision.
        risk_snapshot:
            Owner-bound balance, P&L, portfolio, and position state. Foreign
            scoped positions are ignored and unscoped records fail closed.
        checks:
            Confirmation booleans (candle_close, volume, trend,
            market_data_fresh, broker_available, spread_ok, liquidity_ok).
        score_context:
            Scoring inputs for the central score layer.
        requested_size_usd:
            Required proposed entry notional after upstream sizing logic.
        authoritative_position_proven:
            Hard safety gate; when False, entry is rejected before risk checks.

        Returns
        -------
        Optional[CompiledSignal]
            Execution-ready compiled signal when every stage passes, else None.
        """
        checks = checks or {}
        score_context = score_context or {}
        try:
            verify_snapshot_ownership(trading_context, risk_snapshot)
        except ValueError as exc:
            logger.warning("PIPELINE_REJECT stage=context reason=%s", exc)
            return None
        if broker.strip().lower() != trading_context.broker:
            logger.warning("PIPELINE_REJECT stage=context reason=broker_mismatch_with_trading_context")
            return None
        if df is None or df.empty:
            return None
        regime_full = self._regime_engine.detect(symbol, df)
        regime_result = regime_full.regime
        regime = getattr(regime_result, "value", regime_result)
        regime = str(regime)

        try:
            owned_positions = risk_snapshot.positions_for_owner()
        except ValueError as exc:
            logger.warning("PIPELINE_REJECT stage=situation reason=%s", exc)
            return None
        situation = self._situation_engine.assess(
            trading_context=trading_context,
            regime_result=regime_full,
            positions=owned_positions,
            checks=checks,
            authoritative_position_proven=authoritative_position_proven,
        )
        if not situation.eligible_for_strategy_evaluation:
            logger.warning(
                "PIPELINE_REJECT stage=situation symbol=%s reasons=%s",
                symbol,
                situation.reasons,
            )
            return None

        candidates = self._detector_registry.detect(
            df=df,
            symbol=symbol,
            broker=broker,
            market_regime=regime,
            trading_context=trading_context,
        )
        if not candidates:
            return None

        ranked: List[tuple[StrategySignal, float]] = []
        for candidate in candidates:
            score_result = self._scoring_engine.score(candidate, score_context)
            if score_result.rejected:
                continue
            confirm = self._confirmation_engine.confirm(
                candidate,
                score=score_result.score,
                checks=checks,
            )
            if not confirm.approved:
                logger.info(
                    "CONFIRMATION_FAIL symbol=%s strategy=%s reasons=%s",
                    candidate.symbol,
                    candidate.strategy,
                    confirm.reasons,
                )
                continue
            ranked.append((candidate, score_result.score))

        if not ranked:
            return None
        best_signal, best_score = max(ranked, key=lambda row: row[1])
        strategy_signal_id = best_signal.strategy_signal_id
        if best_signal.trading_context.scope_key != trading_context.scope_key:
            logger.warning("PIPELINE_REJECT stage=context reason=detector_context_mismatch")
            return None
        try:
            requested_size = float(requested_size_usd or 0.0)
        except (TypeError, ValueError):
            requested_size = 0.0
        if requested_size <= 0:
            logger.warning(
                "SIGNAL_REJECTED_INVALID_SIZE symbol=%s strategy=%s reason=requested_size_usd_missing_or_non_positive",
                best_signal.symbol,
                best_signal.strategy,
            )
            return None
        stop_loss_pct, take_profit_pct = self._canonical_protection_percentages(
            best_signal,
            df,
        )
        if best_signal.strategy.strip().upper() == "BREAK_RETEST" and (
            stop_loss_pct is None or take_profit_pct is None
        ):
            logger.warning(
                "SIGNAL_REJECTED_PROTECTION_UNPROVEN symbol=%s strategy=%s",
                best_signal.symbol,
                best_signal.strategy,
            )
            return None
        try:
            entry_price = float(df["close"].iloc[-1])
        except Exception:
            entry_price = 0.0
        stop_loss_pct: Optional[float] = None
        take_profit_pct: Optional[float] = None
        if entry_price <= 0:
            logger.warning("PIPELINE_REJECT stage=protection reason=entry_price_unavailable")
            return None
        if best_signal.suggested_stop is not None:
            stop = float(best_signal.suggested_stop)
            if best_signal.direction == "long" and stop >= entry_price:
                logger.warning("PIPELINE_REJECT stage=protection reason=invalid_long_stop")
                return None
            if best_signal.direction == "short" and stop <= entry_price:
                logger.warning("PIPELINE_REJECT stage=protection reason=invalid_short_stop")
                return None
            stop_loss_pct = abs(entry_price - stop) / entry_price
        if best_signal.target_candidates:
            target = float(best_signal.target_candidates[0])
            if best_signal.direction == "long" and target <= entry_price:
                logger.warning("PIPELINE_REJECT stage=protection reason=invalid_long_target")
                return None
            if best_signal.direction == "short" and target >= entry_price:
                logger.warning("PIPELINE_REJECT stage=protection reason=invalid_short_target")
                return None
            take_profit_pct = abs(target - entry_price) / entry_price

        raw = RawSignal(
            symbol=best_signal.symbol,
            side="buy" if best_signal.direction == "long" else "sell",
            action="enter_long" if best_signal.direction == "long" else "enter_short",
            size_usd=requested_size,
            confidence=best_score,
            regime=best_signal.market_regime,
            strategy=best_signal.strategy,
            user_id=trading_context.user_id,
            account_id=trading_context.trading_account_id,
            broker=trading_context.broker,
            portfolio_id=trading_context.portfolio_id,
            strategy_signal_id=strategy_signal_id,
            trade_id=trading_context.request_id,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
            trading_context=trading_context,
            metadata={
                **best_signal.to_dict(),
                "signal_score": best_score,
            },
            execution_mode=trading_context.mode,
        )
        return self.process_signal(
            raw_signal=raw,
            df=df,
            risk_snapshot=risk_snapshot,
            authoritative_position_proven=authoritative_position_proven,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process_signal(
        self,
        raw_signal: RawSignal,
        df: Optional[pd.DataFrame] = None,
        decision_context: Optional[UserDecisionContext] = None,
        portfolio_snapshot: Optional[UserPortfolioSnapshot] = None,
        current_positions: Optional[List[Dict[str, Any]]] = None,
        portfolio_value_usd: float = 10_000.0,
        peak_portfolio_value: Optional[float] = None,
        daily_pnl: float = 0.0,
        max_position_size_pct: float = 10.0,
        available_balance_usd: Optional[float] = None,
        authoritative_position_proven: bool = True,
        risk_snapshot: Optional[ScopedRiskSnapshot] = None,
    ) -> Optional[CompiledSignal]:
        """
        Run the full signal processing pipeline.

        Parameters
        ----------
        raw_signal           : Unvalidated signal from any source.
        df                   : OHLCV DataFrame for regime detection.
                               If None, regime detection is skipped.
        current_positions    : List of open position dicts.
        portfolio_value_usd  : Current portfolio value.
        peak_portfolio_value : All-time high portfolio value (for drawdown).
        daily_pnl            : Today's realised + unrealised P&L.
        max_position_size_pct: Maximum position size as % of portfolio.
        available_balance_usd: Tradable balance to verify against order minimums.

        Returns
        -------
        CompiledSignal if approved, None if rejected.
        """
        import time as _time

        trading_context = raw_signal.trading_context
        if trading_context is None and decision_context is not None:
            try:
                trading_context = self._trading_context_from_decision_context(raw_signal, decision_context)
                raw_signal = replace(raw_signal, trading_context=trading_context)
            except ValueError as exc:
                logger.warning("PIPELINE_REJECT stage=context reason=%s", exc)
                return None
        if trading_context is None:
            logger.warning("PIPELINE_REJECT stage=context reason=missing_trading_context")
            return None
        scalar_context_error = self._validate_raw_context_alignment(raw_signal, trading_context)
        if scalar_context_error:
            logger.warning("PIPELINE_REJECT stage=context reason=%s", scalar_context_error)
            return None
        if self._context_authorizer is not None:
            try:
                context_authorized = bool(self._context_authorizer(trading_context))
            except Exception as exc:
                logger.warning("PIPELINE_REJECT stage=context reason=context_authorizer_error:%s", type(exc).__name__)
                return None
            if not context_authorized:
                logger.warning("PIPELINE_REJECT stage=context reason=context_not_authorized")
                return None
        elif str(trading_context.mode or "").strip().lower() in {"live", "limited_live"}:
            logger.warning("PIPELINE_REJECT stage=context reason=live_context_authorizer_required")
            return None
        if risk_snapshot is not None and portfolio_snapshot is not None:
            logger.warning("PIPELINE_REJECT stage=context reason=ambiguous_risk_snapshot")
            return None

        decision_identity = self._resolve_decision_context(raw_signal, decision_context)
        if decision_identity is not None:
            context_notes = decision_identity.validate_for_entry()
            context_notes.extend(self._decision_context_alignment_notes(decision_identity, trading_context))
        else:
            context_notes = []

        snapshot = portfolio_snapshot
        if snapshot is not None:
            if decision_identity is None:
                context_notes.append("USER_CONTEXT_UNPROVEN:missing_context")
            else:
                context_notes.extend(snapshot.validate_for_context(decision_identity))
                context_notes.extend(snapshot.readiness_notes(symbol=raw_signal.symbol, direction=raw_signal.side))
            if context_notes:
                logger.warning("PIPELINE_REJECT stage=context reason=%s", context_notes)
                return None
            scoped_positions = []
            for position in snapshot.open_positions:
                scoped = dict(position)
                scoped.update({
                    "user_id": trading_context.user_id,
                    "trading_account_id": trading_context.trading_account_id,
                    "broker": trading_context.broker,
                    "broker_account_id": trading_context.broker_account_id,
                })
                scoped_positions.append(scoped)
            risk_snapshot = ScopedRiskSnapshot.from_values(
                context=trading_context,
                portfolio_value_usd=float(snapshot.equity or 0.0),
                current_positions=scoped_positions,
                daily_pnl=float(snapshot.daily_realized_pnl + snapshot.daily_unrealized_pnl),
                peak_portfolio_value=snapshot.peak_equity,
                available_balance_usd=snapshot.available_buying_power,
            )

        if risk_snapshot is None and str(trading_context.mode or "").strip().lower() in {"live", "limited_live"}:
            logger.warning("PIPELINE_REJECT stage=context reason=live_risk_snapshot_required")
            return None
        if risk_snapshot is not None:
            try:
                verify_snapshot_ownership(trading_context, risk_snapshot)
                positions = list(risk_snapshot.positions_for_owner())
            except ValueError as exc:
                logger.warning("PIPELINE_REJECT stage=context reason=%s", exc)
                return None
            portfolio_value_usd = float(risk_snapshot.portfolio_value_usd)
            peak_portfolio_value = risk_snapshot.peak_portfolio_value
            daily_pnl = float(risk_snapshot.daily_pnl)
            available_balance_usd = risk_snapshot.available_balance_usd
        else:
            positions = current_positions or []
        pipeline_id = str(uuid.uuid4())
        audit: Dict[str, Any] = {
            "pipeline_id":  pipeline_id,
            "symbol":       raw_signal.symbol,
            "action":       raw_signal.action,
            "strategy":     raw_signal.strategy,
            "started_at":   datetime.now(timezone.utc).isoformat(),
            "stages":       {},
        }
        if decision_context is not None:
            audit["decision_context"] = {
                "user_id": decision_context.user_id,
                "account_id": decision_context.account_id,
                "broker": decision_context.broker,
                "portfolio_id": decision_context.portfolio_id,
                "strategy_signal_id": decision_context.strategy_signal_id,
                "trade_id": decision_context.trade_id,
            }

        if decision_context is not None and decision_identity is None:
            audit["stages"]["context"] = {"approved": False, "notes": ["USER_CONTEXT_MISMATCH"]}
            audit["final_decision"] = "rejected"
            audit["rejection_stage"] = "context"
            self._record(accepted=False)
            self._store_pipeline_audit(pipeline_id, audit)
            return None
        duplicate_key: Optional[str] = None
        duplicate_token: Optional[str] = None
        duplicate_handle: Optional[IdempotencyReservationHandle] = None
        if decision_identity is not None:
            if context_notes:
                audit["stages"]["context"] = {"approved": False, "notes": context_notes}
                audit["final_decision"] = "rejected"
                audit["rejection_stage"] = "context"
                self._record(accepted=False)
                self._store_pipeline_audit(pipeline_id, audit)
                logger.warning(
                    "PIPELINE_REJECT stage=context symbol=%s action=%s notes=%s",
                    raw_signal.symbol,
                    raw_signal.action,
                    context_notes,
                )
                return None
            audit["stages"]["context"] = {"approved": True, "notes": ["context_verified"]}
            duplicate_allowed, duplicate_handle = self._idempotency_registry.reserve(
                decision_identity,
                symbol=raw_signal.symbol,
                direction=self._duplicate_direction(raw_signal),
            )
            audit["stages"]["duplicate"] = {
                "approved": duplicate_allowed,
                "key": duplicate_handle.key,
            }
            if not duplicate_allowed:
                audit["final_decision"] = "rejected"
                audit["rejection_stage"] = "duplicate"
                self._record(accepted=False)
                self._store_pipeline_audit(pipeline_id, audit)
                logger.warning(
                    "PIPELINE_REJECT stage=duplicate symbol=%s account=%s key=%s",
                    raw_signal.symbol,
                    decision_identity.account_id,
                    duplicate_handle.key,
                )
                return None

        # ── Pre-flight: Live market feed heartbeat ───────────────────────
        self._check_feed_heartbeat(raw_signal.symbol)

        # ── Pre-flight: Tradable balance vs order minimum ────────────────
        if available_balance_usd is not None:
            self._check_tradable_balance(raw_signal.symbol, available_balance_usd)

        # ── Stage 1: Regime Detection ────────────────────────────────────
        regime_result: Optional[RegimeResult] = None
        if df is not None and not df.empty:
            try:
                regime_result = self._regime_engine.detect(raw_signal.symbol, df)
                audit["stages"]["regime"] = {
                    "regime":     regime_result.regime.value,
                    "confidence": regime_result.confidence,
                    "adx":        regime_result.adx,
                    "rsi":        regime_result.rsi,
                }
                # Inject detected regime into the raw signal
                if _INJECT_DETECTED_REGIME and regime_result.regime.value != "unknown":
                    raw_signal = RawSignal(
                        symbol=raw_signal.symbol,
                        side=raw_signal.side,
                        action=raw_signal.action,
                        size_usd=raw_signal.size_usd,
                        confidence=raw_signal.confidence,
                        regime=regime_result.regime.value,
                        strategy=raw_signal.strategy,
                        user_id=raw_signal.user_id,
                        account_id=raw_signal.account_id,
                        broker=raw_signal.broker,
                        portfolio_id=raw_signal.portfolio_id,
                        strategy_signal_id=raw_signal.strategy_signal_id,
                        trade_id=raw_signal.trade_id,
                        approved=raw_signal.approved,
                        stop_loss_pct=raw_signal.stop_loss_pct,
                        take_profit_pct=raw_signal.take_profit_pct,
                        execution_mode=raw_signal.execution_mode,
                        asset_class=raw_signal.asset_class,
                        metadata=raw_signal.metadata,
                        trading_context=raw_signal.trading_context,
                    )
            except Exception as exc:
                logger.warning("SignalPipeline: regime detection failed: %s", exc)
                audit["stages"]["regime"] = {"error": str(exc)}
        else:
            audit["stages"]["regime"] = {"skipped": "no_dataframe"}

        # ── Stage 2: Compile Signal ──────────────────────────────────────
        compiled, compile_notes = self._compiler.compile(
            raw_signal,
            portfolio_value_usd=portfolio_value_usd,
            max_position_size_pct=max_position_size_pct,
        )
        audit["stages"]["compile"] = {
            "accepted": compiled is not None,
            "notes":    compile_notes,
        }

        if compiled is None:
            # No broker submission occurred. Release the admission reservation so
            # a corrected retry is not falsely treated as an already-submitted
            # order. Reservations remain held only after an approved handoff.
            if decision_identity is not None and duplicate_handle:
                self._idempotency_registry.release(duplicate_handle)
            audit["final_decision"] = "rejected"
            audit["rejection_stage"] = "compile"
            self._record(accepted=False)
            self._store_pipeline_audit(pipeline_id, audit)
            logger.warning(
                "PIPELINE_REJECT stage=compile symbol=%s action=%s confidence=%.3f notes=%s",
                raw_signal.symbol, raw_signal.action, raw_signal.confidence, compile_notes,
            )
            return None

        # Reserve only after all pre-submission compilation work succeeds. This
        # keeps the short admission TTL through handoff and prevents compiler or
        # market-data exceptions from stranding a live intent for the uncertainty
        # window even though no broker dispatch occurred.
        if decision_identity is not None:
            duplicate_allowed, duplicate_key, duplicate_token = self._idempotency_registry.reserve(
                decision_identity,
                symbol=compiled.symbol,
                direction=self._duplicate_direction(raw_signal),
            )
            audit["stages"]["duplicate"] = {
                "approved": duplicate_allowed,
                "key": duplicate_key,
            }
            if not duplicate_allowed:
                audit["final_decision"] = "rejected"
                audit["rejection_stage"] = "duplicate"
                self._record(accepted=False)
                self._store_pipeline_audit(pipeline_id, audit)
                logger.warning(
                    "PIPELINE_REJECT stage=duplicate symbol=%s account=%s key=%s",
                    compiled.symbol,
                    decision_identity.account_id,
                    duplicate_key,
                )
                return None

        try:
            audit["context"] = compiled.trading_context.to_log_fields()
            # ── Stage 3: Risk Validation ─────────────────────────────────────
            risk_approved, risk_notes = self._risk_engine.validate_trade(
                symbol=compiled.symbol,
                side=compiled.side,
                size_usd=compiled.size_usd,
                portfolio_value_usd=portfolio_value_usd,
                current_positions=positions,
                authoritative_position_proven=authoritative_position_proven,
                daily_pnl=daily_pnl,
                peak_portfolio_value=peak_portfolio_value,
                available_balance_usd=available_balance_usd,
                trading_context=compiled.trading_context,
                enforce_isolation=True,
            )
            audit["stages"]["risk"] = {
                "approved": risk_approved,
                "notes":    risk_notes,
            }
            if not risk_approved:
                if decision_identity is not None and duplicate_key and duplicate_token:
                    self._idempotency_registry.release(duplicate_key, token=duplicate_token)
                if decision_identity is not None:
                    self._idempotency_registry.release(duplicate_handle)
                audit["final_decision"] = "rejected"
                audit["rejection_stage"] = "risk"
                self._record(accepted=False)
                self._store_pipeline_audit(pipeline_id, audit)
                logger.warning(
                    "PIPELINE_REJECT stage=risk symbol=%s side=%s size_usd=%.2f user_id=%s account_id=%s notes=%s",
                    compiled.symbol,
                    compiled.side,
                    compiled.size_usd,
                    compiled.trading_context.user_id,
                    compiled.trading_context.trading_account_id,
                    risk_notes,
                )
                return None

            # ── Approved ─────────────────────────────────────────────────────
            audit["final_decision"] = "approved"
            audit["signal_id"] = compiled.signal_id
            if decision_identity is not None:
                # Keep the reservation through the downstream execution handoff.
                # The execution/reconciliation owner must call
                # mark_duplicate_execution_complete() once submission state is known.
                compiled.metadata["duplicate_key"] = duplicate_key
                compiled.metadata["duplicate_token"] = duplicate_token
                compiled.metadata.update(duplicate_handle.to_metadata())
            self._record(accepted=True)
            with self._lock:
                self._last_approved_ts[compiled.trading_context.scope_key] = _time.time()
            self._store_pipeline_audit(pipeline_id, audit)
            logger.info(
                "PIPELINE_APPROVED symbol=%s side=%s size_usd=%.2f regime=%s confidence=%.3f user_id=%s "
                "account_id=%s",
                compiled.symbol,
                compiled.side,
                compiled.size_usd,
                compiled.regime,
                compiled.confidence,
                compiled.trading_context.user_id,
                compiled.trading_context.trading_account_id,
            )
            return compiled
        except Exception:
            if decision_identity is not None and duplicate_key and duplicate_token:
                self._idempotency_registry.release(duplicate_key, token=duplicate_token)
            if decision_identity is not None:
                self._idempotency_registry.release(duplicate_handle)
            raise

    @staticmethod
    def _resolve_decision_context(
        raw_signal: RawSignal,
        decision_context: Optional[UserDecisionContext],
    ) -> Optional[UserDecisionContext]:
        """Resolve decision metadata only from an explicit or authoritative context."""
        if decision_context is not None:
            tc = raw_signal.trading_context
            if tc is not None:
                if tc.user_id != decision_context.user_id:
                    return None
                if tc.trading_account_id != decision_context.account_id:
                    return None
                if tc.broker.lower() != decision_context.broker.lower():
                    return None
                if tc.portfolio_id != decision_context.portfolio_id:
                    return None
            if raw_signal.strategy_signal_id and decision_context.strategy_signal_id != raw_signal.strategy_signal_id:
                return None
            if raw_signal.trade_id and decision_context.trade_id != raw_signal.trade_id:
                return None
            if raw_signal.user_id and raw_signal.user_id != decision_context.user_id:
                return None
            if raw_signal.account_id and raw_signal.account_id != "default" and raw_signal.account_id != decision_context.account_id:
                return None
            if raw_signal.broker and raw_signal.broker.lower() != decision_context.broker.lower():
                return None
            if raw_signal.portfolio_id and raw_signal.portfolio_id != decision_context.portfolio_id:
                return None
            return decision_context

        # Deriving the compatibility decision shape from TradingContext is safe:
        # the immutable context remains the sole authority for owner scope.
        if raw_signal.trading_context is not None:
            tc = raw_signal.trading_context
            if raw_signal.user_id and raw_signal.user_id != tc.user_id:
                return None
            if raw_signal.account_id and raw_signal.account_id != "default" and raw_signal.account_id != tc.trading_account_id:
                return None
            if raw_signal.broker and raw_signal.broker.lower() != tc.broker.lower():
                return None
            if raw_signal.portfolio_id and raw_signal.portfolio_id != tc.portfolio_id:
                return None
            return UserDecisionContext(
                user_id=tc.user_id,
                account_id=tc.trading_account_id,
                broker=tc.broker,
                portfolio_id=tc.portfolio_id,
                strategy_signal_id=raw_signal.strategy_signal_id or tc.strategy_instance_id,
                trade_id=raw_signal.trade_id or tc.decision_id or tc.request_id,
                execution_mode=raw_signal.execution_mode or tc.mode,
                environment=tc.environment,
                asset_class=raw_signal.asset_class,
                correlation_id=tc.correlation_id,
            )
        return None

    @staticmethod
    def _trading_context_from_decision_context(
        raw_signal: RawSignal,
        decision_context: UserDecisionContext,
    ) -> TradingContext:
        """Convert the older public decision contract at the pipeline boundary."""
        mode = str(decision_context.execution_mode or "paper").strip().lower()
        if mode == "test":
            mode = "paper"
        environment = str(
            decision_context.environment
            or ("production" if mode in {"live", "limited_live"} else "test")
        ).strip()
        return TradingContext(
            user_id=decision_context.user_id,
            trading_account_id=decision_context.account_id,
            broker=decision_context.broker,
            broker_account_id=decision_context.account_id,
            strategy_instance_id=(
                str(raw_signal.strategy or "").strip()
                or str(decision_context.risk_profile_id or "").strip()
                or "v2_strategy"
            ),
            portfolio_id=decision_context.portfolio_id,
            request_id=decision_context.trade_id,
            correlation_id=decision_context.correlation_id or decision_context.trade_id,
            environment=environment,
            mode=mode,
            decision_id=decision_context.trade_id,
        )

    @staticmethod
    def _validate_raw_context_alignment(
        raw_signal: RawSignal,
        context: TradingContext,
    ) -> Optional[str]:
        comparisons = {
            "user_id": (raw_signal.user_id, context.user_id),
            "account_id": (raw_signal.account_id, context.trading_account_id),
            "broker": (raw_signal.broker.lower(), context.broker),
            "portfolio_id": (raw_signal.portfolio_id, context.portfolio_id),
        }
        for name, (raw_value, expected) in comparisons.items():
            value = str(raw_value or "").strip()
            if name == "account_id" and value == "default":
                value = ""
            if value and value != str(expected).strip():
                return f"{name}_mismatch_with_trading_context"
        return None

    @staticmethod
    def _decision_context_alignment_notes(
        decision_context: UserDecisionContext,
        trading_context: TradingContext,
    ) -> List[str]:
        expected = (
            trading_context.user_id,
            trading_context.trading_account_id,
            trading_context.broker,
            trading_context.portfolio_id,
        )
        actual = (
            decision_context.user_id,
            decision_context.account_id,
            decision_context.broker.lower(),
            decision_context.portfolio_id,
        )
        if actual != expected:
            return ["USER_CONTEXT_UNPROVEN:trading_context_mismatch"]
        return []

    @staticmethod
    def _duplicate_direction(raw_signal: RawSignal) -> str:
        side = str(raw_signal.side or "").lower()
        action = str(raw_signal.action or "").lower()
        if side in {"buy", "long"} or action == "enter_long":
            return "long"
        if side in {"sell", "short"} or action == "enter_short":
            return "short"
        return side or action or "unknown"

    @staticmethod
    def _canonical_protection_percentages(
        signal: StrategySignal,
        df: pd.DataFrame,
    ) -> tuple[Optional[float], Optional[float]]:
        """Convert absolute detector protection levels into execution fractions."""
        if df is None or df.empty:
            return None, None
        try:
            entry = float(df["close"].iloc[-1])
            stop = float(signal.suggested_stop)
            targets = [float(value) for value in signal.target_candidates]
        except (KeyError, TypeError, ValueError):
            return None, None
        if not math.isfinite(entry) or not math.isfinite(stop) or entry <= 0:
            return None, None
        targets = [value for value in targets if math.isfinite(value) and value > 0]
        direction = str(signal.direction or "").strip().lower()
        if direction == "long":
            valid_targets = [value for value in targets if value > entry]
            if stop <= 0 or stop >= entry or not valid_targets:
                return None, None
        elif direction == "short":
            valid_targets = [value for value in targets if value < entry]
            if stop <= entry or not valid_targets:
                return None, None
        else:
            return None, None
        nearest_target = min(valid_targets, key=lambda value: abs(value - entry))
        return abs(entry - stop) / entry, abs(nearest_target - entry) / entry

    def mark_duplicate_execution_complete(
        self,
        duplicate_key: str,
        duplicate_token: str,
        *,
        state: str = "released",
    ) -> None:
        """Finalize a duplicate reservation after downstream execution reconciliation."""
        if not duplicate_key or not duplicate_token:
            return
        if state == "released":
            self._idempotency_registry.release(duplicate_key, token=duplicate_token)
            return
        self._idempotency_registry.mark_state(duplicate_key, state, token=duplicate_token)
        """Finalize a reservation only with the exact ownership token."""
        handle = IdempotencyReservationHandle(
            str(duplicate_key or "").strip(),
            str(duplicate_token or "").strip(),
        )
        if not handle:
            return
        if state == "released":
            self._idempotency_registry.release(handle)
            return
        self._idempotency_registry.mark_state(handle, state)

    # ------------------------------------------------------------------
    # Diagnostic helpers
    # ------------------------------------------------------------------

    def inject_diagnostic_trade_if_idle(
        self,
        *,
        trading_context: TradingContext,
        risk_snapshot: ScopedRiskSnapshot,
    ) -> Optional[CompiledSignal]:
        """
        When NIJA_DIAGNOSTIC_TRADE_ENABLED=true and no signal has been approved
        in the last NIJA_DIAG_TRADE_IDLE_SECONDS, inject a minimal synthetic
        test signal to verify the execution wiring end-to-end.

        The diagnostic signal does NOT bypass any gate — it uses full confidence
        (1.0) so it will clear the confidence floor, but all other checks (risk,
        balance, ECEL) still apply.  This surfaces the real choke point.
        """
        import time as _time

        if not _DIAGNOSTIC_TRADE_ENABLED:
            return None

        with self._lock:
            last_ts = self._last_approved_ts.get(trading_context.scope_key, 0.0)

        idle_s = _time.time() - last_ts
        if idle_s < _DIAGNOSTIC_TRADE_IDLE_SECONDS:
            return None

        logger.warning(
            "DIAGNOSTIC_TRADE_INJECT idle_seconds=%.0f symbol=%s size_usd=%.2f "
            "— no approved signal in last %.0fs; injecting synthetic probe",
            idle_s,
            _DIAGNOSTIC_TRADE_SYMBOL,
            _DIAGNOSTIC_TRADE_SIZE_USD,
            _DIAGNOSTIC_TRADE_IDLE_SECONDS,
        )
        diag_signal = RawSignal(
            symbol=_DIAGNOSTIC_TRADE_SYMBOL,
            side="buy",
            action="enter_long",
            size_usd=_DIAGNOSTIC_TRADE_SIZE_USD,
            confidence=1.0,
            regime="unknown",
            strategy="diagnostic",
            account_id=trading_context.trading_account_id,
            approved=True,
            metadata={"diagnostic": True},
            trading_context=trading_context,
        )
        return self.process_signal(
            diag_signal,
            risk_snapshot=risk_snapshot,
        )

    @staticmethod
    def _check_feed_heartbeat(symbol: str) -> None:
        """Log a WARNING when the market feed for *symbol* is stale."""
        try:
            from bot.market_data_engine import get_market_data_engine
            engine = get_market_data_engine()
            health = engine.get_health()
            sym_health = health.get("symbols", {}).get(symbol.upper(), {})
            if sym_health:
                if sym_health.get("is_stale"):
                    last_bar_utc = sym_health.get("last_bar_utc") or "never"
                    logger.warning(
                        "FEED_HEARTBEAT_STALE symbol=%s last_bar=%s — market data may be stale",
                        symbol, last_bar_utc,
                    )
                else:
                    logger.debug("FEED_HEARTBEAT_OK symbol=%s", symbol)
            else:
                # Symbol not yet registered in the engine — first-scan or unregistered pair
                logger.warning(
                    "FEED_HEARTBEAT_MISSING symbol=%s — no bar data registered in MarketDataEngine",
                    symbol,
                )
        except Exception as exc:
            logger.debug("SignalPipeline: feed heartbeat check skipped: %s", exc)

    @staticmethod
    def _check_tradable_balance(symbol: str, available_balance_usd: float) -> None:
        """Log a WARNING when available balance may be below exchange order minimums."""
        # Known minimum notionals per broker — fall back to a conservative $1.00
        _MIN_NOTIONAL_COINBASE = 1.0
        _MIN_NOTIONAL_KRAKEN = 10.0

        min_required = max(_MIN_NOTIONAL_COINBASE, _MIN_NOTIONAL_KRAKEN)
        try:
            from bot.ecel_execution_compiler import get_ecel_execution_compiler
            ecel = get_ecel_execution_compiler()
            # Try to find a matching rule for this symbol
            for broker in ("coinbase", "kraken"):
                rule = ecel.schema.get_rule(broker, symbol)
                if rule is not None:
                    min_required = min(min_required, rule.min_notional_usd)
                    break
        except Exception:
            pass

        if available_balance_usd < min_required:
            logger.warning(
                "BALANCE_BELOW_MIN symbol=%s available_balance=%.4f USD min_notional=%.2f USD "
                "— order will be rejected by ECEL; top up account or lower size",
                symbol, available_balance_usd, min_required,
            )
        else:
            logger.debug(
                "BALANCE_OK symbol=%s available_balance=%.4f USD min_notional=%.2f USD",
                symbol, available_balance_usd, min_required,
            )

    def process_dict(
        self,
        signal_dict: Dict[str, Any],
        df: Optional[pd.DataFrame] = None,
        current_positions: Optional[List[Dict[str, Any]]] = None,
        portfolio_value_usd: float = 10_000.0,
        **kwargs,
    ) -> Optional[CompiledSignal]:
        """Convenience wrapper: process a raw signal dict."""
        action = str(signal_dict.get("action") or signal_dict.get("side") or "hold").lower()
        if action in ("buy", "long"):
            action = "enter_long"
        elif action in ("sell", "short"):
            action = "enter_short"

        side = str(signal_dict.get("side") or "")
        if side in ("long", "enter_long"):
            side = "buy"
        elif side in ("short", "enter_short"):
            side = "sell"

        raw = RawSignal(
            symbol=str(signal_dict.get("symbol") or ""),
            side=side,
            action=action,
            size_usd=float(signal_dict.get("size_usd") or 0.0),
            confidence=float(signal_dict.get("confidence") or 0.0),
            regime=str(signal_dict.get("regime") or "unknown"),
            strategy=str(signal_dict.get("strategy") or ""),
            account_id=str(signal_dict.get("account_id") or "default"),
            approved=bool(signal_dict.get("approved", True)),
            stop_loss_pct=signal_dict.get("stop_loss_pct"),
            take_profit_pct=signal_dict.get("take_profit_pct"),
            metadata=dict(signal_dict),
            trading_context=None,
        )
        try:
            raw = RawSignal(
                symbol=raw.symbol,
                side=raw.side,
                action=raw.action,
                size_usd=raw.size_usd,
                confidence=raw.confidence,
                regime=raw.regime,
                strategy=raw.strategy,
                account_id=raw.account_id,
                approved=raw.approved,
                stop_loss_pct=raw.stop_loss_pct,
                take_profit_pct=raw.take_profit_pct,
                metadata=raw.metadata,
                trading_context=self._context_from_signal_dict(signal_dict),
            )
        except ValueError as exc:
            pipeline_id = str(uuid.uuid4())
            audit_context = self._context_audit_from_signal_dict(signal_dict)
            audit = {
                "pipeline_id": pipeline_id,
                "symbol": raw.symbol,
                "action": raw.action,
                "strategy": raw.strategy,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "context": audit_context,
                "stages": {"context": {"error": str(exc)}},
                "final_decision": "rejected",
                "rejection_stage": "context",
            }
            self._record(accepted=False)
            self._store_pipeline_audit(pipeline_id, audit)
            logger.warning("PIPELINE_REJECT stage=context reason=%s", exc)
            return None
        return self.process_signal(
            raw,
            df=df,
            current_positions=current_positions,
            portfolio_value_usd=portfolio_value_usd,
            **kwargs,
        )

    # ------------------------------------------------------------------
    # Observability
    # ------------------------------------------------------------------

    def get_health(self) -> Dict[str, Any]:
        with self._lock:
            total    = self._total
            approved = self._approved
            rejected = self._rejected
        return {
            "available":    True,
            "total":        total,
            "approved":     approved,
            "rejected":     rejected,
            "approval_rate": round(approved / total, 4) if total > 0 else 1.0,
            "compiler":     self._compiler.get_health(),
            "risk_engine":  self._risk_engine.get_health(),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _record(self, accepted: bool) -> None:
        with self._lock:
            self._total += 1
            if accepted:
                self._approved += 1
            else:
                self._rejected += 1

    def _store_pipeline_audit(
        self,
        pipeline_id: str,
        audit: Dict[str, Any],
    ) -> None:
        if self._redis is None:
            return
        try:
            context = audit.get("context") or {}
            try:
                scope_token = TradingContext.from_mapping(context).scope_key[:16]
            except (TypeError, ValueError):
                encoded = json.dumps(context, sort_keys=True, separators=(",", ":")).encode("utf-8")
                scope_token = hashlib.sha256(encoded).hexdigest()[:16]
            key = f"nija:control:pipeline:{scope_token}:{pipeline_id}"
            audit["stored_at"] = datetime.now(timezone.utc).isoformat()
            self._redis.setex(key, _SIGNAL_REDIS_TTL, json.dumps(audit))
        except Exception as exc:
            logger.debug("SignalPipeline: Redis audit store failed: %s", exc)

    @staticmethod
    def _context_from_signal_dict(signal_dict: Dict[str, Any]) -> Optional[TradingContext]:
        context_raw = signal_dict.get("trading_context")
        if isinstance(context_raw, TradingContext):
            context = context_raw
        elif isinstance(context_raw, dict):
            try:
                context = TradingContext.from_mapping(context_raw)
            except Exception as exc:
                raise ValueError(f"malformed_trading_context:{exc}") from exc
        else:
            raise ValueError("missing_trading_context")
        account_id = str(signal_dict.get("account_id") or "").strip().lower()
        if account_id and account_id != str(context.trading_account_id).strip().lower():
            raise ValueError("account_id_mismatch_with_trading_context")
        return context

    @staticmethod
    def _context_audit_from_signal_dict(signal_dict: Dict[str, Any]) -> Dict[str, str]:
        raw = signal_dict.get("trading_context")
        if isinstance(raw, TradingContext):
            return raw.to_log_fields()
        if isinstance(raw, dict):
            return {
                "user_id": str(raw.get("user_id") or "unknown"),
                "trading_account_id": str(raw.get("trading_account_id") or "unknown"),
                "broker": str(raw.get("broker") or "unknown"),
                "broker_account_id": str(raw.get("broker_account_id") or "unknown"),
                "strategy_instance_id": str(raw.get("strategy_instance_id") or "unknown"),
                "portfolio_id": str(raw.get("portfolio_id") or ""),
                "request_id": str(raw.get("request_id") or ""),
                "correlation_id": str(raw.get("correlation_id") or ""),
                "environment": str(raw.get("environment") or ""),
                "mode": str(raw.get("mode") or ""),
                "decision_id": str(raw.get("decision_id") or ""),
            }
        return {
            "user_id": "unknown",
            "trading_account_id": "unknown",
            "broker": "unknown",
            "broker_account_id": "unknown",
            "strategy_instance_id": "unknown",
            "portfolio_id": "",
            "request_id": "",
            "correlation_id": "",
            "environment": "",
            "mode": "",
            "decision_id": "",
        }


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_singleton: Optional[SignalPipeline] = None
_singleton_lock = threading.Lock()


def get_signal_pipeline(
    compiler: Optional[ControlCompiler] = None,
    regime_engine: Optional[RegimeEngine] = None,
    risk_engine: Optional[RiskEngine] = None,
    redis_client=None,
    context_authorizer: Optional[Callable[[TradingContext], bool]] = None,
) -> SignalPipeline:
    """Return the process-level SignalPipeline singleton."""
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                _singleton = SignalPipeline(
                    compiler=compiler,
                    regime_engine=regime_engine,
                    risk_engine=risk_engine,
                    redis_client=redis_client,
                    context_authorizer=context_authorizer,
                )
    return _singleton
