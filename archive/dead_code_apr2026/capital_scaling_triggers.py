"""
NIJA Capital Scaling Triggers
================================

Monitors rolling **Sharpe ratio** and current **drawdown** to decide when it
is safe — and profitable — to *increase* the total capital deployed by the
bot.

Business logic
--------------

A capital scale-up is *approved* when **all** of the following are true:

0. **Profit Threshold Unlock** — account equity > $150 **OR** the last 10
   consecutive closed trades were all profitable.  This gate prevents
   over-optimisation on small starting capital.
1. Rolling Sharpe ratio ≥ ``sharpe_threshold``  (default 1.5)
2. Current drawdown from peak ≤ ``max_drawdown_pct``  (default 5 %)
3. Cooldown since last scale-up ≥ ``cooldown_trades``  (default 20 trades)
4. The proposed new capital does not exceed ``max_scale_factor × base_capital``
   (default 3.0 ×)

When approved the engine emits a ``ScaleDecision`` carrying the recommended
new capital allocation and records the event to a persistent JSONL audit log.

Architecture
------------
::

    ┌──────────────────────────────────────────────────────────────────┐
    │                  CapitalScalingTrigger                           │
    │                                                                  │
    │  record_trade(pnl_usd, is_win, current_capital)                  │
    │    → updates rolling window                                      │
    │    → re-evaluates trigger conditions                             │
    │    → if ALL pass → emit ScaleDecision, reset cooldown            │
    │                                                                  │
    │  check_triggers(current_capital) → ScaleDecision                 │
    │    → callable ad-hoc (e.g. before each new entry)                │
    │                                                                  │
    │  get_report() → dashboard string                                 │
    └──────────────────────────────────────────────────────────────────┘

Public API
----------
::

    from bot.capital_scaling_triggers import get_capital_scaling_trigger

    trigger = get_capital_scaling_trigger(base_capital=10_000.0)

    # After every closed trade:
    decision = trigger.record_trade(
        pnl_usd=120.0,
        is_win=True,
        current_capital=10_750.0,
    )
    if decision.approved:
        print(f"Scale up to ${decision.recommended_capital:,.0f}!")

    # Or check on-demand before a new entry:
    decision = trigger.check_triggers(current_capital=10_750.0)

    # Full dashboard:
    print(trigger.get_report())

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import json
import logging
import math
import threading
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Deque, Dict, List, Optional

logger = logging.getLogger("nija.capital_scaling_triggers")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_WINDOW: int = 50              # rolling trade window for Sharpe calc
DEFAULT_SHARPE_THRESHOLD: float = 1.5 # minimum Sharpe to approve scale-up
DEFAULT_MAX_DRAWDOWN_PCT: float = 5.0 # maximum drawdown allowed for scale-up
DEFAULT_COOLDOWN_TRADES: int = 20     # minimum trades between scale-ups
DEFAULT_MAX_SCALE_FACTOR: float = 3.0 # cap: never exceed base × this
DEFAULT_SCALE_INCREMENT: float = 0.10 # each approved step adds 10 % of base

# Profit Threshold Unlock — prevents scaling on small / immature accounts
PROFIT_UNLOCK_CAPITAL_THRESHOLD: float = 150.0  # USD: account must exceed this…
PROFIT_UNLOCK_CONSECUTIVE_WINS: int = 10         # …OR achieve this many consecutive wins

# Annualisation constant (crypto trades 365 d/yr)
TRADING_DAYS_PER_YEAR: int = 365

DATA_DIR = Path(__file__).parent.parent / "data"
AUDIT_LOG = DATA_DIR / "capital_scaling_trigger.jsonl"

# ---------------------------------------------------------------------------
# Optional dependency: Global Drawdown Circuit Breaker
#
# When the system-wide drawdown has triggered a HALT, capital scaling must be
# blocked regardless of what the local Sharpe / drawdown metrics say.
# We import lazily to avoid circular dependencies.
# ---------------------------------------------------------------------------

def _get_global_drawdown_cb():  # type: ignore[return]
    """Return the global drawdown circuit breaker singleton, or None."""
    try:
        try:
            from global_drawdown_circuit_breaker import (
                get_global_drawdown_cb,
                ProtectionLevel,
            )
        except ImportError:
            from bot.global_drawdown_circuit_breaker import (
                get_global_drawdown_cb,
                ProtectionLevel,
            )
        return get_global_drawdown_cb(), ProtectionLevel
    except Exception:
        return None, None

# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------


@dataclass
class ScaleDecision:
    """Result of a scaling-trigger evaluation."""

    approved: bool
    reason: str
    current_capital: float
    recommended_capital: float       # == current_capital if not approved
    scale_factor: float              # recommended / base_capital
    sharpe_ratio: float
    drawdown_pct: float
    trades_since_last_scale: int
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass
class TriggerConfig:
    """Configurable thresholds for the scaling trigger."""

    sharpe_threshold: float = DEFAULT_SHARPE_THRESHOLD
    max_drawdown_pct: float = DEFAULT_MAX_DRAWDOWN_PCT
    cooldown_trades: int = DEFAULT_COOLDOWN_TRADES
    max_scale_factor: float = DEFAULT_MAX_SCALE_FACTOR
    scale_increment: float = DEFAULT_SCALE_INCREMENT
    # Profit Threshold Unlock
    profit_unlock_capital: float = PROFIT_UNLOCK_CAPITAL_THRESHOLD
    profit_unlock_consecutive_wins: int = PROFIT_UNLOCK_CONSECUTIVE_WINS


# ---------------------------------------------------------------------------
# Main engine
# ---------------------------------------------------------------------------


class CapitalScalingTrigger:
    """
    Monitors Sharpe ratio and drawdown to decide when to increase deployed
    capital.

    Thread-safe singleton via :func:`get_capital_scaling_trigger`.
    """

    def __init__(
        self,
        base_capital: float,
        config: Optional[TriggerConfig] = None,
        window: int = DEFAULT_WINDOW,
    ) -> None:
        self._lock = threading.Lock()
        self.base_capital = base_capital
        self.config = config or TriggerConfig()
        self.window = window

        # Rolling PnL window (used for Sharpe)
        self._pnl_window: Deque[float] = deque(maxlen=window)

        # Capital tracking (for drawdown)
        self._peak_capital: float = base_capital
        self._current_capital: float = base_capital
        self._current_drawdown_pct: float = 0.0

        # Scale-up state
        self._allocated_capital: float = base_capital
        self._trades_since_last_scale: int = 0
        self._scale_events: List[Dict] = []

        # Profit Threshold Unlock state
        self._consecutive_wins: int = 0

        # Persistence
        DATA_DIR.mkdir(parents=True, exist_ok=True)

        logger.info(
            "✅ CapitalScalingTrigger initialised — base=$%.2f "
            "sharpe≥%.2f drawdown≤%.1f%% unlock>$%.0f|%d consecutive wins",
            base_capital,
            self.config.sharpe_threshold,
            self.config.max_drawdown_pct,
            self.config.profit_unlock_capital,
            self.config.profit_unlock_consecutive_wins,
        )

    # ------------------------------------------------------------------
    # Core: record a trade and auto-evaluate
    # ------------------------------------------------------------------

    def record_trade(
        self,
        pnl_usd: float,
        is_win: bool,
        current_capital: float,
    ) -> ScaleDecision:
        """
        Record a closed trade and immediately evaluate scaling triggers.

        Args:
            pnl_usd:          Realised PnL in USD (positive or negative).
            is_win:           ``True`` if the trade was profitable.
            current_capital:  Total account equity after the trade.

        Returns:
            :class:`ScaleDecision` — check ``.approved`` to act on it.
        """
        with self._lock:
            self._pnl_window.append(pnl_usd)
            self._trades_since_last_scale += 1
            self._update_drawdown(current_capital)
            # Track consecutive wins for the Profit Threshold Unlock gate
            if is_win:
                self._consecutive_wins += 1
            else:
                self._consecutive_wins = 0
            return self._evaluate(current_capital)

    # ------------------------------------------------------------------
    # Core: on-demand trigger check
    # ------------------------------------------------------------------

    def check_triggers(self, current_capital: float) -> ScaleDecision:
        """
        Evaluate scaling triggers without recording a new trade.

        Useful for a periodic health-check at the start of a scan cycle.

        Args:
            current_capital: Current total account equity.

        Returns:
            :class:`ScaleDecision`.
        """
        with self._lock:
            self._update_drawdown(current_capital)
            return self._evaluate(current_capital)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def allocated_capital(self) -> float:
        """The current total capital allocation approved by the trigger."""
        return self._allocated_capital

    @property
    def current_drawdown_pct(self) -> float:
        """Live drawdown percentage from the equity peak."""
        return self._current_drawdown_pct

    @property
    def trades_since_last_scale(self) -> int:
        """Number of trades recorded since the last approved scale-up."""
        return self._trades_since_last_scale

    @property
    def consecutive_wins(self) -> int:
        """Current streak of consecutive profitable trades."""
        return self._consecutive_wins

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _is_scaling_unlocked(self, current_capital: float) -> bool:
        """Return ``True`` if the Profit Threshold Unlock condition is met.

        Scaling is permitted when **either**:
        - the account equity exceeds ``profit_unlock_capital`` ($150 by default), or
        - the trader has recorded ≥ ``profit_unlock_consecutive_wins`` consecutive
          profitable trades (10 by default).

        Must be called while holding ``self._lock``.
        """
        cfg = self.config
        return (
            current_capital > cfg.profit_unlock_capital
            or self._consecutive_wins >= cfg.profit_unlock_consecutive_wins
        )

    def _update_drawdown(self, current_capital: float) -> None:
        """Recompute drawdown from the running peak (must hold lock)."""
        self._current_capital = current_capital
        if current_capital > self._peak_capital:
            self._peak_capital = current_capital
        if self._peak_capital > 0:
            self._current_drawdown_pct = (
                (self._peak_capital - current_capital) / self._peak_capital
            ) * 100.0
        else:
            self._current_drawdown_pct = 0.0

    def _sharpe_ratio(self) -> float:
        """Rolling Sharpe (annualised approximation, must hold lock)."""
        if len(self._pnl_window) < 4:
            return 0.0
        arr = list(self._pnl_window)
        mean = sum(arr) / len(arr)
        variance = sum((x - mean) ** 2 for x in arr) / len(arr)
        std = math.sqrt(variance) if variance > 0 else 1e-9
        scale = math.sqrt(TRADING_DAYS_PER_YEAR / self.window)
        return (mean / std) * scale

    def _evaluate(self, current_capital: float) -> ScaleDecision:
        """
        Core evaluation logic — must be called while holding ``self._lock``.

        Returns a :class:`ScaleDecision`; also commits approved events to
        the audit log and updates ``self._allocated_capital``.
        """
        cfg = self.config
        sharpe = self._sharpe_ratio()
        drawdown = self._current_drawdown_pct
        trades_since = self._trades_since_last_scale

        # ── Gate -1: Global Drawdown Circuit Breaker HALT ──────────────
        # The system-wide drawdown guard ALWAYS wins over local scaling
        # logic.  If the circuit breaker is at HALT (≥ 20 % drawdown),
        # block scaling unconditionally.
        try:
            _cb, _ProtectionLevel = _get_global_drawdown_cb()
            if _cb is not None and _ProtectionLevel is not None:
                if _cb.get_current_level() == _ProtectionLevel.HALT:
                    return ScaleDecision(
                        approved=False,
                        reason=(
                            "Global Drawdown Circuit Breaker is HALT — "
                            "capital scaling blocked until drawdown recovers"
                        ),
                        current_capital=current_capital,
                        recommended_capital=self._allocated_capital,
                        scale_factor=self._allocated_capital / self.base_capital,
                        sharpe_ratio=sharpe,
                        drawdown_pct=drawdown,
                        trades_since_last_scale=trades_since,
                    )
        except Exception as _cb_exc:
            logger.debug("Could not check global drawdown CB: %s", _cb_exc)

        # ── Gate 0: Profit Threshold Unlock ────────────────────────────
        if not self._is_scaling_unlocked(current_capital):
            return ScaleDecision(
                approved=False,
                reason=(
                    f"Scaling locked — account ${current_capital:,.2f} ≤ "
                    f"${cfg.profit_unlock_capital:,.0f} threshold "
                    f"AND only {self._consecutive_wins} / "
                    f"{cfg.profit_unlock_consecutive_wins} consecutive wins"
                ),
                current_capital=current_capital,
                recommended_capital=self._allocated_capital,
                scale_factor=self._allocated_capital / self.base_capital,
                sharpe_ratio=sharpe,
                drawdown_pct=drawdown,
                trades_since_last_scale=trades_since,
            )

        # ── Gate 1: Sharpe ─────────────────────────────────────────────
        if sharpe < cfg.sharpe_threshold:
            return ScaleDecision(
                approved=False,
                reason=f"Sharpe {sharpe:.2f} < threshold {cfg.sharpe_threshold}",
                current_capital=current_capital,
                recommended_capital=self._allocated_capital,
                scale_factor=self._allocated_capital / self.base_capital,
                sharpe_ratio=sharpe,
                drawdown_pct=drawdown,
                trades_since_last_scale=trades_since,
            )

        # ── Gate 2: Drawdown ───────────────────────────────────────────
        if drawdown > cfg.max_drawdown_pct:
            return ScaleDecision(
                approved=False,
                reason=f"Drawdown {drawdown:.2f}% > max {cfg.max_drawdown_pct}%",
                current_capital=current_capital,
                recommended_capital=self._allocated_capital,
                scale_factor=self._allocated_capital / self.base_capital,
                sharpe_ratio=sharpe,
                drawdown_pct=drawdown,
                trades_since_last_scale=trades_since,
            )

        # ── Gate 3: Cooldown ───────────────────────────────────────────
        if trades_since < cfg.cooldown_trades:
            return ScaleDecision(
                approved=False,
                reason=(
                    f"Cooldown: {trades_since} / {cfg.cooldown_trades} "
                    "trades since last scale-up"
                ),
                current_capital=current_capital,
                recommended_capital=self._allocated_capital,
                scale_factor=self._allocated_capital / self.base_capital,
                sharpe_ratio=sharpe,
                drawdown_pct=drawdown,
                trades_since_last_scale=trades_since,
            )

        # ── Gate 4: Max-scale cap ──────────────────────────────────────
        max_capital = self.base_capital * cfg.max_scale_factor
        if self._allocated_capital >= max_capital:
            return ScaleDecision(
                approved=False,
                reason=(
                    f"Already at maximum allocation "
                    f"${self._allocated_capital:,.2f} "
                    f"(cap {cfg.max_scale_factor}× base)"
                ),
                current_capital=current_capital,
                recommended_capital=self._allocated_capital,
                scale_factor=self._allocated_capital / self.base_capital,
                sharpe_ratio=sharpe,
                drawdown_pct=drawdown,
                trades_since_last_scale=trades_since,
            )

        # ── All gates passed → APPROVE ─────────────────────────────────
        increment = self.base_capital * cfg.scale_increment
        new_capital = min(
            self._allocated_capital + increment,
            max_capital,
        )
        new_factor = new_capital / self.base_capital

        decision = ScaleDecision(
            approved=True,
            reason=(
                f"All gates passed — Sharpe={sharpe:.2f} "
                f"drawdown={drawdown:.2f}% "
                f"trades_since={trades_since}"
            ),
            current_capital=current_capital,
            recommended_capital=new_capital,
            scale_factor=new_factor,
            sharpe_ratio=sharpe,
            drawdown_pct=drawdown,
            trades_since_last_scale=trades_since,
        )

        # Commit
        self._allocated_capital = new_capital
        self._trades_since_last_scale = 0
        self._scale_events.append(asdict(decision))

        # Audit log
        try:
            with AUDIT_LOG.open("a") as fh:
                fh.write(json.dumps(asdict(decision)) + "\n")
        except Exception as exc:  # pragma: no cover
            logger.warning("CapitalScalingTrigger: audit log write failed: %s", exc)

        logger.info(
            "🚀 Capital scale-up approved: $%.2f → $%.2f (%.2f× base)",
            current_capital,
            new_capital,
            new_factor,
        )

        return decision

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def get_status(self) -> Dict:
        """Return a concise status dictionary."""
        with self._lock:
            return {
                "base_capital": self.base_capital,
                "allocated_capital": self._allocated_capital,
                "scale_factor": self._allocated_capital / self.base_capital,
                "current_capital": self._current_capital,
                "peak_capital": self._peak_capital,
                "drawdown_pct": round(self._current_drawdown_pct, 3),
                "sharpe_ratio": round(self._sharpe_ratio(), 3),
                "trades_since_last_scale": self._trades_since_last_scale,
                "total_scale_events": len(self._scale_events),
                # Profit Threshold Unlock
                "consecutive_wins": self._consecutive_wins,
                "scaling_unlocked": self._is_scaling_unlocked(self._current_capital),
                "config": {
                    "sharpe_threshold": self.config.sharpe_threshold,
                    "max_drawdown_pct": self.config.max_drawdown_pct,
                    "cooldown_trades": self.config.cooldown_trades,
                    "max_scale_factor": self.config.max_scale_factor,
                    "scale_increment": self.config.scale_increment,
                    "profit_unlock_capital": self.config.profit_unlock_capital,
                    "profit_unlock_consecutive_wins": self.config.profit_unlock_consecutive_wins,
                },
            }

    def get_report(self) -> str:
        """Return a human-readable status report."""
        s = self.get_status()
        unlock_status = "✅ UNLOCKED" if s["scaling_unlocked"] else "🔒 LOCKED"
        lines = [
            "",
            "=" * 65,
            "CAPITAL SCALING TRIGGERS — Status Report",
            "=" * 65,
            f"  Generated          : {datetime.now(timezone.utc).isoformat()}",
            f"  Base Capital       : ${s['base_capital']:>12,.2f}",
            f"  Allocated Capital  : ${s['allocated_capital']:>12,.2f}  "
            f"({s['scale_factor']:.2f}× base)",
            f"  Current Equity     : ${s['current_capital']:>12,.2f}",
            f"  Peak Equity        : ${s['peak_capital']:>12,.2f}",
            "",
            "  — Profit Threshold Unlock —",
            f"  Status             : {unlock_status}",
            f"  Consecutive Wins   : {s['consecutive_wins']:>8d}  "
            f"(need ≥ {s['config']['profit_unlock_consecutive_wins']} OR "
            f"account > ${s['config']['profit_unlock_capital']:,.0f})",
            "",
            "  — Current Metrics —",
            f"  Rolling Sharpe     : {s['sharpe_ratio']:>8.3f}  "
            f"(need ≥ {s['config']['sharpe_threshold']})",
            f"  Drawdown           : {s['drawdown_pct']:>8.3f}%  "
            f"(need ≤ {s['config']['max_drawdown_pct']}%)",
            f"  Trades since scale : {s['trades_since_last_scale']:>8d}  "
            f"(need ≥ {s['config']['cooldown_trades']})",
            "",
            "  — Configuration —",
            f"  Max Scale Factor   : {s['config']['max_scale_factor']:.1f}×",
            f"  Scale Increment    : {s['config']['scale_increment']*100:.0f}% of base per step",
            "",
            f"  Scale-up Events    : {s['total_scale_events']}",
            "=" * 65,
        ]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_INSTANCE: Optional[CapitalScalingTrigger] = None
_INSTANCE_LOCK = threading.Lock()


def get_capital_scaling_trigger(
    base_capital: float = 10_000.0,
    config: Optional[TriggerConfig] = None,
    window: int = DEFAULT_WINDOW,
    reset: bool = False,
) -> CapitalScalingTrigger:
    """
    Return the process-wide :class:`CapitalScalingTrigger` singleton.

    Args:
        base_capital: Starting / reference capital amount.
        config:       Custom :class:`TriggerConfig` (optional).
        window:       Rolling window length for Sharpe calculation.
        reset:        Force re-creation (testing only).
    """
    global _INSTANCE
    with _INSTANCE_LOCK:
        if _INSTANCE is None or reset:
            _INSTANCE = CapitalScalingTrigger(base_capital, config, window)
    return _INSTANCE
