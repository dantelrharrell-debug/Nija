"""
NIJA Strategy Intelligence Layer
==================================

Unified orchestration layer for all strategy-selection and signal-quality
decisions.  Combines:

1. **AIIntelligenceHub** — market-regime classification, portfolio-level risk,
   and capital-allocation routing.

2. **StrategyDiversificationEngine** — simultaneous multi-strategy execution
   (ApexTrend / MeanReversion / MomentumBreakout / LiquidityReversal) with
   regime-aware capital weighting.

3. **AITradeRanker** — composite 0-100 trade-quality score
   (trend_strength + volatility + volume + momentum, 25 pts each).

The ``StrategyIntelligenceLayer`` exposes a single ``evaluate()`` method that
returns a ``StrategySignal`` containing the consensus trade decision, the
recommended strategy, the AI quality score, and the regime-adjusted capital
allocation.

Usage
-----
::

    from bot.strategy_intelligence_layer import get_strategy_intelligence_layer

    sil = get_strategy_intelligence_layer(total_capital=10_000)

    signal = sil.evaluate(
        symbol="ETH-USD",
        df=ohlcv_df,
        indicators=indicators_dict,
        portfolio_value=10_000.0,
        current_regime="TRENDING",  # optional override
    )

    if signal.should_trade:
        execute_order(
            symbol=signal.symbol,
            side=signal.side,
            size_usd=signal.capital_allocation_usd,
            strategy=signal.strategy_name,
        )

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd

logger = logging.getLogger("nija.strategy_intelligence_layer")

# ---------------------------------------------------------------------------
# Optional subsystem imports — each degrades gracefully.
# ---------------------------------------------------------------------------

try:
    from ai_intelligence_hub import AIIntelligenceHub, get_ai_intelligence_hub, TradeEvaluation
    _HUB_AVAILABLE = True
except ImportError:
    try:
        from bot.ai_intelligence_hub import AIIntelligenceHub, get_ai_intelligence_hub, TradeEvaluation
        _HUB_AVAILABLE = True
    except ImportError:
        _HUB_AVAILABLE = False
        AIIntelligenceHub = None  # type: ignore
        get_ai_intelligence_hub = None  # type: ignore
        TradeEvaluation = None  # type: ignore
        logger.warning("AIIntelligenceHub not available — regime/allocation AI disabled")

try:
    from strategy_diversification_engine import StrategyDiversificationEngine
    _SDE_AVAILABLE = True
except ImportError:
    try:
        from bot.strategy_diversification_engine import StrategyDiversificationEngine
        _SDE_AVAILABLE = True
    except ImportError:
        _SDE_AVAILABLE = False
        StrategyDiversificationEngine = None  # type: ignore
        logger.warning("StrategyDiversificationEngine not available — multi-strategy disabled")

try:
    from ai_trade_ranker import AITradeRanker
    _RANKER_AVAILABLE = True
except ImportError:
    try:
        from bot.ai_trade_ranker import AITradeRanker
        _RANKER_AVAILABLE = True
    except ImportError:
        _RANKER_AVAILABLE = False
        AITradeRanker = None  # type: ignore
        logger.warning("AITradeRanker not available — trade quality scoring disabled")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class StrategySignal:
    """
    Consensus output from the Strategy Intelligence Layer.

    Attributes
    ----------
    symbol:
        Trading pair evaluated.
    side:
        ``"BUY"``, ``"SELL"``, or ``"HOLD"``.
    should_trade:
        ``True`` when both the diversification engine and the AI ranker agree
        the trade should be executed.
    strategy_name:
        Name of the strategy that generated the primary signal.
    capital_allocation_usd:
        Regime-adjusted capital to deploy for this trade.
    ai_score:
        Composite 0-100 trade-quality score from ``AITradeRanker``.
    ai_score_threshold:
        Minimum score required to pass (default 75).
    regime:
        Detected or provided market regime string.
    regime_confidence:
        Confidence level from regime classifier (0.0 – 1.0).
    hub_evaluation:
        Full ``TradeEvaluation`` from ``AIIntelligenceHub`` (may be ``None``
        when the hub is unavailable).
    diversification_result:
        Raw dict from ``StrategyDiversificationEngine.get_best_signal()``.
    reasons:
        Ordered list of notes explaining the signal decision.
    timestamp:
        UTC datetime of evaluation.
    """

    symbol: str
    side: str
    should_trade: bool
    strategy_name: str
    capital_allocation_usd: float
    ai_score: float = 0.0
    ai_score_threshold: float = 75.0
    regime: str = "UNKNOWN"
    regime_confidence: float = 0.0
    hub_evaluation: Optional[Any] = None
    diversification_result: Optional[Dict[str, Any]] = None
    reasons: List[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a plain dictionary (JSON-safe)."""
        return {
            "symbol": self.symbol,
            "side": self.side,
            "should_trade": self.should_trade,
            "strategy_name": self.strategy_name,
            "capital_allocation_usd": round(self.capital_allocation_usd, 2),
            "ai_score": round(self.ai_score, 2),
            "ai_score_threshold": self.ai_score_threshold,
            "regime": self.regime,
            "regime_confidence": round(self.regime_confidence, 4),
            "reasons": self.reasons,
            "timestamp": self.timestamp.isoformat(),
        }


# ---------------------------------------------------------------------------
# Core layer
# ---------------------------------------------------------------------------

class StrategyIntelligenceLayer:
    """
    Unified strategy intelligence orchestrator.

    Thread-safe; intended to be used as a process-wide singleton via
    ``get_strategy_intelligence_layer()``.

    Parameters
    ----------
    total_capital:
        Total deployable capital in USD (used to initialise
        ``StrategyDiversificationEngine``).
    ai_score_threshold:
        Minimum AITradeRanker score required to approve a trade (default 75).
    """

    def __init__(
        self,
        total_capital: float = 10_000.0,
        ai_score_threshold: float = 75.0,
    ) -> None:
        self._total_capital = total_capital
        self._score_threshold = ai_score_threshold
        self._lock = threading.Lock()

        # Subsystem handles
        self._hub: Optional[AIIntelligenceHub] = (
            get_ai_intelligence_hub() if _HUB_AVAILABLE else None
        )
        self._sde: Optional[StrategyDiversificationEngine] = (
            StrategyDiversificationEngine(total_capital=total_capital)
            if _SDE_AVAILABLE
            else None
        )
        self._ranker: Optional[AITradeRanker] = (
            AITradeRanker(min_score_threshold=ai_score_threshold)
            if _RANKER_AVAILABLE
            else None
        )

        logger.info(
            "StrategyIntelligenceLayer initialised | capital=$%.0f | score_threshold=%.0f",
            total_capital,
            ai_score_threshold,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(
        self,
        symbol: str,
        df: pd.DataFrame,
        indicators: Optional[Dict[str, Any]] = None,
        portfolio_value: Optional[float] = None,
        current_regime: Optional[str] = None,
        side: str = "long",
    ) -> StrategySignal:
        """
        Run the full intelligence pipeline for a proposed trade opportunity.

        Parameters
        ----------
        symbol:
            Trading pair, e.g. ``"BTC-USD"``.
        df:
            Recent OHLCV price DataFrame (required for the ranker and SDE).
        indicators:
            Pre-computed indicator dict passed straight to the diversification
            engine.  Keys depend on the individual strategy implementations.
        portfolio_value:
            Current total portfolio value in USD.
        current_regime:
            Optional regime override; if omitted the hub auto-detects from
            ``df``.
        side:
            ``"long"`` or ``"short"`` (used for hub evaluation).

        Returns
        -------
        StrategySignal
        """
        with self._lock:
            indicators = indicators or {}
            reasons: List[str] = []
            regime = current_regime or "UNKNOWN"
            regime_confidence = 0.0
            hub_eval = None
            diversification_result: Dict[str, Any] = {}
            ai_score = 0.0
            strategy_name = "UNKNOWN"
            capital_allocation_usd = 0.0
            raw_side = "HOLD"

            # ── Step 1: AI Intelligence Hub (regime + portfolio risk) ────
            if self._hub is not None:
                try:
                    hub_eval = self._hub.evaluate_trade(
                        symbol=symbol,
                        side=side,
                        df=df,
                        portfolio_value=portfolio_value or self._total_capital,
                    )
                    if getattr(hub_eval, "regime", None):
                        regime = hub_eval.regime
                    regime_confidence = getattr(hub_eval, "regime_confidence", 0.0)

                    if not hub_eval.approved:
                        reasons.append(f"Hub blocked: {getattr(hub_eval, 'rejection_reason', 'unknown')}")
                        return StrategySignal(
                            symbol=symbol,
                            side="HOLD",
                            should_trade=False,
                            strategy_name="BLOCKED_BY_HUB",
                            capital_allocation_usd=0.0,
                            regime=regime,
                            regime_confidence=regime_confidence,
                            hub_evaluation=hub_eval,
                            reasons=reasons,
                        )
                    reasons.append(f"Hub approved (regime={regime}, score={getattr(hub_eval, 'ai_score', 0):.1f})")
                except Exception as exc:
                    logger.debug("AIIntelligenceHub.evaluate_trade error: %s", exc)
                    reasons.append(f"Hub evaluation error (non-fatal): {exc}")

            # ── Step 2: Strategy Diversification Engine ──────────────────
            if self._sde is not None:
                try:
                    sde_result = self._sde.get_best_signal(
                        df=df,
                        indicators=indicators,
                        market_regime=regime,
                    )
                    diversification_result = sde_result or {}
                    raw_side = str(diversification_result.get("signal", "HOLD")).upper()
                    strategy_name = str(diversification_result.get("strategy", "UNKNOWN"))
                    capital_allocation_usd = float(
                        diversification_result.get("capital_allocation", 0.0)
                    )
                    reasons.append(
                        f"SDE signal={raw_side} via {strategy_name} "
                        f"(${capital_allocation_usd:.0f})"
                    )
                except Exception as exc:
                    logger.debug("StrategyDiversificationEngine.get_best_signal error: %s", exc)
                    reasons.append(f"SDE error (non-fatal): {exc}")
                    raw_side = "HOLD"

            if raw_side == "HOLD":
                reasons.append("No actionable signal from diversification engine")
                return StrategySignal(
                    symbol=symbol,
                    side="HOLD",
                    should_trade=False,
                    strategy_name=strategy_name,
                    capital_allocation_usd=0.0,
                    regime=regime,
                    regime_confidence=regime_confidence,
                    hub_evaluation=hub_eval,
                    diversification_result=diversification_result,
                    reasons=reasons,
                )

            # ── Step 3: AI Trade Ranker ──────────────────────────────────
            if self._ranker is not None:
                try:
                    score_breakdown = self._ranker.score_trade(
                        df=df,
                        signal=raw_side,
                    )
                    ai_score = score_breakdown.total_score
                    if not self._ranker.should_execute(ai_score):
                        reasons.append(
                            f"Ranker blocked: score {ai_score:.1f} < threshold {self._score_threshold}"
                        )
                        return StrategySignal(
                            symbol=symbol,
                            side=raw_side,
                            should_trade=False,
                            strategy_name=strategy_name,
                            capital_allocation_usd=0.0,
                            ai_score=ai_score,
                            ai_score_threshold=self._score_threshold,
                            regime=regime,
                            regime_confidence=regime_confidence,
                            hub_evaluation=hub_eval,
                            diversification_result=diversification_result,
                            reasons=reasons,
                        )
                    reasons.append(f"Ranker approved (score={ai_score:.1f}/{self._score_threshold})")
                except Exception as exc:
                    logger.debug("AITradeRanker.score_trade error: %s", exc)
                    reasons.append(f"Ranker error (non-fatal): {exc}")
                    # Continue without ranker gate if unavailable

            # ── Approved ─────────────────────────────────────────────────
            return StrategySignal(
                symbol=symbol,
                side=raw_side,
                should_trade=True,
                strategy_name=strategy_name,
                capital_allocation_usd=capital_allocation_usd,
                ai_score=ai_score,
                ai_score_threshold=self._score_threshold,
                regime=regime,
                regime_confidence=regime_confidence,
                hub_evaluation=hub_eval,
                diversification_result=diversification_result,
                reasons=reasons,
            )

    # ------------------------------------------------------------------
    # Lifecycle hooks
    # ------------------------------------------------------------------

    def notify_position_opened(
        self,
        symbol: str,
        side: str,
        size_usd: float,
        entry_price: float,
    ) -> None:
        """Propagate position-open event to AI hub for correlation tracking."""
        if self._hub is not None:
            try:
                self._hub.notify_position_opened(
                    symbol=symbol,
                    side=side,
                    size_usd=size_usd,
                    entry_price=entry_price,
                )
            except Exception as exc:
                logger.debug("Hub.notify_position_opened error: %s", exc)

    def notify_position_closed(self, symbol: str) -> None:
        """Propagate position-close event to AI hub."""
        if self._hub is not None:
            try:
                self._hub.notify_position_closed(symbol=symbol)
            except Exception as exc:
                logger.debug("Hub.notify_position_closed error: %s", exc)

    def notify_trade_result(
        self,
        symbol: str,
        pnl_usd: float,
        pnl_pct: float,
        is_winner: bool,
    ) -> None:
        """Forward trade result so the hub can update its performance model."""
        if self._hub is not None:
            try:
                self._hub.notify_trade_result(
                    symbol=symbol,
                    pnl_usd=pnl_usd,
                    pnl_pct=pnl_pct,
                    is_winner=is_winner,
                )
            except Exception as exc:
                logger.debug("Hub.notify_trade_result error: %s", exc)

    def update_price_history(self, symbol: str, price_series: pd.Series) -> None:
        """Push price history into the hub's correlation model."""
        if self._hub is not None:
            try:
                self._hub.update_price_history(symbol=symbol, price_series=price_series)
            except Exception as exc:
                logger.debug("Hub.update_price_history error: %s", exc)

    def update_total_capital(self, total_capital: float) -> None:
        """Update the deployable capital used by the diversification engine."""
        with self._lock:
            self._total_capital = total_capital
            if self._sde is not None:
                try:
                    self._sde.total_capital = total_capital
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def get_status(self) -> Dict[str, Any]:
        """Return a serialisable status snapshot of the layer."""
        with self._lock:
            hub_status = self._hub.get_status() if self._hub is not None else {}
            return {
                "layer": "StrategyIntelligenceLayer",
                "version": "1.0",
                "timestamp": datetime.utcnow().isoformat(),
                "config": {
                    "total_capital_usd": self._total_capital,
                    "ai_score_threshold": self._score_threshold,
                },
                "subsystems": {
                    "ai_intelligence_hub_available": _HUB_AVAILABLE,
                    "strategy_diversification_engine_available": _SDE_AVAILABLE,
                    "ai_trade_ranker_available": _RANKER_AVAILABLE,
                    "ai_intelligence_hub_status": hub_status,
                },
            }


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_sil_instance: Optional[StrategyIntelligenceLayer] = None
_sil_lock = threading.Lock()


def get_strategy_intelligence_layer(
    total_capital: float = 10_000.0,
    ai_score_threshold: float = 75.0,
) -> StrategyIntelligenceLayer:
    """
    Return the process-wide ``StrategyIntelligenceLayer`` singleton.

    Parameters are only applied on first creation.
    """
    global _sil_instance
    with _sil_lock:
        if _sil_instance is None:
            _sil_instance = StrategyIntelligenceLayer(
                total_capital=total_capital,
                ai_score_threshold=ai_score_threshold,
            )
        return _sil_instance


__all__ = [
    "StrategySignal",
    "StrategyIntelligenceLayer",
    "get_strategy_intelligence_layer",
]
