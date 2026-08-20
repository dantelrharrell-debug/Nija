"""Converge runtime capital refresh ownership and bounded publication liveness.

Production after v165 exposed two remaining runtime contradictions:

* a standby NIJA process could run the proactive v137 capital-publication monitor
  even though another process held the canonical Redis writer lease.  The standby
  correctly could not dispatch trades, but duplicate authenticated balance work
  could still contend with the active writer's broker/nonce traffic;
* v165 reserved headroom for the legacy 80-second total coordinator deadline.
  That starts proactive refreshes almost immediately inside a 90-second capital
  TTL and permits long-lived refresh generations to accumulate.  The proactive
  publication path does not need the same synchronous broker wait as bootstrap:
  bounded broker workers may continue asynchronously while fresh observations
  remain subject to the existing v35/v78 freshness rules.

v166 repairs those paths without weakening capital truth:

* in live mode, v137 proactive refresh scheduling/execution is owned only by the
  process that currently owns the canonical Redis writer lease;
* only ``publication_deadline_v137`` refreshes use a shorter synchronous broker
  fetch budget (30s default) and total coordinator deadline (50s default);
  bootstrap and non-proactive refresh deadlines are unchanged;
* v165 headroom is recomputed from that proactive deadline plus watchdog cadence
  and an immutable-validity margin, producing 70s with current production
  settings instead of 85s;
* when a proactive refresh uses a v35 cached fallback observation, the outgoing
  snapshot ``computed_at`` is capped to the oldest exact fallback observation
  timestamp before CapitalAuthority sees it.  Re-publishing cached data therefore
  cannot manufacture a new 90-second freshness window.

The patch does not fabricate balances, extend freshness/publication expiry,
force LIVE_ACTIVE, clear kill switches, grant writer/nonce authority, alter risk
limits, or bypass execution/order gates.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
import time
from dataclasses import replace
from datetime import datetime, timezone
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.runtime_capital_refresh_ownership_v166")
MARKER = "20260819-runtime-capital-refresh-ownership-v166"
_READY_FLAG = "NIJA_RUNTIME_CAPITAL_REFRESH_OWNERSHIP_V166_READY"
_PATCH_ATTR = "_nija_runtime_capital_refresh_ownership_v166"
_LOCK = threading.RLock()
_CTX = threading.local()
_LAST_STANDBY_LOG_MONO = 0.0
_STANDBY_LOG_LOCK = threading.Lock()
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in _TRUE


def _live_mode() -> bool:
    return bool(
        _truthy(os.environ.get("LIVE_CAPITAL_VERIFIED"))
        and not _truthy(os.environ.get("DRY_RUN_MODE"))
        and not _truthy(os.environ.get("PAPER_MODE"))
    )


def _trigger() -> str:
    return str(getattr(_CTX, "trigger", "") or "").strip().lower()


def _is_proactive_trigger(value: Any = None) -> bool:
    trigger = str(_trigger() if value is None else value or "").strip().lower()
    return trigger.startswith("publication_deadline_v137")


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)) or default)
    except (TypeError, ValueError):
        return float(default)


def _v78() -> Any:
    return importlib.import_module("bot.capital_refresh_live_continuity_v78_patch")


def _v137() -> Any:
    return importlib.import_module("bot.capital_publication_deadline_v137_patch")


def _v142() -> Any:
    return importlib.import_module("bot.capital_publication_liveness_v142_patch")


def _v165() -> Any:
    return importlib.import_module("bot.runtime_capital_publication_scheduling_v165_patch")


def _flow() -> Any:
    return importlib.import_module("bot.capital_flow_state_machine")


def _guard() -> Any:
    return importlib.import_module("bot.capital_refresh_stall_guard_v35")


def _freshness_ttl_seconds() -> float:
    try:
        getter = getattr(_v137(), "_freshness_ttl_seconds", None)
        if callable(getter):
            return max(10.0, float(getter()))
    except Exception:
        pass
    return 90.0


def _proactive_fetch_budget_seconds() -> float:
    """Return the synchronous broker wait used only by proactive publication work."""
    ttl_s = _freshness_ttl_seconds()
    requested = _float_env("NIJA_CAPITAL_PROACTIVE_FETCH_BUDGET_S", 30.0)
    # Keep a large immutable margin for publish/fencing/readiness handoff.
    ceiling = max(10.0, ttl_s - 30.0)
    return max(10.0, min(requested, ceiling))


def _proactive_pipeline_deadline_seconds() -> float:
    ttl_s = _freshness_ttl_seconds()
    fetch_s = _proactive_fetch_budget_seconds()
    post_s = max(
        10.0,
        min(30.0, _float_env("NIJA_CAPITAL_PROACTIVE_POST_FETCH_BUDGET_S", 20.0)),
    )
    # Proactive runtime work must terminate with at least ten seconds remaining
    # inside canonical freshness even if an operator requests a larger value.
    ceiling = max(20.0, ttl_s - 10.0)
    requested = fetch_s + post_s
    return max(20.0, min(requested, ceiling))


def _watchdog_cadence_seconds(manager: Any) -> float:
    try:
        value = float(getattr(manager, "capital_watchdog_interval_s", 10.0) or 10.0)
    except (TypeError, ValueError):
        value = 10.0
    return max(1.0, min(10.0, value))


def _proactive_headroom_seconds(manager: Any) -> float:
    ttl_s = _freshness_ttl_seconds()
    deadline_s = _proactive_pipeline_deadline_seconds()
    cadence_s = _watchdog_cadence_seconds(manager)
    expiry_margin_s = max(
        5.0,
        min(20.0, _float_env("NIJA_CAPITAL_PROACTIVE_EXPIRY_MARGIN_S", 15.0)),
    )
    # Do not start immediately after every publication.  With current values
    # this returns 70s: refresh begins around snapshot age 20s, leaving enough
    # time for one bounded attempt plus watchdog cadence and a 15s safety margin.
    ceiling = max(10.0, ttl_s - 10.0)
    return max(10.0, min(deadline_s + cadence_s + expiry_margin_s, ceiling))


def _writer_lease_owned() -> bool:
    """Return exact process-local canonical Redis writer ownership."""
    try:
        module = importlib.import_module("bot.entrypoint_writer_authority")
        getter = getattr(module, "get_entrypoint_writer_authority", None)
        if not callable(getter):
            return False
        authority = getter()
        value = getattr(authority, "writer_lease_owned", False)
        return bool(value() if callable(value) else value)
    except Exception:
        return False


def _standby_log(reason: str) -> None:
    global _LAST_STANDBY_LOG_MONO
    now = time.monotonic()
    with _STANDBY_LOG_LOCK:
        if now - _LAST_STANDBY_LOG_MONO < 30.0:
            return
        _LAST_STANDBY_LOG_MONO = now
    LOGGER.info(
        "CAPITAL_V166_STANDBY_REFRESH_SUPPRESSED marker=%s reason=%s "
        "writer_lease_owned=false proactive_refresh_started=false trading_fail_closed=true",
        MARKER,
        reason,
    )


def _patch_v137_writer_ownership() -> bool:
    v137 = _v137()
    schedule = getattr(v137, "_runtime_schedule_enabled", None)
    execute = getattr(v137, "_execute_deadline_refresh", None)
    if not callable(schedule) or not callable(execute):
        return False

    if not bool(getattr(schedule, _PATCH_ATTR, False)):
        original_schedule = schedule

        @wraps(original_schedule)
        def runtime_schedule_v166(manager: Any) -> bool:
            if not bool(original_schedule(manager)):
                return False
            if _live_mode() and not _writer_lease_owned():
                _standby_log("runtime_schedule")
                return False
            return True

        setattr(runtime_schedule_v166, _PATCH_ATTR, True)
        setattr(runtime_schedule_v166, "__wrapped__", original_schedule)
        v137._runtime_schedule_enabled = runtime_schedule_v166

    execute = getattr(v137, "_execute_deadline_refresh", None)
    if callable(execute) and not bool(getattr(execute, _PATCH_ATTR, False)):
        original_execute = execute

        @wraps(original_execute)
        def execute_deadline_refresh_v166(
            manager: Any,
            *,
            trigger: str = "publication_deadline_v137",
        ) -> bool:
            if _live_mode() and not _writer_lease_owned():
                _standby_log("deadline_execute")
                return False
            return bool(original_execute(manager, trigger=trigger))

        setattr(execute_deadline_refresh_v166, _PATCH_ATTR, True)
        setattr(execute_deadline_refresh_v166, "__wrapped__", original_execute)
        v137._execute_deadline_refresh = execute_deadline_refresh_v166

    return True


def _set_trigger(value: Any) -> Any:
    previous = getattr(_CTX, "trigger", None)
    _CTX.trigger = str(value or "")
    return previous


def _restore_trigger(previous: Any) -> None:
    if previous is None:
        try:
            delattr(_CTX, "trigger")
        except AttributeError:
            pass
    else:
        _CTX.trigger = previous


def _patch_flow_trigger_context() -> bool:
    flow = _flow()
    cls = getattr(flow, "CapitalRefreshCoordinator", None)
    if not isinstance(cls, type):
        return False

    execute = getattr(cls, "execute_refresh", None)
    pipeline = getattr(cls, "_pipeline", None)
    if not callable(execute) or not callable(pipeline):
        return False

    if not bool(getattr(execute, _PATCH_ATTR, False)):
        original_execute = execute

        @wraps(original_execute)
        def execute_refresh_v166(
            self: Any,
            broker_map: dict[str, Any],
            trigger: str = "coordinator",
            open_exposure_usd: float = 0.0,
        ) -> Any:
            previous = _set_trigger(trigger)
            try:
                return original_execute(
                    self,
                    broker_map=broker_map,
                    trigger=trigger,
                    open_exposure_usd=open_exposure_usd,
                )
            finally:
                _restore_trigger(previous)

        setattr(execute_refresh_v166, _PATCH_ATTR, True)
        setattr(execute_refresh_v166, "__wrapped__", original_execute)
        cls.execute_refresh = execute_refresh_v166

    pipeline = getattr(cls, "_pipeline", None)
    if callable(pipeline) and not bool(getattr(pipeline, _PATCH_ATTR, False)):
        original_pipeline = pipeline

        @wraps(original_pipeline)
        def pipeline_v166(
            self: Any,
            broker_map: dict[str, Any],
            trigger: str,
            open_exposure_usd: float,
        ) -> Any:
            previous = _set_trigger(trigger)
            try:
                return original_pipeline(
                    self,
                    broker_map=broker_map,
                    trigger=trigger,
                    open_exposure_usd=open_exposure_usd,
                )
            finally:
                _restore_trigger(previous)

        setattr(pipeline_v166, _PATCH_ATTR, True)
        setattr(pipeline_v166, "__wrapped__", original_pipeline)
        cls._pipeline = pipeline_v166

    return True


def _patch_proactive_fetch_budget() -> bool:
    v78 = _v78()
    current = getattr(v78, "fetch_budget_seconds", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True
    original = current

    @wraps(original)
    def fetch_budget_v166() -> float:
        base = max(5.0, float(original()))
        if not _is_proactive_trigger():
            return base
        return min(base, _proactive_fetch_budget_seconds())

    setattr(fetch_budget_v166, _PATCH_ATTR, True)
    setattr(fetch_budget_v166, "__wrapped__", original)
    v78.fetch_budget_seconds = fetch_budget_v166
    return True


def _patch_proactive_pipeline_deadline() -> bool:
    v142 = _v142()
    current = getattr(v142, "_runtime_pipeline_deadline_seconds", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True
    original = current

    @wraps(original)
    def pipeline_deadline_v166() -> float:
        base = max(10.0, float(original()))
        if not _is_proactive_trigger():
            return base
        return min(base, _proactive_pipeline_deadline_seconds())

    setattr(pipeline_deadline_v166, _PATCH_ATTR, True)
    setattr(pipeline_deadline_v166, "__wrapped__", original)
    v142._runtime_pipeline_deadline_seconds = pipeline_deadline_v166
    return True


def _patch_v165_headroom_model() -> bool:
    v165 = _v165()

    current_effective = getattr(v165, "_effective_pipeline_deadline_seconds", None)
    current_required = getattr(v165, "_required_headroom_seconds", None)
    if not callable(current_effective) or not callable(current_required):
        return False

    if not bool(getattr(current_effective, _PATCH_ATTR, False)):
        original_effective = current_effective

        @wraps(original_effective)
        def effective_deadline_v166() -> float:
            return _proactive_pipeline_deadline_seconds()

        setattr(effective_deadline_v166, _PATCH_ATTR, True)
        setattr(effective_deadline_v166, "__wrapped__", original_effective)
        v165._effective_pipeline_deadline_seconds = effective_deadline_v166

    current_required = getattr(v165, "_required_headroom_seconds", None)
    if callable(current_required) and not bool(getattr(current_required, _PATCH_ATTR, False)):
        original_required = current_required

        @wraps(original_required)
        def required_headroom_v166(manager: Any) -> float:
            return _proactive_headroom_seconds(manager)

        setattr(required_headroom_v166, _PATCH_ATTR, True)
        setattr(required_headroom_v166, "__wrapped__", original_required)
        v165._required_headroom_seconds = required_headroom_v166

    return True


def _oldest_fallback_observed_epoch(status: dict[str, Any], guard: Any) -> float | None:
    if not bool(status.get("used_fallback")):
        return None
    fallback_brokers = dict(status.get("brokers", {}) or {})
    if not fallback_brokers:
        return None
    observations = getattr(guard, "_OBSERVATIONS", None)
    lock = getattr(guard, "_OBSERVATION_LOCK", None)
    if not isinstance(observations, dict):
        return None

    def _read() -> list[float]:
        epochs: list[float] = []
        for broker_id in fallback_brokers:
            observation = observations.get(str(broker_id).strip().lower())
            try:
                epoch = float(getattr(observation, "observed_epoch", 0.0) or 0.0)
            except (TypeError, ValueError):
                epoch = 0.0
            if epoch > 0.0:
                epochs.append(epoch)
        return epochs

    if lock is None:
        epochs = _read()
    else:
        with lock:
            epochs = _read()
    return min(epochs) if epochs else None


def _cap_snapshot_to_fallback_timestamp(snapshot: Any, guard: Any) -> tuple[Any, bool, float | None]:
    getter = getattr(guard, "current_refresh_fallback_status", None)
    if not callable(getter):
        return snapshot, False, None
    try:
        status = dict(getter(_freshness_ttl_seconds()) or {})
    except Exception:
        return snapshot, False, None
    epoch = _oldest_fallback_observed_epoch(status, guard)
    if epoch is None:
        return snapshot, False, None
    computed_at = getattr(snapshot, "computed_at", None)
    if not isinstance(computed_at, datetime):
        return snapshot, False, epoch
    if computed_at.tzinfo is None:
        computed_at = computed_at.replace(tzinfo=timezone.utc)
    capped = datetime.fromtimestamp(epoch, timezone.utc)
    if capped >= computed_at:
        return snapshot, False, epoch
    try:
        return replace(snapshot, computed_at=capped), True, epoch
    except Exception:
        return snapshot, False, epoch


def _patch_fallback_publication_timestamp() -> bool:
    ca = importlib.import_module("bot.capital_authority")
    cls = getattr(ca, "CapitalAuthority", None)
    if not isinstance(cls, type):
        return False
    current = getattr(cls, "publish_snapshot", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True
    original = current

    @wraps(original)
    def publish_snapshot_v166(self: Any, snapshot: Any, writer_id: str) -> bool:
        candidate = snapshot
        capped = False
        epoch = None
        if _is_proactive_trigger():
            try:
                candidate, capped, epoch = _cap_snapshot_to_fallback_timestamp(
                    snapshot,
                    _guard(),
                )
            except Exception as exc:
                LOGGER.debug(
                    "CAPITAL_V166_FALLBACK_TIMESTAMP_PROBE_ERROR marker=%s error=%s:%s",
                    MARKER,
                    type(exc).__name__,
                    exc,
                )
        if capped:
            LOGGER.info(
                "CAPITAL_V166_FALLBACK_TIMESTAMP_CAPPED marker=%s observed_epoch=%.6f "
                "cached_data_does_not_reset_freshness=true publication_expiry_extended=false",
                MARKER,
                float(epoch or 0.0),
            )
        return bool(original(self, candidate, writer_id))

    setattr(publish_snapshot_v166, _PATCH_ATTR, True)
    setattr(publish_snapshot_v166, "__wrapped__", original)
    cls.publish_snapshot = publish_snapshot_v166
    return True


def _patch_release_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_capital_refresh_ownership_v166"] = _READY_FLAG
        return True
    except Exception:
        return False


def install() -> bool:
    with _LOCK:
        ownership_ok = _patch_v137_writer_ownership()
        context_ok = _patch_flow_trigger_context()
        fetch_ok = _patch_proactive_fetch_budget()
        deadline_ok = _patch_proactive_pipeline_deadline()
        headroom_ok = _patch_v165_headroom_model()
        timestamp_ok = _patch_fallback_publication_timestamp()
        manifest_ok = _patch_release_manifest()
        ready = bool(
            ownership_ok
            and context_ok
            and fetch_ok
            and deadline_ok
            and headroom_ok
            and timestamp_ok
            and manifest_ok
        )
        os.environ[_READY_FLAG] = "1" if ready else "0"
        if not ready:
            LOGGER.critical(
                "RUNTIME_CAPITAL_REFRESH_OWNERSHIP_V166_FAILED marker=%s ownership_ok=%s "
                "context_ok=%s fetch_ok=%s deadline_ok=%s headroom_ok=%s timestamp_ok=%s "
                "manifest_ok=%s trading_fail_closed=true",
                MARKER,
                str(ownership_ok).lower(),
                str(context_ok).lower(),
                str(fetch_ok).lower(),
                str(deadline_ok).lower(),
                str(headroom_ok).lower(),
                str(timestamp_ok).lower(),
                str(manifest_ok).lower(),
            )
            return False

        # Representative telemetry. The proactive values below are explicit and
        # do not depend on thread-local trigger context.
        try:
            mabm = importlib.import_module("bot.multi_account_broker_manager")
            getter = getattr(mabm, "get_broker_manager", None)
            manager = getter() if callable(getter) else None
        except Exception:
            manager = None
        LOGGER.critical(
            "RUNTIME_CAPITAL_REFRESH_OWNERSHIP_V166 marker=%s ready=true "
            "active_writer_only=true proactive_fetch_budget_s=%.1f proactive_pipeline_deadline_s=%.1f "
            "proactive_headroom_s=%.1f fallback_timestamp_capped=true standby_refresh_suppressed=true "
            "bootstrap_budget_unchanged=true publication_expiry_extended=false stale_promoted=false "
            "safety_gates_bypassed=false",
            MARKER,
            _proactive_fetch_budget_seconds(),
            _proactive_pipeline_deadline_seconds(),
            _proactive_headroom_seconds(manager),
        )
        return True


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_live_mode",
    "_is_proactive_trigger",
    "_writer_lease_owned",
    "_proactive_fetch_budget_seconds",
    "_proactive_pipeline_deadline_seconds",
    "_proactive_headroom_seconds",
    "_oldest_fallback_observed_epoch",
    "_cap_snapshot_to_fallback_timestamp",
]
