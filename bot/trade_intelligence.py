"""
NIJA Trade Intelligence Engine
================================

Self-analyzing trade pattern engine that continuously learns from historical
trades to identify winning conditions, score new setups, and surface actionable
intelligence.

Key Features:
1. Win/loss attribution — surface the conditions that drive edge
2. Pattern recognition — detect recurring setups across symbols / regimes
3. Predictive entry scoring — score new opportunities using historical base rates
4. Holding-period analysis — optimal hold time per strategy and regime
5. Intelligence reports — concise, structured summaries readable by humans and APIs

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

logger = logging.getLogger("nija.trade_intelligence")

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class TradeRecord:
    """Minimal trade record used for intelligence analysis."""
    trade_id: str
    symbol: str
    strategy: str
    side: str                    # 'long' | 'short'
    entry_price: float
    exit_price: Optional[float]
    position_size_usd: float
    pnl: float                   # net P&L after fees
    fees: float
    market_regime: str           # 'trending' | 'ranging' | 'volatile'
    entry_rsi_9: Optional[float]
    entry_rsi_14: Optional[float]
    entry_adx: Optional[float]
    entry_score: Optional[int]   # 0-5 quality score
    exit_reason: str
    entry_ts: datetime
    exit_ts: Optional[datetime]

    @property
    def is_win(self) -> bool:
        return self.pnl > 0

    @property
    def holding_hours(self) -> Optional[float]:
        if self.exit_ts and self.entry_ts:
            return (self.exit_ts - self.entry_ts).total_seconds() / 3600.0
        return None

    @property
    def pnl_pct(self) -> float:
        if self.position_size_usd and self.position_size_usd > 0:
            return (self.pnl / self.position_size_usd) * 100.0
        return 0.0


@dataclass
class PatternStats:
    """Aggregated statistics for a trade pattern bucket."""
    bucket: str                  # human-readable bucket label
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    total_pnl: float = 0.0
    total_fees: float = 0.0
    avg_pnl: float = 0.0
    avg_holding_hours: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0  # gross_profit / gross_loss
    avg_entry_score: float = 0.0

    def update(self, record: TradeRecord) -> None:
        self.total_trades += 1
        if record.is_win:
            self.wins += 1
        else:
            self.losses += 1
        self.total_pnl += record.pnl
        self.total_fees += record.fees
        if record.holding_hours is not None:
            prev_total = self.avg_holding_hours * (self.total_trades - 1)
            self.avg_holding_hours = (prev_total + record.holding_hours) / self.total_trades
        if record.entry_score is not None:
            prev_total = self.avg_entry_score * (self.total_trades - 1)
            self.avg_entry_score = (prev_total + record.entry_score) / self.total_trades

    def finalize(self) -> None:
        if self.total_trades > 0:
            self.win_rate = self.wins / self.total_trades
            self.avg_pnl = self.total_pnl / self.total_trades
        # profit_factor is set by the engine from raw records for accuracy


@dataclass
class IntelligenceReport:
    """Structured intelligence report snapshot."""
    generated_at: str
    total_trades_analyzed: int
    overall_win_rate: float
    overall_avg_pnl: float
    best_regime: str
    worst_regime: str
    best_strategy: str
    worst_strategy: str
    best_entry_score_bucket: str
    optimal_holding_hours: float
    top_insights: List[str]
    pattern_stats: Dict[str, Any]


# ---------------------------------------------------------------------------
# Core engine
# ---------------------------------------------------------------------------

class TradeIntelligenceEngine:
    """
    Continuously learns from completed trades to surface actionable intelligence.

    Responsibilities:
    1. Ingest completed trade records
    2. Bucket trades by regime, strategy, entry score, holding time
    3. Calculate win rates, profit factors and avg PnL per bucket
    4. Score new opportunities using historical base rates
    5. Generate concise intelligence reports
    """

    DATA_DIR = Path(__file__).parent.parent / "data"
    STATE_FILE = DATA_DIR / "trade_intelligence_state.json"
    MAX_RECORDS = 5_000  # keep the last N completed trades in memory

    def __init__(self):
        self._records: List[TradeRecord] = []
        self.DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._load_state()
        logger.info("🧠 Trade Intelligence Engine initialized with %d records", len(self._records))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def ingest_trade(self, record: TradeRecord) -> None:
        """
        Ingest a completed trade record for analysis.

        Args:
            record: Completed trade record (exit_ts and exit_price required).
        """
        if record.exit_ts is None:
            logger.debug("Skipping open trade %s", record.trade_id)
            return

        self._records.append(record)
        if len(self._records) > self.MAX_RECORDS:
            self._records = self._records[-self.MAX_RECORDS:]

        self._save_state()
        logger.debug("📥 Ingested trade %s | %s | pnl=%.2f", record.trade_id, record.symbol, record.pnl)

    def score_opportunity(
        self,
        strategy: str,
        market_regime: str,
        entry_score: int,
        side: str = "long",
    ) -> Dict[str, Any]:
        """
        Score a new trade opportunity using historical base rates.

        Args:
            strategy: Strategy name
            market_regime: Market regime label
            entry_score: Quality score (0-5)
            side: 'long' or 'short'

        Returns:
            Dictionary with predicted_win_rate, expected_pnl, confidence, recommendation.
        """
        relevant = [
            r for r in self._records
            if r.strategy == strategy
            and r.market_regime == market_regime
            and r.side == side
        ]

        # Fallback: widen the filter if too few records
        if len(relevant) < 10:
            relevant = [r for r in self._records if r.market_regime == market_regime]

        if len(relevant) < 5:
            relevant = list(self._records)  # global fallback

        wins = [r for r in relevant if r.is_win]
        predicted_win_rate = len(wins) / len(relevant) if relevant else 0.5
        expected_pnl = sum(r.pnl for r in relevant) / len(relevant) if relevant else 0.0

        # Adjust by entry score quality (higher score → better)
        score_adjustment = (entry_score - 2.5) * 0.04  # ±10% at extremes
        adjusted_win_rate = max(0.0, min(1.0, predicted_win_rate + score_adjustment))

        confidence = "low" if len(relevant) < 20 else ("medium" if len(relevant) < 100 else "high")

        recommendation = "TAKE" if adjusted_win_rate >= 0.55 and expected_pnl > 0 else (
            "SKIP" if adjusted_win_rate < 0.40 else "NEUTRAL"
        )

        return {
            "predicted_win_rate": round(adjusted_win_rate, 4),
            "expected_pnl": round(expected_pnl, 4),
            "sample_size": len(relevant),
            "confidence": confidence,
            "recommendation": recommendation,
        }

    def get_pattern_stats(self) -> Dict[str, PatternStats]:
        """
        Compute pattern statistics across all known buckets.

        Returns:
            Mapping of bucket_key → PatternStats
        """
        buckets: Dict[str, PatternStats] = {}
        gross_wins_by_bucket: Dict[str, float] = defaultdict(float)
        gross_losses_by_bucket: Dict[str, float] = defaultdict(float)

        for record in self._records:
            for key, label in self._bucket_keys(record):
                if key not in buckets:
                    buckets[key] = PatternStats(bucket=label)
                buckets[key].update(record)

                if record.pnl > 0:
                    gross_wins_by_bucket[key] += record.pnl
                else:
                    gross_losses_by_bucket[key] += abs(record.pnl)

        for key, stats in buckets.items():
            stats.finalize()
            gl = gross_losses_by_bucket[key]
            gw = gross_wins_by_bucket[key]
            stats.profit_factor = round(gw / gl, 4) if gl > 0 else float("inf")

        return buckets

    def generate_report(self) -> IntelligenceReport:
        """
        Generate a comprehensive intelligence report from all ingested trades.

        Returns:
            IntelligenceReport dataclass instance.
        """
        records = self._records
        total = len(records)

        if total == 0:
            return IntelligenceReport(
                generated_at=datetime.now().isoformat(),
                total_trades_analyzed=0,
                overall_win_rate=0.0,
                overall_avg_pnl=0.0,
                best_regime="N/A",
                worst_regime="N/A",
                best_strategy="N/A",
                worst_strategy="N/A",
                best_entry_score_bucket="N/A",
                optimal_holding_hours=0.0,
                top_insights=["No completed trades available for analysis."],
                pattern_stats={},
            )

        wins = [r for r in records if r.is_win]
        overall_win_rate = len(wins) / total
        overall_avg_pnl = sum(r.pnl for r in records) / total

        pattern_stats = self.get_pattern_stats()

        # Best / worst by regime
        regime_stats = {k: v for k, v in pattern_stats.items() if k.startswith("regime:")}
        best_regime, worst_regime = self._best_worst(regime_stats)

        # Best / worst by strategy
        strat_stats = {k: v for k, v in pattern_stats.items() if k.startswith("strategy:")}
        best_strategy, worst_strategy = self._best_worst(strat_stats)

        # Best entry score bucket
        score_stats = {k: v for k, v in pattern_stats.items() if k.startswith("score:")}
        best_score_bucket = max(score_stats.values(), key=lambda s: s.avg_pnl, default=None)
        best_entry_score_bucket = best_score_bucket.bucket if best_score_bucket else "N/A"

        # Optimal holding hours (from winning trades)
        win_holds = [r.holding_hours for r in wins if r.holding_hours is not None]
        optimal_holding_hours = sum(win_holds) / len(win_holds) if win_holds else 0.0

        # Build insights
        insights = self._build_insights(
            records, overall_win_rate, overall_avg_pnl,
            regime_stats, strat_stats, score_stats
        )

        return IntelligenceReport(
            generated_at=datetime.now().isoformat(),
            total_trades_analyzed=total,
            overall_win_rate=round(overall_win_rate, 4),
            overall_avg_pnl=round(overall_avg_pnl, 4),
            best_regime=best_regime,
            worst_regime=worst_regime,
            best_strategy=best_strategy,
            worst_strategy=worst_strategy,
            best_entry_score_bucket=best_entry_score_bucket,
            optimal_holding_hours=round(optimal_holding_hours, 2),
            top_insights=insights,
            pattern_stats={k: asdict(v) for k, v in pattern_stats.items()},
        )

    def print_report(self) -> None:
        """Print a human-readable intelligence report to the log."""
        report = self.generate_report()
        lines = [
            "",
            "=" * 80,
            "🧠  NIJA TRADE INTELLIGENCE REPORT",
            "=" * 80,
            f"  Generated:          {report.generated_at}",
            f"  Trades Analyzed:    {report.total_trades_analyzed}",
            f"  Overall Win Rate:   {report.overall_win_rate * 100:.1f}%",
            f"  Average PnL/Trade:  ${report.overall_avg_pnl:.2f}",
            "",
            "  BEST CONDITIONS",
            f"    Regime:           {report.best_regime}",
            f"    Strategy:         {report.best_strategy}",
            f"    Entry Score:      {report.best_entry_score_bucket}",
            f"    Optimal Hold:     {report.optimal_holding_hours:.1f} hours",
            "",
            "  WORST CONDITIONS",
            f"    Regime:           {report.worst_regime}",
            f"    Strategy:         {report.worst_strategy}",
            "",
            "  TOP INSIGHTS",
        ]
        for insight in report.top_insights:
            lines.append(f"    • {insight}")
        lines.append("=" * 80)
        logger.info("\n".join(lines))

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _bucket_keys(record: TradeRecord) -> List[Tuple[str, str]]:
        """Return all (key, label) pairs for a given trade record."""
        score_bucket = f"score:{record.entry_score}" if record.entry_score is not None else "score:unknown"
        score_label = f"Entry Score {record.entry_score}" if record.entry_score is not None else "Entry Score Unknown"

        hold_bucket = "hold:unknown"
        hold_label = "Holding: Unknown"
        if record.holding_hours is not None:
            if record.holding_hours < 1:
                hold_bucket, hold_label = "hold:<1h", "Holding: <1 hour"
            elif record.holding_hours < 4:
                hold_bucket, hold_label = "hold:1-4h", "Holding: 1–4 hours"
            elif record.holding_hours < 12:
                hold_bucket, hold_label = "hold:4-12h", "Holding: 4–12 hours"
            elif record.holding_hours < 24:
                hold_bucket, hold_label = "hold:12-24h", "Holding: 12–24 hours"
            else:
                hold_bucket, hold_label = "hold:>24h", "Holding: >24 hours"

        return [
            (f"regime:{record.market_regime}", f"Regime: {record.market_regime}"),
            (f"strategy:{record.strategy}", f"Strategy: {record.strategy}"),
            (f"side:{record.side}", f"Side: {record.side}"),
            (score_bucket, score_label),
            (hold_bucket, hold_label),
        ]

    @staticmethod
    def _best_worst(stats_map: Dict[str, PatternStats]) -> Tuple[str, str]:
        """Return (best_bucket_label, worst_bucket_label) by average PnL."""
        if not stats_map:
            return "N/A", "N/A"
        qualified = {k: v for k, v in stats_map.items() if v.total_trades >= 3}
        if not qualified:
            qualified = stats_map
        best = max(qualified.values(), key=lambda s: s.avg_pnl)
        worst = min(qualified.values(), key=lambda s: s.avg_pnl)
        return best.bucket, worst.bucket

    @staticmethod
    def _build_insights(
        records: List[TradeRecord],
        win_rate: float,
        avg_pnl: float,
        regime_stats: Dict[str, PatternStats],
        strat_stats: Dict[str, PatternStats],
        score_stats: Dict[str, PatternStats],
    ) -> List[str]:
        insights: List[str] = []

        # Win rate assessment
        if win_rate >= 0.65:
            insights.append(f"Strong win rate of {win_rate*100:.1f}% — strategy has a proven edge.")
        elif win_rate < 0.45:
            insights.append(f"Win rate of {win_rate*100:.1f}% is below 45% — review entry criteria.")

        # Average PnL
        if avg_pnl < 0:
            insights.append(f"Average PnL is negative (${avg_pnl:.2f}) — fees or stop sizing may need adjustment.")

        # Best regime
        best_regime_stats = max(regime_stats.values(), key=lambda s: s.avg_pnl, default=None)
        if best_regime_stats and best_regime_stats.total_trades >= 5:
            insights.append(
                f"Best performance in {best_regime_stats.bucket} regime: "
                f"win rate {best_regime_stats.win_rate*100:.1f}%, avg ${best_regime_stats.avg_pnl:.2f}/trade."
            )

        # Worst regime
        worst_regime_stats = min(regime_stats.values(), key=lambda s: s.avg_pnl, default=None)
        if worst_regime_stats and worst_regime_stats.total_trades >= 5 and worst_regime_stats.avg_pnl < 0:
            insights.append(
                f"Avoid {worst_regime_stats.bucket} regime: avg PnL ${worst_regime_stats.avg_pnl:.2f}/trade."
            )

        # High entry score advantage
        high_score = score_stats.get("score:5") or score_stats.get("score:4")
        low_score = score_stats.get("score:1") or score_stats.get("score:2")
        if high_score and low_score and high_score.total_trades >= 3 and low_score.total_trades >= 3:
            diff = high_score.avg_pnl - low_score.avg_pnl
            if diff > 0:
                insights.append(
                    f"High entry scores (4-5) outperform low scores by ${diff:.2f}/trade — "
                    "entry quality filters are adding value."
                )

        if not insights:
            insights.append("Insufficient data for meaningful insights — continue accumulating trades.")

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
            for item in data.get("records", []):
                try:
                    record = TradeRecord(
                        trade_id=item["trade_id"],
                        symbol=item["symbol"],
                        strategy=item["strategy"],
                        side=item["side"],
                        entry_price=item["entry_price"],
                        exit_price=item.get("exit_price"),
                        position_size_usd=item["position_size_usd"],
                        pnl=item["pnl"],
                        fees=item["fees"],
                        market_regime=item["market_regime"],
                        entry_rsi_9=item.get("entry_rsi_9"),
                        entry_rsi_14=item.get("entry_rsi_14"),
                        entry_adx=item.get("entry_adx"),
                        entry_score=item.get("entry_score"),
                        exit_reason=item["exit_reason"],
                        entry_ts=datetime.fromisoformat(item["entry_ts"]),
                        exit_ts=datetime.fromisoformat(item["exit_ts"]) if item.get("exit_ts") else None,
                    )
                    self._records.append(record)
                except (KeyError, ValueError) as exc:
                    logger.warning("Skipping malformed record: %s", exc)
            logger.info("✅ Loaded %d trade intelligence records", len(self._records))
        except Exception as exc:
            logger.warning("Could not load trade intelligence state: %s", exc)

    def _save_state(self) -> None:
        try:
            serialized = []
            for r in self._records:
                serialized.append({
                    "trade_id": r.trade_id,
                    "symbol": r.symbol,
                    "strategy": r.strategy,
                    "side": r.side,
                    "entry_price": r.entry_price,
                    "exit_price": r.exit_price,
                    "position_size_usd": r.position_size_usd,
                    "pnl": r.pnl,
                    "fees": r.fees,
                    "market_regime": r.market_regime,
                    "entry_rsi_9": r.entry_rsi_9,
                    "entry_rsi_14": r.entry_rsi_14,
                    "entry_adx": r.entry_adx,
                    "entry_score": r.entry_score,
                    "exit_reason": r.exit_reason,
                    "entry_ts": r.entry_ts.isoformat(),
                    "exit_ts": r.exit_ts.isoformat() if r.exit_ts else None,
                })
            with open(self.STATE_FILE, "w") as f:
                json.dump({"records": serialized, "updated_at": datetime.now().isoformat()}, f, indent=2)
        except Exception as exc:
            logger.error("Failed to save trade intelligence state: %s", exc)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_engine: Optional[TradeIntelligenceEngine] = None


def get_trade_intelligence_engine() -> TradeIntelligenceEngine:
    """Return the module-level singleton TradeIntelligenceEngine."""
    global _engine
    if _engine is None:
        _engine = TradeIntelligenceEngine()
    return _engine


if __name__ == "__main__":
    import random

    logging.basicConfig(level=logging.INFO, format="%(levelname)s - %(message)s")

    engine = get_trade_intelligence_engine()

    # Seed with synthetic trades
    strategies = ["apex_v71", "rsi_dual", "momentum"]
    regimes = ["trending", "ranging", "volatile"]
    now = datetime.now()

    for i in range(50):
        regime = random.choice(regimes)
        score = random.randint(1, 5)
        pnl = random.gauss(5 if score >= 4 else -2, 20)
        engine.ingest_trade(TradeRecord(
            trade_id=f"SIM-{i:04d}",
            symbol=f"BTC-{i % 5}-USD",
            strategy=random.choice(strategies),
            side="long",
            entry_price=40000 + i * 10,
            exit_price=40000 + i * 10 + pnl * 0.1,
            position_size_usd=200.0,
            pnl=pnl,
            fees=0.5,
            market_regime=regime,
            entry_rsi_9=random.uniform(30, 70),
            entry_rsi_14=random.uniform(30, 70),
            entry_adx=random.uniform(15, 40),
            entry_score=score,
            exit_reason="profit_target" if pnl > 0 else "stop_loss",
            entry_ts=now - timedelta(hours=i * 2),
            exit_ts=now - timedelta(hours=i * 2 - 3),
        ))

    engine.print_report()

    scoring = engine.score_opportunity("apex_v71", "trending", entry_score=5)
    print("\nOpportunity Score:", scoring)
