"""
Signal Funnel Diagnostics
==========================

Tracks how many opportunities pass/fail at each filter stage per trading pair,
and provides shadow-paper logging to measure hypothetical PnL vs. executed trades.

Per-pair funnel counters (logged every REPORT_INTERVAL cycles):
  signals_seen       - times analyze_market was called for this pair
  confidence_pass    - passed confidence threshold
  adx_pass           - passed ADX threshold
  volume_pass        - passed volume threshold
  ai_gate_pass       - passed AIEntryGate (gate score ≥ threshold)
  execution_pass     - actually submitted to broker

Rejection events are emitted as structured ``REJECTED_SIGNAL:`` log lines:
  REJECTED_SIGNAL: pair=ETHUSD confidence=0.21 threshold=0.25 adx=9 volume=1.8%

Shadow-paper tracking records every signal that passed all gates, computes
the hypothetical PnL based on subsequent price movement, and compares it
to the actual executed trades.

Usage
-----
::

    from bot.signal_funnel_diagnostics import get_signal_funnel

    funnel = get_signal_funnel()
    funnel.record_signal_seen(symbol)
    funnel.record_confidence_pass(symbol)
    funnel.record_rejected(symbol, confidence=0.21, threshold=0.25, adx=9.0, volume=0.018, reason="low_confidence")
    funnel.record_ai_gate_pass(symbol)
    funnel.record_execution_pass(symbol)
    funnel.maybe_report_and_reset()

Author: NIJA Trading Systems
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Tuple

logger = logging.getLogger("nija.signal_funnel")

# How often to emit the per-pair funnel summary to the log (seconds)
REPORT_INTERVAL_SECS: float = 300.0  # 5 minutes
TRACE_STAGE_ORDER: Tuple[str, ...] = (
    "signal",
    "ai_gate",
    "position_sizing",
    "ecel",
    "broker",
    "fill",
)


# ---------------------------------------------------------------------------
# Per-pair funnel statistics
# ---------------------------------------------------------------------------

@dataclass
class FunnelStats:
    """Per-symbol funnel counters for one reporting window."""
    pair: str
    signals_seen: int = 0
    confidence_pass: int = 0
    adx_pass: int = 0
    volume_pass: int = 0
    ai_gate_pass: int = 0
    execution_pass: int = 0

    def as_log_line(self) -> str:
        """Return a formatted one-line summary suitable for log emission."""
        return (
            f"SIGNAL_FUNNEL: PAIR={self.pair} "
            f"signals_seen={self.signals_seen} "
            f"confidence_pass={self.confidence_pass} "
            f"adx_pass={self.adx_pass} "
            f"volume_pass={self.volume_pass} "
            f"ai_gate_pass={self.ai_gate_pass} "
            f"execution_pass={self.execution_pass}"
        )


# ---------------------------------------------------------------------------
# Shadow-paper trade record
# ---------------------------------------------------------------------------

@dataclass
class ShadowTrade:
    """A hypothetical trade that passed all gates but may not have executed."""
    pair: str
    side: str           # 'long' or 'short'
    entry_price: float
    entry_time: float   # unix timestamp
    confidence: float
    adx: float
    volume_ratio: float
    gate_score: float
    executed: bool = False  # True when the live bot also entered
    exit_price: float = 0.0
    exit_time: float = 0.0
    hypothetical_pnl_pct: float = 0.0  # filled on close


@dataclass
class ExecutionTraceStageEvent:
    """A single stage update inside one execution trace attempt."""
    stage: str
    outcome: str
    reason: str = ""
    timestamp: float = field(default_factory=time.time)
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutionTraceAttempt:
    """Per-attempt execution trace from signal through fill/rejection."""
    trace_id: str
    pair: str
    side: str
    status: str = "in_progress"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    terminal_reason: str = ""
    events: List[ExecutionTraceStageEvent] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Main diagnostics class
# ---------------------------------------------------------------------------

class SignalFunnelDiagnostics:
    """
    Thread-safe signal funnel tracker and shadow-paper logger.

    Call ``get_signal_funnel()`` to obtain the global singleton.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stats: Dict[str, FunnelStats] = {}
        self._shadow_trades: List[ShadowTrade] = []
        self._trace_attempts: List[ExecutionTraceAttempt] = []
        self._trace_quality_by_id: Dict[str, Dict[str, Any]] = {}
        self._active_trace_by_key: Dict[str, str] = {}
        self._trace_counter: int = 0
        self._max_trace_attempts: int = 400
        self._last_report_time: float = time.monotonic()
        self._trace_gate_enabled: bool = (
            str(os.getenv("NIJA_EIL_TRACE_GATE_ENABLED", "false")).lower() in ("1", "true", "yes")
        )
        self._trace_gate_min_pass_probability: float = float(
            os.getenv("NIJA_EIL_TRACE_GATE_MIN_PASS_PROBABILITY", "0.35") or "0.35"
        )
        try:
            from bot.trace_persistence import get_eil_trace_persistence_writer
            get_eil_trace_persistence_writer()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Funnel stage recorders
    # ------------------------------------------------------------------

    def record_signal_seen(self, pair: str) -> None:
        """Increment signals_seen for this pair."""
        with self._lock:
            self._get_or_create(pair).signals_seen += 1

    def record_confidence_pass(self, pair: str) -> None:
        """Increment confidence_pass for this pair."""
        with self._lock:
            self._get_or_create(pair).confidence_pass += 1

    def record_adx_pass(self, pair: str) -> None:
        """Increment adx_pass for this pair."""
        with self._lock:
            self._get_or_create(pair).adx_pass += 1

    def record_volume_pass(self, pair: str) -> None:
        """Increment volume_pass for this pair."""
        with self._lock:
            self._get_or_create(pair).volume_pass += 1

    def record_ai_gate_pass(self, pair: str) -> None:
        """Increment ai_gate_pass for this pair."""
        with self._lock:
            self._get_or_create(pair).ai_gate_pass += 1

    def record_execution_pass(self, pair: str) -> None:
        """Increment execution_pass for this pair."""
        with self._lock:
            self._get_or_create(pair).execution_pass += 1

    # ------------------------------------------------------------------
    # Rejection logger
    # ------------------------------------------------------------------

    def record_rejected(
        self,
        pair: str,
        *,
        confidence: float = 0.0,
        threshold: float = 0.0,
        adx: float = 0.0,
        volume: float = 0.0,
        reason: str = "",
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Emit a structured REJECTED_SIGNAL log line.

        Example output::

            REJECTED_SIGNAL: pair=ETHUSD confidence=0.21 threshold=0.25 adx=9 volume=1.8%
        """
        parts = [
            f"pair={pair}",
            f"confidence={confidence:.2f}",
            f"threshold={threshold:.2f}",
            f"adx={adx:.1f}",
            f"volume={volume * 100:.1f}%",
        ]
        if reason:
            parts.append(f"reason={reason}")
        if extra:
            for k, v in extra.items():
                parts.append(f"{k}={v}")
        logger.warning("REJECTED_SIGNAL: %s", " ".join(parts))

    # ------------------------------------------------------------------
    # Shadow-paper tracking
    # ------------------------------------------------------------------

    def record_shadow_entry(
        self,
        pair: str,
        side: str,
        entry_price: float,
        confidence: float,
        adx: float,
        volume_ratio: float,
        gate_score: float,
        executed: bool = False,
    ) -> None:
        """
        Record a signal that passed all gates (regardless of whether it executed).
        Used for shadow-paper PnL comparison.
        """
        trade = ShadowTrade(
            pair=pair,
            side=side,
            entry_price=entry_price,
            entry_time=time.time(),
            confidence=confidence,
            adx=adx,
            volume_ratio=volume_ratio,
            gate_score=gate_score,
            executed=executed,
        )
        with self._lock:
            self._shadow_trades.append(trade)
            # Trim to the most recent 500 entries to avoid unbounded growth
            if len(self._shadow_trades) > 500:
                self._shadow_trades = self._shadow_trades[-500:]

    def update_shadow_exit(
        self,
        pair: str,
        exit_price: float,
        side: str = "long",
    ) -> None:
        """
        Update the most recently opened shadow trade for the given pair with an exit
        price and compute hypothetical PnL.  Only the newest still-open trade is
        closed so that multiple open shadow entries for the same pair are not all
        closed at once.
        """
        with self._lock:
            for trade in reversed(self._shadow_trades):
                if trade.pair == pair and trade.exit_price == 0.0:
                    trade.exit_price = exit_price
                    trade.exit_time = time.time()
                    if trade.entry_price > 0:
                        raw_pnl = (exit_price - trade.entry_price) / trade.entry_price
                        trade.hypothetical_pnl_pct = (
                            raw_pnl if trade.side == "long" else -raw_pnl
                        ) * 100.0
                    break  # only close the most recent open trade

    def mark_shadow_executed(self, pair: str) -> None:
        """
        Mark the most recently opened (and not yet executed) shadow trade for
        *pair* as having been actually submitted to the broker.  Thread-safe.
        """
        with self._lock:
            for trade in reversed(self._shadow_trades):
                if trade.pair == pair and not trade.executed:
                    trade.executed = True
                    break

    # ------------------------------------------------------------------
    # Execution trace viewer (per-attempt stage flow)
    # ------------------------------------------------------------------

    def start_execution_trace(
        self,
        pair: str,
        side: str,
        *,
        reason: str = "",
        extra: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Start a new execution attempt at SIGNAL stage and return trace_id."""
        event_payload: Optional[Dict[str, Any]] = None
        with self._lock:
            self._trace_counter += 1
            trace_id = f"trace-{int(time.time() * 1000)}-{self._trace_counter}"
            attempt = ExecutionTraceAttempt(
                trace_id=trace_id,
                pair=pair,
                side=side.lower(),
            )
            attempt.events.append(
                ExecutionTraceStageEvent(
                    stage="signal",
                    outcome="pass",
                    reason=reason,
                    extra=dict(extra or {}),
                )
            )
            self._trace_attempts.append(attempt)
            self._active_trace_by_key[self._trace_key(pair, side)] = trace_id
            event_payload = self._build_stream_event_payload(attempt, attempt.events[-1])
            self._trim_traces_locked()
        if event_payload is not None:
            self._publish_trace_event(event_payload)
        return trace_id

    def record_execution_stage(
        self,
        pair: str,
        stage: str,
        outcome: str,
        *,
        side: Optional[str] = None,
        reason: str = "",
        extra: Optional[Dict[str, Any]] = None,
        terminal: bool = False,
    ) -> Optional[str]:
        """Record a stage update for the active trace attempt for pair/side."""
        event_payload: Optional[Dict[str, Any]] = None
        terminal_payload: Optional[Dict[str, Any]] = None
        score_for_output: Optional[Dict[str, Any]] = None
        forced_rejection_terminal: bool = False
        with self._lock:
            attempt = self._resolve_attempt_locked(pair, side)
            if attempt is None:
                # Create a fallback attempt when downstream stages emit before signal stage.
                fallback_side = (side or "unknown").lower()
                self._trace_counter += 1
                trace_id = f"trace-{int(time.time() * 1000)}-{self._trace_counter}"
                attempt = ExecutionTraceAttempt(trace_id=trace_id, pair=pair, side=fallback_side)
                self._trace_attempts.append(attempt)
                self._active_trace_by_key[self._trace_key(pair, fallback_side)] = trace_id

            event = ExecutionTraceStageEvent(
                stage=stage,
                outcome=outcome,
                reason=reason,
                extra=dict(extra or {}),
            )
            attempt.events.append(event)
            attempt.updated_at = event.timestamp
            event_payload = self._build_stream_event_payload(attempt, event)

            if stage == "ecel" and outcome in ("pass", "compiled", "confirmed", "success"):
                score_for_output = self._score_attempt_quality_locked(attempt)
                if score_for_output is not None:
                    self._trace_quality_by_id[attempt.trace_id] = score_for_output
                    if self._trace_gate_enabled:
                        _pp = score_for_output.get("pass_probability")
                        if isinstance(_pp, (float, int)) and float(_pp) < self._trace_gate_min_pass_probability:
                            attempt.status = "rejected"
                            attempt.terminal_reason = "trace_gate_low_pass_probability"
                            attempt.events.append(
                                ExecutionTraceStageEvent(
                                    stage="trace_gate",
                                    outcome="rejected",
                                    reason="trace_gate_low_pass_probability",
                                    extra={
                                        "pass_probability": float(_pp),
                                        "threshold": self._trace_gate_min_pass_probability,
                                    },
                                )
                            )
                            self._active_trace_by_key.pop(self._trace_key(attempt.pair, attempt.side), None)
                            forced_rejection_terminal = True
                            terminal = True

            if terminal:
                if not forced_rejection_terminal:
                    attempt.status = "filled" if outcome in ("pass", "filled", "confirmed", "success") else "rejected"
                    attempt.terminal_reason = reason or outcome
                self._active_trace_by_key.pop(self._trace_key(attempt.pair, attempt.side), None)
            elif outcome in ("rejected", "error", "blocked", "failed"):
                attempt.status = "rejected"
                attempt.terminal_reason = reason or outcome
                self._active_trace_by_key.pop(self._trace_key(attempt.pair, attempt.side), None)
            elif stage == "fill" and outcome in ("pass", "filled", "confirmed", "success"):
                attempt.status = "filled"
                attempt.terminal_reason = reason or "filled"
                self._active_trace_by_key.pop(self._trace_key(attempt.pair, attempt.side), None)

            if attempt.status in ("filled", "rejected"):
                terminal_payload = self._build_terminal_stream_payload(attempt)
                self._apply_terminal_learning_hooks_locked(attempt)
            self._trim_traces_locked()
        if event_payload is not None:
            self._publish_trace_event(event_payload)
        if terminal_payload is not None:
            self._publish_terminal_trace(terminal_payload)
        return attempt.trace_id

    def get_execution_traces(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return latest per-attempt execution traces for viewer/API consumption."""
        with self._lock:
            attempts = list(self._trace_attempts[-max(1, limit):])

        output: List[Dict[str, Any]] = []
        for attempt in reversed(attempts):
            stage_map: Dict[str, Dict[str, Any]] = {}
            last_stage = ""
            for event in attempt.events:
                stage_map[event.stage] = {
                    "outcome": event.outcome,
                    "reason": event.reason,
                    "timestamp": event.timestamp,
                    "extra": dict(event.extra or {}),
                }
                last_stage = event.stage
            output.append(
                {
                    "trace_id": attempt.trace_id,
                    "pair": attempt.pair,
                    "side": attempt.side,
                    "status": attempt.status,
                    "terminal_reason": attempt.terminal_reason,
                    "created_at": attempt.created_at,
                    "updated_at": attempt.updated_at,
                    "last_stage": last_stage,
                    "stages": {
                        stage: stage_map.get(stage)
                        for stage in TRACE_STAGE_ORDER
                    },
                    "events": [
                        {
                            "stage": event.stage,
                            "outcome": event.outcome,
                            "reason": event.reason,
                            "timestamp": event.timestamp,
                            "extra": dict(event.extra or {}),
                        }
                        for event in attempt.events
                    ],
                    "quality_prediction": self._trace_quality_by_id.get(attempt.trace_id),
                }
            )
        return output

    def get_shadow_summary(self) -> Dict[str, Any]:
        """
        Return a snapshot of shadow-paper statistics for logging or API consumption.
        """
        with self._lock:
            closed = [t for t in self._shadow_trades if t.exit_price > 0.0]
            open_shadow = [t for t in self._shadow_trades if t.exit_price == 0.0]
            executed_closed = [t for t in closed if t.executed]
            shadow_only = [t for t in closed if not t.executed]

            avg_pnl_all = (
                sum(t.hypothetical_pnl_pct for t in closed) / len(closed)
                if closed else 0.0
            )
            avg_pnl_executed = (
                sum(t.hypothetical_pnl_pct for t in executed_closed) / len(executed_closed)
                if executed_closed else 0.0
            )
            avg_pnl_shadow = (
                sum(t.hypothetical_pnl_pct for t in shadow_only) / len(shadow_only)
                if shadow_only else 0.0
            )

            return {
                "shadow_trades_open": len(open_shadow),
                "shadow_trades_closed": len(closed),
                "executed_closed": len(executed_closed),
                "shadow_only_closed": len(shadow_only),
                "avg_hyp_pnl_pct_all": round(avg_pnl_all, 3),
                "avg_hyp_pnl_pct_executed": round(avg_pnl_executed, 3),
                "avg_hyp_pnl_pct_shadow_only": round(avg_pnl_shadow, 3),
            }

    # ------------------------------------------------------------------
    # Periodic reporting
    # ------------------------------------------------------------------

    def maybe_report_and_reset(self) -> None:
        """
        If REPORT_INTERVAL_SECS has elapsed, log a funnel summary for every
        active pair and reset all counters.  Thread-safe.
        """
        now = time.monotonic()
        if now - self._last_report_time < REPORT_INTERVAL_SECS:
            return

        with self._lock:
            if now - self._last_report_time < REPORT_INTERVAL_SECS:
                return  # double-check under lock

            stats_snapshot = list(self._stats.values())
            self._stats.clear()
            self._last_report_time = now

        if not stats_snapshot:
            logger.info("SIGNAL_FUNNEL: no pairs scanned in this window")
            return

        logger.info("=" * 60)
        logger.info("SIGNAL_FUNNEL_REPORT (last %.0fs):", REPORT_INTERVAL_SECS)
        for stat in sorted(stats_snapshot, key=lambda s: s.signals_seen, reverse=True):
            logger.info(stat.as_log_line())
        logger.info("=" * 60)

        # Also emit shadow-paper summary
        shadow = self.get_shadow_summary()
        logger.info(
            "SHADOW_PAPER_SUMMARY: open=%d closed=%d executed=%d shadow_only=%d "
            "avg_hyp_pnl=%.2f%% avg_executed_pnl=%.2f%% avg_shadow_pnl=%.2f%%",
            shadow["shadow_trades_open"],
            shadow["shadow_trades_closed"],
            shadow["executed_closed"],
            shadow["shadow_only_closed"],
            shadow["avg_hyp_pnl_pct_all"],
            shadow["avg_hyp_pnl_pct_executed"],
            shadow["avg_hyp_pnl_pct_shadow_only"],
        )

    def get_pair_stats(self, pair: str) -> FunnelStats:
        """Return a copy of the current funnel stats for a pair (read-only snapshot)."""
        with self._lock:
            s = self._stats.get(pair)
            if s is None:
                return FunnelStats(pair=pair)
            return FunnelStats(
                pair=s.pair,
                signals_seen=s.signals_seen,
                confidence_pass=s.confidence_pass,
                adx_pass=s.adx_pass,
                volume_pass=s.volume_pass,
                ai_gate_pass=s.ai_gate_pass,
                execution_pass=s.execution_pass,
            )

    def get_all_stats(self) -> List[FunnelStats]:
        """Return snapshots of all active pair stats."""
        with self._lock:
            return [
                FunnelStats(
                    pair=s.pair,
                    signals_seen=s.signals_seen,
                    confidence_pass=s.confidence_pass,
                    adx_pass=s.adx_pass,
                    volume_pass=s.volume_pass,
                    ai_gate_pass=s.ai_gate_pass,
                    execution_pass=s.execution_pass,
                )
                for s in self._stats.values()
            ]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_or_create(self, pair: str) -> FunnelStats:
        """Return (or create) the FunnelStats entry for this pair. Caller holds lock."""
        if pair not in self._stats:
            self._stats[pair] = FunnelStats(pair=pair)
        return self._stats[pair]

    def _trace_key(self, pair: str, side: str) -> str:
        return f"{pair}|{(side or 'unknown').lower()}"

    def _resolve_attempt_locked(self, pair: str, side: Optional[str]) -> Optional[ExecutionTraceAttempt]:
        if side:
            trace_id = self._active_trace_by_key.get(self._trace_key(pair, side))
            if trace_id:
                for attempt in reversed(self._trace_attempts):
                    if attempt.trace_id == trace_id:
                        return attempt
        for attempt in reversed(self._trace_attempts):
            if attempt.pair == pair and attempt.status == "in_progress":
                return attempt
        return None

    def _trim_traces_locked(self) -> None:
        if len(self._trace_attempts) <= self._max_trace_attempts:
            return
        self._trace_attempts = self._trace_attempts[-self._max_trace_attempts:]
        live_ids = {attempt.trace_id for attempt in self._trace_attempts}
        self._active_trace_by_key = {
            key: trace_id
            for key, trace_id in self._active_trace_by_key.items()
            if trace_id in live_ids
        }
        self._trace_quality_by_id = {
            trace_id: score
            for trace_id, score in self._trace_quality_by_id.items()
            if trace_id in live_ids
        }

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _build_stream_event_payload(
        self,
        attempt: ExecutionTraceAttempt,
        event: ExecutionTraceStageEvent,
    ) -> Dict[str, Any]:
        regime = "unknown"
        confidence = 0.0
        adx = 0.0
        gate_score = 0.0
        ecel_result = ""
        broker = ""
        for evt in reversed(attempt.events):
            extra = evt.extra or {}
            if regime == "unknown":
                regime = str(extra.get("regime") or extra.get("trend") or regime)
            confidence = confidence or self._safe_float(extra.get("confidence"), 0.0)
            adx = adx or self._safe_float(extra.get("adx"), 0.0)
            gate_score = gate_score or self._safe_float(extra.get("gate_score"), 0.0)
            if not broker:
                broker = str(extra.get("broker") or "")
            if evt.stage == "ecel":
                ecel_result = evt.outcome
        return {
            "trace_id": attempt.trace_id,
            "pair": attempt.pair,
            "side": attempt.side,
            "stage": event.stage,
            "outcome": event.outcome,
            "reason": event.reason,
            "regime": regime,
            "confidence": confidence,
            "adx": adx,
            "gate_score": gate_score,
            "ecel_result": ecel_result,
            "broker": broker,
            "ts_unix": event.timestamp,
            "extra": dict(event.extra or {}),
        }

    def _build_terminal_stream_payload(self, attempt: ExecutionTraceAttempt) -> Dict[str, Any]:
        trace_path = [f"{event.stage}:{event.outcome}" for event in attempt.events]
        regime = "unknown"
        confidence = 0.0
        adx = 0.0
        gate_score = 0.0
        ecel_decision = ""
        for event in attempt.events:
            extra = event.extra or {}
            regime = str(extra.get("regime") or extra.get("trend") or regime)
            confidence = confidence or self._safe_float(extra.get("confidence"), 0.0)
            adx = adx or self._safe_float(extra.get("adx"), 0.0)
            gate_score = gate_score or self._safe_float(extra.get("gate_score"), 0.0)
            if event.stage == "ecel":
                ecel_decision = event.reason or event.outcome
        return {
            "trace_id": attempt.trace_id,
            "pair": attempt.pair,
            "side": attempt.side,
            "status": attempt.status,
            "terminal_reason": attempt.terminal_reason,
            "regime": regime,
            "confidence": confidence,
            "adx": adx,
            "gate_score": gate_score,
            "ecel_decision": ecel_decision,
            "trace_path": trace_path,
            "created_at": attempt.created_at,
            "updated_at": attempt.updated_at,
            "filled_at": attempt.updated_at if attempt.status == "filled" else None,
            "events": [
                {
                    "stage": event.stage,
                    "outcome": event.outcome,
                    "reason": event.reason,
                    "timestamp": event.timestamp,
                    "extra": dict(event.extra or {}),
                }
                for event in attempt.events
            ],
            "quality_prediction": self._trace_quality_by_id.get(attempt.trace_id),
        }

    def _score_attempt_quality_locked(self, attempt: ExecutionTraceAttempt) -> Optional[Dict[str, Any]]:
        payload = self._build_terminal_stream_payload(attempt)
        try:
            from bot.trace_quality_scorer import get_trace_quality_scorer

            scorer = get_trace_quality_scorer()
            score_obj = scorer.score_trace(payload)
            if hasattr(score_obj, "__dict__"):
                return dict(score_obj.__dict__)
            if isinstance(score_obj, dict):
                return dict(score_obj)
        except Exception:
            return None
        return None

    def _apply_terminal_learning_hooks_locked(self, attempt: ExecutionTraceAttempt) -> None:
        payload = self._build_terminal_stream_payload(attempt)
        try:
            from bot.failure_cluster_engine import get_failure_cluster_engine

            get_failure_cluster_engine().ingest_terminal_trace(payload)
        except Exception:
            pass
        try:
            from bot.regime_gate_calibrator import get_regime_gate_calibrator

            get_regime_gate_calibrator().update_from_trace(payload)
        except Exception:
            pass
        try:
            from bot.trace_quality_scorer import get_trace_quality_scorer

            quality_grade = ""
            qp = self._trace_quality_by_id.get(attempt.trace_id) or {}
            expected_grade = str(qp.get("expected_grade") or "")
            if expected_grade in ("A", "B", "C", "D"):
                quality_grade = expected_grade
            get_trace_quality_scorer().record_terminal_outcome(payload, quality_grade=quality_grade)
        except Exception:
            pass

    @staticmethod
    def _publish_trace_event(payload: Dict[str, Any]) -> None:
        try:
            from bot.trace_persistence import get_eil_trace_publisher

            get_eil_trace_publisher().publish_event(payload)
        except Exception:
            return

    @staticmethod
    def _publish_terminal_trace(payload: Dict[str, Any]) -> None:
        try:
            from bot.trace_persistence import get_eil_trace_publisher

            get_eil_trace_publisher().publish_terminal(payload)
        except Exception:
            return


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_singleton: Optional[SignalFunnelDiagnostics] = None
_singleton_lock = threading.Lock()


def get_signal_funnel() -> SignalFunnelDiagnostics:
    """Return the process-level SignalFunnelDiagnostics singleton."""
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                _singleton = SignalFunnelDiagnostics()
                logger.info("SignalFunnelDiagnostics initialized (report every %.0fs)", REPORT_INTERVAL_SECS)
    return _singleton
