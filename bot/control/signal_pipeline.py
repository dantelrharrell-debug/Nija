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

        logger.info("SignalPipeline initialised")

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

        Returns
        -------
        CompiledSignal if approved, None if rejected.
        """
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
            logger.info(
                "SignalPipeline: REJECTED at compile | %s | %s",
                raw_signal.symbol, compile_notes,
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
            logger.info(
                "SignalPipeline: REJECTED at risk | %s | %s",
                compiled.symbol, risk_notes,
            )
            return None

        # ── Approved ─────────────────────────────────────────────────────
        audit["final_decision"] = "approved"
        audit["signal_id"]      = compiled.signal_id
        self._record(accepted=True)
        self._store_pipeline_audit(pipeline_id, audit)
        logger.info(
            "SignalPipeline: APPROVED | %s %s %.2f USD | regime=%s confidence=%.2f",
            compiled.symbol, compiled.side, compiled.size_usd,
            compiled.regime, compiled.confidence,
        )
        return compiled

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
