"""
Stress Test Engine
===================

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
            "run_at":            self.run_at,
            "scenarios":         [r.to_dict() for r in self.scenario_results],
        }

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


# ─────────────────────────────────────────────────────────────────────────────
# Core engine
# ─────────────────────────────────────────────────────────────────────────────

class StressTestEngine:
    """
    Monte Carlo stress test engine.

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
        """Run every built-in scenario and return a combined report."""
        report = StressTestReport(
            initial_capital=self.initial_capital,
            num_paths=self.num_paths,
            seed=self.seed,
            run_at=_now(),
        )
        scenarios: List[Tuple[str, Callable[[random.Random], float]]] = [
            ("Flash Crash",       self._scenario_flash_crash),
            ("High Volatility",   self._scenario_high_volatility),
            ("Liquidity Drought", self._scenario_liquidity_drought),
            ("Trending Crisis",   self._scenario_trending_crisis),
            ("Regime Whipsaw",    self._scenario_regime_whipsaw),
        ]
        for name, scenario_fn in scenarios:
            result = self._run_scenario(name, scenario_fn)
            report.scenario_results.append(result)
            logger.info(
                "[StressTest] %-22s survival=%.1f%%  VaR=$%.0f",
                name, result.survival_rate * 100, result.var_95,
            )
        return report

    def run_scenario(self, name: str, scenario_fn: Callable[[random.Random], float]) -> ScenarioResult:
        """Run a single custom scenario function and return its results."""
        return self._run_scenario(name, scenario_fn)

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
            sub_rng = random.Random(rng.randint(0, 2**31))
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
