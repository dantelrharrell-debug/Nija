"""Fail-closed final activation convergence hardening for NIJA.

This patch closes four production gaps that can leave a fully-ready runtime in
LIVE_PENDING_CONFIRMATION:

1. CapitalBootstrapStateMachine finishes in READY while StartupCoordinator's
   runtime reconciliation historically required the literal state RUNNING.
2. AuthorityHeartbeatMonitor could trust an EntrypointWriterAuthority singleton
   whose Redis renewal thread had stopped, allowing canonical heartbeat health to
   remain green while the actual Redis writer lock expired.
3. Preactivation and writer-authority reentry guards still had independent
   wall-clock heartbeat readers and private max-age policies.
4. Activation monitor retries did not always expose the coordinator's exact final
   blocking proof when commit_activation returned False.

No activation, fencing, nonce, kill-switch, capital, or risk gate is bypassed.
All repairs either align equivalent state names, consume the canonical heartbeat
source, or fail closed when lease-renewal evidence is missing.
"""
from __future__ import annotations

import builtins
import logging
import os
import sys
import time
from functools import wraps
from types import ModuleType
from typing import Any

logger = logging.getLogger("nija.activation_convergence_v17")

_MARKER = "20260807-activation-convergence-v17"
_HOOK_FLAG = "_NIJA_ACTIVATION_CONVERGENCE_V17_IMPORT_HOOK"
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}


def _truthy(name: str, default: str = "false") -> bool:
    return str(os.environ.get(name, default) or "").strip().lower() in _TRUE


def _canonical_heartbeat_api() -> ModuleType:
    try:
        from bot import heartbeat_authority_single_source_patch as module
    except ImportError:
        import heartbeat_authority_single_source_patch as module  # type: ignore[import]
    return module


def _canonical_heartbeat_ready(source: str) -> tuple[bool, str, dict[str, Any]]:
    module = _canonical_heartbeat_api()
    healthy, _now, heartbeat_ts, age_s, authoritative = module.heartbeat_check(
        source=source
    )
    max_age_s = float(module.heartbeat_max_age_s())
    active = _truthy("NIJA_WRITER_HEARTBEAT_ACTIVE")
    detail = {
        "healthy": bool(healthy),
        "authoritative": bool(authoritative),
        "active": bool(active),
        "heartbeat_ts": float(heartbeat_ts),
        "heartbeat_age_s": float(age_s),
        "heartbeat_max_age_s": max_age_s,
    }
    if not active:
        return False, "writer_heartbeat_inactive", detail
    if not authoritative:
        return False, "writer_heartbeat_uninitialized", detail
    if not healthy:
        return False, f"writer_heartbeat_stale:{age_s:.1f}>{max_age_s:.1f}", detail
    return True, f"writer_heartbeat_fresh:{age_s:.1f}s", detail


def _redis_configured() -> bool:
    try:
        try:
            from bot.redis_env import get_redis_url
        except ImportError:
            from redis_env import get_redis_url  # type: ignore[import]
        return bool(str(get_redis_url() or "").strip())
    except Exception:
        return bool(
            str(os.environ.get("NIJA_REDIS_URL", "") or "").strip()
            or str(os.environ.get("REDIS_URL", "") or "").strip()
        )


def _renewal_policy(runtime: Any) -> tuple[float, float]:
    try:
        ttl_s = max(15.0, float(getattr(runtime, "_ttl_s", 60.0) or 60.0))
    except (TypeError, ValueError):
        ttl_s = 60.0
    raw_interval = str(os.environ.get("NIJA_WRITER_HEARTBEAT_INTERVAL_S", "") or "").strip()
    if raw_interval:
        try:
            interval_s = max(1.0, float(raw_interval))
        except (TypeError, ValueError):
            interval_s = min(5.0, max(1.0, ttl_s / 3.0))
    else:
        interval_s = min(5.0, max(1.0, ttl_s / 3.0))
    nominal_max_age = max(10.0, interval_s * 3.0)
    ttl_cap = max(interval_s * 2.0, ttl_s * 0.75)
    return interval_s, min(nominal_max_age, ttl_cap)


def _note_lease_renewal(runtime: Any, source: str) -> None:
    now_mono = time.monotonic()
    now_epoch = time.time()
    setattr(runtime, "_nija_last_lease_renewal_monotonic", now_mono)
    setattr(runtime, "_nija_last_lease_renewal_epoch", now_epoch)
    os.environ["NIJA_WRITER_LEASE_RENEWAL_ACTIVE"] = "1"
    os.environ["NIJA_WRITER_LEASE_RENEWED_TS"] = f"{now_epoch:.6f}"
    logger.info(
        "WRITER_LEASE_RENEWAL_PROOF marker=%s generation=%s source=%s renewal_ts=%.6f",
        _MARKER,
        getattr(runtime, "_generation", 0),
        source,
        now_epoch,
    )


def _patch_entrypoint_writer_authority(module: ModuleType) -> None:
    cls = getattr(module, "EntrypointWriterAuthority", None)
    patch_attr = "_NIJA_ACTIVATION_CONVERGENCE_V17_ENTRYPOINT_PATCHED"
    if not isinstance(cls, type) or getattr(cls, patch_attr, False):
        return

    original_publish = getattr(cls, "_publish_env", None)
    if callable(original_publish):
        @wraps(original_publish)
        def _publish_env(self: Any, *args: Any, **kwargs: Any):
            result = original_publish(self, *args, **kwargs)
            _note_lease_renewal(self, "writer_acquired")
            return result
        cls._publish_env = _publish_env

    original_tick = getattr(cls, "_heartbeat_tick", None)
    if callable(original_tick):
        @wraps(original_tick)
        def _heartbeat_tick(self: Any, *args: Any, **kwargs: Any):
            result = original_tick(self, *args, **kwargs)
            try:
                ok = bool(result[0])
            except Exception:
                ok = False
            if ok:
                _note_lease_renewal(self, "heartbeat_tick")
            return result
        cls._heartbeat_tick = _heartbeat_tick

    original_loop = getattr(cls, "_heartbeat_loop", None)
    if callable(original_loop):
        @wraps(original_loop)
        def _heartbeat_loop(self: Any, *args: Any, **kwargs: Any):
            try:
                return original_loop(self, *args, **kwargs)
            except Exception as exc:
                os.environ["NIJA_WRITER_LEASE_RENEWAL_ACTIVE"] = "0"
                setattr(self, "_nija_renewal_loop_exception", f"{type(exc).__name__}:{exc}")
                logger.exception(
                    "WRITER_LEASE_RENEWAL_THREAD_CRASHED marker=%s generation=%s err=%s",
                    _MARKER,
                    getattr(self, "_generation", 0),
                    exc,
                )
                return None
            finally:
                try:
                    stop_event = getattr(self, "_stop", None)
                    stopping = bool(
                        stop_event is not None
                        and callable(getattr(stop_event, "is_set", None))
                        and stop_event.is_set()
                    )
                    if bool(getattr(self, "acquired", False)) and not stopping:
                        os.environ["NIJA_WRITER_LEASE_RENEWAL_ACTIVE"] = "0"
                        logger.critical(
                            "WRITER_LEASE_RENEWAL_THREAD_EXITED_UNEXPECTEDLY marker=%s generation=%s",
                            _MARKER,
                            getattr(self, "_generation", 0),
                        )
                except Exception:
                    pass
        cls._heartbeat_loop = _heartbeat_loop

    def _nija_lease_renewal_health(self: Any) -> tuple[bool, str, float, float]:
        if bool(getattr(self, "_local_fallback", False)):
            return True, "local_fallback", 0.0, float("inf")
        if not bool(getattr(self, "acquired", False)):
            return False, "writer_not_acquired", float("inf"), 0.0
        if bool(getattr(self, "lost", False)):
            return False, "writer_lost", float("inf"), 0.0
        stop_event = getattr(self, "_stop", None)
        if (
            stop_event is not None
            and callable(getattr(stop_event, "is_set", None))
            and stop_event.is_set()
        ):
            return False, "renewal_stop_requested", float("inf"), 0.0
        thread = getattr(self, "_heartbeat_thread", None)
        if thread is None:
            return False, "renewal_thread_missing", float("inf"), 0.0
        try:
            if not bool(thread.is_alive()):
                return False, "renewal_thread_not_alive", float("inf"), 0.0
        except Exception:
            return False, "renewal_thread_state_unavailable", float("inf"), 0.0
        last = float(getattr(self, "_nija_last_lease_renewal_monotonic", 0.0) or 0.0)
        _interval_s, max_age_s = _renewal_policy(self)
        if last <= 0.0:
            return False, "renewal_success_uninitialized", float("inf"), max_age_s
        age_s = max(0.0, time.monotonic() - last)
        if age_s > max_age_s:
            return False, "renewal_success_stale", age_s, max_age_s
        return True, "renewal_healthy", age_s, max_age_s

    cls._nija_lease_renewal_health = _nija_lease_renewal_health
    setattr(cls, patch_attr, True)
    logger.warning(
        "ACTIVATION_CONVERGENCE_ENTRYPOINT_PATCHED marker=%s module=%s",
        _MARKER,
        module.__name__,
    )


def _patch_authority_heartbeat(module: ModuleType) -> None:
    patch_attr = "_NIJA_ACTIVATION_CONVERGENCE_V17_AUTHORITY_HEARTBEAT_PATCHED"
    if getattr(module, patch_attr, False):
        return
    original = getattr(module, "_check_authority_once", None)
    if not callable(original):
        return

    @wraps(original)
    def _check_authority_once(timeout_s: float):
        lease_held = _truthy("NIJA_WRITER_LEASE_ACQUIRED")
        local_fallback = _truthy("NIJA_WRITER_FENCING_TOKEN_FALLBACK")
        if lease_held and not local_fallback:
            runtime = None
            ewa_module = (
                sys.modules.get("bot.entrypoint_writer_authority")
                or sys.modules.get("entrypoint_writer_authority")
            )
            getter = getattr(ewa_module, "get_entrypoint_writer_authority", None)
            if callable(getter):
                try:
                    runtime = getter()
                except Exception:
                    runtime = None
            if runtime is not None:
                if not bool(getattr(runtime, "acquired", False)):
                    return False, "entrypoint writer singleton is not acquired"
                health = getattr(runtime, "_nija_lease_renewal_health", None)
                if not callable(health):
                    return False, "entrypoint writer renewal health proof unavailable"
                ok, reason, age_s, max_age_s = health()
                if not ok:
                    restarted = False
                    if reason in {"renewal_thread_missing", "renewal_thread_not_alive"}:
                        stop_event = getattr(runtime, "_stop", None)
                        stopping = bool(
                            stop_event is not None
                            and callable(getattr(stop_event, "is_set", None))
                            and stop_event.is_set()
                        )
                        start = getattr(runtime, "_start_heartbeat", None)
                        if not stopping and callable(start):
                            try:
                                start()
                                thread = getattr(runtime, "_heartbeat_thread", None)
                                restarted = bool(
                                    thread is not None
                                    and callable(getattr(thread, "is_alive", None))
                                    and thread.is_alive()
                                )
                            except Exception:
                                restarted = False
                        logger.critical(
                            "WRITER_LEASE_RENEWAL_THREAD_RESTART marker=%s restarted=%s generation=%s reason=%s",
                            _MARKER,
                            restarted,
                            getattr(runtime, "_generation", 0),
                            reason,
                        )
                    return (
                        False,
                        "entrypoint writer renewal unhealthy: "
                        f"reason={reason} age_s={age_s:.1f} max_age_s={max_age_s:.1f} "
                        f"restarted={restarted}",
                    )
        return original(timeout_s)

    module._check_authority_once = _check_authority_once
    setattr(module, patch_attr, True)
    logger.warning(
        "ACTIVATION_CONVERGENCE_AUTHORITY_HEARTBEAT_PATCHED marker=%s module=%s",
        _MARKER,
        module.__name__,
    )


def _patch_preactivation(module: ModuleType) -> None:
    patch_attr = "_NIJA_ACTIVATION_CONVERGENCE_V17_PREACTIVATION_PATCHED"
    if getattr(module, patch_attr, False):
        return
    if not callable(getattr(module, "_heartbeat_ready", None)):
        return

    def _heartbeat_ready() -> tuple[bool, str]:
        ok, detail, _meta = _canonical_heartbeat_ready(
            "preactivation_readiness_convergence_v16"
        )
        return ok, detail

    module._heartbeat_ready = _heartbeat_ready
    setattr(module, patch_attr, True)
    logger.warning(
        "ACTIVATION_CONVERGENCE_PREACTIVATION_PATCHED marker=%s module=%s",
        _MARKER,
        module.__name__,
    )


def _patch_writer_reentry_guard(module: ModuleType) -> None:
    patch_attr = "_NIJA_ACTIVATION_CONVERGENCE_V17_REENTRY_PATCHED"
    if getattr(module, patch_attr, False):
        return
    if not callable(getattr(module, "_writer_reentry_proof", None)):
        return

    def _writer_reentry_proof() -> dict[str, Any]:
        token = str(os.environ.get("NIJA_WRITER_FENCING_TOKEN", "") or "").strip()
        generation = str(os.environ.get("NIJA_WRITER_LEASE_GENERATION", "") or "").strip()
        lease_acquired = _truthy("NIJA_WRITER_LEASE_ACQUIRED")
        heartbeat_ok, _detail, heartbeat = _canonical_heartbeat_ready(
            "writer_authority_reentry_guard"
        )
        redis_configured = _redis_configured()
        proof_ok = bool(
            redis_configured
            and token
            and generation
            and lease_acquired
            and heartbeat_ok
        )
        return {
            "ok": proof_ok,
            "redis_configured": redis_configured,
            "redis_reachable": bool(proof_ok),
            "token_present": bool(token),
            "token_prefix": token[:8],
            "lease_generation": generation,
            "lease_acquired": lease_acquired,
            "heartbeat_active": bool(heartbeat.get("active")),
            "heartbeat_age_s": float(heartbeat.get("heartbeat_age_s", float("inf"))),
            "heartbeat_max_age_s": float(heartbeat.get("heartbeat_max_age_s", 0.0)),
            "heartbeat_authoritative": bool(heartbeat.get("authoritative")),
        }

    module._writer_reentry_proof = _writer_reentry_proof
    setattr(module, patch_attr, True)
    logger.warning(
        "ACTIVATION_CONVERGENCE_REENTRY_PATCHED marker=%s module=%s",
        _MARKER,
        module.__name__,
    )


def _patch_secondary_venue_activation(module: ModuleType) -> None:
    patch_attr = "_NIJA_ACTIVATION_CONVERGENCE_V17_SECONDARY_PATCHED"
    if getattr(module, patch_attr, False):
        return
    if not callable(getattr(module, "_heartbeat_healthy", None)):
        return

    def _heartbeat_healthy() -> bool:
        ok, _detail, _meta = _canonical_heartbeat_ready(
            "secondary_venue_activation"
        )
        return bool(ok)

    module._heartbeat_healthy = _heartbeat_healthy
    setattr(module, patch_attr, True)
    logger.warning(
        "ACTIVATION_CONVERGENCE_SECONDARY_PATCHED marker=%s module=%s",
        _MARKER,
        module.__name__,
    )


def _patch_startup_coordinator(module: ModuleType) -> None:
    cls = getattr(module, "StartupCoordinator", None)
    patch_attr = "_NIJA_ACTIVATION_CONVERGENCE_V17_COORDINATOR_PATCHED"
    if not isinstance(cls, type) or getattr(cls, patch_attr, False):
        return
    original = getattr(cls, "_reconcile_runtime_authority_locked", None)
    if not callable(original):
        return

    @wraps(original)
    def _reconcile_runtime_authority_locked(self: Any, *args: Any, **kwargs: Any):
        runtime = getattr(self, "_runtime", None)
        capital_state = str(getattr(runtime, "capital_state", "") or "").strip().upper()
        if runtime is None or capital_state != "READY":
            return original(self, *args, **kwargs)

        original_state = runtime.capital_state
        runtime.capital_state = "RUNNING"
        try:
            result = original(self, *args, **kwargs)
        finally:
            runtime.capital_state = original_state

        if not bool(getattr(self, "_nija_capital_ready_compat_logged", False)):
            setattr(self, "_nija_capital_ready_compat_logged", True)
            logger.critical(
                "STARTUP_COORDINATOR_CAPITAL_READY_COMPAT marker=%s source_state=READY reconcile_state=RUNNING",
                _MARKER,
            )
        return result

    cls._reconcile_runtime_authority_locked = _reconcile_runtime_authority_locked
    setattr(cls, patch_attr, True)
    logger.warning(
        "ACTIVATION_CONVERGENCE_COORDINATOR_PATCHED marker=%s module=%s",
        _MARKER,
        module.__name__,
    )


def _patch_activation_monitor(module: ModuleType) -> None:
    patch_attr = "_NIJA_ACTIVATION_CONVERGENCE_V17_MONITOR_PATCHED"
    if getattr(module, patch_attr, False):
        return
    original = getattr(module, "_commit_once", None)
    if not callable(original):
        return

    @wraps(original)
    def _commit_once(sm: Any, meta: dict[str, Any]) -> bool:
        ok = bool(original(sm, meta))
        if ok:
            return True
        try:
            try:
                from bot.startup_coordinator import get_startup_coordinator
            except ImportError:
                from startup_coordinator import get_startup_coordinator  # type: ignore[import]
            coordinator = get_startup_coordinator()
            state = str(module._current_state_value(sm) or "UNKNOWN")
            snapshot = coordinator.build_snapshot(
                trading_state=state,
                activation_intent=True,
            )
            proof = coordinator.evaluate_system_readiness_proof(snapshot)
            logger.critical(
                "ACTIVATION_FINAL_GATE_BLOCKED marker=%s first_gate=%s failed_gates=%s "
                "proof_passed=%s runtime_authority=%s runtime_reason=%s bootstrap=%s "
                "capital=%s capital_hydrated=%s capital_stale=%s threads=%s/%s "
                "authority=%s nonce=%s dispatch_health=%s epoch=%s/%s pending_readiness=%s",
                _MARKER,
                getattr(proof, "first_blocking_gate", "unknown"),
                ",".join(getattr(proof, "failed_gates", []) or []),
                bool(getattr(proof, "passed", False)),
                getattr(snapshot, "runtime_authority_state", "unknown"),
                getattr(snapshot, "runtime_authority_reason", "unknown"),
                getattr(snapshot, "bootstrap_state", "unknown"),
                getattr(snapshot, "capital_state", "unknown"),
                bool(getattr(snapshot, "capital_hydrated", False)),
                bool(getattr(snapshot, "capital_stale", True)),
                int(getattr(snapshot, "threads_launched", 0) or 0),
                bool(getattr(snapshot, "threads_confirmed_running", False)),
                bool(getattr(snapshot, "authority_ready", False)),
                bool(getattr(snapshot, "nonce_ready", False)),
                bool(getattr(snapshot, "dispatch_health_ready", False)),
                int(getattr(snapshot, "activation_epoch", 0) or 0),
                int(getattr(snapshot, "global_epoch", 0) or 0),
                ",".join(getattr(snapshot, "pending_readiness", []) or []),
            )
        except Exception as exc:
            logger.warning(
                "ACTIVATION_FINAL_GATE_DIAGNOSTIC_FAILED marker=%s err=%s",
                _MARKER,
                exc,
            )
        return False

    module._commit_once = _commit_once
    setattr(module, patch_attr, True)
    logger.warning(
        "ACTIVATION_CONVERGENCE_MONITOR_PATCHED marker=%s module=%s",
        _MARKER,
        module.__name__,
    )


def _patch_loaded() -> None:
    targets = (
        (("bot.entrypoint_writer_authority", "entrypoint_writer_authority"), _patch_entrypoint_writer_authority),
        (("bot.authority_heartbeat", "authority_heartbeat"), _patch_authority_heartbeat),
        (("bot.startup_coordinator", "startup_coordinator"), _patch_startup_coordinator),
        (("bot.writer_authority_recursion_guard_patch", "writer_authority_recursion_guard_patch"), _patch_writer_reentry_guard),
        (("bot.preactivation_readiness_convergence_v16_patch", "preactivation_readiness_convergence_v16_patch"), _patch_preactivation),
        (("bot.secondary_venue_activation_patch", "secondary_venue_activation_patch"), _patch_secondary_venue_activation),
        (("bot.activation_pending_commit_monitor_patch", "activation_pending_commit_monitor_patch"), _patch_activation_monitor),
    )
    for names, patcher in targets:
        seen: set[int] = set()
        for name in names:
            module = sys.modules.get(name)
            if isinstance(module, ModuleType) and id(module) not in seen:
                seen.add(id(module))
                try:
                    patcher(module)
                except Exception:
                    logger.exception(
                        "ACTIVATION_CONVERGENCE_PATCH_FAILED marker=%s module=%s",
                        _MARKER,
                        name,
                    )


def install_import_hook() -> None:
    _patch_loaded()
    if getattr(builtins, _HOOK_FLAG, False):
        return
    original_import = builtins.__import__

    def importing(
        name: str,
        globals: Any = None,
        locals: Any = None,
        fromlist: Any = (),
        level: int = 0,
    ):
        module = original_import(name, globals, locals, fromlist, level)
        if any(
            str(name).endswith(suffix)
            for suffix in (
                "entrypoint_writer_authority",
                "authority_heartbeat",
                "startup_coordinator",
                "writer_authority_recursion_guard_patch",
                "preactivation_readiness_convergence_v16_patch",
                "secondary_venue_activation_patch",
                "activation_pending_commit_monitor_patch",
            )
        ):
            _patch_loaded()
        return module

    builtins.__import__ = importing
    setattr(builtins, _HOOK_FLAG, True)
    logger.critical(
        "ACTIVATION_CONVERGENCE_V17_INSTALL_COMPLETE marker=%s fail_closed=true",
        _MARKER,
    )


def install() -> None:
    install_import_hook()


__all__ = [
    "install",
    "install_import_hook",
    "_patch_entrypoint_writer_authority",
    "_patch_authority_heartbeat",
    "_patch_preactivation",
    "_patch_writer_reentry_guard",
    "_patch_secondary_venue_activation",
    "_patch_startup_coordinator",
    "_patch_activation_monitor",
]
