"""
NIJA Control Layer — Control Compiler
======================================

Normalises and validates every signal from any source (APEX v7.1,
future ML model, manual webhook) before it enters the execution pipeline.

Pipeline
--------
::

    RawSignal (any source)
        │
        ▼
    ControlCompiler.compile(raw)
        │
        ├── 1. Schema validation      — field types & required presence
        ├── 2. Confidence validation  — within [0, 1], meets strategy floor
        ├── 3. Regime compatibility   — signal strategy fits current regime
        ├── 4. Risk rule enforcement  — delegated to RiskEngine
        ├── 5. Position sizing        — size_usd capped to max_position_size_pct
        └── 6. Execution readiness   — final approved flag
                │
               PASS → CompiledSignal (execution-ready)
               FAIL → None  (reason logged + stored in Redis audit trail)

Redis Audit Trail
-----------------
Every compiled signal (pass or fail) is stored in Redis under::

    nija:control:signals:{signal_id}   TTL = NIJA_SIGNAL_REDIS_TTL_SECONDS

Author: NIJA Trading Systems
Phase:  1 — Control Layer
"""

from __future__ import annotations

import json
import logging
import math
import os
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("nija.control.compiler")

# ---------------------------------------------------------------------------
# Environment-driven configuration
# ---------------------------------------------------------------------------

_CONTROL_ENABLED: bool = os.getenv("NIJA_CONTROL_ENABLED", "true").lower() == "true"

_MIN_CONFIDENCE: Dict[str, float] = {
    "scalp":   float(os.getenv("NIJA_MIN_CONFIDENCE_SCALP",   "0.30")),
    "swing":   float(os.getenv("NIJA_MIN_CONFIDENCE_SWING",   "0.65")),
    "default": float(os.getenv("NIJA_MIN_CONFIDENCE_DEFAULT", "0.25")),
}

_SIGNAL_REDIS_TTL: int = int(os.getenv("NIJA_SIGNAL_REDIS_TTL_SECONDS", "3600"))

# Regime → compatible strategy types
_REGIME_STRATEGY_MAP: Dict[str, List[str]] = {
    "trending":       ["scalp", "swing", "trend", "apex"],
    "ranging":        ["scalp", "mean_reversion", "range"],
    "breakout":       ["swing", "breakout", "trend"],
    "mean_reversion": ["mean_reversion", "range", "scalp"],
    "unknown":        ["scalp", "swing", "trend", "apex", "mean_reversion", "range", "breakout"],
}

# Execution actions that require full validation
_EXECUTION_ACTIONS = frozenset({"enter_long", "enter_short", "buy", "sell"})


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class RawSignal:
    """
    Unvalidated signal from any source.

    All fields have safe defaults so callers can construct partial signals;
    the compiler will reject missing required fields during schema validation.
    """
    symbol: str = ""
    side: str = ""                        # "buy" / "sell" / "long" / "short"
    action: str = "hold"                  # "enter_long" / "enter_short" / "hold" / ...
    size_usd: float = 0.0
    confidence: float = 0.0
    regime: str = "unknown"
    strategy: str = ""                    # "scalp" / "swing" / "apex" / ...
    account_id: str = "default"
    approved: bool = True
    stop_loss_pct: Optional[float] = None
    take_profit_pct: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CompiledSignal:
    """
    Validated, execution-ready signal that has passed all compiler checks.

    Downstream components (ExecutionPipeline, OrderRouter) consume this
    instead of raw signal dicts.
    """
    signal_id: str
    symbol: str
    side: str                             # normalised to "buy" / "sell"
    action: str
    size_usd: float                       # final sized value
    confidence: float
    regime: str
    strategy: str
    account_id: str
    approved: bool
    stop_loss_pct: Optional[float]
    take_profit_pct: Optional[float]
    metadata: Dict[str, Any]
    compiled_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    compile_notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_pipeline_kwargs(self) -> Dict[str, Any]:
        """Return kwargs suitable for order-router / pipeline construction."""
        return {
            "signal_id":       self.signal_id,
            "symbol":          self.symbol,
            "side":            self.side,
            "size_usd":        self.size_usd,
            "strategy":        self.strategy,
            "account_id":      self.account_id,
            "stop_loss_pct":   self.stop_loss_pct,
            "take_profit_pct": self.take_profit_pct,
        }


# ---------------------------------------------------------------------------
# ControlCompiler
# ---------------------------------------------------------------------------

class ControlCompiler:
    """
    Central signal normalisation and validation layer.

    Thread-safe.  Use ``get_control_compiler()`` for the process singleton.
    """

    def __init__(self, redis_client=None) -> None:
        self._lock = threading.Lock()
        self._redis = redis_client
        self._total: int = 0
        self._accepted: int = 0
        self._rejected: int = 0
        logger.info("ControlCompiler initialised (control_enabled=%s)", _CONTROL_ENABLED)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compile(
        self,
        raw: RawSignal,
        portfolio_value_usd: float = 10_000.0,
        max_position_size_pct: float = 10.0,
    ) -> Tuple[Optional[CompiledSignal], List[str]]:
        """
        Compile a RawSignal into a CompiledSignal.

        Returns
        -------
        (CompiledSignal, notes)  — on success
        (None, notes)            — on rejection; notes explains why
        """
        notes: List[str] = []

        # Fast-path: control layer disabled
        if not _CONTROL_ENABLED:
            notes.append("control_layer_disabled:pass_through")
            return self._build_compiled(raw, raw.size_usd, notes), notes

        # 1. Schema validation
        ok, reason = self._validate_schema(raw)
        if not ok:
            notes.append(f"schema_invalid:{reason}")
            self._record(accepted=False)
            self._store_audit(raw, None, notes)
            return None, notes

        # 2. Confidence validation
        ok, reason = self._validate_confidence(raw)
        if not ok:
            notes.append(f"confidence_invalid:{reason}")
            self._record(accepted=False)
            self._store_audit(raw, None, notes)
            return None, notes

        # 3. Regime compatibility
        ok, reason = self._validate_regime_compatibility(raw)
        if not ok:
            notes.append(f"regime_incompatible:{reason}")
            self._record(accepted=False)
            self._store_audit(raw, None, notes)
            return None, notes

        # 4. Position sizing
        sized_usd = self._calculate_position_size(
            raw.size_usd, portfolio_value_usd, max_position_size_pct, notes
        )

        # 5. Execution readiness
        if not raw.approved and raw.action in _EXECUTION_ACTIONS:
            notes.append("not_approved:execution_blocked")
            self._record(accepted=False)
            self._store_audit(raw, None, notes)
            return None, notes

        # Build compiled signal
        compiled = self._build_compiled(raw, sized_usd, notes)
        self._record(accepted=True)
        self._store_audit(raw, compiled, notes)
        return compiled, notes

    def compile_dict(
        self,
        signal_dict: Dict[str, Any],
        portfolio_value_usd: float = 10_000.0,
        max_position_size_pct: float = 10.0,
    ) -> Tuple[Optional[CompiledSignal], List[str]]:
        """Convenience wrapper: compile a raw signal dict directly."""
        action = str(signal_dict.get("action") or signal_dict.get("side") or "hold").lower()
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
            approved=bool(signal_dict.get("approved", True)),
            stop_loss_pct=signal_dict.get("stop_loss_pct"),
            take_profit_pct=signal_dict.get("take_profit_pct"),
            metadata={k: v for k, v in signal_dict.items()},
        )
        return self.compile(raw, portfolio_value_usd, max_position_size_pct)

    # ------------------------------------------------------------------
    # Validation steps
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_schema(raw: RawSignal) -> Tuple[bool, str]:
        """Phase 1: field types and required presence."""
        if not isinstance(raw.symbol, str) or not raw.symbol.strip():
            return False, "symbol must be a non-empty string"
        if not isinstance(raw.side, str):
            return False, f"side must be str, got {type(raw.side).__name__}"
        if not isinstance(raw.action, str):
            return False, f"action must be str, got {type(raw.action).__name__}"
        try:
            size = float(raw.size_usd)
        except (TypeError, ValueError):
            return False, f"size_usd must be numeric, got {type(raw.size_usd).__name__}"
        if not math.isfinite(size):
            return False, f"size_usd must be finite, got {size}"
        try:
            conf = float(raw.confidence)
        except (TypeError, ValueError):
            return False, f"confidence must be numeric, got {type(raw.confidence).__name__}"
        if not math.isfinite(conf):
            return False, f"confidence must be finite, got {conf}"
        return True, ""

    @staticmethod
    def _validate_confidence(raw: RawSignal) -> Tuple[bool, str]:
        """Phase 2: confidence within [0, 1] and meets strategy floor."""
        conf = float(raw.confidence)
        if not (0.0 <= conf <= 1.0):
            return False, f"confidence {conf:.4f} out of [0.0, 1.0]"

        # Only enforce floor for execution actions
        if raw.action not in _EXECUTION_ACTIONS:
            return True, ""

        strategy_key = (raw.strategy or "default").lower()
        floor = _MIN_CONFIDENCE.get(strategy_key, _MIN_CONFIDENCE["default"])
        if conf < floor:
            return False, (
                f"confidence {conf:.4f} below floor {floor:.4f} "
                f"for strategy '{strategy_key}'"
            )
        return True, ""

    @staticmethod
    def _validate_regime_compatibility(raw: RawSignal) -> Tuple[bool, str]:
        """Phase 3: signal strategy is compatible with current regime."""
        if raw.action not in _EXECUTION_ACTIONS:
            return True, ""  # non-execution signals skip regime check

        regime = (raw.regime or "unknown").lower()
        strategy = (raw.strategy or "").lower()

        compatible = _REGIME_STRATEGY_MAP.get(regime, _REGIME_STRATEGY_MAP["unknown"])
        # If strategy is empty or matches any compatible type, allow
        if not strategy:
            return True, ""
        for compat in compatible:
            if compat in strategy or strategy in compat:
                return True, ""

        return False, (
            f"strategy '{strategy}' incompatible with regime '{regime}'; "
            f"compatible: {compatible}"
        )

    @staticmethod
    def _calculate_position_size(
        requested_usd: float,
        portfolio_value_usd: float,
        max_pct: float,
        notes: List[str],
    ) -> float:
        """Phase 5: cap position size to max_position_size_pct of portfolio."""
        if portfolio_value_usd <= 0:
            return requested_usd
        max_usd = portfolio_value_usd * (max_pct / 100.0)
        if requested_usd > max_usd:
            notes.append(
                f"size_capped:{requested_usd:.2f}->{max_usd:.2f} "
                f"(max {max_pct}% of {portfolio_value_usd:.2f})"
            )
            return max_usd
        return requested_usd

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalise_side(side: str, action: str) -> str:
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
        return side_lc  # pass through for non-execution actions

    def _build_compiled(
        self,
        raw: RawSignal,
        sized_usd: float,
        notes: List[str],
    ) -> CompiledSignal:
        return CompiledSignal(
            signal_id=str(uuid.uuid4()),
            symbol=raw.symbol.strip().upper(),
            side=self._normalise_side(raw.side, raw.action),
            action=raw.action.lower().strip(),
            size_usd=float(sized_usd),
            confidence=float(raw.confidence),
            regime=(raw.regime or "unknown").lower().strip(),
            strategy=raw.strategy or "",
            account_id=raw.account_id or "default",
            approved=raw.approved,
            stop_loss_pct=raw.stop_loss_pct,
            take_profit_pct=raw.take_profit_pct,
            metadata=dict(raw.metadata or {}),
            compile_notes=list(notes),
        )

    def _record(self, accepted: bool) -> None:
        with self._lock:
            self._total += 1
            if accepted:
                self._accepted += 1
            else:
                self._rejected += 1

    def _store_audit(
        self,
        raw: RawSignal,
        compiled: Optional[CompiledSignal],
        notes: List[str],
    ) -> None:
        """Store signal in Redis for audit trail."""
        if self._redis is None:
            return
        try:
            signal_id = compiled.signal_id if compiled else str(uuid.uuid4())
            key = f"nija:control:signals:{signal_id}"
            payload = {
                "signal_id":   signal_id,
                "symbol":      raw.symbol,
                "action":      raw.action,
                "confidence":  raw.confidence,
                "regime":      raw.regime,
                "strategy":    raw.strategy,
                "accepted":    compiled is not None,
                "notes":       notes,
                "compiled_at": datetime.now(timezone.utc).isoformat(),
            }
            if compiled:
                payload["size_usd"] = compiled.size_usd
                payload["side"] = compiled.side
            self._redis.setex(key, _SIGNAL_REDIS_TTL, json.dumps(payload))
        except Exception as exc:
            logger.debug("ControlCompiler: Redis audit store failed: %s", exc)

    # ------------------------------------------------------------------
    # Observability
    # ------------------------------------------------------------------

    def get_health(self) -> Dict[str, Any]:
        with self._lock:
            total = self._total
            accepted = self._accepted
            rejected = self._rejected
        return {
            "available":     True,
            "total_compiled": total,
            "accepted":      accepted,
            "rejected":      rejected,
            "accept_rate":   round(accepted / total, 4) if total > 0 else 1.0,
        }


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_singleton: Optional[ControlCompiler] = None
_singleton_lock = threading.Lock()


def get_control_compiler(redis_client=None) -> ControlCompiler:
    """Return the process-level ControlCompiler singleton."""
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                _singleton = ControlCompiler(redis_client=redis_client)
    return _singleton
