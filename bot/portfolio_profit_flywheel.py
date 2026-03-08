"""
NIJA Portfolio Profit Flywheel
================================

The Flywheel turns every realised profit into a self-reinforcing growth cycle:

  Win → Compound → Bigger position → Bigger win → Compound more …

How it works
-------------
1. **Profit Tiers** – as cumulative net profit crosses configurable milestones
   (e.g. $500, $2 000, $5 000, $10 000 …) the flywheel "spins faster":
   the compound rate and the capital-growth multiplier both increase
   automatically.

2. **Streak Bonus** – consecutive winning trades earn an extra compounding
   bonus (capped at MAX_STREAK_BONUS).  A single loss resets the bonus.

3. **Capital-Growth Multiplier** – the engine exposes a ``get_capital_multiplier()``
   call that any position-sizer can use to scale trade notional upward as the
   portfolio grows.

4. **Flywheel Spin Rate** – a lightweight metric (profit velocity in USD/trade
   over the last N trades) captures whether the flywheel is accelerating,
   holding steady, or decelerating.

5. **Persistent state** – all data survives restarts via JSON.

6. **Thread-safe singleton** via ``get_portfolio_profit_flywheel()``.

Integration
-----------
    from bot.portfolio_profit_flywheel import get_portfolio_profit_flywheel

    flywheel = get_portfolio_profit_flywheel(base_capital=5000.0)
    flywheel.record_trade("BTC-USD", pnl_usd=120.50, is_win=True)

    multiplier = flywheel.get_capital_multiplier()   # scale position sizes
    print(flywheel.get_report())

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import json
import logging
import threading
from collections import deque
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("nija.portfolio_profit_flywheel")

# ---------------------------------------------------------------------------
# Flywheel tiers
# ---------------------------------------------------------------------------

@dataclass
class FlywheelTier:
    """Definition of one profit milestone."""
    name: str
    profit_threshold: float   # net profit (USD) that unlocks this tier
    compound_rate: float      # fraction of each win to auto-compound (0–1)
    capital_multiplier: float # how much to scale allowed position sizes
    label: str                # emoji + short description for logs


_DEFAULT_TIERS: List[FlywheelTier] = [
    FlywheelTier("seed",     0.0,      0.50, 1.00, "🌱 Seed"),
    FlywheelTier("sprout",   500.0,    0.60, 1.10, "🌿 Sprout"),
    FlywheelTier("grow",     2_000.0,  0.68, 1.20, "🌳 Growing"),
    FlywheelTier("momentum", 5_000.0,  0.74, 1.35, "🚀 Momentum"),
    FlywheelTier("flywheel", 10_000.0, 0.80, 1.50, "🌀 Flywheel"),
    FlywheelTier("elite",    25_000.0, 0.85, 1.70, "🏆 Elite"),
    FlywheelTier("apex",     50_000.0, 0.90, 2.00, "⚡ Apex"),
]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

STREAK_BONUS_PER_WIN   = 0.005   # +0.5 % compound rate per consecutive win
MAX_STREAK_BONUS       = 0.10    # cap at +10 %
SPIN_WINDOW            = 20      # trades used for velocity (spin-rate) calc
MAX_MULTIPLIER         = 3.0     # hard cap on capital multiplier
MIN_MULTIPLIER         = 1.0

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class FlywheelState:
    """Persisted state of the flywheel engine."""
    epoch: int = 0
    base_capital: float = 0.0
    total_gross_profit: float = 0.0
    total_gross_loss: float = 0.0
    total_fees: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0
    compounded_profit: float = 0.0
    current_tier: str = "seed"
    current_win_streak: int = 0
    best_win_streak: int = 0
    epoch_started: str = ""
    last_updated: str = ""
    trades: List[Dict] = field(default_factory=list)

    @property
    def net_profit(self) -> float:
        return self.total_gross_profit - self.total_gross_loss

    @property
    def win_rate(self) -> float:
        if self.total_trades > 0:
            return (self.winning_trades / self.total_trades) * 100
        return 0.0

    @property
    def profit_factor(self) -> float:
        if self.total_gross_loss > 0:
            return round(self.total_gross_profit / self.total_gross_loss, 4)
        return 999.99 if self.total_gross_profit > 0 else 0.0

    @property
    def roi_pct(self) -> float:
        if self.base_capital > 0:
            return (self.net_profit / self.base_capital) * 100
        return 0.0

    def to_dict(self) -> Dict:
        d = asdict(self)
        d["net_profit"] = self.net_profit
        d["win_rate"] = self.win_rate
        d["profit_factor"] = self.profit_factor
        d["roi_pct"] = self.roi_pct
        return d


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class PortfolioProfitFlywheel:
    """
    Self-reinforcing profit-compounding flywheel.

    Each profitable trade automatically compounds a portion of its P&L back
    into the capital pool.  As cumulative profit crosses tier thresholds the
    compound rate increases — creating a flywheel effect that accelerates
    portfolio growth over time.

    Usage
    -----
        flywheel = get_portfolio_profit_flywheel(base_capital=5000.0)
        flywheel.record_trade("BTC-USD", pnl_usd=120.0, is_win=True)
        mult = flywheel.get_capital_multiplier()
    """

    DATA_DIR   = Path(__file__).parent.parent / "data"
    STATE_FILE = DATA_DIR / "flywheel_state.json"

    def __init__(
        self,
        base_capital: float = 0.0,
        tiers: Optional[List[FlywheelTier]] = None,
    ):
        self._lock  = threading.RLock()
        self._tiers = tiers or _DEFAULT_TIERS
        # Sorted ascending by threshold so we can walk them
        self._tiers = sorted(self._tiers, key=lambda t: t.profit_threshold)

        # Rolling window of recent P&Ls for spin-rate calculation
        self._recent_pnls: deque = deque(maxlen=SPIN_WINDOW)

        self.DATA_DIR.mkdir(parents=True, exist_ok=True)

        if not self._load_state():
            self._state = FlywheelState(
                base_capital=base_capital,
                epoch_started=datetime.now().isoformat(),
                last_updated=datetime.now().isoformat(),
            )
            self._save_state()

        # Re-populate recent_pnls from persisted trade history
        for t in self._state.trades[-SPIN_WINDOW:]:
            self._recent_pnls.append(t.get("pnl_usd", 0.0))

        logger.info("=" * 70)
        logger.info("🌀 Portfolio Profit Flywheel initialised")
        logger.info("   Epoch     : %d", self._state.epoch)
        logger.info("   Tier      : %s", self._current_tier().label)
        logger.info("   Net P&L   : $%.2f", self._state.net_profit)
        logger.info("   Spin rate : $%.2f / trade", self._spin_rate())
        logger.info("=" * 70)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _current_tier(self) -> FlywheelTier:
        """Return the highest tier whose threshold the current net profit meets."""
        net = self._state.net_profit
        best = self._tiers[0]
        for tier in self._tiers:
            if net >= tier.profit_threshold:
                best = tier
            else:
                break
        return best

    def _spin_rate(self) -> float:
        """USD profit per trade averaged over the last SPIN_WINDOW trades."""
        if not self._recent_pnls:
            return 0.0
        return sum(self._recent_pnls) / len(self._recent_pnls)

    def _effective_compound_rate(self) -> float:
        """Compound rate = tier base rate + streak bonus (capped)."""
        tier = self._current_tier()
        streak_bonus = min(
            self._state.current_win_streak * STREAK_BONUS_PER_WIN,
            MAX_STREAK_BONUS,
        )
        return min(1.0, tier.compound_rate + streak_bonus)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_trade(
        self,
        symbol: str,
        pnl_usd: float,
        is_win: bool,
        fees_usd: float = 0.0,
        strategy: str = "",
        regime: str = "",
    ) -> Dict:
        """
        Record a completed trade and spin the flywheel.

        Args:
            symbol:    Trading pair (e.g. "BTC-USD").
            pnl_usd:   Net P&L in USD (negative = loss).
            is_win:    True when the trade was profitable.
            fees_usd:  Exchange fees (tracked separately).
            strategy:  Strategy name (for reporting only).
            regime:    Market regime label (for reporting only).

        Returns:
            Dict with flywheel metrics for this trade.
        """
        with self._lock:
            s = self._state
            s.total_trades += 1
            s.total_fees   += fees_usd
            self._recent_pnls.append(pnl_usd)

            tier_before = self._current_tier().name

            if pnl_usd > 0:
                s.total_gross_profit  += pnl_usd
                s.winning_trades      += 1
                s.current_win_streak  += 1
                s.best_win_streak      = max(s.best_win_streak, s.current_win_streak)

                compound_rate  = self._effective_compound_rate()
                compound_amount = pnl_usd * compound_rate
                s.compounded_profit   += compound_amount
            else:
                s.total_gross_loss    += abs(pnl_usd)
                s.current_win_streak   = 0  # streak reset on any loss
                compound_rate   = 0.0
                compound_amount = 0.0

            tier_after  = self._current_tier()
            tier_changed = tier_after.name != tier_before

            if tier_changed:
                logger.info(
                    "🎯 Flywheel tier upgraded → %s  (net profit: $%.2f)",
                    tier_after.label,
                    s.net_profit,
                )

            spin = self._spin_rate()
            trade_record = {
                "timestamp":     datetime.now().isoformat(),
                "symbol":        symbol,
                "strategy":      strategy,
                "regime":        regime,
                "pnl_usd":       pnl_usd,
                "is_win":        is_win,
                "fees_usd":      fees_usd,
                "compound_rate": compound_rate,
                "compounded":    compound_amount,
                "tier":          tier_after.name,
                "win_streak":    s.current_win_streak,
                "spin_rate":     spin,
                "epoch":         s.epoch,
            }
            s.trades.append(trade_record)
            s.current_tier  = tier_after.name
            s.last_updated  = datetime.now().isoformat()
            self._save_state()

            logger.info(
                "%s trade: %s  pnl=$%.2f  tier=%s  streak=%d  spin=$%.2f/trade  "
                "compound_rate=%.0f%%  compounded=$%.2f",
                "🏆" if is_win else "📉",
                symbol,
                pnl_usd,
                tier_after.label,
                s.current_win_streak,
                spin,
                compound_rate * 100,
                compound_amount,
            )

            return {
                "tier":            tier_after.name,
                "tier_label":      tier_after.label,
                "tier_changed":    tier_changed,
                "compound_rate":   compound_rate,
                "compounded_usd":  compound_amount,
                "win_streak":      s.current_win_streak,
                "spin_rate":       spin,
                "capital_mult":    self.get_capital_multiplier(),
                "net_profit":      s.net_profit,
            }

    def get_capital_multiplier(self) -> float:
        """
        Return the current flywheel capital-growth multiplier.

        Position-sizers multiply their base notional by this value to
        benefit from the growing capital pool.

        Returns:
            Float in [MIN_MULTIPLIER, MAX_MULTIPLIER].
        """
        with self._lock:
            tier = self._current_tier()
            mult = tier.capital_multiplier
            # Extra boost: +1 % per consecutive win (capped at +20 %)
            streak_boost = min(0.20, self._state.current_win_streak * 0.01)
            mult *= (1.0 + streak_boost)
            return round(min(MAX_MULTIPLIER, max(MIN_MULTIPLIER, mult)), 4)

    def get_effective_compound_rate(self) -> float:
        """Current compound rate (including streak bonus)."""
        with self._lock:
            return round(self._effective_compound_rate(), 4)

    def get_tier(self) -> FlywheelTier:
        """Return the current FlywheelTier object."""
        with self._lock:
            return self._current_tier()

    def get_spin_rate(self) -> float:
        """Mean USD P&L per trade over the last SPIN_WINDOW trades."""
        with self._lock:
            return round(self._spin_rate(), 4)

    def get_summary(self) -> Dict:
        """Return a full snapshot of flywheel state."""
        with self._lock:
            tier = self._current_tier()
            d = self._state.to_dict()
            d["effective_compound_rate"] = self._effective_compound_rate()
            d["capital_multiplier"]      = self.get_capital_multiplier()
            d["spin_rate"]               = self._spin_rate()
            d["tier_label"]              = tier.label
            d["tier_compound_rate"]      = tier.compound_rate
            d["next_tier"]               = self._next_tier_info()
            return d

    def get_trade_log(self, limit: int = 50) -> List[Dict]:
        """Return the most recent trade records (newest first)."""
        with self._lock:
            return list(reversed(self._state.trades[-limit:]))

    def reset_flywheel(self, new_base_capital: float = 0.0) -> Dict:
        """
        Reset the flywheel to a fresh epoch.  Returns the completed epoch
        summary.

        Args:
            new_base_capital: Starting capital for the new epoch.
        """
        with self._lock:
            old = self._state.to_dict()
            old_epoch = self._state.epoch
            self._state = FlywheelState(
                epoch=old_epoch + 1,
                base_capital=new_base_capital,
                epoch_started=datetime.now().isoformat(),
                last_updated=datetime.now().isoformat(),
            )
            self._recent_pnls.clear()
            self._save_state()
            logger.info(
                "🔄 Flywheel reset — new epoch %d  (prev net profit $%.2f)",
                self._state.epoch,
                old["net_profit"],
            )
            return old

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def get_report(self) -> str:
        """Return a human-readable flywheel report."""
        with self._lock:
            s = self._state
            tier = self._current_tier()
            nt = self._next_tier_info()
            lines = [
                "",
                "=" * 80,
                "  NIJA PORTFOLIO PROFIT FLYWHEEL REPORT",
                "=" * 80,
                f"  Epoch             : {s.epoch}",
                f"  Epoch Started     : {s.epoch_started}",
                f"  Last Updated      : {s.last_updated}",
                "",
                f"  🌀 FLYWHEEL STATUS",
                "-" * 80,
                f"  Current Tier      : {tier.label}",
                f"  Net Profit        : ${s.net_profit:>14,.2f}",
                f"  Base Capital      : ${s.base_capital:>14,.2f}",
                f"  ROI               : {s.roi_pct:>14.2f} %",
                "",
                f"  ⚙️  COMPOUNDING",
                "-" * 80,
                f"  Tier Compound Rate: {tier.compound_rate * 100:>13.1f} %",
                f"  Effective Rate    : {self._effective_compound_rate() * 100:>13.1f} % "
                  f"(streak bonus: {min(s.current_win_streak * STREAK_BONUS_PER_WIN, MAX_STREAK_BONUS)*100:.1f}%)",
                f"  Compounded Profit : ${s.compounded_profit:>14,.2f}",
                f"  Capital Multiplier: {self.get_capital_multiplier():>14.4f}×",
                "",
                f"  🔄 SPIN METRICS",
                "-" * 80,
                f"  Spin Rate         : ${self._spin_rate():>13.2f} / trade  "
                  f"(last {SPIN_WINDOW} trades)",
                f"  Win Streak        : {s.current_win_streak:>14,} trades",
                f"  Best Streak       : {s.best_win_streak:>14,} trades",
                "",
                f"  📊 TRADING PERFORMANCE",
                "-" * 80,
                f"  Total Trades      : {s.total_trades:>14,}",
                f"  Winning Trades    : {s.winning_trades:>14,}",
                f"  Win Rate          : {s.win_rate:>14.1f} %",
                f"  Gross Profit      : ${s.total_gross_profit:>14,.2f}",
                f"  Gross Loss        : ${s.total_gross_loss:>14,.2f}",
                f"  Profit Factor     : {s.profit_factor:>14.2f}",
                f"  Total Fees        : ${s.total_fees:>14,.2f}",
                "",
                f"  🎯 NEXT MILESTONE",
                "-" * 80,
            ]
            if nt:
                gap = nt["threshold"] - s.net_profit
                lines.append(
                    f"  Next Tier         : {nt['label']}  "
                    f"(need ${gap:,.2f} more  →  compound {nt['compound_rate']*100:.0f}%  "
                    f"×{nt['capital_multiplier']:.2f} size)"
                )
            else:
                lines.append("  🏆 Maximum tier reached — Apex flywheel is spinning!")
            lines += ["=" * 80, ""]
            return "\n".join(lines)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _next_tier_info(self) -> Optional[Dict]:
        """Return info about the next tier milestone, or None if at apex."""
        net = self._state.net_profit
        for tier in self._tiers:
            if net < tier.profit_threshold:
                return {
                    "name":             tier.name,
                    "label":            tier.label,
                    "threshold":        tier.profit_threshold,
                    "compound_rate":    tier.compound_rate,
                    "capital_multiplier": tier.capital_multiplier,
                }
        return None

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save_state(self) -> None:
        try:
            with open(self.STATE_FILE, "w") as f:
                json.dump(self._state.to_dict(), f, indent=2)
        except Exception as exc:
            logger.error("Failed to save flywheel state: %s", exc)

    def _load_state(self) -> bool:
        if not self.STATE_FILE.exists():
            return False
        try:
            with open(self.STATE_FILE, "r") as f:
                data = json.load(f)
            computed = {"net_profit", "win_rate", "profit_factor", "roi_pct"}
            clean = {k: v for k, v in data.items() if k not in computed}
            self._state = FlywheelState(**clean)
            logger.info(
                "✅ Flywheel state loaded (epoch %d  net profit $%.2f)",
                self._state.epoch,
                self._state.net_profit,
            )
            return True
        except Exception as exc:
            logger.warning("Failed to load flywheel state: %s", exc)
            return False


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_flywheel_instance: Optional[PortfolioProfitFlywheel] = None
_flywheel_lock = threading.Lock()


def get_portfolio_profit_flywheel(
    base_capital: float = 0.0,
    tiers: Optional[List[FlywheelTier]] = None,
) -> PortfolioProfitFlywheel:
    """
    Return the global PortfolioProfitFlywheel singleton.

    Creates one on first call; subsequent calls ignore constructor arguments
    (persisted state is authoritative).

    Args:
        base_capital: Starting capital for a fresh state (ignored on reload).
        tiers:        Custom list of FlywheelTier milestones (uses defaults if None).
    """
    global _flywheel_instance
    if _flywheel_instance is None:
        with _flywheel_lock:
            if _flywheel_instance is None:
                _flywheel_instance = PortfolioProfitFlywheel(
                    base_capital=base_capital,
                    tiers=tiers,
                )
    return _flywheel_instance


# ---------------------------------------------------------------------------
# Quick smoke-test / demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import logging as _logging
    _logging.basicConfig(level=_logging.INFO, format="%(levelname)s - %(message)s")

    fw = get_portfolio_profit_flywheel(base_capital=5_000.0)

    demo_trades = [
        ("BTC-USD",  120.50, True,  "ApexTrend",       "BULL_TRENDING"),
        ("ETH-USD",  -35.00, False, "MeanReversion",    "RANGING"),
        ("SOL-USD",   75.00, True,  "MomentumBreakout", "BULL_TRENDING"),
        ("XRP-USD",  -10.00, False, "LiquidityReversal","RANGING"),
        ("DOGE-USD",  55.25, True,  "ApexTrend",        "BULL_TRENDING"),
        ("ADA-USD",   88.00, True,  "ApexTrend",        "BULL_TRENDING"),
        ("AVAX-USD",  42.00, True,  "MomentumBreakout", "BULL_TRENDING"),
        ("LINK-USD", -22.00, False, "MeanReversion",    "BEAR_TRENDING"),
        ("DOT-USD",  200.00, True,  "ApexTrend",        "BULL_TRENDING"),
        ("MATIC-USD", 95.00, True,  "ApexTrend",        "BULL_TRENDING"),
    ]

    for sym, pnl, win, strat, regime in demo_trades:
        result = fw.record_trade(sym, pnl, win, strategy=strat, regime=regime)
        print(
            f"  → tier={result['tier_label']}  mult={result['capital_mult']:.4f}×"
            f"  compound={result['compound_rate']*100:.1f}%"
        )

    print(fw.get_report())
