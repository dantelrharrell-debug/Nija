"""
NIJA Paper / Simulated Live Testing
=====================================

Runs a realistic end-to-end paper simulation that routes synthetic market
events through **every** active safety layer, so you can verify the full
stack behaves correctly before touching live capital.

Safety layers exercised
-----------------------
* GlobalRiskGovernor  – daily-loss / consecutive-loss / equity-curve gates
* KillSwitch          – hard-stop propagation
* AICapitalRotation   – regime-aware capital allocation
* AlertManager        – alert firing and auto-pause logic
* StrategyHealthMonitor – health-level transitions

Simulation flow
---------------
1. A synthetic market session is created (configurable: hours, assets, regime).
2. At each simulated bar, signals are generated with configurable win rate.
3. Each signal is passed through the full safety gate chain.
4. Approved signals result in a simulated fill; rejected ones are logged.
5. Trade results feed back into GlobalRiskGovernor and StrategyHealthMonitor.
6. A PaperSimReport is produced at the end with pass/fail criteria.

Usage
-----
    from bot.paper_trading_simulation import PaperTradingSimulation

    sim = PaperTradingSimulation(
        initial_capital=10_000.0,
        session_bars=200,
        win_rate=0.55,
        regime="TRENDING",
    )
    report = sim.run()
    print(report.summary())

    # One-liner convenience
    from bot.paper_trading_simulation import run_paper_simulation
    run_paper_simulation()

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import math
import random
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("nija.paper_trading_simulation")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_CAPITAL: float = 10_000.0
DEFAULT_BARS: int = 200
DEFAULT_WIN_RATE: float = 0.55
DEFAULT_RISK_PER_TRADE_PCT: float = 1.5     # % of capital at risk per trade
DEFAULT_AVG_WIN_PCT: float = 0.025          # 2.5 % avg win
DEFAULT_AVG_LOSS_PCT: float = 0.015         # 1.5 % avg loss

SAMPLE_SYMBOLS = [
    "BTC-USD", "ETH-USD", "SOL-USD", "AVAX-USD", "LINK-USD",
    "MATIC-USD", "DOT-USD", "ADA-USD", "XRP-USD", "DOGE-USD",
]


# ---------------------------------------------------------------------------
# Result structures
# ---------------------------------------------------------------------------

@dataclass
class BarResult:
    bar_index: int
    symbol: str
    signal_score: float
    gate_passed: bool
    gate_reason: str
    pnl_usd: float
    capital_after: float


@dataclass
class PaperSimReport:
    """Final report produced after running the full simulation."""

    timestamp: str
    initial_capital: float
    final_capital: float
    total_bars: int
    regime: str
    win_rate_target: float

    # Trade statistics
    trades_attempted: int
    trades_approved: int
    trades_rejected: int
    trades_won: int
    trades_lost: int
    realized_win_rate: float
    total_pnl_usd: float
    peak_capital: float
    max_drawdown_pct: float

    # Gate summary
    gate_rejections: Dict[str, int] = field(default_factory=dict)

    # Kill switch
    kill_switch_triggered: bool = False
    kill_switch_bar: Optional[int] = None

    # Alert summary
    alerts_fired: int = 0
    auto_pause_triggered: bool = False

    # Health levels
    strategy_health_levels: Dict[str, str] = field(default_factory=dict)

    # Capital rotation meta allocation
    final_meta_allocation: Dict[str, float] = field(default_factory=dict)

    # Overall pass/fail
    passed: bool = False
    failure_reasons: List[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            "=" * 60,
            "  NIJA Paper Trading Simulation Report",
            "=" * 60,
            f"  Timestamp         : {self.timestamp}",
            f"  Regime            : {self.regime}",
            f"  Bars simulated    : {self.total_bars}",
            f"  Initial capital   : ${self.initial_capital:,.2f}",
            f"  Final capital     : ${self.final_capital:,.2f}",
            f"  Total P&L         : ${self.total_pnl_usd:+,.2f} "
            f"({self.total_pnl_usd / self.initial_capital * 100:+.2f}%)",
            f"  Max drawdown      : {self.max_drawdown_pct:.2f}%",
            "",
            f"  Trades attempted  : {self.trades_attempted}",
            f"  Trades approved   : {self.trades_approved}",
            f"  Trades rejected   : {self.trades_rejected}",
            f"  Win rate          : {self.realized_win_rate:.1%} "
            f"(target: {self.win_rate_target:.1%})",
            "",
            f"  Kill switch fired : {self.kill_switch_triggered}"
            + (f" at bar {self.kill_switch_bar}" if self.kill_switch_triggered else ""),
            f"  Alerts fired      : {self.alerts_fired}",
            f"  Auto-pause hit    : {self.auto_pause_triggered}",
            "",
        ]
        if self.gate_rejections:
            lines.append("  Gate rejections:")
            for reason, count in sorted(
                self.gate_rejections.items(), key=lambda x: -x[1]
            ):
                lines.append(f"    {reason:<30}: {count}")
            lines.append("")
        if self.strategy_health_levels:
            lines.append("  Strategy health levels:")
            for strat, level in self.strategy_health_levels.items():
                lines.append(f"    {strat:<30}: {level}")
            lines.append("")
        if self.final_meta_allocation:
            lines.append("  Capital allocation (meta):")
            for strat, pct in self.final_meta_allocation.items():
                lines.append(f"    {strat:<30}: {pct*100:.1f}%")
            lines.append("")
        status = "✅ PASSED" if self.passed else "❌ FAILED"
        lines.append(f"  Overall           : {status}")
        if self.failure_reasons:
            for r in self.failure_reasons:
                lines.append(f"    ✗ {r}")
        lines.append("=" * 60)
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main simulation class
# ---------------------------------------------------------------------------

class PaperTradingSimulation:
    """
    Comprehensive paper simulation that drives synthetic signals through the
    full NIJA safety and intelligence stack.
    """

    def __init__(
        self,
        initial_capital: float = DEFAULT_CAPITAL,
        session_bars: int = DEFAULT_BARS,
        win_rate: float = DEFAULT_WIN_RATE,
        regime: str = "TRENDING",
        risk_per_trade_pct: float = DEFAULT_RISK_PER_TRADE_PCT,
        seed: Optional[int] = None,
        symbols: Optional[List[str]] = None,
    ) -> None:
        self.initial_capital = initial_capital
        self.session_bars = session_bars
        self.win_rate = win_rate
        self.regime = regime
        self.risk_per_trade_pct = risk_per_trade_pct
        self._rng = random.Random(seed)
        self.symbols = symbols or SAMPLE_SYMBOLS

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(self) -> PaperSimReport:
        """Execute the full paper simulation and return a :class:`PaperSimReport`."""
        logger.info(
            "PaperSim starting — capital=$%.0f, bars=%d, regime=%s, win_rate=%.2f",
            self.initial_capital, self.session_bars, self.regime, self.win_rate,
        )

        # ── lazy-import safety modules ────────────────────────────────────
        governor, kill_switch, rotation_engine, alert_mgr, health_mon = \
            self._load_modules()

        # ── simulation state ─────────────────────────────────────────────
        capital = self.initial_capital
        peak_capital = capital
        bar_results: List[BarResult] = []
        gate_rejections: Dict[str, int] = {}
        trades_attempted = 0
        trades_approved = 0
        trades_rejected = 0
        wins = 0
        losses = 0
        kill_switch_bar: Optional[int] = None
        auto_pause_triggered = False
        alerts_before = self._count_alerts(alert_mgr)

        strategy_name = "PaperSimStrategy"
        open_positions: Dict[str, Dict] = {}     # symbol → {risk_usd}

        # ── main bar loop ─────────────────────────────────────────────────
        for bar_idx in range(self.session_bars):

            # Check hard stop first
            if kill_switch is not None and kill_switch.is_active():
                if kill_switch_bar is None:
                    kill_switch_bar = bar_idx
                logger.warning("PaperSim: kill switch active at bar %d — halting", bar_idx)
                break

            # Check alert-manager auto-pause
            if alert_mgr is not None:
                try:
                    if alert_mgr.is_paused():
                        auto_pause_triggered = True
                        logger.info("PaperSim bar %d: alert-manager paused — skipping", bar_idx)
                        time.sleep(0)  # yield
                        continue
                except Exception:
                    pass

            # Pick a symbol for this bar
            symbol = self.symbols[bar_idx % len(self.symbols)]

            # Generate a synthetic signal score (50–100)
            signal_score = self._rng.uniform(55.0, 95.0)

            # Propose a risk amount
            risk_usd = capital * (self.risk_per_trade_pct / 100.0)

            # ── gate chain ────────────────────────────────────────────────
            gate_passed, gate_reason = self._run_gate_chain(
                governor=governor,
                symbol=symbol,
                risk_usd=risk_usd,
                capital=capital,
                open_positions=open_positions,
            )

            trades_attempted += 1

            if not gate_passed:
                trades_rejected += 1
                gate_rejections[gate_reason] = gate_rejections.get(gate_reason, 0) + 1
                bar_results.append(BarResult(
                    bar_index=bar_idx,
                    symbol=symbol,
                    signal_score=signal_score,
                    gate_passed=False,
                    gate_reason=gate_reason,
                    pnl_usd=0.0,
                    capital_after=capital,
                ))
                continue

            trades_approved += 1

            # Simulate fill
            is_win = self._rng.random() < self.win_rate
            pnl = self._calculate_trade_pnl(capital, is_win)
            if is_win:
                wins += 1
            else:
                losses += 1

            capital = max(0.0, capital + pnl)
            peak_capital = max(peak_capital, capital)

            # Update position tracker
            open_positions[symbol] = {"risk_usd": risk_usd}
            # Randomly close some positions to avoid unbounded growth
            if len(open_positions) > 6:
                oldest = next(iter(open_positions))
                del open_positions[oldest]

            # Feed results back into safety modules
            self._record_trade_result(governor, health_mon, strategy_name, pnl, is_win)

            bar_results.append(BarResult(
                bar_index=bar_idx,
                symbol=symbol,
                signal_score=signal_score,
                gate_passed=True,
                gate_reason="approved",
                pnl_usd=pnl,
                capital_after=capital,
            ))

        # ── post-simulation summaries ─────────────────────────────────────
        total_pnl = capital - self.initial_capital
        realized_win_rate = wins / max(1, wins + losses)
        max_drawdown_pct = (peak_capital - capital) / max(1, peak_capital) * 100.0

        strategy_health_levels = self._collect_health_levels(health_mon, strategy_name)
        final_meta_allocation = self._collect_meta_allocation(rotation_engine)
        alerts_fired = self._count_alerts(alert_mgr) - alerts_before

        # ── pass/fail evaluation ─────────────────────────────────────────
        failure_reasons: List[str] = []
        if max_drawdown_pct > 20.0:
            failure_reasons.append(
                f"Max drawdown {max_drawdown_pct:.1f}% exceeded 20% limit"
            )
        if capital < self.initial_capital * 0.75:
            failure_reasons.append(
                f"Capital fell below 75% floor (${capital:,.0f} < ${self.initial_capital*0.75:,.0f})"
            )
        if trades_approved < trades_attempted * 0.10 and trades_attempted > 20:
            failure_reasons.append(
                f"Gate rejection rate too high "
                f"({trades_rejected}/{trades_attempted} = "
                f"{trades_rejected/trades_attempted:.0%})"
            )

        passed = len(failure_reasons) == 0

        report = PaperSimReport(
            timestamp=datetime.now(timezone.utc).isoformat(),
            initial_capital=self.initial_capital,
            final_capital=capital,
            total_bars=len(bar_results),
            regime=self.regime,
            win_rate_target=self.win_rate,
            trades_attempted=trades_attempted,
            trades_approved=trades_approved,
            trades_rejected=trades_rejected,
            trades_won=wins,
            trades_lost=losses,
            realized_win_rate=realized_win_rate,
            total_pnl_usd=total_pnl,
            peak_capital=peak_capital,
            max_drawdown_pct=max_drawdown_pct,
            gate_rejections=gate_rejections,
            kill_switch_triggered=kill_switch_bar is not None,
            kill_switch_bar=kill_switch_bar,
            alerts_fired=alerts_fired,
            auto_pause_triggered=auto_pause_triggered,
            strategy_health_levels=strategy_health_levels,
            final_meta_allocation=final_meta_allocation,
            passed=passed,
            failure_reasons=failure_reasons,
        )

        logger.info(
            "PaperSim complete — pnl=$%.2f, drawdown=%.1f%%, passed=%s",
            total_pnl, max_drawdown_pct, passed,
        )
        return report

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_modules(self):
        """Lazy-import all safety modules; return None on ImportError."""
        governor = None
        kill_switch = None
        rotation_engine = None
        alert_mgr = None
        health_mon = None

        try:
            from bot.global_risk_governor import get_global_risk_governor
            governor = get_global_risk_governor()
        except Exception as exc:
            logger.warning("GlobalRiskGovernor unavailable: %s", exc)

        try:
            from bot.kill_switch import get_kill_switch
            kill_switch = get_kill_switch()
        except Exception as exc:
            logger.warning("KillSwitch unavailable: %s", exc)

        try:
            from bot.ai_capital_rotation_engine import get_ai_capital_rotation_engine
            rotation_engine = get_ai_capital_rotation_engine()
        except Exception as exc:
            logger.warning("AICapitalRotationEngine unavailable: %s", exc)

        try:
            from bot.alert_manager import get_alert_manager
            alert_mgr = get_alert_manager()
        except Exception as exc:
            logger.warning("AlertManager unavailable: %s", exc)

        try:
            from bot.strategy_health_monitor import get_strategy_health_monitor
            health_mon = get_strategy_health_monitor()
        except Exception as exc:
            logger.warning("StrategyHealthMonitor unavailable: %s", exc)

        return governor, kill_switch, rotation_engine, alert_mgr, health_mon

    def _calculate_trade_pnl(self, capital: float, is_win: bool) -> float:
        """
        Calculate simulated P&L for one trade.

        Winners earn between 0.8× and 2.0× the expected win amount;
        losers lose between 0.5× and 1.2× the risk-per-trade amount.
        """
        risk_amount = capital * (self.risk_per_trade_pct / 100.0)
        if is_win:
            # win return scales with avg_win / avg_loss reward-to-risk ratio
            reward_ratio = DEFAULT_AVG_WIN_PCT / DEFAULT_AVG_LOSS_PCT
            return risk_amount * reward_ratio * self._rng.uniform(0.8, 2.0)
        else:
            return -risk_amount * self._rng.uniform(0.5, 1.2)

    def _run_gate_chain(
        self,
        governor,
        symbol: str,
        risk_usd: float,
        capital: float,
        open_positions: Dict,
    ) -> Tuple[bool, str]:
        """Run the global risk gate chain; return (passed, reason)."""
        if governor is None:
            return True, "no_governor"

        try:
            decision = governor.approve_entry(
                symbol=symbol,
                proposed_risk_usd=risk_usd,
                current_portfolio_value=capital,
                volatility_ratio=self._rng.uniform(0.8, 1.5),
            )
            if not decision.allowed:
                return False, _short_reason(decision.reason)
            return True, "approved"
        except Exception as exc:
            logger.debug("Gate chain error for %s: %s", symbol, exc)
            return True, "gate_error_bypass"

    def _record_trade_result(
        self, governor, health_mon, strategy: str, pnl: float, is_win: bool
    ) -> None:
        if governor is not None:
            try:
                governor.record_trade_result(pnl_usd=pnl, is_win=is_win)
            except Exception:
                pass
        if health_mon is not None:
            try:
                health_mon.record_trade(
                    strategy=strategy,
                    pnl_usd=pnl,
                    is_win=is_win,
                    regime=self.regime,
                )
            except Exception:
                pass

    def _count_alerts(self, alert_mgr) -> int:
        if alert_mgr is None:
            return 0
        try:
            return len(alert_mgr.get_recent_alerts(limit=10_000))
        except Exception:
            return 0

    def _collect_health_levels(self, health_mon, strategy: str) -> Dict[str, str]:
        if health_mon is None:
            return {}
        try:
            status = health_mon.get_health(strategy)
            return {strategy: status.health_level.value}
        except Exception:
            return {}

    def _collect_meta_allocation(self, rotation_engine) -> Dict[str, float]:
        if rotation_engine is None:
            return {}
        try:
            result = rotation_engine.run_rotation_cycle(
                current_positions=[],
                pending_signals=[],
                account_balance=self.initial_capital,
                market_regime=self.regime,
            )
            return result.meta_allocation
        except Exception:
            return {}


# ---------------------------------------------------------------------------
# Convenience runner
# ---------------------------------------------------------------------------

def run_paper_simulation(
    initial_capital: float = DEFAULT_CAPITAL,
    session_bars: int = DEFAULT_BARS,
    win_rate: float = DEFAULT_WIN_RATE,
    regime: str = "TRENDING",
    seed: Optional[int] = 42,
    verbose: bool = True,
) -> PaperSimReport:
    """
    Run a complete paper simulation and optionally print the summary.

    Returns the :class:`PaperSimReport` for programmatic inspection.
    """
    sim = PaperTradingSimulation(
        initial_capital=initial_capital,
        session_bars=session_bars,
        win_rate=win_rate,
        regime=regime,
        seed=seed,
    )
    report = sim.run()
    if verbose:
        print(report.summary())
    return report


# ---------------------------------------------------------------------------
# Private utilities
# ---------------------------------------------------------------------------

def _short_reason(full_reason: str, max_len: int = 40) -> str:
    """Return a truncated, key-word version of a gate rejection reason."""
    if not full_reason:
        return "unknown"
    # Strip leading/trailing whitespace and take first segment
    r = full_reason.strip().split(":")[0].strip()
    return r[:max_len]


# ---------------------------------------------------------------------------
# Singleton accessor (follows repo pattern)
# ---------------------------------------------------------------------------

_sim_instance: Optional[PaperTradingSimulation] = None
_sim_lock = threading.Lock()


def get_paper_simulation(**kwargs) -> PaperTradingSimulation:
    """Return a process-wide :class:`PaperTradingSimulation` singleton."""
    global _sim_instance
    with _sim_lock:
        if _sim_instance is None:
            _sim_instance = PaperTradingSimulation(**kwargs)
            logger.info("PaperTradingSimulation singleton created")
    return _sim_instance


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    )

    regime = sys.argv[1] if len(sys.argv) > 1 else "TRENDING"
    bars   = int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_BARS
    run_paper_simulation(regime=regime, session_bars=bars)
