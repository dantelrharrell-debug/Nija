"""
NIJA Hedge Fund Analytics
==========================

Optional hedge-fund-grade analytical layer:

1. **Multi-Strategy Correlation Analysis**
   Computes the pairwise return correlation between active strategies to
   detect overlapping exposures.  A correlation > 0.70 between two
   strategies is flagged as a concentration risk.

2. **Liquidity Heatmap**
   Tracks venue-level market depth across supported markets and produces
   a normalised heatmap score (0 = illiquid, 1 = deep/liquid) per
   symbol × venue grid.

3. **Advanced Scenario Simulation**
   Runs a quick multi-strategy stress test under configurable macro events
   (e.g. "Fed rate hike", "crypto market-wide crash", "USD spike").

Integration points
------------------
- ``bot.strategy_diversification_engine`` – strategy return streams
- ``bot.multi_venue_calibrator``          – venue execution data
- ``bot.stress_test_engine``              – scenario simulations

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import random
import statistics
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger("nija.hedge_fund_analytics")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HIGH_CORRELATION_THRESHOLD: float = 0.70    # Flag if pairwise corr > this
MIN_LIQUIDITY_SCORE: float = 0.10           # Below this → illiquid warning
DEFAULT_SCENARIO_PATHS: int = 200

KNOWN_STRATEGIES: List[str] = [
    "ApexTrend",
    "MeanReversion",
    "MomentumBreakout",
    "LiquidityReversal",
]

SUPPORTED_VENUES: List[str] = ["coinbase", "kraken", "binance", "alpaca", "okx"]
SAMPLE_SYMBOLS: List[str] = [
    "BTC-USD", "ETH-USD", "SOL-USD", "AVAX-USD", "MATIC-USD",
    "LINK-USD", "UNI-USD", "AAVE-USD", "DOT-USD", "ATOM-USD",
]

MACRO_EVENTS: Dict[str, Dict[str, float]] = {
    "fed_rate_hike": {
        "ApexTrend": -0.08, "MeanReversion": -0.04,
        "MomentumBreakout": -0.12, "LiquidityReversal": 0.02,
    },
    "crypto_market_crash": {
        "ApexTrend": -0.25, "MeanReversion": 0.05,
        "MomentumBreakout": -0.30, "LiquidityReversal": 0.10,
    },
    "usd_spike": {
        "ApexTrend": -0.10, "MeanReversion": -0.05,
        "MomentumBreakout": -0.15, "LiquidityReversal": 0.01,
    },
    "btc_halving_rally": {
        "ApexTrend": 0.15, "MeanReversion": -0.03,
        "MomentumBreakout": 0.20, "LiquidityReversal": -0.05,
    },
    "exchange_hack": {
        "ApexTrend": -0.18, "MeanReversion": 0.08,
        "MomentumBreakout": -0.22, "LiquidityReversal": 0.15,
    },
}


# ---------------------------------------------------------------------------
# Correlation analysis
# ---------------------------------------------------------------------------

@dataclass
class CorrelationResult:
    """Pairwise correlation between two strategies."""
    strategy_a: str
    strategy_b: str
    correlation: float
    is_high: bool
    sample_count: int
    note: str = ""

    def to_dict(self) -> Dict:
        return {
            "strategy_a": self.strategy_a,
            "strategy_b": self.strategy_b,
            "correlation": round(self.correlation, 4),
            "is_high": self.is_high,
            "sample_count": self.sample_count,
            "note": self.note,
        }


@dataclass
class CorrelationMatrix:
    """Full pairwise correlation matrix for all tracked strategies."""
    timestamp: str
    strategies: List[str]
    correlations: List[CorrelationResult]
    high_correlation_pairs: List[Tuple[str, str]]

    def summary(self) -> str:
        lines = ["=== Multi-Strategy Correlation Analysis ==="]
        for c in self.correlations:
            flag = " ⚠️  HIGH CORRELATION" if c.is_high else ""
            lines.append(
                f"  {c.strategy_a:25s} ↔ {c.strategy_b:25s}: "
                f"{c.correlation:+.3f}{flag}"
            )
        if self.high_correlation_pairs:
            lines.append(
                f"\n⚠️  {len(self.high_correlation_pairs)} high-correlation pair(s) detected."
            )
        else:
            lines.append("\n✅ No high-correlation pairs detected.")
        return "\n".join(lines)


class StrategyCorrelationAnalyzer:
    """
    Accumulates per-strategy return streams and computes pairwise correlations.

    Usage
    -----
    analyzer = StrategyCorrelationAnalyzer()
    analyzer.record_return("ApexTrend", 0.015)
    analyzer.record_return("MomentumBreakout", 0.018)
    matrix = analyzer.compute_matrix()
    print(matrix.summary())
    """

    def __init__(self, max_history: int = 500) -> None:
        self._returns: Dict[str, List[float]] = {s: [] for s in KNOWN_STRATEGIES}
        self._max_history = max_history
        self._lock = threading.Lock()

    def record_return(self, strategy: str, return_pct: float) -> None:
        """Record one trade return for a strategy."""
        with self._lock:
            if strategy not in self._returns:
                self._returns[strategy] = []
            self._returns[strategy].append(return_pct)
            # Keep rolling window
            if len(self._returns[strategy]) > self._max_history:
                self._returns[strategy] = self._returns[strategy][-self._max_history:]

    def compute_matrix(self) -> CorrelationMatrix:
        """Compute the full pairwise correlation matrix."""
        with self._lock:
            strategies = [s for s, r in self._returns.items() if len(r) >= 10]
            returns_copy = {s: list(self._returns[s]) for s in strategies}

        correlations: List[CorrelationResult] = []
        high_pairs: List[Tuple[str, str]] = []

        for i, s_a in enumerate(strategies):
            for s_b in strategies[i + 1:]:
                r_a = returns_copy[s_a]
                r_b = returns_copy[s_b]
                # Align lengths
                min_len = min(len(r_a), len(r_b))
                if min_len < 5:
                    continue
                r_a = r_a[-min_len:]
                r_b = r_b[-min_len:]

                try:
                    corr_matrix = np.corrcoef(r_a, r_b)
                    corr = float(corr_matrix[0, 1])
                    if not np.isfinite(corr):
                        corr = 0.0
                except Exception:
                    corr = 0.0

                is_high = abs(corr) >= HIGH_CORRELATION_THRESHOLD
                if is_high:
                    high_pairs.append((s_a, s_b))

                correlations.append(CorrelationResult(
                    strategy_a=s_a,
                    strategy_b=s_b,
                    correlation=corr,
                    is_high=is_high,
                    sample_count=min_len,
                    note="overlapping exposure — consider reducing one" if is_high else "",
                ))

        return CorrelationMatrix(
            timestamp=datetime.utcnow().isoformat(),
            strategies=strategies,
            correlations=correlations,
            high_correlation_pairs=high_pairs,
        )


# ---------------------------------------------------------------------------
# Liquidity heatmap
# ---------------------------------------------------------------------------

@dataclass
class LiquidityCell:
    """One cell in the symbol × venue heatmap."""
    symbol: str
    venue: str
    score: float                  # 0 (illiquid) → 1 (deep/liquid)
    spread_bps: float
    depth_usd: float
    is_warning: bool
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> Dict:
        return {
            "symbol": self.symbol,
            "venue": self.venue,
            "score": round(self.score, 3),
            "spread_bps": round(self.spread_bps, 2),
            "depth_usd": round(self.depth_usd, 2),
            "is_warning": self.is_warning,
        }


@dataclass
class LiquidityHeatmap:
    """Full symbol × venue liquidity heatmap."""
    timestamp: str
    cells: List[LiquidityCell]
    warning_cells: List[Tuple[str, str]]   # (symbol, venue)

    def summary(self) -> str:
        lines = ["=== Liquidity Heatmap ==="]
        symbols = sorted({c.symbol for c in self.cells})
        venues = sorted({c.venue for c in self.cells})
        header = f"{'Symbol':15s}" + "".join(f"{v:12s}" for v in venues)
        lines.append(header)
        cell_map = {(c.symbol, c.venue): c for c in self.cells}
        for sym in symbols:
            row = f"{sym:15s}"
            for venue in venues:
                cell = cell_map.get((sym, venue))
                if cell:
                    flag = "⚠️" if cell.is_warning else "  "
                    row += f"{cell.score:.2f}{flag}     "
                else:
                    row += "N/A          "
            lines.append(row)
        if self.warning_cells:
            lines.append(f"\n⚠️  {len(self.warning_cells)} illiquid cell(s) detected.")
        return "\n".join(lines)


class LiquidityHeatmapEngine:
    """
    Maintains venue-level market depth data and generates liquidity heatmaps.

    In live operation, update() is called periodically with fresh order-book
    data from each venue.  In testing, synthetic data can be injected.
    """

    def __init__(self) -> None:
        self._data: Dict[Tuple[str, str], LiquidityCell] = {}
        self._lock = threading.Lock()

    def update(
        self,
        symbol: str,
        venue: str,
        spread_bps: float,
        depth_usd: float,
    ) -> LiquidityCell:
        """
        Update liquidity data for one symbol × venue pair.

        Score is computed as:
            score = 1 / (1 + spread_bps / 10) × log10(depth_usd + 1) / 7
        Clamped to [0, 1].
        """
        import math
        spread_factor = 1.0 / (1.0 + spread_bps / 10.0)
        depth_factor = math.log10(max(depth_usd, 1.0)) / 7.0   # $10M depth → 1.0
        score = max(0.0, min(1.0, spread_factor * depth_factor))
        is_warning = score < MIN_LIQUIDITY_SCORE

        cell = LiquidityCell(
            symbol=symbol,
            venue=venue,
            score=score,
            spread_bps=spread_bps,
            depth_usd=depth_usd,
            is_warning=is_warning,
        )
        with self._lock:
            self._data[(symbol, venue)] = cell
        if is_warning:
            logger.warning(
                "⚠️  Low liquidity: %s on %s — score=%.2f, spread=%.1f bps",
                symbol, venue, score, spread_bps,
            )
        return cell

    def get_heatmap(self) -> LiquidityHeatmap:
        """Return the current heatmap snapshot."""
        with self._lock:
            cells = list(self._data.values())
        warnings = [(c.symbol, c.venue) for c in cells if c.is_warning]
        return LiquidityHeatmap(
            timestamp=datetime.utcnow().isoformat(),
            cells=cells,
            warning_cells=warnings,
        )

    def get_score(self, symbol: str, venue: str) -> Optional[float]:
        """Return the liquidity score for a specific symbol × venue pair."""
        with self._lock:
            cell = self._data.get((symbol, venue))
        return cell.score if cell else None


# ---------------------------------------------------------------------------
# Advanced scenario simulation
# ---------------------------------------------------------------------------

@dataclass
class ScenarioSimResult:
    """Result of running a macro scenario across strategies."""
    scenario: str
    strategy_impacts: Dict[str, float]    # strategy → expected return change
    portfolio_impact: float               # weighted average
    worst_strategy: str
    best_strategy: str
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def summary(self) -> str:
        lines = [
            f"Scenario: {self.scenario}",
            f"  Portfolio impact : {self.portfolio_impact:+.2%}",
            f"  Worst strategy   : {self.worst_strategy} "
            f"({self.strategy_impacts.get(self.worst_strategy, 0):+.2%})",
            f"  Best strategy    : {self.best_strategy} "
            f"({self.strategy_impacts.get(self.best_strategy, 0):+.2%})",
        ]
        return "\n".join(lines)


def simulate_macro_scenario(
    scenario: str,
    strategy_weights: Optional[Dict[str, float]] = None,
    noise_std: float = 0.02,
    num_paths: int = DEFAULT_SCENARIO_PATHS,
    rng: Optional[random.Random] = None,
) -> ScenarioSimResult:
    """
    Simulate the impact of a predefined macro event across strategies.

    Parameters
    ----------
    scenario : str
        One of the keys in ``MACRO_EVENTS``.
    strategy_weights : dict | None
        Capital weight per strategy.  Defaults to equal weights.
    noise_std : float
        Standard deviation of Monte Carlo noise added to each strategy's impact.
    num_paths : int
        Number of Monte Carlo paths for noise sampling.
    rng : random.Random | None
        Optional random number generator for reproducibility.
    """
    if scenario not in MACRO_EVENTS:
        raise ValueError(f"Unknown scenario '{scenario}'. Known: {list(MACRO_EVENTS)}")

    rng = rng or random.Random()
    np_rng = np.random.default_rng(rng.randint(0, 2**31))

    base_impacts = MACRO_EVENTS[scenario]
    strategy_weights = strategy_weights or {s: 1.0 / len(KNOWN_STRATEGIES) for s in KNOWN_STRATEGIES}

    # Monte Carlo: add noise and average
    avg_impacts: Dict[str, float] = {}
    for strategy, base in base_impacts.items():
        path_returns = [
            base + float(np_rng.normal(0, noise_std))
            for _ in range(num_paths)
        ]
        avg_impacts[strategy] = statistics.mean(path_returns)

    # Weighted portfolio impact
    portfolio_impact = sum(
        avg_impacts.get(s, 0) * strategy_weights.get(s, 0)
        for s in avg_impacts
    )

    worst = min(avg_impacts, key=avg_impacts.get)
    best = max(avg_impacts, key=avg_impacts.get)

    result = ScenarioSimResult(
        scenario=scenario,
        strategy_impacts=avg_impacts,
        portfolio_impact=portfolio_impact,
        worst_strategy=worst,
        best_strategy=best,
    )
    logger.info("Macro scenario '%s': portfolio_impact=%+.2%%", scenario, portfolio_impact)
    return result


# ---------------------------------------------------------------------------
# Façade class
# ---------------------------------------------------------------------------

class HedgeFundAnalytics:
    """
    Unified hedge-fund analytics façade.

    Exposes:
    - ``correlation_analyzer``  – StrategyCorrelationAnalyzer
    - ``liquidity_engine``      – LiquidityHeatmapEngine
    - ``simulate_scenario()``   – advanced scenario simulation wrapper
    """

    def __init__(self) -> None:
        self.correlation_analyzer = StrategyCorrelationAnalyzer()
        self.liquidity_engine = LiquidityHeatmapEngine()
        logger.info("HedgeFundAnalytics initialised")

    def simulate_scenario(
        self,
        scenario: str,
        strategy_weights: Optional[Dict[str, float]] = None,
    ) -> ScenarioSimResult:
        """Simulate a macro event. See ``simulate_macro_scenario`` for details."""
        return simulate_macro_scenario(scenario, strategy_weights)

    def list_scenarios(self) -> List[str]:
        """Return the list of available macro event scenarios."""
        return list(MACRO_EVENTS.keys())

    def full_report(self, strategy_weights: Optional[Dict[str, float]] = None) -> str:
        """Generate a human-readable report combining all analytics."""
        lines = [
            "=" * 60,
            "NIJA HEDGE FUND ANALYTICS — FULL REPORT",
            f"Timestamp: {datetime.utcnow().isoformat()}",
            "=" * 60,
        ]

        # Correlation matrix
        matrix = self.correlation_analyzer.compute_matrix()
        lines.append(matrix.summary())
        lines.append("")

        # Liquidity heatmap
        heatmap = self.liquidity_engine.get_heatmap()
        if heatmap.cells:
            lines.append(heatmap.summary())
        else:
            lines.append("Liquidity heatmap: no data yet.")
        lines.append("")

        # Scenario simulations
        lines.append("=== Macro Scenario Simulations ===")
        for scenario in self.list_scenarios():
            result = self.simulate_scenario(scenario, strategy_weights)
            lines.append(result.summary())

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_analytics_instance: Optional[HedgeFundAnalytics] = None
_analytics_lock = threading.Lock()


def get_hedge_fund_analytics() -> HedgeFundAnalytics:
    """Return the global HedgeFundAnalytics singleton."""
    global _analytics_instance
    with _analytics_lock:
        if _analytics_instance is None:
            _analytics_instance = HedgeFundAnalytics()
        return _analytics_instance
