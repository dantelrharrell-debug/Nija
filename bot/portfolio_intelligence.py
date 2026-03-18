"""
NIJA Portfolio Intelligence Module
===================================

Central intelligence layer that controls five portfolio-level dimensions:

1. **Global Exposure**       – Enforces total portfolio exposure caps (soft + hard).
2. **Sector Concentration**  – Prevents over-weighting any single crypto sector.
3. **Correlation Risk**      – Screens new positions for excessive correlation with
                               existing holdings.
4. **Portfolio Volatility**  – Maintains a target daily volatility envelope and
                               scales position sizes when vol is elevated.
5. **Capital Allocation**    – Produces approved position sizes after applying all
                               the above constraints in sequence.

Portfolio-Level Optimization
-----------------------------
The module also contains a **portfolio-level optimizer** that tunes four
system-wide levers using live trade feedback:

* **capital_allocation**  – fraction of equity deployed per trade
* **max_positions**       – maximum concurrent open positions
* **risk_budget**         – maximum portfolio risk per cycle (% of equity)
* **strategy_weighting**  – relative weight given to each active strategy

Optimization is gated by a minimum trade count so it never runs on
insufficient data:

    MIN_TRADES_FOR_OPTIMIZATION = 50   # must have at least 50 completed trades
    EVALUATION_TRADES = 30             # window used to evaluate each adjustment

This module acts as the unified "brain" for portfolio-level decisions.
It integrates with (but does not require) the existing PortfolioRiskEngine,
VolatilityTargetingEngine, and CryptoSectorTaxonomy subsystems.

Author: NIJA Trading Systems
Version: 1.1
Date: March 2026
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from itertools import combinations
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger("nija.portfolio_intelligence")

# ---------------------------------------------------------------------------
# Portfolio-level optimization trade-count gates
# ---------------------------------------------------------------------------

#: Minimum number of completed trades required before the portfolio-level
#: optimizer is allowed to run.  Running on fewer trades risks noise-driven
#: changes that hurt rather than help performance.
MIN_TRADES_FOR_OPTIMIZATION: int = 50

#: Number of trades in the rolling evaluation window used to measure whether
#: a recent parameter adjustment actually improved performance before it is
#: committed as the new baseline.
EVALUATION_TRADES: int = 30

# ---------------------------------------------------------------------------
# Sector concentration thresholds
# ---------------------------------------------------------------------------

#: Soft warning zone: when a sector's portfolio share reaches this level
#: (30 %) a non-blocking warning is raised to flag over-concentration that
#: has built up in existing positions (e.g. via mark-to-market drift).
#: Sits above the hard-block limit (default 20 %) and below the emergency
#: reduction threshold.
SOFT_SECTOR_WARNING: float = 0.30


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class AllocationDecision(Enum):
    """Outcome of a capital allocation evaluation."""

    APPROVED = "approved"   # Full requested size is approved
    REDUCED = "reduced"     # A reduced size is approved
    DEFERRED = "deferred"   # No allocation now; try again later
    REJECTED = "rejected"   # Position is not allowed at all


# ---------------------------------------------------------------------------
# Data-classes  (immutable snapshots / value objects)
# ---------------------------------------------------------------------------

@dataclass
class ExposureSnapshot:
    """Point-in-time snapshot of portfolio global exposure."""

    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    total_exposure_usd: float = 0.0
    total_exposure_pct: float = 0.0
    long_exposure_usd: float = 0.0
    short_exposure_usd: float = 0.0
    net_exposure_pct: float = 0.0
    num_positions: int = 0
    available_capital_usd: float = 0.0
    exposure_headroom_pct: float = 1.0


@dataclass
class SectorConcentrationReport:
    """Analysis of sector concentration across the portfolio."""

    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    sector_exposures: Dict[str, float] = field(default_factory=dict)  # sector → % of portfolio
    max_sector: str = ""
    max_sector_pct: float = 0.0
    soft_breaches: List[str] = field(default_factory=list)  # Sectors at or above soft limit
    hard_breaches: List[str] = field(default_factory=list)  # Sectors at or above hard limit
    herfindahl_index: float = 0.0  # Sector-level concentration (0 = diverse, 1 = concentrated)


@dataclass
class CorrelationRiskReport:
    """Pairwise correlation risk analysis for current portfolio."""

    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    high_correlation_pairs: List[Tuple[str, str, float]] = field(default_factory=list)
    avg_portfolio_correlation: float = 0.0
    diversification_score: float = 1.0   # 0 = undiversified, 1 = well diversified
    correlation_risk_level: str = "low"  # "low" | "medium" | "high" | "extreme"


@dataclass
class VolatilityAssessment:
    """Current portfolio volatility assessment."""

    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    realized_daily_vol: float = 0.0
    target_daily_vol: float = 0.02
    vol_ratio: float = 1.0
    vol_regime: str = "normal"   # "calm" | "normal" | "elevated" | "stressed"
    position_scalar: float = 1.0
    exposure_scalar: float = 1.0
    var_95_usd: float = 0.0
    expected_shortfall_usd: float = 0.0


@dataclass
class AllocationRecommendation:
    """Capital allocation recommendation produced by the intelligence module."""

    symbol: str
    requested_size_usd: float
    recommended_size_usd: float
    decision: AllocationDecision
    rejection_reasons: List[str] = field(default_factory=list)
    reduction_reasons: List[str] = field(default_factory=list)
    portfolio_impact: Dict[str, float] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class PortfolioIntelligenceReport:
    """Full portfolio intelligence report covering all five dimensions."""

    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    exposure: Optional[ExposureSnapshot] = None
    sector_concentration: Optional[SectorConcentrationReport] = None
    correlation_risk: Optional[CorrelationRiskReport] = None
    volatility: Optional[VolatilityAssessment] = None
    health_score: float = 1.0       # 0 = critical, 1 = optimal
    health_label: str = "optimal"   # "optimal" | "good" | "caution" | "warning" | "critical"
    recommended_actions: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Portfolio-level optimization dataclasses
# ---------------------------------------------------------------------------

@dataclass
class PortfolioAllocations:
    """
    The four system-wide levers controlled by the portfolio-level optimizer.

    Attributes:
        capital_allocation_pct: Fraction of total equity to deploy per trade
                                 (e.g. 0.05 = 5 % per trade).
        max_positions: Maximum number of concurrent open positions.
        risk_budget_pct: Maximum portfolio risk accepted per optimization cycle
                         expressed as a % of equity (e.g. 0.02 = 2 %).
        strategy_weighting: Mapping of strategy_name → relative weight (0–1).
                             Weights are normalised to sum to 1.0 before use.
    """

    capital_allocation_pct: float = 0.05
    max_positions: int = 5
    risk_budget_pct: float = 0.02
    strategy_weighting: Dict[str, float] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def normalized_strategy_weights(self) -> Dict[str, float]:
        """Return strategy weights normalised so they sum to 1.0."""
        total = sum(self.strategy_weighting.values())
        if total <= 0:
            return {k: 1.0 / len(self.strategy_weighting) for k in self.strategy_weighting} \
                if self.strategy_weighting else {}
        return {k: v / total for k, v in self.strategy_weighting.items()}


@dataclass
class PortfolioOptimizationResult:
    """
    Result produced by one portfolio-level optimization cycle.

    Attributes:
        cycle_id: Unique identifier for this cycle.
        trigger_reason: What caused this optimization (e.g. ``'scheduled'``).
        trades_used: Number of completed trades used for analysis.
        previous_allocations: Allocations active before this cycle.
        recommended_allocations: New allocations recommended by the optimizer.
        performance_delta: Estimated performance improvement (%, positive = better).
        was_applied: Whether the new allocations were committed as the baseline.
        notes: Human-readable summary of the key changes.
        timestamp: When the cycle ran.
    """

    cycle_id: str
    trigger_reason: str
    trades_used: int
    previous_allocations: Optional[PortfolioAllocations] = None
    recommended_allocations: Optional[PortfolioAllocations] = None
    performance_delta: float = 0.0
    was_applied: bool = False
    notes: List[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class PortfolioIntelligence:
    """
    Portfolio Intelligence Module

    Central controller for portfolio-level risk management.  It orchestrates
    decisions across five key dimensions:

    1. **Global Exposure Control**
       - Enforces hard caps on total portfolio exposure.
       - Scales positions proportionally when approaching the soft limit.
       - Separates long/short exposure for net-exposure management.

    2. **Sector Concentration Management**
       - Soft limit (default 15 %): warn and reduce incoming position size.
       - Hard limit (default 20 %): reject trade entirely.
       - Auto-classifies symbols via the ``crypto_sector_taxonomy`` module.

    3. **Correlation Risk Screening**
       - Detects high correlation between proposed and existing positions.
       - Reduces size or rejects when adding a position would create an
         over-concentrated, correlated portfolio.

    4. **Portfolio Volatility Control**
       - Maintains a target daily portfolio volatility (default 2 %).
       - Scales all position sizes downward when realised vol exceeds target.
       - Adjusts exposure limits in stressed vol environments.

    5. **Capital Allocation Engine**
       - Applies the four constraints above in sequence.
       - Returns the approved position size or a rejection with reasons.
       - Enforces a minimum position-size gate after all reductions.
    """

    def __init__(self, config: Optional[Dict] = None) -> None:
        """
        Initialise the Portfolio Intelligence module.

        Args:
            config: Optional configuration dictionary.  Supported keys and
                    defaults are documented alongside each attribute below.
        """
        self.config: Dict = config or {}

        # --- Global exposure parameters ---
        self.max_total_exposure_pct: float = self.config.get("max_total_exposure_pct", 0.80)
        self.soft_exposure_pct: float = self.config.get("soft_exposure_pct", 0.65)

        # --- Sector concentration parameters ---
        self.soft_sector_limit_pct: float = self.config.get("soft_sector_limit_pct", 0.15)
        self.hard_sector_limit_pct: float = self.config.get("hard_sector_limit_pct", 0.20)

        # --- Correlation parameters ---
        self.high_correlation_threshold: float = self.config.get("high_correlation_threshold", 0.70)
        self.max_avg_portfolio_correlation: float = self.config.get("max_avg_portfolio_correlation", 0.60)
        self.correlation_lookback: int = self.config.get("correlation_lookback", 100)

        # --- Volatility parameters ---
        self.target_daily_vol: float = self.config.get("target_daily_vol", 0.02)
        self.max_daily_vol: float = self.config.get("max_daily_vol", 0.04)
        self.vol_lookback: int = self.config.get("vol_lookback", 20)

        # --- Capital allocation parameters ---
        self.min_position_size_usd: float = self.config.get("min_position_size_usd", 10.0)
        self.max_single_position_pct: float = self.config.get("max_single_position_pct", 0.15)

        # --- Internal state ---
        # positions: symbol → {size_usd, direction, sector, entry_time}
        self.positions: Dict[str, Dict] = {}
        self.price_history: Dict[str, pd.Series] = {}
        self.portfolio_value: float = 0.0

        # --- Portfolio-level optimizer state ---
        # Completed trade records used by the optimizer.
        # Each entry: {strategy, pnl, return_pct, win, timestamp}
        self._trade_log: List[Dict] = []

        # Active (baseline) portfolio allocations
        self.current_allocations: PortfolioAllocations = PortfolioAllocations(
            capital_allocation_pct=self.config.get("capital_allocation_pct", 0.05),
            max_positions=self.config.get("max_positions", 5),
            risk_budget_pct=self.config.get("risk_budget_pct", 0.02),
            strategy_weighting=dict(self.config.get("strategy_weighting", {})),
        )

        # History of completed optimization cycles
        self.optimization_history: List[PortfolioOptimizationResult] = []

        # Optional: override trade-count gate from config
        self._min_trades_for_opt: int = self.config.get(
            "min_trades_for_optimization", MIN_TRADES_FOR_OPTIMIZATION
        )
        self._evaluation_trades: int = self.config.get(
            "evaluation_trades", EVALUATION_TRADES
        )

        # --- Optional integrations ---
        self._sector_taxonomy_available: bool = False
        self._get_sector = None
        self._get_sector_name = None
        self._risk_engine = None
        self._risk_engine_available: bool = False
        self._init_integrations()

        logger.info("=" * 70)
        logger.info("🧠 Portfolio Intelligence Module Initialized")
        logger.info("=" * 70)
        logger.info(
            f"Max Exposure: {self.max_total_exposure_pct * 100:.0f}%  |  "
            f"Soft: {self.soft_exposure_pct * 100:.0f}%"
        )
        logger.info(
            f"Sector Limits: soft={self.soft_sector_limit_pct * 100:.0f}%  "
            f"hard={self.hard_sector_limit_pct * 100:.0f}%"
        )
        logger.info(f"Correlation Threshold: {self.high_correlation_threshold}")
        logger.info(
            f"Target Vol: {self.target_daily_vol * 100:.1f}% daily  "
            f"Max: {self.max_daily_vol * 100:.1f}%"
        )
        logger.info(
            f"Optimization gate: {self._min_trades_for_opt} trades min  |  "
            f"Evaluation window: {self._evaluation_trades} trades"
        )
        logger.info("=" * 70)

    # =========================================================================
    # Integration bootstrap
    # =========================================================================

    def _init_integrations(self) -> None:
        """Initialise optional integrations with existing NIJA subsystems."""
        # Crypto sector taxonomy
        for module_path in ("bot.crypto_sector_taxonomy", "crypto_sector_taxonomy"):
            try:
                import importlib
                mod = importlib.import_module(module_path)
                self._get_sector = mod.get_sector
                self._get_sector_name = mod.get_sector_name
                self._sector_taxonomy_available = True
                break
            except Exception:
                continue

        # Portfolio risk engine (for shared correlation data)
        for module_path in ("bot.portfolio_risk_engine", "portfolio_risk_engine"):
            try:
                import importlib
                mod = importlib.import_module(module_path)
                self._risk_engine = mod.get_portfolio_risk_engine()
                self._risk_engine_available = True
                break
            except Exception:
                continue

    # =========================================================================
    # Public API – state management
    # =========================================================================

    def update_portfolio_value(self, portfolio_value: float) -> None:
        """
        Update the current total portfolio value.

        Args:
            portfolio_value: Total portfolio value in USD.
        """
        if portfolio_value > 0:
            self.portfolio_value = portfolio_value

    def register_position(
        self,
        symbol: str,
        size_usd: float,
        direction: str = "long",
        sector: Optional[str] = None,
    ) -> None:
        """
        Register an open position with the intelligence module.

        Args:
            symbol: Trading pair (e.g. ``'BTC-USD'``).
            size_usd: Current position value in USD.
            direction: ``'long'`` or ``'short'``.
            sector: Optional sector override; auto-detected when omitted.
        """
        resolved_sector = sector or self._resolve_sector(symbol)
        self.positions[symbol] = {
            "size_usd": size_usd,
            "direction": direction,
            "sector": resolved_sector,
            "entry_time": datetime.now().isoformat(),
        }
        logger.debug(
            f"Position registered: {symbol} ${size_usd:,.2f} "
            f"[{direction}] sector={resolved_sector}"
        )

    def deregister_position(self, symbol: str) -> None:
        """
        Remove a closed (or rejected) position.

        Args:
            symbol: Symbol to remove.
        """
        if symbol in self.positions:
            del self.positions[symbol]
            logger.debug(f"Position deregistered: {symbol}")

    def update_price_history(self, symbol: str, prices: pd.Series) -> None:
        """
        Feed price history used for volatility and correlation calculations.

        Args:
            symbol: Trading pair symbol.
            prices: Pandas Series of closing prices (oldest first).
        """
        self.price_history[symbol] = prices

    # =========================================================================
    # Public API – primary evaluation
    # =========================================================================

    def evaluate_new_position(
        self,
        symbol: str,
        requested_size_usd: float,
        direction: str = "long",
    ) -> AllocationRecommendation:
        """
        Evaluate whether a new position can be opened and at what size.

        This is the primary entry-point for trade gating.  Call this before
        opening a new position to get the portfolio-intelligence-approved size.

        Checks applied in order:
        1. Global exposure cap
        2. Sector concentration limits
        3. Correlation risk
        4. Volatility scalar
        5. Single-position cap
        6. Minimum position size gate

        Args:
            symbol: Trading pair to evaluate.
            requested_size_usd: Intended position size in USD.
            direction: ``'long'`` or ``'short'``.

        Returns:
            :class:`AllocationRecommendation` with approved size and decision.
        """
        rejection_reasons: List[str] = []
        reduction_reasons: List[str] = []
        approved_size = requested_size_usd
        portfolio_value = self.portfolio_value

        if portfolio_value <= 0:
            rejection_reasons.append(
                "Portfolio value not set — cannot evaluate exposure"
            )
            return AllocationRecommendation(
                symbol=symbol,
                requested_size_usd=requested_size_usd,
                recommended_size_usd=0.0,
                decision=AllocationDecision.REJECTED,
                rejection_reasons=rejection_reasons,
            )

        # --- 1. Global exposure ---
        approved_size, exp_reasons = self._apply_global_exposure_limit(
            symbol, approved_size, direction, portfolio_value
        )
        reduction_reasons.extend(exp_reasons)
        if approved_size <= 0:
            rejection_reasons.append("Global exposure limit reached")
            return AllocationRecommendation(
                symbol=symbol,
                requested_size_usd=requested_size_usd,
                recommended_size_usd=0.0,
                decision=AllocationDecision.REJECTED,
                rejection_reasons=rejection_reasons,
                reduction_reasons=reduction_reasons,
            )

        # --- 2. Sector concentration ---
        sector = self._resolve_sector(symbol)
        approved_size, sec_reasons, sector_blocked = self._apply_sector_limits(
            symbol, sector, approved_size, portfolio_value
        )
        reduction_reasons.extend(sec_reasons)
        if sector_blocked:
            rejection_reasons.append(
                f"Sector '{sector}' at hard concentration limit "
                f"({self.hard_sector_limit_pct * 100:.0f}%)"
            )
            return AllocationRecommendation(
                symbol=symbol,
                requested_size_usd=requested_size_usd,
                recommended_size_usd=0.0,
                decision=AllocationDecision.REJECTED,
                rejection_reasons=rejection_reasons,
                reduction_reasons=reduction_reasons,
            )

        # --- 3. Correlation risk ---
        approved_size, corr_reasons, corr_blocked = self._apply_correlation_limit(
            symbol, approved_size, portfolio_value
        )
        reduction_reasons.extend(corr_reasons)
        if corr_blocked:
            rejection_reasons.append(
                "Correlation risk too high — portfolio would be over-concentrated"
            )
            return AllocationRecommendation(
                symbol=symbol,
                requested_size_usd=requested_size_usd,
                recommended_size_usd=0.0,
                decision=AllocationDecision.REJECTED,
                rejection_reasons=rejection_reasons,
                reduction_reasons=reduction_reasons,
            )

        # --- 4. Volatility scalar ---
        vol_scalar = self._get_volatility_scalar()
        if vol_scalar < 1.0:
            original = approved_size
            approved_size = approved_size * vol_scalar
            reduction_reasons.append(
                f"Volatility regime adjustment: ×{vol_scalar:.2f} "
                f"(${original:,.2f} → ${approved_size:,.2f})"
            )

        # --- 5. Single-position cap ---
        max_single = portfolio_value * self.max_single_position_pct
        if approved_size > max_single:
            reduction_reasons.append(
                f"Single-position cap ({self.max_single_position_pct * 100:.0f}%): "
                f"${approved_size:,.2f} → ${max_single:,.2f}"
            )
            approved_size = max_single

        # --- 6. Minimum size gate ---
        if approved_size < self.min_position_size_usd:
            rejection_reasons.append(
                f"Position too small after adjustments: "
                f"${approved_size:,.2f} < min ${self.min_position_size_usd:.2f}"
            )
            return AllocationRecommendation(
                symbol=symbol,
                requested_size_usd=requested_size_usd,
                recommended_size_usd=0.0,
                decision=AllocationDecision.REJECTED,
                rejection_reasons=rejection_reasons,
                reduction_reasons=reduction_reasons,
            )

        decision = (
            AllocationDecision.REDUCED if reduction_reasons else AllocationDecision.APPROVED
        )

        current_exposure = self._total_exposure_usd()
        portfolio_impact = {
            "new_total_exposure_pct": (current_exposure + approved_size) / portfolio_value,
            "position_pct_of_portfolio": approved_size / portfolio_value,
            "sector_pct_after": (
                self._sector_exposure_pct(sector, portfolio_value)
                + approved_size / portfolio_value
            ),
        }

        return AllocationRecommendation(
            symbol=symbol,
            requested_size_usd=requested_size_usd,
            recommended_size_usd=approved_size,
            decision=decision,
            rejection_reasons=rejection_reasons,
            reduction_reasons=reduction_reasons,
            portfolio_impact=portfolio_impact,
        )

    # =========================================================================
    # Public API – report generation
    # =========================================================================

    def get_exposure_snapshot(self) -> ExposureSnapshot:
        """Return a point-in-time snapshot of current global exposure."""
        total = self._total_exposure_usd()
        long_exp = sum(
            v["size_usd"]
            for v in self.positions.values()
            if v.get("direction") == "long"
        )
        short_exp = sum(
            v["size_usd"]
            for v in self.positions.values()
            if v.get("direction") == "short"
        )
        pv = max(self.portfolio_value, 1e-9)
        return ExposureSnapshot(
            total_exposure_usd=total,
            total_exposure_pct=total / pv,
            long_exposure_usd=long_exp,
            short_exposure_usd=short_exp,
            net_exposure_pct=(long_exp - short_exp) / pv,
            num_positions=len(self.positions),
            available_capital_usd=max(pv - total, 0.0),
            exposure_headroom_pct=max(self.max_total_exposure_pct - total / pv, 0.0),
        )

    def get_sector_concentration_report(self) -> SectorConcentrationReport:
        """Analyse sector concentration across all open positions."""
        pv = max(self.portfolio_value, 1e-9)

        sector_usd: Dict[str, float] = {}
        for pos in self.positions.values():
            sector = pos.get("sector", "misc")
            sector_usd[sector] = sector_usd.get(sector, 0.0) + pos["size_usd"]

        sector_pct: Dict[str, float] = {s: v / pv for s, v in sector_usd.items()}

        soft_breaches = [
            s for s, p in sector_pct.items() if p >= self.soft_sector_limit_pct
        ]
        hard_breaches = [
            s for s, p in sector_pct.items() if p >= self.hard_sector_limit_pct
        ]

        # Soft warning zone: sectors that have drifted above SOFT_SECTOR_WARNING
        # (30 %) through mark-to-market movement – flag for review/reduction.
        soft_warning_sectors = [
            f"'{s}' ({p*100:.1f}%)"
            for s, p in sector_pct.items()
            if p >= SOFT_SECTOR_WARNING
        ]
        if soft_warning_sectors:
            logger.warning(
                f"🟡 SOFT WARNING ZONE: {len(soft_warning_sectors)} sector(s) at or above "
                f"{SOFT_SECTOR_WARNING*100:.0f}% – consider reducing existing positions: "
                + ", ".join(soft_warning_sectors)
            )

        max_sector = max(sector_pct, key=sector_pct.get) if sector_pct else ""
        max_pct = sector_pct.get(max_sector, 0.0)
        hhi = sum(p ** 2 for p in sector_pct.values()) if sector_pct else 0.0

        return SectorConcentrationReport(
            sector_exposures=sector_pct,
            max_sector=max_sector,
            max_sector_pct=max_pct,
            soft_breaches=soft_breaches,
            hard_breaches=hard_breaches,
            herfindahl_index=hhi,
        )

    def get_correlation_risk_report(self) -> CorrelationRiskReport:
        """Analyse pairwise correlation risk across the current portfolio."""
        symbols = list(self.positions.keys())
        high_corr_pairs: List[Tuple[str, str, float]] = []
        correlations: List[float] = []

        if len(symbols) >= 2 and len(self.price_history) >= 2:
            for sym_a, sym_b in combinations(symbols, 2):
                corr = self._compute_correlation(sym_a, sym_b)
                if corr is not None:
                    correlations.append(abs(corr))
                    if abs(corr) >= self.high_correlation_threshold:
                        high_corr_pairs.append((sym_a, sym_b, corr))

        avg_corr = float(np.mean(correlations)) if correlations else 0.0
        n = max(len(symbols), 1)
        # Scale diversification score by number of positions (max benefit at 5+)
        div_score = max(0.0, 1.0 - avg_corr) * min(1.0, n / 5.0)

        if avg_corr >= 0.80:
            risk_level = "extreme"
        elif avg_corr >= 0.65:
            risk_level = "high"
        elif avg_corr >= 0.45:
            risk_level = "medium"
        else:
            risk_level = "low"

        return CorrelationRiskReport(
            high_correlation_pairs=high_corr_pairs,
            avg_portfolio_correlation=avg_corr,
            diversification_score=div_score,
            correlation_risk_level=risk_level,
        )

    def get_volatility_assessment(self) -> VolatilityAssessment:
        """Calculate current portfolio volatility and return an assessment."""
        realized_vol = self._estimate_portfolio_volatility()
        vol_ratio = realized_vol / max(self.target_daily_vol, 1e-9)

        if realized_vol < self.target_daily_vol * 0.5:
            regime = "calm"
        elif realized_vol < self.target_daily_vol * 1.2:
            regime = "normal"
        elif realized_vol < self.max_daily_vol:
            regime = "elevated"
        else:
            regime = "stressed"

        position_scalar = 1.0 if vol_ratio <= 1.0 else max(0.3, 1.0 / vol_ratio)
        exposure_scalar = position_scalar

        total_exposure = self._total_exposure_usd()
        var_95 = total_exposure * realized_vol * 1.645
        es_95 = var_95 * 1.25  # CVaR ≈ 1.25 × VaR for normal tail

        return VolatilityAssessment(
            realized_daily_vol=realized_vol,
            target_daily_vol=self.target_daily_vol,
            vol_ratio=vol_ratio,
            vol_regime=regime,
            position_scalar=position_scalar,
            exposure_scalar=exposure_scalar,
            var_95_usd=var_95,
            expected_shortfall_usd=es_95,
        )

    def get_full_report(self) -> PortfolioIntelligenceReport:
        """
        Generate a comprehensive portfolio intelligence report.

        Returns:
            :class:`PortfolioIntelligenceReport` covering all five dimensions.
        """
        exposure = self.get_exposure_snapshot()
        sector = self.get_sector_concentration_report()
        correlation = self.get_correlation_risk_report()
        volatility = self.get_volatility_assessment()
        health_score, health_label, actions = self._compute_health(
            exposure, sector, correlation, volatility
        )
        return PortfolioIntelligenceReport(
            exposure=exposure,
            sector_concentration=sector,
            correlation_risk=correlation,
            volatility=volatility,
            health_score=health_score,
            health_label=health_label,
            recommended_actions=actions,
        )

    # =========================================================================
    # Public API – portfolio-level optimization
    # =========================================================================

    def record_trade_result(
        self,
        strategy: str,
        pnl: float,
        return_pct: float,
    ) -> None:
        """
        Record a completed trade result so the optimizer can learn from it.

        Call this after every closed trade.  Once
        ``MIN_TRADES_FOR_OPTIMIZATION`` (50) trades have been recorded
        the portfolio optimizer becomes eligible to run.

        Args:
            strategy: Name of the strategy that produced the trade.
            pnl: Realised profit/loss in USD (negative for losses).
            return_pct: Return as a decimal fraction (e.g. ``0.02`` = 2 %).
        """
        self._trade_log.append(
            {
                "strategy": strategy,
                "pnl": pnl,
                "return_pct": return_pct,
                "win": pnl > 0,
                "timestamp": datetime.now().isoformat(),
            }
        )
        logger.debug(
            f"Trade recorded: strategy={strategy} pnl={pnl:+.2f} "
            f"return={return_pct*100:+.2f}%  "
            f"total_trades={len(self._trade_log)}"
        )

    @property
    def total_trades_recorded(self) -> int:
        """Number of completed trades recorded so far."""
        return len(self._trade_log)

    def get_optimization_status(self) -> Dict:
        """
        Return a summary of the portfolio-level optimizer's readiness.

        Returns:
            Dictionary with keys: ``trades_recorded``, ``trades_needed``,
            ``ready_to_optimize``, ``cycles_completed``,
            ``current_allocations``.
        """
        trades_recorded = len(self._trade_log)
        return {
            "trades_recorded": trades_recorded,
            "trades_needed": self._min_trades_for_opt,
            "ready_to_optimize": trades_recorded >= self._min_trades_for_opt,
            "evaluation_window": self._evaluation_trades,
            "cycles_completed": len(self.optimization_history),
            "current_allocations": {
                "capital_allocation_pct": self.current_allocations.capital_allocation_pct,
                "max_positions": self.current_allocations.max_positions,
                "risk_budget_pct": self.current_allocations.risk_budget_pct,
                "strategy_weighting": self.current_allocations.normalized_strategy_weights(),
            },
        }

    def run_portfolio_optimization(
        self,
        trigger_reason: str = "manual",
        force: bool = False,
    ) -> PortfolioOptimizationResult:
        """
        Run one portfolio-level optimization cycle.

        The optimizer adjusts four system-wide levers based on live trade
        performance:

        1. **capital_allocation_pct** – how much equity to deploy per trade
        2. **max_positions** – cap on concurrent open positions
        3. **risk_budget_pct** – maximum accepted portfolio risk per cycle
        4. **strategy_weighting** – relative weight of each active strategy

        The cycle is **gated** by ``MIN_TRADES_FOR_OPTIMIZATION``.  Pass
        ``force=True`` only in tests or manual overrides when you want to
        skip the gate.

        Args:
            trigger_reason: Human-readable reason for running (e.g.
                            ``'scheduled'``, ``'performance_degradation'``).
            force: Skip the minimum-trade-count gate.

        Returns:
            :class:`PortfolioOptimizationResult` describing the outcome.
        """
        from datetime import datetime as _dt
        cycle_id = f"portopt_{_dt.now().strftime('%Y%m%d_%H%M%S_%f')}"

        trades_available = len(self._trade_log)

        # --- Gate: refuse to optimize without sufficient data ---
        if not force and trades_available < self._min_trades_for_opt:
            msg = (
                f"Optimization skipped: only {trades_available} trades recorded, "
                f"need at least {self._min_trades_for_opt} "
                f"(MIN_TRADES_FOR_OPTIMIZATION={MIN_TRADES_FOR_OPTIMIZATION})."
            )
            logger.info(f"⏳ {msg}")
            result = PortfolioOptimizationResult(
                cycle_id=cycle_id,
                trigger_reason=trigger_reason,
                trades_used=trades_available,
                previous_allocations=self.current_allocations,
                recommended_allocations=self.current_allocations,
                was_applied=False,
                notes=[msg],
            )
            self.optimization_history.append(result)
            return result

        # Use the most recent EVALUATION_TRADES records as the analysis window,
        # capped at the number of trades actually available.
        window = min(trades_available, self._evaluation_trades)
        recent_trades = self._trade_log[-window:]

        logger.info(
            f"🔬 Portfolio optimization starting  "
            f"[cycle={cycle_id} trades={len(recent_trades)} reason={trigger_reason}]"
        )

        # ---- Analyse recent performance ----
        perf = self._analyse_trades(recent_trades)

        # ---- Optimise each lever independently ----
        new_capital_alloc, cap_notes = self._optimize_capital_allocation(perf)
        new_max_pos, pos_notes = self._optimize_max_positions(perf)
        new_risk_budget, risk_notes = self._optimize_risk_budget(perf)
        new_strategy_wts, strat_notes = self._optimize_strategy_weighting(recent_trades)

        recommended = PortfolioAllocations(
            capital_allocation_pct=new_capital_alloc,
            max_positions=new_max_pos,
            risk_budget_pct=new_risk_budget,
            strategy_weighting=new_strategy_wts,
        )

        # ---- Estimate performance delta (simplified) ----
        perf_delta = self._estimate_performance_delta(perf, recommended)

        all_notes = cap_notes + pos_notes + risk_notes + strat_notes
        if not all_notes:
            all_notes = ["All levers already at optimal levels — no changes made."]

        result = PortfolioOptimizationResult(
            cycle_id=cycle_id,
            trigger_reason=trigger_reason,
            trades_used=len(recent_trades),
            previous_allocations=self.current_allocations,
            recommended_allocations=recommended,
            performance_delta=perf_delta,
            was_applied=True,
            notes=all_notes,
        )

        # Commit the new allocations as the active baseline
        self.current_allocations = recommended
        self.optimization_history.append(result)

        logger.info(
            f"✅ Portfolio optimization complete  "
            f"[Δperf={perf_delta:+.1f}%  applied=True]"
        )
        for note in all_notes:
            logger.info(f"   • {note}")

        return result

    # =========================================================================
    # Private helpers – portfolio-level optimization
    # =========================================================================

    def _analyse_trades(self, trades: List[Dict]) -> Dict:
        """Compute summary statistics from a list of trade records."""
        if not trades:
            return {
                "win_rate": 0.0,
                "avg_return": 0.0,
                "avg_win": 0.0,
                "avg_loss": 0.0,
                "profit_factor": 1.0,
                "sharpe": 0.0,
                "max_drawdown": 0.0,
                "strategy_counts": {},
                "strategy_win_rates": {},
                "strategy_avg_returns": {},
            }

        returns = [t["return_pct"] for t in trades]
        wins = [t for t in trades if t["win"]]
        losses = [t for t in trades if not t["win"]]

        win_rate = len(wins) / len(trades)
        avg_return = float(np.mean(returns))
        avg_win = float(np.mean([t["return_pct"] for t in wins])) if wins else 0.0
        avg_loss = float(np.mean([t["return_pct"] for t in losses])) if losses else 0.0

        total_gain = sum(t["pnl"] for t in wins) if wins else 0.0
        total_loss = abs(sum(t["pnl"] for t in losses)) if losses else 1e-9
        profit_factor = total_gain / total_loss

        std_return = float(np.std(returns)) if len(returns) > 1 else 1e-9
        sharpe = avg_return / max(std_return, 1e-9)

        # Simple max drawdown from cumulative returns
        cum = np.cumsum(returns)
        running_max = np.maximum.accumulate(cum)
        drawdowns = running_max - cum
        max_drawdown = float(np.max(drawdowns)) if len(drawdowns) else 0.0

        # Per-strategy breakdown
        strategy_counts: Dict[str, int] = {}
        strategy_wins: Dict[str, int] = {}
        strategy_returns: Dict[str, List[float]] = {}
        for t in trades:
            s = t.get("strategy", "unknown")
            strategy_counts[s] = strategy_counts.get(s, 0) + 1
            strategy_wins[s] = strategy_wins.get(s, 0) + (1 if t["win"] else 0)
            strategy_returns.setdefault(s, []).append(t["return_pct"])

        strategy_win_rates = {
            s: strategy_wins.get(s, 0) / count
            for s, count in strategy_counts.items()
        }
        strategy_avg_returns = {
            s: float(np.mean(rets)) for s, rets in strategy_returns.items()
        }

        return {
            "win_rate": win_rate,
            "avg_return": avg_return,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "profit_factor": profit_factor,
            "sharpe": sharpe,
            "max_drawdown": max_drawdown,
            "strategy_counts": strategy_counts,
            "strategy_win_rates": strategy_win_rates,
            "strategy_avg_returns": strategy_avg_returns,
        }

    def _optimize_capital_allocation(
        self, perf: Dict
    ) -> Tuple[float, List[str]]:
        """
        Adjust the capital allocation fraction based on performance.

        Rules:
        - High win rate + positive Sharpe → increase allocation (up to 10 %)
        - Low win rate or negative Sharpe → decrease allocation (floor 2 %)
        - Drawdown stress → cap at 5 %
        """
        notes: List[str] = []
        current = self.current_allocations.capital_allocation_pct
        new_alloc = current

        win_rate = perf.get("win_rate", 0.5)
        sharpe = perf.get("sharpe", 0.0)
        max_dd = perf.get("max_drawdown", 0.0)

        if max_dd > 0.10:
            # Significant drawdown: cap allocation at 5 %
            if new_alloc > 0.05:
                new_alloc = 0.05
                notes.append(
                    f"capital_allocation capped at 5% due to drawdown "
                    f"({max_dd*100:.1f}%)"
                )
        elif win_rate >= 0.60 and sharpe >= 0.5:
            # Strong performance: allow up to 8 %
            new_alloc = min(current * 1.10, 0.08)
            if new_alloc != current:
                notes.append(
                    f"capital_allocation increased: "
                    f"{current*100:.1f}% → {new_alloc*100:.1f}% "
                    f"(win_rate={win_rate:.0%} sharpe={sharpe:.2f})"
                )
        elif win_rate < 0.40 or sharpe < 0:
            # Weak performance: reduce by 10 %, floor at 2 %
            new_alloc = max(current * 0.90, 0.02)
            if new_alloc != current:
                notes.append(
                    f"capital_allocation reduced: "
                    f"{current*100:.1f}% → {new_alloc*100:.1f}% "
                    f"(win_rate={win_rate:.0%} sharpe={sharpe:.2f})"
                )

        return new_alloc, notes

    def _optimize_max_positions(
        self, perf: Dict
    ) -> Tuple[int, List[str]]:
        """
        Adjust the maximum number of concurrent positions.

        Rules:
        - High profit factor + good diversification → allow more positions
        - Poor profit factor or high drawdown → reduce positions
        """
        notes: List[str] = []
        current = self.current_allocations.max_positions
        new_max = current

        pf = perf.get("profit_factor", 1.0)
        max_dd = perf.get("max_drawdown", 0.0)

        if max_dd > 0.15:
            new_max = max(current - 1, 1)
            if new_max != current:
                notes.append(
                    f"max_positions reduced: {current} → {new_max} "
                    f"(drawdown={max_dd*100:.1f}%)"
                )
        elif pf >= 1.5 and max_dd <= 0.05:
            new_max = min(current + 1, 10)
            if new_max != current:
                notes.append(
                    f"max_positions increased: {current} → {new_max} "
                    f"(profit_factor={pf:.2f})"
                )
        elif pf < 1.0:
            new_max = max(current - 1, 1)
            if new_max != current:
                notes.append(
                    f"max_positions reduced: {current} → {new_max} "
                    f"(profit_factor={pf:.2f} < 1.0)"
                )

        return new_max, notes

    def _optimize_risk_budget(
        self, perf: Dict
    ) -> Tuple[float, List[str]]:
        """
        Adjust the portfolio risk budget (% of equity risked per cycle).

        Rules:
        - Sharpe >= 1.0 and low drawdown → loosen budget by 10 % (max 4 %)
        - Drawdown > 10 % → tighten by 20 % (floor 0.5 %)
        """
        notes: List[str] = []
        current = self.current_allocations.risk_budget_pct
        new_budget = current

        sharpe = perf.get("sharpe", 0.0)
        max_dd = perf.get("max_drawdown", 0.0)

        if max_dd > 0.10:
            new_budget = max(current * 0.80, 0.005)
            if new_budget != current:
                notes.append(
                    f"risk_budget tightened: "
                    f"{current*100:.2f}% → {new_budget*100:.2f}% "
                    f"(drawdown={max_dd*100:.1f}%)"
                )
        elif sharpe >= 1.0 and max_dd <= 0.05:
            new_budget = min(current * 1.10, 0.04)
            if new_budget != current:
                notes.append(
                    f"risk_budget loosened: "
                    f"{current*100:.2f}% → {new_budget*100:.2f}% "
                    f"(sharpe={sharpe:.2f})"
                )

        return new_budget, notes

    def _optimize_strategy_weighting(
        self, trades: List[Dict]
    ) -> Tuple[Dict[str, float], List[str]]:
        """
        Reweight strategies proportionally to their risk-adjusted performance.

        Each strategy's weight is set proportional to its risk-adjusted
        performance over the evaluation window.

        For strategies with fewer than 3 trades (where Sharpe is unreliable),
        the average return is used directly as the quality signal.
        Strategies with negative signal receive the minimum weight of 0.05 so
        they are never completely excluded.
        """
        notes: List[str] = []
        current_weights = dict(self.current_allocations.strategy_weighting)

        # Group by strategy
        strategy_returns: Dict[str, List[float]] = {}
        for t in trades:
            s = t.get("strategy", "unknown")
            strategy_returns.setdefault(s, []).append(t["return_pct"])

        if not strategy_returns:
            return current_weights, notes

        # Compute quality score per strategy.
        # Use Sharpe when ≥ 3 trades are available, otherwise fall back to
        # average return so a single good (or bad) trade is handled sensibly.
        scores: Dict[str, float] = {}
        for s, rets in strategy_returns.items():
            mean_r = float(np.mean(rets))
            if len(rets) >= 3:
                std_r = float(np.std(rets))
                scores[s] = mean_r / max(std_r, 1e-9)
            else:
                # Too few trades for reliable Sharpe — use avg return scaled
                # to a comparable magnitude (÷ 0.01 maps 1% avg → score of 1)
                scores[s] = mean_r / 0.01

        # Convert score → weight (floor at 0.05 to keep all strategies alive)
        min_weight = 0.05
        raw_weights = {s: max(sc, 0.0) + min_weight for s, sc in scores.items()}
        total = sum(raw_weights.values())
        new_weights = {s: w / total for s, w in raw_weights.items()}

        # Report changes worth reporting (> 5 pp shift)
        for s, new_w in new_weights.items():
            old_w = current_weights.get(s, 1.0 / len(new_weights))
            if abs(new_w - old_w) >= 0.05:
                notes.append(
                    f"strategy_weighting[{s}]: "
                    f"{old_w*100:.0f}% → {new_w*100:.0f}% "
                    f"(score={scores[s]:.2f})"
                )

        return new_weights, notes

    def _estimate_performance_delta(
        self, perf: Dict, new_alloc: PortfolioAllocations
    ) -> float:
        """
        Estimate the expected performance improvement from new allocations (%).

        This is a heuristic estimate, not a backtest.  It measures how far the
        new allocations move toward the theoretically optimal settings given
        the current performance regime.
        """
        score_before = self._allocation_score(self.current_allocations, perf)
        score_after = self._allocation_score(new_alloc, perf)
        if score_before <= 0:
            return 0.0
        return ((score_after - score_before) / score_before) * 100.0

    def _allocation_score(self, alloc: PortfolioAllocations, perf: Dict) -> float:
        """Heuristic score (0–1) for how well allocations fit the current regime."""
        win_rate = perf.get("win_rate", 0.5)
        pf = perf.get("profit_factor", 1.0)
        sharpe = perf.get("sharpe", 0.0)
        max_dd = perf.get("max_drawdown", 0.0)

        # Ideal capital allocation: between 3 % (low perf) and 8 % (high perf)
        ideal_cap = 0.03 + 0.05 * max(0.0, min(1.0, win_rate))
        cap_score = 1.0 - abs(alloc.capital_allocation_pct - ideal_cap) / 0.10

        # Ideal max_positions: 1–10 scaled by profit factor
        ideal_pos = max(1, min(10, int(pf * 3)))
        pos_score = 1.0 - abs(alloc.max_positions - ideal_pos) / 10.0

        # Risk budget score: prefer tighter budget when Sharpe is low
        ideal_rb = 0.005 + 0.015 * max(0.0, min(1.0, sharpe))
        rb_score = 1.0 - abs(alloc.risk_budget_pct - ideal_rb) / 0.04

        # Drawdown penalty
        dd_penalty = max(0.0, max_dd - 0.05) * 5.0  # 5 pp penalty per 1 % excess dd

        score = (cap_score * 0.35 + pos_score * 0.30 + rb_score * 0.35) - dd_penalty
        return max(0.0, min(1.0, score))

    # =========================================================================
    # Private helpers – constraint application
    # =========================================================================

    def _apply_global_exposure_limit(
        self,
        symbol: str,
        size_usd: float,
        direction: str,
        portfolio_value: float,
    ) -> Tuple[float, List[str]]:
        """
        Enforce global exposure cap.

        Returns:
            Tuple of (approved_size, list_of_reduction_reasons).
        """
        reasons: List[str] = []
        current_exp = self._total_exposure_usd()
        max_allowed_usd = portfolio_value * self.max_total_exposure_pct
        headroom_usd = max(max_allowed_usd - current_exp, 0.0)

        if headroom_usd <= 0:
            return 0.0, ["Global exposure at maximum"]

        if size_usd > headroom_usd:
            reasons.append(
                f"Global exposure headroom: ${headroom_usd:,.2f} available "
                f"(requested ${size_usd:,.2f}, capped)"
            )
            size_usd = headroom_usd
        elif current_exp / portfolio_value >= self.soft_exposure_pct:
            # Approaching soft limit: apply a moderate reduction
            reduction = 0.80
            reasons.append(
                f"Soft exposure limit ({self.soft_exposure_pct * 100:.0f}%): "
                f"position reduced to {reduction * 100:.0f}%"
            )
            size_usd = size_usd * reduction

        return size_usd, reasons

    def _apply_sector_limits(
        self,
        symbol: str,
        sector: str,
        size_usd: float,
        portfolio_value: float,
    ) -> Tuple[float, List[str], bool]:
        """
        Enforce sector concentration limits.

        Returns:
            Tuple of (approved_size, reasons, blocked).
            ``blocked=True`` means the position is entirely rejected.
        """
        reasons: List[str] = []
        current_sector_usd = sum(
            v["size_usd"]
            for v in self.positions.values()
            if v.get("sector") == sector
        )
        current_sector_pct = (
            current_sector_usd / portfolio_value if portfolio_value > 0 else 0.0
        )

        # Hard limit: block entirely
        if current_sector_pct >= self.hard_sector_limit_pct:
            return 0.0, reasons, True

        hard_limit_usd = portfolio_value * self.hard_sector_limit_pct
        soft_limit_usd = portfolio_value * self.soft_sector_limit_pct
        headroom_hard = max(hard_limit_usd - current_sector_usd, 0.0)

        if size_usd > headroom_hard:
            reasons.append(
                f"Sector '{sector}' hard cap: "
                f"capped at ${headroom_hard:,.2f}"
            )
            size_usd = headroom_hard
        elif current_sector_usd + size_usd > soft_limit_usd:
            headroom_soft = max(soft_limit_usd - current_sector_usd, 0.0)
            if size_usd > headroom_soft:
                reasons.append(
                    f"Sector '{sector}' soft limit "
                    f"({self.soft_sector_limit_pct * 100:.0f}%): "
                    f"reduced from ${size_usd:,.2f} to ${headroom_soft:,.2f}"
                )
                size_usd = headroom_soft

        if size_usd <= 0:
            return 0.0, reasons, True

        return size_usd, reasons, False

    def _apply_correlation_limit(
        self,
        symbol: str,
        size_usd: float,
        portfolio_value: float,
    ) -> Tuple[float, List[str], bool]:
        """
        Reduce or reject a position based on correlation with existing holdings.

        Returns:
            Tuple of (approved_size, reasons, blocked).
        """
        reasons: List[str] = []
        existing_symbols = [s for s in self.positions if s != symbol]

        if not existing_symbols:
            return size_usd, reasons, False

        corr_values: List[float] = []
        for existing in existing_symbols:
            corr = self._compute_correlation(symbol, existing)
            if corr is not None:
                corr_values.append(abs(corr))

        if not corr_values:
            return size_usd, reasons, False

        avg_corr = float(np.mean(corr_values))

        # Full block when average correlation is at or above the absolute cap
        if avg_corr >= self.max_avg_portfolio_correlation:
            return 0.0, reasons, True

        # Partial reduction when above the high-correlation warning threshold
        if avg_corr >= self.high_correlation_threshold:
            span = self.max_avg_portfolio_correlation - self.high_correlation_threshold
            excess = avg_corr - self.high_correlation_threshold
            reduction = 1.0 - (excess / max(span, 1e-9)) * 0.5
            reduction = max(0.3, reduction)
            new_size = size_usd * reduction
            reasons.append(
                f"High correlation ({avg_corr:.2f}): "
                f"size reduced ×{reduction:.2f} "
                f"(${size_usd:,.2f} → ${new_size:,.2f})"
            )
            size_usd = new_size

        return size_usd, reasons, False

    # =========================================================================
    # Private helpers – metrics
    # =========================================================================

    def _total_exposure_usd(self) -> float:
        """Sum of all registered position sizes in USD."""
        return sum(v["size_usd"] for v in self.positions.values())

    def _sector_exposure_pct(self, sector: str, portfolio_value: float) -> float:
        """Current sector exposure as a fraction of portfolio value."""
        if portfolio_value <= 0:
            return 0.0
        total = sum(
            v["size_usd"]
            for v in self.positions.values()
            if v.get("sector") == sector
        )
        return total / portfolio_value

    def _resolve_sector(self, symbol: str) -> str:
        """Auto-classify a symbol into its crypto sector."""
        if self._sector_taxonomy_available and self._get_sector and self._get_sector_name:
            try:
                sector_enum = self._get_sector(symbol)
                return self._get_sector_name(sector_enum)
            except Exception:
                pass
        return "misc"

    def _get_volatility_scalar(self) -> float:
        """Return position sizing scalar based on current portfolio volatility."""
        realized_vol = self._estimate_portfolio_volatility()
        if realized_vol <= self.target_daily_vol:
            return 1.0
        vol_ratio = realized_vol / self.target_daily_vol
        return max(0.3, 1.0 / vol_ratio)

    def _estimate_portfolio_volatility(self) -> float:
        """
        Estimate realised portfolio daily volatility from stored price history.

        Falls back to the target volatility when insufficient data are available.
        """
        if not self.price_history:
            return self.target_daily_vol

        vol_estimates: List[Tuple[str, float]] = []
        for symbol, prices in self.price_history.items():
            if symbol not in self.positions:
                continue
            if len(prices) < self.vol_lookback + 1:
                continue
            returns = prices.pct_change().dropna()
            recent = returns.iloc[-self.vol_lookback :]
            vol_estimates.append((symbol, float(recent.std())))

        if not vol_estimates:
            return self.target_daily_vol

        total_usd = self._total_exposure_usd()
        if total_usd <= 0:
            return float(np.mean([v for _, v in vol_estimates]))

        weighted_vol = 0.0
        for symbol, est in vol_estimates:
            weight = self.positions[symbol]["size_usd"] / total_usd
            weighted_vol += weight * est

        return weighted_vol

    def _compute_correlation(self, sym_a: str, sym_b: str) -> Optional[float]:
        """
        Compute Pearson correlation between two symbols using stored price history.

        Falls back to the shared :class:`PortfolioRiskEngine` when local history
        is unavailable.
        """
        if sym_a not in self.price_history or sym_b not in self.price_history:
            if self._risk_engine_available and hasattr(
                self._risk_engine, "get_correlation"
            ):
                return self._risk_engine.get_correlation(sym_a, sym_b)
            return None

        prices_a = self.price_history[sym_a]
        prices_b = self.price_history[sym_b]

        lookback = min(len(prices_a), len(prices_b), self.correlation_lookback)
        if lookback < 20:
            return None

        ret_a = prices_a.iloc[-lookback:].pct_change().dropna()
        ret_b = prices_b.iloc[-lookback:].pct_change().dropna()

        # Align on common index; fall back to positional alignment
        common = ret_a.index.intersection(ret_b.index)
        if len(common) >= 20:
            ret_a = ret_a.loc[common]
            ret_b = ret_b.loc[common]
        else:
            min_len = min(len(ret_a), len(ret_b))
            ret_a = ret_a.iloc[-min_len:]
            ret_b = ret_b.iloc[-min_len:]

        if len(ret_a) < 20:
            return None

        corr = float(ret_a.corr(ret_b))
        return corr if not np.isnan(corr) else None

    def _compute_health(
        self,
        exposure: ExposureSnapshot,
        sector: SectorConcentrationReport,
        correlation: CorrelationRiskReport,
        volatility: VolatilityAssessment,
    ) -> Tuple[float, str, List[str]]:
        """
        Compute an overall portfolio health score (0–1) from the four reports.

        Returns:
            Tuple of (score, label, recommended_actions).
        """
        score = 1.0
        actions: List[str] = []

        # Exposure dimension
        if exposure.total_exposure_pct > self.max_total_exposure_pct:
            score -= 0.30
            actions.append(
                "🚨 Reduce total exposure — hard limit breached"
            )
        elif exposure.total_exposure_pct > self.soft_exposure_pct:
            score -= 0.10
            actions.append(
                "⚠️ Approaching exposure soft limit — add positions conservatively"
            )

        # Sector concentration dimension
        if sector.hard_breaches:
            score -= 0.20
            for s in sector.hard_breaches:
                actions.append(
                    f"🚨 Sector '{s}' at hard concentration limit — trim or avoid"
                )
        elif sector.soft_breaches:
            score -= 0.10
            for s in sector.soft_breaches:
                actions.append(
                    f"⚠️ Sector '{s}' approaching concentration limit"
                )

        # Correlation dimension
        if correlation.correlation_risk_level == "extreme":
            score -= 0.25
            actions.append(
                "🚨 Extreme portfolio correlation — diversify immediately"
            )
        elif correlation.correlation_risk_level == "high":
            score -= 0.15
            actions.append(
                "⚠️ High portfolio correlation — avoid adding similar assets"
            )
        elif correlation.correlation_risk_level == "medium":
            score -= 0.05

        # Volatility dimension
        if volatility.vol_regime == "stressed":
            score -= 0.20
            actions.append(
                "🚨 Portfolio volatility stressed — reduce position sizes"
            )
        elif volatility.vol_regime == "elevated":
            score -= 0.10
            actions.append(
                "⚠️ Elevated volatility — apply vol-targeting scalar"
            )

        score = max(0.0, min(1.0, score))

        if score >= 0.85:
            label = "optimal"
        elif score >= 0.70:
            label = "good"
        elif score >= 0.55:
            label = "caution"
        elif score >= 0.35:
            label = "warning"
        else:
            label = "critical"

        return score, label, actions


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_portfolio_intelligence_instance: Optional[PortfolioIntelligence] = None


def get_portfolio_intelligence(
    config: Optional[Dict] = None,
) -> PortfolioIntelligence:
    """
    Return the singleton :class:`PortfolioIntelligence` instance.

    On the first call the instance is created with the supplied *config*.
    Subsequent calls return the existing instance (config is ignored).

    Args:
        config: Configuration dictionary (only applied on first call).

    Returns:
        :class:`PortfolioIntelligence` instance.
    """
    global _portfolio_intelligence_instance
    if _portfolio_intelligence_instance is None:
        _portfolio_intelligence_instance = PortfolioIntelligence(config)
    return _portfolio_intelligence_instance
