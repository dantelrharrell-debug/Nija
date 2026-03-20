"""
NIJA Capital Ladder Compounding
================================

A simple but powerful framework for growing small accounts safely without
over-risking.  Quantitative traders use this to compound micro accounts
($15–$1 000+) in a structured, disciplined way.

How it works
------------
Capital is divided into **rungs**, much like a physical ladder:

  Rung 1 — SEED    ($15 – $49)   : 90% position, 3.0% target, 1.5% SL,  1 max pos, 5 trades/session
  Rung 2 — SPROUT  ($50 – $99)   : 85% position, 2.5% target, 1.25% SL, 1 max pos, 6 trades/session
  Rung 3 — SAPLING ($100 – $249) : 70% position, 2.0% target, 1.0% SL,  2 max pos, 6 trades/session
  Rung 4 — TREE    ($250 – $499) : 55% position, 1.8% target, 0.9% SL,  3 max pos, 5 trades/session
  Rung 5 — GROVE   ($500 – $999) : 45% position, 1.5% target, 0.75% SL, 4 max pos, 5 trades/session
  Rung 6 — FOREST  ($1 000+)     : 35% position, 1.2% target, 0.6% SL,  6 max pos, 6 trades/session

Key properties
--------------
* **Floor protection** – once you step onto a rung the engine sets a balance
  floor at that rung's ``entry_balance``.  Drawdowns cannot pull you back to a
  lower rung mid-session; the floor only resets at the start of a new session.
* **Rung advancement** – every time a rung boundary is crossed upward the new
  (higher) floor is committed and the richer rung parameters take effect
  immediately.
* **Concentrated bets** – each rung's ``position_size_pct`` is deliberately
  large so that a small number of quality trades (3–5 on the lower rungs)
  compound capital meaningfully without fragmenting into dozens of tiny trades.
* **Transparent status** – ``get_status()`` / ``get_ladder_summary()`` expose
  all metrics needed for dashboard display or log lines.

Quick start
-----------
::

    from capital_ladder import get_capital_ladder

    ladder = get_capital_ladder(current_balance=43.0)
    params = ladder.get_trading_params()   # position size, targets, …

    # After each trade:
    ladder.record_trade(pnl=1.29, balance=44.29)

    print(ladder.get_ladder_summary())

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger("nija.capital_ladder")


# ---------------------------------------------------------------------------
# Rung definition
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LadderRung:
    """
    One rung of the capital ladder.

    Attributes:
        name:              Human-readable rung name (e.g. ``"SEED"``).
        entry_balance:     Minimum balance required to occupy this rung (USD).
        target_balance:    Balance at which the next rung is unlocked (USD).
        position_size_pct: Fraction of tradeable capital to deploy per trade
                           (e.g. ``0.80`` = 80 %).
        profit_target_pct: Base profit-target per trade as a percentage of
                           entry price (e.g. ``3.0`` = 3 %).
        stop_loss_pct:     Stop-loss per trade as a percentage of entry price
                           (e.g. ``1.5`` = 1.5 %).  Maintained at ≈ 2 : 1 R:R.
        max_positions:     Maximum concurrent open positions on this rung.
        trades_per_session: Recommended number of high-conviction trades per session.
                           This is a guideline to maintain focus, not a hard cap enforced
                           by the engine. The per-symbol cooldown (MICRO_CAP_TRADE_COOLDOWN)
                           controls actual re-entry frequency independently.
    """
    name: str
    entry_balance: float
    target_balance: float          # float('inf') for the top rung
    position_size_pct: float       # 0.0 – 1.0
    profit_target_pct: float       # e.g. 3.0  (percentage points)
    stop_loss_pct: float           # e.g. 1.5  (percentage points)
    max_positions: int
    trades_per_session: int

    @property
    def risk_reward_ratio(self) -> float:
        """Reward-to-risk ratio (profit target / stop loss)."""
        return self.profit_target_pct / self.stop_loss_pct if self.stop_loss_pct else 0.0

    @property
    def has_next_rung(self) -> bool:
        """False only for the top (FOREST) rung."""
        return self.target_balance != float("inf")

    def progress_to_target(self, balance: float) -> float:
        """
        Percentage progress from this rung's entry toward its target (0–100).

        Returns 100.0 once *balance* meets or exceeds *target_balance*.
        """
        if not self.has_next_rung:
            return 100.0
        span = self.target_balance - self.entry_balance
        if span <= 0:
            return 100.0
        return min(100.0, max(0.0, (balance - self.entry_balance) / span * 100.0))

    def balance_to_next_rung(self, balance: float) -> float:
        """USD still needed to reach the next rung (0 when already there)."""
        if not self.has_next_rung:
            return 0.0
        return max(0.0, self.target_balance - balance)


# ---------------------------------------------------------------------------
# The ladder — ordered from lowest to highest
# ---------------------------------------------------------------------------

LADDER_RUNGS: List[LadderRung] = [
    # Rung 1 — SEED: $15–$49
    # Absolute concentration: one trade at a time, 90% of capital, 3% target.
    # Mirrors the micro-cap compounding mode settings.
    LadderRung(
        name="SEED",
        entry_balance=15.0,
        target_balance=50.0,
        position_size_pct=0.90,
        profit_target_pct=3.0,
        stop_loss_pct=1.5,
        max_positions=1,
        trades_per_session=5,
    ),
    # Rung 2 — SPROUT: $50–$99
    # Still highly concentrated; matches SEED sizing to maximise compounding speed.
    LadderRung(
        name="SPROUT",
        entry_balance=50.0,
        target_balance=100.0,
        position_size_pct=0.85,
        profit_target_pct=2.5,
        stop_loss_pct=1.25,
        max_positions=1,
        trades_per_session=6,
    ),
    # Rung 3 — SAPLING: $100–$249
    # Two positions allowed; fee drag drops, so target can relax further.
    LadderRung(
        name="SAPLING",
        entry_balance=100.0,
        target_balance=250.0,
        position_size_pct=0.70,
        profit_target_pct=2.0,
        stop_loss_pct=1.0,
        max_positions=2,
        trades_per_session=6,
    ),
    # Rung 4 — TREE: $250–$499
    # Begin diversifying; meaningful capital per position ($50–$80+).
    LadderRung(
        name="TREE",
        entry_balance=250.0,
        target_balance=500.0,
        position_size_pct=0.55,
        profit_target_pct=1.8,
        stop_loss_pct=0.9,
        max_positions=3,
        trades_per_session=5,
    ),
    # Rung 5 — GROVE: $500–$999
    # Approaching standard account territory; balance diversification and size.
    LadderRung(
        name="GROVE",
        entry_balance=500.0,
        target_balance=1_000.0,
        position_size_pct=0.45,
        profit_target_pct=1.5,
        stop_loss_pct=0.75,
        max_positions=4,
        trades_per_session=5,
    ),
    # Rung 6 — FOREST: $1 000+
    # Hands off to the higher-tier CompoundingEngine; ladder is complete.
    LadderRung(
        name="FOREST",
        entry_balance=1_000.0,
        target_balance=float("inf"),
        position_size_pct=0.35,
        profit_target_pct=1.2,
        stop_loss_pct=0.6,
        max_positions=6,
        trades_per_session=6,
    ),
]

# Quick lookup: entry balance → rung (sorted ascending)
_RUNGS_BY_ENTRY: List[LadderRung] = sorted(LADDER_RUNGS, key=lambda r: r.entry_balance)


# ---------------------------------------------------------------------------
# Trade record
# ---------------------------------------------------------------------------

@dataclass
class _TradeRecord:
    """Lightweight per-trade record stored by CapitalLadder."""
    timestamp: str
    rung_name: str
    pnl: float
    balance_after: float


# ---------------------------------------------------------------------------
# Capital Ladder engine
# ---------------------------------------------------------------------------

class CapitalLadder:
    """
    Capital Ladder Compounding engine for micro/small accounts ($15–$1 000+).

    Usage::

        ladder = CapitalLadder(initial_balance=43.0)
        params = ladder.get_trading_params()
        ladder.record_trade(pnl=-0.65, balance=42.35)
        ladder.record_trade(pnl=1.30,  balance=43.65)
        print(ladder.get_ladder_summary())
    """

    def __init__(self, initial_balance: float) -> None:
        """
        Initialise the ladder.

        Args:
            initial_balance: Current account balance in USD used to determine
                             the starting rung and set the initial floor.
        """
        self._trades: List[_TradeRecord] = []
        self._session_start = datetime.utcnow().isoformat()

        # Resolve starting rung and set floor
        starting_rung = self._resolve_rung(initial_balance)
        self._floor: float = starting_rung.entry_balance
        self._rung_name: str = starting_rung.name
        self._balance: float = initial_balance

        logger.info("=" * 65)
        logger.info("🪜  Capital Ladder Compounding — Initialised")
        logger.info("=" * 65)
        logger.info("  Starting balance : $%.2f", initial_balance)
        logger.info("  Current rung     : %s (%s)", starting_rung.name,
                    self._rung_range_str(starting_rung))
        logger.info("  Floor            : $%.2f", self._floor)
        logger.info("  Position size    : %.0f%%", starting_rung.position_size_pct * 100)
        logger.info("  Profit target    : %.1f%%", starting_rung.profit_target_pct)
        logger.info("  Stop loss        : %.2f%%", starting_rung.stop_loss_pct)
        logger.info("  Max positions    : %d", starting_rung.max_positions)
        logger.info("  Trades/session   : %d", starting_rung.trades_per_session)
        logger.info("  To next rung     : $%.2f",
                    starting_rung.balance_to_next_rung(initial_balance))
        logger.info("=" * 65)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def current_rung(self) -> LadderRung:
        """The rung the account currently occupies."""
        return self._get_rung_by_name(self._rung_name)

    @property
    def floor(self) -> float:
        """Protective balance floor — the account never trades below this."""
        return self._floor

    def get_trading_params(self) -> Dict:
        """
        Return a ready-to-use dict of trading parameters for the current rung.

        The dict is compatible with the keys expected by ``trading_strategy.py``
        and ``micro_capital_config.py``.

        Returns::

            {
                'rung_name':          str,    # e.g. 'SEED'
                'position_size_pct':  float,  # e.g. 0.80
                'profit_target_pct':  float,  # e.g. 3.0
                'stop_loss_pct':      float,  # e.g. 1.5
                'max_positions':      int,
                'trades_per_session': int,
                'floor':              float,
                'balance':            float,
                'progress_pct':       float,  # 0–100 toward next rung
                'balance_to_next':    float,  # USD to next rung
            }
        """
        rung = self.current_rung
        return {
            "rung_name": rung.name,
            "position_size_pct": rung.position_size_pct,
            "profit_target_pct": rung.profit_target_pct,
            "stop_loss_pct": rung.stop_loss_pct,
            "max_positions": rung.max_positions,
            "trades_per_session": rung.trades_per_session,
            "floor": self._floor,
            "balance": self._balance,
            "progress_pct": rung.progress_to_target(self._balance),
            "balance_to_next": rung.balance_to_next_rung(self._balance),
        }

    def record_trade(self, pnl: float, balance: float) -> Dict:
        """
        Record a completed trade and update the ladder state.

        If *balance* crosses into a higher rung the floor is advanced and the
        new rung's parameters take effect.  The floor **never moves down**.

        Args:
            pnl:     Net profit/loss of the trade in USD.
            balance: Account balance **after** the trade settles.

        Returns:
            Dict with ``rung_changed`` flag and ``new_rung`` / ``old_rung``
            keys when a rung advancement occurs.
        """
        old_rung_name = self._rung_name
        self._balance = balance

        # Check for rung advancement
        new_rung = self._resolve_rung(balance)
        rung_changed = new_rung.name != old_rung_name

        if rung_changed and new_rung.entry_balance > self._floor:
            self._floor = new_rung.entry_balance
            self._rung_name = new_rung.name
            logger.info(
                "🚀 RUNG ADVANCED: %s → %s | balance=$%.2f | floor=$%.2f",
                old_rung_name, new_rung.name, balance, self._floor,
            )

        # Persist trade record
        self._trades.append(_TradeRecord(
            timestamp=datetime.utcnow().isoformat(),
            rung_name=self._rung_name,
            pnl=pnl,
            balance_after=balance,
        ))

        result: Dict = {
            "rung_changed": rung_changed,
            "current_rung": self._rung_name,
        }
        if rung_changed:
            result["old_rung"] = old_rung_name
            result["new_rung"] = self._rung_name
            result["new_floor"] = self._floor

        return result

    def get_status(self) -> Dict:
        """
        Return a comprehensive status dictionary for dashboard / logging.

        Keys
        ----
        balance, floor, rung_name, rung_index, total_rungs,
        progress_pct, balance_to_next_rung, target_balance,
        position_size_pct, profit_target_pct, stop_loss_pct,
        risk_reward_ratio, max_positions, trades_per_session,
        session_trades, session_pnl, session_wins, session_losses,
        win_rate_pct, session_start.
        """
        rung = self.current_rung
        rung_index = next(
            (i for i, r in enumerate(_RUNGS_BY_ENTRY) if r.name == rung.name), 0
        )
        session_pnl = sum(t.pnl for t in self._trades)
        wins = sum(1 for t in self._trades if t.pnl > 0)
        losses = sum(1 for t in self._trades if t.pnl <= 0)
        total_trades = len(self._trades)

        return {
            "balance": self._balance,
            "floor": self._floor,
            "rung_name": rung.name,
            "rung_index": rung_index + 1,
            "total_rungs": len(_RUNGS_BY_ENTRY),
            "progress_pct": rung.progress_to_target(self._balance),
            "balance_to_next_rung": rung.balance_to_next_rung(self._balance),
            "target_balance": rung.target_balance,
            "position_size_pct": rung.position_size_pct,
            "profit_target_pct": rung.profit_target_pct,
            "stop_loss_pct": rung.stop_loss_pct,
            "risk_reward_ratio": rung.risk_reward_ratio,
            "max_positions": rung.max_positions,
            "trades_per_session": rung.trades_per_session,
            "session_trades": total_trades,
            "session_pnl": round(session_pnl, 4),
            "session_wins": wins,
            "session_losses": losses,
            "win_rate_pct": round(wins / total_trades * 100, 1) if total_trades else 0.0,
            "session_start": self._session_start,
        }

    def get_ladder_summary(self) -> str:
        """
        Return a formatted, human-readable ladder summary for logging / CLI.

        Example output::

            ╔══════════════════════════════════════════════════════════╗
            ║         🪜  CAPITAL LADDER — RUNG 1 / 6 (SEED)          ║
            ╠══════════════════════════════════════════════════════════╣
            ║  Balance  : $43.00     Floor : $15.00                   ║
            ║  Progress : ▓▓▓▓▓░░░░░░░░░░░░░░░░  14.3%  ($7.00 left) ║
            ║  Next rung: SPROUT at $50.00                            ║
            ╠══════════════════════════════════════════════════════════╣
            ║  Position : 80%    Target: 3.0%    Stop: 1.5% (2.0R:R) ║
            ║  Max pos  : 1      Trades/session: 3                    ║
            ╠══════════════════════════════════════════════════════════╣
            ║  Session  : 0 trades | P&L $0.00 | Win rate: 0%        ║
            ╚══════════════════════════════════════════════════════════╝
        """
        s = self.get_status()
        rung = self.current_rung
        bar = self._progress_bar(s["progress_pct"])
        # Use the 0-based rung_index to look up the *next* rung safely.
        # s['rung_index'] is 1-based, so the 0-based index of the current rung
        # is s['rung_index'] - 1, and the next rung is at s['rung_index'].
        # This branch is only reached when rung.has_next_rung is True, so the
        # index is guaranteed to be within bounds (max = len - 1 = 5).
        next_str: str
        if rung.has_next_rung:
            next_rung = _RUNGS_BY_ENTRY[s["rung_index"]]  # 0-based next rung
            next_str = f"NEXT: {next_rung.name} at ${rung.target_balance:,.0f}"
        else:
            next_str = "TOP RUNG REACHED 🏆"
        lines = [
            "╔" + "═" * 58 + "╗",
            f"║  🪜  CAPITAL LADDER — RUNG {s['rung_index']}/{s['total_rungs']} ({s['rung_name']})"
            .ljust(59) + "║",
            "╠" + "═" * 58 + "╣",
            f"║  Balance  : ${s['balance']:>8,.2f}     Floor : ${s['floor']:>8,.2f}  ║",
            f"║  Progress : {bar}  {s['progress_pct']:5.1f}%  (${s['balance_to_next_rung']:.2f} left)  ║",
            f"║  {next_str}".ljust(59) + "║",
            "╠" + "═" * 58 + "╣",
            (
                f"║  Position : {s['position_size_pct']*100:.0f}%"
                f"    Target: {s['profit_target_pct']:.1f}%"
                f"    Stop: {s['stop_loss_pct']:.2f}%"
                f" ({s['risk_reward_ratio']:.1f}R:R)"
            ).ljust(59) + "║",
            (
                f"║  Max pos  : {s['max_positions']}"
                f"      Trades/session: {s['trades_per_session']}"
            ).ljust(59) + "║",
            "╠" + "═" * 58 + "╣",
            (
                f"║  Session  : {s['session_trades']} trades"
                f" | P&L ${s['session_pnl']:+.2f}"
                f" | Win rate: {s['win_rate_pct']:.0f}%"
            ).ljust(59) + "║",
            "╚" + "═" * 58 + "╝",
        ]
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_rung(balance: float) -> LadderRung:
        """Return the highest rung whose entry_balance ≤ balance."""
        eligible = [r for r in _RUNGS_BY_ENTRY if balance >= r.entry_balance]
        if not eligible:
            # Balance below the first rung — return SEED as a safe default
            return _RUNGS_BY_ENTRY[0]
        return eligible[-1]

    @staticmethod
    def _get_rung_by_name(name: str) -> LadderRung:
        for r in _RUNGS_BY_ENTRY:
            if r.name == name:
                return r
        return _RUNGS_BY_ENTRY[0]

    @staticmethod
    def _rung_range_str(rung: LadderRung) -> str:
        if rung.has_next_rung:
            return f"${rung.entry_balance:,.0f}–${rung.target_balance:,.0f}"
        return f"${rung.entry_balance:,.0f}+"

    @staticmethod
    def _progress_bar(pct: float, width: int = 10) -> str:
        filled = int(round(pct / 100 * width))
        return "▓" * filled + "░" * (width - filled)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_ladder_instance: Optional[CapitalLadder] = None


def get_capital_ladder(balance: float = 0.0) -> CapitalLadder:
    """
    Return (or create) the shared :class:`CapitalLadder` singleton.

    On first call *balance* is used to set the starting rung.  Subsequent
    calls ignore *balance* and return the existing instance so the ladder's
    state (trades, floor, rung) persists across the session.

    Args:
        balance: Current account balance in USD (used only on first call).

    Returns:
        The singleton :class:`CapitalLadder` instance.
    """
    global _ladder_instance
    if _ladder_instance is None:
        _ladder_instance = CapitalLadder(initial_balance=balance)
    return _ladder_instance


def reset_capital_ladder() -> None:
    """
    Destroy the singleton so the next :func:`get_capital_ladder` call
    creates a fresh instance.  Useful between trading sessions or in tests.
    """
    global _ladder_instance
    _ladder_instance = None
