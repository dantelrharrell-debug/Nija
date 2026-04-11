# bot/execution_risk_firewall.py
"""
NIJA Execution Risk Firewall
==============================

Institutional-grade execution quality enforcement layer.  Four independent
gates protect every trade from bad fills, degraded venues, and abnormal
execution conditions.

Gates
-----
1. **Per-trade max slippage guard**
   After each fill, compare the actual fill price to the pre-order expected
   (mid) price.  If the deviation in basis-points exceeds ``max_slippage_bps``
   the fill is flagged and the consecutive-anomaly counter is incremented.
   Configure via ``NIJA_MAX_SLIPPAGE_BPS`` (default 50 bps = 0.50 %).

2. **Exchange health scoring**
   Each venue earns a rolling composite score (0–100) based on:
     - API success rate        (60 % weight)
     - Order acceptance rate   (25 % weight)
     - Fill quality rate       (15 % weight)
   Venues below ``NIJA_MIN_VENUE_SCORE`` (default 40) are automatically
   disabled; all new orders to that venue are blocked until its score
   recovers above ``NIJA_VENUE_RECOVERY_SCORE`` (default 60).

3. **Fill anomaly detection**
   A rolling z-score on (fill_price − expected_price) residuals per symbol
   flags any fill that deviates more than ``NIJA_ANOMALY_SIGMA`` (default
   3.0 σ) from recent history.

4. **Auto-degrade LIVE → SAFE_MODE → HALT**
   Accumulated evidence from gates 1–3 drives a system-level execution mode:

     LIVE      — full trading; all entries allowed
     WATCHFUL  — elevated alerts; trading continues at 75 % sizing
     SAFE_MODE — new entries blocked; exits/stops only; 25 % sizing
     HALT      — all trading stopped; KillSwitch activated

   The system steps back toward LIVE after ``NIJA_RECOVERY_CLEAN_FILLS``
   (default 5) consecutive clean fills.

Wire-in
-------
In ``trading_strategy.py``::

    from bot.execution_risk_firewall import (
        get_execution_risk_firewall, ExecutionMode
    )
    EXEC_FIREWALL_AVAILABLE = True
    ...
    _erf = get_execution_risk_firewall()

    # Entry gate (alongside other LAYER 0 checks):
    _erf_mode = _erf.get_execution_mode()
    if _erf_mode in (ExecutionMode.SAFE_MODE, ExecutionMode.HALT):
        user_mode = True   # block new entries

    # After each confirmed fill:
    _erf.record_fill(
        venue="coinbase",
        symbol="BTC-USD",
        expected_price=50_000.0,
        fill_price=50_120.0,
        side="buy",
    )

In ``multi_account_broker_manager.py``::

    _erf.record_api_call(
        venue=broker_type.value,
        latency_ms=elapsed_ms,
        success=True,
    )

Author: NIJA Trading Systems
Version: 1.0
Date: April 2026
"""

from __future__ import annotations

import logging
import math
import os
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Deque, Dict, List, Optional, Tuple

logger = logging.getLogger("nija.execution_risk_firewall")

# ---------------------------------------------------------------------------
# Optional KillSwitch integration
# ---------------------------------------------------------------------------
try:
    from kill_switch import KillSwitch as _KillSwitch
    _KS_AVAILABLE = True
except ImportError:
    try:
        from bot.kill_switch import KillSwitch as _KillSwitch
        _KS_AVAILABLE = True
    except ImportError:
        _KS_AVAILABLE = False
        _KillSwitch = None  # type: ignore[assignment]
        logger.debug("KillSwitch not importable — firewall HALT will log only")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class FirewallConfig:
    """Tunable parameters — all overridable via environment variables."""

    # Gate 1: slippage
    #: Maximum allowed per-fill slippage in basis-points (1 bps = 0.01 %).
    max_slippage_bps: float = float(os.environ.get("NIJA_MAX_SLIPPAGE_BPS", "50"))

    # Gate 2: venue health
    #: Rolling-window size (events) for each venue metric deque.
    venue_window_size: int = int(os.environ.get("NIJA_VENUE_WINDOW_SIZE", "50"))
    #: Score below which a venue is disabled.
    min_healthy_score: float = float(os.environ.get("NIJA_MIN_VENUE_SCORE", "40.0"))
    #: Score above which a disabled venue is re-enabled.
    recovery_score: float = float(os.environ.get("NIJA_VENUE_RECOVERY_SCORE", "60.0"))

    # Gate 3: fill anomaly
    #: Rolling window of fill residuals used for z-score per symbol.
    fill_residual_window: int = int(os.environ.get("NIJA_FILL_RESIDUAL_WINDOW", "20"))
    #: Sigma threshold beyond which a fill is flagged as anomalous.
    anomaly_sigma_threshold: float = float(os.environ.get("NIJA_ANOMALY_SIGMA", "3.0"))

    # Gate 4: auto-degrade
    #: Fraction of known venues disabled before mode escalation.
    degraded_venue_fraction: float = float(
        os.environ.get("NIJA_DEGRADED_VENUE_FRACTION", "0.5")
    )
    #: Consecutive flagged fills → SAFE_MODE.
    safe_mode_anomaly_threshold: int = int(
        os.environ.get("NIJA_SAFE_MODE_ANOMALY_THRESHOLD", "3")
    )
    #: Consecutive flagged fills → HALT.
    halt_anomaly_threshold: int = int(
        os.environ.get("NIJA_HALT_ANOMALY_THRESHOLD", "6")
    )
    #: Consecutive clean fills needed to step down one mode level.
    recovery_clean_fills: int = int(
        os.environ.get("NIJA_RECOVERY_CLEAN_FILLS", "5")
    )


# ---------------------------------------------------------------------------
# ExecutionMode
# ---------------------------------------------------------------------------

class ExecutionMode(str, Enum):
    LIVE      = "LIVE"       # Full trading — all entries allowed
    WATCHFUL  = "WATCHFUL"   # Elevated alerts; trading continues
    SAFE_MODE = "SAFE_MODE"  # Entries blocked; exits/stops only; 25 % sizing
    HALT      = "HALT"       # All trading stopped; KillSwitch activated

    def allow_new_entries(self) -> bool:
        return self in (ExecutionMode.LIVE, ExecutionMode.WATCHFUL)

    def position_size_multiplier(self) -> float:
        return {
            ExecutionMode.LIVE:      1.00,
            ExecutionMode.WATCHFUL:  0.75,
            ExecutionMode.SAFE_MODE: 0.25,
            ExecutionMode.HALT:      0.00,
        }.get(self, 0.0)


# ---------------------------------------------------------------------------
# VenueHealthTracker — per-venue rolling score (Gate 2)
# ---------------------------------------------------------------------------

@dataclass
class _VenueMetrics:
    """Rolling event deques for a single venue."""
    api_outcomes:   Deque[bool] = field(default_factory=lambda: deque(maxlen=50))
    order_outcomes: Deque[bool] = field(default_factory=lambda: deque(maxlen=50))
    fill_quality:   Deque[bool] = field(default_factory=lambda: deque(maxlen=50))
    disabled: bool = False


class VenueHealthTracker:
    """Computes a 0–100 composite score for each venue and gates access."""

    _W_API   = 0.60
    _W_ORDER = 0.25
    _W_FILL  = 0.15

    def __init__(self, config: FirewallConfig) -> None:
        self._cfg = config
        self._venues: Dict[str, _VenueMetrics] = {}
        self._lock = threading.Lock()

    def record_api_call(self, venue: str, success: bool) -> None:
        with self._lock:
            m = self._get_or_create(venue)
            m.api_outcomes.append(success)
            self._maybe_update_disabled(venue, m)

    def record_order_result(self, venue: str, accepted: bool) -> None:
        with self._lock:
            m = self._get_or_create(venue)
            m.order_outcomes.append(accepted)
            self._maybe_update_disabled(venue, m)

    def record_fill_quality(self, venue: str, ok: bool) -> None:
        with self._lock:
            m = self._get_or_create(venue)
            m.fill_quality.append(ok)
            self._maybe_update_disabled(venue, m)

    def get_score(self, venue: str) -> float:
        with self._lock:
            m = self._venues.get(venue)
            return 100.0 if m is None else self._compute_score(m)

    def is_healthy(self, venue: str) -> bool:
        with self._lock:
            m = self._venues.get(venue)
            return True if m is None else not m.disabled

    def get_all_scores(self) -> Dict[str, float]:
        with self._lock:
            return {v: self._compute_score(m) for v, m in self._venues.items()}

    def degraded_fraction(self) -> float:
        """Fraction of known venues that are currently disabled."""
        with self._lock:
            if not self._venues:
                return 0.0
            disabled = sum(1 for m in self._venues.values() if m.disabled)
            return disabled / len(self._venues)

    # ── internal ──────────────────────────────────────────────────────────

    def _get_or_create(self, venue: str) -> _VenueMetrics:
        if venue not in self._venues:
            maxlen = self._cfg.venue_window_size
            self._venues[venue] = _VenueMetrics(
                api_outcomes=deque(maxlen=maxlen),
                order_outcomes=deque(maxlen=maxlen),
                fill_quality=deque(maxlen=maxlen),
            )
        return self._venues[venue]

    @staticmethod
    def _rate(buf: Deque[bool]) -> float:
        return 1.0 if not buf else sum(buf) / len(buf)

    def _compute_score(self, m: _VenueMetrics) -> float:
        raw = (
            self._W_API   * self._rate(m.api_outcomes)
            + self._W_ORDER * self._rate(m.order_outcomes)
            + self._W_FILL  * self._rate(m.fill_quality)
        )
        return round(raw * 100.0, 1)

    def _maybe_update_disabled(self, venue: str, m: _VenueMetrics) -> None:
        score = self._compute_score(m)
        if not m.disabled and score < self._cfg.min_healthy_score:
            m.disabled = True
            logger.warning(
                "⚠️ ExecFirewall: venue '%s' DISABLED — "
                "health score %.1f < %.1f threshold",
                venue, score, self._cfg.min_healthy_score,
            )
        elif m.disabled and score >= self._cfg.recovery_score:
            m.disabled = False
            logger.info(
                "✅ ExecFirewall: venue '%s' RE-ENABLED — "
                "health score %.1f ≥ %.1f recovery threshold",
                venue, score, self._cfg.recovery_score,
            )


# ---------------------------------------------------------------------------
# FillAnomalyDetector — z-score on fill residuals per symbol (Gate 3)
# ---------------------------------------------------------------------------

class FillAnomalyDetector:
    """Detects abnormal fill prices via a rolling z-score per symbol."""

    def __init__(self, window: int, sigma_threshold: float) -> None:
        self._window = max(window, 5)
        self._sigma = sigma_threshold
        self._residuals: Dict[str, Deque[float]] = {}
        self._lock = threading.Lock()

    def check_and_record(
        self,
        symbol: str,
        expected_price: float,
        fill_price: float,
    ) -> Tuple[bool, float]:
        """
        Record the fill residual and return (is_anomalous, z_score).

        Returns (False, 0.0) when fewer than 5 samples are available — not
        enough data for a meaningful z-score.
        """
        if expected_price <= 0:
            return False, 0.0

        residual_bps = (fill_price - expected_price) / expected_price * 10_000.0

        with self._lock:
            buf = self._residuals.setdefault(symbol, deque(maxlen=self._window))
            buf.append(residual_bps)

            if len(buf) < 5:
                return False, 0.0

            mean = sum(buf) / len(buf)
            variance = sum((x - mean) ** 2 for x in buf) / len(buf)
            std = math.sqrt(variance) if variance > 0 else 0.0
            if std == 0.0:
                return False, 0.0

            z = (residual_bps - mean) / std
            return abs(z) > self._sigma, round(z, 2)


# ---------------------------------------------------------------------------
# ExecutionRiskFirewall — orchestrator
# ---------------------------------------------------------------------------

class ExecutionRiskFirewall:
    """
    Central execution risk enforcement layer.

    Thread-safe singleton — obtain via :func:`get_execution_risk_firewall`.
    """

    def __init__(self, config: Optional[FirewallConfig] = None) -> None:
        self._cfg = config or FirewallConfig()
        self._lock = threading.Lock()
        self._venue_tracker    = VenueHealthTracker(self._cfg)
        self._anomaly_detector = FillAnomalyDetector(
            window=self._cfg.fill_residual_window,
            sigma_threshold=self._cfg.anomaly_sigma_threshold,
        )
        self._mode: ExecutionMode = ExecutionMode.LIVE
        self._consecutive_anomalies: int = 0
        self._consecutive_clean_fills: int = 0
        # Event log — last 100 entries for monitoring/reporting
        self._events: List[Dict] = []

        logger.info(
            "✅ ExecutionRiskFirewall initialised "
            "(max_slippage=%.0f bps, min_venue_score=%.0f, "
            "safe_mode_after=%d anomalies, halt_after=%d anomalies)",
            self._cfg.max_slippage_bps,
            self._cfg.min_healthy_score,
            self._cfg.safe_mode_anomaly_threshold,
            self._cfg.halt_anomaly_threshold,
        )

    # ------------------------------------------------------------------
    # Feed methods — call these from broker/execution paths
    # ------------------------------------------------------------------

    def record_api_call(
        self, venue: str, latency_ms: float, success: bool
    ) -> None:
        """Feed every API call result into the venue health tracker (Gate 2)."""
        self._venue_tracker.record_api_call(venue, success)
        self._maybe_escalate_mode()

    def record_order_result(self, venue: str, accepted: bool) -> None:
        """Feed every order acceptance/rejection result (Gate 2)."""
        self._venue_tracker.record_order_result(venue, accepted)
        self._maybe_escalate_mode()

    def record_fill(
        self,
        venue: str,
        symbol: str,
        expected_price: float,
        fill_price: float,
        side: str = "buy",
    ) -> bool:
        """
        Record an actual fill and run Gates 1, 3, and 4.

        Args:
            venue:          Exchange identifier (e.g. ``"coinbase"``).
            symbol:         Instrument symbol (e.g. ``"BTC-USD"``).
            expected_price: Mid-price or signal price at order stamp time.
            fill_price:     Actual execution price returned by the broker.
            side:           ``"buy"`` or ``"sell"``.

        Returns:
            ``True`` when the fill is within normal bounds; ``False`` when
            it is flagged as anomalous or slippage-excessive.
        """
        if expected_price <= 0 or fill_price <= 0:
            return True  # Cannot evaluate — pass through

        # Gate 1: per-trade slippage ──────────────────────────────────────
        slippage_bps = abs(fill_price - expected_price) / expected_price * 10_000.0
        slippage_ok  = slippage_bps <= self._cfg.max_slippage_bps

        if not slippage_ok:
            logger.warning(
                "⚠️ ExecFirewall SLIPPAGE: %s@%s fill=%.6f expected=%.6f "
                "slippage=%.1f bps (max=%.0f bps)",
                symbol, venue, fill_price, expected_price,
                slippage_bps, self._cfg.max_slippage_bps,
            )

        # Gate 3: fill anomaly (z-score) ──────────────────────────────────
        is_anomalous, z_score = self._anomaly_detector.check_and_record(
            symbol, expected_price, fill_price
        )
        if is_anomalous:
            logger.warning(
                "⚠️ ExecFirewall FILL ANOMALY: %s@%s z=%.2f "
                "fill=%.6f expected=%.6f side=%s",
                symbol, venue, z_score, fill_price, expected_price, side,
            )

        fill_ok = slippage_ok and not is_anomalous
        self._venue_tracker.record_fill_quality(venue, fill_ok)

        # Gate 4: auto-degrade ────────────────────────────────────────────
        with self._lock:
            if not fill_ok:
                self._consecutive_anomalies += 1
                self._consecutive_clean_fills = 0
            else:
                self._consecutive_clean_fills += 1
                if self._consecutive_clean_fills >= self._cfg.recovery_clean_fills:
                    self._try_step_down()

        self._maybe_escalate_mode()

        self._log_event({
            "ts":           datetime.now(timezone.utc).isoformat(),
            "type":         "fill",
            "venue":        venue,
            "symbol":       symbol,
            "side":         side,
            "slippage_bps": round(slippage_bps, 2),
            "z_score":      z_score,
            "fill_ok":      fill_ok,
        })
        return fill_ok

    # ------------------------------------------------------------------
    # Query methods — call these before placing orders
    # ------------------------------------------------------------------

    def get_execution_mode(self) -> ExecutionMode:
        """Return the current system-level execution mode."""
        with self._lock:
            return self._mode

    def is_venue_healthy(self, venue: str) -> bool:
        """Return ``False`` when the venue is currently disabled."""
        return self._venue_tracker.is_healthy(venue)

    def get_position_size_multiplier(self) -> float:
        """Return sizing multiplier for the current mode (0.0–1.0)."""
        with self._lock:
            return self._mode.position_size_multiplier()

    def get_report(self) -> Dict:
        """Return a status snapshot for monitoring / health endpoints."""
        with self._lock:
            mode = self._mode
            anomalies = self._consecutive_anomalies
            clean = self._consecutive_clean_fills
        return {
            "mode":                     mode.value,
            "consecutive_anomalies":    anomalies,
            "consecutive_clean_fills":  clean,
            "venue_scores":             self._venue_tracker.get_all_scores(),
            "disabled_venues": [
                v for v, m in self._venue_tracker._venues.items() if m.disabled
            ],
            "degraded_fraction": round(self._venue_tracker.degraded_fraction(), 2),
            "recent_events":     list(self._events[-5:]),
        }

    # ------------------------------------------------------------------
    # Internal — mode escalation / step-down
    # ------------------------------------------------------------------

    def _maybe_escalate_mode(self) -> None:
        with self._lock:
            old_mode = self._mode
            new_mode = self._compute_target_mode()
            if self._mode_order(new_mode) > self._mode_order(old_mode):
                self._mode = new_mode
                logger.warning(
                    "🚨 ExecFirewall MODE: %s → %s "
                    "(%d consecutive anomalies, venue degraded_fraction=%.2f)",
                    old_mode.value, new_mode.value,
                    self._consecutive_anomalies,
                    self._venue_tracker.degraded_fraction(),
                )
                if new_mode == ExecutionMode.HALT:
                    self._fire_kill_switch(
                        f"ExecutionRiskFirewall: {self._consecutive_anomalies} "
                        "consecutive fill anomalies — entering HALT"
                    )

    def _compute_target_mode(self) -> ExecutionMode:
        """Derive the warranted mode from current evidence (called under lock)."""
        anomalies     = self._consecutive_anomalies
        degraded_frac = self._venue_tracker.degraded_fraction()

        if (anomalies >= self._cfg.halt_anomaly_threshold
                or degraded_frac >= self._cfg.degraded_venue_fraction):
            return ExecutionMode.HALT

        if (anomalies >= self._cfg.safe_mode_anomaly_threshold
                or degraded_frac >= self._cfg.degraded_venue_fraction * 0.5):
            return ExecutionMode.SAFE_MODE

        if anomalies >= max(1, self._cfg.safe_mode_anomaly_threshold // 2):
            return ExecutionMode.WATCHFUL

        return ExecutionMode.LIVE

    def _try_step_down(self) -> None:
        """Step mode down one level after enough clean fills (called under lock)."""
        _order = [
            ExecutionMode.LIVE,
            ExecutionMode.WATCHFUL,
            ExecutionMode.SAFE_MODE,
            ExecutionMode.HALT,
        ]
        if self._mode == ExecutionMode.LIVE:
            return
        idx = _order.index(self._mode)
        self._mode = _order[idx - 1]
        self._consecutive_anomalies = max(0, self._consecutive_anomalies - 1)
        self._consecutive_clean_fills = 0
        logger.info(
            "✅ ExecFirewall MODE stepped down → %s "
            "(%d clean fills accumulated)",
            self._mode.value, self._cfg.recovery_clean_fills,
        )

    @staticmethod
    def _mode_order(mode: ExecutionMode) -> int:
        return {
            ExecutionMode.LIVE:      0,
            ExecutionMode.WATCHFUL:  1,
            ExecutionMode.SAFE_MODE: 2,
            ExecutionMode.HALT:      3,
        }.get(mode, 0)

    @staticmethod
    def _fire_kill_switch(reason: str) -> None:
        if not _KS_AVAILABLE or _KillSwitch is None:
            logger.critical("🛑 ExecFirewall HALT (KillSwitch unavailable): %s", reason)
            return
        try:
            ks = _KillSwitch()
            ks.activate(reason=reason, source="ExecutionRiskFirewall")
            logger.critical("🛑 ExecFirewall: KillSwitch ACTIVATED — %s", reason)
        except Exception as _e:
            logger.critical(
                "🛑 ExecFirewall HALT — KillSwitch fire failed (%s): %s", _e, reason
            )

    def _log_event(self, event: Dict) -> None:
        self._events.append(event)
        if len(self._events) > 100:
            self._events.pop(0)


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------

_fw_instance: Optional[ExecutionRiskFirewall] = None
_fw_lock = threading.Lock()


def get_execution_risk_firewall(
    config: Optional[FirewallConfig] = None,
) -> ExecutionRiskFirewall:
    """Return the process-wide ``ExecutionRiskFirewall`` singleton."""
    global _fw_instance
    if _fw_instance is None:
        with _fw_lock:
            if _fw_instance is None:
                _fw_instance = ExecutionRiskFirewall(config=config)
    return _fw_instance
