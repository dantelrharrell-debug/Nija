"""
NIJA Strategy Performance Tracker
===================================

Per-strategy performance tracking with institutional-grade metrics:
- Sharpe Ratio (risk-adjusted returns)
- Profit Factor (gross wins / gross losses)
- Maximum Drawdown (peak-to-trough)
- Win Rate, Expectancy, Calmar Ratio
- Rolling performance windows (7d, 30d, 90d)
- Strategy comparison and ranking

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

import json
import logging
import math
from collections import defaultdict
from dataclasses import dataclass, asdict, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("nija.strategy_performance")

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class StrategyTrade:
    """Single trade result attributed to a strategy."""
    trade_id: str
    strategy: str
    symbol: str
    pnl: float          # net P&L after fees
    fees: float
    entry_ts: datetime
    exit_ts: datetime
    side: str           # 'long' | 'short'
    market_regime: str

    @property
    def gross_pnl(self) -> float:
        return self.pnl + self.fees

    @property
    def holding_hours(self) -> float:
        return (self.exit_ts - self.entry_ts).total_seconds() / 3600.0


@dataclass
class StrategyMetrics:
    """Comprehensive metrics for a single strategy."""
    strategy: str
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    total_pnl: float = 0.0
    total_fees: float = 0.0
    profit_factor: float = 0.0
    expectancy: float = 0.0          # avg $ per trade
    avg_win: float = 0.0
    avg_loss: float = 0.0
    max_drawdown: float = 0.0        # as $ amount
    max_drawdown_pct: float = 0.0    # as % of peak equity
    sharpe_ratio: float = 0.0
    calmar_ratio: float = 0.0        # annualised return / max drawdown
    avg_holding_hours: float = 0.0
    best_trade: float = 0.0
    worst_trade: float = 0.0
    consecutive_wins: int = 0        # current streak
    consecutive_losses: int = 0      # current streak
    max_consecutive_wins: int = 0
    max_consecutive_losses: int = 0
    last_updated: str = ""

    @property
    def risk_reward(self) -> float:
        if self.avg_loss != 0:
            return abs(self.avg_win / self.avg_loss)
        return 0.0


# ---------------------------------------------------------------------------
# Core tracker
# ---------------------------------------------------------------------------

class StrategyPerformanceTracker:
    """
    Tracks and evaluates per-strategy performance with institutional-grade metrics.

    Usage:
        tracker = StrategyPerformanceTracker()
        tracker.record_trade(trade)
        metrics = tracker.get_metrics("apex_v71")
        report = tracker.generate_report()
    """

    DATA_DIR = Path(__file__).parent.parent / "data"
    STATE_FILE = DATA_DIR / "strategy_performance_state.json"
    ANNUALISATION_FACTOR = math.sqrt(252)  # trading days, used for Sharpe scaling

    def __init__(self):
        self._trades: Dict[str, List[StrategyTrade]] = defaultdict(list)
        self.DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._load_state()
        logger.info(
            "📊 Strategy Performance Tracker initialized — %d strategies tracked",
            len(self._trades),
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_trade(self, trade: StrategyTrade) -> None:
        """
        Record a completed trade for a strategy.

        Args:
            trade: Completed StrategyTrade instance.
        """
        self._trades[trade.strategy].append(trade)
        self._save_state()
        logger.debug(
            "📥 Trade %s recorded for strategy %s | pnl=%.2f",
            trade.trade_id, trade.strategy, trade.pnl,
        )

    def get_metrics(self, strategy: str, window_days: Optional[int] = None) -> StrategyMetrics:
        """
        Calculate comprehensive metrics for a strategy.

        Args:
            strategy: Strategy name.
            window_days: If provided, only consider trades from the last N days.

        Returns:
            StrategyMetrics dataclass.
        """
        trades = self._trades.get(strategy, [])

        if window_days is not None:
            cutoff = datetime.now() - timedelta(days=window_days)
            trades = [t for t in trades if t.exit_ts >= cutoff]

        return self._calculate_metrics(strategy, trades)

    def get_all_metrics(self, window_days: Optional[int] = None) -> Dict[str, StrategyMetrics]:
        """
        Get metrics for all tracked strategies.

        Args:
            window_days: Optional rolling window in days.

        Returns:
            Mapping of strategy_name → StrategyMetrics.
        """
        return {s: self.get_metrics(s, window_days) for s in self._trades}

    def rank_strategies(self, by: str = "sharpe_ratio", window_days: Optional[int] = None) -> List[Tuple[str, float]]:
        """
        Rank strategies by a specified metric.

        Args:
            by: Metric attribute name to sort by (e.g. 'sharpe_ratio', 'profit_factor').
            window_days: Optional rolling window.

        Returns:
            Sorted list of (strategy_name, metric_value), best first.
        """
        all_metrics = self.get_all_metrics(window_days)
        ranked = []
        for name, m in all_metrics.items():
            value = getattr(m, by, 0.0)
            ranked.append((name, float(value)))
        ranked.sort(key=lambda x: x[1], reverse=True)
        return ranked

    def generate_report(self, window_days: Optional[int] = None) -> str:
        """
        Generate a formatted text report for all strategies.

        Args:
            window_days: Optional rolling window (default: all-time).

        Returns:
            Formatted report string.
        """
        label = f"Last {window_days} Days" if window_days else "All-Time"
        all_metrics = self.get_all_metrics(window_days)
        ranked = self.rank_strategies("sharpe_ratio", window_days)

        lines = [
            "",
            "=" * 90,
            f"📊  NIJA STRATEGY PERFORMANCE REPORT ({label})",
            "=" * 90,
        ]

        if not ranked:
            lines.append("  No strategy data available.")
            lines.append("=" * 90)
            return "\n".join(lines)

        col_w = 16
        hdr = (
            f"{'Strategy':<20} {'Trades':>7} {'Win%':>7} "
            f"{'PnL':>10} {'PF':>6} {'Sharpe':>8} "
            f"{'MaxDD':>10} {'Expect':>10}"
        )
        lines.append(hdr)
        lines.append("-" * 90)

        for strategy, _ in ranked:
            m = all_metrics.get(strategy)
            if not m:
                continue
            pf_str = f"{m.profit_factor:.2f}" if m.profit_factor != float("inf") else "∞"
            dd_str = f"${m.max_drawdown:.2f}"
            lines.append(
                f"{m.strategy:<20} {m.total_trades:>7} {m.win_rate*100:>6.1f}% "
                f"${m.total_pnl:>9.2f} {pf_str:>6} {m.sharpe_ratio:>8.3f} "
                f"{dd_str:>10} ${m.expectancy:>9.2f}"
            )

        lines.append("=" * 90)

        # Detailed section for each strategy
        for strategy, _ in ranked:
            m = all_metrics[strategy]
            lines.extend([
                "",
                f"  ▶  {m.strategy.upper()}",
                f"     Trades:        {m.total_trades}  ({m.wins}W / {m.losses}L)",
                f"     Win Rate:      {m.win_rate * 100:.1f}%",
                f"     Profit Factor: {m.profit_factor:.2f}",
                f"     Sharpe Ratio:  {m.sharpe_ratio:.3f}",
                f"     Calmar Ratio:  {m.calmar_ratio:.3f}",
                f"     Total PnL:     ${m.total_pnl:.2f}",
                f"     Expectancy:    ${m.expectancy:.2f}/trade",
                f"     Avg Win:       ${m.avg_win:.2f}",
                f"     Avg Loss:      ${m.avg_loss:.2f}",
                f"     Risk/Reward:   {m.risk_reward:.2f}",
                f"     Max Drawdown:  ${m.max_drawdown:.2f} ({m.max_drawdown_pct:.1f}%)",
                f"     Best Trade:    ${m.best_trade:.2f}",
                f"     Worst Trade:   ${m.worst_trade:.2f}",
                f"     Avg Hold:      {m.avg_holding_hours:.1f} hours",
                f"     Consec Wins:   {m.consecutive_wins} (max {m.max_consecutive_wins})",
                f"     Consec Loss:   {m.consecutive_losses} (max {m.max_consecutive_losses})",
            ])

        lines.append("")
        lines.append("=" * 90)
        return "\n".join(lines)

    def get_rolling_windows(self, strategy: str) -> Dict[str, StrategyMetrics]:
        """
        Get metrics across multiple rolling windows.

        Args:
            strategy: Strategy name.

        Returns:
            Dict with keys '7d', '30d', '90d', 'all' → StrategyMetrics.
        """
        return {
            "7d": self.get_metrics(strategy, 7),
            "30d": self.get_metrics(strategy, 30),
            "90d": self.get_metrics(strategy, 90),
            "all": self.get_metrics(strategy),
        }

    # ------------------------------------------------------------------
    # Calculation internals
    # ------------------------------------------------------------------

    def _calculate_metrics(self, strategy: str, trades: List[StrategyTrade]) -> StrategyMetrics:
        m = StrategyMetrics(strategy=strategy)

        if not trades:
            m.last_updated = datetime.now().isoformat()
            return m

        m.total_trades = len(trades)
        pnl_series = [t.pnl for t in trades]
        m.total_pnl = sum(pnl_series)
        m.total_fees = sum(t.fees for t in trades)

        win_pnls = [p for p in pnl_series if p > 0]
        loss_pnls = [p for p in pnl_series if p <= 0]

        m.wins = len(win_pnls)
        m.losses = len(loss_pnls)
        m.win_rate = m.wins / m.total_trades if m.total_trades else 0.0

        m.gross_profit = sum(win_pnls)
        m.gross_loss = sum(abs(p) for p in loss_pnls)

        m.profit_factor = (m.gross_profit / m.gross_loss) if m.gross_loss > 0 else float("inf")
        m.expectancy = m.total_pnl / m.total_trades if m.total_trades else 0.0

        m.avg_win = m.gross_profit / m.wins if m.wins else 0.0
        m.avg_loss = -(m.gross_loss / m.losses) if m.losses else 0.0

        m.best_trade = max(pnl_series)
        m.worst_trade = min(pnl_series)

        hold_hours = [t.holding_hours for t in trades]
        m.avg_holding_hours = sum(hold_hours) / len(hold_hours) if hold_hours else 0.0

        # Max drawdown (running equity curve)
        m.max_drawdown, m.max_drawdown_pct = self._calculate_max_drawdown(pnl_series)

        # Sharpe Ratio
        m.sharpe_ratio = self._calculate_sharpe(pnl_series)

        # Calmar Ratio: annualised return / max drawdown
        if m.max_drawdown > 0 and len(trades) > 0:
            days = max(1, (trades[-1].exit_ts - trades[0].entry_ts).days)
            annualised_return = m.total_pnl * (365.0 / days)
            m.calmar_ratio = annualised_return / m.max_drawdown
        else:
            m.calmar_ratio = 0.0

        # Consecutive wins/losses
        m.consecutive_wins, m.consecutive_losses, m.max_consecutive_wins, m.max_consecutive_losses = (
            self._calculate_streaks(pnl_series)
        )

        m.last_updated = datetime.now().isoformat()
        return m

    @staticmethod
    def _calculate_max_drawdown(pnl_series: List[float]) -> Tuple[float, float]:
        """Calculate max drawdown in $ and as % of peak equity."""
        if not pnl_series:
            return 0.0, 0.0

        equity = 0.0
        peak = 0.0
        max_dd = 0.0
        max_dd_pct = 0.0

        for pnl in pnl_series:
            equity += pnl
            if equity > peak:
                peak = equity
            drawdown = peak - equity
            if drawdown > max_dd:
                max_dd = drawdown
                max_dd_pct = (drawdown / peak * 100.0) if peak > 0 else 0.0

        return round(max_dd, 4), round(max_dd_pct, 4)

    @staticmethod
    def _calculate_sharpe(pnl_series: List[float], risk_free_rate: float = 0.0) -> float:
        """
        Calculate daily Sharpe ratio from per-trade P&L series.

        Args:
            pnl_series: List of per-trade net P&L values.
            risk_free_rate: Daily risk-free rate (default: 0).

        Returns:
            Annualised Sharpe ratio.
        """
        if len(pnl_series) < 2:
            return 0.0

        n = len(pnl_series)
        mean = sum(pnl_series) / n
        variance = sum((x - mean) ** 2 for x in pnl_series) / (n - 1)
        std = math.sqrt(variance)

        if std == 0:
            return 0.0

        # Per-trade Sharpe, annualised with square root of 252 trading days
        return round(((mean - risk_free_rate) / std) * math.sqrt(252), 4)

    @staticmethod
    def _calculate_streaks(pnl_series: List[float]) -> Tuple[int, int, int, int]:
        """Return (current_wins, current_losses, max_wins, max_losses)."""
        cur_wins = cur_losses = max_wins = max_losses = 0

        for pnl in pnl_series:
            if pnl > 0:
                cur_wins += 1
                cur_losses = 0
            else:
                cur_losses += 1
                cur_wins = 0
            max_wins = max(max_wins, cur_wins)
            max_losses = max(max_losses, cur_losses)

        return cur_wins, cur_losses, max_wins, max_losses

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load_state(self) -> None:
        if not self.STATE_FILE.exists():
            return
        try:
            with open(self.STATE_FILE, "r") as f:
                data = json.load(f)
            for strategy, trade_list in data.get("trades", {}).items():
                for item in trade_list:
                    try:
                        trade = StrategyTrade(
                            trade_id=item["trade_id"],
                            strategy=item["strategy"],
                            symbol=item["symbol"],
                            pnl=item["pnl"],
                            fees=item["fees"],
                            entry_ts=datetime.fromisoformat(item["entry_ts"]),
                            exit_ts=datetime.fromisoformat(item["exit_ts"]),
                            side=item["side"],
                            market_regime=item["market_regime"],
                        )
                        self._trades[strategy].append(trade)
                    except (KeyError, ValueError) as exc:
                        logger.warning("Skipping malformed strategy trade: %s", exc)
            logger.info("✅ Loaded strategy performance state — %d strategies", len(self._trades))
        except Exception as exc:
            logger.warning("Could not load strategy performance state: %s", exc)

    def _save_state(self) -> None:
        try:
            serialized: Dict[str, List[Dict]] = {}
            for strategy, trades in self._trades.items():
                serialized[strategy] = [
                    {
                        "trade_id": t.trade_id,
                        "strategy": t.strategy,
                        "symbol": t.symbol,
                        "pnl": t.pnl,
                        "fees": t.fees,
                        "entry_ts": t.entry_ts.isoformat(),
                        "exit_ts": t.exit_ts.isoformat(),
                        "side": t.side,
                        "market_regime": t.market_regime,
                    }
                    for t in trades
                ]
            with open(self.STATE_FILE, "w") as f:
                json.dump({"trades": serialized, "updated_at": datetime.now().isoformat()}, f, indent=2)
        except Exception as exc:
            logger.error("Failed to save strategy performance state: %s", exc)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_tracker: Optional[StrategyPerformanceTracker] = None


def get_strategy_performance_tracker() -> StrategyPerformanceTracker:
    """Return the module-level singleton StrategyPerformanceTracker."""
    global _tracker
    if _tracker is None:
        _tracker = StrategyPerformanceTracker()
    return _tracker


if __name__ == "__main__":
    import random

    logging.basicConfig(level=logging.INFO, format="%(levelname)s - %(message)s")

    tracker = get_strategy_performance_tracker()
    strategies = ["apex_v71", "rsi_dual", "momentum"]
    now = datetime.now()

    for i in range(60):
        strat = random.choice(strategies)
        pnl = random.gauss(3 if strat == "apex_v71" else 0, 20)
        t = StrategyTrade(
            trade_id=f"SIM-{i:04d}",
            strategy=strat,
            symbol="BTC-USD",
            pnl=pnl,
            fees=0.5,
            entry_ts=now - timedelta(hours=i * 3),
            exit_ts=now - timedelta(hours=i * 3 - 2),
            side="long",
            market_regime=random.choice(["trending", "ranging", "volatile"]),
        )
        tracker.record_trade(t)

    print(tracker.generate_report())
    print("\nRanking by Sharpe:", tracker.rank_strategies("sharpe_ratio"))
