"""Bound runtime capital refreshes and keep readiness proofs semantically truthful.

Production 2026-08-18 showed a canonical CapitalRefreshCoordinator remaining
``_in_flight`` beyond the immutable CapitalAuthority publication expiry. v137
correctly detected the expired publication but could only coalesce behind the
stuck coordinator, so v133 correctly failed LIVE_ACTIVE closed to OFF.

v142 repairs liveness without weakening that safety behavior:

* reassert the v35/v36 bounded broker-fetch wrapper plus the v78 freshness
  budget before every canonical runtime refresh;
* put a total runtime deadline around the coordinator pipeline after capital
  bootstrap is terminal, so a stuck downstream stage cannot monopolize the
  single writer indefinitely;
* generation-fence abandoned coordinator workers and replace a timed-out
  canonical coordinator in the manager, allowing one immediate v137 retry;
* keep CapitalAuthority publication expiry immutable and reject late retired
  generations without mutating the current publication status;
* make ``broker_connected`` come from the canonical broker registry and make
  ``balance_hydrated`` mean hydration only. ``capital_ready`` remains freshness
  gated, so an expired publication still revokes live execution through v133;
* register v140/v141/v142 as required runtime-release proofs.

The patch never fabricates capital or connectivity, extends snapshot expiry,
forces LIVE_ACTIVE, clears a kill switch, grants writer/nonce authority, or
bypasses risk/execution gates.
"""
from __future__ import annotations

import importlib
import logging
import os
import queue
import sys
import threading
import time
from functools import wraps
from types import ModuleType
from typing import Any

LOGGER = logging.getLogger("nija.capital_publication_liveness_v142")
MARKER = "20260818-capital-publication-liveness-v142"
RELEASE_ID = "20260818-runtime-convergence-v142"
_FLAG = "NIJA_CAPITAL_PUBLICATION_LIVENESS_V142_READY"
_PATCH_ATTR = "_nija_capital_publication_liveness_v142"
_LOCK = threading.RLock()
_ROLLOVER_LOCK = threading.RLock()
_GENERATION_LOCK = threading.RLock()
_LOCAL = threading.local()
_INSTALLED = False
_NEXT_GENERATION = 0
_ACTIVE_GENERATION = 0
_ROLLOVER_OCCURRED = False
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}


def _truthy(value: object) -> bool:
    return str(value or "").strip().lower() in _TRUE


def _import_first(*names: str) -> ModuleType:
    last: BaseException | None = None
    for name in names:
        try:
            return importlib.import_module(name)
        except Exception as exc:
            last = exc
    if last is not None:
        raise last
    raise ImportError("no module names supplied")


def _capital_flow_module() -> ModuleType:
    return _import_first("bot.capital_flow_state_machine", "capital_flow_state_machine")


def _authority() -> Any:
    module = _import_first("bot.capital_authority", "capital_authority")
    getter = getattr(module, "get_capital_authority", None)
    if not callable(getter):
        raise RuntimeError("capital_authority_getter_missing")
    authority = getter()
    if authority is None:
        raise RuntimeError("capital_authority_missing")
    return authority


def _canonical_manager() -> Any:
    module = sys.modules.get("bot.multi_account_broker_manager")
    if not isinstance(module, ModuleType):
        try:
            module = importlib.import_module("bot.multi_account_broker_manager")
        except Exception:
            return None
    getter = getattr(module, "get_broker_manager", None)
    if callable(getter):
        try:
            return getter()
        except Exception:
            return None
    return getattr(module, "_manager", None) or getattr(
        module, "multi_account_broker_manager", None
    )


def _freshness_ttl_seconds() -> float:
    try:
        ca = _import_first("bot.capital_authority", "capital_authority")
        canonical = float(getattr(ca, "_DEFAULT_FRESHNESS_TTL_S", 90.0) or 90.0)
    except Exception:
        canonical = 90.0
    try:
        configured = float(os.environ.get("NIJA_CAPITAL_FRESHNESS_TTL_S", canonical) or canonical)
    except (TypeError, ValueError):
        configured = canonical
    return max(10.0, min(canonical, configured))


def _fetch_budget_seconds() -> float:
    try:
        v78 = importlib.import_module("bot.capital_refresh_live_continuity_v78_patch")
        getter = getattr(v78, "fetch_budget_seconds", None)
        if callable(getter):
            return max(5.0, float(getter()))
    except Exception:
        pass
    return max(5.0, _freshness_ttl_seconds() - 30.0)


def _runtime_pipeline_deadline_seconds() -> float:
    """Return a total runtime coordinator deadline strictly inside freshness TTL."""
    ttl_s = _freshness_ttl_seconds()
    fetch_budget_s = _fetch_budget_seconds()
    default = min(ttl_s - 10.0, fetch_budget_s + 5.0)
    raw = str(os.environ.get("NIJA_CAPITAL_RUNTIME_PIPELINE_DEADLINE_S", "") or "").strip()
    if raw:
        try:
            requested = float(raw)
        except (TypeError, ValueError):
            requested = default
    else:
        requested = default
    # Never allow this liveness layer to broaden the immutable freshness window.
    return max(10.0, min(requested, max(10.0, ttl_s - 10.0)))


def _next_generation() -> int:
    global _NEXT_GENERATION, _ACTIVE_GENERATION
    with _GENERATION_LOCK:
        _NEXT_GENERATION += 1
        _ACTIVE_GENERATION = _NEXT_GENERATION
        return _ACTIVE_GENERATION


def _retire_generation(generation: int | None, reason: str) -> int:
    """Fence a timed-out/abandoned writer generation before replacement work starts."""
    global _NEXT_GENERATION, _ACTIVE_GENERATION, _ROLLOVER_OCCURRED
    with _GENERATION_LOCK:
        candidate = int(generation or 0)
        if candidate <= 0 or _ACTIVE_GENERATION == candidate:
            _NEXT_GENERATION = max(_NEXT_GENERATION, candidate) + 1
            _ACTIVE_GENERATION = _NEXT_GENERATION
        _ROLLOVER_OCCURRED = True
        active = _ACTIVE_GENERATION
    LOGGER.critical(
        "CAPITAL_COORDINATOR_GENERATION_RETIRED_V142 marker=%s retired=%s active=%d "
        "reason=%s late_publication_fenced=true",
        MARKER,
        candidate or "untagged",
        active,
        reason,
    )
    return active


def _generation_state() -> tuple[int, bool]:
    with _GENERATION_LOCK:
        return int(_ACTIVE_GENERATION), bool(_ROLLOVER_OCCURRED)


def _chain_contains(callable_obj: Any, *, marker: str, expected_name: str = "") -> bool:
    seen: set[int] = set()
    current = callable_obj
    for _ in range(32):
        if not callable(current) or id(current) in seen:
            return False
        seen.add(id(current))
        if bool(getattr(current, marker, False)):
            if not expected_name or str(getattr(current, "__name__", "")) == expected_name:
                return True
        current = getattr(current, "__wrapped__", None)
    return False


def _reassert_bounded_fetch_contract() -> tuple[bool, str]:
    """Prove the actual wrappers are present, not merely their environment flags."""
    try:
        flow = _capital_flow_module()
        v35 = importlib.import_module("bot.capital_refresh_stall_guard_v35")
        v78 = importlib.import_module("bot.capital_refresh_live_continuity_v78_patch")
        cls = getattr(flow, "CapitalRefreshCoordinator", None)
        batch_cls = getattr(v35, "_BalanceFetchBatch", None)
        if not isinstance(cls, type) or not isinstance(batch_cls, type):
            return False, "classes_missing"

        pipeline = getattr(cls, "_pipeline", None)
        bounded = _chain_contains(
            pipeline,
            marker="_nija_capital_refresh_stall_guard_v36",
            expected_name="_pipeline_with_bounded_brokers",
        )
        if not bounded:
            # functools.wraps can copy marker attributes to unrelated outer
            # wrappers. Remove only the copied top-level markers so v35 can
            # safely wrap the current owner and preserve every inner layer.
            for attr in (
                "_nija_capital_refresh_stall_guard_v35",
                "_nija_capital_refresh_stall_guard_v36",
            ):
                try:
                    if callable(pipeline) and hasattr(pipeline, attr):
                        delattr(pipeline, attr)
                except Exception:
                    pass
            patcher = getattr(v35, "_patch", None)
            if not callable(patcher) or not bool(patcher(flow)):
                return False, "v35_repatch_failed"
            pipeline = getattr(cls, "_pipeline", None)
            bounded = _chain_contains(
                pipeline,
                marker="_nija_capital_refresh_stall_guard_v36",
                expected_name="_pipeline_with_bounded_brokers",
            )

        init_fn = getattr(batch_cls, "__init__", None)
        v78_marker = str(getattr(v78, "_PATCH_ATTR", "_nija_capital_refresh_live_continuity_v78"))
        freshness_bounded = _chain_contains(
            init_fn,
            marker=v78_marker,
            expected_name="init_v78",
        )
        if not freshness_bounded:
            try:
                if callable(init_fn) and hasattr(init_fn, v78_marker):
                    delattr(init_fn, v78_marker)
            except Exception:
                pass
            patch_guard = getattr(v78, "_patch_guard", None)
            if not callable(patch_guard) or not bool(patch_guard(v35)):
                return False, "v78_repatch_failed"
            init_fn = getattr(batch_cls, "__init__", None)
            freshness_bounded = _chain_contains(
                init_fn,
                marker=v78_marker,
                expected_name="init_v78",
            )

        if not (bounded and freshness_bounded):
            return False, f"wrapper_proof_failed:v35={bounded}:v78={freshness_bounded}"
        return True, "v35_v36_and_v78_proven"
    except Exception as exc:
        return False, f"bounded_fetch_probe:{type(exc).__name__}:{exc}"


def _runtime_terminal(coordinator: Any) -> bool:
    boot = getattr(coordinator, "_boot", None)
    state = getattr(boot, "state", None) if boot is not None else None
    value = str(getattr(state, "value", state) or "").strip().upper()
    return value in {"READY", "RUNNING"}


def _emit_snapshot_rejected(coordinator: Any, trigger: str, exc: BaseException) -> None:
    try:
        flow = _capital_flow_module()
        event_cls = getattr(flow, "CapitalEvent")
        event_type = getattr(flow, "CapitalEventType").SNAPSHOT_REJECTED
        coordinator._bus.emit(
            event_cls(
                event_type=event_type,
                trigger=trigger,
                metadata={"error": str(exc), "marker": MARKER},
            )
        )
    except Exception:
        pass


def _flight_age_s(coordinator: Any) -> float:
    try:
        started = float(
            getattr(coordinator, "_nija_v142_flight_started_monotonic", 0.0) or 0.0
        )
    except (TypeError, ValueError):
        started = 0.0
    return max(0.0, time.monotonic() - started) if started > 0.0 else float("inf")


def _rollover_coordinator(
    manager: Any,
    *,
    expected_old: Any = None,
    reason: str,
) -> Any:
    """Swap only the canonical manager's coordinator; the retired worker is fenced."""
    with _ROLLOVER_LOCK:
        old = getattr(manager, "_capital_coordinator", None)
        if old is None:
            return None
        if expected_old is not None and old is not expected_old:
            return old

        generation = int(getattr(old, "_nija_v142_flight_generation", 0) or 0)
        _retire_generation(generation, reason)

        flow = _capital_flow_module()
        cls = getattr(flow, "CapitalRefreshCoordinator", None)
        if not isinstance(cls, type):
            return None
        bus = getattr(manager, "_capital_event_bus", None) or getattr(old, "_bus", None)
        boot = getattr(manager, "_capital_bootstrap_fsm", None) or getattr(old, "_boot", None)
        runtime = getattr(manager, "_capital_runtime_fsm", None) or getattr(old, "_runtime", None)
        if bus is None or boot is None or runtime is None:
            LOGGER.critical(
                "CAPITAL_COORDINATOR_ROLLOVER_V142_FAILED marker=%s reason=%s "
                "bus=%s boot=%s runtime=%s trading_fail_closed=true",
                MARKER,
                reason,
                bus is not None,
                boot is not None,
                runtime is not None,
            )
            return None

        replacement = cls(bus, boot, runtime)
        try:
            authority = _authority()
            if bool(getattr(authority, "is_hydrated", False)):
                replacement.balance_hydrated = True
                event = getattr(replacement, "balance_hydrated_event", None)
                if event is not None and callable(getattr(event, "set", None)):
                    event.set()
        except Exception:
            pass

        # The manager reference is the canonical ownership point. Old work is
        # allowed to unwind in its daemon thread but can no longer publish once
        # its generation has been retired.
        manager._capital_coordinator = replacement
        LOGGER.critical(
            "CAPITAL_COORDINATOR_ROLLOVER_V142 marker=%s reason=%s old_id=%s new_id=%s "
            "old_generation=%s old_age_s=%.1f old_trigger=%s old_thread_alive=%s "
            "publication_expiry_unchanged=true trading_fail_closed_until_refresh=true",
            MARKER,
            reason,
            hex(id(old)),
            hex(id(replacement)),
            generation or "untagged",
            _flight_age_s(old),
            str(getattr(old, "_nija_v142_flight_trigger", "unknown") or "unknown"),
            bool(
                getattr(
                    getattr(old, "_nija_v142_flight_thread", None),
                    "is_alive",
                    lambda: False,
                )()
            ),
        )
        return replacement


def _patch_coordinator_execute() -> bool:
    flow = _capital_flow_module()
    cls = getattr(flow, "CapitalRefreshCoordinator", None)
    if not isinstance(cls, type):
        return False
    current = getattr(cls, "execute_refresh", None)
    if not callable(current):
        return False
    if getattr(current, _PATCH_ATTR, False):
        return True
    original = current

    @wraps(original)
    def execute_refresh_v142(
        self: Any,
        broker_map: dict[str, Any],
        trigger: str = "coordinator",
        open_exposure_usd: float = 0.0,
    ) -> Any:
        bounded_ok, bounded_detail = _reassert_bounded_fetch_contract()
        if not bounded_ok:
            LOGGER.critical(
                "CAPITAL_RUNTIME_BOUND_CONTRACT_V142_FAILED marker=%s trigger=%s detail=%s "
                "refresh_started=false trading_fail_closed=true",
                MARKER,
                trigger,
                bounded_detail,
            )
            return None

        # Bootstrap transitions are thread-owned. Preserve the exact legacy
        # synchronous path until the capital bootstrap FSM is terminal.
        if not _runtime_terminal(self):
            return original(
                self,
                broker_map=broker_map,
                trigger=trigger,
                open_exposure_usd=open_exposure_usd,
            )

        with self._lock:
            if bool(getattr(self, "_in_flight", False)):
                LOGGER.info(
                    "CAPITAL_RUNTIME_REFRESH_V142_COALESCED marker=%s trigger=%s "
                    "owner_trigger=%s age_s=%.1f",
                    MARKER,
                    trigger,
                    str(getattr(self, "_nija_v142_flight_trigger", "unknown") or "unknown"),
                    _flight_age_s(self),
                )
                return None
            self._in_flight = True
            generation = _next_generation()
            self._nija_v142_flight_generation = generation
            self._nija_v142_flight_started_monotonic = time.monotonic()
            self._nija_v142_flight_trigger = str(trigger)
            self._nija_v142_flight_timed_out = False

        result_queue: queue.Queue[tuple[str, Any]] = queue.Queue(maxsize=1)

        def _run() -> None:
            previous_generation = getattr(_LOCAL, "refresh_generation", None)
            _LOCAL.refresh_generation = generation
            try:
                result = self._pipeline(
                    broker_map=broker_map,
                    trigger=trigger,
                    open_exposure_usd=open_exposure_usd,
                )
                try:
                    result_queue.put_nowait(("ok", result))
                except queue.Full:
                    pass
            except BaseException as exc:
                LOGGER.exception(
                    "CAPITAL_RUNTIME_PIPELINE_V142_EXCEPTION marker=%s trigger=%s "
                    "generation=%d error=%s:%s trading_fail_closed=true",
                    MARKER,
                    trigger,
                    generation,
                    type(exc).__name__,
                    exc,
                )
                _emit_snapshot_rejected(self, trigger, exc)
                try:
                    result_queue.put_nowait(("error", None))
                except queue.Full:
                    pass
            finally:
                if previous_generation is None:
                    try:
                        delattr(_LOCAL, "refresh_generation")
                    except AttributeError:
                        pass
                else:
                    _LOCAL.refresh_generation = previous_generation
                with self._lock:
                    if int(getattr(self, "_nija_v142_flight_generation", 0) or 0) == generation:
                        self._in_flight = False
                        self._nija_v142_flight_finished_monotonic = time.monotonic()

        worker = threading.Thread(
            target=_run,
            name=f"capital-runtime-refresh-v142-g{generation}",
            daemon=True,
        )
        with self._lock:
            self._nija_v142_flight_thread = worker
        worker.start()

        deadline_s = _runtime_pipeline_deadline_seconds()
        try:
            outcome, result = result_queue.get(timeout=deadline_s)
            return result if outcome == "ok" else None
        except queue.Empty:
            with self._lock:
                self._nija_v142_flight_timed_out = True
            _retire_generation(generation, "runtime_pipeline_deadline_exceeded")
            manager = _canonical_manager()
            replacement = None
            if manager is not None and getattr(manager, "_capital_coordinator", None) is self:
                replacement = _rollover_coordinator(
                    manager,
                    expected_old=self,
                    reason="runtime_pipeline_deadline_exceeded",
                )
            LOGGER.critical(
                "CAPITAL_RUNTIME_PIPELINE_V142_TIMEOUT marker=%s trigger=%s generation=%d "
                "deadline_s=%.1f age_s=%.1f rollover=%s late_publication_fenced=true "
                "publication_expiry_extended=false trading_fail_closed=true",
                MARKER,
                trigger,
                generation,
                deadline_s,
                _flight_age_s(self),
                replacement is not None and replacement is not self,
            )
            # Do not clear this retired instance's _in_flight flag here. Its
            # daemon owns that flag until it actually unwinds. The manager has
            # already moved to a fresh fenced coordinator when rollover succeeds.
            return None

    setattr(execute_refresh_v142, _PATCH_ATTR, True)
    setattr(execute_refresh_v142, "_nija_v142_original", original)
    cls.execute_refresh = execute_refresh_v142
    return True


def _patch_publication_generation_fence() -> bool:
    ca = _import_first("bot.capital_authority", "capital_authority")
    cls = getattr(ca, "CapitalAuthority", None)
    if not isinstance(cls, type):
        return False
    current = getattr(cls, "publish_snapshot", None)
    if not callable(current):
        return False
    if getattr(current, _PATCH_ATTR, False):
        return True
    original = current

    @wraps(original)
    def publish_snapshot_v142(self: Any, snapshot: Any, writer_id: str) -> bool:
        generation = getattr(_LOCAL, "refresh_generation", None)
        active, rolled = _generation_state()
        authorized = str(writer_id or "") == str(
            getattr(self, "_AUTHORIZED_WRITER_ID", "mabm_capital_refresh_coordinator")
        )
        if authorized:
            if generation is not None and int(generation) != active:
                LOGGER.warning(
                    "CAPITAL_PUBLICATION_V142_RETIRED_GENERATION_REJECTED marker=%s "
                    "generation=%s active=%s publication_status_unchanged=true",
                    MARKER,
                    generation,
                    active,
                )
                return False
            if generation is None and rolled:
                # Covers a legacy coordinator that entered before v142 was
                # installed and only returned after a rollover occurred.
                LOGGER.warning(
                    "CAPITAL_PUBLICATION_V142_UNTAGGED_AFTER_ROLLOVER_REJECTED marker=%s "
                    "active=%s publication_status_unchanged=true",
                    MARKER,
                    active,
                )
                return False
        return bool(original(self, snapshot, writer_id))

    setattr(publish_snapshot_v142, _PATCH_ATTR, True)
    setattr(publish_snapshot_v142, "_nija_v142_original", original)
    cls.publish_snapshot = publish_snapshot_v142
    return True


def _coordinator_in_flight_v142(manager: Any) -> bool:
    coordinator = getattr(manager, "_capital_coordinator", None)
    if coordinator is None:
        return False
    if not bool(getattr(coordinator, "_in_flight", False)):
        return False

    timed_out = bool(getattr(coordinator, "_nija_v142_flight_timed_out", False))
    thread = getattr(coordinator, "_nija_v142_flight_thread", None)
    alive_fn = getattr(thread, "is_alive", None) if thread is not None else None
    thread_alive = bool(alive_fn()) if callable(alive_fn) else False
    age_s = _flight_age_s(coordinator)
    limit_s = _runtime_pipeline_deadline_seconds()
    tracked = bool(getattr(coordinator, "_nija_v142_flight_generation", 0))

    should_roll = bool(timed_out or (tracked and (not thread_alive or age_s > limit_s + 1.0)))
    if not tracked:
        # A pre-v142/untracked flight cannot prove the total-runtime bound. Only
        # replace it once the immutable publication itself is no longer current.
        try:
            v137 = importlib.import_module("bot.capital_publication_deadline_v137_patch")
            current, _meta = v137._publication_meta(_authority())
        except Exception:
            current = False
        should_roll = not current

    if should_roll:
        replacement = _rollover_coordinator(
            manager,
            expected_old=coordinator,
            reason=(
                "coordinator_timeout_flag"
                if timed_out
                else "coordinator_owner_dead"
                if tracked and not thread_alive
                else "coordinator_age_exceeded"
                if tracked
                else "untracked_inflight_with_expired_publication"
            ),
        )
        return bool(replacement is coordinator or replacement is None)
    return True


def _patch_v137_liveness() -> bool:
    v137 = importlib.import_module("bot.capital_publication_deadline_v137_patch")
    v137._coordinator_in_flight = _coordinator_in_flight_v142

    current = getattr(v137, "_execute_deadline_refresh", None)
    if not callable(current):
        return False
    if getattr(current, _PATCH_ATTR, False):
        return True
    original = current

    @wraps(original)
    def execute_deadline_refresh_v142(
        manager: Any,
        *,
        trigger: str = "publication_deadline_v137",
    ) -> bool:
        # Probe liveness before v137 captures its local coordinator reference.
        if _coordinator_in_flight_v142(manager):
            return False
        before = getattr(manager, "_capital_coordinator", None)
        ok = bool(original(manager, trigger=trigger))
        if ok:
            return True

        after = getattr(manager, "_capital_coordinator", None)
        if after is not None and after is not before:
            LOGGER.warning(
                "CAPITAL_PUBLICATION_V142_IMMEDIATE_ROLLOVER_RETRY marker=%s "
                "trigger=%s old_id=%s new_id=%s",
                MARKER,
                trigger,
                hex(id(before)) if before is not None else "none",
                hex(id(after)),
            )
            if _coordinator_in_flight_v142(manager):
                return False
            return bool(original(manager, trigger=f"{trigger}:v142_rollover_retry"))
        return False

    setattr(execute_deadline_refresh_v142, _PATCH_ATTR, True)
    setattr(execute_deadline_refresh_v142, "_nija_v142_original", original)
    v137._execute_deadline_refresh = execute_deadline_refresh_v142
    return True


def _canonical_broker_connectivity() -> tuple[bool, dict[str, Any]]:
    manager = _canonical_manager()
    if manager is None:
        return False, {"reason": "manager_missing", "connected": [], "registered": []}

    platform = getattr(manager, "_platform_brokers", None)
    if not isinstance(platform, dict) or not platform:
        return False, {"reason": "platform_registry_empty", "connected": [], "registered": []}

    registered: list[str] = []
    connected: list[str] = []
    probe = getattr(manager, "is_platform_connected", None)
    state_map = getattr(manager, "_platform_state", {})
    for raw_key, broker in list(platform.items()):
        if broker is None:
            continue
        name = str(getattr(raw_key, "value", raw_key) or "").strip().lower()
        if not name:
            continue
        registered.append(name)
        direct = bool(getattr(broker, "connected", False))
        manager_connected = False
        if callable(probe):
            try:
                manager_connected = bool(probe(raw_key))
            except Exception:
                manager_connected = False
        state_connected = False
        if isinstance(state_map, dict):
            state = state_map.get(name, state_map.get(raw_key))
            state_value = str(getattr(state, "value", state) or "").strip().lower()
            state_connected = state_value == "connected"
        if direct or manager_connected or state_connected:
            connected.append(name)

    policy = str(os.environ.get("NIJA_SECONDARY_VENUE_POLICY", "optional") or "optional").strip().lower()
    if policy == "global_all_required":
        ready = bool(registered and len(connected) == len(registered))
    else:
        ready = bool(connected)
    return ready, {
        "reason": "ok" if ready else "canonical_platform_connectivity_not_proven",
        "policy": policy,
        "registered": sorted(set(registered)),
        "connected": sorted(set(connected)),
    }


def _patch_readiness_truth() -> bool:
    v16 = _import_first(
        "preactivation_readiness_convergence_v16_patch",
        "bot.preactivation_readiness_convergence_v16_patch",
    )
    current = getattr(v16, "_collect_proofs", None)
    if not callable(current):
        return False
    if getattr(current, _PATCH_ATTR, False):
        return True
    original = current

    @wraps(original)
    def collect_proofs_v142() -> tuple[dict[str, bool], dict[str, Any]]:
        proofs, details = original()
        proofs = dict(proofs or {})
        details = dict(details or {})
        capital = dict(details.get("capital") or {})

        connectivity, connectivity_meta = _canonical_broker_connectivity()
        authority_hydrated = bool(capital.get("hydrated", False))
        capital_stale = bool(capital.get("stale", True))

        # Semantics only: connectivity and hydration are independent facts.
        # capital_ready remains whatever the existing freshness-gated proof
        # computed, so stale capital still blocks/terminates live execution.
        proofs["broker_connected"] = bool(connectivity)
        proofs["balance_hydrated"] = bool(authority_hydrated)
        details["v142_readiness_truth"] = {
            "broker_connected": bool(connectivity),
            "balance_hydrated": bool(authority_hydrated),
            "capital_stale": capital_stale,
            "capital_ready": bool(proofs.get("capital_ready", False)),
            "connectivity": connectivity_meta,
            "freshness_does_not_relabel_connectivity": True,
        }
        return proofs, details

    setattr(collect_proofs_v142, _PATCH_ATTR, True)
    setattr(collect_proofs_v142, "_nija_v142_original", original)
    v16._collect_proofs = collect_proofs_v142
    return True


def _patch_release_manifest() -> bool:
    manifest = importlib.import_module("bot.runtime_release_manifest_patch")
    required = getattr(manifest, "_REQUIRED_FLAGS", None)
    installers = getattr(manifest, "_INSTALLERS", None)
    if not isinstance(required, dict) or not isinstance(installers, tuple):
        return False

    required["runtime_killswitch_authority_liveness_v140"] = (
        "NIJA_RUNTIME_KILLSWITCH_AUTHORITY_LIVENESS_V140_READY"
    )
    required["stalled_writer_capital_freshness_v141"] = (
        "NIJA_STALLED_WRITER_CAPITAL_FRESHNESS_V141_INSTALLED"
    )
    required["capital_publication_liveness_v142"] = _FLAG

    own = ("bot.capital_publication_liveness_v142_patch", "install_import_hook")
    if own not in installers:
        manifest._INSTALLERS = tuple(installers) + (own,)

    # v139 protects RELEASE_ID from diverging from DECLARED_RELEASE_ID. Advance
    # the declaration first, then the compatibility name.
    manifest.DECLARED_RELEASE_ID = RELEASE_ID
    manifest.RELEASE_ID = RELEASE_ID
    os.environ["NIJA_RUNTIME_RELEASE_ID"] = RELEASE_ID
    return True


def install_import_hook() -> bool:
    global _INSTALLED
    with _LOCK:
        try:
            bounded_ok, bounded_detail = _reassert_bounded_fetch_contract()
            ok = bool(
                bounded_ok
                and _patch_coordinator_execute()
                and _patch_publication_generation_fence()
                and _patch_v137_liveness()
                and _patch_readiness_truth()
                and _patch_release_manifest()
            )
        except Exception as exc:
            LOGGER.critical(
                "CAPITAL_PUBLICATION_LIVENESS_V142_INSTALL_FAILED marker=%s error=%s:%s "
                "trading_fail_closed=true",
                MARKER,
                type(exc).__name__,
                exc,
                exc_info=True,
            )
            ok = False
            bounded_detail = f"install_exception:{type(exc).__name__}:{exc}"
        if not ok:
            os.environ.pop(_FLAG, None)
            os.environ["NIJA_RUNTIME_RELEASE_READY"] = "0"
            return False

        os.environ[_FLAG] = "1"
        first = not _INSTALLED
        _INSTALLED = True

    if first:
        LOGGER.critical(
            "CAPITAL_PUBLICATION_LIVENESS_V142_INSTALLED marker=%s release=%s "
            "bounded_fetch=%s runtime_pipeline_deadline_s=%.1f generation_fence=true "
            "coordinator_rollover=true v137_immediate_retry=true truthful_connectivity=true "
            "truthful_hydration=true capital_freshness_gate_unchanged=true "
            "publication_expiry_extended=false kill_switch_unchanged=true nonce_unchanged=true "
            "risk_gates_unchanged=true execution_gates_unchanged=true force_live=false",
            MARKER,
            RELEASE_ID,
            bounded_detail,
            _runtime_pipeline_deadline_seconds(),
        )
    return True


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER",
    "RELEASE_ID",
    "install",
    "install_import_hook",
    "_runtime_pipeline_deadline_seconds",
    "_reassert_bounded_fetch_contract",
    "_rollover_coordinator",
    "_coordinator_in_flight_v142",
    "_canonical_broker_connectivity",
    "_patch_coordinator_execute",
    "_patch_publication_generation_fence",
    "_patch_v137_liveness",
    "_patch_readiness_truth",
    "_patch_release_manifest",
]
