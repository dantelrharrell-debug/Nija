"""
NIJA Emergency Capital Protection Mode
========================================

Monitors the trading account balance against a configurable drawdown
threshold and, when capital is at risk, escalates through five protection
levels — each progressively restricting trade sizes and blocking salary
payouts until the account recovers.

Protection levels
-----------------
::

  NORMAL    0 – 5 % drawdown  →  100 % sizing   | salary ✅ | entries ✅
  CAUTION   5 – 10 % drawdown →   75 % sizing   | salary ✅ | entries ✅
  WARNING  10 – 15 % drawdown →   50 % sizing   | salary ❌ | entries ✅
  DANGER   15 – 20 % drawdown →   25 % sizing   | salary ❌ | entries ✅ (reduced)
  EMERGENCY    > 20 % drawdown →    0 % sizing  | salary ❌ | entries ❌

Recovery
--------
The engine steps down one level at a time.  To exit EMERGENCY fully the
account must recover by ``recovery_pct`` (default 5 %) from the drawdown
low AND record at least ``recovery_wins`` (default 3) consecutive wins.

Architecture
------------
::

  ┌──────────────────────────────────────────────────────────────────────┐
  │                EmergencyCapitalProtection                            │
  │                                                                      │
  │  update(current_balance)    →  ProtectionDecision                   │
  │  record_trade(pnl, is_win)  →  feeds recovery tracker               │
  │  is_active()                →  True when level ≥ WARNING            │
  │  get_report()               →  status dashboard                     │
  └──────────────────────────────────────────────────────────────────────┘

Usage
-----
    from bot.emergency_capital_protection import (
        get_emergency_capital_protection, ProtectionConfig
    )

    guard = get_emergency_capital_protection()

    # After every price cycle / balance refresh:
    decision = guard.update(current_balance=9_800.0)
    if not decision.allow_new_entries:
        skip_new_trades()
    position_usd *= decision.position_size_multiplier

    # After a trade closes:
    guard.record_trade(pnl_usd=+45.0, is_win=True)

    # Before paying salary:
    if guard.is_active():
        skip_salary_payment()

    # Dashboard:
    print(guard.get_report())

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nija.emergency_capital_protection")

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class ProtectionLevel(str, Enum):
    """Ordered protection escalation levels."""
    NORMAL    = "NORMAL"
    CAUTION   = "CAUTION"
    WARNING   = "WARNING"
    DANGER    = "DANGER"
    EMERGENCY = "EMERGENCY"

    # Convenience: numeric rank so levels can be compared with < / >
    @property
    def rank(self) -> int:
        return _LEVEL_RANK[self]


_LEVEL_RANK: Dict[ProtectionLevel, int] = {
    ProtectionLevel.NORMAL:    0,
    ProtectionLevel.CAUTION:   1,
    ProtectionLevel.WARNING:   2,
    ProtectionLevel.DANGER:    3,
    ProtectionLevel.EMERGENCY: 4,
}

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class ProtectionConfig:
    """Tunable parameters for the emergency protection engine."""

    # Drawdown thresholds that trigger each level (% from rolling peak)
    caution_pct:   float = 5.0
    warning_pct:   float = 10.0
    danger_pct:    float = 15.0
    emergency_pct: float = 20.0

    # Position-size multiplier at each level (1.0 = no reduction)
    caution_multiplier:   float = 0.75
    warning_multiplier:   float = 0.50
    danger_multiplier:    float = 0.25
    emergency_multiplier: float = 0.0

    # Salary is blocked at WARNING and above
    salary_block_level: str = ProtectionLevel.WARNING.value

    # Recovery: consecutive wins and % recovery from drawdown low required
    # to step *down* one protection level
    recovery_wins: int   = 3
    recovery_pct:  float = 5.0   # account must recover 5 % from its low

    # Optional hard floor in USD (0 = disabled)
    floor_usd: float = 0.0

    # Whether this engine is enabled at all
    enabled: bool = True

    # Directory for persistent state / audit log
    data_dir: Optional[str] = None

    def validate(self) -> None:
        thresholds = [
            self.caution_pct, self.warning_pct,
            self.danger_pct, self.emergency_pct,
        ]
        if thresholds != sorted(thresholds):
            raise ValueError("Protection thresholds must be in ascending order")
        for name, val in [
            ("caution_multiplier",   self.caution_multiplier),
            ("warning_multiplier",   self.warning_multiplier),
            ("danger_multiplier",    self.danger_multiplier),
            ("emergency_multiplier", self.emergency_multiplier),
        ]:
            if not 0.0 <= val <= 1.0:
                raise ValueError(f"{name} must be 0–1, got {val}")


@dataclass
class ProtectionDecision:
    """Result returned by ``update()``."""
    level:                    ProtectionLevel
    drawdown_pct:             float
    position_size_multiplier: float   # 0.0 = no new positions
    allow_new_entries:        bool
    block_salary:             bool
    reason:                   str
    peak_balance_usd:         float
    current_balance_usd:      float
    floor_hit:                bool = False


@dataclass
class ProtectionEvent:
    """Audit log entry for every level transition."""
    event_id:          str
    timestamp:         str
    event_type:        str    # "escalate" | "recover" | "floor_hit" | "manual_reset"
    old_level:         str
    new_level:         str
    drawdown_pct:      float
    current_balance:   float
    peak_balance:      float
    note:              str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ProtectionState:
    """Persisted engine state."""
    level:                 str   = ProtectionLevel.NORMAL.value
    peak_balance_usd:      float = 0.0
    low_balance_usd:       float = 0.0       # lowest balance seen while in protection
    consecutive_wins:      int   = 0
    total_escalations:     int   = 0
    total_recoveries:      int   = 0
    last_updated:          str   = ""
    event_log:             List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ProtectionState":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ---------------------------------------------------------------------------
# EmergencyCapitalProtection
# ---------------------------------------------------------------------------


class EmergencyCapitalProtection:
    """
    Monitors account balance and escalates through protection levels when
    drawdown thresholds are breached.  Recovers automatically as wins
    accumulate and the balance climbs back.

    Thread-safe; obtain the process-wide singleton via
    ``get_emergency_capital_protection()``.
    """

    DEFAULT_DATA_DIR = Path("data/emergency_protection")

    def __init__(
        self,
        config: Optional[ProtectionConfig] = None,
        data_dir: Optional[Path] = None,
    ) -> None:
        self._lock = threading.RLock()
        self._config = config or ProtectionConfig()
        self._config.validate()

        _dir = (
            Path(self._config.data_dir) if self._config.data_dir
            else (data_dir or self.DEFAULT_DATA_DIR)
        )
        _dir.mkdir(parents=True, exist_ok=True)
        self._state_file = _dir / "protection_state.json"
        self._audit_file = _dir / "protection_audit.jsonl"

        self._state = self._load_state()
        self._salary_block_level = ProtectionLevel(self._config.salary_block_level)

        logger.info("=" * 70)
        logger.info("🛡️   Emergency Capital Protection initialised")
        logger.info("    Level        : %s", self._state.level)
        logger.info("    Peak balance : $%.2f", self._state.peak_balance_usd)
        logger.info("    Thresholds   : caution=%.0f%% warning=%.0f%% danger=%.0f%% emergency=%.0f%%",
                    self._config.caution_pct, self._config.warning_pct,
                    self._config.danger_pct, self._config.emergency_pct)
        logger.info("=" * 70)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load_state(self) -> ProtectionState:
        if self._state_file.exists():
            try:
                with open(self._state_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                state = ProtectionState.from_dict(data)
                logger.debug("EmergencyCapitalProtection: state loaded")
                return state
            except Exception as exc:
                logger.warning("EmergencyCapitalProtection: failed to load state (%s) — fresh start", exc)
        return ProtectionState()

    def _save_state(self) -> None:
        try:
            with open(self._state_file, "w", encoding="utf-8") as f:
                json.dump(self._state.to_dict(), f, indent=2)
        except Exception as exc:
            logger.error("EmergencyCapitalProtection: failed to save state: %s", exc)

    def _append_audit(self, event: ProtectionEvent) -> None:
        try:
            with open(self._audit_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(event.to_dict()) + "\n")
        except Exception as exc:
            logger.error("EmergencyCapitalProtection: audit write failed: %s", exc)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _drawdown_to_level(self, drawdown_pct: float) -> ProtectionLevel:
        """Map a drawdown percentage to the corresponding protection level."""
        if drawdown_pct >= self._config.emergency_pct:
            return ProtectionLevel.EMERGENCY
        if drawdown_pct >= self._config.danger_pct:
            return ProtectionLevel.DANGER
        if drawdown_pct >= self._config.warning_pct:
            return ProtectionLevel.WARNING
        if drawdown_pct >= self._config.caution_pct:
            return ProtectionLevel.CAUTION
        return ProtectionLevel.NORMAL

    def _multiplier_for(self, level: ProtectionLevel) -> float:
        return {
            ProtectionLevel.NORMAL:    1.0,
            ProtectionLevel.CAUTION:   self._config.caution_multiplier,
            ProtectionLevel.WARNING:   self._config.warning_multiplier,
            ProtectionLevel.DANGER:    self._config.danger_multiplier,
            ProtectionLevel.EMERGENCY: self._config.emergency_multiplier,
        }[level]

    def _log_transition(
        self,
        event_type: str,
        old_level: ProtectionLevel,
        new_level: ProtectionLevel,
        drawdown_pct: float,
        current_balance: float,
        note: str = "",
    ) -> None:
        event = ProtectionEvent(
            event_id=str(uuid.uuid4()),
            timestamp=datetime.now(timezone.utc).isoformat(),
            event_type=event_type,
            old_level=old_level.value,
            new_level=new_level.value,
            drawdown_pct=drawdown_pct,
            current_balance=current_balance,
            peak_balance=self._state.peak_balance_usd,
            note=note,
        )
        self._state.event_log.append(event.to_dict())
        self._append_audit(event)

    def _build_decision(
        self,
        level: ProtectionLevel,
        drawdown_pct: float,
        current_balance: float,
        reason: str,
        floor_hit: bool = False,
    ) -> ProtectionDecision:
        multiplier = self._multiplier_for(level)
        block_salary = level.rank >= self._salary_block_level.rank
        allow_entries = multiplier > 0.0
        return ProtectionDecision(
            level=level,
            drawdown_pct=drawdown_pct,
            position_size_multiplier=multiplier,
            allow_new_entries=allow_entries,
            block_salary=block_salary,
            reason=reason,
            peak_balance_usd=self._state.peak_balance_usd,
            current_balance_usd=current_balance,
            floor_hit=floor_hit,
        )

    # ------------------------------------------------------------------
    # Core public API
    # ------------------------------------------------------------------

    def update(self, current_balance: float) -> ProtectionDecision:
        """
        Process the latest account balance and return a ``ProtectionDecision``.

        Call this on every balance refresh / price cycle.

        Args:
            current_balance: Current account value in USD.

        Returns:
            A ``ProtectionDecision`` describing allowed trade sizes and
            whether salary payments should be blocked.
        """
        if not self._config.enabled:
            return self._build_decision(
                ProtectionLevel.NORMAL, 0.0, current_balance, "Protection disabled"
            )

        with self._lock:
            s = self._state
            s.last_updated = datetime.now(timezone.utc).isoformat()

            # --- Update rolling peak ---
            if current_balance > s.peak_balance_usd:
                s.peak_balance_usd = current_balance
                # Reset wins counter when a new peak is reached (system is healthy)
                s.consecutive_wins = 0

            # Guard against zero peak on very first call
            if s.peak_balance_usd <= 0:
                s.peak_balance_usd = current_balance
                self._save_state()
                return self._build_decision(
                    ProtectionLevel.NORMAL, 0.0, current_balance,
                    "First balance update — peak established"
                )

            # --- Hard floor check ---
            floor_hit = (
                self._config.floor_usd > 0
                and current_balance <= self._config.floor_usd
            )
            if floor_hit:
                old_level = ProtectionLevel(s.level)
                if old_level != ProtectionLevel.EMERGENCY:
                    s.level = ProtectionLevel.EMERGENCY.value
                    s.total_escalations += 1
                    self._log_transition(
                        "floor_hit", old_level, ProtectionLevel.EMERGENCY,
                        drawdown_pct=100.0 * (1 - current_balance / s.peak_balance_usd),
                        current_balance=current_balance,
                        note=f"Hard floor ${self._config.floor_usd:.2f} hit — balance=${current_balance:.2f}",
                    )
                    self._save_state()
                    logger.critical(
                        "🚨 EmergencyCapitalProtection: HARD FLOOR HIT "
                        "(balance=$%.2f ≤ floor=$%.2f) — ALL TRADING HALTED",
                        current_balance, self._config.floor_usd,
                    )
                decision = self._build_decision(
                    ProtectionLevel.EMERGENCY,
                    drawdown_pct=100.0 * (1 - current_balance / s.peak_balance_usd),
                    current_balance=current_balance,
                    reason=f"Hard floor ${self._config.floor_usd:.2f} hit",
                    floor_hit=True,
                )
                return decision

            # --- Compute current drawdown ---
            drawdown_pct = max(0.0, 100.0 * (1.0 - current_balance / s.peak_balance_usd))
            required_level = self._drawdown_to_level(drawdown_pct)
            current_level  = ProtectionLevel(s.level)

            # Track drawdown low for recovery measurement
            if drawdown_pct > 0 and (
                s.low_balance_usd <= 0 or current_balance < s.low_balance_usd
            ):
                s.low_balance_usd = current_balance

            # --- Escalation ---
            if required_level.rank > current_level.rank:
                s.level = required_level.value
                s.consecutive_wins = 0
                s.total_escalations += 1
                self._log_transition(
                    "escalate", current_level, required_level,
                    drawdown_pct, current_balance,
                    note=f"Drawdown {drawdown_pct:.2f}% breached {required_level.value} threshold",
                )
                self._save_state()
                logger.warning(
                    "⚠️  EmergencyCapitalProtection: ESCALATED %s → %s "
                    "(drawdown=%.2f%%, balance=$%.2f, peak=$%.2f)",
                    current_level.value, required_level.value,
                    drawdown_pct, current_balance, s.peak_balance_usd,
                )
                decision = self._build_decision(
                    required_level, drawdown_pct, current_balance,
                    reason=f"Drawdown {drawdown_pct:.2f}% → level {required_level.value}",
                )
                return decision

            # --- Recovery: step down one level if conditions met ---
            if current_level.rank > 0:
                low = s.low_balance_usd if s.low_balance_usd > 0 else current_balance
                recovery_from_low_pct = (
                    100.0 * (current_balance - low) / low if low > 0 else 0.0
                )
                wins_ok     = s.consecutive_wins >= self._config.recovery_wins
                recovery_ok = recovery_from_low_pct >= self._config.recovery_pct
                drawdown_ok = required_level.rank < current_level.rank

                if wins_ok and recovery_ok and drawdown_ok:
                    levels_ordered = list(ProtectionLevel)
                    new_level = levels_ordered[current_level.rank - 1]
                    s.level = new_level.value
                    s.total_recoveries += 1
                    if new_level == ProtectionLevel.NORMAL:
                        s.low_balance_usd = 0.0   # reset low when fully recovered
                    self._log_transition(
                        "recover", current_level, new_level,
                        drawdown_pct, current_balance,
                        note=(
                            f"{s.consecutive_wins} wins, "
                            f"+{recovery_from_low_pct:.1f}% recovery from low"
                        ),
                    )
                    self._save_state()
                    logger.info(
                        "✅  EmergencyCapitalProtection: RECOVERED %s → %s "
                        "(drawdown=%.2f%%, +%.1f%% from low, %d wins)",
                        current_level.value, new_level.value,
                        drawdown_pct, recovery_from_low_pct, s.consecutive_wins,
                    )
                    current_level = new_level

            self._save_state()
            decision = self._build_decision(
                current_level, drawdown_pct, current_balance,
                reason=f"Drawdown {drawdown_pct:.2f}% — level {current_level.value}",
            )
            return decision

    def record_trade(self, pnl_usd: float, is_win: bool) -> None:
        """
        Notify the engine about a closed trade.

        Consecutive wins are tracked for the recovery gate.  A loss resets
        the streak to zero.

        Args:
            pnl_usd: Realised P&L (informational; not used for balance tracking).
            is_win:  Whether the trade was profitable.
        """
        if not self._config.enabled:
            return
        with self._lock:
            if is_win:
                self._state.consecutive_wins += 1
                logger.debug(
                    "EmergencyCapitalProtection: win recorded — streak=%d",
                    self._state.consecutive_wins,
                )
            else:
                if self._state.consecutive_wins > 0:
                    logger.debug(
                        "EmergencyCapitalProtection: loss — win streak reset (was %d)",
                        self._state.consecutive_wins,
                    )
                self._state.consecutive_wins = 0
            self._save_state()

    def is_active(self) -> bool:
        """
        Return ``True`` when the protection level is WARNING or higher
        (i.e., the engine is actively restricting the bot).
        """
        with self._lock:
            return ProtectionLevel(self._state.level).rank >= ProtectionLevel.WARNING.rank

    def current_level(self) -> ProtectionLevel:
        """Return the current protection level."""
        with self._lock:
            return ProtectionLevel(self._state.level)

    def reset(self, note: str = "manual reset") -> None:
        """
        Manually reset the engine to NORMAL level.

        **Use with caution** — this bypasses all automatic gates.  Only
        call after verifying the root cause of the drawdown has been
        addressed.

        Args:
            note: Reason for the manual reset (written to the audit log).
        """
        with self._lock:
            old_level = ProtectionLevel(self._state.level)
            if old_level == ProtectionLevel.NORMAL:
                logger.info("EmergencyCapitalProtection: already NORMAL — reset is a no-op")
                return
            self._state.level = ProtectionLevel.NORMAL.value
            self._state.consecutive_wins = 0
            self._state.low_balance_usd = 0.0
            self._log_transition(
                "manual_reset", old_level, ProtectionLevel.NORMAL,
                drawdown_pct=0.0,
                current_balance=self._state.peak_balance_usd,
                note=note,
            )
            self._save_state()
            logger.warning(
                "🔓  EmergencyCapitalProtection: MANUAL RESET (%s → NORMAL) — %s",
                old_level.value, note,
            )

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def get_report(self) -> str:
        """Return a human-readable status dashboard."""
        with self._lock:
            s = self._state
            level = ProtectionLevel(s.level)
            multiplier = self._multiplier_for(level)
            block_salary = level.rank >= self._salary_block_level.rank

            if s.peak_balance_usd > 0:
                ref_balance = s.low_balance_usd if s.low_balance_usd > 0 else s.peak_balance_usd
                drawdown_pct = max(
                    0.0,
                    100.0 * (1.0 - ref_balance / s.peak_balance_usd),
                )
            else:
                drawdown_pct = 0.0

            level_icons = {
                ProtectionLevel.NORMAL:    "🟢",
                ProtectionLevel.CAUTION:   "🟡",
                ProtectionLevel.WARNING:   "🟠",
                ProtectionLevel.DANGER:    "🔴",
                ProtectionLevel.EMERGENCY: "🚨",
            }
            icon = level_icons.get(level, "❓")

            lines = [
                "=" * 70,
                f"🛡️   EMERGENCY CAPITAL PROTECTION — STATUS REPORT",
                "=" * 70,
                f"  Status          : {'🟢 ENABLED' if self._config.enabled else '🔴 DISABLED'}",
                f"  Protection Level: {icon} {level.value}",
                f"  Pos-Size Multi  : {multiplier * 100:.0f} %",
                f"  New Entries     : {'✅ ALLOWED' if multiplier > 0 else '❌ HALTED'}",
                f"  Salary Blocked  : {'❌ YES' if block_salary else '✅ NO'}",
                "-" * 70,
                "  📊  BALANCE TRACKING",
                f"  Peak Balance    : ${s.peak_balance_usd:,.2f}",
                f"  Drawdown Low    : ${s.low_balance_usd:,.2f}" if s.low_balance_usd > 0 else "  Drawdown Low    : N/A",
                f"  Max Drawdown    : {drawdown_pct:.2f} %",
                f"  Floor (USD)     : {'$' + f'{self._config.floor_usd:,.2f}' if self._config.floor_usd > 0 else 'disabled'}",
                "-" * 70,
                "  🔄  RECOVERY TRACKER",
                f"  Consec. Wins    : {s.consecutive_wins} / {self._config.recovery_wins} needed",
                f"  Recovery Target : {self._config.recovery_pct:.1f} % from low",
                "-" * 70,
                "  📈  LIFETIME STATS",
                f"  Total Escalations : {s.total_escalations}",
                f"  Total Recoveries  : {s.total_recoveries}",
                "-" * 70,
                "  🚦  THRESHOLDS",
                f"  Caution   : ≥ {self._config.caution_pct:.0f}% drawdown → {self._config.caution_multiplier*100:.0f}% sizing",
                f"  Warning   : ≥ {self._config.warning_pct:.0f}% drawdown → {self._config.warning_multiplier*100:.0f}% sizing  (salary blocked)",
                f"  Danger    : ≥ {self._config.danger_pct:.0f}% drawdown → {self._config.danger_multiplier*100:.0f}% sizing  (salary blocked)",
                f"  Emergency : ≥ {self._config.emergency_pct:.0f}% drawdown →   0% sizing  (all halted)",
                "=" * 70,
            ]
            return "\n".join(lines)


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_INSTANCE: Optional[EmergencyCapitalProtection] = None
_INSTANCE_LOCK = threading.Lock()


def get_emergency_capital_protection(
    config: Optional[ProtectionConfig] = None,
    data_dir: Optional[Path] = None,
) -> EmergencyCapitalProtection:
    """
    Return the process-wide singleton ``EmergencyCapitalProtection``.

    Thread-safe; created on first call.  Subsequent calls ignore *config*
    and *data_dir* (construct directly for custom instances in tests).
    """
    global _INSTANCE
    if _INSTANCE is None:
        with _INSTANCE_LOCK:
            if _INSTANCE is None:
                _INSTANCE = EmergencyCapitalProtection(config=config, data_dir=data_dir)
    return _INSTANCE
