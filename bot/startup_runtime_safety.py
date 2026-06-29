"""Startup-time safety normalisation for live runtime flags."""

from __future__ import annotations

from collections.abc import MutableMapping
import logging
import os
import sys
import threading
import time

TRUTHY_ENV_VALUES = {"1", "true", "yes", "on", "enabled"}
LIVE_BYPASS_FLAGS = (
    "NIJA_UNSAFE_BYPASS_DISTRIBUTED_LOCK",
    "NIJA_DISABLE_WRITER_LOCK",
    "NIJA_FORCE_ACTIVATION",
    "NIJA_SKIP_STARTUP_PHASE_GATE",
)
REDIS_LOCK_EMERGENCY_FLAGS = (
    "NIJA_ALLOW_LOCAL_WRITER_LOCK_FALLBACK",
    "NIJA_FORCE_LOCAL_WRITER_LOCK_FALLBACK",
    "NIJA_ALLOW_DEGRADED_WRITER_AUTHORITY",
    "NIJA_ALLOW_REDIS_DEGRADED",
    "NIJA_EMERGENCY_LOCAL_FALLBACK_ACTIVE",
)

logger = logging.getLogger("nija.startup_runtime_safety")
_POSITION_SYNC_AUTOWIRE_STARTED = False
_POSITION_SYNC_AUTOWIRE_LOCK = threading.Lock()
_RUNTIME_CORE_LOOP_PATCH_STARTED = False
_RUNTIME_CORE_LOOP_PATCH_LOCK = threading.Lock()


def env_truthy(value: str | None) -> bool:
    """Return ``True`` when *value* represents an enabled environment flag."""

    return str(value or "").strip().lower() in TRUTHY_ENV_VALUES


def live_mode_enabled(env: MutableMapping[str, str]) -> bool:
    """Return ``True`` when the runtime should be treated as live mode."""

    return not env_truthy(env.get("DRY_RUN_MODE")) and not env_truthy(env.get("PAPER_MODE"))


def _redis_lock_emergency_enabled(env: MutableMapping[str, str]) -> bool:
    return any(env_truthy(env.get(flag)) for flag in REDIS_LOCK_EMERGENCY_FLAGS)


def _apply_redis_lock_emergency_fallback(env: MutableMapping[str, str], notes: list[str]) -> None:
    """Respect explicit operator emergency fallback flags for stale Redis locks.

    start.sh may clear NIJA_UNSAFE_BYPASS_DISTRIBUTED_LOCK in live mode unless
    NIJA_CONFIRM_BYPASS_RISKS is set.  When the operator has explicitly enabled
    the safer emergency/degraded fallback flags, restore the effective runtime
    behavior here before bot.py attempts the distributed writer lock.  This keeps
    the service from crash-looping on stale Redis locks while still requiring an
    explicit env flag to leave strict single-writer mode.
    """
    if not _redis_lock_emergency_enabled(env):
        return

    env["NIJA_CONFIRM_BYPASS_RISKS"] = "true"
    env["NIJA_UNSAFE_BYPASS_DISTRIBUTED_LOCK"] = "true"
    env["NIJA_DISABLE_WRITER_LOCK"] = "true"
    env["NIJA_STRICT_REDIS_LEASE"] = "0"
    env["NIJA_REQUIRE_DISTRIBUTED_LOCK"] = "false"
    env["NIJA_STRICT_WRITER_LOCK"] = "false"
    env["NIJA_FAIL_CLOSED_EXIT_ON_UNREACHABLE_REDIS"] = "false"
    env["NIJA_FAIL_CLOSED_RETRY_ON_LOCK_FAILURE"] = "false"
    env["NIJA_FAIL_CLOSED_MAX_RETRY_ATTEMPTS"] = "0"
    env["NIJA_RUNTIME_DEGRADED_MODE"] = "true"
    env["NIJA_ALLOW_DEGRADED_WRITER_AUTHORITY"] = "true"
    env["NIJA_ALLOW_LOCAL_WRITER_LOCK_FALLBACK"] = "true"
    notes.append("enabled:REDIS_LOCK_EMERGENCY_FALLBACK")


def _invoke_position_sync(strategy, source: str) -> None:
    """Invoke startup position sync on *strategy* exactly once."""
    if getattr(strategy, "_startup_position_sync_done", False):
        return
    setattr(strategy, "_startup_position_sync_done", True)
    try:
        try:
            from bot.startup_position_sync import sync_exchange_positions_on_startup
        except ImportError:
            from startup_position_sync import sync_exchange_positions_on_startup  # type: ignore[import]
        logger.warning("EXCHANGE_POSITION_SYNC invocation starting source=%s", source)
        adopted = sync_exchange_positions_on_startup(strategy)
        logger.warning("EXCHANGE_POSITION_SYNC invocation complete adopted=%s source=%s", adopted, source)
    except Exception as exc:
        logger.exception("EXCHANGE_POSITION_SYNC invocation failed source=%s error=%s", source, exc)


def _patch_trading_strategy_class(cls) -> bool:
    """Wrap *cls.__init__* to trigger position sync after construction."""
    original_init = getattr(cls, "__init__", None)
    if original_init is None:
        return False
    if getattr(original_init, "_nija_position_sync_wrapped", False):
        return True

    def _init_with_position_sync(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        _invoke_position_sync(self, "TradingStrategy.__init__")

    _init_with_position_sync._nija_position_sync_wrapped = True  # type: ignore[attr-defined]
    cls.__init__ = _init_with_position_sync
    logger.warning("EXCHANGE_POSITION_SYNC TradingStrategy.__init__ patched from startup_runtime_safety")
    return True


def _broker_tracker_position_count(broker) -> int | None:
    tracker = getattr(broker, "position_tracker", None)
    if tracker is None:
        return None
    getter = getattr(tracker, "get_all_positions", None)
    if not callable(getter):
        return None
    try:
        positions = getter() or []
        if isinstance(positions, dict):
            return len(positions)
        if isinstance(positions, (list, tuple, set)):
            return len(positions)
    except Exception as exc:
        logger.debug("BROKER_SLOT_SCOPE tracker count failed: %s", exc)
    return None


def _broker_name_for_log(broker) -> str:
    if broker is None:
        return "none"
    broker_type = getattr(broker, "broker_type", None)
    value = getattr(broker_type, "value", None)
    if value:
        return str(value).lower()
    return type(broker).__name__.replace("Broker", "").lower()


def _patch_core_loop_class(cls) -> bool:
    original_run_scan_phase = getattr(cls, "run_scan_phase", None)
    if original_run_scan_phase is None:
        return False
    if getattr(original_run_scan_phase, "_nija_broker_slot_scoped", False):
        return True

    def _run_scan_phase_broker_scoped(self, *args, **kwargs):
        broker = kwargs.get("broker") if "broker" in kwargs else (args[0] if args else None)
        broker_count = _broker_tracker_position_count(broker)
        if broker_count is not None:
            original_count = kwargs.get("open_positions_count")
            if "open_positions_count" in kwargs:
                kwargs["open_positions_count"] = broker_count
            elif len(args) >= 4:
                args = list(args)
                original_count = args[3]
                args[3] = broker_count
                args = tuple(args)
            else:
                kwargs["open_positions_count"] = broker_count
            logger.warning(
                "BROKER_SLOT_SCOPE active broker=%s original_open=%s broker_open=%s max_positions=%s",
                _broker_name_for_log(broker),
                original_count,
                broker_count,
                getattr(self, "max_positions", None),
            )
        else:
            logger.info(
                "BROKER_SLOT_SCOPE fallback_global_count broker=%s open_positions_count=%s",
                _broker_name_for_log(broker),
                kwargs.get("open_positions_count", args[3] if len(args) >= 4 else None),
            )

        started_at = time.monotonic()
        result = original_run_scan_phase(self, *args, **kwargs)

        try:
            scored = int(getattr(result, "symbols_scored", 0) or 0)
            entered = int(getattr(result, "entries_taken", 0) or 0)
            blocked = int(getattr(result, "entries_blocked", 0) or 0)
            exited = int(getattr(result, "exits_taken", 0) or 0)
            veto_counts = getattr(self, "veto_reason_counts", {}) or {}
            reject_counts = getattr(self, "reject_reason_counts", {}) or {}
            top_veto = max(veto_counts.items(), key=lambda kv: kv[1])[0] if veto_counts else "none"
            top_reject = max(reject_counts.items(), key=lambda kv: kv[1])[0] if reject_counts else "none"
            if entered > 0:
                status = "ORDER_PATH_ACTIVE"
                reason = "entries_taken"
            elif blocked > 0:
                status = "ENTRY_BLOCKED"
                reason = top_reject if top_reject != "none" else "blocked_candidates"
            elif scored > 0:
                status = "NO_ENTRY_FROM_SCORED_SYMBOLS"
                reason = top_reject if top_reject != "none" else top_veto
            else:
                status = "NO_SCORABLE_SIGNAL"
                reason = top_veto if top_veto != "none" else "market_data_or_filters"
            logger.critical(
                "ORDER_ADMISSION_SUMMARY broker=%s status=%s scored=%d entered=%d blocked=%d exited=%d "
                "top_veto=%s top_reject=%s duration_ms=%d",
                _broker_name_for_log(broker),
                status,
                scored,
                entered,
                blocked,
                exited,
                top_veto,
                top_reject,
                int((time.monotonic() - started_at) * 1000),
            )
            print(
                f"[NIJA-PRINT] ORDER_ADMISSION_SUMMARY | broker={_broker_name_for_log(broker)} "
                f"status={status} reason={reason} scored={scored} entered={entered} blocked={blocked} exited={exited}",
                flush=True,
            )
        except Exception as exc:
            logger.debug("ORDER_ADMISSION_SUMMARY failed: %s", exc)

        return result

    _run_scan_phase_broker_scoped._nija_broker_slot_scoped = True  # type: ignore[attr-defined]
    cls.run_scan_phase = _run_scan_phase_broker_scoped
    logger.warning("BROKER_SLOT_SCOPE NijaCoreLoop.run_scan_phase patched from startup_runtime_safety")
    return True


def _install_position_sync_autowire() -> None:
    """Start the background autowire worker thread — at most once per process."""
    global _POSITION_SYNC_AUTOWIRE_STARTED
    if _POSITION_SYNC_AUTOWIRE_STARTED:
        return
    with _POSITION_SYNC_AUTOWIRE_LOCK:
        if _POSITION_SYNC_AUTOWIRE_STARTED:
            return
        _POSITION_SYNC_AUTOWIRE_STARTED = True

        if not env_truthy(os.getenv("NIJA_STARTUP_POSITION_SYNC_ENABLED", "true")):
            logger.warning("EXCHANGE_POSITION_SYNC autowire disabled by NIJA_STARTUP_POSITION_SYNC_ENABLED=false")
            return

        def _worker() -> None:
            deadline = time.monotonic() + float(os.getenv("NIJA_POSITION_SYNC_AUTOWIRE_TIMEOUT_S", "120") or "120")
            logger.warning("EXCHANGE_POSITION_SYNC autowire worker started source=startup_runtime_safety")
            while time.monotonic() < deadline:
                for module_name in ("bot.trading_strategy", "trading_strategy"):
                    module = sys.modules.get(module_name)
                    cls = getattr(module, "TradingStrategy", None) if module is not None else None
                    if cls is not None and _patch_trading_strategy_class(cls):
                        return
                time.sleep(0.25)
            logger.warning("EXCHANGE_POSITION_SYNC autowire timeout: TradingStrategy class was not observed")

        threading.Thread(target=_worker, name="startup-position-sync-autowire", daemon=True).start()


def _install_broker_slot_scope_autowire() -> None:
    """Patch NijaCoreLoop so slot caps are counted per broker account."""
    global _RUNTIME_CORE_LOOP_PATCH_STARTED
    if _RUNTIME_CORE_LOOP_PATCH_STARTED:
        return
    with _RUNTIME_CORE_LOOP_PATCH_LOCK:
        if _RUNTIME_CORE_LOOP_PATCH_STARTED:
            return
        _RUNTIME_CORE_LOOP_PATCH_STARTED = True

        if not env_truthy(os.getenv("NIJA_BROKER_SCOPED_POSITION_CAP", "true")):
            logger.warning("BROKER_SLOT_SCOPE disabled by NIJA_BROKER_SCOPED_POSITION_CAP=false")
            return

        def _worker() -> None:
            deadline = time.monotonic() + float(os.getenv("NIJA_BROKER_SLOT_SCOPE_TIMEOUT_S", "120") or "120")
            logger.warning("BROKER_SLOT_SCOPE autowire worker started source=startup_runtime_safety")
            while time.monotonic() < deadline:
                for module_name in ("bot.nija_core_loop", "nija_core_loop"):
                    module = sys.modules.get(module_name)
                    cls = getattr(module, "NijaCoreLoop", None) if module is not None else None
                    if cls is not None and _patch_core_loop_class(cls):
                        return
                time.sleep(0.25)
            logger.warning("BROKER_SLOT_SCOPE autowire timeout: NijaCoreLoop class was not observed")

        threading.Thread(target=_worker, name="broker-slot-scope-autowire", daemon=True).start()


def normalize_runtime_startup_env(env: MutableMapping[str, str]) -> list[str]:
    """Fail closed by default, but respect explicit Redis-lock emergency recovery flags."""

    _install_position_sync_autowire()
    _install_broker_slot_scope_autowire()

    notes: list[str] = []
    if not live_mode_enabled(env):
        return notes

    _apply_redis_lock_emergency_fallback(env, notes)
    bypass_confirmed = env_truthy(env.get("NIJA_CONFIRM_BYPASS_RISKS"))

    if not bypass_confirmed:
        for flag in LIVE_BYPASS_FLAGS:
            if env_truthy(env.get(flag)):
                env[flag] = "0" if "LOCK" in flag else "false"
                notes.append(f"cleared:{flag}")

    hf_flip_mode = env_truthy(env.get("HF_FLIP_MODE"))
    hf_scalp_mode = env_truthy(env.get("HF_SCALP_MODE"))
    if not hf_flip_mode and not hf_scalp_mode:
        env["HF_SCALP_MODE"] = "1"
        notes.append("enabled:HF_SCALP_MODE")

    env.setdefault("HF_SCALPING_MODE", env.get("HF_SCALP_MODE", "1"))
    env.setdefault("NIJA_BROKER_SCOPED_POSITION_CAP", "true")
    env.setdefault("NIJA_STARTUP_POSITION_SYNC_ENABLED", "true")
    env.setdefault("NIJA_LOG_TRADE_DECISIONS", "true")
    env.setdefault("NIJA_PROFITABILITY_GUARD_ENABLED", "true")

    # Ensure generation mismatch recovery is enabled by default so the bot
    # can self-heal from diverged generation counters without operator intervention.
    if not env_truthy(env.get("NIJA_GENERATION_MISMATCH_RECOVERY_ENABLED")):
        env["NIJA_GENERATION_MISMATCH_RECOVERY_ENABLED"] = "true"
        notes.append("enabled:NIJA_GENERATION_MISMATCH_RECOVERY_ENABLED")

    return notes
