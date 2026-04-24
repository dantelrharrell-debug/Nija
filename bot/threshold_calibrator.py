"""
NIJA Threshold Calibrator
==========================

Analyses observed broker-behaviour patterns (API latency, error-rate,
order-rejection rate, fill rate) together with historical trade P&L to
produce evidence-based threshold recommendations for every kill-switch
and risk-governor gate.

Why this matters
----------------
Default kill-switch thresholds are conservative estimates.  After running
against a real broker for even a few days, you accumulate enough telemetry
to answer:

  "Should my API-error-rate gate fire at 5 % or 10 %?"
  "Is my daily-loss limit of 3 % leaving money on the table, or is it too
   loose for my actual volatility regime?"
  "Are my consecutive-loss limits calibrated to my real win-rate distribution?"

The calibrator addresses all three by:

  1. **Baseline estimation** – compute natural broker-side error rates and
     latency percentiles from a sample of observations.

  2. **P&L-driven threshold suggestions** – given historical trades,
     recommend daily-loss and consecutive-loss limits that correspond to
     the 5th-percentile drawdown seen in Monte Carlo simulation.

  3. **Alert threshold fine-tuning** – suggest per-category alert cooldown
     periods that prevent alert fatigue while still catching real anomalies.

  4. **One-click apply** – optionally write the calibrated values directly
     into a ``calibration_profile.json`` that operators can review and then
     apply to the live modules.

Usage
-----
    from bot.threshold_calibrator import ThresholdCalibrator

    cal = ThresholdCalibrator()

    # Feed broker observations
    cal.record_api_call(latency_ms=42.0, success=True)
    cal.record_api_call(latency_ms=3800.0, success=False)
    ...

    # Feed historical trades
    cal.record_trade(pnl_usd=120.0, is_win=True)
    cal.record_trade(pnl_usd=-80.0, is_win=False)
    ...

    # Get calibrated recommendations
    profile = cal.calibrate()
    print(profile.summary())

    # Optionally persist the recommendations
    profile.save("calibration_profile.json")

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import json
import logging
import math
import random
import statistics
import threading
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("nija.threshold_calibrator")

# ---------------------------------------------------------------------------
# Default broker-behaviour baselines (used when < MIN_SAMPLES observations
# have been recorded – prevents division-by-zero on a fresh deployment).
# ---------------------------------------------------------------------------

MIN_SAMPLES: int = 10                          # minimum observations before calibration
DEFAULT_LATENCY_P95_MS: float = 500.0          # assumed p95 API latency
DEFAULT_ERROR_RATE: float = 0.02               # assumed 2% baseline error rate
DEFAULT_REJECTION_RATE: float = 0.03           # assumed 3% order rejection rate

# Monte Carlo configuration for P&L-driven gate calibration
MC_PATHS: int = 1_000
MC_TRADES_PER_PATH: int = 50

# Multipliers that convert raw percentiles into threshold suggestions
# e.g. if natural p95 latency is 500 ms, we set the latency gate at 3× → 1 500 ms
LATENCY_GATE_MULTIPLIER: float = 3.0
ERROR_RATE_GATE_MULTIPLIER: float = 3.0        # trigger gate at 3× natural error rate
REJECTION_RATE_GATE_MULTIPLIER: float = 3.0

# Clamp bounds for recommended thresholds
MAX_ERROR_RATE_GATE_PCT: float = 25.0          # never set error-rate gate above 25%
MIN_ERROR_RATE_GATE_PCT: float = 3.0           # never set error-rate gate below 3%
MAX_LATENCY_GATE_MS: float = 10_000.0          # never set latency gate above 10 s
MIN_LATENCY_GATE_MS: float = 300.0             # never set latency gate below 300 ms
MAX_REJECTION_RATE_GATE_PCT: float = 20.0      # never set rejection gate above 20%
MIN_REJECTION_RATE_GATE_PCT: float = 5.0       # never set rejection gate below 5%


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class BrokerObservation:
    """Single recorded broker interaction."""
    latency_ms: float
    success: bool
    order_rejected: bool = False
    fill_received: bool = True


@dataclass
class TradeObservation:
    """Single recorded trade result."""
    pnl_usd: float
    is_win: bool


@dataclass
class CalibrationProfile:
    """
    Calibrated threshold recommendations.

    All values are *suggestions* — operators should review them before
    applying to production.
    """

    timestamp: str

    # ── GlobalRiskGovernor gates ──────────────────────────────────────────
    recommended_daily_loss_pct: float           # e.g. 3.5
    recommended_consecutive_losses: int         # e.g. 6
    recommended_max_volatility_ratio: float     # e.g. 2.8

    # ── KillSwitch / exchange-health gates ───────────────────────────────
    recommended_api_error_rate_pct: float       # e.g. 8.0 (= 8%)
    recommended_latency_p95_ms: float           # e.g. 1200 ms
    recommended_order_rejection_rate_pct: float # e.g. 6.0

    # ── AlertManager cooldowns (seconds) ─────────────────────────────────
    recommended_alert_cooldown_risk: int        # RISK_LIMIT_BREACH category
    recommended_alert_cooldown_execution: int   # EXECUTION_ANOMALY category
    recommended_alert_cooldown_strategy: int    # STRATEGY_PERFORMANCE category

    # ── Confidence metadata ───────────────────────────────────────────────
    broker_samples: int
    trade_samples: int
    confidence: str                             # LOW / MEDIUM / HIGH

    # ── Derived statistics (informational) ───────────────────────────────
    observed_error_rate_pct: float
    observed_latency_p95_ms: float
    observed_rejection_rate_pct: float
    observed_daily_loss_p5_pct: float           # 5th-percentile daily P&L
    observed_consecutive_loss_p95: int          # 95th-percentile streak

    # Raw change notes
    change_notes: List[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            "=" * 64,
            "  NIJA Threshold Calibration Profile",
            "=" * 64,
            f"  Timestamp    : {self.timestamp}",
            f"  Confidence   : {self.confidence}  "
            f"(broker={self.broker_samples} samples, "
            f"trades={self.trade_samples} samples)",
            "",
            "  ── GlobalRiskGovernor recommended gates ──",
            f"  Daily Loss Limit     : {self.recommended_daily_loss_pct:.2f}%",
            f"  Consecutive Losses   : {self.recommended_consecutive_losses}",
            f"  Max Volatility Ratio : {self.recommended_max_volatility_ratio:.2f}×",
            "",
            "  ── KillSwitch / Exchange Health gates ──",
            f"  API Error Rate Gate  : {self.recommended_api_error_rate_pct:.1f}%",
            f"  Latency P95 Gate     : {self.recommended_latency_p95_ms:.0f} ms",
            f"  Order Rejection Gate : {self.recommended_order_rejection_rate_pct:.1f}%",
            "",
            "  ── AlertManager Cooldowns ──",
            f"  Risk Limit Breach    : {self.recommended_alert_cooldown_risk}s",
            f"  Execution Anomaly    : {self.recommended_alert_cooldown_execution}s",
            f"  Strategy Performance : {self.recommended_alert_cooldown_strategy}s",
            "",
            "  ── Observed baselines ──",
            f"  API Error Rate       : {self.observed_error_rate_pct:.2f}%",
            f"  Latency P95          : {self.observed_latency_p95_ms:.0f} ms",
            f"  Order Rejection Rate : {self.observed_rejection_rate_pct:.2f}%",
            f"  Daily Loss P5        : {self.observed_daily_loss_p5_pct:.2f}%",
            f"  Consec. Loss P95     : {self.observed_consecutive_loss_p95}",
            "",
        ]
        if self.change_notes:
            lines.append("  ── Calibration notes ──")
            for note in self.change_notes:
                lines.append(f"  • {note}")
            lines.append("")
        lines.append("=" * 64)
        return "\n".join(lines)

    def save(self, path: str = "calibration_profile.json") -> None:
        """Persist the calibration profile as JSON."""
        out = Path(path)
        data = asdict(self)
        out.write_text(json.dumps(data, indent=2))
        logger.info("CalibrationProfile saved to %s", out)

    def to_dict(self) -> Dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Main calibrator class
# ---------------------------------------------------------------------------

class ThresholdCalibrator:
    """
    Collects broker observations and trade history, then produces a
    :class:`CalibrationProfile` with evidence-based threshold recommendations.
    """

    def __init__(self, seed: Optional[int] = None) -> None:
        self._lock = threading.Lock()
        self._broker_obs: List[BrokerObservation] = []
        self._trade_obs: List[TradeObservation] = []
        self._rng = random.Random(seed)

    # ------------------------------------------------------------------
    # Data ingestion
    # ------------------------------------------------------------------

    def record_api_call(
        self,
        latency_ms: float,
        success: bool,
        order_rejected: bool = False,
        fill_received: bool = True,
    ) -> None:
        """Record a single broker API interaction."""
        with self._lock:
            self._broker_obs.append(
                BrokerObservation(
                    latency_ms=latency_ms,
                    success=success,
                    order_rejected=order_rejected,
                    fill_received=fill_received,
                )
            )

    def record_trade(self, pnl_usd: float, is_win: bool) -> None:
        """Record a completed trade result."""
        with self._lock:
            self._trade_obs.append(TradeObservation(pnl_usd=pnl_usd, is_win=is_win))

    def load_from_dict(self, data: Dict) -> None:
        """
        Bulk-load observations from a dict (e.g. from a saved JSON file).

        Expected format::

            {
                "broker": [{"latency_ms": 42, "success": true, ...}, ...],
                "trades": [{"pnl_usd": 120, "is_win": true}, ...],
            }
        """
        with self._lock:
            for obs in data.get("broker", []):
                self._broker_obs.append(BrokerObservation(**obs))
            for obs in data.get("trades", []):
                self._trade_obs.append(TradeObservation(**obs))
        logger.info(
            "Loaded %d broker and %d trade observations",
            len(data.get("broker", [])), len(data.get("trades", [])),
        )

    # ------------------------------------------------------------------
    # Core calibration logic
    # ------------------------------------------------------------------

    def calibrate(self) -> CalibrationProfile:
        """
        Analyse all recorded observations and return calibrated threshold
        recommendations.
        """
        with self._lock:
            broker_obs = list(self._broker_obs)
            trade_obs = list(self._trade_obs)

        # ── Broker-side statistics ────────────────────────────────────────
        (
            error_rate_pct,
            latency_p95_ms,
            rejection_rate_pct,
        ) = self._compute_broker_stats(broker_obs)

        # ── Trade P&L statistics via Monte Carlo ─────────────────────────
        (
            daily_loss_p5_pct,
            consecutive_loss_p95,
        ) = self._compute_pnl_stats(trade_obs)

        # ── Build recommendations ─────────────────────────────────────────
        rec_daily_loss = self._recommend_daily_loss(daily_loss_p5_pct, trade_obs)
        rec_consec     = self._recommend_consecutive_losses(consecutive_loss_p95)
        rec_vol_ratio  = self._recommend_volatility_ratio(trade_obs)
        rec_error_rate = min(MAX_ERROR_RATE_GATE_PCT, max(MIN_ERROR_RATE_GATE_PCT, error_rate_pct * ERROR_RATE_GATE_MULTIPLIER))
        rec_latency    = min(MAX_LATENCY_GATE_MS, max(MIN_LATENCY_GATE_MS, latency_p95_ms * LATENCY_GATE_MULTIPLIER))
        rec_rejection  = min(MAX_REJECTION_RATE_GATE_PCT, max(MIN_REJECTION_RATE_GATE_PCT, rejection_rate_pct * REJECTION_RATE_GATE_MULTIPLIER))

        # ── Alert cooldowns – driven by event frequency ───────────────────
        rec_risk_cd       = self._recommend_cooldown(error_rate_pct, base=300)
        rec_execution_cd  = self._recommend_cooldown(rejection_rate_pct, base=180)
        rec_strategy_cd   = 600   # strategy alerts need more soak time

        # ── Confidence level ─────────────────────────────────────────────
        confidence = self._assess_confidence(len(broker_obs), len(trade_obs))

        # ── Change notes ─────────────────────────────────────────────────
        notes = self._build_notes(
            error_rate_pct, latency_p95_ms, rejection_rate_pct,
            daily_loss_p5_pct, consecutive_loss_p95,
            rec_daily_loss, rec_consec,
            len(broker_obs), len(trade_obs),
        )

        profile = CalibrationProfile(
            timestamp=datetime.now(timezone.utc).isoformat(),
            recommended_daily_loss_pct=round(rec_daily_loss, 2),
            recommended_consecutive_losses=rec_consec,
            recommended_max_volatility_ratio=round(rec_vol_ratio, 2),
            recommended_api_error_rate_pct=round(rec_error_rate, 2),
            recommended_latency_p95_ms=round(rec_latency, 1),
            recommended_order_rejection_rate_pct=round(rec_rejection, 2),
            recommended_alert_cooldown_risk=rec_risk_cd,
            recommended_alert_cooldown_execution=rec_execution_cd,
            recommended_alert_cooldown_strategy=rec_strategy_cd,
            broker_samples=len(broker_obs),
            trade_samples=len(trade_obs),
            confidence=confidence,
            observed_error_rate_pct=round(error_rate_pct, 3),
            observed_latency_p95_ms=round(latency_p95_ms, 1),
            observed_rejection_rate_pct=round(rejection_rate_pct, 3),
            observed_daily_loss_p5_pct=round(daily_loss_p5_pct, 3),
            observed_consecutive_loss_p95=consecutive_loss_p95,
            change_notes=notes,
        )
        logger.info(
            "Calibration complete — confidence=%s, daily_loss=%.2f%%, "
            "consec=%d, error_rate=%.2f%%",
            confidence, rec_daily_loss, rec_consec, rec_error_rate,
        )
        return profile

    # ------------------------------------------------------------------
    # Statistical helpers
    # ------------------------------------------------------------------

    def _compute_broker_stats(
        self, obs: List[BrokerObservation]
    ) -> Tuple[float, float, float]:
        """Return (error_rate_pct, latency_p95_ms, rejection_rate_pct)."""
        if not obs:
            return DEFAULT_ERROR_RATE * 100, DEFAULT_LATENCY_P95_MS, DEFAULT_REJECTION_RATE * 100

        n = len(obs)
        error_rate_pct     = sum(1 for o in obs if not o.success) / n * 100
        rejection_rate_pct = sum(1 for o in obs if o.order_rejected) / n * 100

        latencies = sorted(o.latency_ms for o in obs)
        p95_idx   = max(0, int(0.95 * len(latencies)) - 1)
        latency_p95_ms = latencies[p95_idx] if latencies else DEFAULT_LATENCY_P95_MS

        return error_rate_pct, latency_p95_ms, rejection_rate_pct

    def _compute_pnl_stats(
        self, trades: List[TradeObservation]
    ) -> Tuple[float, int]:
        """
        Run Monte Carlo to estimate 5th-percentile daily loss % and
        95th-percentile consecutive-loss streak.

        Returns (daily_loss_p5_pct, consecutive_loss_p95).
        """
        if len(trades) < MIN_SAMPLES:
            # Fall back to conservative defaults
            return 2.0, 4

        # Estimate per-trade statistics from the sample
        wins  = [t.pnl_usd for t in trades if t.is_win]
        losses= [abs(t.pnl_usd) for t in trades if not t.is_win]
        win_rate = len(wins) / len(trades)
        avg_win  = statistics.mean(wins)  if wins  else 50.0
        avg_loss = statistics.mean(losses) if losses else 30.0

        # ── Monte Carlo P&L simulation ────────────────────────────────────
        daily_pnl_pcts: List[float] = []
        consec_streaks: List[int] = []
        capital_ref = 10_000.0       # normalisation base

        for _ in range(MC_PATHS):
            daily_pnl = 0.0
            streak = 0
            max_streak = 0
            for _ in range(MC_TRADES_PER_PATH):
                if self._rng.random() < win_rate:
                    pnl = avg_win * self._rng.uniform(0.5, 1.8)
                    daily_pnl += pnl
                    streak = 0
                else:
                    pnl = -avg_loss * self._rng.uniform(0.5, 1.8)
                    daily_pnl += pnl
                    streak += 1
                    max_streak = max(max_streak, streak)
            daily_pnl_pcts.append(daily_pnl / capital_ref * 100)
            consec_streaks.append(max_streak)

        daily_pnl_pcts.sort()
        idx5 = max(0, int(0.05 * MC_PATHS) - 1)
        daily_loss_p5_pct = abs(min(0.0, daily_pnl_pcts[idx5]))

        consec_streaks.sort()
        idx95 = min(MC_PATHS - 1, int(0.95 * MC_PATHS))
        consecutive_loss_p95 = consec_streaks[idx95]

        return daily_loss_p5_pct, consecutive_loss_p95

    # ------------------------------------------------------------------
    # Recommendation builders
    # ------------------------------------------------------------------

    def _recommend_daily_loss(
        self, daily_loss_p5_pct: float, trades: List[TradeObservation]
    ) -> float:
        """
        Recommend a daily-loss limit that is the larger of:
        * 1.5× the observed 5th-percentile daily drawdown (data-driven)
        * 2.0%  (absolute floor — never be more lenient than 2%)
        * capped at 6.0%
        """
        data_driven = daily_loss_p5_pct * 1.5
        return max(2.0, min(6.0, data_driven if daily_loss_p5_pct > 0 else 3.0))

    def _recommend_consecutive_losses(self, p95_streak: int) -> int:
        """
        Recommend a consecutive-loss limit equal to the observed p95 streak,
        clamped to [3, 10].
        """
        return max(3, min(10, p95_streak))

    def _recommend_volatility_ratio(self, trades: List[TradeObservation]) -> float:
        """
        A simple heuristic: if the trade sample shows wide variance in P&L,
        suggest a tighter volatility gate.
        """
        if len(trades) < MIN_SAMPLES:
            return 2.5  # default
        pnls = [t.pnl_usd for t in trades]
        std  = statistics.stdev(pnls) if len(pnls) > 1 else 0.0
        mean = abs(statistics.mean(pnls)) or 1.0
        cv   = std / mean   # coefficient of variation
        # High CV → tighter vol gate
        if cv > 3.0:
            return 2.0
        elif cv > 1.5:
            return 2.5
        else:
            return 3.0

    def _recommend_cooldown(self, event_rate_pct: float, base: int = 300) -> int:
        """
        Higher event rates → shorter cooldowns (more events → alerts must fire
        more often to remain meaningful).
        High rate means we need alerts to fire; low rate means we can afford
        longer cooldowns.
        """
        if event_rate_pct < 1.0:
            return base * 2    # very rare events → long cooldown OK
        elif event_rate_pct < 5.0:
            return base
        else:
            return max(60, base // 2)   # frequent errors → shorter cooldown

    # ------------------------------------------------------------------
    # Utility helpers
    # ------------------------------------------------------------------

    def _assess_confidence(self, n_broker: int, n_trades: int) -> str:
        if n_broker >= 500 and n_trades >= 100:
            return "HIGH"
        elif n_broker >= 50 or n_trades >= 20:
            return "MEDIUM"
        else:
            return "LOW"

    def _build_notes(
        self,
        error_rate_pct: float,
        latency_p95_ms: float,
        rejection_rate_pct: float,
        daily_loss_p5_pct: float,
        consecutive_loss_p95: int,
        rec_daily_loss: float,
        rec_consec: int,
        n_broker: int,
        n_trades: int,
    ) -> List[str]:
        notes: List[str] = []
        if n_broker < MIN_SAMPLES:
            notes.append(
                f"Only {n_broker} broker observations (need ≥{MIN_SAMPLES}); "
                "broker-side gates use safe defaults."
            )
        if n_trades < MIN_SAMPLES:
            notes.append(
                f"Only {n_trades} trade observations (need ≥{MIN_SAMPLES}); "
                "P&L-driven gates use Monte Carlo defaults."
            )
        if error_rate_pct > 5.0:
            notes.append(
                f"Observed API error rate is {error_rate_pct:.1f}% — "
                "consider investigating broker connectivity."
            )
        if latency_p95_ms > 2_000:
            notes.append(
                f"P95 API latency is {latency_p95_ms:.0f} ms — "
                "high latency may cause slippage; verify network path."
            )
        if rejection_rate_pct > 5.0:
            notes.append(
                f"Order rejection rate is {rejection_rate_pct:.1f}% — "
                "review order sizing or margin requirements."
            )
        notes.append(
            f"Recommended daily-loss gate: {rec_daily_loss:.2f}% "
            f"(based on P5 drawdown={daily_loss_p5_pct:.2f}% × 1.5)."
        )
        notes.append(
            f"Recommended consecutive-loss gate: {rec_consec} "
            f"(based on P95 streak={consecutive_loss_p95})."
        )
        return notes

    # ------------------------------------------------------------------
    # Optional: apply recommendations to live modules
    # ------------------------------------------------------------------

    def apply_to_governor(self, profile: CalibrationProfile) -> bool:
        """
        Attempt to push calibrated values into the live GlobalRiskGovernor.

        Returns True if successful.

        Note: The GlobalRiskGovernor is instantiated with fixed config at
        startup.  This method re-instantiates the singleton with new config
        values — only safe to call before the first trade of a session.
        """
        try:
            from bot.global_risk_governor import GlobalRiskGovernor, GovernorConfig
            import bot.global_risk_governor as _gov_module

            new_config = GovernorConfig(
                max_daily_loss_pct=profile.recommended_daily_loss_pct,
                max_consecutive_losses=profile.recommended_consecutive_losses,
                max_volatility_multiplier=profile.recommended_max_volatility_ratio,
            )
            with _gov_module._governor_lock:
                _gov_module._governor_instance = GlobalRiskGovernor(new_config)
            logger.info(
                "CalibrationProfile applied to GlobalRiskGovernor — "
                "daily_loss=%.2f%%, consec=%d, vol_ratio=%.2f",
                profile.recommended_daily_loss_pct,
                profile.recommended_consecutive_losses,
                profile.recommended_max_volatility_ratio,
            )
            return True
        except Exception as exc:
            logger.error("Failed to apply profile to GlobalRiskGovernor: %s", exc)
            return False

    def apply_to_alert_manager(self, profile: CalibrationProfile) -> bool:
        """Push calibrated cooldown values into the live AlertManager."""
        try:
            from bot.alert_manager import get_alert_manager
            mgr = get_alert_manager()
            mgr.cooldown_seconds = profile.recommended_alert_cooldown_risk
            logger.info(
                "CalibrationProfile applied to AlertManager — cooldown=%ds",
                profile.recommended_alert_cooldown_risk,
            )
            return True
        except Exception as exc:
            logger.error("Failed to apply profile to AlertManager: %s", exc)
            return False


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_calibrator_instance: Optional[ThresholdCalibrator] = None
_calibrator_lock = threading.Lock()


def get_threshold_calibrator(seed: Optional[int] = None) -> ThresholdCalibrator:
    """Return the process-wide :class:`ThresholdCalibrator` singleton."""
    global _calibrator_instance
    with _calibrator_lock:
        if _calibrator_instance is None:
            _calibrator_instance = ThresholdCalibrator(seed=seed)
            logger.info("ThresholdCalibrator singleton created")
    return _calibrator_instance


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    )

    rng = random.Random(42)

    cal = ThresholdCalibrator(seed=42)

    # Simulate broker observations
    for _ in range(200):
        latency = max(10.0, rng.gauss(120.0, 80.0))
        success = rng.random() > 0.03          # 3% error rate
        rejected = not success and rng.random() < 0.5
        cal.record_api_call(latency_ms=latency, success=success, order_rejected=rejected)

    # Simulate trade history
    win_rate = 0.55
    for _ in range(80):
        is_win = rng.random() < win_rate
        pnl = rng.gauss(80.0, 30.0) if is_win else -rng.gauss(55.0, 20.0)
        cal.record_trade(pnl_usd=pnl, is_win=is_win)

    profile = cal.calibrate()
    print(profile.summary())

    if len(sys.argv) > 1 and sys.argv[1] == "--save":
        profile.save("calibration_profile.json")
        print("Profile saved to calibration_profile.json")
