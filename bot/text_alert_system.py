"""
NIJA Text Alert System
=======================

Sends real-time owner notifications for critical financial events:

* **Salary paid**        — when the weekly salary engine pays out
* **Emergency mode**     — when capital-protection escalates / de-escalates
* **Big profit day**     — when daily realised profits cross a configurable
                           threshold (default $200)

Notification channels (all optional / pluggable):
--------------------------------------------------
1. **Webhook**  — POST JSON payload to any URL (Discord / Slack / custom).
2. **Twilio SMS** — real text message to an owner phone number.
3. **Callback** — register a Python callable for in-process dispatch.

Quick start
-----------
::

    from bot.text_alert_system import get_text_alert_system, AlertConfig

    cfg = AlertConfig(
        webhook_url="https://hooks.slack.com/services/…",
        twilio_account_sid="AC…",
        twilio_auth_token="…",
        twilio_from_number="+15550001111",
        twilio_to_number="+15559999999",
        big_profit_day_threshold_usd=200.0,
    )
    alerts = get_text_alert_system(config=cfg)

    # Anywhere in the bot:
    alerts.salary_paid(amount_usd=875.0, week="2026-W12")
    alerts.emergency_mode_triggered(level="EMERGENCY", drawdown_pct=21.5)
    alerts.big_profit_day(daily_profit_usd=450.0)

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("nija.text_alert_system")

# ---------------------------------------------------------------------------
# Optional: Twilio SDK
# ---------------------------------------------------------------------------

try:
    from twilio.rest import Client as TwilioClient  # type: ignore
    _TWILIO_AVAILABLE = True
except ImportError:
    TwilioClient = None  # type: ignore
    _TWILIO_AVAILABLE = False

# ---------------------------------------------------------------------------
# Optional: requests for webhook delivery
# ---------------------------------------------------------------------------

try:
    import requests as _requests  # type: ignore
    _REQUESTS_AVAILABLE = True
except ImportError:
    _requests = None  # type: ignore
    _REQUESTS_AVAILABLE = False

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class AlertConfig:
    """Configuration for the text-alert system."""

    # ---- Webhook (Discord / Slack / custom) ----
    webhook_url: Optional[str] = None
    webhook_timeout_s: int = 10

    # ---- Twilio SMS ----
    twilio_account_sid: Optional[str] = None
    twilio_auth_token: Optional[str] = None
    twilio_from_number: Optional[str] = None   # e.g. "+15550001111"
    twilio_to_number: Optional[str] = None     # owner phone

    # ---- Thresholds ----
    big_profit_day_threshold_usd: float = 200.0  # daily profit that triggers alert

    # ---- Feature toggles ----
    enabled: bool = True
    send_salary_alerts: bool = True
    send_emergency_alerts: bool = True
    send_big_profit_alerts: bool = True


# ---------------------------------------------------------------------------
# Alert record
# ---------------------------------------------------------------------------


@dataclass
class TextAlert:
    """Immutable record of a dispatched alert."""
    alert_id: str
    event_type: str         # "salary_paid" | "emergency_mode" | "big_profit_day"
    message: str
    data: Dict[str, Any]
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    delivered_webhook: bool = False
    delivered_sms: bool = False
    delivered_callback: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------


class TextAlertSystem:
    """
    Owner notification hub for NIJA critical financial events.

    Thread-safe.  All public methods acquire ``_lock``.
    """

    def __init__(self, config: Optional[AlertConfig] = None) -> None:
        self._config: AlertConfig = config or AlertConfig()
        self._lock = threading.RLock()
        self._history: List[TextAlert] = []
        self._callbacks: List[Callable[[TextAlert], None]] = []
        self._counter: int = 0

        # Initialise Twilio client if credentials are present
        self._twilio: Optional[Any] = None
        self._init_twilio()

        logger.info(
            "TextAlertSystem initialised — webhook=%s, sms=%s",
            bool(self._config.webhook_url),
            bool(self._twilio),
        )

    # ------------------------------------------------------------------
    # Channel initialisation
    # ------------------------------------------------------------------

    def _init_twilio(self) -> None:
        cfg = self._config
        if not (cfg.twilio_account_sid and cfg.twilio_auth_token):
            return
        if not _TWILIO_AVAILABLE:
            logger.warning(
                "Twilio credentials supplied but twilio package not installed. "
                "Run: pip install twilio"
            )
            return
        try:
            self._twilio = TwilioClient(cfg.twilio_account_sid, cfg.twilio_auth_token)
            logger.info("Twilio client initialised successfully.")
        except Exception as exc:
            logger.error("Failed to initialise Twilio client: %s", exc)

    # ------------------------------------------------------------------
    # Handler registration
    # ------------------------------------------------------------------

    def add_callback(self, fn: Callable[[TextAlert], None]) -> None:
        """Register an in-process callback that receives every TextAlert."""
        with self._lock:
            self._callbacks.append(fn)

    # ------------------------------------------------------------------
    # Public event methods
    # ------------------------------------------------------------------

    def salary_paid(self, amount_usd: float, week: str = "", note: str = "") -> Optional[TextAlert]:
        """
        Fire a 'salary paid' notification.

        Parameters
        ----------
        amount_usd  : USD amount paid.
        week        : ISO week string, e.g. "2026-W12".
        note        : Optional extra context.
        """
        if not (self._config.enabled and self._config.send_salary_alerts):
            return None
        emoji = "💵"
        week_label = f" ({week})" if week else ""
        message = (
            f"{emoji} NIJA Salary Paid{week_label}: ${amount_usd:,.2f}"
        )
        if note:
            message += f" — {note}"
        return self._dispatch_alert(
            event_type="salary_paid",
            message=message,
            data={"amount_usd": amount_usd, "week": week, "note": note},
        )

    def emergency_mode_triggered(
        self,
        level: str,
        drawdown_pct: float,
        previous_level: str = "",
        extra: str = "",
    ) -> Optional[TextAlert]:
        """
        Fire an 'emergency mode' notification whenever protection level changes.

        Parameters
        ----------
        level         : new protection level string (e.g. "EMERGENCY").
        drawdown_pct  : current drawdown percentage.
        previous_level: previous level string.
        extra         : optional detail.
        """
        if not (self._config.enabled and self._config.send_emergency_alerts):
            return None

        icons = {
            "NORMAL": "🟢", "CAUTION": "🟡",
            "WARNING": "🟠", "DANGER": "🔴", "EMERGENCY": "🚨",
        }
        icon = icons.get(level, "⚠️")
        prev = f" (was {previous_level})" if previous_level and previous_level != level else ""
        message = (
            f"{icon} NIJA Emergency Mode: {level}{prev} — "
            f"drawdown {drawdown_pct:.1f}%"
        )
        if extra:
            message += f" | {extra}"
        return self._dispatch_alert(
            event_type="emergency_mode",
            message=message,
            data={
                "level": level,
                "previous_level": previous_level,
                "drawdown_pct": drawdown_pct,
                "extra": extra,
            },
        )

    def big_profit_day(
        self, daily_profit_usd: float, note: str = ""
    ) -> Optional[TextAlert]:
        """
        Fire a 'big profit day' notification.

        Only fires if ``daily_profit_usd`` ≥ the configured threshold.

        Parameters
        ----------
        daily_profit_usd: total realised profit for the day so far.
        note            : optional extra message.
        """
        if not (self._config.enabled and self._config.send_big_profit_alerts):
            return None
        threshold = self._config.big_profit_day_threshold_usd
        if daily_profit_usd < threshold:
            return None
        message = (
            f"🎉 NIJA Big Profit Day! ${daily_profit_usd:,.2f} today "
            f"(threshold: ${threshold:,.2f})"
        )
        if note:
            message += f" — {note}"
        return self._dispatch_alert(
            event_type="big_profit_day",
            message=message,
            data={
                "daily_profit_usd": daily_profit_usd,
                "threshold_usd": threshold,
                "note": note,
            },
        )

    # ------------------------------------------------------------------
    # Internal dispatch
    # ------------------------------------------------------------------

    def _dispatch_alert(
        self,
        event_type: str,
        message: str,
        data: Dict[str, Any],
    ) -> TextAlert:
        with self._lock:
            self._counter += 1
            alert = TextAlert(
                alert_id=f"TXTALERT-{self._counter:06d}",
                event_type=event_type,
                message=message,
                data=data,
            )

            logger.info("[TextAlert] %s", message)
            self._history.append(alert)

        # Deliver outside lock to avoid deadlocks
        alert.delivered_webhook = self._send_webhook(alert)
        alert.delivered_sms = self._send_sms(alert)
        alert.delivered_callback = self._invoke_callbacks(alert)
        return alert

    def _send_webhook(self, alert: TextAlert) -> bool:
        url = self._config.webhook_url
        if not url:
            return False
        if not _REQUESTS_AVAILABLE:
            logger.debug("requests not installed — webhook delivery skipped.")
            return False
        try:
            payload = {
                "text": alert.message,
                "event_type": alert.event_type,
                "timestamp": alert.timestamp,
                "data": alert.data,
            }
            resp = _requests.post(
                url,
                json=payload,
                timeout=self._config.webhook_timeout_s,
            )
            if resp.status_code < 300:
                logger.debug("Webhook delivered: %s", alert.alert_id)
                return True
            logger.warning(
                "Webhook delivery failed for %s: HTTP %s",
                alert.alert_id, resp.status_code,
            )
            return False
        except Exception as exc:
            logger.warning("Webhook exception for %s: %s", alert.alert_id, exc)
            return False

    def _send_sms(self, alert: TextAlert) -> bool:
        if not self._twilio:
            return False
        cfg = self._config
        if not (cfg.twilio_from_number and cfg.twilio_to_number):
            return False
        try:
            self._twilio.messages.create(
                body=alert.message,
                from_=cfg.twilio_from_number,
                to=cfg.twilio_to_number,
            )
            logger.debug("SMS delivered: %s", alert.alert_id)
            return True
        except Exception as exc:
            logger.warning("SMS exception for %s: %s", alert.alert_id, exc)
            return False

    def _invoke_callbacks(self, alert: TextAlert) -> bool:
        with self._lock:
            callbacks = list(self._callbacks)
        if not callbacks:
            return False
        delivered = True
        for fn in callbacks:
            try:
                fn(alert)
            except Exception as exc:
                logger.warning("Callback exception for %s: %s", alert.alert_id, exc)
                delivered = False
        return delivered

    # ------------------------------------------------------------------
    # History / reporting
    # ------------------------------------------------------------------

    def get_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return the most-recent *limit* alerts as dicts."""
        with self._lock:
            return [a.to_dict() for a in self._history[-limit:]]

    def get_report(self) -> str:
        """Return a human-readable summary."""
        with self._lock:
            total = len(self._history)
            by_type: Dict[str, int] = {}
            for a in self._history:
                by_type[a.event_type] = by_type.get(a.event_type, 0) + 1
            lines = [
                "=" * 60,
                "📣  TEXT ALERT SYSTEM — STATUS REPORT",
                "=" * 60,
                f"  Enabled         : {'✅ YES' if self._config.enabled else '❌ NO'}",
                f"  Webhook         : {'✅' if self._config.webhook_url else '—'}",
                f"  SMS (Twilio)    : {'✅' if self._twilio else '—'}",
                f"  Total Alerts    : {total}",
                "-" * 60,
                "  BY EVENT TYPE",
            ]
            for etype, cnt in by_type.items():
                lines.append(f"    {etype:<28} {cnt}")
            lines.append("=" * 60)
            return "\n".join(lines)


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_INSTANCE: Optional[TextAlertSystem] = None
_INSTANCE_LOCK = threading.Lock()


def get_text_alert_system(
    config: Optional[AlertConfig] = None,
) -> TextAlertSystem:
    """
    Return the process-wide singleton :class:`TextAlertSystem`.

    Thread-safe.  First call creates the instance; subsequent calls ignore
    *config* (pass a new instance to the constructor directly if needed).
    """
    global _INSTANCE
    if _INSTANCE is None:
        with _INSTANCE_LOCK:
            if _INSTANCE is None:
                _INSTANCE = TextAlertSystem(config=config)
    return _INSTANCE
