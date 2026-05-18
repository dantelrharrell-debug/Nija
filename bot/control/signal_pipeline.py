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

import json
import logging
import os
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pandas as pd

from bot.control.control_compiler import (
    ControlCompiler,
    CompiledSignal,
    RawSignal,
    get_control_compiler,
)
from bot.control.regime_engine import (
    RegimeEngine,
    RegimeResult,
    get_regime_engine,
)
from bot.control.risk_engine import (
    RiskEngine,
    get_risk_engine,
)

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
    ) -> None:
        self._compiler      = compiler      or get_control_compiler(redis_client)
        self._regime_engine = regime_engine or get_regime_engine(redis_client)
        self._risk_engine   = risk_engine   or get_risk_engine(redis_client)
        self._redis         = redis_client
        self._lock          = threading.Lock()

        # Session counters
        self._total:    int = 0
        self._approved: int = 0
        self._rejected: int = 0

        # Diagnostic trade tracking
        self._last_approved_ts: float = 0.0

        logger.info(
            "SignalPipeline initialised | diagnostic_trade=%s idle_threshold=%.0fs",
            _DIAGNOSTIC_TRADE_ENABLED, _DIAGNOSTIC_TRADE_IDLE_SECONDS,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process_signal(
        self,
        raw_signal: RawSignal,
        df: Optional[pd.DataFrame] = None,
        current_positions: Optional[List[Dict[str, Any]]] = None,
        portfolio_value_usd: float = 10_000.0,
        peak_portfolio_value: Optional[float] = None,
        daily_pnl: float = 0.0,
        max_position_size_pct: float = 10.0,
        available_balance_usd: Optional[float] = None,
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
                        account_id=raw_signal.account_id,
                        approved=raw_signal.approved,
                        stop_loss_pct=raw_signal.stop_loss_pct,
                        take_profit_pct=raw_signal.take_profit_pct,
                        metadata=raw_signal.metadata,
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
            audit["final_decision"] = "rejected"
            audit["rejection_stage"] = "compile"
            self._record(accepted=False)
            self._store_pipeline_audit(pipeline_id, audit)
            logger.warning(
                "PIPELINE_REJECT stage=compile symbol=%s action=%s confidence=%.3f notes=%s",
                raw_signal.symbol, raw_signal.action, raw_signal.confidence, compile_notes,
            )
            return None

        # ── Stage 3: Risk Validation ─────────────────────────────────────
        risk_approved, risk_notes = self._risk_engine.validate_trade(
            symbol=compiled.symbol,
            side=compiled.side,
            size_usd=compiled.size_usd,
            portfolio_value_usd=portfolio_value_usd,
            current_positions=positions,
            daily_pnl=daily_pnl,
            peak_portfolio_value=peak_portfolio_value,
        )
        audit["stages"]["risk"] = {
            "approved": risk_approved,
            "notes":    risk_notes,
        }

        if not risk_approved:
            audit["final_decision"] = "rejected"
            audit["rejection_stage"] = "risk"
            self._record(accepted=False)
            self._store_pipeline_audit(pipeline_id, audit)
            logger.warning(
                "PIPELINE_REJECT stage=risk symbol=%s side=%s size_usd=%.2f notes=%s",
                compiled.symbol, compiled.side, compiled.size_usd, risk_notes,
            )
            return None

        # ── Approved ─────────────────────────────────────────────────────
        audit["final_decision"] = "approved"
        audit["signal_id"]      = compiled.signal_id
        self._record(accepted=True)
        with self._lock:
            self._last_approved_ts = _time.time()
        self._store_pipeline_audit(pipeline_id, audit)
        logger.info(
            "PIPELINE_APPROVED symbol=%s side=%s size_usd=%.2f regime=%s confidence=%.3f",
            compiled.symbol, compiled.side, compiled.size_usd,
            compiled.regime, compiled.confidence,
        )
        return compiled

    # ------------------------------------------------------------------
    # Diagnostic helpers
    # ------------------------------------------------------------------

    def inject_diagnostic_trade_if_idle(
        self,
        portfolio_value_usd: float = 10_000.0,
        available_balance_usd: Optional[float] = None,
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
            last_ts = self._last_approved_ts

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
            approved=True,
            metadata={"diagnostic": True},
        )
        return self.process_signal(
            diag_signal,
            portfolio_value_usd=portfolio_value_usd,
            available_balance_usd=available_balance_usd,
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
        )
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
            key = f"nija:control:pipeline:{pipeline_id}"
            audit["stored_at"] = datetime.now(timezone.utc).isoformat()
            self._redis.setex(key, _SIGNAL_REDIS_TTL, json.dumps(audit))
        except Exception as exc:
            logger.debug("SignalPipeline: Redis audit store failed: %s", exc)


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
                )
    return _singleton
