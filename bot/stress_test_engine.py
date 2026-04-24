"""
Stress Test Engine

Unified stress-testing framework that subjects portfolio strategies to
extreme market scenarios using Monte Carlo simulation.

Scenarios
---------
flash_crash        – sudden 15–40 % price collapse over 1–3 candles
high_volatility    – sustained 3× normal volatility for 20–60 periods
liquidity_drought  – bid-ask spreads widen 5–20×, fill rate drops to 30–60 %
trending_crisis    – prolonged bear market with 25–60 % drawdown
regime_whipsaw     – rapid alternation between bull/bear/ranging regimes

Usage
-----
    from bot.stress_test_engine import StressTestEngine

    engine = StressTestEngine(initial_capital=50_000, num_paths=500, seed=42)
NIJA Unified Stress Test Engine

Validates NIJA's trading system under extreme market conditions before
deploying real capital.  Orchestrates three distinct stress scenarios:

1. **Flash Crash**       – sudden price drop of 20-50 % within minutes
2. **High Volatility**   – sustained elevated volatility (3–10× normal)
3. **Liquidity Drought** – order-book depth shrinks, spreads widen 5–20×

Each scenario runs a configurable number of Monte Carlo paths and reports
which percentage of paths survive without breaching key risk limits.

Integration points
------------------
- ``bot.monte_carlo_stress_test`` – per-trade execution imperfection modelling
- ``bot.liquidity_stress_testing`` – order-book and spread compression
- ``bot.global_risk_controller``  – kill-switch / risk-level evaluation
- ``bot.portfolio_var_monitor``   – real-time VaR during the stress run

Usage
-----
    engine = StressTestEngine(initial_capital=100_000)
    report = engine.run_all_scenarios()
    print(report.summary())

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import math
import random
import statistics
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("nija.stress_test_engine")


# ─────────────────────────────────────────────────────────────────────────────
# Result dataclasses
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ScenarioResult:
    scenario_name: str
    num_paths: int
    mean_pnl: float
    median_pnl: float
    pct_5_pnl: float       # 5th-percentile P&L (tail loss)
    pct_95_pnl: float      # 95th-percentile P&L (tail gain)
    mean_max_drawdown: float
    worst_drawdown: float
    survival_rate: float   # fraction of paths that don't lose > 20 %
    var_95: float          # Value-at-Risk at 95 % confidence
    cvar_95: float         # Conditional VaR (expected loss beyond VaR)
    paths_raw: List[float] = field(default_factory=list, repr=False)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scenario_name":     self.scenario_name,
            "num_paths":         self.num_paths,
            "mean_pnl":          round(self.mean_pnl, 2),
            "median_pnl":        round(self.median_pnl, 2),
            "pct_5_pnl":         round(self.pct_5_pnl, 2),
            "pct_95_pnl":        round(self.pct_95_pnl, 2),
            "mean_max_drawdown": round(self.mean_max_drawdown, 4),
            "worst_drawdown":    round(self.worst_drawdown, 4),
            "survival_rate":     round(self.survival_rate, 4),
            "var_95":            round(self.var_95, 2),
            "cvar_95":           round(self.cvar_95, 2),
        }
# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FLASH_CRASH_DROP_RANGE: Tuple[float, float] = (0.20, 0.50)   # 20–50 %
HIGH_VOL_MULTIPLIER_RANGE: Tuple[float, float] = (3.0, 10.0)  # vs normal
LIQUIDITY_SPREAD_MULTIPLIER_RANGE: Tuple[float, float] = (5.0, 20.0)

DEFAULT_NUM_PATHS: int = 500
DEFAULT_INITIAL_CAPITAL: float = 100_000.0
MAX_DRAWDOWN_LIMIT: float = 0.20   # 20 % hard stop
VAR_BREACH_LIMIT: float = 0.08     # 8 % 99 % VaR hard limit

# Crypto markets tested in a representative sample
SAMPLE_MARKETS: List[str] = [
    "BTC-USD", "ETH-USD", "SOL-USD", "AVAX-USD", "MATIC-USD",
    "LINK-USD", "UNI-USD", "AAVE-USD", "DOT-USD", "ATOM-USD",
    "ADA-USD", "XRP-USD", "LTC-USD", "BCH-USD", "FIL-USD",
]


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class PathResult:
    """Result of one Monte Carlo path through a stress scenario."""
    path_id: int
    scenario: str
    final_capital: float
    peak_capital: float
    trough_capital: float
    max_drawdown_pct: float
    var_breached: bool
    kill_switch_triggered: bool
    num_trades: int
    win_rate: float
    total_pnl: float
    execution_notes: List[str] = field(default_factory=list)

    @property
    def survived(self) -> bool:
        """Path survived if drawdown stayed within limit and kill-switch was not triggered."""
        return (
            self.max_drawdown_pct < MAX_DRAWDOWN_LIMIT
            and not self.kill_switch_triggered
        )


@dataclass
class ScenarioReport:
    """Aggregated results across all paths for a single scenario."""
    scenario: str
    num_paths: int
    survival_rate: float               # fraction of paths that survived
    avg_final_capital: float
    avg_max_drawdown_pct: float
    worst_drawdown_pct: float
    var_breach_rate: float             # fraction of paths with a VaR breach
    kill_switch_rate: float            # fraction that triggered the kill-switch
    avg_win_rate: float
    paths: List[PathResult] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"=== {self.scenario} Stress Scenario ===",
            f"  Paths run          : {self.num_paths}",
            f"  Survival rate      : {self.survival_rate * 100:.1f}%",
            f"  Avg final capital  : ${self.avg_final_capital:,.2f}",
            f"  Avg max drawdown   : {self.avg_max_drawdown_pct * 100:.2f}%",
            f"  Worst drawdown     : {self.worst_drawdown_pct * 100:.2f}%",
            f"  VaR breach rate    : {self.var_breach_rate * 100:.1f}%",
            f"  Kill-switch rate   : {self.kill_switch_rate * 100:.1f}%",
            f"  Avg win rate       : {self.avg_win_rate * 100:.1f}%",
        ]
        return "\n".join(lines)


@dataclass
class StressTestReport:
    initial_capital: float
    num_paths: int
    seed: int
    run_at: str
    scenario_results: List[ScenarioResult] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            "=" * 70,
            f"📊 STRESS TEST REPORT  |  capital=${self.initial_capital:,.0f}"
            f"  |  paths={self.num_paths}  |  seed={self.seed}",
            f"   Run at: {self.run_at}",
            "=" * 70,
        ]
        for r in self.scenario_results:
            verdict = "✅ PASS" if r.survival_rate >= 0.80 else "⚠️  CAUTION" if r.survival_rate >= 0.60 else "🔴 FAIL"
            lines += [
                f"\n📌 {r.scenario_name}  {verdict}",
                f"   Survival rate : {r.survival_rate*100:.1f}%",
                f"   Mean P&L      : ${r.mean_pnl:+,.2f}",
                f"   P5 / P95 P&L  : ${r.pct_5_pnl:+,.2f} / ${r.pct_95_pnl:+,.2f}",
                f"   VaR-95        : ${r.var_95:,.2f}",
                f"   CVaR-95       : ${r.cvar_95:,.2f}",
                f"   Worst dd      : {r.worst_drawdown*100:.1f}%",
            ]
        lines.append("=" * 70)
        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "initial_capital":   self.initial_capital,
            "num_paths":         self.num_paths,
            "seed":              self.seed,
            "timestamp":         self.run_at,
            "scenarios":         [r.to_dict() for r in self.scenario_results],
        }

    @property
    def scenarios(self) -> List[ScenarioResult]:
        """Alias for scenario_results — public shorthand."""
        return self.scenario_results

    @property
    def overall_passed(self) -> bool:
        """True when the overall survival rate meets the minimum threshold (60%)."""
        return self.overall_survival_rate >= 0.60

    @property
    def worst_scenario(self) -> Optional[ScenarioResult]:
        if not self.scenario_results:
            return None
        return min(self.scenario_results, key=lambda r: r.survival_rate)

    @property
    def overall_survival_rate(self) -> float:
        if not self.scenario_results:
            return 1.0
        return statistics.mean(r.survival_rate for r in self.scenario_results)


# ---------------------------------------------------------------------------
# Scenario helpers
# ---------------------------------------------------------------------------

class _ScenarioRunner:
    """Internal helper that runs individual Monte Carlo paths for a scenario."""

    def __init__(self, initial_capital: float, rng: random.Random) -> None:
        self._initial_capital = initial_capital
        self._rng = rng
        self._np_rng = np.random.default_rng(rng.randint(0, 2**31))

    # ------------------------------------------------------------------
    # Public scenario runners
    # ------------------------------------------------------------------

    def run_flash_crash(self, path_id: int) -> PathResult:
        """Simulate a sudden 20-50% price crash within a short window."""
        drop_pct = self._rng.uniform(*FLASH_CRASH_DROP_RANGE)
        num_trades = self._rng.randint(5, 20)

        capital = self._initial_capital
        peak = capital
        trough = capital
        wins = 0
        var_breached = False
        kill_switch = False
        notes: List[str] = []

        for i in range(num_trades):
            # During flash crash: losses dominate, slippage is extreme
            is_crash_trade = i < num_trades // 2
            if is_crash_trade:
                pnl_pct = self._np_rng.normal(-drop_pct / num_trades * 2, 0.015)
                notes.append(f"trade {i}: crash slippage={pnl_pct*100:.2f}%")
            else:
                # Recovery phase: smaller positions, mixed results
                pnl_pct = self._np_rng.normal(0.002, 0.008)

            trade_size = capital * 0.05  # 5% per trade
            pnl = trade_size * pnl_pct
            capital += pnl

            if pnl > 0:
                wins += 1

            peak = max(peak, capital)
            trough = min(trough, capital)
            drawdown = (peak - capital) / peak if peak > 0 else 0

            if drawdown >= VAR_BREACH_LIMIT:
                var_breached = True
            if drawdown >= MAX_DRAWDOWN_LIMIT:
                kill_switch = True
                notes.append(f"kill-switch at trade {i}, drawdown={drawdown*100:.1f}%")
                break

            capital = max(capital, 0.0)

        max_dd = (peak - trough) / peak if peak > 0 else 0
        return PathResult(
            path_id=path_id,
            scenario="FlashCrash",
            final_capital=capital,
            peak_capital=peak,
            trough_capital=trough,
            max_drawdown_pct=max_dd,
            var_breached=var_breached,
            kill_switch_triggered=kill_switch,
            num_trades=num_trades,
            win_rate=wins / num_trades if num_trades > 0 else 0,
            total_pnl=capital - self._initial_capital,
            execution_notes=notes,
        )

    def run_high_volatility(self, path_id: int) -> PathResult:
        """Simulate sustained high-volatility market conditions."""
        vol_mult = self._rng.uniform(*HIGH_VOL_MULTIPLIER_RANGE)
        num_trades = self._rng.randint(20, 60)

        # Normal volatility ~0.8% per trade; scale by multiplier
        base_vol = 0.008
        effective_vol = base_vol * vol_mult

        capital = self._initial_capital
        peak = capital
        trough = capital
        wins = 0
        var_breached = False
        kill_switch = False
        notes: List[str] = []

        for i in range(num_trades):
            pnl_pct = self._np_rng.normal(0.0, effective_vol)
            trade_size = capital * 0.04
            pnl = trade_size * pnl_pct
            capital += pnl

            if pnl > 0:
                wins += 1

            peak = max(peak, capital)
            trough = min(trough, capital)
            drawdown = (peak - capital) / peak if peak > 0 else 0

            if drawdown >= VAR_BREACH_LIMIT:
                var_breached = True
            if drawdown >= MAX_DRAWDOWN_LIMIT:
                kill_switch = True
                notes.append(f"kill-switch at trade {i}: volatility={vol_mult:.1f}x")
                break

            capital = max(capital, 0.0)

        max_dd = (peak - trough) / peak if peak > 0 else 0
        return PathResult(
            path_id=path_id,
            scenario="HighVolatility",
            final_capital=capital,
            peak_capital=peak,
            trough_capital=trough,
            max_drawdown_pct=max_dd,
            var_breached=var_breached,
            kill_switch_triggered=kill_switch,
            num_trades=num_trades,
            win_rate=wins / num_trades if num_trades > 0 else 0,
            total_pnl=capital - self._initial_capital,
            execution_notes=notes,
        )

    def run_liquidity_drought(self, path_id: int) -> PathResult:
        """Simulate extreme spread widening and partial fills."""
        spread_mult = self._rng.uniform(*LIQUIDITY_SPREAD_MULTIPLIER_RANGE)
        num_trades = self._rng.randint(10, 30)

        base_spread_cost_pct = 0.0005   # 5 bps normal spread
        effective_spread_pct = base_spread_cost_pct * spread_mult

        capital = self._initial_capital
        peak = capital
        trough = capital
        wins = 0
        var_breached = False
        kill_switch = False
        notes: List[str] = []

        for i in range(num_trades):
            # Partial fill (random 40–100% fill rate during drought)
            fill_pct = self._rng.uniform(0.40, 1.0)
            trade_size = capital * 0.05 * fill_pct

            # Expected trade pnl before spread cost
            raw_pnl_pct = self._np_rng.normal(0.003, 0.010)
            # Deduct spread cost (paid on entry AND exit)
            net_pnl_pct = raw_pnl_pct - (effective_spread_pct * 2)
            pnl = trade_size * net_pnl_pct
            capital += pnl

            if pnl > 0:
                wins += 1

            if fill_pct < 0.70:
                notes.append(f"trade {i}: partial fill {fill_pct*100:.0f}%, spread={spread_mult:.1f}x")

            peak = max(peak, capital)
            trough = min(trough, capital)
            drawdown = (peak - capital) / peak if peak > 0 else 0

            if drawdown >= VAR_BREACH_LIMIT:
                var_breached = True
            if drawdown >= MAX_DRAWDOWN_LIMIT:
                kill_switch = True
                notes.append(f"kill-switch at trade {i}: spread={spread_mult:.1f}x")
                break

            capital = max(capital, 0.0)

        max_dd = (peak - trough) / peak if peak > 0 else 0
        return PathResult(
            path_id=path_id,
            scenario="LiquidityDrought",
            final_capital=capital,
            peak_capital=peak,
            trough_capital=trough,
            max_drawdown_pct=max_dd,
            var_breached=var_breached,
            kill_switch_triggered=kill_switch,
            num_trades=num_trades,
            win_rate=wins / num_trades if num_trades > 0 else 0,
            total_pnl=capital - self._initial_capital,
            execution_notes=notes,
        )


def _aggregate(paths: List[PathResult], scenario_name: str) -> ScenarioReport:
    """Aggregate a list of PathResult objects into a ScenarioReport."""
    n = len(paths)
    if n == 0:
        return ScenarioReport(
            scenario=scenario_name, num_paths=0,
            survival_rate=0, avg_final_capital=0,
            avg_max_drawdown_pct=0, worst_drawdown_pct=0,
            var_breach_rate=0, kill_switch_rate=0, avg_win_rate=0,
        )

    survival_rate = sum(1 for p in paths if p.survived) / n
    avg_capital = statistics.mean(p.final_capital for p in paths)
    avg_dd = statistics.mean(p.max_drawdown_pct for p in paths)
    worst_dd = max(p.max_drawdown_pct for p in paths)
    var_rate = sum(1 for p in paths if p.var_breached) / n
    ks_rate = sum(1 for p in paths if p.kill_switch_triggered) / n
    avg_wr = statistics.mean(p.win_rate for p in paths)

    return ScenarioReport(
        scenario=scenario_name,
        num_paths=n,
        survival_rate=survival_rate,
        avg_final_capital=avg_capital,
        avg_max_drawdown_pct=avg_dd,
        worst_drawdown_pct=worst_dd,
        var_breach_rate=var_rate,
        kill_switch_rate=ks_rate,
        avg_win_rate=avg_wr,
        paths=paths,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class StressTestEngine:
    """
    Orchestrates flash-crash, high-volatility, and liquidity-drought stress
    tests across a configurable number of Monte Carlo paths.

    Parameters
    ----------
    initial_capital : float
        Starting portfolio value for each simulated path.
    num_paths : int
        Number of Monte Carlo paths per scenario (default 500).
    seed : int
        Random seed for reproducibility (default 42).
    win_rate : float
        Assumed base win rate (default 0.55).
    avg_win_pct : float
        Average winning trade as % of capital (default 0.012).
    avg_loss_pct : float
        Average losing trade as % of capital (default 0.008).
    trades_per_scenario : int
        Number of simulated trades per path (default 200).
        Starting capital for each Monte Carlo path.
    num_paths : int
        Number of independent simulation paths per scenario.
    seed : int | None
        Random seed for reproducibility.  None = non-deterministic.
    """

    def __init__(
        self,
        initial_capital: float = 50_000.0,
        num_paths: int = 500,
        seed: int = 42,
        win_rate: float = 0.55,
        avg_win_pct: float = 0.012,
        avg_loss_pct: float = 0.008,
        trades_per_scenario: int = 200,
    ) -> None:
        self.initial_capital     = max(1.0, initial_capital)
        self.num_paths           = max(10, num_paths)
        self.seed                = seed
        self.win_rate            = win_rate
        self.avg_win_pct         = avg_win_pct
        self.avg_loss_pct        = avg_loss_pct
        self.trades_per_scenario = trades_per_scenario
        self._lock               = threading.RLock()

        logger.info(
            "🧪 StressTestEngine | capital=$%.0f | paths=%d | seed=%d",
            self.initial_capital, self.num_paths, self.seed,
        )

    # ── public API ────────────────────────────────────────────────────────────

    def run_all_scenarios(self) -> StressTestReport:
        """Run the three core stress scenarios and return a combined report."""
        report = StressTestReport(
            initial_capital=self.initial_capital,
            num_paths=self.num_paths,
            seed=self.seed,
            run_at=_now(),
        )
        scenarios: List[Tuple[str, Callable[[random.Random], float]]] = [
            ("FlashCrash",       self._scenario_flash_crash),
            ("HighVolatility",   self._scenario_high_volatility),
            ("LiquidityDrought", self._scenario_liquidity_drought),
        ]
        for name, scenario_fn in scenarios:
            result = self._run_scenario(name, scenario_fn)
            report.scenario_results.append(result)
            logger.info(
                "[StressTest] %-22s survival=%.1f%%  VaR=$%.0f",
                name, result.survival_rate * 100, result.var_95,
            )
        return report

    def run_flash_crash_scenario(self) -> ScenarioReport:
        """Run the FlashCrash scenario and return a ScenarioReport."""
        result = self._run_scenario("FlashCrash", self._scenario_flash_crash)
        return self._result_to_report(result)

    def run_high_volatility_scenario(self) -> ScenarioReport:
        """Run the HighVolatility scenario and return a ScenarioReport."""
        result = self._run_scenario("HighVolatility", self._scenario_high_volatility)
        return self._result_to_report(result)

    def run_liquidity_drought_scenario(self) -> ScenarioReport:
        """Run the LiquidityDrought scenario and return a ScenarioReport."""
        result = self._run_scenario("LiquidityDrought", self._scenario_liquidity_drought)
        return self._result_to_report(result)

    def get_markets(self) -> List[str]:
        """Return the list of crypto markets used in stress scenarios."""
        return list(SAMPLE_MARKETS)

    def _result_to_report(self, result: ScenarioResult) -> ScenarioReport:
        """Convert a ScenarioResult to a ScenarioReport for the public per-scenario API."""
        avg_final = self.initial_capital + result.mean_pnl
        return ScenarioReport(
            scenario=result.scenario_name,
            num_paths=result.num_paths,
            survival_rate=result.survival_rate,
            avg_final_capital=max(0.0, avg_final),
            avg_max_drawdown_pct=result.mean_max_drawdown,
            worst_drawdown_pct=result.worst_drawdown,
            var_breach_rate=0.0,
            kill_switch_rate=0.0,
            avg_win_rate=0.0,
        )

    # ── scenario implementations ─────────────────────────────────────────────

    def _scenario_flash_crash(self, rng: random.Random) -> float:
        """Sudden 15–40 % price collapse; stop-losses may gap through."""
        crash_pct    = rng.uniform(0.15, 0.40)
        gap_factor   = rng.uniform(1.0, 2.5)  # slippage multiplier
        capital      = self._simulate_trades(rng, win_rate_adj=-0.08, loss_mult=1 + crash_pct * gap_factor)
        return capital

    def _scenario_high_volatility(self, rng: random.Random) -> float:
        """Sustained 3× normal volatility for 20–60 periods."""
        vol_mult = rng.uniform(2.5, 4.0)
        return self._simulate_trades(
            rng,
            win_rate_adj=-0.04,
            win_mult=vol_mult * 0.6,
            loss_mult=vol_mult,
        )

    def _scenario_liquidity_drought(self, rng: random.Random) -> float:
        """Wide spreads, reduced fill rate, higher impact costs."""
        fill_rate    = rng.uniform(0.30, 0.60)
        spread_mult  = rng.uniform(5.0, 20.0)
        cost_per_trade = self.avg_loss_pct * (spread_mult - 1) * 0.1
        return self._simulate_trades(
            rng,
            win_rate_adj=-0.06,
            extra_cost_pct=cost_per_trade,
            fill_rate=fill_rate,
        )

    def _scenario_trending_crisis(self, rng: random.Random) -> float:
        """Prolonged bear market – 25–60 % drawdown environment."""
        bear_magnitude = rng.uniform(0.25, 0.60)
        return self._simulate_trades(
            rng,
            win_rate_adj=-bear_magnitude * 0.3,
            loss_mult=1.0 + bear_magnitude,
        )

    def _scenario_regime_whipsaw(self, rng: random.Random) -> float:
        """Rapid regime shifts; trend-following strategies suffer."""
        regime_cost = rng.uniform(0.005, 0.015)  # extra cost per whipsaw
        return self._simulate_trades(
            rng,
            win_rate_adj=-0.10,
            extra_cost_pct=regime_cost,
        )

    # ── simulation core ───────────────────────────────────────────────────────

    def _simulate_trades(
        self,
        rng: random.Random,
        win_rate_adj: float = 0.0,
        win_mult: float = 1.0,
        loss_mult: float = 1.0,
        extra_cost_pct: float = 0.0,
        fill_rate: float = 1.0,
    ) -> float:
        """
        Simulate a sequence of trades under modified parameters.
        Returns the final capital level.
        """
        capital  = self.initial_capital
        wr       = max(0.05, min(0.95, self.win_rate + win_rate_adj))
        peak     = capital

        for _ in range(self.trades_per_scenario):
            # Some trades don't fill in liquidity-drought scenarios
            if fill_rate < 1.0 and rng.random() > fill_rate:
                continue

            position_pct = rng.uniform(0.005, 0.025)   # random position size
            if rng.random() < wr:
                # Winner
                gain_pct = self.avg_win_pct * win_mult * rng.uniform(0.5, 2.0)
                capital += capital * position_pct * gain_pct
            else:
                # Loser
                loss_pct = self.avg_loss_pct * loss_mult * rng.uniform(0.5, 2.0)
                capital -= capital * position_pct * loss_pct

            capital -= capital * extra_cost_pct   # friction / spread costs
            capital  = max(0.0, capital)
            if capital > peak:
                peak = capital

        return capital

    # ── Monte Carlo runner ────────────────────────────────────────────────────

    def _run_scenario(
        self,
        name: str,
        scenario_fn: Callable[[random.Random], float],
    ) -> ScenarioResult:
        """Run N Monte Carlo paths for one scenario and aggregate."""
        rng      = random.Random(self.seed)
        finals   = []
        drawdowns = []

        for _ in range(self.num_paths):
            # Each path gets a fresh sub-seed from the master RNG
            sub_rng = random.Random(rng.getrandbits(32))
            final   = scenario_fn(sub_rng)
            finals.append(final)
            dd = max(0.0, (self.initial_capital - final) / self.initial_capital)
            drawdowns.append(dd)

        finals_sorted = sorted(finals)
        pnls = [f - self.initial_capital for f in finals]
        pnls_sorted = sorted(pnls)
        n = len(pnls_sorted)

        # 5th / 95th percentile
        idx5  = max(0, int(0.05 * n) - 1)
        idx95 = min(n - 1, int(0.95 * n))
        pct5  = pnls_sorted[idx5]
        pct95 = pnls_sorted[idx95]

        # VaR / CVaR at 95 %
        var_idx = max(0, int(0.05 * n))
        var_95  = abs(pnls_sorted[var_idx]) if pnls_sorted[var_idx] < 0 else 0.0
        tail    = [p for p in pnls_sorted[:var_idx] if p < 0]
        cvar_95 = abs(statistics.mean(tail)) if tail else 0.0

        survival_count = sum(1 for f in finals if f >= self.initial_capital * 0.80)
        survival_rate  = survival_count / n

        return ScenarioResult(
            scenario_name    = name,
            num_paths        = n,
            mean_pnl         = statistics.mean(pnls),
            median_pnl       = statistics.median(pnls),
            pct_5_pnl        = pct5,
            pct_95_pnl       = pct95,
            mean_max_drawdown= statistics.mean(drawdowns),
            worst_drawdown   = max(drawdowns),
            survival_rate    = survival_rate,
            var_95           = var_95,
            cvar_95          = cvar_95,
            paths_raw        = finals,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Convenience helper
# ─────────────────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
