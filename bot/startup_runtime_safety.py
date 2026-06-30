"""Startup-time safety normalisation for live runtime flags."""

from __future__ import annotations

from collections.abc import MutableMapping
import importlib
import logging
import os
import sys
import threading
import time

TRUTHY_ENV_VALUES = {"1", "true", "yes", "on", "enabled", "y"}
REDIS_URL_FLAGS = (
    "NIJA_REDIS_URL",
    "REDIS_URL",
    "REDIS_PRIVATE_URL",
    "REDIS_PUBLIC_URL",
)
LIVE_BYPASS_FLAGS = (
    "NIJA_UNSAFE_BYPASS_DISTRIBUTED_LOCK",
    "NIJA_DISABLE_WRITER_LOCK",
    "NIJA_FORCE_ACTIVATION",
    "NIJA_SKIP_STARTUP_PHASE_GATE",
    "NIJA_CONFIRM_BYPASS_RISKS",
)
REDIS_LOCK_EMERGENCY_FLAGS = (
    "NIJA_ALLOW_LOCAL_WRITER_LOCK_FALLBACK",
    "NIJA_FORCE_LOCAL_WRITER_LOCK_FALLBACK",
    "NIJA_ALLOW_DEGRADED_WRITER_AUTHORITY",
    "NIJA_ALLOW_REDIS_DEGRADED",
    "NIJA_EMERGENCY_LOCAL_FALLBACK_ACTIVE",
)
STRICT_LIVE_REDIS_FLAGS = LIVE_BYPASS_FLAGS + REDIS_LOCK_EMERGENCY_FLAGS
STRICT_LIVE_REDIS_DEFAULTS = {
    "NIJA_REQUIRE_DISTRIBUTED_LOCK": "true",
    "NIJA_STRICT_REDIS_LEASE": "1",
    "NIJA_STRICT_WRITER_LOCK": "true",
    "NIJA_FAIL_CLOSED_EXIT_ON_UNREACHABLE_REDIS": "true",
    "NIJA_FAIL_CLOSED_RETRY_ON_LOCK_FAILURE": "true",
    "NIJA_RUNTIME_DEGRADED_MODE": "false",
}

logger = logging.getLogger("nija.startup_runtime_safety")
_POSITION_SYNC_AUTOWIRE_STARTED = False
_POSITION_SYNC_AUTOWIRE_LOCK = threading.Lock()
_RUNTIME_CORE_LOOP_PATCH_STARTED = False
_RUNTIME_CORE_LOOP_PATCH_LOCK = threading.Lock()
_CAPITAL_GATE_LATCH_PATCH_STARTED = False
_CAPITAL_GATE_LATCH_PATCH_LOCK = threading.Lock()
_OKX_BALANCE_PATCH_STARTED = False
_OKX_BALANCE_PATCH_LOCK = threading.Lock()


def env_truthy(value: str | None) -> bool:
    """Return ``True`` when *value* represents an enabled environment flag."""

    return str(value or "").strip().lower() in TRUTHY_ENV_VALUES


def live_mode_enabled(env: MutableMapping[str, str]) -> bool:
    """Return ``True`` when the runtime should be treated as live mode."""

    return not env_truthy(env.get("DRY_RUN_MODE")) and not env_truthy(env.get("PAPER_MODE"))


def redis_configured(env: MutableMapping[str, str]) -> bool:
    """Return ``True`` when a Redis endpoint is configured for the process."""

    return any(str(env.get(flag, "")).strip() for flag in REDIS_URL_FLAGS)


def _disabled_value_for(flag: str) -> str:
    return "0" if "LOCK" in flag else "false"


def _clear_truthy_flags(env: MutableMapping[str, str], flags: tuple[str, ...], notes: list[str]) -> None:
    for flag in flags:
        if env_truthy(env.get(flag)):
            env[flag] = _disabled_value_for(flag)
            notes.append(f"cleared:{flag}")


def _enforce_strict_live_redis_authority(env: MutableMapping[str, str], notes: list[str]) -> None:
    """For live Redis deployments, make bypass/degraded authority impossible.

    This is intentionally source-level enforcement, not a follow-up cleanup.  The
    previous emergency-fallback branch could re-enable unsafe local writer paths
    after package import sanitization.  In live mode with Redis configured, Redis
    lineage and the distributed writer lease are mandatory; fallback flags are
    stripped before any runtime safety initialization can observe them.
    """

    _clear_truthy_flags(env, STRICT_LIVE_REDIS_FLAGS, notes)
    for flag, value in STRICT_LIVE_REDIS_DEFAULTS.items():
        if env.get(flag) != value:
            env[flag] = value
            notes.append(f"set:{flag}={value}")
    try:
        attempts = int(float(env.get("NIJA_FAIL_CLOSED_MAX_RETRY_ATTEMPTS", "0") or "0"))
    except Exception:
        attempts = 0
    if attempts <= 0:
        env["NIJA_FAIL_CLOSED_MAX_RETRY_ATTEMPTS"] = "12"
        notes.append("set:NIJA_FAIL_CLOSED_MAX_RETRY_ATTEMPTS=12")


def _redis_lock_emergency_enabled(env: MutableMapping[str, str]) -> bool:
    return any(env_truthy(env.get(flag)) for flag in REDIS_LOCK_EMERGENCY_FLAGS)


def _apply_redis_lock_emergency_fallback(env: MutableMapping[str, str], notes: list[str]) -> None:
    """Handle legacy emergency fallback flags without creating a live Redis race."""

    if not _redis_lock_emergency_enabled(env):
        return

    if redis_configured(env):
        notes.append("blocked:REDIS_LOCK_EMERGENCY_FALLBACK_LIVE_REDIS")
        _enforce_strict_live_redis_authority(env, notes)
        return
    # Non-Redis live recovery remains explicit/operator-confirmed.  This path is
    # kept only for deployments that truly have no Redis endpoint configured.
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


def _resolve_class(module_names: tuple[str, ...], class_name: str):
    """Resolve a runtime class from loaded modules, then by safe import.

    The previous autowire workers only inspected ``sys.modules``.  In Railway
    starts where ``startup_runtime_safety`` ran before the core modules loaded,
    this produced false timeouts even though the classes existed on disk.  This
    helper preserves the cheap loaded-module fast path, then imports the target
    module if it has not appeared yet.
    """

    for module_name in module_names:
        module = sys.modules.get(module_name)
        cls = getattr(module, class_name, None) if module is not None else None
        if cls is not None:
            return cls

    for module_name in module_names:
        try:
            module = importlib.import_module(module_name)
        except Exception as exc:
            logger.debug(
                "runtime class import probe failed module=%s class=%s error=%s",
                module_name,
                class_name,
                exc,
            )
            continue
        cls = getattr(module, class_name, None)
        if cls is not None:
            return cls
    return None


def _invoke_position_sync_once(strategy, source: str) -> int:
    try:
        try:
            from bot.startup_position_sync import sync_exchange_positions_on_startup
        except ImportError:
            from startup_position_sync import sync_exchange_positions_on_startup  # type: ignore[import]
        logger.warning("EXCHANGE_POSITION_SYNC invocation starting source=%s", source)
        adopted = sync_exchange_positions_on_startup(strategy)
        logger.warning("EXCHANGE_POSITION_SYNC invocation complete adopted=%s source=%s", adopted, source)
        return int(adopted or 0)
    except Exception as exc:
        logger.exception("EXCHANGE_POSITION_SYNC invocation failed source=%s error=%s", source, exc)
        return 0


def _invoke_position_sync(strategy, source: str) -> None:
    """Invoke startup position sync and keep retrying until hydrated brokers are visible.

    TradingStrategy.__init__ can run before platform/user brokers finish connecting.  The
    previous implementation marked sync as done immediately, so early empty attempts
    permanently suppressed adoption.  This method now starts a bounded retry worker and
    only marks completion after connected brokers have produced tracked/adopted positions
    or after the retry window expires with explicit diagnostics.
    """
    if getattr(strategy, "_startup_position_sync_retry_started", False):
        return
    setattr(strategy, "_startup_position_sync_retry_started", True)

    def _tracked_total() -> int:
        total = 0
        seen: set[int] = set()
        for attr in ("multi_account_manager", "broker_manager"):
            owner = getattr(strategy, attr, None)
            if owner is None:
                continue
            containers = []
            if hasattr(owner, "platform_brokers"):
                containers.append(getattr(owner, "platform_brokers", {}) or {})
            if hasattr(owner, "user_brokers"):
                for nested in (getattr(owner, "user_brokers", {}) or {}).values():
                    containers.append(nested or {})
            if hasattr(owner, "brokers"):
                containers.append(getattr(owner, "brokers", {}) or {})
            for container in containers:
                for broker in (container or {}).values():
                    tracker = getattr(broker, "position_tracker", None)
                    if tracker is not None and id(tracker) not in seen:
                        seen.add(id(tracker))
                        getter = getattr(tracker, "get_all_positions", None)
                        if callable(getter):
                            try:
                                total += len(getter() or [])
                            except Exception:
                                pass
        return total

    def _worker() -> None:
        delay = float(os.getenv("NIJA_POSITION_SYNC_RETRY_INTERVAL_S", "3") or "3")
        timeout = float(os.getenv("NIJA_POSITION_SYNC_RETRY_TIMEOUT_S", "90") or "90")
        deadline = time.monotonic() + timeout
        attempt = 0
        while time.monotonic() <= deadline:
            attempt += 1
            setattr(strategy, "_startup_position_sync_done", False)
            logger.warning("EXCHANGE_POSITION_SYNC retry_attempt=%d source=%s", attempt, source)
            adopted = _invoke_position_sync_once(strategy, f"{source}:retry:{attempt}")
            tracked = _tracked_total()
            if adopted > 0 or tracked > 0:
                setattr(strategy, "_startup_position_sync_done", True)
                logger.warning(
                    "EXCHANGE_POSITION_SYNC retry_success attempt=%d adopted=%d tracked_total=%d",
                    attempt,
                    adopted,
                    tracked,
                )
                return
            time.sleep(delay)
        logger.warning(
            "EXCHANGE_POSITION_SYNC retry_exhausted source=%s tracked_total=%d timeout_s=%.1f — no exchange positions adopted",
            source,
            _tracked_total(),
            timeout,
        )

    threading.Thread(target=_worker, name="startup-position-sync-retry", daemon=True).start()


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
        broker_name = _broker_name_for_log(broker)
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
                broker_name,
                original_count,
                broker_count,
                getattr(self, "max_positions", None),
            )
        else:
            logger.info(
                "BROKER_SLOT_SCOPE fallback_global_count broker=%s open_positions_count=%s",
                broker_name,
                kwargs.get("open_positions_count", args[3] if len(args) >= 4 else None),
            )

        started_at = time.monotonic()
        cycle_id = int(getattr(self, "_nija_trade_loop_heartbeat_cycle", 0) or 0) + 1
        setattr(self, "_nija_trade_loop_heartbeat_cycle", cycle_id)
        logger.critical(
            "TRADE_LOOP_HEARTBEAT cycle=%d phase=scan_start broker=%s open_positions=%s max_positions=%s",
            cycle_id,
            broker_name,
            kwargs.get("open_positions_count", args[3] if len(args) >= 4 else None),
            getattr(self, "max_positions", None),
        )

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
            duration_ms = int((time.monotonic() - started_at) * 1000)
            logger.critical(
                "TRADE_LOOP_HEARTBEAT cycle=%d phase=scan_complete broker=%s status=%s reason=%s "
                "scored=%d entered=%d blocked=%d exited=%d top_veto=%s top_reject=%s duration_ms=%d",
                cycle_id,
                broker_name,
                status,
                reason,
                scored,
                entered,
                blocked,
                exited,
                top_veto,
                top_reject,
                duration_ms,
            )
            logger.critical(
                "ORDER_ADMISSION_SUMMARY broker=%s status=%s scored=%d entered=%d blocked=%d exited=%d "
                "top_veto=%s top_reject=%s duration_ms=%d",
                broker_name,
                status,
                scored,
                entered,
                blocked,
                exited,
                top_veto,
                top_reject,
                duration_ms,
            )
            print(
                f"[NIJA-PRINT] ORDER_ADMISSION_SUMMARY | broker={broker_name} "
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


def _patch_capital_authority_class(cls) -> bool:
    """Add unambiguous first-snapshot latch telemetry after publish_snapshot()."""
    original_publish = getattr(cls, "publish_snapshot", None)
    if original_publish is None:
        return False
    if getattr(original_publish, "_nija_first_snapshot_latch_wrapped", False):
        return True

    def _publish_snapshot_with_latch_log(self, snapshot, writer_id: str):
        accepted_by_publish = original_publish(self, snapshot, writer_id)
        try:
            real_capital = float(getattr(snapshot, "real_capital", 0.0) or 0.0)
            broker_count = int(getattr(snapshot, "broker_count", 0) or 0)
            is_stale = bool(getattr(snapshot, "is_stale", True))
            valid_broker_count = 0
            for value in (getattr(snapshot, "broker_balances", {}) or {}).values():
                try:
                    if float(value or 0.0) > 0.0:
                        valid_broker_count += 1
                except Exception:
                    pass
            conditions_met = bool(
                accepted_by_publish
                and getattr(self, "is_hydrated", False)
                and real_capital > 0.0
                and valid_broker_count > 0
                and not is_stale
            )
            latch = bool(getattr(self, "first_snap_accepted", False))
            logger.info(
                "FIRST_SNAPSHOT_GATE_LATCH accepted_by_publish=%s accepted_conditions=%s "
                "accepted_latched=%s capital=$%.2f broker_count=%d valid_brokers=%d stale=%s",
                accepted_by_publish,
                conditions_met,
                latch,
                real_capital,
                broker_count,
                valid_broker_count,
                is_stale,
            )
        except Exception as exc:
            logger.debug("FIRST_SNAPSHOT_GATE_LATCH log failed: %s", exc)
        return accepted_by_publish

    _publish_snapshot_with_latch_log._nija_first_snapshot_latch_wrapped = True  # type: ignore[attr-defined]
    cls.publish_snapshot = _publish_snapshot_with_latch_log
    logger.warning("FIRST_SNAPSHOT_GATE CapitalAuthority.publish_snapshot latch telemetry patched")
    return True


def _patch_capital_csm_class(cls) -> bool:
    """Add unambiguous first-snapshot latch telemetry after CSM ingest_snapshot()."""
    original_ingest = getattr(cls, "ingest_snapshot", None)
    if original_ingest is None:
        return False
    if getattr(original_ingest, "_nija_csm_first_snapshot_latch_wrapped", False):
        return True

    def _ingest_snapshot_with_latch_log(self, snapshot):
        state = original_ingest(self, snapshot)
        try:
            real_capital = float(getattr(snapshot, "real_capital", 0.0) or 0.0)
            broker_count = int(getattr(snapshot, "broker_count", 0) or 0)
            is_stale = bool(getattr(snapshot, "is_stale", True))
            latch = bool(getattr(self, "first_snap_accepted", False))
            logger.info(
                "FIRST_SNAPSHOT_GATE_CSM_LATCH accepted_latched=%s state=%s capital=$%.2f broker_count=%d stale=%s",
                latch,
                getattr(state, "value", state),
                real_capital,
                broker_count,
                is_stale,
            )
        except Exception as exc:
            logger.debug("FIRST_SNAPSHOT_GATE_CSM_LATCH log failed: %s", exc)
        return state

    _ingest_snapshot_with_latch_log._nija_csm_first_snapshot_latch_wrapped = True  # type: ignore[attr-defined]
    cls.ingest_snapshot = _ingest_snapshot_with_latch_log
    logger.warning("FIRST_SNAPSHOT_GATE CapitalCSMv2.ingest_snapshot latch telemetry patched")
    return True


def _okx_seed_balance_payload(manager) -> None:
    """Force OKX's last-known balance to match the live balance after connect()."""
    try:
        try:
            from bot.broker_manager import BrokerType
        except ImportError:
            from broker_manager import BrokerType  # type: ignore[import]
        broker = (getattr(manager, "_platform_brokers", {}) or {}).get(BrokerType.OKX)
        if broker is None:
            return
        raw = broker.get_account_balance()
        if isinstance(raw, dict):
            balance = float(
                raw.get("trading_balance")
                or raw.get("total_funds")
                or raw.get("usd")
                or raw.get("cash")
                or 0.0
            )
        else:
            balance = float(raw or 0.0)
        setattr(broker, "_last_known_balance", balance)
        if hasattr(broker, "_last_balance_payload_for_capital"):
            setattr(broker, "_last_balance_payload_for_capital", raw)
        logger.info(
            "OKX_CAPITAL_READY_BALANCE_SYNC total=$%.2f raw_type=%s",
            balance,
            type(raw).__name__,
        )
    except Exception as exc:
        logger.debug("OKX_CAPITAL_READY_BALANCE_SYNC failed: %s", exc)


def _patch_mabm_class(cls) -> bool:
    """Patch platform-ready handling so OKX capital logs use the hydrated balance."""
    original_mark_connected = getattr(cls, "_mark_platform_connected", None)
    if original_mark_connected is None:
        return False
    if getattr(original_mark_connected, "_nija_okx_balance_sync_wrapped", False):
        return True

    def _mark_platform_connected_with_okx_sync(self, broker_type, *args, **kwargs):
        result = original_mark_connected(self, broker_type, *args, **kwargs)
        try:
            broker_value = getattr(broker_type, "value", str(broker_type)).lower()
            if broker_value == "okx":
                _okx_seed_balance_payload(self)
        except Exception as exc:
            logger.debug("OKX_CAPITAL_READY_BALANCE_SYNC wrapper failed: %s", exc)
        return result

    _mark_platform_connected_with_okx_sync._nija_okx_balance_sync_wrapped = True  # type: ignore[attr-defined]
    cls._mark_platform_connected = _mark_platform_connected_with_okx_sync
    logger.warning("OKX capital-ready balance propagation patched from startup_runtime_safety")
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
                cls = _resolve_class(("bot.trading_strategy", "trading_strategy"), "TradingStrategy")
                if cls is not None and _patch_trading_strategy_class(cls):
                    return
                time.sleep(0.25)
            logger.error("EXCHANGE_POSITION_SYNC autowire timeout: TradingStrategy class was not observed or importable")

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
                cls = _resolve_class(("bot.nija_core_loop", "nija_core_loop"), "NijaCoreLoop")
                if cls is not None and _patch_core_loop_class(cls):
                    return
                time.sleep(0.25)
            logger.error("BROKER_SLOT_SCOPE autowire timeout: NijaCoreLoop class was not observed or importable")

        threading.Thread(target=_worker, name="broker-slot-scope-autowire", daemon=True).start()


def _install_capital_gate_latch_autowire() -> None:
    """Patch capital gate telemetry classes once available."""
    global _CAPITAL_GATE_LATCH_PATCH_STARTED
    if _CAPITAL_GATE_LATCH_PATCH_STARTED:
        return
    with _CAPITAL_GATE_LATCH_PATCH_LOCK:
        if _CAPITAL_GATE_LATCH_PATCH_STARTED:
            return
        _CAPITAL_GATE_LATCH_PATCH_STARTED = True

        def _worker() -> None:
            deadline = time.monotonic() + float(os.getenv("NIJA_CAPITAL_GATE_PATCH_TIMEOUT_S", "120") or "120")
            patched_authority = False
            patched_csm = False
            logger.warning("FIRST_SNAPSHOT_GATE latch autowire worker started source=startup_runtime_safety")
            while time.monotonic() < deadline:
                if not patched_authority:
                    cls = _resolve_class(("bot.capital_authority", "capital_authority"), "CapitalAuthority")
                    if cls is not None:
                        patched_authority = _patch_capital_authority_class(cls)
                if not patched_csm:
                    cls = _resolve_class(("bot.capital_csm_v2", "capital_csm_v2"), "CapitalCSMv2")
                    if cls is not None:
                        patched_csm = _patch_capital_csm_class(cls)
                if patched_authority and patched_csm:
                    return
                time.sleep(0.25)
            if not patched_authority:
                logger.error("FIRST_SNAPSHOT_GATE latch autowire timeout: CapitalAuthority class was not observed or importable")
            if not patched_csm:
                logger.error("FIRST_SNAPSHOT_GATE latch autowire timeout: CapitalCSMv2 class was not observed or importable")

        threading.Thread(target=_worker, name="capital-gate-latch-autowire", daemon=True).start()


def _install_okx_balance_autowire() -> None:
    """Patch MABM so OKX's capital-ready state cannot log a stale $0.00 total."""
    global _OKX_BALANCE_PATCH_STARTED
    if _OKX_BALANCE_PATCH_STARTED:
        return
    with _OKX_BALANCE_PATCH_LOCK:
        if _OKX_BALANCE_PATCH_STARTED:
            return
        _OKX_BALANCE_PATCH_STARTED = True

        def _worker() -> None:
            deadline = time.monotonic() + float(os.getenv("NIJA_OKX_BALANCE_PATCH_TIMEOUT_S", "120") or "120")
            logger.warning("OKX capital-ready balance autowire worker started source=startup_runtime_safety")
            while time.monotonic() < deadline:
                cls = _resolve_class(
                    ("bot.multi_account_broker_manager", "multi_account_broker_manager"),
                    "MultiAccountBrokerManager",
                )
                if cls is not None and _patch_mabm_class(cls):
                    return
                time.sleep(0.25)
            logger.error("OKX capital-ready balance autowire timeout: MultiAccountBrokerManager class was not observed or importable")

        threading.Thread(target=_worker, name="okx-balance-autowire", daemon=True).start()


def normalize_runtime_startup_env(env: MutableMapping[str, str]) -> list[str]:
    """Normalize startup flags before live execution authority is initialized."""

    _install_position_sync_autowire()
    _install_broker_slot_scope_autowire()
    _install_capital_gate_latch_autowire()
    _install_okx_balance_autowire()

    notes: list[str] = []
    if not live_mode_enabled(env):
        return notes

    if redis_configured(env):
        _enforce_strict_live_redis_authority(env, notes)
    else:
        _apply_redis_lock_emergency_fallback(env, notes)
        bypass_confirmed = env_truthy(env.get("NIJA_CONFIRM_BYPASS_RISKS"))
        if not bypass_confirmed:
            _clear_truthy_flags(env, LIVE_BYPASS_FLAGS, notes)

    # FORCE_TRADE must not bypass authority/activation gates in live mode.
    # The trading state machine can still activate when the real gates pass.
    if env_truthy(env.get("FORCE_TRADE")):
        env["FORCE_TRADE"] = "false"
        notes.append("cleared:FORCE_TRADE")

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
    env.setdefault("NIJA_TRADE_LOOP_HEARTBEAT_REQUIRED", "true")

    # Ensure generation mismatch recovery is enabled by default so the bot
    # can self-heal from diverged generation counters without operator intervention.
    if not env_truthy(env.get("NIJA_GENERATION_MISMATCH_RECOVERY_ENABLED")):
        env["NIJA_GENERATION_MISMATCH_RECOVERY_ENABLED"] = "true"
        notes.append("enabled:NIJA_GENERATION_MISMATCH_RECOVERY_ENABLED")

    return notes
