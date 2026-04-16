"""
NIJA Trade Permission Engine
============================

Single-source, authoritative execution decision layer.

Every trade candidate is funnelled through one decision tree.  The engine
replaces the ad-hoc gate/filter calls that are currently scattered across
nija_core_loop Phase 3, ai_entry_gate, liquidity_risk_gate, and the streak
bypass helpers.

Decision tree (evaluated in strict order)
-----------------------------------------
::

    Layer 1 — Signal
        Is the AI composite score ≥ effective floor?
        Bypass: streak logic (dead-zone / hard-bypass / force / volume-fallback).

    Layer 2 — Regime
        Is the current market regime permitting this entry type / side?
        Bypass: same streak conditions as Layer 1.

    Layer 3 — Capital           (hard block — no bypass)
        Is the account balance ≥ the minimum tradeable threshold?

    Layer 4 — Liquidity         (hard block — no bypass)
        Is the bid-ask spread + slippage cost within the broker ceiling?

    Layer 5 — Execution mode
        Classify the entry mode based on active bypass flags.

    Final verdict: EXECUTE | BLOCKED

DECISION TRACE output (emitted every evaluation at INFO level)
--------------------------------------------------------------
::

    DECISION TRACE [BTC-USD long]:
      signal         : YES  (score=42.5 ≥ 14.0)
      regime         : UNFAVORABLE  (bypassed via streak logic)
      capital        : PASS  ($23.47 ≥ $18.00 threshold)
      liquidity      : PASS  (spread 0.08% + slippage 0.10% = 0.18% ≤ 1.00%)
      execution mode : NORMAL
      ──────────────────────────────────────────────────
      final decision : EXECUTE

    DECISION TRACE [ETH-USD long]:
      signal         : YES  (score=42.5 ≥ 14.0)
      regime         : UNFAVORABLE  (bypassed via streak logic)
      capital        : PASS  ($18.03 ≥ $18.00 threshold)
      liquidity      : FAIL  (spread too high)
      execution mode : HARD_BYPASS
      ──────────────────────────────────────────────────
      final decision : BLOCKED
      reason         : liquidity filter (spread too high)

Integration
-----------
::

    from bot.trade_permission_engine import get_trade_permission_engine

    engine = get_trade_permission_engine()

    decision = engine.evaluate(
        symbol="BTC-USD",
        side="long",
        ai_score=42.5,
        ai_threshold=14.0,
        balance=23.47,
        regime=current_regime,
        zero_signal_streak=3,
        df=df,
        entry_type="swing",
        broker="coinbase",
        force_next_cycle=False,
        dead_zone=False,
        hard_bypass=False,
        volume_fallback=False,
        metadata=sig.metadata,
    )

    if decision.final_decision != "EXECUTE":
        blocked += 1
        continue

Author: NIJA Trading Systems
Version: 1.0
Date: April 2026
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import pandas as pd

logger = logging.getLogger("nija.trade_permission")

# ---------------------------------------------------------------------------
# Configuration — overridable via environment variables
# ---------------------------------------------------------------------------

# Minimum account balance required to open a new position (hard block).
# The $18 default covers the Coinbase $10 order minimum plus a fee buffer.
_DEFAULT_CAPITAL_THRESHOLD: float = float(
    os.environ.get("NIJA_MIN_TRADE_CAPITAL", "18.0")
)

# ---------------------------------------------------------------------------
# Execution mode labels
# ---------------------------------------------------------------------------
MODE_NORMAL = "NORMAL"
MODE_MOMENTUM_ONLY = "MOMENTUM_ONLY"
MODE_PROGRESSIVE_RELAX = "PROGRESSIVE_RELAX"
MODE_HARD_BYPASS = "HARD_BYPASS"
MODE_DEAD_ZONE = "DEAD_ZONE"
MODE_FORCED = "FORCED"
MODE_VOLUME_FALLBACK = "VOLUME_FALLBACK"


# ---------------------------------------------------------------------------
# Decision record
# ---------------------------------------------------------------------------

@dataclass
class TradeDecision:
    """Full decision record for one candidate entry.

    Every field is populated by :meth:`TradePermissionEngine.evaluate`.
    Callers should inspect ``final_decision`` ("EXECUTE" or "BLOCKED") and
    ``block_reason`` to act on the result.  The full record is available for
    audit logging, dashboards, or downstream consumers.
    """

    # ── Context ─────────────────────────────────────────────────────────────
    symbol: str
    side: str

    # ── Layer 1: Signal ──────────────────────────────────────────────────────
    signal: str               # "YES" | "NO"
    signal_score: float
    signal_threshold: float
    signal_bypass: bool       # True → streak / force bypassed the score floor

    # ── Layer 2: Regime ──────────────────────────────────────────────────────
    regime_label: str         # normalised regime name (upper-case)
    regime_pass: bool         # True if regime natively permits this entry
    regime_bypass: bool       # True → streak bypassed the regime block

    # ── Layer 3: Capital ─────────────────────────────────────────────────────
    capital: str              # "PASS" | "FAIL"
    capital_balance: float
    capital_threshold: float

    # ── Layer 4: Liquidity ────────────────────────────────────────────────────
    liquidity: str            # "PASS" | "FAIL"
    liquidity_detail: str

    # ── Layer 5: Execution mode ──────────────────────────────────────────────
    execution_mode: str       # one of the MODE_* constants

    # ── Final verdict ────────────────────────────────────────────────────────
    final_decision: str       # "EXECUTE" | "BLOCKED"
    block_reason: str         # human-readable reason; empty when EXECUTE

    # ── Layer 6: Broker Criticality ──────────────────────────────────────────
    # Minimum viable execution set: ≥1 CRITICAL broker connected.
    # OPTIONAL broker (OKX, Binance, Alpaca) failure → always pass.
    # CRITICAL broker (Kraken, Coinbase) dead → block BUY only.
    broker: str = ""
    broker_criticality: str = "UNKNOWN"   # "CRITICAL" | "OPTIONAL" | "UNKNOWN"
    broker_health: str = "UNKNOWN"        # "HEALTHY" | "DEAD" | "UNKNOWN"

    # ── Extended decision context ─────────────────────────────────────────────
    risk_allowed: bool = True             # False when risk engine blocks the trade
    capital_allocated: float = 0.0       # Dollar amount allocated to this trade
    market_regime: str = ""              # Normalised regime label (mirrors regime_label)
    strategy_name: str = ""              # Strategy that generated the signal

    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Return the decision as a plain dictionary (e.g. for JSON logging)."""
        return {
            "symbol": self.symbol,
            "side": self.side,
            "signal": self.signal,
            "signal_score": self.signal_score,
            "signal_threshold": self.signal_threshold,
            "signal_bypass": self.signal_bypass,
            "regime": self.regime_label,
            "regime_pass": self.regime_pass,
            "regime_bypass": self.regime_bypass,
            "capital": self.capital,
            "capital_balance": self.capital_balance,
            "capital_threshold": self.capital_threshold,
            "liquidity": self.liquidity,
            "liquidity_detail": self.liquidity_detail,
            "execution_mode": self.execution_mode,
            "broker": self.broker,
            "broker_criticality": self.broker_criticality,
            "broker_health": self.broker_health,
            "final_decision": self.final_decision,
            "block_reason": self.block_reason,
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class TradePermissionEngine:
    """Collapse all gate/filter layers into one authoritative decision tree.

    A single instance may be shared safely across threads — internal state
    (stats counters) is protected by a lock.  All evaluation logic is
    stateless with respect to individual decisions.
    """

    def __init__(self, capital_threshold: float = _DEFAULT_CAPITAL_THRESHOLD) -> None:
        self._capital_threshold = capital_threshold
        self._lock = threading.Lock()
        self._eval_count = 0
        self._execute_count = 0
        self._blocked_count = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(
        self,
        *,
        symbol: str,
        side: str,
        ai_score: float,
        ai_threshold: float,
        balance: float,
        regime: Any,
        zero_signal_streak: int,
        df: Optional[pd.DataFrame] = None,
        entry_type: str = "swing",
        broker: str = "coinbase",
        force_next_cycle: bool = False,
        dead_zone: bool = False,
        hard_bypass: bool = False,
        volume_fallback: bool = False,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> TradeDecision:
        """Run all permission layers for a single candidate entry.

        Parameters
        ----------
        symbol:
            Ticker symbol (e.g. ``"BTC-USD"``).
        side:
            ``"long"`` or ``"short"``.
        ai_score:
            Composite AI score from :class:`NijaAIEngine`.
        ai_threshold:
            Effective score floor for this cycle (may be relaxed by streak
            logic before being passed in).
        balance:
            Current account balance in USD.
        regime:
            Current market regime object (or string label).
        zero_signal_streak:
            Consecutive cycles with no qualifying signal.
        df:
            OHLCV DataFrame — used for the spread / liquidity check.
            Pass ``None`` to skip spread verification (gate fails open).
        entry_type:
            Entry style label (``"swing"`` / ``"momentum"`` / etc.).
        broker:
            Broker name — ``"coinbase"`` or ``"kraken"``.
        force_next_cycle:
            ``True`` when the global ``FORCE_NEXT_CYCLE`` flag is active.
        dead_zone:
            ``True`` when ``zero_signal_streak ≥ DEAD_ZONE_STREAK_THRESHOLD``.
        hard_bypass:
            ``True`` when ``zero_signal_streak ≥ HARD_BYPASS_STREAK_THRESHOLD``.
        volume_fallback:
            ``True`` when the candidate was injected as a volume-fallback.
        metadata:
            Extra metadata dict from the ``AIEngineSignal`` (may contain
            bypass flags set by progressive-relaxation logic).

        Returns
        -------
        TradeDecision
            Full trace of the decision.  The DECISION TRACE is emitted to
            the ``nija.trade_permission`` logger at INFO level.
        """
        md: Dict[str, Any] = metadata or {}

        # ── Derive active bypass flags from all sources ──────────────────────
        # A bypass is active when any of the streak / force conditions are set,
        # OR when the AIEngineSignal itself carries a bypass flag from the
        # progressive-relaxation logic in _phase3_scan_and_enter.
        _md_bypass = bool(
            md.get("bypass_quality_filter")
            or md.get("bypass_low_quality")
        )
        bypass_active = (
            force_next_cycle
            or hard_bypass
            or volume_fallback
            or dead_zone
            or _md_bypass
        )

        # ── Layer 1: Signal ──────────────────────────────────────────────────
        signal_ok = (ai_score >= ai_threshold) or bypass_active
        signal_label = "YES" if signal_ok else "NO"

        # ── Layer 2: Regime ──────────────────────────────────────────────────
        regime_label, regime_native_pass = self._check_regime(
            regime, side, entry_type, broker
        )
        # Regime bypass uses identical conditions as the signal bypass so that
        # the streak / force mechanism unlocks both layers together.
        regime_bypass = bypass_active
        regime_ok = regime_native_pass or regime_bypass

        # ── Layer 3: Capital (hard block) ────────────────────────────────────
        capital_ok = balance >= self._capital_threshold
        capital_label = "PASS" if capital_ok else "FAIL"

        # ── Layer 4: Liquidity / spread (hard block) ─────────────────────────
        liquidity_ok, liquidity_detail = self._check_spread(df, broker)
        liquidity_label = "PASS" if liquidity_ok else "FAIL"

        # ── Layer 5: Execution mode ──────────────────────────────────────────
        execution_mode = self._classify_mode(
            force_next_cycle=force_next_cycle,
            hard_bypass=hard_bypass,
            dead_zone=dead_zone,
            volume_fallback=volume_fallback,
            md=md,
        )

        # ── Layer 6: Broker Criticality (hard block — BUY only) ──────────────
        # Minimum viable execution set: at least 1 CRITICAL broker connected.
        # OPTIONAL broker (OKX, Binance, Alpaca) failure → always pass.
        # CRITICAL broker (Kraken, Coinbase) dead → block BUY until recovery.
        # SELL / exit orders always pass so positions can always be closed.
        broker_crit_label, broker_health_ok, broker_health_detail = (
            self._check_broker_criticality(broker, side)
        )
        broker_health_label = "HEALTHY" if broker_health_ok else "DEAD"

        # ── Final verdict ────────────────────────────────────────────────────
        # Layers 1 & 2 can be bypassed by streak / force logic.
        # Layers 3, 4, 6 are absolute hard blocks — no bypass is permitted.
        if not signal_ok:
            final = "BLOCKED"
            block_reason = (
                f"signal below floor "
                f"(score={ai_score:.1f} < threshold={ai_threshold:.1f})"
            )
        elif not regime_ok:
            final = "BLOCKED"
            block_reason = f"regime filter ({regime_label})"
        elif not capital_ok:
            final = "BLOCKED"
            block_reason = (
                f"capital below threshold "
                f"(${balance:.2f} < ${self._capital_threshold:.2f})"
            )
        elif not liquidity_ok:
            final = "BLOCKED"
            block_reason = f"liquidity filter ({liquidity_detail})"
        elif not broker_health_ok:
            final = "BLOCKED"
            block_reason = f"broker criticality gate ({broker_health_detail})"
        else:
            final = "EXECUTE"
            block_reason = ""

        decision = TradeDecision(
            symbol=symbol,
            side=side,
            signal=signal_label,
            signal_score=ai_score,
            signal_threshold=ai_threshold,
            signal_bypass=bypass_active,
            regime_label=regime_label,
            regime_pass=regime_native_pass,
            regime_bypass=regime_bypass,
            capital=capital_label,
            capital_balance=balance,
            capital_threshold=self._capital_threshold,
            liquidity=liquidity_label,
            liquidity_detail=liquidity_detail,
            execution_mode=execution_mode,
            broker=broker,
            broker_criticality=broker_crit_label,
            broker_health=broker_health_label,
            final_decision=final,
            block_reason=block_reason,
            market_regime=regime_label,
        )

        self._emit_trace(decision)
        self._record_stat(final)
        return decision

    def set_capital_threshold(self, value: float) -> None:
        """Update the capital minimum at runtime (e.g. when balance grows)."""
        self._capital_threshold = value
        logger.info(
            "TradePermissionEngine: capital threshold updated → $%.2f", value
        )

    def get_stats(self) -> Dict[str, Any]:
        """Return cumulative decision statistics."""
        with self._lock:
            total = self._eval_count
            return {
                "evaluations": total,
                "execute": self._execute_count,
                "blocked": self._blocked_count,
                "execute_rate": (
                    self._execute_count / total if total > 0 else 0.0
                ),
            }

    # ------------------------------------------------------------------
    # Layer checks
    # ------------------------------------------------------------------

    @staticmethod
    def _check_regime(
        regime: Any,
        side: str,
        entry_type: str,
        broker: str,
    ) -> tuple[str, bool]:
        """Return (label, natively_passes) for the current regime.

        Attempts to delegate to :class:`AIEntryGate` for consistent logic.
        Falls back to a small hard-coded block-list when the gate is
        unavailable.
        """
        if regime is None:
            return "UNKNOWN", True  # permissive when no regime data

        # Normalise to a lower-case string key (matches AIEntryGate convention)
        try:
            from bot.ai_entry_gate import AIEntryGate
            regime_key = AIEntryGate._regime_key(regime)
            gc = AIEntryGate._gate_regime(regime_key, entry_type, side)
            return regime_key.upper(), gc.passed
        except Exception:
            pass

        # Fallback: derive label and apply a minimal block-list
        if hasattr(regime, "value"):
            label = str(regime.value).upper()
        elif hasattr(regime, "name"):
            label = str(regime.name).upper()
        else:
            label = str(regime).upper()

        _HARD_BLOCK_REGIMES = {
            "CRASH", "EXTREME_VOLATILITY", "VOLATILITY_EXPLOSION", "BEAR_EXTREME"
        }
        return label, label not in _HARD_BLOCK_REGIMES

    @staticmethod
    def _check_spread(
        df: Optional[pd.DataFrame],
        broker: str,
    ) -> tuple[bool, str]:
        """Return (passes, detail_string) for the spread / liquidity check.

        Delegates to :class:`AIEntryGate._gate_spread` so the broker-specific
        spread ceiling configuration is respected.  Falls back to a direct
        bid/ask calculation when the gate module is unavailable, and fails
        open when no price data exists at all.
        """
        if df is None or len(df) < 2:
            return True, "no data (skipped)"

        try:
            from bot.ai_entry_gate import AIEntryGate
            broker_key = AIEntryGate._broker_key(broker)
            gc = AIEntryGate._gate_spread(df, broker_key)
            return gc.passed, gc.detail
        except Exception:
            pass

        # Secondary attempt with plain module path (e.g. inside bot/ package)
        try:
            from ai_entry_gate import AIEntryGate  # type: ignore
            broker_key = AIEntryGate._broker_key(broker)
            gc = AIEntryGate._gate_spread(df, broker_key)
            return gc.passed, gc.detail
        except Exception:
            pass

        # Pure-pandas fallback — compute spread from bid/ask columns or
        # fall back to a conservative fixed estimate.
        # Hard-block threshold: 5 % total cost (very wide markets).
        _SPREAD_HARD_BLOCK_PCT = 5.0
        try:
            if "bid" in df.columns and "ask" in df.columns:
                bid = float(df["bid"].iloc[-1])
                ask = float(df["ask"].iloc[-1])
                mid = (bid + ask) / 2.0
                spread_pct = ((ask - bid) / mid * 100.0) if mid > 0 else 0.0
            else:
                # No bid/ask — use the conservative fixed estimate from AIEntryGate
                spread_pct = 0.10  # 0.10% when no bid/ask data
            slippage_pct = 0.10   # standard slippage estimate
            total_cost = spread_pct + slippage_pct
            passed = total_cost <= _SPREAD_HARD_BLOCK_PCT
            detail = (
                f"spread {spread_pct:.3f}% + slippage {slippage_pct:.2f}% "
                f"= {total_cost:.3f}% "
                f"({'≤' if passed else '>'} {_SPREAD_HARD_BLOCK_PCT:.2f}% ceiling)"
            )
            return passed, detail
        except Exception as exc:
            logger.debug("TradePermissionEngine spread fallback error: %s", exc)
            return True, "spread check unavailable (skipped)"

    @staticmethod
    def _classify_mode(
        *,
        force_next_cycle: bool,
        hard_bypass: bool,
        dead_zone: bool,
        volume_fallback: bool,
        md: Dict[str, Any],
    ) -> str:
        """Classify the execution mode from the active bypass state."""
        if force_next_cycle:
            return MODE_FORCED
        if volume_fallback or md.get("volume_fallback"):
            return MODE_VOLUME_FALLBACK
        if hard_bypass or md.get("bypass_quality_filter"):
            return MODE_HARD_BYPASS
        if dead_zone or md.get("dead_zone"):
            # Distinguish momentum-only sub-mode (candidates come from the
            # relaxed momentum scanner, not the full AI scoring pipeline).
            if md.get("bypass_low_quality") and not hard_bypass:
                return MODE_MOMENTUM_ONLY
            return MODE_DEAD_ZONE
        if md.get("relaxation_factor") or md.get("relaxation_step"):
            return MODE_PROGRESSIVE_RELAX
        return MODE_NORMAL

    # ------------------------------------------------------------------
    # Layer checks
    # ------------------------------------------------------------------

    @staticmethod
    def _check_broker_criticality(
        broker: str,
        side: str,
    ) -> "tuple[str, bool, str]":
        """Return ``(criticality_label, health_passes, detail)`` for *broker*.

        Layer 6 rules (strictly enforced):
        * SELL / exit orders always pass — positions must be closeable.
        * OPTIONAL brokers (OKX, Binance, Alpaca) always pass — non-blocking.
        * CRITICAL brokers (Kraken, Coinbase) block BUY when dead.
        * Any import / runtime error → fail open (skip check).
        """
        if side.lower() not in ("long", "buy"):
            return "N/A", True, "sell/exit — criticality not checked"

        try:
            from bot.broker_registry import get_broker_criticality, BrokerCriticality
        except ImportError:
            try:
                from broker_registry import get_broker_criticality, BrokerCriticality  # type: ignore
            except ImportError:
                return "UNKNOWN", True, "broker_registry unavailable (skipped)"

        crit = get_broker_criticality(broker)
        crit_label = crit.value if hasattr(crit, "value") else str(crit)

        if crit != BrokerCriticality.CRITICAL:
            return crit_label, True, f"{broker} is OPTIONAL — non-blocking"

        # CRITICAL broker: verify liveness via BrokerFailureManager.
        try:
            from bot.broker_failure_manager import get_broker_failure_manager
        except ImportError:
            try:
                from broker_failure_manager import get_broker_failure_manager  # type: ignore
            except ImportError:
                return crit_label, True, "BrokerFailureManager unavailable (skipped)"

        try:
            bfm = get_broker_failure_manager()
            if bfm.is_dead(broker.lower()):
                delay = bfm.get_retry_delay(broker.lower())
                return (
                    crit_label,
                    False,
                    f"CRITICAL broker '{broker}' is dead (retry in {delay:.0f}s)",
                )
            return crit_label, True, f"CRITICAL broker '{broker}' is healthy"
        except Exception as exc:
            return crit_label, True, f"broker health check error: {exc} (skipped)"

    # ------------------------------------------------------------------
    # Trace emission
    # ------------------------------------------------------------------

    @staticmethod
    def _emit_trace(d: TradeDecision) -> None:
        """Write the structured DECISION TRACE to the logger."""

        # ── Signal line ──────────────────────────────────────────────────────
        if d.signal_bypass:
            signal_line = (
                f"{d.signal}  "
                f"(score={d.signal_score:.1f}, bypassed via streak logic)"
            )
        else:
            cmp = "≥" if d.signal == "YES" else "<"
            signal_line = (
                f"{d.signal}  "
                f"(score={d.signal_score:.1f} {cmp} {d.signal_threshold:.1f})"
            )

        # ── Regime line ──────────────────────────────────────────────────────
        if d.regime_bypass and not d.regime_pass:
            regime_line = f"{d.regime_label}  (bypassed via streak logic)"
        elif d.regime_pass:
            regime_line = f"{d.regime_label}  (favorable)"
        else:
            regime_line = f"{d.regime_label}  (unfavorable)"

        # ── Capital line ─────────────────────────────────────────────────────
        if d.capital == "PASS":
            capital_line = (
                f"PASS  "
                f"(${d.capital_balance:.2f} ≥ ${d.capital_threshold:.2f} threshold)"
            )
        else:
            capital_line = (
                f"FAIL  "
                f"(${d.capital_balance:.2f} < ${d.capital_threshold:.2f} threshold)"
            )

        # ── Broker criticality line ──────────────────────────────────────────
        if d.broker_criticality == "N/A":
            broker_crit_line = "N/A  (sell/exit — not checked)"
        elif d.broker_health == "DEAD":
            broker_crit_line = (
                f"BLOCKED  ({d.broker} is DEAD — CRITICAL broker cannot trade)"
            )
        elif d.broker_criticality in ("OPTIONAL", "UNKNOWN"):
            broker_crit_line = f"{d.broker_criticality}  ({d.broker} — non-blocking)"
        else:
            broker_crit_line = f"{d.broker_criticality}  ({d.broker} healthy)"

        # ── Final decision lines ─────────────────────────────────────────────
        if d.final_decision == "EXECUTE":
            verdict = "  final decision : EXECUTE"
        else:
            verdict = (
                f"  final decision : BLOCKED\n"
                f"  reason         : {d.block_reason}"
            )

        trace = (
            f"\nDECISION TRACE [{d.symbol} {d.side}]:\n"
            f"  signal         : {signal_line}\n"
            f"  regime         : {regime_line}\n"
            f"  capital        : {capital_line}\n"
            f"  liquidity      : {d.liquidity}  ({d.liquidity_detail})\n"
            f"  execution mode : {d.execution_mode}\n"
            f"  broker crit    : {broker_crit_line}\n"
            f"  {'─' * 50}\n"
            f"{verdict}"
        )
        logger.warning(f"""
🚨 TRADE DECISION
symbol={d.symbol}
signal={d.signal}
score={d.signal_score}

final_decision={d.final_decision}
passed_gate={d.final_decision == "EXECUTE"}

reason_blocked={d.block_reason}

risk_allowed={d.risk_allowed}
capital_allocated={d.capital_allocated}
broker_selected={d.broker}

regime={d.market_regime}
strategy={d.strategy_name}
""")

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def _record_stat(self, final: str) -> None:
        with self._lock:
            self._eval_count += 1
            if final == "EXECUTE":
                self._execute_count += 1
            else:
                self._blocked_count += 1


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_engine_instance: Optional[TradePermissionEngine] = None
_engine_lock = threading.Lock()


def get_trade_permission_engine(
    capital_threshold: float = _DEFAULT_CAPITAL_THRESHOLD,
) -> TradePermissionEngine:
    """Return (and lazily create) the module-level singleton engine.

    Parameters are applied only on first creation; subsequent calls return the
    existing instance unchanged.
    """
    global _engine_instance
    if _engine_instance is None:
        with _engine_lock:
            if _engine_instance is None:
                _engine_instance = TradePermissionEngine(
                    capital_threshold=capital_threshold,
                )
                logger.info(
                    "TradePermissionEngine created "
                    "(capital_threshold=$%.2f)",
                    capital_threshold,
                )
    return _engine_instance
