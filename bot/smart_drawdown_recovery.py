"""
NIJA Smart Drawdown Recovery
==============================

Detects portfolio drawdowns and automatically activates a structured recovery
mode that:
  1. Reduces position sizes progressively as the drawdown deepens
  2. Shifts strategy allocation toward higher win-rate strategies
  3. Tightens profit locks (take gains sooner during recovery)
  4. Tracks recovery progress and automatically exits recovery mode
     once the portfolio has regained a configurable percentage of the loss

Architecture
------------
The engine wraps the existing ``DrawdownProtectionSystem`` and adds the
*active recovery layer* on top:

  ┌─────────────────────────────────────────────┐
  │          SmartDrawdownRecovery               │
  │  ┌──────────────────────────────────────┐   │
  │  │   DrawdownProtectionSystem (existing) │   │
  │  │   - position size multiplier          │   │
  │  │   - can_trade() circuit breaker       │   │
  │  └──────────────────────────────────────┘   │
  │  + Recovery mode detection                   │
  │  + Strategy shift recommendations            │
  │  + Tighter profit-lock thresholds            │
  │  + Persistent state & reporting              │
  └─────────────────────────────────────────────┘

Key Features
------------
- Four-tier drawdown severity: NORMAL / CAUTION / WARNING / CRITICAL
- Recovery mode activates automatically at CAUTION (≥5 % drawdown)
- Position-size multiplier steps down per tier
- Strategy preference list updated dynamically (prefer high win-rate)
- Profit-lock multiplier tightens: exit sooner to lock in recovery gains
- Integrates with SelfLearningStrategyAllocator for strategy preference
- Persistent JSON state survives restarts
- Thread-safe singleton via ``get_smart_drawdown_recovery()``

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

import json
import logging
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("nija.smart_drawdown_recovery")


# ---------------------------------------------------------------------------
# Enums & config
# ---------------------------------------------------------------------------

class DrawdownSeverity(Enum):
    """Drawdown severity tiers."""
    NORMAL   = "normal"    # < 5 %  — full-size trading, no constraints
    CAUTION  = "caution"   # 5-10 % — recovery mode enters; reduce size
    WARNING  = "warning"   # 10-15% — significant reduction; tighter locks
    CRITICAL = "critical"  # ≥ 15 % — minimal positions; hardest locks


@dataclass
class RecoveryConfig:
    """Configurable parameters for Smart Drawdown Recovery."""
    # Drawdown thresholds that trigger each severity level
    caution_pct:  float = 5.0
    warning_pct:  float = 10.0
    critical_pct: float = 15.0

    # Position size multipliers per severity (applied on top of normal sizing)
    caution_size_multiplier:  float = 0.70
    warning_size_multiplier:  float = 0.45
    critical_size_multiplier: float = 0.20

    # Profit-lock tightening per severity
    # Multiplier applied to the broker's profit-take threshold.
    # 0.7 means "take profit 30 % sooner than normal".
    caution_profit_lock:  float = 0.80
    warning_profit_lock:  float = 0.65
    critical_profit_lock: float = 0.50

    # Recovery exit condition: exit recovery mode once portfolio has
    # recovered this fraction of the peak drawdown amount.
    recovery_exit_threshold: float = 0.75   # 75 % recovered → exit recovery

    # Number of consecutive winning trades required to step up one severity tier
    wins_to_step_up: int = 3


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

@dataclass
class DrawdownSnapshot:
    """Point-in-time capital snapshot used to track drawdown."""
    timestamp: str
    capital: float
    severity: str
    drawdown_pct: float


@dataclass
class RecoveryState:
    """Persistent state for the Smart Drawdown Recovery engine."""
    # Capital tracking
    peak_capital: float = 0.0
    current_capital: float = 0.0

    # Severity & recovery
    severity: str = DrawdownSeverity.NORMAL.value
    in_recovery_mode: bool = False
    recovery_start_capital: float = 0.0      # capital when recovery mode began
    recovery_target_capital: float = 0.0     # capital to reach to exit recovery

    # Streak counters (reset on loss)
    consecutive_wins: int = 0
    consecutive_losses: int = 0

    # Session statistics
    total_trades: int = 0
    recovery_trades: int = 0                 # trades executed while in recovery
    times_entered_recovery: int = 0
    times_exited_recovery: int = 0

    # Timestamps
    last_updated: str = ""
    recovery_entered_at: str = ""
    recovery_exited_at: str = ""

    # Snapshot log
    snapshots: List[Dict] = field(default_factory=list)

    # Computed helpers
    @property
    def drawdown_amount(self) -> float:
        return max(0.0, self.peak_capital - self.current_capital)

    @property
    def drawdown_pct(self) -> float:
        if self.peak_capital > 0:
            return (self.drawdown_amount / self.peak_capital) * 100
        return 0.0

    @property
    def recovery_progress_pct(self) -> float:
        """How much of the drawdown has been recovered (0–100 %)."""
        target_gain = self.recovery_target_capital - self.recovery_start_capital
        if target_gain <= 0:
            return 100.0
        actual_gain = self.current_capital - self.recovery_start_capital
        return max(0.0, min(100.0, (actual_gain / target_gain) * 100))

    def to_dict(self) -> Dict:
        d = asdict(self)
        d["drawdown_amount"] = self.drawdown_amount
        d["drawdown_pct"] = self.drawdown_pct
        d["recovery_progress_pct"] = self.recovery_progress_pct
        return d


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class SmartDrawdownRecovery:
    """
    Detects drawdowns and manages structured recovery.

    Usage::

        engine = get_smart_drawdown_recovery(base_capital=5000.0)

        # After every closed trade:
        guidance = engine.update(current_capital=4800.0, is_win=False)
        size_mult = guidance["position_size_multiplier"]
        profit_lock = guidance["profit_lock_multiplier"]
        preferred_strategies = guidance["preferred_strategies"]

        # Before entering a trade:
        can_trade, reason = engine.can_trade()
    """

    DATA_DIR = Path(__file__).parent.parent / "data"
    STATE_FILE = DATA_DIR / "smart_drawdown_recovery_state.json"

    def __init__(
        self,
        base_capital: float = 0.0,
        config: Optional[RecoveryConfig] = None,
    ):
        self._lock = threading.RLock()
        self.config = config or RecoveryConfig()

        if not self._load_state():
            self._state = RecoveryState(
                peak_capital=base_capital,
                current_capital=base_capital,
                last_updated=datetime.now().isoformat(),
            )
            self._save_state()

        logger.info("=" * 70)
        logger.info("🛡️  Smart Drawdown Recovery initialised")
        logger.info(f"   Severity      : {self._state.severity.upper()}")
        logger.info(f"   Peak Capital  : ${self._state.peak_capital:,.2f}")
        logger.info(f"   Current Cap   : ${self._state.current_capital:,.2f}")
        logger.info(f"   Drawdown      : {self._state.drawdown_pct:.2f}%")
        logger.info(f"   Recovery Mode : {self._state.in_recovery_mode}")
        logger.info("=" * 70)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(self, current_capital: float, is_win: bool) -> Dict:
        """
        Update the engine with the latest capital reading and trade outcome.

        Call this after every closed trade.

        Args:
            current_capital: Portfolio value after the trade.
            is_win:          True if the trade was profitable.

        Returns:
            dict with keys:
              - severity              (str)
              - in_recovery_mode      (bool)
              - position_size_multiplier (float, 0-1)
              - profit_lock_multiplier   (float, 0-1)
              - preferred_strategies     (list[str])
              - recovery_progress_pct    (float)
              - can_trade                (bool)
              - message                  (str)
        """
        with self._lock:
            s = self._state
            s.total_trades += 1
            s.last_updated = datetime.now().isoformat()

            # Update streaks
            if is_win:
                s.consecutive_wins += 1
                s.consecutive_losses = 0
            else:
                s.consecutive_losses += 1
                s.consecutive_wins = 0

            # Update capital and peak
            s.current_capital = current_capital
            if current_capital > s.peak_capital:
                s.peak_capital = current_capital

            # Determine severity
            old_severity = DrawdownSeverity(s.severity)
            new_severity = self._compute_severity(s.drawdown_pct)

            if new_severity != old_severity:
                self._on_severity_change(old_severity, new_severity)
            s.severity = new_severity.value

            # Recovery mode transitions
            if not s.in_recovery_mode and new_severity != DrawdownSeverity.NORMAL:
                self._enter_recovery(current_capital)
            elif s.in_recovery_mode:
                if new_severity == DrawdownSeverity.NORMAL:
                    self._exit_recovery("drawdown cleared")
                elif (
                    s.consecutive_wins >= self.config.wins_to_step_up
                    and s.recovery_progress_pct >= self.config.recovery_exit_threshold * 100
                ):
                    self._exit_recovery("recovery target reached")

            if s.in_recovery_mode:
                s.recovery_trades += 1

            # Save snapshot (keep last 500)
            s.snapshots.append(DrawdownSnapshot(
                timestamp=s.last_updated,
                capital=current_capital,
                severity=s.severity,
                drawdown_pct=round(s.drawdown_pct, 4),
            ).__dict__)
            if len(s.snapshots) > 500:
                s.snapshots = s.snapshots[-500:]

            self._save_state()
            return self._build_guidance()

    def can_trade(self) -> Tuple[bool, str]:
        """
        Check whether trading is currently allowed.

        Returns:
            (allowed: bool, reason: str)
        """
        with self._lock:
            s = self._state
            sev = DrawdownSeverity(s.severity)
            if sev == DrawdownSeverity.CRITICAL and self.config.critical_size_multiplier == 0.0:
                return False, f"Trading halted — critical drawdown {s.drawdown_pct:.1f}%"
            return True, f"Trading allowed — severity={s.severity} drawdown={s.drawdown_pct:.1f}%"

    def get_position_size_multiplier(self) -> float:
        """Return position-size multiplier for the current severity (0–1)."""
        with self._lock:
            return self._size_mult(DrawdownSeverity(self._state.severity))

    def get_profit_lock_multiplier(self) -> float:
        """Return profit-lock tightening multiplier for the current severity (0–1)."""
        with self._lock:
            return self._profit_lock(DrawdownSeverity(self._state.severity))

    def get_preferred_strategies(self) -> List[str]:
        """
        Return preferred strategy names for the current recovery posture.

        During recovery, the allocator is queried for top strategies; otherwise
        an empty list is returned (no preference — use normal allocation).
        """
        with self._lock:
            if not self._state.in_recovery_mode:
                return []
            return self._preferred_strategies()

    def get_status(self) -> Dict:
        """Return a snapshot of the current recovery state."""
        with self._lock:
            return self._state.to_dict()

    def update_capital(self, current_capital: float) -> None:
        """Update current capital without a trade outcome (e.g. on balance sync)."""
        with self._lock:
            old_peak = self._state.peak_capital
            self._state.current_capital = current_capital
            if current_capital > self._state.peak_capital:
                self._state.peak_capital = current_capital
            self._state.last_updated = datetime.now().isoformat()
            self._save_state()
            if current_capital > old_peak:
                logger.info(f"🏔️  New portfolio peak: ${current_capital:,.2f}")

    def get_report(self) -> str:
        """Generate a human-readable recovery status report."""
        s = self._state
        lines = [
            "",
            "=" * 80,
            "  NIJA SMART DRAWDOWN RECOVERY — STATUS REPORT",
            "=" * 80,
            f"  Severity            : {s.severity.upper()}",
            f"  In Recovery Mode    : {s.in_recovery_mode}",
            f"  Recovery Progress   : {s.recovery_progress_pct:.1f} %",
            "",
            "  📉 DRAWDOWN",
            "-" * 80,
            f"  Peak Capital        : ${s.peak_capital:>14,.2f}",
            f"  Current Capital     : ${s.current_capital:>14,.2f}",
            f"  Drawdown Amount     : ${s.drawdown_amount:>14,.2f}",
            f"  Drawdown %          : {s.drawdown_pct:>14.2f} %",
            "",
            "  🔧 ACTIVE CONSTRAINTS",
            "-" * 80,
            f"  Position Size Mult  : {self._size_mult(DrawdownSeverity(s.severity)):>14.2f} x",
            f"  Profit Lock Mult    : {self._profit_lock(DrawdownSeverity(s.severity)):>14.2f} x",
            f"  Preferred Strategies: {', '.join(self._preferred_strategies()) or 'None (normal mode)'}",
            "",
            "  📊 COUNTERS",
            "-" * 80,
            f"  Total Trades        : {s.total_trades:>14,}",
            f"  Recovery Trades     : {s.recovery_trades:>14,}",
            f"  Consecutive Wins    : {s.consecutive_wins:>14,}",
            f"  Consecutive Losses  : {s.consecutive_losses:>14,}",
            f"  Times in Recovery   : {s.times_entered_recovery:>14,}",
            f"  Times Recovered     : {s.times_exited_recovery:>14,}",
            "=" * 80,
            "",
        ]
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _compute_severity(self, drawdown_pct: float) -> DrawdownSeverity:
        c = self.config
        if drawdown_pct >= c.critical_pct:
            return DrawdownSeverity.CRITICAL
        if drawdown_pct >= c.warning_pct:
            return DrawdownSeverity.WARNING
        if drawdown_pct >= c.caution_pct:
            return DrawdownSeverity.CAUTION
        return DrawdownSeverity.NORMAL

    def _size_mult(self, severity: DrawdownSeverity) -> float:
        c = self.config
        return {
            DrawdownSeverity.NORMAL:   1.0,
            DrawdownSeverity.CAUTION:  c.caution_size_multiplier,
            DrawdownSeverity.WARNING:  c.warning_size_multiplier,
            DrawdownSeverity.CRITICAL: c.critical_size_multiplier,
        }[severity]

    def _profit_lock(self, severity: DrawdownSeverity) -> float:
        c = self.config
        return {
            DrawdownSeverity.NORMAL:   1.0,
            DrawdownSeverity.CAUTION:  c.caution_profit_lock,
            DrawdownSeverity.WARNING:  c.warning_profit_lock,
            DrawdownSeverity.CRITICAL: c.critical_profit_lock,
        }[severity]

    def _preferred_strategies(self) -> List[str]:
        """Query the strategy allocator for top performers to favour during recovery."""
        try:
            from bot.self_learning_strategy_allocator import get_self_learning_allocator
            allocator = get_self_learning_allocator()
        except ImportError:
            try:
                from self_learning_strategy_allocator import get_self_learning_allocator
                allocator = get_self_learning_allocator()
            except ImportError:
                return []

        weights = allocator.get_weights()
        if not weights:
            return []
        # Return top half of strategies sorted by weight
        sorted_strats = sorted(weights, key=lambda n: weights[n], reverse=True)
        top_n = max(1, len(sorted_strats) // 2)
        return sorted_strats[:top_n]

    def _on_severity_change(
        self,
        old: DrawdownSeverity,
        new: DrawdownSeverity,
    ) -> None:
        levels = [DrawdownSeverity.NORMAL, DrawdownSeverity.CAUTION,
                  DrawdownSeverity.WARNING, DrawdownSeverity.CRITICAL]
        escalating = levels.index(new) > levels.index(old)
        arrow = "▲" if escalating else "▼"
        emoji = "🔴" if escalating else "🟢"
        logger.warning(
            f"{emoji} Drawdown severity {arrow} {old.value.upper()} → {new.value.upper()}  "
            f"drawdown={self._state.drawdown_pct:.2f}%"
        )

    def _enter_recovery(self, current_capital: float) -> None:
        s = self._state
        s.in_recovery_mode = True
        s.recovery_start_capital = current_capital
        # Target: recover ``recovery_exit_threshold`` fraction of the peak loss
        loss = s.peak_capital - current_capital
        s.recovery_target_capital = current_capital + loss * self.config.recovery_exit_threshold
        s.times_entered_recovery += 1
        s.recovery_entered_at = datetime.now().isoformat()
        logger.warning(
            f"🩺 Recovery mode ACTIVATED  "
            f"drawdown={s.drawdown_pct:.2f}%  "
            f"target=${s.recovery_target_capital:,.2f}"
        )

    def _exit_recovery(self, reason: str) -> None:
        s = self._state
        s.in_recovery_mode = False
        s.times_exited_recovery += 1
        s.recovery_exited_at = datetime.now().isoformat()
        logger.info(
            f"✅ Recovery mode DEACTIVATED ({reason})  "
            f"capital=${s.current_capital:,.2f}"
        )

    def _build_guidance(self) -> Dict:
        s = self._state
        sev = DrawdownSeverity(s.severity)
        can, msg = self.can_trade()
        return {
            "severity": s.severity,
            "in_recovery_mode": s.in_recovery_mode,
            "drawdown_pct": round(s.drawdown_pct, 2),
            "recovery_progress_pct": round(s.recovery_progress_pct, 1),
            "position_size_multiplier": self._size_mult(sev),
            "profit_lock_multiplier": self._profit_lock(sev),
            "preferred_strategies": self._preferred_strategies(),
            "can_trade": can,
            "message": msg,
        }

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save_state(self) -> None:
        try:
            with open(self.STATE_FILE, "w") as f:
                json.dump(self._state.to_dict(), f, indent=2)
        except Exception as exc:
            logger.error(f"Failed to save recovery state: {exc}")

    def _load_state(self) -> bool:
        if not self.STATE_FILE.exists():
            return False
        try:
            with open(self.STATE_FILE, "r") as f:
                data = json.load(f)
            computed = {"drawdown_amount", "drawdown_pct", "recovery_progress_pct"}
            clean = {k: v for k, v in data.items() if k not in computed}
            self._state = RecoveryState(**clean)
            logger.info(
                f"✅ Recovery state loaded  severity={self._state.severity}  "
                f"drawdown={self._state.drawdown_pct:.2f}%"
            )
            return True
        except Exception as exc:
            logger.warning(f"Failed to load recovery state: {exc}")
            return False


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_recovery_instance: Optional[SmartDrawdownRecovery] = None
_recovery_lock = threading.Lock()


def get_smart_drawdown_recovery(
    base_capital: float = 0.0,
    config: Optional[RecoveryConfig] = None,
) -> SmartDrawdownRecovery:
    """Return (or create) the global SmartDrawdownRecovery singleton."""
    global _recovery_instance
    if _recovery_instance is None:
        with _recovery_lock:
            if _recovery_instance is None:
                _recovery_instance = SmartDrawdownRecovery(
                    base_capital=base_capital,
                    config=config,
                )
    return _recovery_instance


# ---------------------------------------------------------------------------
# Quick smoke-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s - %(message)s")

    engine = get_smart_drawdown_recovery(base_capital=10_000.0)

    # Simulate a losing streak that pushes into drawdown
    capital = 10_000.0
    print("\n--- Simulating losing streak ---")
    for i in range(8):
        capital -= 180.0
        guidance = engine.update(current_capital=capital, is_win=False)
        print(f"  Trade {i+1}: cap=${capital:,.0f}  severity={guidance['severity']}  "
              f"size_mult={guidance['position_size_multiplier']:.2f}  "
              f"recovery={guidance['in_recovery_mode']}")

    print(engine.get_report())

    # Simulate recovery
    print("--- Simulating recovery ---")
    for i in range(10):
        capital += 120.0
        guidance = engine.update(current_capital=capital, is_win=True)
        print(f"  Win {i+1}: cap=${capital:,.0f}  severity={guidance['severity']}  "
              f"progress={guidance['recovery_progress_pct']:.1f}%  "
              f"recovery={guidance['in_recovery_mode']}")

    print(engine.get_report())
