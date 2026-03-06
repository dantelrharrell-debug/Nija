"""
NIJA AI Intelligence Hub
=========================

Unified integration layer for the three core AI systems:

1. AI Market Regime Detection  (MarketRegimeClassificationAI)
   - 7-class regime classifier (STRONG_TREND, WEAK_TREND, RANGING, EXPANSION,
     MEAN_REVERSION, VOLATILITY_EXPLOSION, CONSOLIDATION)
   - ML + rule-based hybrid classification
   - Auto strategy-switching per detected regime

2. Portfolio Risk Engine  (PortfolioRiskEngine)
   - Real-time correlation tracking across all open positions
   - Correlation-adjusted position sizing (reduces size for correlated assets)
   - Portfolio-wide VaR / CVaR metrics and sector-cap enforcement

3. Capital Allocation AI  (CapitalAllocationBrain)
   - Dynamic capital routing by Sharpe ratio, risk parity, or Kelly criterion
   - Automatic rebalancing when allocations drift beyond threshold
   - Expected-return / diversification scoring per rebalance cycle

The hub exposes a single `AIIntelligenceHub` class and a module-level
singleton (`get_ai_intelligence_hub()`). The strategy integration method
`evaluate_trade()` is the primary entry-point for the trading strategy.

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd
import numpy as np

logger = logging.getLogger("nija.ai_hub")

# ---------------------------------------------------------------------------
# Optional dependency imports – each component is imported defensively so the
# hub degrades gracefully if a module is unavailable.
# ---------------------------------------------------------------------------

try:
    from market_regime_classification_ai import (
        MarketRegimeClassificationAI,
        MarketRegimeType,
        StrategyType as RegimeStrategyType,
        RegimeClassification,
    )
    REGIME_AI_AVAILABLE = True
except ImportError:
    REGIME_AI_AVAILABLE = False
    MarketRegimeClassificationAI = None  # type: ignore
    MarketRegimeType = None  # type: ignore
    logger.warning("MarketRegimeClassificationAI not available – regime AI disabled")

try:
    from portfolio_risk_engine import (
        PortfolioRiskEngine,
        get_portfolio_risk_engine,
        PortfolioRiskMetrics,
    )
    PORTFOLIO_RISK_AVAILABLE = True
except ImportError:
    PORTFOLIO_RISK_AVAILABLE = False
    PortfolioRiskEngine = None  # type: ignore
    get_portfolio_risk_engine = None  # type: ignore
    logger.warning("PortfolioRiskEngine not available – portfolio risk control disabled")

try:
    from capital_allocation_brain import (
        CapitalAllocationBrain,
        AllocationMethod,
        AllocationPlan,
    )
    CAPITAL_BRAIN_AVAILABLE = True
except ImportError:
    CAPITAL_BRAIN_AVAILABLE = False
    CapitalAllocationBrain = None  # type: ignore
    logger.warning("CapitalAllocationBrain not available – capital allocation AI disabled")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class TradeEvaluation:
    """Comprehensive AI evaluation result for a proposed trade."""

    symbol: str
    side: str  # 'long' or 'short'

    # Regime analysis
    regime: str = "unknown"
    regime_confidence: float = 0.0
    recommended_strategy: str = "trend_following"
    regime_position_multiplier: float = 1.0

    # Portfolio risk
    correlation_adjusted_size_pct: float = 0.0
    portfolio_var_95: float = 0.0
    exposure_allowed: bool = True
    exposure_rejection_reason: str = ""

    # Capital allocation
    allocated_capital: float = 0.0
    allocation_source: str = "base"

    # Final recommendation
    ai_approved: bool = True
    ai_score: float = 1.0  # 0.0 – 1.0 composite score
    ai_reason: str = ""

    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict:
        return {
            "symbol": self.symbol,
            "side": self.side,
            "regime": self.regime,
            "regime_confidence": self.regime_confidence,
            "recommended_strategy": self.recommended_strategy,
            "regime_position_multiplier": self.regime_position_multiplier,
            "correlation_adjusted_size_pct": self.correlation_adjusted_size_pct,
            "portfolio_var_95": self.portfolio_var_95,
            "exposure_allowed": self.exposure_allowed,
            "exposure_rejection_reason": self.exposure_rejection_reason,
            "allocated_capital": self.allocated_capital,
            "allocation_source": self.allocation_source,
            "ai_approved": self.ai_approved,
            "ai_score": self.ai_score,
            "ai_reason": self.ai_reason,
            "timestamp": self.timestamp.isoformat(),
        }


# ---------------------------------------------------------------------------
# Main hub class
# ---------------------------------------------------------------------------

class AIIntelligenceHub:
    """
    Unified AI Intelligence Hub for NIJA.

    Combines:
      1. AI Market Regime Detection
      2. Portfolio Risk Engine
      3. Capital Allocation Brain

    Usage
    -----
    hub = get_ai_intelligence_hub(config)

    # During market scan / signal evaluation
    evaluation = hub.evaluate_trade(
        symbol="BTC-USD",
        side="long",
        df=ohlcv_dataframe,
        indicators=indicators_dict,
        base_size_pct=0.05,
        portfolio_value=10_000.0,
    )

    if evaluation.ai_approved:
        position_size_pct = evaluation.correlation_adjusted_size_pct
        ...
    """

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}

        # -------------------------------------------------------------------
        # Configurable risk parameters
        # -------------------------------------------------------------------
        # Minimum composite AI score (0–1) required to approve a trade.
        # Trades scoring below this threshold are rejected.  Tunable via config
        # so operators can raise/lower the bar without code changes.
        self.min_ai_score: float = self.config.get("min_ai_score", 0.40)

        # Regime → position-size multiplier mapping (configurable per regime).
        # Overriding a single key is enough to retune that regime without
        # touching anything else.
        default_multipliers: Dict[str, float] = {
            "strong_trend": 1.20,        # Bigger size on strong trends
            "weak_trend": 1.00,          # Normal size
            "ranging": 0.70,             # Smaller – mean reversion likely
            "expansion": 1.10,           # Breakout – slightly larger
            "mean_reversion": 0.80,      # Pullback – moderate size
            "volatility_explosion": 0.50, # Crisis – very small
            "consolidation": 0.60,       # Pre-breakout – cautious
            "unknown": 1.00,
        }
        custom_multipliers: Dict[str, float] = self.config.get(
            "regime_size_multipliers", {}
        )
        self.regime_size_multipliers: Dict[str, float] = {
            **default_multipliers, **custom_multipliers
        }

        # Regimes that produce poor trend-following results (extra score penalty)
        self.unfavourable_regimes: set = set(
            self.config.get(
                "unfavourable_regimes",
                ["ranging", "volatility_explosion", "consolidation"],
            )
        )

        # -------------------------------------------------------------------
        # 1. AI Market Regime Detection
        # -------------------------------------------------------------------
        self.regime_ai: Optional[MarketRegimeClassificationAI] = None
        if REGIME_AI_AVAILABLE:
            regime_config = self.config.get("regime_ai", {})
            self.regime_ai = MarketRegimeClassificationAI(regime_config)
            logger.info("✅ [AI Hub] AI Market Regime Detector initialised (7-class classifier)")
        else:
            logger.warning("⚠️  [AI Hub] AI Regime Detector unavailable – using fallback")

        # -------------------------------------------------------------------
        # 2. Portfolio Risk Engine
        # -------------------------------------------------------------------
        self.risk_engine: Optional[PortfolioRiskEngine] = None
        if PORTFOLIO_RISK_AVAILABLE:
            risk_config = self.config.get("portfolio_risk", {})
            self.risk_engine = get_portfolio_risk_engine(risk_config)
            logger.info("✅ [AI Hub] Portfolio Risk Engine initialised (correlation + VaR tracking)")
        else:
            logger.warning("⚠️  [AI Hub] Portfolio Risk Engine unavailable – skipping correlation control")

        # -------------------------------------------------------------------
        # 3. Capital Allocation Brain
        # -------------------------------------------------------------------
        self.capital_brain: Optional[CapitalAllocationBrain] = None
        if CAPITAL_BRAIN_AVAILABLE:
            brain_config = self.config.get("capital_brain", {})
            self.capital_brain = CapitalAllocationBrain(brain_config)
            logger.info("✅ [AI Hub] Capital Allocation Brain initialised (dynamic Sharpe-weighted routing)")
        else:
            logger.warning("⚠️  [AI Hub] Capital Allocation Brain unavailable – using flat allocation")

        # Hub-level statistics
        self._evaluations: int = 0
        self._approvals: int = 0
        self._rejections: int = 0

        logger.info("=" * 70)
        logger.info("🤖 NIJA AI Intelligence Hub – ACTIVE")
        logger.info(f"   Regime AI     : {'ON' if self.regime_ai else 'OFF'}")
        logger.info(f"   Portfolio Risk: {'ON' if self.risk_engine else 'OFF'}")
        logger.info(f"   Capital Brain : {'ON' if self.capital_brain else 'OFF'}")
        logger.info(f"   Min AI Score  : {self.min_ai_score}")
        logger.info("=" * 70)

    # ------------------------------------------------------------------
    # Primary entry point
    # ------------------------------------------------------------------

    def evaluate_trade(
        self,
        symbol: str,
        side: str,
        df: pd.DataFrame,
        indicators: Dict,
        base_size_pct: float,
        portfolio_value: float,
    ) -> TradeEvaluation:
        """
        Run the full AI evaluation pipeline for a proposed trade.

        Parameters
        ----------
        symbol        : e.g. "BTC-USD"
        side          : "long" or "short"
        df            : OHLCV DataFrame (at least 50 bars recommended)
        indicators    : Pre-calculated indicator dict (adx, atr, macd, rsi, …)
        base_size_pct : Desired position size as fraction of portfolio (e.g. 0.05 = 5 %)
        portfolio_value: Total portfolio value in USD

        Returns
        -------
        TradeEvaluation with ai_approved flag and adjusted size.
        """
        self._evaluations += 1
        result = TradeEvaluation(symbol=symbol, side=side)

        # 1. Market Regime Detection ----------------------------------------
        result = self._apply_regime_detection(result, df, indicators)

        # 2. Portfolio Risk Engine ------------------------------------------
        result = self._apply_portfolio_risk(
            result, symbol, side, base_size_pct, portfolio_value
        )

        # 3. Capital Allocation AI ------------------------------------------
        result = self._apply_capital_allocation(
            result, symbol, base_size_pct, portfolio_value
        )

        # 4. Composite AI Score & Final Decision ----------------------------
        result = self._compute_ai_score(result)

        if result.ai_approved:
            self._approvals += 1
        else:
            self._rejections += 1

        logger.debug(
            "[AI Hub] %s %s | regime=%s(%.0f%%) | size=%.2f%% | score=%.2f | approved=%s",
            side.upper(), symbol,
            result.regime, result.regime_confidence * 100,
            result.correlation_adjusted_size_pct * 100,
            result.ai_score,
            result.ai_approved,
        )

        return result

    # ------------------------------------------------------------------
    # Step 1: Regime Detection
    # ------------------------------------------------------------------

    def _apply_regime_detection(
        self,
        result: TradeEvaluation,
        df: pd.DataFrame,
        indicators: Dict,
    ) -> TradeEvaluation:
        """Classify current market regime and set position-size multiplier."""
        if self.regime_ai is None or df is None or len(df) < 10:
            result.regime = "unknown"
            result.regime_confidence = 0.0
            result.regime_position_multiplier = 1.0
            return result

        try:
            # Normalise indicators: the NIJA system stores indicators as pd.Series.
            # The regime classifier expects scalar (last-value) floats for each key.
            scalar_indicators: Dict = {}
            for key, val in indicators.items():
                if hasattr(val, "iloc"):
                    try:
                        scalar_indicators[key] = float(val.iloc[-1])
                    except Exception:
                        scalar_indicators[key] = 0.0
                else:
                    try:
                        scalar_indicators[key] = float(val)
                    except Exception:
                        scalar_indicators[key] = 0.0

            classification = self.regime_ai.classify_regime(df, scalar_indicators)
            result.regime = classification.regime.value
            result.regime_confidence = classification.confidence
            result.recommended_strategy = classification.recommended_strategy.value
        except Exception as exc:
            logger.warning("[AI Hub] Regime classification failed: %s", exc)
            result.regime = "unknown"
            result.regime_confidence = 0.0

        result.regime_position_multiplier = self.regime_size_multipliers.get(
            result.regime, 1.0
        )
        return result

    # ------------------------------------------------------------------
    # Step 2: Portfolio Risk Engine
    # ------------------------------------------------------------------

    def _apply_portfolio_risk(
        self,
        result: TradeEvaluation,
        symbol: str,
        side: str,
        base_size_pct: float,
        portfolio_value: float,
    ) -> TradeEvaluation:
        """
        Check portfolio-level risk limits and return correlation-adjusted
        position size. Rejects the trade if exposure limits are exceeded.
        """
        if self.risk_engine is None:
            # No risk engine – pass through with regime multiplier applied
            result.correlation_adjusted_size_pct = (
                base_size_pct * result.regime_position_multiplier
            )
            result.exposure_allowed = True
            return result

        try:
            # Correlation-adjusted size
            adjusted_pct = self.risk_engine.get_position_size_adjustment(
                symbol, base_size_pct, portfolio_value
            )
            # Apply regime multiplier on top
            adjusted_pct *= result.regime_position_multiplier
            result.correlation_adjusted_size_pct = max(0.0, adjusted_pct)

            # Check if new position is allowed (exposure gate)
            can_add = self.risk_engine.add_position(
                symbol=symbol,
                size_usd=result.correlation_adjusted_size_pct * portfolio_value,
                direction=side,
                portfolio_value=portfolio_value,
            )

            if not can_add:
                result.exposure_allowed = False
                result.exposure_rejection_reason = (
                    "Portfolio exposure limit reached – position blocked by Risk Engine"
                )
                result.ai_approved = False
            else:
                # Immediately remove the probe position we just added
                self.risk_engine.remove_position(symbol)
                result.exposure_allowed = True

            # Current portfolio VaR
            metrics = self.risk_engine.calculate_portfolio_metrics(portfolio_value)
            result.portfolio_var_95 = getattr(metrics, "var_95", 0.0)

        except Exception as exc:
            logger.warning("[AI Hub] Portfolio risk check failed: %s", exc)
            # Fail-open (allow trade) but log the error
            result.correlation_adjusted_size_pct = (
                base_size_pct * result.regime_position_multiplier
            )
            result.exposure_allowed = True

        return result

    # ------------------------------------------------------------------
    # Step 3: Capital Allocation AI
    # ------------------------------------------------------------------

    def _apply_capital_allocation(
        self,
        result: TradeEvaluation,
        symbol: str,
        base_size_pct: float,
        portfolio_value: float,
    ) -> TradeEvaluation:
        """
        Consult the Capital Allocation Brain for the maximum capital that
        should be deployed in this symbol/strategy combination.
        """
        if self.capital_brain is None:
            result.allocated_capital = (
                result.correlation_adjusted_size_pct * portfolio_value
            )
            result.allocation_source = "base"
            return result

        try:
            # Ensure the target exists in the brain
            if symbol not in self.capital_brain.targets:
                self.capital_brain.add_target(
                    target_id=symbol,
                    target_type="asset",
                )

            # Max capital the brain allows for this symbol
            target = self.capital_brain.targets[symbol]
            max_pct = target.max_allocation_pct  # e.g. 0.25 = 25 %
            min_pct = target.min_allocation_pct  # e.g. 0.02 = 2 %

            # Respect brain limits
            clamped_pct = min(
                max(result.correlation_adjusted_size_pct, min_pct), max_pct
            )
            result.correlation_adjusted_size_pct = clamped_pct
            result.allocated_capital = clamped_pct * portfolio_value
            result.allocation_source = "capital_brain"

        except Exception as exc:
            logger.warning("[AI Hub] Capital allocation check failed: %s", exc)
            result.allocated_capital = (
                result.correlation_adjusted_size_pct * portfolio_value
            )
            result.allocation_source = "fallback"

        return result

    # ------------------------------------------------------------------
    # Step 4: Composite Score & Final Decision
    # ------------------------------------------------------------------

    def _compute_ai_score(self, result: TradeEvaluation) -> TradeEvaluation:
        """
        Compute a composite AI score (0–1) and make the final approve/reject
        decision if not already rejected upstream.
        """
        score = 1.0

        # Regime confidence component (weight: 30 %)
        regime_score = result.regime_confidence * 0.3
        score = score * 0.7 + regime_score  # blended

        # Regime desirability penalty
        if result.regime in self.unfavourable_regimes:
            score *= 0.75
            logger.debug("[AI Hub] Regime penalty applied for '%s'", result.regime)

        # Portfolio risk component (if var_95 high, reduce score)
        if result.portfolio_var_95 > 0 and result.correlation_adjusted_size_pct > 0:
            # Penalise if VaR > 5 % of portfolio
            portfolio_value_estimate = (
                result.allocated_capital / result.correlation_adjusted_size_pct
                if result.correlation_adjusted_size_pct > 0 else 1.0
            )
            var_pct = result.portfolio_var_95 / portfolio_value_estimate
            if var_pct > 0.05:
                score *= max(0.5, 1.0 - (var_pct - 0.05) * 5)

        result.ai_score = round(min(1.0, max(0.0, score)), 4)

        # Build reason string
        reasons = []
        if result.regime != "unknown":
            reasons.append(
                f"regime={result.regime}({result.regime_confidence*100:.0f}%)"
            )
        if not result.exposure_allowed:
            reasons.append(result.exposure_rejection_reason)
        reasons.append(f"score={result.ai_score:.2f}")

        result.ai_reason = " | ".join(reasons) if reasons else "AI evaluation complete"

        # Final gate: reject if score below configurable threshold
        if result.ai_approved and result.ai_score < self.min_ai_score:
            result.ai_approved = False
            result.ai_reason += f" | REJECTED: ai_score < {self.min_ai_score}"

        return result

    # ------------------------------------------------------------------
    # Position lifecycle helpers (call from strategy after fill/close)
    # ------------------------------------------------------------------

    def notify_position_opened(
        self,
        symbol: str,
        size_usd: float,
        direction: str,
        portfolio_value: float,
    ) -> None:
        """Register an opened position with the Portfolio Risk Engine."""
        if self.risk_engine is None:
            return
        try:
            self.risk_engine.add_position(symbol, size_usd, direction, portfolio_value)
            logger.debug("[AI Hub] Position registered: %s %s $%.2f", direction, symbol, size_usd)
        except Exception as exc:
            logger.warning("[AI Hub] notify_position_opened failed: %s", exc)

    def notify_position_closed(self, symbol: str) -> None:
        """Remove a closed position from the Portfolio Risk Engine."""
        if self.risk_engine is None:
            return
        try:
            self.risk_engine.remove_position(symbol)
            logger.debug("[AI Hub] Position removed: %s", symbol)
        except Exception as exc:
            logger.warning("[AI Hub] notify_position_closed failed: %s", exc)

    def notify_trade_result(
        self,
        symbol: str,
        pnl: float,
        is_win: bool,
        regime: Optional[str] = None,
        strategy: Optional[str] = None,
    ) -> None:
        """
        Feed trade outcome back into the Regime AI and Capital Brain for
        continuous self-improvement.
        """
        # Update Regime AI performance tracker
        if self.regime_ai is not None and regime and strategy:
            try:
                regime_type = MarketRegimeType(regime)
                from market_regime_classification_ai import StrategyType as ST
                strategy_type = ST(strategy)
                self.regime_ai.update_performance(regime_type, strategy_type, pnl, is_win)
            except Exception as exc:
                logger.debug("[AI Hub] Regime performance update failed: %s", exc)

        # Update Capital Brain performance
        if self.capital_brain is not None and symbol in self.capital_brain.targets:
            try:
                self.capital_brain.update_target_performance(
                    symbol,
                    {
                        "avg_return": pnl,
                        "returns": [pnl],
                    },
                )
            except Exception as exc:
                logger.debug("[AI Hub] Capital brain update failed: %s", exc)

    def update_price_history(self, symbol: str, price_series: pd.Series) -> None:
        """Feed price history into the risk engine for correlation tracking."""
        if self.risk_engine is None:
            return
        try:
            self.risk_engine.update_price_history(symbol, price_series)
        except Exception as exc:
            logger.debug("[AI Hub] Price history update failed: %s", exc)

    # ------------------------------------------------------------------
    # Rebalancing (call periodically, e.g. every hour)
    # ------------------------------------------------------------------

    def maybe_rebalance_capital(self, portfolio_value: float) -> Optional[Dict]:
        """
        Check if the Capital Brain wants to rebalance and execute if so.

        Returns the allocation plan dict, or None if no rebalance occurred.
        """
        if self.capital_brain is None:
            return None

        if not self.capital_brain.should_rebalance():
            return None

        try:
            self.capital_brain.total_capital = portfolio_value
            plan = self.capital_brain.allocate_capital(
                total_capital=portfolio_value,
                method=self.capital_brain.default_method,
            )
            self.capital_brain.execute_rebalancing(plan)
            logger.info(
                "[AI Hub] Capital rebalanced: method=%s, targets=%d, "
                "expected_sharpe=%.2f",
                plan.method.value,
                len(plan.allocations),
                plan.expected_sharpe,
            )
            return plan.to_dict()
        except Exception as exc:
            logger.warning("[AI Hub] Capital rebalancing failed: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def get_status(self) -> Dict:
        """Return hub status and statistics."""
        status: Dict = {
            "components": {
                "regime_ai": self.regime_ai is not None,
                "portfolio_risk": self.risk_engine is not None,
                "capital_brain": self.capital_brain is not None,
            },
            "evaluations": {
                "total": self._evaluations,
                "approved": self._approvals,
                "rejected": self._rejections,
                "approval_rate": (
                    self._approvals / self._evaluations
                    if self._evaluations else 0.0
                ),
            },
        }

        if self.regime_ai is not None:
            try:
                status["regime_stats"] = self.regime_ai.get_regime_statistics()
            except Exception:
                pass

        if self.risk_engine is not None:
            try:
                status["risk_stats"] = self.risk_engine.get_stats()
            except Exception:
                pass

        if self.capital_brain is not None:
            try:
                status["allocation_summary"] = self.capital_brain.get_allocation_summary()
            except Exception:
                pass

        return status


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_hub_instance: Optional[AIIntelligenceHub] = None


def get_ai_intelligence_hub(config: Optional[Dict] = None) -> AIIntelligenceHub:
    """
    Return the module-level singleton AIIntelligenceHub.

    The first call creates the instance with the supplied config.
    Subsequent calls ignore the config argument and return the cached instance.
    """
    global _hub_instance
    if _hub_instance is None:
        _hub_instance = AIIntelligenceHub(config)
    return _hub_instance
