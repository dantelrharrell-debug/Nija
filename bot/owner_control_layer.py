"""
NIJA Owner Control Layer
==========================

PIN-protected command centre giving the bot operator direct control over
critical subsystems from a single API surface.

Capabilities
------------
* **Emergency override** — force-activate or force-clear emergency-stop.
* **Salary toggle**      — enable / disable the weekly salary payout.
* **Trading toggle**     — pause / resume all new trade entries.
* **Big-profit monitor** — detect and report "big profit days".
* **Audit trail**        — every control action is logged with timestamp and PIN.

Security
--------
A 4-digit PIN (default ``"1234"``; **change via** :attr:`OwnerConfig.owner_pin`)
is required for all state-changing actions.  The PIN is compared in constant
time to prevent timing attacks.

Architecture
------------
::

  ┌──────────────────────────────────────────────────────────────────┐
  │                    OwnerControlLayer                             │
  │                                                                  │
  │  verify_pin(pin) → bool                                          │
  │  emergency_stop(pin)            → ControlResult                  │
  │  clear_emergency_stop(pin)      → ControlResult                  │
  │  pause_trading(pin)             → ControlResult                  │
  │  resume_trading(pin)            → ControlResult                  │
  │  disable_salary(pin)            → ControlResult                  │
  │  enable_salary(pin)             → ControlResult                  │
  │  check_big_profit_day(daily_usd)→ bool                           │
  │  get_status()                   → dict                           │
  │  get_report()                   → str                            │
  └──────────────────────────────────────────────────────────────────┘

Usage
-----
::

    from bot.owner_control_layer import get_owner_control_layer, OwnerConfig

    cfg = OwnerConfig(owner_pin="9876", big_profit_threshold_usd=300.0)
    owner = get_owner_control_layer(config=cfg)

    # From a web API handler:
    result = owner.emergency_stop(pin=request.json["pin"])
    if not result.success:
        return {"error": result.message}, 403

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nija.owner_control_layer")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_OWNER_PIN: str = "1234"
DEFAULT_BIG_PROFIT_THRESHOLD_USD: float = 200.0
DEFAULT_DATA_DIR: Path = Path("data/owner_control")
AUDIT_LOG_FILENAME: str = "owner_audit.jsonl"

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class OwnerConfig:
    """Configuration for the Owner Control Layer."""

    # PIN (stored as-is; hashing is done at runtime)
    owner_pin: str = DEFAULT_OWNER_PIN

    # Big-profit day threshold
    big_profit_threshold_usd: float = DEFAULT_BIG_PROFIT_THRESHOLD_USD

    # Directory for audit log
    data_dir: Optional[str] = None

    # Whether control actions require PIN
    require_pin: bool = True


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class ControlResult:
    """Outcome of an owner control action."""
    success: bool
    action: str
    message: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Audit record
# ---------------------------------------------------------------------------


@dataclass
class AuditRecord:
    """Append-only audit trail entry."""
    record_id: str
    action: str
    success: bool
    message: str
    timestamp: str
    ip_address: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Owner Control Layer
# ---------------------------------------------------------------------------


class OwnerControlLayer:
    """
    PIN-protected owner command centre for NIJA.

    All state-changing methods require a valid PIN unless
    ``config.require_pin`` is False (testing only).

    Thread-safe.
    """

    def __init__(self, config: Optional[OwnerConfig] = None) -> None:
        self._config = config or OwnerConfig()
        self._lock = threading.RLock()

        # Mutable state
        self._trading_paused: bool = False
        self._salary_disabled: bool = False
        self._emergency_stop: bool = False
        self._audit: List[AuditRecord] = []
        self._record_counter: int = 0

        # Persistent audit log
        data_dir = Path(self._config.data_dir) if self._config.data_dir else DEFAULT_DATA_DIR
        data_dir.mkdir(parents=True, exist_ok=True)
        self._audit_path = data_dir / AUDIT_LOG_FILENAME

        logger.info(
            "OwnerControlLayer initialised — big_profit_threshold=$%.0f",
            self._config.big_profit_threshold_usd,
        )

    # ------------------------------------------------------------------
    # PIN verification (constant-time)
    # ------------------------------------------------------------------

    def verify_pin(self, pin: str) -> bool:
        """Return True if *pin* matches the configured owner PIN."""
        expected = self._config.owner_pin.encode()
        provided = (pin or "").encode()
        return hmac.compare_digest(
            hashlib.sha256(expected).digest(),
            hashlib.sha256(provided).digest(),
        )

    def _require_pin(self, pin: str, action: str) -> Optional[ControlResult]:
        """Return a failure ControlResult if PIN is invalid, else None."""
        if not self._config.require_pin:
            return None
        if not self.verify_pin(pin):
            logger.warning("OwnerControlLayer: invalid PIN attempt for action '%s'", action)
            self._record_audit(action=action, success=False, message="Invalid PIN")
            return ControlResult(success=False, action=action, message="Invalid PIN")
        return None

    # ------------------------------------------------------------------
    # Emergency stop
    # ------------------------------------------------------------------

    def emergency_stop(self, pin: str = "", ip: str = "") -> ControlResult:
        """Activate emergency stop — halts all new trade entries."""
        err = self._require_pin(pin, "emergency_stop")
        if err:
            return err
        with self._lock:
            self._emergency_stop = True
        msg = "🚨 Emergency stop ACTIVATED by owner"
        logger.critical(msg)
        self._record_audit("emergency_stop", True, msg, ip)
        return ControlResult(success=True, action="emergency_stop", message=msg)

    def clear_emergency_stop(self, pin: str = "", ip: str = "") -> ControlResult:
        """Deactivate emergency stop — allows trading to resume."""
        err = self._require_pin(pin, "clear_emergency_stop")
        if err:
            return err
        with self._lock:
            self._emergency_stop = False
        msg = "✅ Emergency stop CLEARED by owner"
        logger.info(msg)
        self._record_audit("clear_emergency_stop", True, msg, ip)
        return ControlResult(success=True, action="clear_emergency_stop", message=msg)

    # ------------------------------------------------------------------
    # Trading toggle
    # ------------------------------------------------------------------

    def pause_trading(self, pin: str = "", ip: str = "") -> ControlResult:
        """Pause all new trade entries."""
        err = self._require_pin(pin, "pause_trading")
        if err:
            return err
        with self._lock:
            self._trading_paused = True
        msg = "⏸️  Trading PAUSED by owner"
        logger.info(msg)
        self._record_audit("pause_trading", True, msg, ip)
        return ControlResult(success=True, action="pause_trading", message=msg)

    def resume_trading(self, pin: str = "", ip: str = "") -> ControlResult:
        """Resume trade entries."""
        err = self._require_pin(pin, "resume_trading")
        if err:
            return err
        with self._lock:
            self._trading_paused = False
        msg = "▶️  Trading RESUMED by owner"
        logger.info(msg)
        self._record_audit("resume_trading", True, msg, ip)
        return ControlResult(success=True, action="resume_trading", message=msg)

    # ------------------------------------------------------------------
    # Salary toggle
    # ------------------------------------------------------------------

    def disable_salary(self, pin: str = "", ip: str = "") -> ControlResult:
        """Disable the weekly salary payout."""
        err = self._require_pin(pin, "disable_salary")
        if err:
            return err
        with self._lock:
            self._salary_disabled = True
        msg = "💵 Salary payouts DISABLED by owner"
        logger.info(msg)
        self._record_audit("disable_salary", True, msg, ip)
        return ControlResult(success=True, action="disable_salary", message=msg)

    def enable_salary(self, pin: str = "", ip: str = "") -> ControlResult:
        """Enable the weekly salary payout."""
        err = self._require_pin(pin, "enable_salary")
        if err:
            return err
        with self._lock:
            self._salary_disabled = False
        msg = "💵 Salary payouts ENABLED by owner"
        logger.info(msg)
        self._record_audit("enable_salary", True, msg, ip)
        return ControlResult(success=True, action="enable_salary", message=msg)

    # ------------------------------------------------------------------
    # Big-profit day detection
    # ------------------------------------------------------------------

    def check_big_profit_day(self, daily_profit_usd: float) -> bool:
        """Return True if *daily_profit_usd* meets the big-profit threshold."""
        return daily_profit_usd >= self._config.big_profit_threshold_usd

    # ------------------------------------------------------------------
    # State queries
    # ------------------------------------------------------------------

    @property
    def is_emergency_stop_active(self) -> bool:
        with self._lock:
            return self._emergency_stop

    @property
    def is_trading_paused(self) -> bool:
        with self._lock:
            return self._trading_paused or self._emergency_stop

    @property
    def is_salary_disabled(self) -> bool:
        with self._lock:
            return self._salary_disabled

    def get_status(self) -> Dict[str, Any]:
        """Return current owner-layer state as a dict."""
        with self._lock:
            return {
                "emergency_stop_active": self._emergency_stop,
                "trading_paused": self._trading_paused,
                "salary_disabled": self._salary_disabled,
                "trading_allowed": not (self._emergency_stop or self._trading_paused),
                "salary_allowed": not self._salary_disabled,
                "big_profit_threshold_usd": self._config.big_profit_threshold_usd,
            }

    def get_recent_audit(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Return the most-recent *limit* audit records."""
        with self._lock:
            return [r.to_dict() for r in self._audit[-limit:]]

    def get_report(self) -> str:
        """Return a human-readable status report."""
        status = self.get_status()
        with self._lock:
            audit_count = len(self._audit)
        lines = [
            "=" * 60,
            "🔑  OWNER CONTROL LAYER — STATUS",
            "=" * 60,
            f"  Emergency Stop  : {'🚨 ACTIVE' if status['emergency_stop_active'] else '✅ CLEAR'}",
            f"  Trading         : {'⏸️  PAUSED' if status['trading_paused'] else '▶️  RUNNING'}",
            f"  Salary Payout   : {'❌ DISABLED' if status['salary_disabled'] else '✅ ENABLED'}",
            f"  Big-Profit Thr  : ${status['big_profit_threshold_usd']:,.0f} / day",
            "-" * 60,
            f"  Total Audit Log : {audit_count} actions",
            "=" * 60,
        ]
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Audit helpers
    # ------------------------------------------------------------------

    def _record_audit(
        self, action: str, success: bool, message: str, ip: str = ""
    ) -> None:
        with self._lock:
            self._record_counter += 1
            record = AuditRecord(
                record_id=f"OWNER-{self._record_counter:06d}",
                action=action,
                success=success,
                message=message,
                timestamp=datetime.now(timezone.utc).isoformat(),
                ip_address=ip,
            )
            self._audit.append(record)
        self._append_audit_disk(record)

    def _append_audit_disk(self, record: AuditRecord) -> None:
        try:
            with open(self._audit_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record.to_dict()) + "\n")
        except OSError as exc:
            logger.error("Failed to write audit record: %s", exc)


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_INSTANCE: Optional[OwnerControlLayer] = None
_INSTANCE_LOCK = threading.Lock()


def get_owner_control_layer(
    config: Optional[OwnerConfig] = None,
) -> OwnerControlLayer:
    """
    Return the process-wide singleton :class:`OwnerControlLayer`.

    Thread-safe.  First call creates the instance; subsequent calls ignore
    *config*.
    """
    global _INSTANCE
    if _INSTANCE is None:
        with _INSTANCE_LOCK:
            if _INSTANCE is None:
                _INSTANCE = OwnerControlLayer(config=config)
    return _INSTANCE
