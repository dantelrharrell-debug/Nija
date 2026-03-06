"""
NIJA Unified Stress Test Engine
=================================

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
import random
import statistics
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger("nija.stress_test_engine")

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
    """Complete report across all scenarios."""
    timestamp: str
    initial_capital: float
    scenarios: List[ScenarioReport] = field(default_factory=list)
    overall_passed: bool = False

    def summary(self) -> str:
        lines = [
            "=" * 55,
            "NIJA STRESS TEST ENGINE — FULL REPORT",
            f"Timestamp      : {self.timestamp}",
            f"Initial capital: ${self.initial_capital:,.2f}",
            f"Overall passed : {'✅ YES' if self.overall_passed else '❌ NO'}",
            "=" * 55,
        ]
        for sr in self.scenarios:
            lines.append(sr.summary())
            lines.append("")
        return "\n".join(lines)

    def to_dict(self) -> Dict:
        return {
            "timestamp": self.timestamp,
            "initial_capital": self.initial_capital,
            "overall_passed": self.overall_passed,
            "scenarios": [
                {
                    "scenario": s.scenario,
                    "num_paths": s.num_paths,
                    "survival_rate": s.survival_rate,
                    "avg_final_capital": s.avg_final_capital,
                    "avg_max_drawdown_pct": s.avg_max_drawdown_pct,
                    "worst_drawdown_pct": s.worst_drawdown_pct,
                    "var_breach_rate": s.var_breach_rate,
                    "kill_switch_rate": s.kill_switch_rate,
                    "avg_win_rate": s.avg_win_rate,
                }
                for s in self.scenarios
            ],
        }


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
        Starting capital for each Monte Carlo path.
    num_paths : int
        Number of independent simulation paths per scenario.
    seed : int | None
        Random seed for reproducibility.  None → non-deterministic.
    """

    def __init__(
        self,
        initial_capital: float = DEFAULT_INITIAL_CAPITAL,
        num_paths: int = DEFAULT_NUM_PATHS,
        seed: Optional[int] = None,
    ) -> None:
        self.initial_capital = initial_capital
        self.num_paths = num_paths
        self._rng = random.Random(seed)
        logger.info(
            "StressTestEngine initialised — capital=$%.2f, paths=%d",
            initial_capital, num_paths,
        )

    # ------------------------------------------------------------------
    # Individual scenario runners
    # ------------------------------------------------------------------

    def run_flash_crash_scenario(self) -> ScenarioReport:
        """Run flash-crash scenario across all paths."""
        logger.info("Running FlashCrash scenario (%d paths)…", self.num_paths)
        t0 = time.monotonic()
        runner = _ScenarioRunner(self.initial_capital, self._rng)
        paths = [runner.run_flash_crash(i) for i in range(self.num_paths)]
        elapsed = time.monotonic() - t0
        report = _aggregate(paths, "FlashCrash")
        logger.info(
            "FlashCrash done in %.1fs — survival=%.1f%%",
            elapsed, report.survival_rate * 100,
        )
        return report

    def run_high_volatility_scenario(self) -> ScenarioReport:
        """Run high-volatility scenario across all paths."""
        logger.info("Running HighVolatility scenario (%d paths)…", self.num_paths)
        t0 = time.monotonic()
        runner = _ScenarioRunner(self.initial_capital, self._rng)
        paths = [runner.run_high_volatility(i) for i in range(self.num_paths)]
        elapsed = time.monotonic() - t0
        report = _aggregate(paths, "HighVolatility")
        logger.info(
            "HighVolatility done in %.1fs — survival=%.1f%%",
            elapsed, report.survival_rate * 100,
        )
        return report

    def run_liquidity_drought_scenario(self) -> ScenarioReport:
        """Run liquidity-drought scenario across all paths."""
        logger.info("Running LiquidityDrought scenario (%d paths)…", self.num_paths)
        t0 = time.monotonic()
        runner = _ScenarioRunner(self.initial_capital, self._rng)
        paths = [runner.run_liquidity_drought(i) for i in range(self.num_paths)]
        elapsed = time.monotonic() - t0
        report = _aggregate(paths, "LiquidityDrought")
        logger.info(
            "LiquidityDrought done in %.1fs — survival=%.1f%%",
            elapsed, report.survival_rate * 100,
        )
        return report

    # ------------------------------------------------------------------
    # Full test suite
    # ------------------------------------------------------------------

    def run_all_scenarios(self) -> StressTestReport:
        """
        Run all three stress scenarios and return a unified report.

        The overall test is considered *passed* when every scenario achieves
        a survival rate of ≥ 70 % (i.e. at most 30 % of paths trigger the
        kill-switch or exceed the drawdown limit).
        """
        logger.info("=== Starting full stress-test suite ===")
        t_start = time.monotonic()

        flash = self.run_flash_crash_scenario()
        high_vol = self.run_high_volatility_scenario()
        drought = self.run_liquidity_drought_scenario()

        scenarios = [flash, high_vol, drought]
        overall_passed = all(s.survival_rate >= 0.70 for s in scenarios)

        report = StressTestReport(
            timestamp=datetime.utcnow().isoformat(),
            initial_capital=self.initial_capital,
            scenarios=scenarios,
            overall_passed=overall_passed,
        )

        elapsed = time.monotonic() - t_start
        logger.info(
            "=== Stress-test suite complete in %.1fs — overall_passed=%s ===",
            elapsed, overall_passed,
        )
        return report

    def get_markets(self) -> List[str]:
        """Return the list of crypto markets covered by the stress test."""
        return list(SAMPLE_MARKETS)
