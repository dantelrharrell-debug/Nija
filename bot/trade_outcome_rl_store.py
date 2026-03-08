"""
NIJA Trade Outcome RL Store
============================

Stores every closed trade outcome persistently and feeds a reward-feedback /
reinforcement-learning loop that improves future decisions.

What it does
-------------
1. **Persistent JSONL log** – every closed trade is appended to
   ``data/trade_outcomes.jsonl`` in newline-delimited JSON format.  The log
   survives restarts and can be replayed or analysed off-line.

2. **Reward computation** – a normalised scalar reward in [-1, +1] is derived
   from the trade's return percentage, holding time, and win/loss status.

3. **Fan-out to all learning subsystems** – on every ``record_outcome()`` call
   the store automatically notifies:
   * ``MetaLearningOptimizer`` – regime-aware EMA strategy scoring
   * ``SelfLearningStrategyAllocator`` – dynamic capital weight rebalancing
   * ``PortfolioProfitFlywheel`` – flywheel compounding acceleration
   * ``PortfolioProfitEngine`` – master ledger update

4. **In-memory analytics** – the store keeps a rolling window of recent
   outcomes and exposes convenience helpers:
   * ``get_strategy_stats()`` – per-strategy win-rate / avg-reward
   * ``get_regime_stats()``   – per-regime performance breakdown
   * ``get_symbol_stats()``   – per-symbol performance breakdown
   * ``get_recent_rewards()`` – raw reward series for the last N trades
   * ``get_summary()``        – aggregated dashboard snapshot

5. **Thread-safe singleton** via ``get_trade_outcome_rl_store()``.

Usage
-----
    from bot.trade_outcome_rl_store import get_trade_outcome_rl_store

    store = get_trade_outcome_rl_store()
    store.record_outcome(
        symbol="BTC-USD",
        strategy="ApexTrend",
        regime="BULL_TRENDING",
        pnl_usd=120.50,
        is_win=True,
        entry_price=65_000.0,
        exit_price=66_000.0,
        holding_bars=12,
        fees_usd=0.80,
        extra={"rsi_9": 62.3, "rsi_14": 58.1},
    )

    stats = store.get_strategy_stats()
    print(store.get_summary())

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import json
import logging
import math
import threading
from collections import defaultdict, deque
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("nija.trade_outcome_rl_store")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REWARD_SCALE       = 10.0   # return_pct is multiplied by this before clipping
MAX_REWARD         =  1.0   # upper bound of normalised reward
MIN_REWARD         = -1.0   # lower bound of normalised reward
PENALTY_PER_BAR    = 0.002  # small time penalty per holding bar (opportunity cost)
EMA_DECAY          = 0.90   # EMA smoothing for rolling reward tracker
RECENT_WINDOW      = 200    # in-memory rolling window of outcomes

DATA_DIR  = Path(__file__).parent.parent / "data"
LOG_FILE  = DATA_DIR / "trade_outcomes.jsonl"

# ---------------------------------------------------------------------------
# Outcome record
# ---------------------------------------------------------------------------

@dataclass
class TradeOutcome:
    """Single closed-trade outcome stored by the RL engine."""
    timestamp:    str
    symbol:       str
    strategy:     str
    regime:       str
    pnl_usd:      float
    is_win:       bool
    entry_price:  float
    exit_price:   float
    return_pct:   float   # (exit - entry) / entry  ×100  (sign follows direction)
    holding_bars: int
    fees_usd:     float
    reward:       float   # normalised RL reward [-1, +1]
    extra:        Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Per-bucket statistics helper
# ---------------------------------------------------------------------------

@dataclass
class BucketStats:
    """Running statistics for a strategy / regime / symbol bucket."""
    trades:       int   = 0
    wins:         int   = 0
    total_pnl:    float = 0.0
    total_reward: float = 0.0
    ema_reward:   float = 0.0

    @property
    def win_rate(self) -> float:
        return (self.wins / self.trades * 100) if self.trades else 0.0

    @property
    def avg_reward(self) -> float:
        return (self.total_reward / self.trades) if self.trades else 0.0

    @property
    def avg_pnl(self) -> float:
        return (self.total_pnl / self.trades) if self.trades else 0.0

    def update(self, reward: float, pnl: float, won: bool) -> None:
        self.trades       += 1
        self.wins         += int(won)
        self.total_pnl    += pnl
        self.total_reward += reward
        alpha              = 1.0 - EMA_DECAY
        self.ema_reward    = EMA_DECAY * self.ema_reward + alpha * reward

    def to_dict(self) -> Dict:
        return {
            "trades":      self.trades,
            "wins":        self.wins,
            "win_rate":    round(self.win_rate, 2),
            "avg_pnl":     round(self.avg_pnl, 4),
            "avg_reward":  round(self.avg_reward, 4),
            "ema_reward":  round(self.ema_reward, 4),
            "total_pnl":   round(self.total_pnl, 4),
        }


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class TradeOutcomeRLStore:
    """
    Persistent RL-feedback store for trade outcomes.

    Every ``record_outcome()`` call:
    1. Computes a normalised reward signal.
    2. Appends the full outcome to the JSONL log.
    3. Updates in-memory analytics buckets.
    4. Fans out to all downstream learning subsystems.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        DATA_DIR.mkdir(parents=True, exist_ok=True)

        # In-memory analytics
        self._strategy_stats: Dict[str, BucketStats] = defaultdict(BucketStats)
        self._regime_stats:   Dict[str, BucketStats] = defaultdict(BucketStats)
        self._symbol_stats:   Dict[str, BucketStats] = defaultdict(BucketStats)
        self._recent:         deque = deque(maxlen=RECENT_WINDOW)
        self._total_trades    = 0
        self._ema_reward      = 0.0

        # Replay history from disk so analytics survive restarts
        self._replay_log()

        # Lazy references to downstream singletons (imported on first use to
        # avoid circular-import issues at module load time)
        self._meta_opt      = None
        self._sl_alloc      = None
        self._flywheel      = None
        self._profit_engine = None

        logger.info("=" * 70)
        logger.info("🧠 Trade Outcome RL Store initialised")
        logger.info("   Trades in log : %d", self._total_trades)
        logger.info("   EMA reward    : %.4f", self._ema_reward)
        logger.info("=" * 70)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_outcome(
        self,
        symbol:       str,
        strategy:     str,
        regime:       str,
        pnl_usd:      float,
        is_win:       bool,
        entry_price:  float = 0.0,
        exit_price:   float = 0.0,
        holding_bars: int   = 0,
        fees_usd:     float = 0.0,
        extra:        Optional[Dict[str, Any]] = None,
    ) -> TradeOutcome:
        """
        Record a closed trade outcome and trigger the RL feedback loop.

        Args:
            symbol:       Trading pair, e.g. "BTC-USD".
            strategy:     Strategy name that generated the trade.
            regime:       Market regime at time of entry.
            pnl_usd:      Net P&L in USD (negative = loss).
            is_win:       True when the trade was profitable.
            entry_price:  Entry price (used for return_pct).
            exit_price:   Exit price.
            holding_bars: Number of candle bars the position was held.
            fees_usd:     Exchange fees (informational).
            extra:        Any additional context (RSI values, ATR, …).

        Returns:
            The ``TradeOutcome`` dataclass that was stored.
        """
        return_pct = self._calc_return_pct(entry_price, exit_price, pnl_usd)
        reward     = self._calc_reward(return_pct, holding_bars, is_win)

        outcome = TradeOutcome(
            timestamp    = datetime.now().isoformat(),
            symbol       = symbol,
            strategy     = strategy,
            regime       = regime,
            pnl_usd      = pnl_usd,
            is_win       = is_win,
            entry_price  = entry_price,
            exit_price   = exit_price,
            return_pct   = return_pct,
            holding_bars = holding_bars,
            fees_usd     = fees_usd,
            reward       = reward,
            extra        = extra or {},
        )

        with self._lock:
            # ── 1. Persist to JSONL ───────────────────────────────────────
            self._append_to_log(outcome)

            # ── 2. Update in-memory analytics ────────────────────────────
            self._update_analytics(outcome)

            # ── 3. Fan-out to learning subsystems ────────────────────────
            self._fanout(outcome)

        logger.info(
            "📝 RL outcome: %s  strategy=%s  pnl=$%.2f  reward=%.4f  "
            "ema_reward=%.4f",
            symbol, strategy, pnl_usd, reward, self._ema_reward,
        )
        return outcome

    # -- Analytics --------------------------------------------------------

    def get_strategy_stats(self) -> Dict[str, Dict]:
        """Return per-strategy statistics dict."""
        with self._lock:
            return {k: v.to_dict() for k, v in self._strategy_stats.items()}

    def get_regime_stats(self) -> Dict[str, Dict]:
        """Return per-regime statistics dict."""
        with self._lock:
            return {k: v.to_dict() for k, v in self._regime_stats.items()}

    def get_symbol_stats(self) -> Dict[str, Dict]:
        """Return per-symbol statistics dict."""
        with self._lock:
            return {k: v.to_dict() for k, v in self._symbol_stats.items()}

    def get_recent_rewards(self, n: int = 20) -> List[float]:
        """Return the last *n* reward values (newest last)."""
        with self._lock:
            items = list(self._recent)[-n:]
            return [o.reward for o in items]

    def get_summary(self) -> Dict:
        """Return an aggregated dashboard snapshot."""
        with self._lock:
            best_strategy = max(
                self._strategy_stats.items(),
                key=lambda kv: kv[1].ema_reward,
                default=(None, BucketStats()),
            )
            worst_strategy = min(
                self._strategy_stats.items(),
                key=lambda kv: kv[1].ema_reward,
                default=(None, BucketStats()),
            )
            return {
                "total_trades":    self._total_trades,
                "ema_reward":      round(self._ema_reward, 4),
                "best_strategy":   best_strategy[0],
                "worst_strategy":  worst_strategy[0],
                "strategy_stats":  self.get_strategy_stats(),
                "regime_stats":    self.get_regime_stats(),
                "recent_rewards":  self.get_recent_rewards(),
            }

    def get_report(self) -> str:
        """Return a human-readable RL store report."""
        with self._lock:
            lines = [
                "",
                "=" * 80,
                "  NIJA TRADE OUTCOME RL STORE — REWARD FEEDBACK REPORT",
                "=" * 80,
                f"  Total Outcomes Recorded : {self._total_trades:,}",
                f"  EMA Reward (global)     : {self._ema_reward:+.4f}",
                "",
                "  📈 STRATEGY PERFORMANCE",
                "-" * 80,
            ]
            for strat, stats in sorted(
                self._strategy_stats.items(),
                key=lambda kv: kv[1].ema_reward,
                reverse=True,
            ):
                lines.append(
                    f"  {strat:<26s}  trades={stats.trades:>5,}  "
                    f"win={stats.win_rate:>5.1f}%  "
                    f"avg_pnl=${stats.avg_pnl:>8.2f}  "
                    f"ema_reward={stats.ema_reward:+.4f}"
                )

            lines += [
                "",
                "  🌍 REGIME PERFORMANCE",
                "-" * 80,
            ]
            for regime, stats in sorted(
                self._regime_stats.items(),
                key=lambda kv: kv[1].ema_reward,
                reverse=True,
            ):
                lines.append(
                    f"  {regime:<26s}  trades={stats.trades:>5,}  "
                    f"win={stats.win_rate:>5.1f}%  "
                    f"avg_pnl=${stats.avg_pnl:>8.2f}  "
                    f"ema_reward={stats.ema_reward:+.4f}"
                )

            lines += ["=" * 80, ""]
            return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _calc_return_pct(entry: float, exit_: float, pnl_usd: float) -> float:
        """Compute return percentage from price or from PnL sign."""
        if entry and exit_:
            return ((exit_ - entry) / entry) * 100.0
        # Fallback: derive from PnL sign only (unknown entry / exit)
        return math.copysign(1.0, pnl_usd) * abs(pnl_usd) / max(1.0, abs(entry or 1.0))

    @staticmethod
    def _calc_reward(return_pct: float, holding_bars: int, is_win: bool) -> float:
        """
        Compute a normalised reward in [MIN_REWARD, MAX_REWARD].

        Reward = (return_pct * REWARD_SCALE / 100) − (holding_bars × PENALTY_PER_BAR)
        Clipped to [MIN_REWARD, MAX_REWARD].
        """
        base   = (return_pct / 100.0) * REWARD_SCALE
        penalty = holding_bars * PENALTY_PER_BAR
        raw    = base - penalty
        return round(max(MIN_REWARD, min(MAX_REWARD, raw)), 6)

    def _update_analytics(self, outcome: TradeOutcome) -> None:
        """Update in-memory buckets (must be called inside self._lock)."""
        self._total_trades += 1
        alpha = 1.0 - EMA_DECAY
        self._ema_reward = EMA_DECAY * self._ema_reward + alpha * outcome.reward
        self._recent.append(outcome)

        self._strategy_stats[outcome.strategy].update(
            outcome.reward, outcome.pnl_usd, outcome.is_win
        )
        self._regime_stats[outcome.regime].update(
            outcome.reward, outcome.pnl_usd, outcome.is_win
        )
        self._symbol_stats[outcome.symbol].update(
            outcome.reward, outcome.pnl_usd, outcome.is_win
        )

    def _append_to_log(self, outcome: TradeOutcome) -> None:
        """Append outcome to the persistent JSONL log."""
        try:
            with open(LOG_FILE, "a") as f:
                f.write(json.dumps(outcome.to_dict()) + "\n")
        except Exception as exc:
            logger.error("Failed to write trade outcome to JSONL: %s", exc)

    def _replay_log(self) -> None:
        """Replay the JSONL log into in-memory analytics on startup."""
        if not LOG_FILE.exists():
            return
        try:
            with open(LOG_FILE, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                        outcome = TradeOutcome(
                            timestamp    = d.get("timestamp", ""),
                            symbol       = d.get("symbol", ""),
                            strategy     = d.get("strategy", ""),
                            regime       = d.get("regime", ""),
                            pnl_usd      = float(d.get("pnl_usd", 0.0)),
                            is_win       = bool(d.get("is_win", False)),
                            entry_price  = float(d.get("entry_price", 0.0)),
                            exit_price   = float(d.get("exit_price", 0.0)),
                            return_pct   = float(d.get("return_pct", 0.0)),
                            holding_bars = int(d.get("holding_bars", 0)),
                            fees_usd     = float(d.get("fees_usd", 0.0)),
                            reward       = float(d.get("reward", 0.0)),
                            extra        = d.get("extra", {}),
                        )
                        self._update_analytics(outcome)
                    except Exception:
                        pass  # Skip malformed lines
            logger.info(
                "✅ RL log replayed: %d outcomes loaded", self._total_trades
            )
        except Exception as exc:
            logger.warning("Failed to replay trade outcome log: %s", exc)

    # ------------------------------------------------------------------
    # Fan-out to downstream learning subsystems
    # ------------------------------------------------------------------

    def _fanout(self, outcome: TradeOutcome) -> None:
        """Notify all downstream learning subsystems (best-effort)."""
        self._fanout_meta_optimizer(outcome)
        self._fanout_self_learning_allocator(outcome)
        self._fanout_flywheel(outcome)
        self._fanout_profit_engine(outcome)

    def _get_meta_opt(self):
        if self._meta_opt is None:
            try:
                from bot.meta_learning_optimizer import get_meta_learning_optimizer
                self._meta_opt = get_meta_learning_optimizer()
            except Exception as exc:
                logger.debug("MetaLearningOptimizer unavailable: %s", exc)
        return self._meta_opt

    def _get_sl_alloc(self):
        if self._sl_alloc is None:
            try:
                from bot.self_learning_strategy_allocator import get_self_learning_allocator
                self._sl_alloc = get_self_learning_allocator()
            except Exception as exc:
                logger.debug("SelfLearningStrategyAllocator unavailable: %s", exc)
        return self._sl_alloc

    def _get_flywheel(self):
        if self._flywheel is None:
            try:
                from bot.portfolio_profit_flywheel import get_portfolio_profit_flywheel
                self._flywheel = get_portfolio_profit_flywheel()
            except Exception as exc:
                logger.debug("PortfolioProfitFlywheel unavailable: %s", exc)
        return self._flywheel

    def _get_profit_engine(self):
        if self._profit_engine is None:
            try:
                from bot.portfolio_profit_engine import get_portfolio_profit_engine
                self._profit_engine = get_portfolio_profit_engine()
            except Exception as exc:
                logger.debug("PortfolioProfitEngine unavailable: %s", exc)
        return self._profit_engine

    def _fanout_meta_optimizer(self, outcome: TradeOutcome) -> None:
        try:
            opt = self._get_meta_opt()
            if opt is None:
                return
            opt.record_outcome(
                strategy     = outcome.strategy or "unknown",
                regime       = outcome.regime   or "unknown",
                pnl          = outcome.pnl_usd,
                won          = outcome.is_win,
                drawdown_pct = max(0.0, -outcome.return_pct),
            )
        except Exception as exc:
            logger.debug("MetaLearningOptimizer fanout failed: %s", exc)

    def _fanout_self_learning_allocator(self, outcome: TradeOutcome) -> None:
        try:
            alloc = self._get_sl_alloc()
            if alloc is None:
                return
            alloc.record_trade(
                strategy = outcome.strategy or "unknown",
                pnl_usd  = outcome.pnl_usd,
                is_win   = outcome.is_win,
                fees_usd = outcome.fees_usd,
            )
        except Exception as exc:
            logger.debug("SelfLearningStrategyAllocator fanout failed: %s", exc)

    def _fanout_flywheel(self, outcome: TradeOutcome) -> None:
        try:
            fw = self._get_flywheel()
            if fw is None:
                return
            fw.record_trade(
                symbol   = outcome.symbol,
                pnl_usd  = outcome.pnl_usd,
                is_win   = outcome.is_win,
                fees_usd = outcome.fees_usd,
                strategy = outcome.strategy,
                regime   = outcome.regime,
            )
        except Exception as exc:
            logger.debug("PortfolioProfitFlywheel fanout failed: %s", exc)

    def _fanout_profit_engine(self, outcome: TradeOutcome) -> None:
        try:
            eng = self._get_profit_engine()
            if eng is None:
                return
            eng.record_trade(
                symbol   = outcome.symbol,
                pnl_usd  = outcome.pnl_usd,
                is_win   = outcome.is_win,
                fees_usd = outcome.fees_usd,
            )
        except Exception as exc:
            logger.debug("PortfolioProfitEngine fanout failed: %s", exc)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_store_instance: Optional[TradeOutcomeRLStore] = None
_store_lock = threading.Lock()


def get_trade_outcome_rl_store() -> TradeOutcomeRLStore:
    """
    Return the global TradeOutcomeRLStore singleton.

    Thread-safe; safe to call from anywhere in the codebase.
    """
    global _store_instance
    if _store_instance is None:
        with _store_lock:
            if _store_instance is None:
                _store_instance = TradeOutcomeRLStore()
    return _store_instance


# ---------------------------------------------------------------------------
# Quick smoke-test / demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import logging as _logging
    _logging.basicConfig(level=_logging.INFO, format="%(levelname)s - %(message)s")

    store = get_trade_outcome_rl_store()

    demo = [
        ("BTC-USD",  "ApexTrend",       "BULL_TRENDING",  120.50, True,  65000, 66100, 8,  0.80),
        ("ETH-USD",  "MeanReversion",   "RANGING",        -35.00, False, 3200,  3158,  14, 0.22),
        ("SOL-USD",  "MomentumBreakout","BULL_TRENDING",    75.00, True,  140,   145,   6,  0.14),
        ("XRP-USD",  "LiquidityReversal","RANGING",        -10.00, False, 0.55,  0.53,  20, 0.05),
        ("DOGE-USD", "ApexTrend",       "BULL_TRENDING",   55.25, True,  0.12,  0.125, 5,  0.10),
    ]

    for sym, strat, regime, pnl, win, ep, xp, bars, fees in demo:
        oc = store.record_outcome(
            symbol=sym, strategy=strat, regime=regime,
            pnl_usd=pnl, is_win=win,
            entry_price=ep, exit_price=xp,
            holding_bars=bars, fees_usd=fees,
            extra={"rsi_9": 62.0, "rsi_14": 58.0},
        )
        print(f"  reward={oc.reward:+.4f}  return={oc.return_pct:+.3f}%")

    print(store.get_report())
    print("Summary:", json.dumps(store.get_summary(), indent=2))
