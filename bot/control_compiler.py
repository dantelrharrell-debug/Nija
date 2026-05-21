"""
NIJA Control Compiler Layer
============================

A single enforcement layer that sits between signal generation and execution.
It validates every signal, enforces invariants, detects feedback instability,
and manages a tunable control-matrix of gate gains (K values).

Architecture
------------
::

    Signal source (MasterStrategyRouter / TradingView webhook / ...)
        │
        ▼
    ControlCompiler.compile(raw_signal)
        │
        ├── 1. Schema validation (ControlSignal dataclass + type/range checks)
        ├── 2. Invariant checks (symbol/side/size/confidence/regime consistency)
        ├── 3. Feedback-instability probe (reject or throttle oscillating paths)
        └── 4. K-gain gate (applies current ControlMatrix to scale thresholds)
                │
               PASS → CompileResult(accepted=True, signal=ControlSignal)
               FAIL → CompileResult(accepted=False, reason=...)
                         └── feeds trace into SignalFunnelDiagnostics

Control Matrix (K values)
--------------------------
Each gain maps to a threshold that already exists in the system.  A K of 1.0
means "use the current default".  K > 1.0 tightens; K < 1.0 loosens.

    K_AI_GATE        — scalar on BASE_ENTRY_SCORE_THRESHOLD
    K_REGIME_PASS    — minimum regime-gate pass probability
    K_CONFIDENCE     — minimum acceptable signal confidence
    K_SIZE_FLOOR     — minimum size_usd floor multiplier

KAutoTuner runs periodically over the last N traces and nudges K values within
bounded clamp limits.  Every update is recorded with a timestamp and reason.

Feedback-Instability Detection
-------------------------------
The detector watches recent traces for a symbol+regime key and flags:
  * rapid accept→reject→accept oscillation (flip rate)
  * same path hash appearing in FailureClusterEngine with high rejection rate
  * repeated K threshold bumps for the same regime within a cooldown window

When instability is MILD  → tighten K for the affected path by a small step.
When instability is SEVERE → freeze the control path (block new entries for
                             that symbol/regime) and emit a terminal trace.

Usage
-----
::

    from bot.control_compiler import get_control_compiler, RawSignal

    compiler = get_control_compiler()

    result = compiler.compile(RawSignal(
        symbol="BTC-USD",
        side="buy",
        action="enter_long",
        size_usd=500.0,
        confidence=0.72,
        regime="strong_trend",
        strategy="ApexTrend",
    ))

    if not result.accepted:
        logger.warning("Compiler rejected signal: %s", result.reason)
    else:
        signal = result.signal          # validated ControlSignal
        pipeline.execute(PipelineRequest(
            symbol=signal.symbol,
            side=signal.side,
            size_usd=signal.size_usd,
            strategy=signal.strategy,
        ))

Author: NIJA Trading Systems
Version: 1.0
Date: May 2026
"""

from __future__ import annotations

import logging
import math
import os
import threading
import time
from collections import deque
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Deque, Dict, List, Optional, Tuple

logger = logging.getLogger("nija.control_compiler")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_VALID_SIDES = frozenset({"buy", "sell", "long", "short"})
_VALID_ACTIONS = frozenset({"enter_long", "enter_short", "exit_long", "exit_short", "hold", "no_trade"})
_EXECUTION_ACTIONS = frozenset({"enter_long", "enter_short"})

# Instability detection window (seconds)
_INSTABILITY_WINDOW_S: float = float(os.getenv("NIJA_CC_INSTABILITY_WINDOW_S", "600"))
# Min flips in window to trigger mild instability
_INSTABILITY_FLIP_THRESHOLD: int = int(os.getenv("NIJA_CC_INSTABILITY_FLIP_THRESHOLD", "4"))
# Min flips in window to trigger severe instability
_INSTABILITY_SEVERE_THRESHOLD: int = int(os.getenv("NIJA_CC_INSTABILITY_SEVERE_THRESHOLD", "8"))
# Duration of a freeze block (seconds)
_INSTABILITY_FREEZE_S: float = float(os.getenv("NIJA_CC_INSTABILITY_FREEZE_S", "900"))

# K auto-tuner interval (seconds between runs)
_K_TUNER_INTERVAL_S: float = float(os.getenv("NIJA_CC_K_TUNER_INTERVAL_S", "300"))
# How many recent traces to use for tuning
_K_TUNER_WINDOW: int = int(os.getenv("NIJA_CC_K_TUNER_WINDOW", "50"))
# Maximum K adjustment per tuner cycle
_K_MAX_STEP: float = float(os.getenv("NIJA_CC_K_MAX_STEP", "0.05"))
# Minimum K value (floor – cannot loosen below this fraction of baseline)
_K_FLOOR: float = float(os.getenv("NIJA_CC_K_FLOOR", "0.5"))
# Maximum K value (ceiling – cannot tighten beyond this multiple of baseline)
_K_CEILING: float = float(os.getenv("NIJA_CC_K_CEILING", "2.0"))
# Cooldown between K adjustments for the same dimension (seconds)
_K_COOLDOWN_S: float = float(os.getenv("NIJA_CC_K_COOLDOWN_S", "120"))

# Minimum confidence to accept a signal (baseline; scaled by K_CONFIDENCE)
_MIN_CONFIDENCE_BASELINE: float = float(os.getenv("NIJA_CC_MIN_CONFIDENCE", "0.0"))
# Minimum size_usd to accept an execution signal
_MIN_SIZE_USD_BASELINE: float = float(os.getenv("NIJA_CC_MIN_SIZE_USD", "0.0"))
# Low-friction bootstrap: allow a bounded number of synthetic or low-threshold
# signals to pass through the compiler so end-to-end execution can be verified
# before tightening filters upward.
_BOOTSTRAP_PASS_ENABLED: bool = os.getenv("NIJA_CC_BOOTSTRAP_PASS_ENABLED", "true").lower() in (
    "1",
    "true",
    "yes",
)
_BOOTSTRAP_PASS_LIMIT: int = max(0, int(os.getenv("NIJA_CC_BOOTSTRAP_PASS_LIMIT", "1")))
_BOOTSTRAP_MIN_CONFIDENCE: float = max(
    0.0,
    min(1.0, float(os.getenv("NIJA_CC_BOOTSTRAP_MIN_CONFIDENCE", "0.05"))),
)
# Self-healing bootstrap decay: as execution acceptance stabilizes, bootstrap
# affordances decay toward strict confidence gating automatically.
_BOOTSTRAP_DECAY_WINDOW: int = max(10, int(os.getenv("NIJA_CC_BOOTSTRAP_DECAY_WINDOW", "120")))
_BOOTSTRAP_DECAY_MIN_SAMPLES: int = max(1, int(os.getenv("NIJA_CC_BOOTSTRAP_DECAY_MIN_SAMPLES", "20")))
_BOOTSTRAP_DECAY_BASELINE_ACCEPT_RATE: float = max(
    0.0,
    min(1.0, float(os.getenv("NIJA_CC_BOOTSTRAP_DECAY_BASELINE_ACCEPT_RATE", "0.50"))),
)
_BOOTSTRAP_DECAY_TARGET_ACCEPT_RATE: float = max(
    0.0,
    min(1.0, float(os.getenv("NIJA_CC_BOOTSTRAP_DECAY_TARGET_ACCEPT_RATE", "0.85"))),
)
_BOOTSTRAP_DECAY_SHAPE: float = max(0.5, float(os.getenv("NIJA_CC_BOOTSTRAP_DECAY_SHAPE", "1.5")))
_MIN_LIVE_EXECUTION_GAP_S: float = max(60.0, float(os.getenv("NIJA_CC_MIN_LIVE_EXECUTION_GAP_S", "1800")))
_MIN_LIVE_EXECUTION_CONF_RELAX: float = max(
    0.1, min(1.0, float(os.getenv("NIJA_CC_MIN_LIVE_EXECUTION_CONF_RELAX", "0.5")))
)
_MIN_LIVE_EXECUTION_LIMIT_FLOOR: int = max(1, int(os.getenv("NIJA_CC_MIN_LIVE_EXECUTION_LIMIT_FLOOR", "2")))


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class CompileStatus(Enum):
    ACCEPTED = "accepted"
    SCHEMA_INVALID = "schema_invalid"
    INVARIANT_FAILED = "invariant_failed"
    INSTABILITY_FROZEN = "instability_frozen"
    INSTABILITY_THROTTLED = "instability_throttled"
    K_GATE_FAILED = "k_gate_failed"


class InstabilityLevel(Enum):
    NONE = "none"
    MILD = "mild"
    SEVERE = "severe"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class RawSignal:
    """
    Unvalidated signal from any source (strategy, webhook, broadcaster).

    All fields are optional because real signal dicts may be incomplete.
    The compiler will reject missing required fields during schema validation.
    """
    symbol: str = ""
    side: str = ""                       # "buy" / "sell" / "long" / "short"
    action: str = "hold"                 # "enter_long" / "enter_short" / "hold" / ...
    size_usd: float = 0.0
    confidence: float = 0.0
    regime: str = "unknown"
    strategy: str = ""
    account_id: str = "default"
    order_type: Optional[str] = None
    asset_class: Optional[str] = None
    preferred_broker: Optional[str] = None
    available_balance_usd: Optional[float] = None
    price_hint_usd: Optional[float] = None
    approved: bool = True                # from RouterSignal / StrategyVoter
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ControlSignal:
    """
    Validated, normalized signal that has passed all compiler checks.

    Downstream components (ExecutionPipeline, SignalBroadcaster) should
    consume this instead of raw signal dicts.
    """
    symbol: str
    side: str                            # normalized to "buy" / "sell"
    action: str                          # normalized action string
    size_usd: float
    confidence: float
    regime: str
    strategy: str
    account_id: str
    order_type: Optional[str]
    asset_class: Optional[str]
    preferred_broker: Optional[str]
    available_balance_usd: Optional[float]
    price_hint_usd: Optional[float]
    metadata: Dict[str, Any]
    compiled_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_pipeline_kwargs(self) -> Dict[str, Any]:
        """Return kwargs suitable for PipelineRequest construction."""
        return {
            "symbol": self.symbol,
            "side": self.side,
            "size_usd": self.size_usd,
            "strategy": self.strategy,
            "order_type": self.order_type,
            "asset_class": self.asset_class,
            "preferred_broker": self.preferred_broker,
            "available_balance_usd": self.available_balance_usd,
            "price_hint_usd": self.price_hint_usd,
            "account_id": self.account_id,
        }


@dataclass
class CompileResult:
    """Result returned by ControlCompiler.compile()."""

    accepted: bool
    status: CompileStatus
    reason: str = ""
    signal: Optional[ControlSignal] = None
    # Machine-readable rejection code for structured logging / tracing
    reason_code: str = ""


@dataclass(frozen=True)
class ExecutionDecision:
    """Canonical trade-admission deny telemetry event."""

    stage: str
    allow: bool
    reason: str
    confidence: float
    threshold: float
    governor_mode: str


@dataclass
class KValue:
    """One named control gain with its history."""

    name: str
    value: float
    floor: float
    ceiling: float
    last_updated: float = field(default_factory=time.time)
    last_update_reason: str = ""
    update_count: int = 0

    def clamp(self, candidate: float) -> float:
        return max(self.floor, min(self.ceiling, candidate))

    def apply_step(self, delta: float, reason: str) -> None:
        now = time.time()
        new_value = self.clamp(self.value + delta)
        if new_value != self.value:
            self.value = new_value
            self.last_updated = now
            self.last_update_reason = reason
            self.update_count += 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "value": round(self.value, 6),
            "floor": self.floor,
            "ceiling": self.ceiling,
            "last_updated": self.last_updated,
            "last_update_reason": self.last_update_reason,
            "update_count": self.update_count,
        }


@dataclass
class KHistory:
    """Auditable record of one K-update event."""
    name: str
    old_value: float
    new_value: float
    reason: str
    source: str
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


# ---------------------------------------------------------------------------
# ControlMatrix
# ---------------------------------------------------------------------------

class ControlMatrix:
    """
    Thread-safe registry of named gate gains (K values).

    Current dimensions:
      K_AI_GATE        — multiplier on AI-gate pass threshold
      K_REGIME_PASS    — minimum regime-gate Laplace probability floor
      K_CONFIDENCE     — minimum acceptable confidence
      K_SIZE_FLOOR     — minimum size_usd multiplier

    Default K=1.0 means "use existing baseline thresholds unchanged".
    """

    _DIMENSIONS = ("K_AI_GATE", "K_REGIME_PASS", "K_CONFIDENCE", "K_SIZE_FLOOR")

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._k: Dict[str, KValue] = {
            "K_AI_GATE": KValue("K_AI_GATE", 1.0, _K_FLOOR, _K_CEILING),
            "K_REGIME_PASS": KValue("K_REGIME_PASS", 1.0, _K_FLOOR, _K_CEILING),
            "K_CONFIDENCE": KValue("K_CONFIDENCE", 1.0, _K_FLOOR, _K_CEILING),
            "K_SIZE_FLOOR": KValue("K_SIZE_FLOOR", 1.0, _K_FLOOR, _K_CEILING),
        }
        self._history: Deque[KHistory] = deque(maxlen=200)
        self._cooldowns: Dict[str, float] = {}

    def get(self, name: str) -> float:
        with self._lock:
            kv = self._k.get(name)
            return kv.value if kv is not None else 1.0

    def apply_step(self, name: str, delta: float, reason: str, source: str = "auto") -> bool:
        """Apply a bounded step to the named K dimension.

        Returns True if the value was actually changed (not clamped to same).
        """
        with self._lock:
            kv = self._k.get(name)
            if kv is None:
                logger.warning("ControlMatrix: unknown dimension %s", name)
                return False
            now = time.time()
            last_update = self._cooldowns.get(name, 0.0)
            if now - last_update < _K_COOLDOWN_S:
                logger.debug("ControlMatrix: %s cooldown active (%.0fs remaining)", name, _K_COOLDOWN_S - (now - last_update))
                return False

            old_value = kv.value
            # Clamp the step so one update cannot exceed _K_MAX_STEP
            clamped_delta = max(-_K_MAX_STEP, min(_K_MAX_STEP, delta))
            kv.apply_step(clamped_delta, reason)
            if kv.value != old_value:
                self._cooldowns[name] = now
                self._history.append(KHistory(
                    name=name,
                    old_value=old_value,
                    new_value=kv.value,
                    reason=reason,
                    source=source,
                ))
                logger.info(
                    "ControlMatrix K update | %s: %.4f → %.4f | reason=%s source=%s",
                    name, old_value, kv.value, reason, source,
                )
                return True
            return False

    def reset(self, name: str, reason: str = "rollback") -> None:
        """Reset a K dimension to 1.0 (neutral baseline)."""
        with self._lock:
            kv = self._k.get(name)
            if kv is not None:
                old = kv.value
                kv.value = 1.0
                kv.last_updated = time.time()
                kv.last_update_reason = reason
                kv.update_count += 1
                self._history.append(KHistory(name=name, old_value=old, new_value=1.0, reason=reason, source="reset"))

    def get_all(self) -> Dict[str, Any]:
        with self._lock:
            return {name: kv.to_dict() for name, kv in self._k.items()}

    def get_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            items = list(self._history)[-limit:]
        return [asdict(h) for h in reversed(items)]


# ---------------------------------------------------------------------------
# FeedbackInstabilityDetector
# ---------------------------------------------------------------------------

class FeedbackInstabilityDetector:
    """
    Detects oscillation patterns in the signal acceptance history.

    For each (symbol, regime) key it maintains a rolling window of
    accept/reject timestamps and detects:

    * High flip rate (outcome alternates rapidly)
    * Cluster-level rejection concentration (via FailureClusterEngine)
    * Repeated K bumps for the same key (from ControlMatrix history)
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        # {key: deque of (ts, accepted: bool)}
        self._history: Dict[str, Deque[Tuple[float, bool]]] = {}
        # {key: (freeze_until_ts, level)}
        self._freezes: Dict[str, Tuple[float, InstabilityLevel]] = {}

    @staticmethod
    def _make_key(symbol: str, regime: str) -> str:
        return f"{symbol.upper()}|{(regime or 'unknown').lower()}"

    def record(self, symbol: str, regime: str, accepted: bool) -> None:
        """Record a compile decision for a symbol/regime pair."""
        key = self._make_key(symbol, regime)
        now = time.time()
        with self._lock:
            if key not in self._history:
                self._history[key] = deque(maxlen=100)
            self._history[key].append((now, accepted))

    def check(self, symbol: str, regime: str) -> Tuple[InstabilityLevel, str]:
        """
        Check whether a symbol/regime is currently unstable.

        Returns (level, reason).  MILD and SEVERE callers should take action.
        """
        key = self._make_key(symbol, regime)
        now = time.time()

        with self._lock:
            # Check active freeze
            if key in self._freezes:
                freeze_until, level = self._freezes[key]
                if now < freeze_until:
                    remaining = int(freeze_until - now)
                    return level, f"instability_freeze_active:{remaining}s_remaining"
                else:
                    del self._freezes[key]

            history = list(self._history.get(key, deque()))

        if not history:
            return InstabilityLevel.NONE, ""

        # Count flips in instability window
        cutoff = now - _INSTABILITY_WINDOW_S
        recent = [(ts, acc) for ts, acc in history if ts >= cutoff]
        flips = 0
        for i in range(1, len(recent)):
            if recent[i][1] != recent[i - 1][1]:
                flips += 1

        if flips >= _INSTABILITY_SEVERE_THRESHOLD:
            level = InstabilityLevel.SEVERE
            reason = f"severe_oscillation:flips={flips}:window={int(_INSTABILITY_WINDOW_S)}s"
            with self._lock:
                self._freezes[key] = (now + _INSTABILITY_FREEZE_S, level)
            logger.warning(
                "ControlCompiler: SEVERE instability detected for %s | %s | freezing for %.0fs",
                key, reason, _INSTABILITY_FREEZE_S,
            )
            return level, reason

        if flips >= _INSTABILITY_FLIP_THRESHOLD:
            reason = f"mild_oscillation:flips={flips}:window={int(_INSTABILITY_WINDOW_S)}s"
            logger.info("ControlCompiler: MILD instability for %s | %s", key, reason)
            return InstabilityLevel.MILD, reason

        # Also probe FailureClusterEngine for high rejection concentration
        cluster_reason = self._check_failure_clusters(symbol, regime)
        if cluster_reason:
            return InstabilityLevel.MILD, cluster_reason

        return InstabilityLevel.NONE, ""

    @staticmethod
    def _check_failure_clusters(symbol: str, regime: str) -> str:
        """Returns a non-empty reason string if FailureClusters show high rejection."""
        try:
            try:
                from bot.failure_cluster_engine import get_failure_cluster_engine
            except ImportError:
                from failure_cluster_engine import get_failure_cluster_engine  # type: ignore[import]
            patterns = get_failure_cluster_engine().get_top_failure_patterns(limit=10)
            norm_regime = (regime or "unknown").lower()
            for p in patterns:
                if str(p.get("regime", "")).lower() == norm_regime:
                    if float(p.get("rejection_rate", 0.0)) >= 0.80 and int(p.get("sample_count", 0)) >= 5:
                        return f"failure_cluster:{p.get('cluster_id', '')}:rate={p.get('rejection_rate', 0):.2f}"
        except Exception:
            pass
        return ""

    def get_freezes(self) -> Dict[str, Any]:
        now = time.time()
        with self._lock:
            return {
                k: {
                    "freeze_until": v[0],
                    "remaining_s": max(0.0, v[0] - now),
                    "level": v[1].value,
                }
                for k, v in self._freezes.items()
                if v[0] > now
            }

    def clear_freeze(self, symbol: str, regime: str) -> None:
        """Manually clear an instability freeze (e.g. after operator review)."""
        key = self._make_key(symbol, regime)
        with self._lock:
            self._freezes.pop(key, None)


# ---------------------------------------------------------------------------
# SignalValidator
# ---------------------------------------------------------------------------

class SignalValidator:
    """
    Validates a RawSignal against the canonical signal contract.

    Phase 1 — Schema: field types and required presence.
    Phase 2 — Invariants: logical consistency rules.
    Phase 3 — K-gate: apply current ControlMatrix thresholds.
    """

    # Invariant reason codes (stable strings for downstream consumers)
    RC_MISSING_SYMBOL = "invariant:missing_symbol"
    RC_INVALID_SIDE = "invariant:invalid_side"
    RC_SIDE_ACTION_MISMATCH = "invariant:side_action_mismatch"
    RC_NON_FINITE_SIZE = "invariant:non_finite_size"
    RC_NEGATIVE_SIZE = "invariant:negative_size"
    RC_NON_FINITE_CONFIDENCE = "invariant:non_finite_confidence"
    RC_CONFIDENCE_OUT_OF_RANGE = "invariant:confidence_out_of_range"
    RC_NOT_APPROVED = "invariant:not_approved"
    RC_EMPTY_REGIME = "invariant:empty_regime"
    RC_SCHEMA_TYPE = "schema:type_error"
    RC_K_CONFIDENCE = "k_gate:confidence_below_threshold"
    RC_K_SIZE = "k_gate:size_below_floor"

    def validate(
        self,
        raw: RawSignal,
        matrix: ControlMatrix,
    ) -> Tuple[bool, str, str, Optional[ControlSignal]]:
        """
        Validate *raw* against the signal contract.

        Returns (ok, reason, reason_code, signal_or_None).
        """
        # ── Phase 1: Schema ─────────────────────────────────────────────
        schema_ok, schema_reason = self._check_schema(raw)
        if not schema_ok:
            return False, schema_reason, self.RC_SCHEMA_TYPE, None

        # ── Phase 2: Invariants ─────────────────────────────────────────
        inv_ok, inv_reason, inv_code = self._check_invariants(raw)
        if not inv_ok:
            return False, inv_reason, inv_code, None

        # ── Normalize ───────────────────────────────────────────────────
        normalized_side = _normalize_side(raw.side, raw.action)
        normalized_regime = (raw.regime or "unknown").lower().strip()

        # ── Phase 3: K-gate ─────────────────────────────────────────────
        k_ok, k_reason, k_code = self._check_k_gates(raw, normalized_side, matrix)
        if not k_ok:
            return False, k_reason, k_code, None

        signal = ControlSignal(
            symbol=raw.symbol.strip().upper(),
            side=normalized_side,
            action=raw.action.lower().strip(),
            size_usd=float(raw.size_usd),
            confidence=float(raw.confidence),
            regime=normalized_regime,
            strategy=raw.strategy or "",
            account_id=raw.account_id or "default",
            order_type=raw.order_type,
            asset_class=raw.asset_class,
            preferred_broker=raw.preferred_broker,
            available_balance_usd=raw.available_balance_usd,
            price_hint_usd=raw.price_hint_usd,
            metadata=dict(raw.metadata or {}),
        )
        return True, "", "", signal

    # ------------------------------------------------------------------
    # Phase 1 – Schema
    # ------------------------------------------------------------------

    @staticmethod
    def _check_schema(raw: RawSignal) -> Tuple[bool, str]:
        """Type and presence checks."""
        if not isinstance(raw.symbol, str):
            return False, f"symbol must be str, got {type(raw.symbol).__name__}"
        if not isinstance(raw.side, str):
            return False, f"side must be str, got {type(raw.side).__name__}"
        if not isinstance(raw.action, str):
            return False, f"action must be str, got {type(raw.action).__name__}"
        try:
            _ = float(raw.size_usd)
        except (TypeError, ValueError):
            return False, f"size_usd must be numeric, got {type(raw.size_usd).__name__}"
        try:
            _ = float(raw.confidence)
        except (TypeError, ValueError):
            return False, f"confidence must be numeric, got {type(raw.confidence).__name__}"
        return True, ""

    # ------------------------------------------------------------------
    # Phase 2 – Invariants
    # ------------------------------------------------------------------

    def _check_invariants(self, raw: RawSignal) -> Tuple[bool, str, str]:
        """Logical consistency rules."""
        symbol = raw.symbol.strip() if isinstance(raw.symbol, str) else ""
        if not symbol:
            return False, "symbol is required and must be non-empty", self.RC_MISSING_SYMBOL

        # Normalize side/action to canonical form
        side = raw.side.lower().strip()
        action = raw.action.lower().strip()
        effective_side = _normalize_side(side, action)
        if effective_side not in {"buy", "sell", ""}:
            return (
                False,
                f"side '{raw.side}' with action '{raw.action}' cannot be resolved to buy/sell",
                self.RC_INVALID_SIDE,
            )

        # For execution actions (enter_long / enter_short), side must be resolvable
        if action in _EXECUTION_ACTIONS and not effective_side:
            return (
                False,
                f"action='{action}' requires a resolvable side; got side='{raw.side}'",
                self.RC_SIDE_ACTION_MISMATCH,
            )

        # For execution actions, 'approved' must be truthy
        if action in _EXECUTION_ACTIONS and not raw.approved:
            return (
                False,
                "signal has approved=False but action is an execution action",
                self.RC_NOT_APPROVED,
            )

        # size_usd finiteness
        size = float(raw.size_usd)
        if not math.isfinite(size):
            return False, f"size_usd must be finite, got {size}", self.RC_NON_FINITE_SIZE
        if action in _EXECUTION_ACTIONS and size < 0:
            return False, f"size_usd must be non-negative for entry, got {size}", self.RC_NEGATIVE_SIZE

        # confidence finiteness and range
        confidence = float(raw.confidence)
        if not math.isfinite(confidence):
            return False, f"confidence must be finite, got {confidence}", self.RC_NON_FINITE_CONFIDENCE
        if not (0.0 <= confidence <= 1.0):
            return (
                False,
                f"confidence {confidence:.4f} out of [0.0, 1.0]",
                self.RC_CONFIDENCE_OUT_OF_RANGE,
            )

        # regime must not be empty (use "unknown" explicitly instead of empty string)
        regime = (raw.regime or "").strip()
        if not regime:
            return False, "regime must be non-empty (use 'unknown' if unknown)", self.RC_EMPTY_REGIME

        return True, "", ""

    # ------------------------------------------------------------------
    # Phase 3 – K-gates
    # ------------------------------------------------------------------

    def _check_k_gates(
        self, raw: RawSignal, side: str, matrix: ControlMatrix
    ) -> Tuple[bool, str, str]:
        """Apply ControlMatrix K thresholds."""
        action = raw.action.lower().strip()
        if action not in _EXECUTION_ACTIONS:
            # Non-execution actions (hold, no_trade) pass K gates unconditionally
            return True, "", ""

        confidence = float(raw.confidence)
        k_conf = matrix.get("K_CONFIDENCE")
        effective_conf_floor = _MIN_CONFIDENCE_BASELINE * k_conf
        if effective_conf_floor > 0.0 and confidence < effective_conf_floor:
            return (
                False,
                f"confidence {confidence:.4f} below K_CONFIDENCE floor {effective_conf_floor:.4f}",
                self.RC_K_CONFIDENCE,
            )

        size = float(raw.size_usd)
        k_size = matrix.get("K_SIZE_FLOOR")
        effective_size_floor = _MIN_SIZE_USD_BASELINE * k_size
        if effective_size_floor > 0.0 and size < effective_size_floor:
            return (
                False,
                f"size_usd {size:.4f} below K_SIZE_FLOOR {effective_size_floor:.4f}",
                self.RC_K_SIZE,
            )

        return True, "", ""


# ---------------------------------------------------------------------------
# KAutoTuner
# ---------------------------------------------------------------------------

class KAutoTuner:
    """
    Periodically analyses recent trace outcomes and proposes bounded K updates.

    It reads from FailureClusterEngine and RegimeGateCalibrator (already
    maintained by SignalFunnelDiagnostics) and nudges the ControlMatrix
    gains toward better pass/quality balance.

    Rules
    -----
    * High recent rejection rate in a regime  → tighten K_AI_GATE (+ step)
    * Low recent pass probability for a path  → loosen K_AI_GATE (− step)
    * Instability freeze active              → skip that regime

    All changes are bounded by the KValue floor/ceiling and per-dimension
    cooldowns (already enforced inside ControlMatrix.apply_step).
    """

    def __init__(self, matrix: ControlMatrix) -> None:
        self._matrix = matrix
        self._lock = threading.Lock()
        self._last_run: float = 0.0
        self._run_count: int = 0

    def maybe_run(self) -> None:
        """Run one tuner cycle if the inter-run interval has elapsed."""
        now = time.time()
        with self._lock:
            if now - self._last_run < _K_TUNER_INTERVAL_S:
                return
            self._last_run = now

        try:
            self._run_cycle()
            self._run_count += 1
        except Exception as exc:
            logger.warning("KAutoTuner: cycle failed: %s", exc)

    def _run_cycle(self) -> None:
        """One calibration cycle."""
        cluster_patterns = self._fetch_cluster_patterns()
        regime_probs = self._fetch_regime_probs()

        # --- High cluster rejection rate → tighten K_AI_GATE ---
        for pattern in cluster_patterns:
            rate = float(pattern.get("rejection_rate", 0.0))
            count = int(pattern.get("sample_count", 0))
            if rate >= 0.80 and count >= 5:
                self._matrix.apply_step(
                    "K_AI_GATE",
                    delta=+_K_MAX_STEP * rate,
                    reason=f"cluster_high_rejection:rate={rate:.2f}:count={count}",
                    source="k_auto_tuner",
                )
                break  # one adjustment per cycle is enough

        # --- Low regime pass probability → loosen K_AI_GATE ---
        avg_prob = None
        if regime_probs:
            all_probs = [
                p
                for regime_dict in regime_probs.values()
                for p in regime_dict.values()
            ]
            if all_probs:
                avg_prob = sum(all_probs) / len(all_probs)

        if avg_prob is not None and avg_prob < 0.30:
            self._matrix.apply_step(
                "K_AI_GATE",
                delta=-_K_MAX_STEP,
                reason=f"regime_pass_prob_low:avg={avg_prob:.3f}",
                source="k_auto_tuner",
            )

    @staticmethod
    def _fetch_cluster_patterns() -> List[Dict[str, Any]]:
        try:
            try:
                from bot.failure_cluster_engine import get_failure_cluster_engine
            except ImportError:
                from failure_cluster_engine import get_failure_cluster_engine  # type: ignore[import]
            return get_failure_cluster_engine().get_top_failure_patterns(limit=10)
        except Exception:
            return []

    @staticmethod
    def _fetch_regime_probs() -> Dict[str, Any]:
        try:
            try:
                from bot.regime_gate_calibrator import get_regime_gate_calibrator
            except ImportError:
                from regime_gate_calibrator import get_regime_gate_calibrator  # type: ignore[import]
            return get_regime_gate_calibrator().get_regime_heatmap()
        except Exception:
            return {}


# ---------------------------------------------------------------------------
# ControlCompiler
# ---------------------------------------------------------------------------

class ControlCompiler:
    """
    Central control-compiler orchestrator.

    Combines SignalValidator, FeedbackInstabilityDetector, ControlMatrix,
    and KAutoTuner into one callable unit.

    Thread-safe singleton via ``get_control_compiler()``.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._matrix = ControlMatrix()
        self._validator = SignalValidator()
        self._instability = FeedbackInstabilityDetector()
        self._tuner = KAutoTuner(self._matrix)

        # Session counters
        self._total: int = 0
        self._accepted: int = 0
        self._rejected: int = 0
        self._rejection_reasons: Dict[str, int] = {}
        self._bootstrap_passes_used: int = 0
        self._execution_outcomes: Deque[bool] = deque(maxlen=_BOOTSTRAP_DECAY_WINDOW)
        self._last_live_execution_ts: Optional[float] = None
        self._execution_drop_counts: Dict[str, int] = {
            "compiler_confidence": 0,
            "governor_guarded": 0,
            "broker_health": 0,
            "nonce_authority": 0,
        }

        logger.info(
            "ControlCompiler initialized | K_AI_GATE=%.2f K_CONFIDENCE=%.2f "
            "K_SIZE_FLOOR=%.2f K_REGIME_PASS=%.2f",
            self._matrix.get("K_AI_GATE"),
            self._matrix.get("K_CONFIDENCE"),
            self._matrix.get("K_SIZE_FLOOR"),
            self._matrix.get("K_REGIME_PASS"),
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compile(self, raw: RawSignal) -> CompileResult:
        """
        Compile a raw signal into a validated ControlSignal.

        Steps
        -----
        1. Schema validation
        2. Invariant checks
        3. K-gate checks
        4. Instability probe (for execution actions)
        5. Return CompileResult

        Rejections are automatically fed into SignalFunnelDiagnostics.
        """
        # Opportunistically run the auto-tuner (no-op if too soon)
        try:
            self._tuner.maybe_run()
        except Exception:
            pass

        action = (raw.action or "hold").lower().strip()
        is_execution = action in _EXECUTION_ACTIONS

        # ── Phase 1-3: Validation ────────────────────────────────────────
        ok, reason, reason_code, signal = self._validator.validate(raw, self._matrix)
        if not ok and is_execution:
            signal = self._try_bootstrap_pass(raw, reason_code)
            if signal is not None:
                ok = True
                reason = ""
                reason_code = ""

        if not ok:
            status = (
                CompileStatus.SCHEMA_INVALID
                if reason_code.startswith("schema:")
                else (
                    CompileStatus.K_GATE_FAILED
                    if reason_code.startswith("k_gate:")
                    else CompileStatus.INVARIANT_FAILED
                )
            )
            result = CompileResult(
                accepted=False,
                status=status,
                reason=reason,
                reason_code=reason_code,
            )
            self._record(raw, accepted=False, reason_code=reason_code)
            self._emit_trace_rejection(raw, stage="compiler_validate", reason=reason, reason_code=reason_code)
            if is_execution:
                self._record_compiler_reject_telemetry(raw, reason_code)
            return result

        assert signal is not None  # guaranteed by validator

        # ── Phase 4: Instability probe (execution signals only) ──────────
        if is_execution:
            level, inst_reason = self._instability.check(raw.symbol, raw.regime)

            if level == InstabilityLevel.SEVERE:
                result = CompileResult(
                    accepted=False,
                    status=CompileStatus.INSTABILITY_FROZEN,
                    reason=inst_reason,
                    reason_code="instability:frozen",
                )
                self._record(raw, accepted=False, reason_code="instability:frozen")
                self._emit_trace_rejection(
                    raw, stage="compiler_instability", reason=inst_reason, reason_code="instability:frozen"
                )
                self._emit_execution_decision(
                    reason="governor_guarded",
                    confidence=float(raw.confidence),
                    threshold=0.0,
                    governor_mode="GUARDED",
                )
                # K auto-response: tighten AI gate
                self._matrix.apply_step(
                    "K_AI_GATE",
                    delta=+_K_MAX_STEP,
                    reason=f"severe_instability:{raw.symbol}:{raw.regime}",
                    source="instability_detector",
                )
                return result

            if level == InstabilityLevel.MILD:
                # Tighten K slightly but allow execution to proceed
                self._matrix.apply_step(
                    "K_AI_GATE",
                    delta=+_K_MAX_STEP * 0.5,
                    reason=f"mild_instability:{raw.symbol}:{raw.regime}",
                    source="instability_detector",
                )

        # ── Accept ───────────────────────────────────────────────────────
        if is_execution:
            self._instability.record(raw.symbol, raw.regime, accepted=True)
        self._record(raw, accepted=True, reason_code="")
        if is_execution:
            k_conf_threshold = _MIN_CONFIDENCE_BASELINE * self._matrix.get("K_CONFIDENCE")
            bootstrap_pass = bool(getattr(signal, "metadata", {}).get("bootstrap_pass"))
            self._emit_execution_decision(
                allow=True,
                reason="compiler_bootstrap_pass" if bootstrap_pass else "compiler_passed",
                confidence=float(raw.confidence),
                threshold=float(k_conf_threshold),
                governor_mode="RECOVERING" if bootstrap_pass else "NORMAL",
            )
        return CompileResult(
            accepted=True,
            status=CompileStatus.ACCEPTED,
            signal=signal,
        )

    def compile_dict(self, signal_dict: Dict[str, Any]) -> CompileResult:
        """
        Convenience wrapper: compile a raw signal dict directly.

        Handles the varied dict shapes produced by MasterStrategyRouter,
        TradingView webhooks, and SignalBroadcaster.
        """
        action = str(signal_dict.get("action") or signal_dict.get("side") or "hold").lower()
        # Map broadcaster / webhook actions to canonical form
        if action in ("buy", "long"):
            action = "enter_long"
        elif action in ("sell", "short"):
            action = "enter_short"

        side = str(signal_dict.get("side") or "")
        if side in ("long", "enter_long"):
            side = "buy"
        elif side in ("short", "enter_short"):
            side = "sell"

        raw = RawSignal(
            symbol=str(signal_dict.get("symbol") or ""),
            side=side,
            action=action,
            size_usd=float(signal_dict.get("size_usd") or signal_dict.get("size") or 0.0),
            confidence=float(signal_dict.get("confidence") or 0.0),
            regime=str(signal_dict.get("regime") or "unknown"),
            strategy=str(signal_dict.get("strategy") or ""),
            account_id=str(signal_dict.get("account_id") or "default"),
            order_type=signal_dict.get("order_type"),
            asset_class=signal_dict.get("asset_class"),
            preferred_broker=signal_dict.get("preferred_broker") or signal_dict.get("broker"),
            available_balance_usd=(
                float(v) if (v := signal_dict.get("available_balance_usd")) is not None else None
            ),
            price_hint_usd=(
                float(v) if (v := signal_dict.get("price_hint_usd")) is not None else None
            ),
            approved=bool(signal_dict.get("approved", True)),
            metadata={k: v for k, v in signal_dict.items()},
        )
        return self.compile(raw)

    # ------------------------------------------------------------------
    # Observability
    # ------------------------------------------------------------------

    def get_health(self) -> Dict[str, Any]:
        """Return a health snapshot suitable for dashboard ingestion."""
        with self._lock:
            total = self._total
            accepted = self._accepted
            rejected = self._rejected
            reasons = dict(self._rejection_reasons)
            bootstrap_used = self._bootstrap_passes_used
            bootstrap_decay = self._compute_bootstrap_decay_state_unlocked()

        accept_rate = (accepted / total) if total > 0 else 1.0
        return {
            "available": True,
            "total_compiled": total,
            "accepted": accepted,
            "rejected": rejected,
            "accept_rate": round(accept_rate, 4),
            "rejection_reasons": reasons,
            "bootstrap_pass": {
                "enabled": _BOOTSTRAP_PASS_ENABLED,
                "limit": _BOOTSTRAP_PASS_LIMIT,
                "used": bootstrap_used,
                "remaining": max(0, bootstrap_decay["effective_limit"] - bootstrap_used),
                "min_confidence": _BOOTSTRAP_MIN_CONFIDENCE,
                "effective_limit": bootstrap_decay["effective_limit"],
                "effective_min_confidence": round(bootstrap_decay["effective_min_confidence"], 6),
                "decay_progress": round(bootstrap_decay["decay_progress"], 6),
                "acceptance_rate": round(bootstrap_decay["acceptance_rate"], 6),
                "samples": bootstrap_decay["samples"],
                "live_execution_gap_s": bootstrap_decay["live_execution_gap_s"],
                "starvation_recovery_active": bootstrap_decay["starvation_recovery_active"],
            },
            "execution_drop_counts": dict(self._execution_drop_counts),
            "k_values": self._matrix.get_all(),
            "k_history": self._matrix.get_history(limit=20),
            "active_freezes": self._instability.get_freezes(),
        }

    def get_matrix(self) -> ControlMatrix:
        return self._matrix

    def get_instability_detector(self) -> FeedbackInstabilityDetector:
        return self._instability

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _record(self, raw: RawSignal, accepted: bool, reason_code: str) -> None:
        action = (raw.action or "hold").lower().strip()
        is_execution = action in _EXECUTION_ACTIONS
        with self._lock:
            self._total += 1
            if accepted:
                self._accepted += 1
            else:
                self._rejected += 1
                if reason_code:
                    self._rejection_reasons[reason_code] = (
                        self._rejection_reasons.get(reason_code, 0) + 1
                    )
            if is_execution:
                self._execution_outcomes.append(bool(accepted))
                if accepted:
                    self._last_live_execution_ts = time.time()
        if not accepted:
            # Also record in instability detector for non-schema rejections
            if is_execution and not reason_code.startswith("schema:"):
                self._instability.record(raw.symbol, raw.regime, accepted=False)

    def _emit_execution_decision(
        self,
        *,
        allow: bool = False,
        reason: str,
        confidence: float,
        threshold: float,
        governor_mode: str,
        stage: str = "control_compiler",
    ) -> None:
        decision = ExecutionDecision(
            stage=stage,
            allow=bool(allow),
            reason=reason,
            confidence=float(confidence),
            threshold=float(threshold),
            governor_mode=governor_mode,
        )
        logger.info(
            "ExecutionDecision(stage=%s, allow=%s, reason=%s, confidence=%.4f, threshold=%.4f, governor_mode=%s)",
            decision.stage,
            decision.allow,
            decision.reason,
            decision.confidence,
            decision.threshold,
            decision.governor_mode,
        )

    def _increment_drop_count(self, bucket: str) -> None:
        with self._lock:
            if bucket in self._execution_drop_counts:
                self._execution_drop_counts[bucket] += 1

    def record_external_execution_drop(
        self,
        *,
        reason: str,
        drop_bucket: str,
        governor_mode: str = "UNKNOWN",
        confidence: float = 0.0,
        threshold: float = 0.0,
        stage: str = "control_compiler",
    ) -> None:
        """Record a non-compiler trade-admission deny in canonical telemetry."""
        self._increment_drop_count(drop_bucket)
        self._emit_execution_decision(
            allow=False,
            stage=stage,
            reason=reason,
            confidence=confidence,
            threshold=threshold,
            governor_mode=governor_mode,
        )

    def _record_compiler_reject_telemetry(self, raw: RawSignal, reason_code: str) -> None:
        try:
            confidence = float(raw.confidence)
        except (TypeError, ValueError):
            confidence = 0.0

        threshold = 0.0
        reason = reason_code or "compiler_reject"
        governor_mode = "NORMAL"
        if reason_code == SignalValidator.RC_K_CONFIDENCE:
            threshold = _MIN_CONFIDENCE_BASELINE * self._matrix.get("K_CONFIDENCE")
            reason = "confidence_below_threshold"
            governor_mode = "GUARDED"
            self._increment_drop_count("compiler_confidence")

        self._emit_execution_decision(
            allow=False,
            reason=reason,
            confidence=confidence,
            threshold=threshold,
            governor_mode=governor_mode,
        )

    def _compute_bootstrap_decay_state_unlocked(self) -> Dict[str, Any]:
        """
        Compute bootstrap decay state from execution outcomes.

        Caller must hold ``self._lock``.
        """
        samples = len(self._execution_outcomes)
        accepted = sum(1 for value in self._execution_outcomes if value)
        acceptance_rate = (accepted / samples) if samples > 0 else 0.0
        smoothed_acceptance = ((accepted + 1.0) / (samples + 2.0)) if samples > 0 else 0.5

        decay_progress = 0.0
        if samples >= _BOOTSTRAP_DECAY_MIN_SAMPLES:
            target = _BOOTSTRAP_DECAY_TARGET_ACCEPT_RATE
            baseline = min(_BOOTSTRAP_DECAY_BASELINE_ACCEPT_RATE, target - 1e-6)
            span = max(1e-6, target - baseline)
            decay_progress = (smoothed_acceptance - baseline) / span
            decay_progress = max(0.0, min(1.0, decay_progress))

        decay_multiplier = max(0.0, (1.0 - decay_progress) ** _BOOTSTRAP_DECAY_SHAPE)
        effective_limit = int(round(_BOOTSTRAP_PASS_LIMIT * decay_multiplier))
        effective_limit = max(0, min(_BOOTSTRAP_PASS_LIMIT, effective_limit))

        k_conf = self._matrix.get("K_CONFIDENCE")
        target_conf_floor = max(_BOOTSTRAP_MIN_CONFIDENCE, _MIN_CONFIDENCE_BASELINE * k_conf)
        effective_min_confidence = _BOOTSTRAP_MIN_CONFIDENCE + (
            (target_conf_floor - _BOOTSTRAP_MIN_CONFIDENCE) * decay_progress
        )
        last_live_ts = self._last_live_execution_ts
        live_execution_gap_s = (time.time() - last_live_ts) if last_live_ts else float("inf")
        starvation_recovery_active = False
        if last_live_ts is not None:
            starvation_recovery_active = bool(live_execution_gap_s > _MIN_LIVE_EXECUTION_GAP_S)
        elif samples >= _BOOTSTRAP_DECAY_MIN_SAMPLES:
            # Pre-first-live-execution recovery: only engage after enough
            # observed execution outcomes to avoid immediate over-bypass.
            starvation_recovery_active = True
        if starvation_recovery_active:
            effective_min_confidence *= _MIN_LIVE_EXECUTION_CONF_RELAX
            # Recovery floor is rolling while starved so bootstrap credits do not
            # permanently exhaust after the first recovery pass.
            effective_limit = max(
                _MIN_LIVE_EXECUTION_LIMIT_FLOOR,
                self._bootstrap_passes_used + _MIN_LIVE_EXECUTION_LIMIT_FLOOR,
                effective_limit,
            )

        return {
            "samples": samples,
            "accepted": accepted,
            "acceptance_rate": acceptance_rate,
            "decay_progress": decay_progress,
            "effective_limit": effective_limit,
            "effective_min_confidence": max(0.0, min(1.0, effective_min_confidence)),
            "live_execution_gap_s": (
                round(live_execution_gap_s, 3) if math.isfinite(live_execution_gap_s) else None
            ),
            "starvation_recovery_active": starvation_recovery_active,
        }

    def _get_bootstrap_decay_state(self) -> Dict[str, Any]:
        with self._lock:
            return self._compute_bootstrap_decay_state_unlocked()

    def _emit_trace_rejection(
        self,
        raw: RawSignal,
        stage: str,
        reason: str,
        reason_code: str,
    ) -> None:
        """Feed compiler-stage rejections into the existing trace infrastructure."""
        try:
            try:
                from bot.signal_funnel_diagnostics import get_signal_funnel
            except ImportError:
                from signal_funnel_diagnostics import get_signal_funnel  # type: ignore[import]
            funnel = get_signal_funnel()
            side = _normalize_side(raw.side, raw.action) or raw.side or "unknown"
            pair = (raw.symbol or "unknown").upper()

            # Start a trace if none is active; otherwise the rejection just
            # appends to the existing attempt.
            funnel.start_execution_trace(
                pair=pair,
                side=side,
                reason=reason,
                extra={
                    "compiler_stage": stage,
                    "reason_code": reason_code,
                    "regime": raw.regime or "unknown",
                    "confidence": raw.confidence,
                    "action": raw.action,
                },
            )
            funnel.record_execution_stage(
                pair=pair,
                stage=stage,
                outcome="rejected",
                side=side,
                reason=reason,
                extra={
                    "reason_code": reason_code,
                    "regime": raw.regime or "unknown",
                },
            )
        except Exception as exc:
            logger.debug("ControlCompiler: trace emission failed: %s", exc)

    def _try_bootstrap_pass(self, raw: RawSignal, reason_code: str) -> Optional[ControlSignal]:
        """
        Allow a bounded compiler bootstrap pass for synthetic/low-threshold signals.

        This only applies to K-confidence rejections for execution actions.
        """
        if not _BOOTSTRAP_PASS_ENABLED:
            return None
        if reason_code != SignalValidator.RC_K_CONFIDENCE:
            return None
        confidence = float(raw.confidence)
        decay_state = self._get_bootstrap_decay_state()
        effective_min_confidence = float(decay_state["effective_min_confidence"])
        if confidence < effective_min_confidence:
            return None

        metadata = raw.metadata or {}
        starvation_recovery_active = bool(decay_state.get("starvation_recovery_active"))
        synthetic = bool(
            metadata.get("synthetic")
            or metadata.get("diagnostic")
            or metadata.get("probe")
            or metadata.get("volume_fallback")
            or metadata.get("bypass_low_quality")
            or metadata.get("bypass_quality_filter")
            or metadata.get("weak_signal_entry")
            or metadata.get("fallback_entry")
        )
        low_threshold = bool(metadata.get("bootstrap_low_threshold") or metadata.get("low_threshold"))
        if not (synthetic or low_threshold or starvation_recovery_active):
            return None

        with self._lock:
            effective_limit = self._compute_bootstrap_decay_state_unlocked()["effective_limit"]
            if effective_limit <= 0:
                return None
            if self._bootstrap_passes_used >= effective_limit:
                return None
            self._bootstrap_passes_used += 1
            used = self._bootstrap_passes_used

        signal = ControlSignal(
            symbol=raw.symbol.strip().upper(),
            side=_normalize_side(raw.side, raw.action),
            action=(raw.action or "").lower().strip(),
            size_usd=float(raw.size_usd),
            confidence=confidence,
            regime=(raw.regime or "unknown").lower().strip(),
            strategy=raw.strategy or "",
            account_id=raw.account_id or "default",
            order_type=raw.order_type,
            asset_class=raw.asset_class,
            preferred_broker=raw.preferred_broker,
            available_balance_usd=raw.available_balance_usd,
            price_hint_usd=raw.price_hint_usd,
            metadata=dict(metadata),
        )
        signal.metadata["bootstrap_pass"] = True
        signal.metadata["bootstrap_pass_index"] = used
        signal.metadata["bootstrap_reason"] = "k_confidence_override"
        signal.metadata["bootstrap_effective_limit"] = effective_limit
        signal.metadata["bootstrap_decay_progress"] = round(float(decay_state["decay_progress"]), 6)
        signal.metadata["bootstrap_effective_min_confidence"] = round(effective_min_confidence, 6)
        logger.warning(
            "COMPILER_BOOTSTRAP_PASS symbol=%s action=%s confidence=%.3f used=%d/%d decay=%.3f",
            signal.symbol,
            signal.action,
            signal.confidence,
            used,
            effective_limit,
            float(decay_state["decay_progress"]),
        )
        return signal


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize_side(side: str, action: str) -> str:
    """
    Resolve the canonical buy/sell side from (side, action) pair.

    Returns "" when neither field gives a conclusive answer.
    """
    side_lc = (side or "").lower().strip()
    if side_lc in ("buy", "long", "enter_long"):
        return "buy"
    if side_lc in ("sell", "short", "enter_short"):
        return "sell"
    action_lc = (action or "").lower().strip()
    if action_lc in ("enter_long", "buy", "long"):
        return "buy"
    if action_lc in ("enter_short", "sell", "short"):
        return "sell"
    return ""


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_singleton: Optional[ControlCompiler] = None
_singleton_lock = threading.Lock()


def get_control_compiler() -> ControlCompiler:
    """Return the process-level ControlCompiler singleton."""
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                _singleton = ControlCompiler()
    return _singleton
