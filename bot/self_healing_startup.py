"""
NIJA Self-Healing Startup Sequence
====================================

Resilient connection-layer boot sequence that automatically:

1. **Detects nonce poisoning**          — inspects persisted nonce lead, nuclear-reset
                                          history, and duplicate-process state
2. **Auto-escalates ceiling jumps**     — standard probe → deep-probe → ceiling jump
                                          → emergency alert (new API key required)
3. **Falls back to secondary broker**   — if Kraken fails after all escalations,
                                          switches to Coinbase automatically and alerts
4. **Alerts before trading halts**      — fires CRITICAL alerts with a configurable
                                          countdown before halting so the operator has
                                          time to intervene

Architecture
------------
SelfHealingStartup          ← top-level orchestrator; call .run()
  ├── NoncePoisonDetector    ← reads nonce state, returns severity + recommended action
  ├── CeilingJumpEscalator   ← drives probe → deep-probe → ceiling jump → emergency
  ├── BrokerFallbackController← Kraken first; Coinbase on failure; alerts on switch
  └── PreHaltAlertEngine     ← watchdog thread; fires CRITICAL before halting

Quick start
-----------
::

    from bot.self_healing_startup import SelfHealingStartup, StartupConfig

    cfg    = StartupConfig()
    result = SelfHealingStartup(cfg).run()

    if not result.ok:
        logger.critical("Bot startup failed: %s", result.reason)
        raise SystemExit(1)

    active_broker      = result.broker
    active_broker_name = result.broker_name
    if result.on_fallback:
        logger.warning("Running on FALLBACK broker (%s)", active_broker_name)

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
from enum import Enum
from typing import Any, Callable, Optional

logger = logging.getLogger("nija.self_healing_startup")

# ---------------------------------------------------------------------------
# Optional dependency imports (everything is graceful-fallback)
# ---------------------------------------------------------------------------

try:
    from global_kraken_nonce import (
        get_global_nonce_manager,
        get_global_nonce_stats,
        KrakenNonceManager,
        _PROBE_SYSTEM_ENABLED as _NONCE_PROBE_SYSTEM_ENABLED,  # noqa: PLC2701
    )
    _NONCE_MGR_AVAILABLE = True
except ImportError:
    _NONCE_MGR_AVAILABLE = False
    get_global_nonce_manager = None  # type: ignore[assignment]
    get_global_nonce_stats   = None  # type: ignore[assignment]
    KrakenNonceManager       = None  # type: ignore[assignment]
    _NONCE_PROBE_SYSTEM_ENABLED = False
    logger.warning("⚠️  global_kraken_nonce not importable — nonce checks skipped")

try:
    from alert_manager import get_alert_manager, AlertSeverity, AlertCategory
    _ALERT_MGR_AVAILABLE = True
except ImportError:
    _ALERT_MGR_AVAILABLE = False
    get_alert_manager = None  # type: ignore[assignment]
    AlertSeverity     = None  # type: ignore[assignment]
    AlertCategory     = None  # type: ignore[assignment]
    logger.debug("alert_manager not importable — console-only alerts")

try:
    from text_alert_system import get_text_alert_system
    _TEXT_ALERT_AVAILABLE = True
except ImportError:
    _TEXT_ALERT_AVAILABLE = False
    get_text_alert_system = None  # type: ignore[assignment]

try:
    from trading_state_machine import get_state_machine, TradingState
    _STATE_MACHINE_AVAILABLE = True
except ImportError:
    _STATE_MACHINE_AVAILABLE = False
    get_state_machine = None  # type: ignore[assignment]
    TradingState      = None  # type: ignore[assignment]
    logger.warning("⚠️  trading_state_machine not importable — state-machine checks skipped")

try:
    from startup_readiness_gate import get_startup_readiness_gate
    _READINESS_GATE_AVAILABLE = True
except ImportError:
    _READINESS_GATE_AVAILABLE = False
    get_startup_readiness_gate = None  # type: ignore[assignment]

try:
    from capital_authority import get_capital_authority as _get_capital_authority
    _CA_AVAILABLE = True
except ImportError:
    try:
        from bot.capital_authority import get_capital_authority as _get_capital_authority  # type: ignore[import]
        _CA_AVAILABLE = True
    except ImportError:
        _get_capital_authority = None  # type: ignore[assignment]
        _CA_AVAILABLE = False

try:
    from broker_manager import (
        KrakenBroker,
        CoinbaseBroker,
        BrokerType,
        AccountType,
        BaseBroker,
        get_platform_broker,
    )
    _BROKER_AVAILABLE = True
except ImportError:
    _BROKER_AVAILABLE = False
    KrakenBroker      = None  # type: ignore[assignment]
    CoinbaseBroker    = None  # type: ignore[assignment]
    BrokerType        = None  # type: ignore[assignment]
    AccountType       = None  # type: ignore[assignment]
    BaseBroker        = None  # type: ignore[assignment]
    get_platform_broker = None  # type: ignore[assignment]
    logger.warning("⚠️  broker_manager not importable — broker failover skipped")

# Import MABM for delegated initialization (Step 3 — consumer pattern)
try:
    from multi_account_broker_manager import multi_account_broker_manager as _mabm
    _MABM_AVAILABLE = True
except ImportError:
    try:
        from bot.multi_account_broker_manager import multi_account_broker_manager as _mabm
        _MABM_AVAILABLE = True
    except ImportError:
        _mabm = None  # type: ignore[assignment]
        _MABM_AVAILABLE = False

# Import broker criticality registry for role annotation in fallback paths
try:
    try:
        from bot.broker_registry import broker_registry as _broker_registry, BrokerCriticality as _BC
    except ImportError:
        from broker_registry import broker_registry as _broker_registry, BrokerCriticality as _BC  # type: ignore[import]
    _BROKER_REGISTRY_AVAILABLE = True
except Exception:
    _broker_registry = None  # type: ignore[assignment]
    _BC = None  # type: ignore[assignment]
    _BROKER_REGISTRY_AVAILABLE = False


# Poll interval (seconds) used by the post-connection CA readiness loop.
# Intentionally faster than the watchdog_interval_s (default 60 s) so startup
# converges quickly; the background watchdog takes over once the loop exits.
_CA_POLL_INTERVAL_S: float = 3.0

# Maximum number of state-machine step attempts in the post-preflight transition
# guarantee loop (FIX 1).  Three attempts cover the common EMERGENCY_STOP → OFF →
# LIVE_ACTIVE two-step transition while keeping the hot path cheap.
_MAX_STATE_TRANSITION_ATTEMPTS: int = 3

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class StartupConfig:
    """Tunable parameters for the self-healing startup sequence."""

    # ── Nonce-poison thresholds ────────────────────────────────────────────
    # Nonce lead (ms ahead of wall clock) above which we consider it potentially
    # poisoned and start escalation.
    nonce_warn_lead_ms: int  = int(os.environ.get("NIJA_SHS_NONCE_WARN_MS",   "600000"))    # 10 min
    nonce_probe_lead_ms: int = int(os.environ.get("NIJA_SHS_NONCE_PROBE_MS",  "1800000"))   # 30 min
    nonce_deep_lead_ms: int  = int(os.environ.get("NIJA_SHS_NONCE_DEEP_MS",   "3600000"))   # 60 min
    nonce_ceiling_lead_ms: int = int(os.environ.get("NIJA_SHS_NONCE_CEIL_MS", "7200000"))   # 2 h

    # ── Escalation settings ────────────────────────────────────────────────
    # Whether to actually attempt each escalation tier (set False to disable)
    escalation_standard_probe: bool  = True
    escalation_deep_probe: bool      = True
    escalation_ceiling_jump: bool    = True

    # Maximum probe attempts for each tier (0 = use module defaults)
    standard_probe_max_attempts: int = 0
    deep_probe_max_attempts: int     = 0

    # Ceiling jump size (ms) — defaults to 24 h
    ceiling_jump_ms: int = int(os.environ.get("NIJA_NONCE_CEILING_JUMP_MS", "86400000"))

    # ── Broker failover ────────────────────────────────────────────────────
    # Maximum Kraken connection attempts before declaring primary failed
    primary_max_attempts: int  = int(os.environ.get("NIJA_SHS_PRIMARY_ATTEMPTS", "3"))
    fallback_enabled: bool     = True

    # ── Pre-halt alerting ──────────────────────────────────────────────────
    # How many seconds before a trading halt to fire the pre-halt warning
    pre_halt_warn_s: float    = float(os.environ.get("NIJA_SHS_PREHALT_WARN_S", "300"))
    # Watchdog: poll broker health every N seconds (also used for CA-readiness
    # watchdog — separate from the 3-second post-connection polling loop which
    # is intentionally faster for startup convergence)
    watchdog_interval_s: float = float(os.environ.get("NIJA_SHS_WATCHDOG_S", "60"))
    # How many consecutive watchdog failures before triggering a halt warning
    watchdog_max_failures: int = int(os.environ.get("NIJA_SHS_WATCHDOG_FAILURES", "3"))


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

class EscalationTier(Enum):
    NONE            = "none"
    STANDARD_PROBE  = "standard_probe"
    DEEP_PROBE      = "deep_probe"
    CEILING_JUMP    = "ceiling_jump"
    EMERGENCY       = "emergency"  # human intervention required


class NonceSeverity(Enum):
    CLEAN    = "clean"
    WARN     = "warn"      # >10 min lead — monitor
    PROBE    = "probe"     # >30 min lead — run standard probe
    DEEP     = "deep"      # >60 min lead — run deep probe
    CEILING  = "ceiling"   # >2 h lead    — force ceiling jump
    CRITICAL = "critical"  # poisoned AND nuclear resets — alert operator


@dataclass
class NoncePoisonReport:
    severity: NonceSeverity
    lead_ms: int
    nuclear_resets: int
    deep_reset_active: bool
    trading_paused: bool
    duplicate_process: bool
    recommended_tier: EscalationTier
    details: list[str] = field(default_factory=list)


@dataclass
class EscalationResult:
    success: bool
    tier_used: EscalationTier
    message: str
    new_api_key_required: bool = False


@dataclass
class StartupResult:
    ok: bool
    broker: Optional[Any]         = None   # BaseBroker-compatible instance
    broker_name: str               = ""
    on_fallback: bool              = False
    escalation_result: Optional[EscalationResult] = None
    reason: str                    = ""


# ---------------------------------------------------------------------------
# 1. Nonce Poison Detector
# ---------------------------------------------------------------------------

class NoncePoisonDetector:
    """
    Inspect the running KrakenNonceManager singleton (and its persisted state)
    to determine if the nonce has been "poisoned" — driven so far ahead of
    wall-clock time that Kraken will reject every connection attempt.

    Call :meth:`detect` at startup *before* attempting to connect.  The
    returned :class:`NoncePoisonReport` contains:

    * ``severity``           — how bad the situation is
    * ``recommended_tier``   — which escalation tier CeilingJumpEscalator should start from
    * ``details``            — human-readable explanation list
    """

    def __init__(self, config: Optional[StartupConfig] = None) -> None:
        self._cfg = config or StartupConfig()

    def detect(self) -> NoncePoisonReport:
        """
        Analyse nonce health.  Safe to call when broker is not yet connected.

        Returns a :class:`NoncePoisonReport` describing severity and
        recommended recovery action.
        """
        if not _NONCE_MGR_AVAILABLE:
            return NoncePoisonReport(
                severity=NonceSeverity.CLEAN,
                lead_ms=0,
                nuclear_resets=0,
                deep_reset_active=False,
                trading_paused=False,
                duplicate_process=False,
                recommended_tier=EscalationTier.NONE,
                details=["global_kraken_nonce not available — nonce check skipped"],
            )

        mgr    = get_global_nonce_manager()
        stats  = get_global_nonce_stats()
        now_ms = int(time.time() * 1000)

        lead_ms          = stats["last_nonce"] - now_ms
        nuclear_resets   = stats["nuclear_reset_count"]
        deep_active      = stats["deep_reset_active"]
        trading_paused   = stats["trading_paused"]
        dup_proc         = mgr.detect_other_process_running()

        details: list[str] = []
        details.append(f"Nonce lead: {lead_ms / 1000:.1f}s ({lead_ms / 60_000:.2f} min)")
        if nuclear_resets:
            details.append(f"Nuclear resets this session: {nuclear_resets}")
        if deep_active:
            details.append("Deep-reset mode is active (120-min probe coverage)")
        if trading_paused:
            details.append(f"Trading paused: {stats['pause_remaining_s']:.0f}s remaining")
        if dup_proc:
            details.append("⚠️  Duplicate NIJA process detected — sharing a Kraken key causes nonce poisoning")

        # Determine severity and recommended tier
        cfg = self._cfg

        if dup_proc and nuclear_resets >= 2:
            severity = NonceSeverity.CRITICAL
            tier = EscalationTier.EMERGENCY
            details.append("CRITICAL: duplicate process + multiple nuclear resets → new API key likely required")

        elif lead_ms >= cfg.nonce_ceiling_lead_ms or nuclear_resets >= 2:
            severity = NonceSeverity.CEILING
            tier = EscalationTier.CEILING_JUMP
            details.append(f"Nonce {lead_ms / 3_600_000:.1f}h ahead — ceiling jump required")

        elif lead_ms >= cfg.nonce_deep_lead_ms or (nuclear_resets >= 1 and lead_ms > cfg.nonce_probe_lead_ms):
            severity = NonceSeverity.DEEP
            tier = EscalationTier.DEEP_PROBE
            details.append(f"Nonce {lead_ms / 60_000:.1f}min ahead — deep probe required")

        elif lead_ms >= cfg.nonce_probe_lead_ms:
            severity = NonceSeverity.PROBE
            tier = EscalationTier.STANDARD_PROBE
            details.append(f"Nonce {lead_ms / 60_000:.1f}min ahead — standard probe recommended")

        elif lead_ms >= cfg.nonce_warn_lead_ms:
            severity = NonceSeverity.WARN
            tier = EscalationTier.NONE
            details.append(f"Nonce {lead_ms / 60_000:.1f}min ahead — monitoring")

        else:
            severity = NonceSeverity.CLEAN
            tier = EscalationTier.NONE

        report = NoncePoisonReport(
            severity=severity,
            lead_ms=lead_ms,
            nuclear_resets=nuclear_resets,
            deep_reset_active=deep_active,
            trading_paused=trading_paused,
            duplicate_process=dup_proc,
            recommended_tier=tier,
            details=details,
        )

        if severity != NonceSeverity.CLEAN:
            logger.warning(
                "NoncePoisonDetector: %s — %s",
                severity.value.upper(), "; ".join(details),
            )
        else:
            logger.info("NoncePoisonDetector: nonce is healthy (lead=%d ms)", lead_ms)

        return report


# ---------------------------------------------------------------------------
# 2. Ceiling Jump Escalator
# ---------------------------------------------------------------------------

class CeilingJumpEscalator:
    """
    Drive nonce recovery through a four-tier escalation ladder:

    Tier 0  Standard probe_and_resync   — adaptive step, up to 60 min coverage
    Tier 1  Deep probe                  — 10-min step, 120 min coverage
    Tier 2  Ceiling jump                — nonce → now + 24 h in one step
    Tier 3  Emergency (CRITICAL alert)  — instructs operator to create new API key

    The escalator fires an alert before each tier transition so the operator
    knows what is happening and can intervene if needed.
    """

    def __init__(
        self,
        api_call_fn: Optional[Callable[[], dict]],
        config: Optional[StartupConfig] = None,
    ) -> None:
        """
        Args:
            api_call_fn: ``() → dict`` — must return a Kraken API response with
                         an ``"error"`` key.  Typically wraps
                         ``broker._kraken_private_call("Balance", {})``.
                         May be ``None`` when no broker is yet connected (in
                         which case STANDARD_PROBE and DEEP_PROBE are skipped).
            config:      Startup configuration (optional).
        """
        self._api_call_fn = api_call_fn
        self._cfg = config or StartupConfig()

    # ── Public entry point ─────────────────────────────────────────────────

    def run(
        self,
        starting_tier: EscalationTier = EscalationTier.STANDARD_PROBE,
    ) -> EscalationResult:
        """
        Execute escalation from *starting_tier* upward until one succeeds.

        Returns an :class:`EscalationResult` describing what happened.
        """
        if not _NONCE_MGR_AVAILABLE:
            return EscalationResult(
                success=True,
                tier_used=EscalationTier.NONE,
                message="Nonce manager not available — escalation skipped",
            )

        mgr = get_global_nonce_manager()
        cfg = self._cfg

        tiers_to_try: list[EscalationTier] = []

        tier_order = [
            EscalationTier.STANDARD_PROBE,
            EscalationTier.DEEP_PROBE,
            EscalationTier.CEILING_JUMP,
            EscalationTier.EMERGENCY,
        ]

        start_idx = tier_order.index(starting_tier) if starting_tier in tier_order else 0
        for t in tier_order[start_idx:]:
            tiers_to_try.append(t)

        for tier in tiers_to_try:
            logger.info("CeilingJumpEscalator: attempting tier=%s", tier.value)

            if tier == EscalationTier.STANDARD_PROBE:
                if not cfg.escalation_standard_probe:
                    continue
                if self._api_call_fn is None:
                    logger.info("CeilingJumpEscalator: STANDARD_PROBE skipped — no api_call_fn yet")
                    continue
                self._fire_alert(
                    f"Nonce recovery: attempting standard probe_and_resync (adaptive step)",
                    severity="WARNING",
                )
                kwargs: dict[str, Any] = {}
                if cfg.standard_probe_max_attempts:
                    kwargs["max_attempts"] = cfg.standard_probe_max_attempts
                ok = mgr.probe_and_resync(self._api_call_fn, **kwargs)
                if ok:
                    logger.info("✅ CeilingJumpEscalator: STANDARD_PROBE succeeded")
                    return EscalationResult(
                        success=True,
                        tier_used=tier,
                        message="Standard probe_and_resync calibrated the nonce",
                    )
                logger.warning("CeilingJumpEscalator: STANDARD_PROBE exhausted — escalating")

            elif tier == EscalationTier.DEEP_PROBE:
                if not cfg.escalation_deep_probe:
                    continue
                if self._api_call_fn is None:
                    logger.info("CeilingJumpEscalator: DEEP_PROBE skipped — no api_call_fn yet")
                    continue
                self._fire_alert(
                    "Nonce recovery escalated to deep-probe mode (12×10 min = 120 min coverage)",
                    severity="WARNING",
                )
                # Activate deep-reset mode on the running manager instance via public API
                if _NONCE_MGR_AVAILABLE:
                    get_global_nonce_manager().activate_deep_reset()
                kwargs = {}
                if cfg.deep_probe_max_attempts:
                    kwargs["max_attempts"] = cfg.deep_probe_max_attempts
                ok = mgr.probe_and_resync(self._api_call_fn, **kwargs)
                if ok:
                    logger.info("✅ CeilingJumpEscalator: DEEP_PROBE succeeded")
                    return EscalationResult(
                        success=True,
                        tier_used=tier,
                        message="Deep probe_and_resync calibrated the nonce",
                    )
                logger.warning("CeilingJumpEscalator: DEEP_PROBE exhausted — escalating")

            elif tier == EscalationTier.CEILING_JUMP:
                if not cfg.escalation_ceiling_jump:
                    continue
                self._fire_alert(
                    f"Nonce escalated to CEILING JUMP (now+{cfg.ceiling_jump_ms / 3_600_000:.0f}h). "
                    "Nonce poisoning is severe. Broker will reconnect after this jump.",
                    severity="CRITICAL",
                )
                new_nonce = mgr.force_ceiling_jump(ms=cfg.ceiling_jump_ms)
                logger.warning(
                    "CeilingJumpEscalator: ceiling jump applied — nonce=%d "
                    "(now+%.1f h). Reconnect required.",
                    new_nonce, cfg.ceiling_jump_ms / 3_600_000,
                )
                if self._api_call_fn is not None:
                    ok = mgr.probe_and_resync(self._api_call_fn)
                    if ok:
                        logger.info("✅ CeilingJumpEscalator: CEILING_JUMP + probe succeeded")
                        return EscalationResult(
                            success=True,
                            tier_used=tier,
                            message=f"Ceiling jump (now+{cfg.ceiling_jump_ms / 3_600_000:.0f}h) + probe succeeded",
                        )
                    logger.warning("CeilingJumpEscalator: post-ceiling probe still failing — escalating to EMERGENCY")
                else:
                    # No API call fn: ceiling jump applied, reconnect should work
                    return EscalationResult(
                        success=True,
                        tier_used=tier,
                        message=f"Ceiling jump applied (now+{cfg.ceiling_jump_ms / 3_600_000:.0f}h). Reconnect the broker.",
                    )

            elif tier == EscalationTier.EMERGENCY:
                msg = (
                    "🚨 NONCE ESCALATION FAILED — ALL RECOVERY TIERS EXHAUSTED.\n"
                    "Only two real recovery paths remain:\n"
                    "  Option 1 (FASTEST + CLEAN): Rotate Kraken API keys.\n"
                    "    1. Kraken → Settings → API\n"
                    "    2. Delete old API key\n"
                    "    3. Create new API key\n"
                    "    4. Update bot credentials (.env or store_user_api_key())\n"
                    "    5. Restart bot/service\n"
                    "    👉 This resets the nonce floor to zero for the new key.\n"
                    "  Option 2: Wait until wall-clock time catches up to Kraken's poisoned nonce floor.\n"
                )
                logger.critical(msg)
                self._fire_alert(msg, severity="EMERGENCY")
                return EscalationResult(
                    success=False,
                    tier_used=tier,
                    message=msg,
                    new_api_key_required=True,
                )

        return EscalationResult(
            success=False,
            tier_used=EscalationTier.EMERGENCY,
            message="All escalation tiers exhausted",
            new_api_key_required=True,
        )

    # ── Private helpers ────────────────────────────────────────────────────

    def _fire_alert(self, message: str, severity: str = "WARNING") -> None:
        """Fire an alert through the alert manager (or log it if unavailable)."""
        log_fn = {
            "INFO":      logger.info,
            "WARNING":   logger.warning,
            "CRITICAL":  logger.critical,
            "EMERGENCY": logger.critical,
        }.get(severity, logger.warning)
        log_fn("CeilingJumpEscalator [%s]: %s", severity, message)

        if _ALERT_MGR_AVAILABLE and get_alert_manager is not None:
            try:
                sev = AlertSeverity[severity] if severity in AlertSeverity.__members__ else AlertSeverity.WARNING  # type: ignore[union-attr]
                cat = AlertCategory.RISK if hasattr(AlertCategory, "RISK") else list(AlertCategory)[0]  # type: ignore[union-attr]
                get_alert_manager().fire(
                    category=cat,
                    severity=sev,
                    title=f"Nonce escalation: {severity}",
                    message=message,
                    source="CeilingJumpEscalator",
                )
            except Exception as exc:
                logger.debug("CeilingJumpEscalator: alert dispatch failed (%s)", exc)


# ---------------------------------------------------------------------------
# 3. Broker Fallback Controller
# ---------------------------------------------------------------------------

class BrokerFallbackController:
    """
    Connect to the primary broker (Kraken) and automatically fall back to the
    secondary broker (Coinbase) if primary connection fails.

    Fires alerts on broker switch and when falling back to let the operator
    know the bot is running in degraded mode.

    Usage::

        ctrl   = BrokerFallbackController(config)
        result = ctrl.connect_with_fallback()

        if result.ok:
            broker = result.broker
    """

    PRIMARY_NAME   = "KRAKEN"
    SECONDARY_NAME = "COINBASE"

    def __init__(self, config: Optional[StartupConfig] = None) -> None:
        self._cfg           = config or StartupConfig()
        self._active_broker: Optional[Any] = None
        self._active_name   = ""
        self._on_fallback   = False
        self._lock          = threading.Lock()

    # ── Properties ─────────────────────────────────────────────────────────

    @property
    def active_broker(self) -> Optional[Any]:
        with self._lock:
            return self._active_broker

    @property
    def active_name(self) -> str:
        with self._lock:
            return self._active_name

    @property
    def on_fallback(self) -> bool:
        with self._lock:
            return self._on_fallback

    # ── Public entry point ─────────────────────────────────────────────────

    def connect_with_fallback(self) -> StartupResult:
        """
        Attempt primary broker connection; fall back to secondary on failure.

        Returns a :class:`StartupResult` with ``ok=True`` when *any* broker
        connected successfully.
        """
        if not _BROKER_AVAILABLE:
            logger.warning("BrokerFallbackController: broker_manager not available — skipping broker connection")
            return StartupResult(
                ok=True,  # Don't block startup if broker module is missing
                broker=None,
                broker_name="NONE",
                reason="broker_manager not importable",
            )

        # ── Primary: Kraken ────────────────────────────────────────────────
        kraken_creds = (
            os.getenv("KRAKEN_PLATFORM_API_KEY") or os.getenv("KRAKEN_API_KEY")
        )
        if kraken_creds:
            logger.info("BrokerFallbackController: attempting PRIMARY broker (Kraken)…")
            kraken_broker, kraken_ok = self._try_connect_kraken()
            if kraken_ok and kraken_broker is not None:
                with self._lock:
                    self._active_broker = kraken_broker
                    self._active_name   = self.PRIMARY_NAME
                    self._on_fallback   = False
                logger.info("✅ BrokerFallbackController: PRIMARY (Kraken) connected")
                return StartupResult(
                    ok=True,
                    broker=kraken_broker,
                    broker_name=self.PRIMARY_NAME,
                    on_fallback=False,
                )
            logger.warning(
                "BrokerFallbackController: PRIMARY (Kraken) failed after %d attempt(s) — "
                "evaluating fallback", self._cfg.primary_max_attempts,
            )
        else:
            logger.info("BrokerFallbackController: Kraken credentials not configured — trying secondary")

        # ── Secondary: Coinbase ────────────────────────────────────────────
        if not self._cfg.fallback_enabled:
            return StartupResult(
                ok=False,
                reason="Primary (Kraken) failed and fallback is disabled",
            )

        # Respect the NIJA_DISABLE_COINBASE flag — if Coinbase is explicitly
        # disabled, treat it the same as having no fallback configured.
        _coinbase_disabled = os.getenv("NIJA_DISABLE_COINBASE", "false").strip().lower() in (
            "1", "true", "yes"
        )
        if _coinbase_disabled:
            msg = "Primary (Kraken) failed and NIJA_DISABLE_COINBASE=true — Coinbase fallback suppressed."
            logger.warning("BrokerFallbackController: %s", msg)
            return StartupResult(ok=False, reason=msg)

        coinbase_creds = os.getenv("COINBASE_API_KEY") and os.getenv("COINBASE_API_SECRET")
        if not coinbase_creds:
            msg = (
                "Primary (Kraken) failed and Coinbase credentials are not configured. "
                "Bot cannot connect to any broker."
            )
            logger.error("BrokerFallbackController: %s", msg)
            self._fire_alert(
                "🚨 PRIMARY BROKER (Kraken) FAILED — no fallback credentials configured. "
                "Trading is impossible until Kraken is restored or Coinbase credentials are added.",
                severity="EMERGENCY",
            )
            return StartupResult(ok=False, reason=msg)

        self._fire_alert(
            "⚠️  PRIMARY BROKER (Kraken) failed — SWITCHING TO SECONDARY (Coinbase). "
            "Trading continues in fallback mode. Investigate Kraken credentials / nonce.",
            severity="CRITICAL",
        )
        logger.warning("BrokerFallbackController: switching to SECONDARY broker (Coinbase)…")

        coinbase_broker, coinbase_ok = self._try_connect_coinbase()
        if coinbase_ok and coinbase_broker is not None:
            with self._lock:
                self._active_broker = coinbase_broker
                self._active_name   = self.SECONDARY_NAME
                self._on_fallback   = True
            logger.warning(
                "BrokerFallbackController: running on FALLBACK broker (%s). "
                "Restore Kraken to return to primary.",
                self.SECONDARY_NAME,
            )
            return StartupResult(
                ok=True,
                broker=coinbase_broker,
                broker_name=self.SECONDARY_NAME,
                on_fallback=True,
            )

        msg = "Both primary (Kraken) and secondary (Coinbase) brokers failed to connect"
        logger.critical("BrokerFallbackController: %s", msg)
        self._fire_alert(
            "🚨 ALL BROKERS FAILED — Kraken AND Coinbase could not connect. "
            "NIJA cannot trade. Check API keys, internet connectivity, and rate limits.",
            severity="EMERGENCY",
        )
        return StartupResult(ok=False, reason=msg)

    # ── Private helpers ────────────────────────────────────────────────────

    def _try_connect_kraken(self) -> tuple[Optional[Any], bool]:
        """Return the singleton Kraken PLATFORM broker from the registry.

        Delegates to ``multi_account_broker_manager.initialize_platform_brokers()``
        so there is exactly one Kraken instance per process.  Falls back to
        raw construction only when MABM is not importable (rare bootstrap edge
        case).
        """
        # ── Primary path: delegate to MABM (idempotent, guarded) ─────────────
        if _MABM_AVAILABLE and _mabm is not None:
            try:
                results = _mabm.initialize_platform_brokers()
                kraken_result = results.get("kraken", {})
                broker = kraken_result.get("broker")
                ok = kraken_result.get("connected", False)
                if broker is not None and ok:
                    return broker, True
                # initialize_platform_brokers already logged the failure;
                # surface it here for BrokerFallbackController's counter.
                logger.warning(
                    "BrokerFallbackController: MABM Kraken init returned connected=False",
                )
                return broker, False
            except Exception as exc:
                logger.warning(
                    "BrokerFallbackController: MABM Kraken init raised: %s — falling back to direct construction",
                    exc,
                )

        # ── Fallback path: direct construction (MABM unavailable) ────────────
        for attempt in range(1, self._cfg.primary_max_attempts + 1):
            try:
                broker = KrakenBroker(account_type=AccountType.PLATFORM)
                ok = broker.connect()
                if ok:
                    # Record CRITICAL criticality in the global registry so all
                    # layers see the correct role even in this bootstrap path.
                    if _BROKER_REGISTRY_AVAILABLE and _broker_registry is not None and _BC is not None:
                        _broker_registry.set_criticality("kraken", _BC.CRITICAL)
                    return broker, True
                logger.warning(
                    "BrokerFallbackController: Kraken attempt %d/%d — connect() returned False",
                    attempt, self._cfg.primary_max_attempts,
                )
            except Exception as exc:
                logger.warning(
                    "BrokerFallbackController: Kraken attempt %d/%d — exception: %s",
                    attempt, self._cfg.primary_max_attempts, exc,
                )
            if attempt < self._cfg.primary_max_attempts:
                delay = min(5.0 * attempt, 30.0)
                time.sleep(delay)

        return None, False

    def _try_connect_coinbase(self) -> tuple[Optional[Any], bool]:
        """Return the singleton Coinbase PLATFORM broker from the registry.

        Delegates to ``get_platform_broker("coinbase")`` first (instance
        already created by MABM), then falls back to
        ``multi_account_broker_manager.initialize_platform_brokers()`` if the
        instance does not exist yet, and finally to direct construction when
        MABM is unavailable.
        """
        # ── Fast path: instance already in registry ───────────────────────────
        if get_platform_broker is not None:
            existing = get_platform_broker("coinbase")
            if existing is not None and getattr(existing, "connected", False):
                logger.info("BrokerFallbackController: reusing existing Coinbase singleton from registry")
                return existing, True

        # ── Delegate path: MABM initialisation (idempotent) ──────────────────
        if _MABM_AVAILABLE and _mabm is not None:
            try:
                results = _mabm.initialize_platform_brokers()
                cb_result = results.get("coinbase", {})
                broker = cb_result.get("broker")
                ok = cb_result.get("connected", False)
                if broker is not None and ok:
                    return broker, True
                logger.warning("BrokerFallbackController: MABM Coinbase init returned connected=False")
                return broker, False
            except Exception as exc:
                logger.warning(
                    "BrokerFallbackController: MABM Coinbase init raised: %s — falling back to direct construction",
                    exc,
                )

        # ── Fallback path: direct construction (MABM unavailable) ────────────
        try:
            broker = CoinbaseBroker()
            ok = broker.connect()
            if ok:
                # When Coinbase is acting as the live fallback (Kraken failed),
                # elevate its registry criticality to PRIMARY so all layers know
                # it is the active execution broker for this session.
                if _BROKER_REGISTRY_AVAILABLE and _broker_registry is not None and _BC is not None:
                    _broker_registry.set_criticality("coinbase", _BC.PRIMARY)
                return broker, True
            logger.warning("BrokerFallbackController: Coinbase connect() returned False")
        except Exception as exc:
            logger.warning("BrokerFallbackController: Coinbase exception: %s", exc)
        return None, False

    def _fire_alert(self, message: str, severity: str = "WARNING") -> None:
        log_fn = {
            "WARNING":   logger.warning,
            "CRITICAL":  logger.critical,
            "EMERGENCY": logger.critical,
        }.get(severity, logger.warning)
        log_fn("BrokerFallbackController [%s]: %s", severity, message)

        if _ALERT_MGR_AVAILABLE and get_alert_manager is not None:
            try:
                sev = AlertSeverity[severity] if severity in AlertSeverity.__members__ else AlertSeverity.WARNING  # type: ignore[union-attr]
                cat = AlertCategory.RISK if hasattr(AlertCategory, "RISK") else list(AlertCategory)[0]  # type: ignore[union-attr]
                get_alert_manager().fire(
                    category=cat,
                    severity=sev,
                    title=f"Broker failover: {severity}",
                    message=message,
                    source="BrokerFallbackController",
                )
            except Exception as exc:
                logger.debug("BrokerFallbackController: alert dispatch failed (%s)", exc)

        if _TEXT_ALERT_AVAILABLE and get_text_alert_system is not None and severity in ("CRITICAL", "EMERGENCY"):
            try:
                get_text_alert_system().emergency_mode_triggered(  # type: ignore[union-attr]
                    level=severity,
                    message=message,
                )
            except Exception as exc:
                logger.debug("BrokerFallbackController: text alert failed (%s)", exc)


# ---------------------------------------------------------------------------
# 4. Pre-Halt Alert Engine
# ---------------------------------------------------------------------------

class PreHaltAlertEngine:
    """
    Fires warning alerts with a countdown before trading halts so the operator
    has time to intervene.

    Typical use::

        engine = PreHaltAlertEngine(config)

        # Register a broker-health watchdog
        engine.register_watchdog(
            name="kraken_health",
            fn=lambda: broker.connected,
            interval_s=60,
        )
        engine.start()

        # Elsewhere, when you know a halt is coming:
        engine.warn_pre_halt("Risk limit breached", countdown_s=300)
    """

    def __init__(self, config: Optional[StartupConfig] = None) -> None:
        self._cfg       = config or StartupConfig()
        self._stop      = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._watchdogs: list[dict] = []
        self._lock = threading.Lock()

    # ── Watchdog registration ──────────────────────────────────────────────

    def register_watchdog(
        self,
        name: str,
        fn: Callable[[], bool],
        interval_s: Optional[float] = None,
        max_failures: Optional[int] = None,
    ) -> None:
        """
        Register a liveness function that the engine will call periodically.

        Args:
            name:         Human-readable name for log messages.
            fn:           ``() → bool`` — return True if healthy; False if failing.
            interval_s:   Poll interval (defaults to ``config.watchdog_interval_s``).
            max_failures: Consecutive failures before warning (defaults to ``config.watchdog_max_failures``).
        """
        with self._lock:
            self._watchdogs.append({
                "name":         name,
                "fn":           fn,
                "interval_s":   interval_s if interval_s is not None else self._cfg.watchdog_interval_s,
                "max_failures": max_failures if max_failures is not None else self._cfg.watchdog_max_failures,
                "fail_count":   0,
                "last_check":   0.0,
            })
        logger.debug("PreHaltAlertEngine: registered watchdog '%s'", name)

    # ── Lifecycle ──────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the background watchdog thread."""
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="nija.pre_halt_watchdog",
            daemon=True,
        )
        self._thread.start()
        logger.info("PreHaltAlertEngine: watchdog thread started")

    def stop(self) -> None:
        """Stop the watchdog thread gracefully."""
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    # ── Manual halt warning ────────────────────────────────────────────────

    def warn_pre_halt(self, reason: str, countdown_s: float = 60.0) -> None:
        """
        Immediately fire a CRITICAL alert warning that trading will halt in
        *countdown_s* seconds.

        If *countdown_s* > 0, schedules a second "halting NOW" alert at
        expiry so the operator can track whether the halt actually fired.
        """
        pre_msg = (
            f"⚠️  TRADING HALT IMMINENT in {countdown_s:.0f}s — {reason}\n"
            "Intervene now to prevent trading from stopping."
        )
        logger.critical("PreHaltAlertEngine: %s", pre_msg)
        self._fire_alert(pre_msg, severity="CRITICAL", title="Trading halt imminent")

        if countdown_s > 0:
            def _send_halt_now():
                time.sleep(countdown_s)
                if not self._stop.is_set():
                    now_msg = f"🛑  TRADING HALTED — {reason}"
                    logger.critical("PreHaltAlertEngine: %s", now_msg)
                    self._fire_alert(now_msg, severity="EMERGENCY", title="Trading halted")

            t = threading.Thread(target=_send_halt_now, daemon=True)
            t.start()

    # ── Background loop ────────────────────────────────────────────────────

    def _run_loop(self) -> None:
        """Watchdog background thread body."""
        while not self._stop.is_set():
            now = time.time()
            with self._lock:
                watchdogs = list(self._watchdogs)

            for wd in watchdogs:
                if now - wd["last_check"] < wd["interval_s"]:
                    continue
                wd["last_check"] = now

                try:
                    healthy = bool(wd["fn"]())
                except Exception as exc:
                    logger.debug("PreHaltAlertEngine: watchdog '%s' raised %s", wd["name"], exc)
                    healthy = False

                if healthy:
                    if wd["fail_count"] > 0:
                        logger.info(
                            "PreHaltAlertEngine: watchdog '%s' recovered (was %d failures)",
                            wd["name"], wd["fail_count"],
                        )
                    wd["fail_count"] = 0
                else:
                    wd["fail_count"] += 1
                    logger.warning(
                        "PreHaltAlertEngine: watchdog '%s' failure #%d/%d",
                        wd["name"], wd["fail_count"], wd["max_failures"],
                    )
                    if wd["fail_count"] >= wd["max_failures"]:
                        self.warn_pre_halt(
                            reason=f"Watchdog '{wd['name']}' failed {wd['fail_count']} consecutive times",
                            countdown_s=self._cfg.pre_halt_warn_s,
                        )
                        wd["fail_count"] = 0  # reset so we don't spam

            self._stop.wait(timeout=5.0)

    # ── Alert dispatch ─────────────────────────────────────────────────────

    def _fire_alert(self, message: str, severity: str, title: str = "") -> None:
        log_fn = {
            "INFO":      logger.info,
            "WARNING":   logger.warning,
            "CRITICAL":  logger.critical,
            "EMERGENCY": logger.critical,
        }.get(severity, logger.warning)
        log_fn("PreHaltAlertEngine [%s]: %s", severity, message)

        if _ALERT_MGR_AVAILABLE and get_alert_manager is not None:
            try:
                sev = AlertSeverity[severity] if severity in AlertSeverity.__members__ else AlertSeverity.CRITICAL  # type: ignore[union-attr]
                cat = AlertCategory.RISK if hasattr(AlertCategory, "RISK") else list(AlertCategory)[0]  # type: ignore[union-attr]
                get_alert_manager().fire(
                    category=cat,
                    severity=sev,
                    title=title or f"Pre-halt: {severity}",
                    message=message,
                    source="PreHaltAlertEngine",
                )
            except Exception as exc:
                logger.debug("PreHaltAlertEngine: alert dispatch failed (%s)", exc)

        if _TEXT_ALERT_AVAILABLE and get_text_alert_system is not None and severity in ("CRITICAL", "EMERGENCY"):
            try:
                get_text_alert_system().emergency_mode_triggered(  # type: ignore[union-attr]
                    level=severity,
                    message=message,
                )
            except Exception as exc:
                logger.debug("PreHaltAlertEngine: text alert failed (%s)", exc)


# ---------------------------------------------------------------------------
# 5. Self-Healing Startup Orchestrator
# ---------------------------------------------------------------------------

class SelfHealingStartup:
    """
    Orchestrates the full self-healing boot sequence.

    Steps
    -----
    1. **State-machine check** — if EMERGENCY_STOP: auto-reset to OFF (then
       auto-activate to LIVE_ACTIVE when LIVE_CAPITAL_VERIFIED=true).
    2. **Nonce poison detection** — inspect lead, nuclear-reset count, dup process.
    3. **Nonce escalation** — run CeilingJumpEscalator from the recommended tier.
    4. **Broker connection** — connect via BrokerFallbackController.
    5. **Watchdog registration** — register broker-health watchdog with PreHaltAlertEngine.
    6. **Readiness gate** — signal startup_readiness_gate (if available).

    Usage::

        result = SelfHealingStartup().run()
        if result.ok:
            broker = result.broker
        else:
            raise SystemExit("Startup failed: " + result.reason)
    """

    def __init__(self, config: Optional[StartupConfig] = None) -> None:
        self._cfg                    = config or StartupConfig()
        self.pre_halt_engine         = PreHaltAlertEngine(self._cfg)
        self._broker_ctrl            = BrokerFallbackController(self._cfg)
        self._sm_lock                = threading.Lock()
        self._sm_started: bool       = False
        self._bootstrap_complete: bool = False  # Fix 4: set True once run() succeeds

    # ── Private bootstrap helpers ──────────────────────────────────────────

    @staticmethod
    def _is_bootstrap_ready(startup_result: "StartupResult", broker_map: dict, ca: Any) -> bool:
        """Return True when all bootstrap prerequisites are satisfied.

        This replaces the old strict gate ``startup_result.ok and broker_map
        and ca.is_ready()`` which was race-sensitive during bootstrap: both
        ``broker_map`` and ``ca.is_ready()`` could be momentarily falsy even
        when the system was actually ready, causing the state machine to stall
        in OFF indefinitely.

        The new gate is intentionally more lenient:
        * ``brokers_ok`` — at least one broker is registered (non-empty map).
        * ``ca_ok``      — CA must be ready *only* when the CA module is present;
                          if the module is absent the gate defaults to True
                          (graceful degradation).
        """
        try:
            brokers_ok = bool(broker_map)
            ca_ok = True
            if _CA_AVAILABLE and _get_capital_authority is not None:
                ca_ok = ca.is_ready()
            return startup_result.ok and brokers_ok and ca_ok
        except Exception:
            return False

    # ── Public entry point ─────────────────────────────────────────────────

    def run(self) -> StartupResult:
        """
        Execute the full self-healing boot sequence.

        Returns a :class:`StartupResult`.  ``ok=True`` means *at least one*
        broker is connected and trading can begin.
        """
        logger.info("=" * 60)
        logger.info("🚀  NIJA Self-Healing Startup — beginning boot sequence")
        logger.info("=" * 60)

        # Step 1: State machine
        self.start_state_machine()
        # Step 1: State machine — HARD REQUIREMENT: must start before anything else
        # Direct synchronous call only; never via thread, scheduler, or async fire-and-forget.
        logger.critical("BOOT: forcing state machine entry")
        _started = False
        try:
            logger.critical("BOOT: entering state machine")
            self._step_state_machine()
            _started = True
        except Exception as _boot_sm_err:
            logger.critical("BOOT: state machine failed: %s", _boot_sm_err)
            raise
        if not _started:
            raise RuntimeError("STATE MACHINE DID NOT START")

        # Step 2: Nonce poison detection
        nonce_report = NoncePoisonDetector(self._cfg).detect()
        self._log_nonce_report(nonce_report)

        # Step 3: Pre-connection nonce escalation (no api_call_fn yet)
        esc_result: Optional[EscalationResult] = None
        if nonce_report.recommended_tier not in (EscalationTier.NONE, EscalationTier.STANDARD_PROBE):
            # For DEEP_PROBE and CEILING_JUMP we don't need an api_call_fn — ceiling jump is
            # pure local state; deep-probe mode only takes effect when probe_and_resync is called
            # inside KrakenBroker.connect(), so we just flag it here.
            escalator = CeilingJumpEscalator(api_call_fn=None, config=self._cfg)
            if nonce_report.recommended_tier == EscalationTier.CEILING_JUMP:
                if _NONCE_PROBE_SYSTEM_ENABLED:
                    esc_result = escalator.run(starting_tier=EscalationTier.CEILING_JUMP)
                else:
                    logger.info(
                        "SelfHealingStartup: CEILING_JUMP recommended but probe system is "
                        "disabled (NIJA_ENABLE_PROBE_SYSTEM not set) — "
                        "server-anchored next_nonce() will self-heal on the first API call "
                        "(nonce lead=%.1f min). Skipping ceiling jump.",
                        nonce_report.lead_ms / 60_000,
                    )
            elif nonce_report.recommended_tier == EscalationTier.DEEP_PROBE:
                if _NONCE_PROBE_SYSTEM_ENABLED and _NONCE_MGR_AVAILABLE:
                    get_global_nonce_manager().activate_deep_reset()
                    logger.warning(
                        "SelfHealingStartup: deep-reset mode activated on nonce manager "
                        "(probe_and_resync inside KrakenBroker.connect() will use 120-min coverage)"
                    )
                else:
                    logger.info(
                        "SelfHealingStartup: DEEP_PROBE recommended but probe system is "
                        "disabled (NIJA_ENABLE_PROBE_SYSTEM not set) — "
                        "server-anchored next_nonce() will self-heal on the first API call "
                        "(nonce lead=%.1f min). Skipping deep-reset activation.",
                        nonce_report.lead_ms / 60_000,
                    )
            elif nonce_report.recommended_tier == EscalationTier.EMERGENCY:
                esc_result = escalator.run(starting_tier=EscalationTier.EMERGENCY)
                if esc_result and not esc_result.success:
                    return StartupResult(
                        ok=False,
                        reason=esc_result.message,
                    )

        # Step 4: Broker connection with fallback
        startup_result = self._broker_ctrl.connect_with_fallback()
        if esc_result:
            startup_result.escalation_result = esc_result

        # Step 5: Watchdog
        if startup_result.ok and startup_result.broker is not None:
            broker = startup_result.broker
            self.pre_halt_engine.register_watchdog(
                name=f"{startup_result.broker_name}_health",
                fn=lambda: getattr(broker, "connected", True),
            )
            # CA/LIVE health watchdog — LIVE_ACTIVE never bypasses CA checks.
            self.pre_halt_engine.register_watchdog(
                name="ca_live_health",
                fn=self._ca_watchdog_fn,
            )
            # Fix #3: CA-readiness watchdog re-entry — if CA becomes stale after
            # startup the watchdog re-runs the state machine to recover silently
            # without requiring a full restart.
            self.pre_halt_engine.register_watchdog(
                name="ca_readiness",
                fn=self._ca_watchdog_fn,
                interval_s=self._cfg.watchdog_interval_s,
                max_failures=1,
            )
            self.pre_halt_engine.start()
            logger.info("PreHaltAlertEngine: watchdog started for %s", startup_result.broker_name)

        # Step 6: Signal readiness gate
        if startup_result.ok and _READINESS_GATE_AVAILABLE and get_startup_readiness_gate is not None:
            try:
                gate = get_startup_readiness_gate()
                gate.signal_ready("self_healing_startup")
            except Exception as exc:
                logger.debug("SelfHealingStartup: readiness gate signal failed (%s)", exc)

        # Step 7: HARD POST-CONNECTION READINESS LOOP
        # Repeatedly refresh CapitalAuthority and step the state machine until
        # CA is confirmed ready (or the bot is already LIVE_ACTIVE), preventing
        # the silent stall where the broker is connected but the state machine
        # never observes a fresh CA snapshot and sits idle forever.
        broker_map = (
            dict(_mabm.platform_brokers)
            if (_MABM_AVAILABLE and _mabm is not None)
            else (
                {startup_result.broker_name: startup_result.broker}
                if startup_result.broker is not None
                else {}
            )
        )
        # Obtain the CapitalAuthority instance; fall back to a pass-through stub
        # when the module is unavailable so the condition still evaluates cleanly.
        ca: Any = type("_NullCA", (), {"is_ready": lambda self: True})()
        if _CA_AVAILABLE and _get_capital_authority is not None:
            try:
                ca = _get_capital_authority()
            except Exception:
                pass  # leave ca as the pass-through stub
        if self._is_bootstrap_ready(startup_result, broker_map, ca):
            # ensure first activation tick occurs immediately post-init
            self._step_state_machine()

            import time as _time

            _ca_timeout_s = 60
            _ca_start = _time.time()

            logger.info("🔁 Post-connection CA readiness loop started")

            while _time.time() - _ca_start < _ca_timeout_s:
                # FIX 3: Force CA refresh before each state-machine evaluation.
                # Must call _step_state_machine() directly (not start_state_machine())
                # so maybe_auto_activate() is re-evaluated on every iteration — the
                # once-only guard in start_state_machine() would make it a no-op here.
                if _MABM_AVAILABLE and _mabm is not None:
                    try:
                        if hasattr(_mabm, "refresh_capital_authority"):
                            _mabm.refresh_capital_authority(trigger="post_connection_gate")
                    except Exception as _ca_exc:
                        logger.warning(
                            "Failed to refresh CapitalAuthority in post-connection loop: %s",
                            _ca_exc,
                        )

                self._step_state_machine()

                if self._is_ca_ready() or self._is_live_active():
                    logger.info("✅ CA_READY RESOLVED — exiting post-connection loop")
                    break

                _time.sleep(_CA_POLL_INTERVAL_S)
            else:
                logger.critical("🚨 CA_READY TIMEOUT — bot stuck in pre-trade state")

        # ── HARD POST-PREFLIGHT TRANSITION GUARANTEE ───────────────────────
        # After the CA readiness loop completes (or times out), force a
        # deterministic push through the state machine so the bot cannot silently
        # stall between PREFLIGHT and RUNTIME.  Up to three attempts are made;
        # the loop short-circuits as soon as LIVE_ACTIVE is confirmed.
        # FIX 3: use _step_state_machine() directly so maybe_auto_activate() is
        # called on every attempt (start_state_machine() is a no-op after the
        # first call due to its once-only guard).
        if startup_result.ok:
            self._bootstrap_complete = True  # Fix 4: mark bootstrap as complete
            logger.info("🚀 PREFLIGHT COMPLETE → ENTERING RUNTIME BOOTSTRAP")
            for _ in range(_MAX_STATE_TRANSITION_ATTEMPTS):
                self._step_state_machine()
                if self._is_live_active():
                    break
            if not self._is_live_active():
                logger.warning(
                    "⚠️ Not LIVE_ACTIVE after PREFLIGHT — "
                    "state machine could not complete transition; "
                    "watchdog will retry"
                )

        if startup_result.ok:
            mode = "FALLBACK" if startup_result.on_fallback else "PRIMARY"
            logger.info(
                "✅  SelfHealingStartup: boot sequence complete — broker=%s (%s mode)",
                startup_result.broker_name, mode,
            )
        else:
            logger.critical(
                "❌  SelfHealingStartup: boot sequence FAILED — %s",
                startup_result.reason,
            )
            self.pre_halt_engine.warn_pre_halt(
                reason=f"Startup failed: {startup_result.reason}",
                countdown_s=0,
            )

        return startup_result

    # ── Private helpers ────────────────────────────────────────────────────

    def _is_live_active(self) -> bool:
        """Return True if the trading state machine is currently LIVE_ACTIVE."""
        if not _STATE_MACHINE_AVAILABLE:
            return False
        try:
            sm = get_state_machine()
            return sm.get_current_state() == TradingState.LIVE_ACTIVE
        except Exception as exc:
            logger.debug("SelfHealingStartup._is_live_active: state machine query failed (%s)", exc)
            return False

    def _is_ca_ready(self) -> bool:
        """Return True if CapitalAuthority passes the capital readiness gate.

        Module absence is treated as passing (graceful degradation) so that
        deployments without the capital_authority module are not permanently
        locked out.  Any other exception is treated as not-ready to prevent
        a silent false-positive.
        """
        _capital_readiness_gate = None
        for _module in ("trading_state_machine", "bot.trading_state_machine"):
            try:
                import importlib
                mod = importlib.import_module(_module)
                _capital_readiness_gate = getattr(mod, "_capital_readiness_gate", None)
                if _capital_readiness_gate is not None:
                    break
            except ImportError:
                continue

        if _capital_readiness_gate is None:
            # Module unavailable — treat as passing (graceful degradation).
            return True

        try:
            ready, _ = _capital_readiness_gate()
            return ready
        except Exception as exc:
            logger.warning(
                "SelfHealingStartup._is_ca_ready: CA gate check failed (%s: %s)"
                " — treating as not-ready to prevent silent false-positive",
                type(exc).__name__, exc,
            )
            return False

    def start_state_machine(self) -> None:
        """Single-authority entry point for the state machine.

        Guarantees the state machine is invoked at most once per
        :class:`SelfHealingStartup` instance.  Thread-safe: a
        :class:`threading.Lock` prevents concurrent invocations from multiple
        call sites from both entering :meth:`_step_state_machine` simultaneously.
        """
        logger.critical("BOOT: unified state machine entry")

        with self._sm_lock:
            if self._sm_started:
                logger.critical("BOOT: state machine already started — skipping")
                return

            self._sm_started = True

        self._step_state_machine()

    def step_state_machine(self) -> None:
        """Public entry point for an unconditional state machine step.

        Unlike :meth:`start_state_machine`, this method does **not** enforce
        the once-only guard — it is intended for callers that need to force a
        re-evaluation of the trading state machine *after* the initial boot
        sequence has already completed (e.g. after ``INIT_LOCK_ACQUIRED →
        bootstrap complete``).

        Thread-safe via the internal ``_sm_lock``.
        """
        logger.critical("BOOT: forced post-init state machine step")
        with self._sm_lock:
            self._step_state_machine()

    def _step_state_machine(self) -> None:
        """Auto-reset EMERGENCY_STOP → OFF → LIVE_ACTIVE when safe to do so."""
        logger.critical("B2 ENTERING_NEXT_PREFLIGHT_STAGE")
        if not _STATE_MACHINE_AVAILABLE:
            return

        # Pre-warm: if brokers are already registered, refresh CapitalAuthority
        # so the CA_READY gate sees a fresh snapshot rather than a stale one.
        # This is a no-op when called before any broker has been registered
        # (refresh_capital_authority gates on has_registered_brokers()), and a
        # genuine refresh when called after broker connection — the intended use.
        if _MABM_AVAILABLE and _mabm is not None:
            try:
                if hasattr(_mabm, "has_registered_brokers") and _mabm.has_registered_brokers():
                    logger.info(
                        "SelfHealingStartup: refreshing CapitalAuthority before state machine step"
                    )
                    _mabm.refresh_capital_authority(trigger="state_machine_gate")
            except Exception as exc:
                logger.warning(
                    "SelfHealingStartup: CA pre-warm before state machine step failed (%s: %s)"
                    " — state machine will evaluate CA_READY against potentially stale data",
                    type(exc).__name__, exc,
                )

        try:
            sm      = get_state_machine()
            current = sm.get_current_state()

            if current == TradingState.EMERGENCY_STOP:
                lcv = os.environ.get("LIVE_CAPITAL_VERIFIED", "false").lower()
                if lcv in ("true", "1", "yes", "enabled"):
                    # Check three-condition capital readiness before resetting
                    try:
                        from trading_state_machine import _capital_readiness_gate
                    except ImportError:
                        try:
                            from bot.trading_state_machine import _capital_readiness_gate  # type: ignore[import]
                        except ImportError:
                            _capital_readiness_gate = None  # type: ignore[assignment]

                    cap_ready, cap_reason = (
                        _capital_readiness_gate()
                        if _capital_readiness_gate is not None
                        else (True, "gate unavailable — skipping")
                    )
                    if not cap_ready:
                        logger.warning(
                            "SelfHealingStartup: EMERGENCY_STOP + LIVE_CAPITAL_VERIFIED=true "
                            "but capital readiness gate not satisfied: %s — "
                            "leaving in EMERGENCY_STOP until capital is ready",
                            cap_reason,
                        )
                        return
                    logger.warning(
                        "SelfHealingStartup: state machine is EMERGENCY_STOP + "
                        "LIVE_CAPITAL_VERIFIED=true + capital ready — auto-resetting to OFF"
                    )
                    sm.transition_to(
                        TradingState.OFF,
                        "Auto-reset by SelfHealingStartup: LIVE_CAPITAL_VERIFIED=true, "
                        "capital readiness confirmed, "
                        "EMERGENCY_STOP was set by a prior test trigger",
                    )
                    sm.maybe_auto_activate()
                else:
                    logger.warning(
                        "SelfHealingStartup: state machine is EMERGENCY_STOP but "
                        "LIVE_CAPITAL_VERIFIED is not true — leaving in EMERGENCY_STOP. "
                        "Set LIVE_CAPITAL_VERIFIED=true and run scripts/reset_state_machine.py"
                    )
            elif current == TradingState.OFF:
                # HARD SAFETY: ensure system cannot remain OFF indefinitely post-bootstrap.
                # If the full bootstrap sequence has already completed and the state machine
                # is still OFF, force an activation tick unconditionally.  This covers race
                # windows where CA becomes ready between the post-connection loop and here.
                if getattr(self, "_bootstrap_complete", False):
                    logger.warning("[STATE] OFF after bootstrap complete — forcing activation tick")
                    sm.maybe_auto_activate()
                    return
                # Only call maybe_auto_activate() when CapitalAuthority confirms it is ready.
                # This is deterministic, idempotent-safe, and fixes the
                # "ready but not activating" condition by guaranteeing the call is
                # made exactly when the CA gate will pass (not before, not never).
                # Logs a hard diagnostic when CA is not ready so this condition is never silent.
                _ca_is_ready = not _CA_AVAILABLE  # proceed when CA module absent
                if _CA_AVAILABLE and _get_capital_authority is not None:
                    try:
                        _ca = _get_capital_authority()
                        _ca_is_ready = _ca.is_ready()
                        if not _ca_is_ready:
                            _broker_keys: list[str] = []
                            if _MABM_AVAILABLE and _mabm is not None:
                                try:
                                    _broker_keys = list(
                                        getattr(_mabm, "platform_brokers", {}).keys()
                                    )
                                except Exception:
                                    pass
                            logger.critical(
                                "EXECUTION BLOCKED: CA_READY=%s, is_hydrated=%s, brokers=%s — "
                                "ensure brokers are registered and CA is refreshed before "
                                "maybe_auto_activate()",
                                _ca.is_ready(),
                                _ca.is_hydrated,
                                _broker_keys,
                            )
                    except Exception:
                        _ca_is_ready = False  # CA check failed — block activation
                # CA module unavailable — attempt activation without the guard
                # (graceful degradation for deployments without CapitalAuthority)
                if _ca_is_ready:
                    sm.maybe_auto_activate()
            else:
                logger.info(
                    "SelfHealingStartup: state machine is %s — no reset needed",
                    current.value,
                )
        except Exception as exc:
            logger.warning("SelfHealingStartup: state machine step failed (%s)", exc)

    def _is_live_active(self) -> bool:
        """Return True if the trading state machine has reached LIVE_ACTIVE."""
        if not _STATE_MACHINE_AVAILABLE or get_state_machine is None:
            return False
        try:
            return get_state_machine().get_current_state() == TradingState.LIVE_ACTIVE
        except Exception:
            return False

    def _is_ca_ready(self) -> bool:
        """Return True when CapitalAuthority holds at least one usable broker balance."""
        if not _CA_AVAILABLE or _get_capital_authority is None:
            return False
        try:
            return _get_capital_authority().is_ready()
        except Exception:
            return False

    def _ca_watchdog_fn(self) -> bool:
        """Watchdog probe: True = CA healthy.  On failure, re-run the state machine.

        Called periodically by :class:`PreHaltAlertEngine`.  When CA is not
        ready the watchdog fires ``_step_state_machine()`` so the bot recovers
        from a post-startup stall without requiring a manual restart.
        """
        ready = self._is_ca_ready() or self._is_live_active()
        if not ready:
            logger.warning(
                "SelfHealingStartup: CA watchdog detected stale/unready CA "
                "— re-running state machine for self-heal"
            )
            self._step_state_machine()
        return ready

    def _log_nonce_report(self, report: NoncePoisonReport) -> None:
        """Log the nonce poison report at an appropriate level."""
        sev_map = {
            NonceSeverity.CLEAN:    logger.info,
            NonceSeverity.WARN:     logger.warning,
            NonceSeverity.PROBE:    logger.warning,
            NonceSeverity.DEEP:     logger.error,
            NonceSeverity.CEILING:  logger.critical,
            NonceSeverity.CRITICAL: logger.critical,
        }
        log_fn = sev_map.get(report.severity, logger.warning)
        log_fn(
            "NoncePoisonDetector: severity=%s recommended_tier=%s — %s",
            report.severity.value,
            report.recommended_tier.value,
            "; ".join(report.details),
        )


# ---------------------------------------------------------------------------
# Module-level convenience
# ---------------------------------------------------------------------------

def get_self_healing_startup(config: Optional[StartupConfig] = None) -> SelfHealingStartup:
    """Return a new :class:`SelfHealingStartup` instance with the given config."""
    return SelfHealingStartup(config)


def force_post_init_state_machine_step() -> None:
    """Module-level helper: force an unconditional trading-state-machine step.

    Intended to be called from ``bot.py`` (and similar entry points) immediately
    after ``INIT_LOCK_ACQUIRED → bootstrap complete`` so the activation check
    runs once the full bootstrap sequence is truly finished — not only during the
    early init loop inside :meth:`SelfHealingStartup.run`.

    Errors are logged as warnings and never re-raised so that a failed state
    machine step never aborts an otherwise healthy supervisor loop.
    """
    try:
        SelfHealingStartup().step_state_machine()
    except Exception as exc:
        logger.warning(
            "force_post_init_state_machine_step: state machine step failed (%s: %s)",
            type(exc).__name__, exc,
        )


__all__ = [
    "StartupConfig",
    "StartupResult",
    "NoncePoisonDetector",
    "NoncePoisonReport",
    "NonceSeverity",
    "CeilingJumpEscalator",
    "EscalationResult",
    "EscalationTier",
    "BrokerFallbackController",
    "PreHaltAlertEngine",
    "SelfHealingStartup",
    "get_self_healing_startup",
    "force_post_init_state_machine_step",
]
