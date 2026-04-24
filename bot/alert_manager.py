"""
NIJA Unified Alert Manager
===========================

Central hub for all operational alerts across NIJA's subsystems:

- **Strategy performance deviations** – win rate / profit factor drop beyond thresholds
- **Execution anomalies**            – failed orders, extreme slippage
- **Compliance violations**          – blocked trades, logging errors
- **Risk limit breaches**            – VaR / drawdown / kill-switch events

Supports auto-pausing: when a CRITICAL or EMERGENCY alert fires, the manager
sets a global pause flag that callers can query before entering new trades.

Notification channels (all are pluggable via callbacks):
- Console / Python logging (always active)
- File-based alert log (JSON-lines format)
- Webhook callback (register with ``add_webhook_handler``)
- Email callback (register with ``add_email_handler``)

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
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Callable, Deque, Dict, List, Optional

logger = logging.getLogger("nija.alert_manager")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_LOG_DIR: str = "alert_logs"
DEFAULT_MAX_ALERTS: int = 1_000
DEFAULT_COOLDOWN_SECONDS: int = 300       # same alert type won't re-fire within 5 min
DEFAULT_PAUSE_DURATION_SECONDS: int = 900  # auto-pause lasts 15 min by default


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class AlertSeverity(Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
    EMERGENCY = "EMERGENCY"


class AlertCategory(Enum):
    STRATEGY_PERFORMANCE = "STRATEGY_PERFORMANCE"
    EXECUTION_ANOMALY = "EXECUTION_ANOMALY"
    COMPLIANCE_VIOLATION = "COMPLIANCE_VIOLATION"
    RISK_LIMIT_BREACH = "RISK_LIMIT_BREACH"
    SYSTEM = "SYSTEM"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class Alert:
    """Immutable alert record."""
    alert_id: str
    severity: AlertSeverity
    category: AlertCategory
    title: str
    message: str
    data: Dict = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    acknowledged: bool = False

    def to_dict(self) -> Dict:
        d = asdict(self)
        d["severity"] = self.severity.value
        d["category"] = self.category.value
        return d


@dataclass
class AlertThreshold:
    """Configurable threshold for automatic alert generation."""
    name: str
    category: AlertCategory
    severity: AlertSeverity
    description: str = ""
    enabled: bool = True


# ---------------------------------------------------------------------------
# Alert Manager
# ---------------------------------------------------------------------------

class AlertManager:
    """
    Unified alert manager for all NIJA subsystems.

    Thread-safe.  All public methods acquire ``_lock``.

    Auto-pause behaviour
    --------------------
    When an alert with severity CRITICAL or EMERGENCY is fired, the manager
    sets ``_paused = True`` for ``pause_duration_seconds``.  Any code
    can call ``is_paused()`` to check before entering a new trade.
    """

    def __init__(
        self,
        log_dir: str = DEFAULT_LOG_DIR,
        max_alerts: int = DEFAULT_MAX_ALERTS,
        cooldown_seconds: int = DEFAULT_COOLDOWN_SECONDS,
        pause_duration_seconds: int = DEFAULT_PAUSE_DURATION_SECONDS,
        auto_pause_on_critical: bool = True,
    ) -> None:
        self._lock = threading.RLock()
        self._alerts: Deque[Alert] = deque(maxlen=max_alerts)
        self._cooldowns: Dict[str, datetime] = {}  # alert_key → last_fired_time
        self._cooldown_seconds = cooldown_seconds
        self._pause_duration = timedelta(seconds=pause_duration_seconds)
        self._auto_pause = auto_pause_on_critical
        self._paused: bool = False
        self._pause_until: Optional[datetime] = None
        self._pause_reason: str = ""

        # Registered notification handlers
        self._webhook_handlers: List[Callable[[Alert], None]] = []
        self._email_handlers: List[Callable[[Alert], None]] = []

        # File logging
        self._log_path: Optional[Path] = None
        if log_dir:
            path = Path(log_dir)
            path.mkdir(parents=True, exist_ok=True)
            self._log_path = path / "alerts.jsonl"

        self._alert_counter = 0
        logger.info("AlertManager initialised — log_dir=%s, auto_pause=%s", log_dir, auto_pause_on_critical)

    # ------------------------------------------------------------------
    # Handler registration
    # ------------------------------------------------------------------

    def add_webhook_handler(self, handler: Callable[[Alert], None]) -> None:
        """Register a callable that receives every new Alert object."""
        with self._lock:
            self._webhook_handlers.append(handler)

    def add_email_handler(self, handler: Callable[[Alert], None]) -> None:
        """Register a callable for email delivery of alerts."""
        with self._lock:
            self._email_handlers.append(handler)

    # ------------------------------------------------------------------
    # Core alert firing
    # ------------------------------------------------------------------

    def fire(
        self,
        severity: AlertSeverity,
        category: AlertCategory,
        title: str,
        message: str,
        data: Optional[Dict] = None,
        cooldown_key: Optional[str] = None,
    ) -> Optional[Alert]:
        """
        Fire an alert.

        Parameters
        ----------
        severity    : alert severity level
        category    : alert category
        title       : short human-readable title
        message     : detailed description
        data        : optional structured context (dict)
        cooldown_key: if set, suppress re-firing within cooldown_seconds

        Returns the Alert if it was fired, or None if suppressed by cooldown.
        """
        with self._lock:
            # Cooldown check
            if cooldown_key:
                last_fired = self._cooldowns.get(cooldown_key)
                if last_fired:
                    elapsed = (datetime.utcnow() - last_fired).total_seconds()
                    if elapsed < self._cooldown_seconds:
                        logger.debug(
                            "Alert '%s' suppressed by cooldown (%.0fs remaining)",
                            cooldown_key, self._cooldown_seconds - elapsed,
                        )
                        return None
                self._cooldowns[cooldown_key] = datetime.utcnow()

            self._alert_counter += 1
            alert = Alert(
                alert_id=f"ALERT-{self._alert_counter:06d}",
                severity=severity,
                category=category,
                title=title,
                message=message,
                data=data or {},
            )
            self._alerts.append(alert)
            self._dispatch(alert)
            return alert

    # ------------------------------------------------------------------
    # Convenience methods for common alert types
    # ------------------------------------------------------------------

    def strategy_performance_deviation(
        self,
        strategy: str,
        metric: str,
        current_value: float,
        threshold: float,
    ) -> Optional[Alert]:
        """Fire a strategy performance deviation alert."""
        severity = (
            AlertSeverity.CRITICAL
            if current_value < threshold * 0.80
            else AlertSeverity.WARNING
        )
        return self.fire(
            severity=severity,
            category=AlertCategory.STRATEGY_PERFORMANCE,
            title=f"Strategy deviation: {strategy}",
            message=(
                f"{strategy} — {metric} dropped to {current_value:.3f} "
                f"(threshold: {threshold:.3f})"
            ),
            data={"strategy": strategy, "metric": metric,
                  "current": current_value, "threshold": threshold},
            cooldown_key=f"strategy_deviation_{strategy}_{metric}",
        )

    def execution_anomaly(
        self,
        venue: str,
        symbol: str,
        anomaly_type: str,
        detail: str,
        severity: AlertSeverity = AlertSeverity.WARNING,
    ) -> Optional[Alert]:
        """Fire an execution anomaly alert (failed order, extreme slippage, etc.)."""
        return self.fire(
            severity=severity,
            category=AlertCategory.EXECUTION_ANOMALY,
            title=f"Execution anomaly: {anomaly_type} on {venue}/{symbol}",
            message=detail,
            data={"venue": venue, "symbol": symbol, "anomaly_type": anomaly_type},
            cooldown_key=f"exec_anomaly_{venue}_{anomaly_type}",
        )

    def compliance_violation(
        self,
        rule: str,
        detail: str,
        severity: AlertSeverity = AlertSeverity.CRITICAL,
    ) -> Optional[Alert]:
        """Fire a compliance violation alert (blocked trade, logging error, etc.)."""
        return self.fire(
            severity=severity,
            category=AlertCategory.COMPLIANCE_VIOLATION,
            title=f"Compliance violation: {rule}",
            message=detail,
            data={"rule": rule},
            cooldown_key=f"compliance_{rule}",
        )

    def risk_limit_breach(
        self,
        limit_type: str,
        current_value: float,
        limit_value: float,
        severity: AlertSeverity = AlertSeverity.EMERGENCY,
    ) -> Optional[Alert]:
        """Fire a risk limit breach alert (VaR, drawdown, kill-switch)."""
        return self.fire(
            severity=severity,
            category=AlertCategory.RISK_LIMIT_BREACH,
            title=f"Risk limit breached: {limit_type}",
            message=(
                f"{limit_type} = {current_value:.4f} exceeded limit {limit_value:.4f}"
            ),
            data={"limit_type": limit_type,
                  "current": current_value, "limit": limit_value},
            cooldown_key=f"risk_breach_{limit_type}",
        )

    # ------------------------------------------------------------------
    # Auto-pause
    # ------------------------------------------------------------------

    def _maybe_auto_pause(self, alert: Alert) -> None:
        """Trigger auto-pause for CRITICAL or EMERGENCY alerts."""
        if not self._auto_pause:
            return
        if alert.severity in (AlertSeverity.CRITICAL, AlertSeverity.EMERGENCY):
            if not self._paused:
                self._paused = True
                self._pause_until = datetime.utcnow() + self._pause_duration
                self._pause_reason = f"{alert.severity.value}: {alert.title}"
                logger.warning(
                    "🛑 AUTO-PAUSE engaged until %s — reason: %s",
                    self._pause_until.isoformat(), self._pause_reason,
                )

    def is_paused(self) -> bool:
        """Return True if new trade entries should be blocked."""
        with self._lock:
            if self._paused and self._pause_until:
                if datetime.utcnow() >= self._pause_until:
                    self._paused = False
                    self._pause_until = None
                    self._pause_reason = ""
                    logger.info("✅ Auto-pause lifted — trading may resume")
            return self._paused

    def resume(self) -> None:
        """Manually lift the auto-pause."""
        with self._lock:
            self._paused = False
            self._pause_until = None
            self._pause_reason = ""
            logger.info("✅ Auto-pause manually lifted")

    def pause_status(self) -> Dict:
        """Return current pause state for API responses."""
        with self._lock:
            return {
                "paused": self._paused,
                "pause_until": self._pause_until.isoformat() if self._pause_until else None,
                "reason": self._pause_reason,
            }

    # ------------------------------------------------------------------
    # Dispatch (logging, file, webhooks, email)
    # ------------------------------------------------------------------

    def _dispatch(self, alert: Alert) -> None:
        """Internal: log, persist, and notify for a newly-fired alert."""
        # Log to Python logging
        log_fn = {
            AlertSeverity.INFO: logger.info,
            AlertSeverity.WARNING: logger.warning,
            AlertSeverity.CRITICAL: logger.error,
            AlertSeverity.EMERGENCY: logger.critical,
        }.get(alert.severity, logger.info)
        log_fn("[%s] %s — %s", alert.category.value, alert.title, alert.message)

        # Persist to JSON-lines file
        if self._log_path:
            try:
                with self._log_path.open("a") as fh:
                    fh.write(json.dumps(alert.to_dict()) + "\n")
            except OSError as exc:
                logger.error("Failed to write alert to file: %s", exc)

        # Auto-pause check
        self._maybe_auto_pause(alert)

        # External handlers
        for handler in self._webhook_handlers:
            try:
                handler(alert)
            except Exception as exc:  # noqa: BLE001
                logger.error("Webhook handler error: %s", exc)

        for handler in self._email_handlers:
            try:
                handler(alert)
            except Exception as exc:  # noqa: BLE001
                logger.error("Email handler error: %s", exc)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_recent_alerts(
        self,
        limit: int = 50,
        severity: Optional[AlertSeverity] = None,
        category: Optional[AlertCategory] = None,
    ) -> List[Alert]:
        """Return recent alerts, optionally filtered by severity/category."""
        with self._lock:
            alerts = list(self._alerts)

        if severity:
            alerts = [a for a in alerts if a.severity == severity]
        if category:
            alerts = [a for a in alerts if a.category == category]

        return alerts[-limit:]

    def acknowledge(self, alert_id: str) -> bool:
        """Mark an alert as acknowledged. Returns True if found."""
        with self._lock:
            for alert in self._alerts:
                if alert.alert_id == alert_id:
                    alert.acknowledged = True
                    return True
        return False

    def unacknowledged_count(self, severity: Optional[AlertSeverity] = None) -> int:
        """Count unacknowledged alerts."""
        with self._lock:
            alerts = [a for a in self._alerts if not a.acknowledged]
        if severity:
            alerts = [a for a in alerts if a.severity == severity]
        return len(alerts)

    def clear_old_alerts(self, older_than_hours: int = 24) -> int:
        """Remove acknowledged alerts older than the specified number of hours."""
        cutoff = datetime.utcnow() - timedelta(hours=older_than_hours)
        with self._lock:
            before = len(self._alerts)
            keep = deque(
                (a for a in self._alerts
                 if not a.acknowledged or datetime.fromisoformat(a.timestamp) >= cutoff),
                maxlen=self._alerts.maxlen,
            )
            self._alerts = keep
            removed = before - len(self._alerts)
        logger.info("Cleared %d old acknowledged alerts", removed)
        return removed


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_manager_instance: Optional[AlertManager] = None
_manager_lock = threading.Lock()


def get_alert_manager() -> AlertManager:
    """Return the global AlertManager singleton."""
    global _manager_instance
    with _manager_lock:
        if _manager_instance is None:
            _manager_instance = AlertManager()
        return _manager_instance
