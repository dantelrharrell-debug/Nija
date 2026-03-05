"""
NIJA Performance Reporter
===========================

Investor-grade performance reporting that aggregates data across all NIJA
modules and produces structured, exportable reports for:

1. Daily summary — overnight snapshot for operators
2. Weekly digest — 7-day performance overview
3. Monthly investor report — fund-level metrics
4. Quarterly review — strategy attribution and regime breakdown
5. On-demand JSON export — machine-readable for dashboards/APIs

The reporter integrates with:
- trade_intelligence.py    (trade pattern insights)
- strategy_performance.py  (per-strategy metrics)
- regime_intelligence.py   (regime history and performance)
- compounding_engine.py    (capital growth and milestones)

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

import json
import logging
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nija.performance_reporter")

# ---------------------------------------------------------------------------
# Report data structures
# ---------------------------------------------------------------------------

@dataclass
class DailySummary:
    """Daily performance snapshot."""
    date: str
    total_trades: int
    wins: int
    losses: int
    win_rate: float
    gross_profit: float
    total_fees: float
    net_profit: float
    best_trade: float
    worst_trade: float
    ending_capital: float
    roi_pct: float
    regime_of_day: str
    top_strategy: str
    notes: List[str]


@dataclass
class WeeklyDigest:
    """7-day performance digest."""
    week_start: str
    week_end: str
    total_trades: int
    win_rate: float
    net_profit: float
    roi_pct: float
    sharpe_ratio: float
    max_drawdown: float
    best_day_profit: float
    worst_day_profit: float
    dominant_regime: str
    strategy_ranking: List[str]
    capital_start: float
    capital_end: float
    milestones_hit: List[str]
    key_insights: List[str]


@dataclass
class MonthlyReport:
    """Monthly investor-grade report."""
    month: str                      # e.g. "2026-03"
    total_trades: int
    win_rate: float
    gross_profit: float
    total_fees: float
    net_profit: float
    roi_pct: float
    cagr_pct: float
    sharpe_ratio: float
    calmar_ratio: float
    max_drawdown: float
    profit_factor: float
    capital_start: float
    capital_end: float
    best_strategy: str
    worst_strategy: str
    dominant_regime: str
    regime_breakdown: Dict[str, float]      # regime → win_rate
    strategy_breakdown: Dict[str, float]    # strategy → net_pnl
    milestones: List[str]
    projections: Dict[str, float]           # "30d" → projected_capital
    risk_notes: List[str]
    disclaimer: str


@dataclass
class QuarterlyReview:
    """Quarterly strategy attribution review."""
    quarter: str                        # e.g. "Q1-2026"
    total_trades: int
    net_profit: float
    roi_pct: float
    cagr_pct: float
    sharpe_ratio: float
    best_month: str
    worst_month: str
    strategy_attribution: Dict[str, Dict[str, float]]  # strategy → metrics
    regime_attribution: Dict[str, Dict[str, float]]    # regime → metrics
    milestones: List[str]
    insights: List[str]
    forward_outlook: str


# ---------------------------------------------------------------------------
# Core reporter
# ---------------------------------------------------------------------------

class PerformanceReporter:
    """
    Generates investor-grade performance reports by aggregating data from
    all NIJA intelligence modules.

    Usage:
        reporter = PerformanceReporter()
        reporter.record_trade(trade_data)
        daily = reporter.generate_daily_summary()
        print(reporter.format_daily_summary(daily))
        reporter.export_json("reports/daily_2026-03-05.json", asdict(daily))
    """

    REPORT_DIR = Path(__file__).parent.parent / "reports"
    DATA_DIR = Path(__file__).parent.parent / "data"
    STATE_FILE = DATA_DIR / "performance_reporter_state.json"

    DISCLAIMER = (
        "RISK DISCLOSURE: Past performance is not indicative of future results. "
        "Cryptocurrency trading involves substantial risk of loss. "
        "All figures are estimates based on backtested and live data. "
        "This report is for informational purposes only."
    )

    def __init__(self):
        self._daily_records: List[Dict[str, Any]] = []  # per-trade records for period aggregation
        self.REPORT_DIR.mkdir(parents=True, exist_ok=True)
        self.DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._load_state()
        logger.info("📋 Performance Reporter initialized with %d historical records", len(self._daily_records))

    # ------------------------------------------------------------------
    # Trade recording
    # ------------------------------------------------------------------

    def record_trade(
        self,
        trade_id: str,
        strategy: str,
        symbol: str,
        side: str,
        pnl: float,
        fees: float,
        market_regime: str,
        entry_ts: datetime,
        exit_ts: datetime,
        entry_score: int = 0,
    ) -> None:
        """
        Record a completed trade for reporting purposes.

        Args:
            trade_id: Unique trade identifier.
            strategy: Strategy that generated the trade.
            symbol: Trading symbol (e.g. 'BTC-USD').
            side: 'long' or 'short'.
            pnl: Net P&L after fees.
            fees: Fees paid.
            market_regime: Regime label at entry.
            entry_ts: Entry timestamp.
            exit_ts: Exit timestamp.
            entry_score: Entry quality score (0-5).
        """
        record = {
            "trade_id": trade_id,
            "strategy": strategy,
            "symbol": symbol,
            "side": side,
            "pnl": pnl,
            "fees": fees,
            "market_regime": market_regime,
            "entry_ts": entry_ts.isoformat(),
            "exit_ts": exit_ts.isoformat(),
            "date": exit_ts.date().isoformat(),
            "entry_score": entry_score,
            "is_win": pnl > 0,
        }
        self._daily_records.append(record)

        # Keep at most 10,000 records
        if len(self._daily_records) > 10_000:
            self._daily_records = self._daily_records[-10_000:]

        self._save_state()

    # ------------------------------------------------------------------
    # Report generators
    # ------------------------------------------------------------------

    def generate_daily_summary(
        self,
        date: Optional[datetime] = None,
        capital: float = 0.0,
        regime: str = "unknown",
        compounding_engine: Optional[Any] = None,
        strategy_tracker: Optional[Any] = None,
    ) -> DailySummary:
        """
        Generate a daily performance summary.

        Args:
            date: Date to summarise (default: today).
            capital: Current total capital (optional).
            regime: Dominant regime for the day (optional).
            compounding_engine: Optional CompoundingEngine for capital data.
            strategy_tracker: Optional StrategyPerformanceTracker for top strategy.

        Returns:
            DailySummary dataclass.
        """
        target_date = (date or datetime.now()).date()
        day_records = [r for r in self._daily_records if r["date"] == target_date.isoformat()]

        wins = [r for r in day_records if r["is_win"]]
        losses = [r for r in day_records if not r["is_win"]]
        pnls = [r["pnl"] for r in day_records]
        fees = sum(r["fees"] for r in day_records)
        net_profit = sum(pnls)
        gross_profit = net_profit + fees

        ending_capital = capital
        if compounding_engine:
            try:
                ending_capital = compounding_engine.get_state().total_capital
            except Exception:
                pass

        top_strategy = "N/A"
        if strategy_tracker:
            try:
                ranked = strategy_tracker.rank_strategies("total_pnl", window_days=1)
                top_strategy = ranked[0][0] if ranked else "N/A"
            except Exception:
                pass

        notes = self._build_daily_notes(day_records, net_profit, wins, losses)

        return DailySummary(
            date=target_date.isoformat(),
            total_trades=len(day_records),
            wins=len(wins),
            losses=len(losses),
            win_rate=len(wins) / len(day_records) if day_records else 0.0,
            gross_profit=round(gross_profit, 2),
            total_fees=round(fees, 2),
            net_profit=round(net_profit, 2),
            best_trade=round(max(pnls), 2) if pnls else 0.0,
            worst_trade=round(min(pnls), 2) if pnls else 0.0,
            ending_capital=round(ending_capital, 2),
            roi_pct=0.0,  # calculated externally
            regime_of_day=regime,
            top_strategy=top_strategy,
            notes=notes,
        )

    def generate_weekly_digest(
        self,
        end_date: Optional[datetime] = None,
        compounding_engine: Optional[Any] = None,
        strategy_tracker: Optional[Any] = None,
        intelligence_engine: Optional[Any] = None,
    ) -> WeeklyDigest:
        """
        Generate a 7-day performance digest.

        Args:
            end_date: End date of the week (default: today).
            compounding_engine: Optional CompoundingEngine for capital data.
            strategy_tracker: Optional StrategyPerformanceTracker for rankings.
            intelligence_engine: Optional TradeIntelligenceEngine for insights.

        Returns:
            WeeklyDigest dataclass.
        """
        end = (end_date or datetime.now()).date()
        start = end - timedelta(days=6)

        week_records = [
            r for r in self._daily_records
            if start.isoformat() <= r["date"] <= end.isoformat()
        ]

        pnls = [r["pnl"] for r in week_records]
        wins = [r for r in week_records if r["is_win"]]
        fees = sum(r["fees"] for r in week_records)
        net_profit = sum(pnls)

        sharpe = self._calculate_sharpe(pnls)
        max_dd, _ = self._calculate_max_drawdown(pnls)

        # Day-level aggregation for best/worst day
        day_pnls: Dict[str, float] = {}
        for r in week_records:
            day_pnls[r["date"]] = day_pnls.get(r["date"], 0.0) + r["pnl"]
        best_day = round(max(day_pnls.values()), 2) if day_pnls else 0.0
        worst_day = round(min(day_pnls.values()), 2) if day_pnls else 0.0

        # Dominant regime
        regimes = [r["market_regime"] for r in week_records]
        dominant_regime = max(set(regimes), key=regimes.count) if regimes else "unknown"

        # Strategy ranking
        strat_pnl: Dict[str, float] = {}
        for r in week_records:
            strat_pnl[r["strategy"]] = strat_pnl.get(r["strategy"], 0.0) + r["pnl"]
        strategy_ranking = [k for k, _ in sorted(strat_pnl.items(), key=lambda x: x[1], reverse=True)]

        # Capital
        capital_start = 0.0
        capital_end = 0.0
        milestones_hit: List[str] = []
        if compounding_engine:
            try:
                state = compounding_engine.get_state()
                capital_end = state.total_capital
                capital_start = capital_end - net_profit
                milestones_hit = [f"${m:,.0f}" for m in state.milestones_hit[-5:]]
            except Exception:
                pass

        # Insights from intelligence engine
        insights: List[str] = []
        if intelligence_engine:
            try:
                report = intelligence_engine.generate_report()
                insights = report.top_insights[:5]
            except Exception:
                pass

        return WeeklyDigest(
            week_start=start.isoformat(),
            week_end=end.isoformat(),
            total_trades=len(week_records),
            win_rate=round(len(wins) / len(week_records), 4) if week_records else 0.0,
            net_profit=round(net_profit, 2),
            roi_pct=round((net_profit / max(1.0, capital_start)) * 100, 2) if capital_start else 0.0,
            sharpe_ratio=round(sharpe, 4),
            max_drawdown=round(max_dd, 2),
            best_day_profit=best_day,
            worst_day_profit=worst_day,
            dominant_regime=dominant_regime,
            strategy_ranking=strategy_ranking,
            capital_start=round(capital_start, 2),
            capital_end=round(capital_end, 2),
            milestones_hit=milestones_hit,
            key_insights=insights,
        )

    def generate_monthly_report(
        self,
        year: int,
        month: int,
        compounding_engine: Optional[Any] = None,
        strategy_tracker: Optional[Any] = None,
        intelligence_engine: Optional[Any] = None,
        regime_engine: Optional[Any] = None,
    ) -> MonthlyReport:
        """
        Generate a comprehensive monthly investor report.

        Args:
            year: Report year (e.g. 2026).
            month: Report month (1-12).
            compounding_engine: Optional CompoundingEngine.
            strategy_tracker: Optional StrategyPerformanceTracker.
            intelligence_engine: Optional TradeIntelligenceEngine.
            regime_engine: Optional RegimeIntelligenceEngine.

        Returns:
            MonthlyReport dataclass.
        """
        month_prefix = f"{year}-{month:02d}"
        month_records = [r for r in self._daily_records if r["date"].startswith(month_prefix)]

        pnls = [r["pnl"] for r in month_records]
        wins = [r for r in month_records if r["is_win"]]
        fees = sum(r["fees"] for r in month_records)
        gross_profit = sum(p for p in pnls if p > 0) + fees
        net_profit = sum(pnls)

        profit_factor = 0.0
        gross_wins = sum(p for p in pnls if p > 0)
        gross_losses = sum(abs(p) for p in pnls if p < 0)
        if gross_losses > 0:
            profit_factor = round(gross_wins / gross_losses, 4)

        sharpe = self._calculate_sharpe(pnls)
        max_dd, max_dd_pct = self._calculate_max_drawdown(pnls)

        # Capital
        capital_start = capital_end = 0.0
        milestones: List[str] = []
        cagr_pct = 0.0
        projections: Dict[str, float] = {}
        if compounding_engine:
            try:
                state = compounding_engine.get_state()
                capital_end = state.total_capital
                capital_start = capital_end - net_profit
                cagr_pct = compounding_engine._calculate_cagr()
                milestones = [f"${m:,.0f}" for m in state.milestones_hit]
                for proj in compounding_engine.get_projections():
                    projections[f"{proj.days}d"] = proj.projected_capital
            except Exception:
                pass

        # Calmar ratio
        calmar = round((cagr_pct / max_dd_pct) if max_dd_pct > 0 else 0.0, 4)

        # Strategy breakdown
        strat_pnl: Dict[str, float] = {}
        for r in month_records:
            strat_pnl[r["strategy"]] = strat_pnl.get(r["strategy"], 0.0) + r["pnl"]

        best_strategy = max(strat_pnl, key=strat_pnl.get, default="N/A")  # type: ignore[arg-type]
        worst_strategy = min(strat_pnl, key=strat_pnl.get, default="N/A")  # type: ignore[arg-type]

        # Regime breakdown
        regime_pnl: Dict[str, List[float]] = {}
        for r in month_records:
            regime_pnl.setdefault(r["market_regime"], []).append(r["pnl"])

        regime_breakdown: Dict[str, float] = {}
        dominant_regime = "unknown"
        if regime_pnl:
            dominant_regime = max(regime_pnl, key=lambda k: len(regime_pnl[k]))
            for regime, rpnls in regime_pnl.items():
                wins_in_regime = sum(1 for p in rpnls if p > 0)
                regime_breakdown[regime] = round(wins_in_regime / len(rpnls), 4) if rpnls else 0.0

        # Risk notes
        risk_notes = self._build_risk_notes(pnls, max_dd_pct, sharpe, profit_factor)

        return MonthlyReport(
            month=month_prefix,
            total_trades=len(month_records),
            win_rate=round(len(wins) / len(month_records), 4) if month_records else 0.0,
            gross_profit=round(gross_profit, 2),
            total_fees=round(fees, 2),
            net_profit=round(net_profit, 2),
            roi_pct=round((net_profit / max(1.0, capital_start)) * 100, 2) if capital_start else 0.0,
            cagr_pct=round(cagr_pct, 2),
            sharpe_ratio=round(sharpe, 4),
            calmar_ratio=calmar,
            max_drawdown=round(max_dd, 2),
            profit_factor=profit_factor,
            capital_start=round(capital_start, 2),
            capital_end=round(capital_end, 2),
            best_strategy=best_strategy,
            worst_strategy=worst_strategy,
            dominant_regime=dominant_regime,
            regime_breakdown=regime_breakdown,
            strategy_breakdown={k: round(v, 2) for k, v in strat_pnl.items()},
            milestones=milestones,
            projections=projections,
            risk_notes=risk_notes,
            disclaimer=self.DISCLAIMER,
        )

    def generate_quarterly_review(
        self,
        year: int,
        quarter: int,
        compounding_engine: Optional[Any] = None,
        strategy_tracker: Optional[Any] = None,
    ) -> QuarterlyReview:
        """
        Generate a quarterly strategy attribution review.

        Args:
            year: Review year.
            quarter: Quarter (1-4).
            compounding_engine: Optional CompoundingEngine.
            strategy_tracker: Optional StrategyPerformanceTracker.

        Returns:
            QuarterlyReview dataclass.
        """
        months = [(year, (quarter - 1) * 3 + i + 1) for i in range(3)]
        quarter_label = f"Q{quarter}-{year}"

        all_records = []
        for y, m in months:
            prefix = f"{y}-{m:02d}"
            all_records.extend([r for r in self._daily_records if r["date"].startswith(prefix)])

        pnls = [r["pnl"] for r in all_records]
        wins = [r for r in all_records if r["is_win"]]
        net_profit = sum(pnls)
        sharpe = self._calculate_sharpe(pnls)

        # Best / worst month
        month_pnl: Dict[str, float] = {}
        for r in all_records:
            key = r["date"][:7]
            month_pnl[key] = month_pnl.get(key, 0.0) + r["pnl"]
        best_month = max(month_pnl, key=month_pnl.get, default="N/A") if month_pnl else "N/A"  # type: ignore[arg-type]
        worst_month = min(month_pnl, key=month_pnl.get, default="N/A") if month_pnl else "N/A"  # type: ignore[arg-type]

        # Strategy attribution
        strat_attr: Dict[str, Dict[str, float]] = {}
        for r in all_records:
            s = r["strategy"]
            if s not in strat_attr:
                strat_attr[s] = {"trades": 0, "wins": 0, "net_pnl": 0.0}
            strat_attr[s]["trades"] += 1
            if r["is_win"]:
                strat_attr[s]["wins"] += 1
            strat_attr[s]["net_pnl"] += r["pnl"]
        for s in strat_attr:
            t = strat_attr[s]["trades"]
            strat_attr[s]["win_rate"] = round(strat_attr[s]["wins"] / t, 4) if t else 0.0

        # Regime attribution
        regime_attr: Dict[str, Dict[str, float]] = {}
        for r in all_records:
            reg = r["market_regime"]
            if reg not in regime_attr:
                regime_attr[reg] = {"trades": 0, "wins": 0, "net_pnl": 0.0}
            regime_attr[reg]["trades"] += 1
            if r["is_win"]:
                regime_attr[reg]["wins"] += 1
            regime_attr[reg]["net_pnl"] += r["pnl"]
        for reg in regime_attr:
            t = regime_attr[reg]["trades"]
            regime_attr[reg]["win_rate"] = round(regime_attr[reg]["wins"] / t, 4) if t else 0.0

        # Milestones
        milestones: List[str] = []
        cagr_pct = 0.0
        if compounding_engine:
            try:
                state = compounding_engine.get_state()
                milestones = [f"${m:,.0f}" for m in state.milestones_hit]
                cagr_pct = compounding_engine._calculate_cagr()
            except Exception:
                pass

        insights = self._build_quarterly_insights(strat_attr, regime_attr, net_profit, pnls)

        forward_outlook = (
            "Based on historical patterns, continue focusing on high entry-score setups "
            f"in the dominant regime. Monitor drawdown closely. Current CAGR: {cagr_pct:.1f}%."
        )

        return QuarterlyReview(
            quarter=quarter_label,
            total_trades=len(all_records),
            net_profit=round(net_profit, 2),
            roi_pct=0.0,
            cagr_pct=round(cagr_pct, 2),
            sharpe_ratio=round(sharpe, 4),
            best_month=best_month,
            worst_month=worst_month,
            strategy_attribution={k: {sk: round(sv, 4) for sk, sv in v.items()} for k, v in strat_attr.items()},
            regime_attribution={k: {sk: round(sv, 4) for sk, sv in v.items()} for k, v in regime_attr.items()},
            milestones=milestones,
            insights=insights,
            forward_outlook=forward_outlook,
        )

    # ------------------------------------------------------------------
    # Formatting
    # ------------------------------------------------------------------

    def format_daily_summary(self, summary: DailySummary) -> str:
        """Format a DailySummary as a human-readable string."""
        lines = [
            "",
            "=" * 70,
            f"📋  DAILY SUMMARY — {summary.date}",
            "=" * 70,
            f"  Trades:        {summary.total_trades}  ({summary.wins}W / {summary.losses}L)",
            f"  Win Rate:      {summary.win_rate * 100:.1f}%",
            f"  Net Profit:    ${summary.net_profit:.2f}",
            f"  Gross Profit:  ${summary.gross_profit:.2f}",
            f"  Fees:          ${summary.total_fees:.2f}",
            f"  Best Trade:    ${summary.best_trade:.2f}",
            f"  Worst Trade:   ${summary.worst_trade:.2f}",
            f"  Capital:       ${summary.ending_capital:,.2f}",
            f"  Regime:        {summary.regime_of_day}",
            f"  Top Strategy:  {summary.top_strategy}",
        ]
        if summary.notes:
            lines.append("")
            lines.append("  NOTES")
            for note in summary.notes:
                lines.append(f"    • {note}")
        lines.append("=" * 70)
        return "\n".join(lines)

    def format_weekly_digest(self, digest: WeeklyDigest) -> str:
        """Format a WeeklyDigest as a human-readable string."""
        lines = [
            "",
            "=" * 70,
            f"📋  WEEKLY DIGEST — {digest.week_start} to {digest.week_end}",
            "=" * 70,
            f"  Trades:          {digest.total_trades}",
            f"  Win Rate:        {digest.win_rate * 100:.1f}%",
            f"  Net Profit:      ${digest.net_profit:.2f}",
            f"  ROI:             {digest.roi_pct:.2f}%",
            f"  Sharpe:          {digest.sharpe_ratio:.3f}",
            f"  Max Drawdown:    ${digest.max_drawdown:.2f}",
            f"  Best Day:        ${digest.best_day_profit:.2f}",
            f"  Worst Day:       ${digest.worst_day_profit:.2f}",
            f"  Capital Start:   ${digest.capital_start:,.2f}",
            f"  Capital End:     ${digest.capital_end:,.2f}",
            f"  Dominant Regime: {digest.dominant_regime}",
            f"  Strategy Rank:   {', '.join(digest.strategy_ranking[:3])}",
        ]
        if digest.milestones_hit:
            lines.append(f"  Milestones:      {', '.join(digest.milestones_hit)}")
        if digest.key_insights:
            lines.extend(["", "  KEY INSIGHTS"])
            for insight in digest.key_insights:
                lines.append(f"    • {insight}")
        lines.append("=" * 70)
        return "\n".join(lines)

    def format_monthly_report(self, report: MonthlyReport) -> str:
        """Format a MonthlyReport as a human-readable string."""
        lines = [
            "",
            "=" * 90,
            f"📊  NIJA MONTHLY INVESTOR REPORT — {report.month}",
            "=" * 90,
            "",
            "  PERFORMANCE SUMMARY",
            f"    Total Trades:     {report.total_trades}",
            f"    Win Rate:         {report.win_rate * 100:.1f}%",
            f"    Net Profit:       ${report.net_profit:,.2f}",
            f"    Gross Profit:     ${report.gross_profit:,.2f}",
            f"    Total Fees:       ${report.total_fees:,.2f}",
            f"    Monthly ROI:      {report.roi_pct:.2f}%",
            f"    CAGR:             {report.cagr_pct:.2f}%",
            "",
            "  RISK METRICS",
            f"    Sharpe Ratio:     {report.sharpe_ratio:.3f}",
            f"    Calmar Ratio:     {report.calmar_ratio:.3f}",
            f"    Profit Factor:    {report.profit_factor:.2f}",
            f"    Max Drawdown:     ${report.max_drawdown:,.2f}",
            "",
            "  CAPITAL",
            f"    Start:            ${report.capital_start:,.2f}",
            f"    End:              ${report.capital_end:,.2f}",
        ]

        if report.milestones:
            lines.append(f"    Milestones:       {', '.join(report.milestones)}")

        lines.extend([
            "",
            "  STRATEGY BREAKDOWN",
            f"    Best Strategy:    {report.best_strategy}",
            f"    Worst Strategy:   {report.worst_strategy}",
        ])
        for strat, pnl in sorted(report.strategy_breakdown.items(), key=lambda x: x[1], reverse=True):
            lines.append(f"    {strat:<25} ${pnl:>10,.2f}")

        lines.extend(["", "  REGIME BREAKDOWN"])
        for regime, wr in sorted(report.regime_breakdown.items(), key=lambda x: x[1], reverse=True):
            lines.append(f"    {regime:<25} win_rate={wr * 100:.1f}%")

        if report.projections:
            lines.extend(["", "  GROWTH PROJECTIONS (based on current CAGR)"])
            for period, cap in sorted(report.projections.items(), key=lambda x: int(x[0].replace("d", ""))):
                lines.append(f"    {period:>6}: ${cap:>12,.2f}")

        if report.risk_notes:
            lines.extend(["", "  RISK NOTES"])
            for note in report.risk_notes:
                lines.append(f"    ⚠  {note}")

        lines.extend([
            "",
            "  DISCLAIMER",
            f"    {report.disclaimer}",
            "=" * 90,
        ])
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def export_json(self, filename: str, data: Dict[str, Any]) -> str:
        """
        Export a report as a JSON file.

        Args:
            filename: File name (relative to REPORT_DIR or absolute path).
            data: Report data dictionary.

        Returns:
            Absolute path to the exported file.
        """
        path = Path(filename) if Path(filename).is_absolute() else self.REPORT_DIR / filename
        path.parent.mkdir(parents=True, exist_ok=True)

        payload = {
            "generated_at": datetime.now().isoformat(),
            "version": "1.0",
            "data": data,
        }
        with open(path, "w") as f:
            json.dump(payload, f, indent=2, default=str)

        logger.info("📤 Report exported to %s", path)
        return str(path)

    def auto_export_daily(self, summary: DailySummary) -> str:
        """Auto-export a daily summary to the reports directory."""
        filename = f"daily_{summary.date}.json"
        return self.export_json(filename, asdict(summary))

    def auto_export_monthly(self, report: MonthlyReport) -> str:
        """Auto-export a monthly report to the reports directory."""
        filename = f"monthly_{report.month}.json"
        return self.export_json(filename, asdict(report))

    # ------------------------------------------------------------------
    # Calculation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _calculate_sharpe(pnls: List[float], risk_free: float = 0.0) -> float:
        if len(pnls) < 2:
            return 0.0
        n = len(pnls)
        mean = sum(pnls) / n
        variance = sum((x - mean) ** 2 for x in pnls) / (n - 1)
        import math
        std = math.sqrt(variance) if variance > 0 else 0.0
        if std == 0:
            return 0.0
        return ((mean - risk_free) / std) * math.sqrt(252)

    @staticmethod
    def _calculate_max_drawdown(pnls: List[float]) -> Tuple[float, float]:
        """Return (max_drawdown_$, max_drawdown_pct)."""
        if not pnls:
            return 0.0, 0.0
        equity = peak = 0.0
        max_dd = max_dd_pct = 0.0
        for pnl in pnls:
            equity += pnl
            peak = max(peak, equity)
            dd = peak - equity
            dd_pct = (dd / peak * 100) if peak > 0 else 0.0
            if dd > max_dd:
                max_dd = dd
                max_dd_pct = dd_pct
        return round(max_dd, 4), round(max_dd_pct, 4)

    @staticmethod
    def _build_daily_notes(
        records: List[Dict],
        net_profit: float,
        wins: List[Dict],
        losses: List[Dict],
    ) -> List[str]:
        notes = []
        if not records:
            notes.append("No trades recorded for this day.")
            return notes
        if net_profit > 0:
            notes.append(f"Profitable day: +${net_profit:.2f}")
        elif net_profit < 0:
            notes.append(f"Losing day: ${net_profit:.2f} — review entry criteria.")
        if len(records) >= 15:
            notes.append("High trade volume — check for overtrading signals.")
        if wins and losses:
            wr = len(wins) / len(records)
            if wr < 0.40:
                notes.append(f"Low win rate ({wr*100:.0f}%) — entry signals may need tightening.")
        return notes

    @staticmethod
    def _build_risk_notes(
        pnls: List[float],
        max_dd_pct: float,
        sharpe: float,
        profit_factor: float,
    ) -> List[str]:
        notes = []
        if max_dd_pct > 15:
            notes.append(f"Max drawdown exceeded 15% ({max_dd_pct:.1f}%) — consider reducing position sizes.")
        if sharpe < 0.5 and len(pnls) >= 20:
            notes.append(f"Sharpe ratio is low ({sharpe:.2f}) — returns are not sufficiently risk-adjusted.")
        if profit_factor < 1.0 and pnls:
            notes.append(f"Profit factor below 1.0 ({profit_factor:.2f}) — strategy is net-negative this month.")
        if len(pnls) < 10:
            notes.append("Small sample size — statistical reliability is limited.")
        return notes

    @staticmethod
    def _build_quarterly_insights(
        strat_attr: Dict,
        regime_attr: Dict,
        net_profit: float,
        pnls: List[float],
    ) -> List[str]:
        insights = []
        if net_profit > 0:
            insights.append(f"Quarter was net profitable: +${net_profit:,.2f}.")
        else:
            insights.append(f"Quarter was net unprofitable: ${net_profit:,.2f}. Review strategy parameters.")

        if strat_attr:
            best_strat = max(strat_attr, key=lambda s: strat_attr[s].get("net_pnl", 0))
            insights.append(f"Best strategy: {best_strat} (${strat_attr[best_strat].get('net_pnl', 0):,.2f}).")

        if regime_attr:
            best_regime = max(regime_attr, key=lambda r: regime_attr[r].get("win_rate", 0))
            insights.append(f"Best-performing regime: {best_regime} (win_rate={regime_attr[best_regime].get('win_rate', 0)*100:.1f}%).")

        return insights

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load_state(self) -> None:
        if not self.STATE_FILE.exists():
            return
        try:
            with open(self.STATE_FILE, "r") as f:
                data = json.load(f)
            self._daily_records = data.get("records", [])
            logger.info("✅ Loaded %d performance records", len(self._daily_records))
        except Exception as exc:
            logger.warning("Could not load performance reporter state: %s", exc)

    def _save_state(self) -> None:
        try:
            payload = {
                "records": self._daily_records,
                "updated_at": datetime.now().isoformat(),
            }
            with open(self.STATE_FILE, "w") as f:
                json.dump(payload, f, indent=2)
        except Exception as exc:
            logger.error("Failed to save performance reporter state: %s", exc)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_reporter: Optional[PerformanceReporter] = None


def get_performance_reporter() -> PerformanceReporter:
    """Return the module-level singleton PerformanceReporter."""
    global _reporter
    if _reporter is None:
        _reporter = PerformanceReporter()
    return _reporter


if __name__ == "__main__":
    import random

    logging.basicConfig(level=logging.INFO, format="%(levelname)s - %(message)s")

    reporter = get_performance_reporter()
    now = datetime.now()
    strategies = ["apex_v71", "rsi_dual", "momentum"]
    regimes = ["trending", "ranging", "volatile"]

    print("Seeding performance data...\n")
    for i in range(40):
        strat = random.choice(strategies)
        regime = random.choice(regimes)
        pnl = random.gauss(5, 20)
        ts = now - timedelta(hours=i * 4)
        reporter.record_trade(
            trade_id=f"T-{i:04d}",
            strategy=strat,
            symbol="BTC-USD",
            side="long",
            pnl=pnl,
            fees=0.50,
            market_regime=regime,
            entry_ts=ts - timedelta(hours=2),
            exit_ts=ts,
            entry_score=random.randint(2, 5),
        )

    daily = reporter.generate_daily_summary()
    print(reporter.format_daily_summary(daily))

    weekly = reporter.generate_weekly_digest()
    print(reporter.format_weekly_digest(weekly))

    monthly = reporter.generate_monthly_report(now.year, now.month)
    print(reporter.format_monthly_report(monthly))

    quarterly = reporter.generate_quarterly_review(now.year, (now.month - 1) // 3 + 1)
    print(f"\nQuarterly Review: {quarterly.quarter} | Trades: {quarterly.total_trades} | Net PnL: ${quarterly.net_profit:.2f}")
    print("Insights:", quarterly.insights)
