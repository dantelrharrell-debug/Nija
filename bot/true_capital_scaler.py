"""
NIJA True Capital Scaling Engine
=================================

$94 → $1,000+ with structured compounding logic.

Built on top of CapitalLadder, this engine adds:
  1. Session targeting   — rung's ``trades_per_session`` sets the daily entry goal
  2. Reinvestment rule   — 100% of profits stay in play until next rung milestone
  3. Milestone log       — records each rung advancement with timestamp + elapsed days
  4. Projection display  — estimated days to $1 000 at TCS_DAILY_GROWTH_PCT
  5. Integration hook    — ``get_cycle_params(balance)`` feeds into run_cycle() sizing

Configuration (environment variables)
--------------------------------------
  NIJA_TCS_DAILY_GROWTH_PCT   Expected daily growth % for projection (default: 2.5)
  NIJA_TCS_STATE_FILE         Persisted state path (default: data/capital_scaler_state.json)
  NIJA_TCS_ENABLED            Set to "0" to disable (default: "1")

Usage
-----
    from bot.true_capital_scaler import get_true_capital_scaler

    scaler = get_true_capital_scaler()

    # Once per cycle (after balance is fetched):
    params = scaler.get_cycle_params(balance=94.0)
    position_size = balance * params.position_size_pct
    max_positions = params.max_positions

    # After every confirmed trade:
    scaler.record_trade(pnl=2.35, balance=96.35, symbol="ETH-USD")

    # Periodic status (e.g. every 10 cycles):
    scaler.log_status(balance=94.0)

Capital Ladder rungs (from capital_ladder.py)
----------------------------------------------
  SEED    ($15–$49)   : 90% pos · 3.0% TP · 1.5% SL · 1 max pos
  SPROUT  ($50–$99)   : 85% pos · 2.5% TP · 1.25% SL · 1 max pos   ← $94 starts here
  SAPLING ($100–$249) : 70% pos · 2.0% TP · 1.0% SL  · 2 max pos
  TREE    ($250–$499) : 55% pos · 1.8% TP · 0.9% SL  · 3 max pos
  GROVE   ($500–$999) : 45% pos · 1.5% TP · 0.75% SL · 4 max pos
  FOREST  ($1,000+)   : 35% pos · 1.2% TP · 0.6% SL  · 6 max pos   ← target

Author: NIJA Trading Systems
Version: 1.0
Date: April 2026
"""

from __future__ import annotations

import json
import logging
import math
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nija.true_capital_scaler")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

TCS_DAILY_GROWTH_PCT: float = float(os.environ.get("NIJA_TCS_DAILY_GROWTH_PCT", "2.5"))
_STATE_FILE: str = os.environ.get("NIJA_TCS_STATE_FILE", "data/capital_scaler_state.json")
TCS_ENABLED: bool = os.environ.get("NIJA_TCS_ENABLED", "1").strip() not in ("0", "false", "no")

# Milestone target balances (USD)
_MILESTONES: List[float] = [50.0, 100.0, 250.0, 500.0, 1_000.0]

# Default params used when CapitalLadder is unavailable
_FALLBACK_PARAMS: Dict[str, Any] = dict(
    rung_name="UNKNOWN",
    position_size_pct=0.35,
    max_positions=3,
    profit_target_pct=1.5,
    stop_loss_pct=1.0,
    trades_per_session=5,
)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ScalerParams:
    """Trading parameters for the current capital rung."""
    rung_name: str
    balance: float
    position_size_pct: float    # fraction of balance per position (e.g. 0.85 = 85%)
    max_positions: int
    profit_target_pct: float    # % profit target per trade
    stop_loss_pct: float        # % stop loss per trade
    trades_per_session: int     # recommended entries per session
    progress_pct: float         # progress toward next milestone (0–100)
    next_milestone: float       # next target balance in USD
    balance_needed: float       # USD still needed to hit next milestone


@dataclass
class _MilestoneRecord:
    """Record of when a balance milestone was achieved."""
    milestone: float
    balance_at_hit: float
    rung_name: str
    timestamp: str
    days_elapsed: float


@dataclass
class _State:
    """Persisted TCS state."""
    session_start_balance: float = 0.0
    session_trades: int = 0
    session_pnl: float = 0.0
    total_trades: int = 0
    total_pnl: float = 0.0
    peak_balance: float = 0.0
    current_rung: str = "UNKNOWN"
    milestones_hit: List[dict] = field(default_factory=list)
    start_timestamp: str = field(
        default_factory=lambda: datetime.utcnow().isoformat()
    )


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class TrueCapitalScaler:
    """
    True Capital Scaling Engine.

    Wraps CapitalLadder to provide structured compounding from $94 → $1 000+.
    Every cycle the caller queries ``get_cycle_params(balance)`` to receive
    the correct position size, TP, SL, and max positions for the current rung.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._ladder = None          # lazy-loaded CapitalLadder
        self._state = _State()
        self._last_params: Optional[ScalerParams] = None
        self._load_state()
        if TCS_ENABLED:
            logger.info(
                "✅ True Capital Scaling Engine initialized — "
                "target=$1,000  daily_growth_assumption=%.1f%%",
                TCS_DAILY_GROWTH_PCT,
            )
        else:
            logger.info("⏸️  True Capital Scaling Engine DISABLED (NIJA_TCS_ENABLED=0)")

    # ------------------------------------------------------------------
    # Lazy ladder loader
    # ------------------------------------------------------------------

    def _get_ladder(self, balance: float):
        """Lazy-load CapitalLadder with the current balance."""
        if self._ladder is None:
            try:
                from capital_ladder import get_capital_ladder
            except ImportError:
                from bot.capital_ladder import get_capital_ladder
            self._ladder = get_capital_ladder(current_balance=balance)
        return self._ladder

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load_state(self) -> None:
        try:
            p = Path(_STATE_FILE)
            if p.exists():
                with p.open("r") as f:
                    raw = json.load(f)
                valid = {k: v for k, v in raw.items()
                         if k in _State.__dataclass_fields__}
                self._state = _State(**valid)
                logger.debug(
                    "TCS: state loaded — rung=%s  total_trades=%d  total_pnl=$%.2f",
                    self._state.current_rung,
                    self._state.total_trades,
                    self._state.total_pnl,
                )
        except Exception as exc:
            logger.debug("TCS: state load skipped: %s", exc)

    def _save_state(self) -> None:
        try:
            p = Path(_STATE_FILE)
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".tmp")
            with tmp.open("w") as f:
                json.dump(asdict(self._state), f, indent=2)
            tmp.replace(p)
        except Exception as exc:
            logger.debug("TCS: state save failed: %s", exc)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_cycle_params(self, balance: float) -> ScalerParams:
        """
        Return trading parameters for the current capital rung.

        Call once per cycle after the account balance has been fetched.
        The result is also stored as ``self._last_params`` for downstream access.

        Parameters
        ----------
        balance : Current account equity in USD.

        Returns
        -------
        ScalerParams
        """
        if not TCS_ENABLED or balance <= 0:
            return ScalerParams(
                rung_name="DISABLED", balance=balance,
                **_FALLBACK_PARAMS,
                progress_pct=0.0,
                next_milestone=1_000.0,
                balance_needed=max(0.0, 1_000.0 - balance),
            )

        with self._lock:
            try:
                ladder = self._get_ladder(balance)
                rung = ladder.get_current_rung()

                if rung is not None:
                    rung_name = rung.name
                    pos_pct = rung.position_size_pct
                    max_pos = rung.max_positions
                    tp_pct = rung.profit_target_pct
                    sl_pct = rung.stop_loss_pct
                    trades = rung.trades_per_session
                    progress = rung.progress_to_target(balance)
                    next_m = rung.target_balance
                    if next_m == float("inf"):
                        next_m = balance * 10   # top rung: already achieved
                    needed = max(0.0, next_m - balance)
                else:
                    rung_name = "UNKNOWN"
                    pos_pct = _FALLBACK_PARAMS["position_size_pct"]
                    max_pos = _FALLBACK_PARAMS["max_positions"]
                    tp_pct = _FALLBACK_PARAMS["profit_target_pct"]
                    sl_pct = _FALLBACK_PARAMS["stop_loss_pct"]
                    trades = _FALLBACK_PARAMS["trades_per_session"]
                    progress = 0.0
                    next_m = 1_000.0
                    needed = max(0.0, 1_000.0 - balance)

                # Track peak balance
                if balance > self._state.peak_balance:
                    self._state.peak_balance = balance

                # Detect rung advancement
                if rung_name != self._state.current_rung and self._state.current_rung != "UNKNOWN":
                    old_rung = self._state.current_rung
                    self._state.current_rung = rung_name
                    logger.info("=" * 60)
                    logger.info("🏆 CAPITAL LADDER: RUNG ADVANCED!")
                    logger.info("   %s → %s", old_rung, rung_name)
                    logger.info("   Balance : $%.2f", balance)
                    logger.info("   Pos size: %.0f%%", pos_pct * 100)
                    logger.info("   Max pos : %d", max_pos)
                    logger.info("   Target  : $%.2f", next_m)
                    logger.info("=" * 60)
                    self._save_state()
                elif self._state.current_rung == "UNKNOWN":
                    self._state.current_rung = rung_name

                params = ScalerParams(
                    rung_name=rung_name,
                    balance=balance,
                    position_size_pct=pos_pct,
                    max_positions=max_pos,
                    profit_target_pct=tp_pct,
                    stop_loss_pct=sl_pct,
                    trades_per_session=trades,
                    progress_pct=progress,
                    next_milestone=next_m,
                    balance_needed=needed,
                )
                self._last_params = params
                logger.debug(
                    "TCS: rung=%s  pos=%.0f%%  max_pos=%d  "
                    "tp=%.1f%%  sl=%.1f%%  progress=%.1f%%  next=$%.0f",
                    rung_name, pos_pct * 100, max_pos,
                    tp_pct, sl_pct, progress, next_m,
                )
                return params

            except Exception as exc:
                logger.warning("TCS: get_cycle_params error: %s", exc)
                return ScalerParams(
                    rung_name="ERROR", balance=balance,
                    **_FALLBACK_PARAMS,
                    progress_pct=0.0,
                    next_milestone=1_000.0,
                    balance_needed=max(0.0, 1_000.0 - balance),
                )

    def get_current_params(self) -> Optional[ScalerParams]:
        """Return the last params computed by get_cycle_params(), or None."""
        return self._last_params

    def record_trade(
        self,
        pnl: float,
        balance: float,
        symbol: str = "",
    ) -> None:
        """
        Record a completed trade and update ladder + milestone tracking.

        Parameters
        ----------
        pnl     : Profit/loss of the trade in USD (negative = loss).
        balance : Account balance AFTER the trade.
        symbol  : Symbol traded (optional, for logging).
        """
        with self._lock:
            # Session & cumulative counters
            self._state.session_trades += 1
            self._state.session_pnl += pnl
            self._state.total_trades += 1
            self._state.total_pnl += pnl

            # Forward to CapitalLadder
            try:
                ladder = self._get_ladder(balance)
                ladder.record_trade(pnl=pnl, balance=balance)
            except Exception as exc:
                logger.debug("TCS: ladder.record_trade failed: %s", exc)

            # Update peak
            if balance > self._state.peak_balance:
                self._state.peak_balance = balance

            # Milestone detection
            for m in _MILESTONES:
                already_hit = any(
                    rec.get("milestone", 0) >= m
                    for rec in self._state.milestones_hit
                )
                if not already_hit and balance >= m:
                    try:
                        elapsed_days = (
                            datetime.utcnow()
                            - datetime.fromisoformat(self._state.start_timestamp)
                        ).total_seconds() / 86400.0
                    except Exception:
                        elapsed_days = 0.0
                    record = _MilestoneRecord(
                        milestone=m,
                        balance_at_hit=balance,
                        rung_name=self._state.current_rung,
                        timestamp=datetime.utcnow().isoformat(),
                        days_elapsed=float(elapsed_days),
                    )
                    self._state.milestones_hit.append(asdict(record))
                    logger.info("=" * 60)
                    logger.info("🎯 MILESTONE ACHIEVED: $%.0f", m)
                    logger.info("   Balance  : $%.2f", balance)
                    logger.info("   Rung     : %s", self._state.current_rung)
                    logger.info("   Days     : %.0f", elapsed_days)
                    logger.info("=" * 60)

            self._save_state()

        logger.debug(
            "TCS: trade recorded — %s  pnl=%.4f  balance=$%.2f  "
            "session=%d  total_pnl=$%.2f",
            symbol, pnl, balance,
            self._state.session_trades, self._state.total_pnl,
        )

    def get_projection(self, balance: float) -> dict:
        """
        Return a projection dict for dashboard display or log lines.

        Estimates days to $1 000 at TCS_DAILY_GROWTH_PCT using geometric
        compounding: balance × (1 + rate)^n = 1000 → n = log(1000/balance) / log(1+rate).

        Parameters
        ----------
        balance : Current account balance in USD.

        Returns
        -------
        dict with keys: balance, target_1k, current_rung, progress_to_1k_pct,
                        days_to_1k_at_current_rate, assumed_daily_growth_pct,
                        milestones_hit, total_trades, total_pnl_usd.
        """
        if balance <= 0:
            return {}

        target = 1_000.0
        if balance >= target:
            return {
                "balance": balance,
                "target_1k": target,
                "already_achieved": True,
                "milestones_hit": len(self._state.milestones_hit),
                "total_trades": self._state.total_trades,
                "total_pnl_usd": round(self._state.total_pnl, 4),
            }

        rate = TCS_DAILY_GROWTH_PCT / 100.0
        if rate > 0:
            days = math.log(target / balance) / math.log(1.0 + rate)
        else:
            days = float("inf")

        with self._lock:
            return {
                "balance": balance,
                "target_1k": target,
                "current_rung": self._state.current_rung,
                "progress_to_1k_pct": round(min(100.0, balance / target * 100), 2),
                "days_to_1k_at_current_rate": round(days, 1),
                "assumed_daily_growth_pct": TCS_DAILY_GROWTH_PCT,
                "milestones_hit": len(self._state.milestones_hit),
                "total_trades": self._state.total_trades,
                "total_pnl_usd": round(self._state.total_pnl, 4),
            }

    def log_status(self, balance: float) -> None:
        """
        Emit a structured status banner.  Call every N cycles for visibility.
        """
        params = self.get_cycle_params(balance)
        proj = self.get_projection(balance)

        logger.info("=" * 60)
        logger.info("💰 TRUE CAPITAL SCALER STATUS")
        logger.info(
            "   Rung     : %-8s  $%.2f", params.rung_name, balance
        )
        logger.info(
            "   Progress : %.1f%%  →  $%.0f  (need $%.2f)",
            params.progress_pct, params.next_milestone, params.balance_needed,
        )
        logger.info(
            "   Sizing   : %.0f%% / pos · max %d pos · TP %.1f%% · SL %.1f%%",
            params.position_size_pct * 100, params.max_positions,
            params.profit_target_pct, params.stop_loss_pct,
        )
        logger.info(
            "   Session  : %d trades / %d target · P&L $%.2f",
            self._state.session_trades, params.trades_per_session,
            self._state.session_pnl,
        )
        if proj.get("already_achieved"):
            logger.info("   🏆 $1K milestone achieved!")
        else:
            logger.info(
                "   To $1K   : ~%.0f days @ %.1f%%/day  "
                "(%.1f%% complete)",
                proj.get("days_to_1k_at_current_rate", 0),
                TCS_DAILY_GROWTH_PCT,
                proj.get("progress_to_1k_pct", 0),
            )
        logger.info(
            "   All-time : %d trades · P&L $%.2f · peak $%.2f",
            self._state.total_trades, self._state.total_pnl,
            self._state.peak_balance,
        )
        logger.info("=" * 60)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_instance: Optional[TrueCapitalScaler] = None
_singleton_lock = threading.Lock()


def get_true_capital_scaler() -> TrueCapitalScaler:
    """Return the global TrueCapitalScaler singleton."""
    global _instance
    with _singleton_lock:
        if _instance is None:
            _instance = TrueCapitalScaler()
        return _instance
