"""NIJA activation lifecycle handoff v41.

Production after v40 proved that writer heartbeat recovery can converge again,
but the final activation proof can still be left with stale coordinator evidence:
``capital_state=BOOT_IDLE`` while canonical CapitalAuthority is hydrated/fresh,
and ``threads=0/True`` while the supervised core loop is alive.

v41 repairs only those evidence handoffs.  It never force-activates, never
synthesizes capital, never marks dispatch health healthy, and never bypasses
writer authority, nonce, kill-switch, SEAK, risk, broker, or readiness gates.

Safety contract
---------------
* BOOT/BOOT_IDLE/UNKNOWN/READY capital is promoted to coordinator ``RUNNING``
  only after an independent canonical CapitalAuthority proof: live-capital mode,
  hydrated, positive real+usable capital, at least one broker balance, fresh,
  and kill switch clear.
* Missing supervised-thread count is repaired only when the actual bot core
  thread is alive and EntrypointWriterAuthority is acquired/not-lost with a live
  heartbeat thread and healthy renewal proof.
* ``dispatch_health_ready`` and every other transaction input are preserved.
* ``bot.startup_coordinator`` and ``startup_coordinator`` are bound to one
  canonical singleton/getter so later mixed imports cannot split lifecycle
  evidence across two coordinators.
"""
from __future__ import annotations

import builtins
import importlib
import logging
import os
import sys
import threading
from functools import wraps
from types import ModuleType
from typing import Any, Optional

LOGGER = logging.getLogger("nija.activation_lifecycle_handoff_v41")
MARKER = "20260807-activation-lifecycle-handoff-v41"

_TRUE = {"1", "true", "yes", "on", "enabled", "y"}
_INSTALL_FLAG = "_NIJA_ACTIVATION_LIFECYCLE_HANDOFF_V41_IMPORT_HOOK"
_IMPORTLIB_FLAG = "_NIJA_ACTIVATION_LIFECYCLE_HANDOFF_V41_IMPORTLIB_HOOK"
_CANONICAL_KEY = "_NIJA_CANONICAL_STARTUP_COORDINATOR_MODULE_V41"
_PATCH_ATTR = "_nija_activation_lifecycle_handoff_v41"
_LOCK = threading.RLock()


def _truthy(name: str, default: str = "false") -> bool:
    return str(os.environ.get(name, default) or "").strip().lower() in _TRUE


def _simulation_mode() -> bool:
    return _truthy("DRY_RUN_MODE") or _truthy("PAPER_MODE")


def _kill_switch_clear() -> tuple[bool, str]:
    try:
        module = importlib.import_module("bot.kill_switch")
        getter = getattr(module, "get_kill_switch", None)
        if not callable(getter):
            return False, "kill_switch_getter_unavailable"
        active = bool(getter().is_active())
        return (not active), "kill_switch_active" if active else "kill_switch_clear"
    except Exception as exc:
        return False, f"kill_switch_probe_error:{type(exc).__name__}:{exc}"


def _capital_broker_count(ca: Any) -> int:
    count = 0
    for attr in ("valid_broker_count", "registered_broker_count", "ca_valid_brokers"):
        try:
            count = max(count, int(getattr(ca, attr, 0) or 0))
        except Exception:
            pass
    for attr in ("broker_balances", "_broker_balances"):
        try:
            balances = getattr(ca, attr, None)
            if isinstance(balances, dict):
                count = max(count, len([v for v in balances.values() if v is not None]))
        except Exception:
            pass
    try:
        snap_getter = getattr(ca, "get_typed_snapshot", None)
        snapshot = snap_getter() if callable(snap_getter) else None
        count = max(count, int(getattr(snapshot, "broker_count", 0) or 0))
    except Exception:
        pass
    return count


def _capital_fresh(ca: Any) -> bool:
    checker = getattr(ca, "is_fresh", None)
    if callable(checker):
        try:
            return bool(checker(ttl_s=180.0))
        except TypeError:
            try:
                return bool(checker())
            except Exception:
                return False
        except Exception:
            return False
    stale = getattr(ca, "is_stale", None)
    if callable(stale):
        try:
            return not bool(stale(ttl_s=180.0))
        except TypeError:
            try:
                return not bool(stale())
            except Exception:
                return False
        except Exception:
            return False
    return False


def _verified_capital_evidence() -> tuple[bool, str, dict[str, Any]]:
    detail: dict[str, Any] = {
        "hydrated": False,
        "real": 0.0,
        "usable": 0.0,
        "broker_count": 0,
        "fresh": False,
    }
    if _simulation_mode():
        return False, "simulation_mode", detail
    if not _truthy("LIVE_CAPITAL_VERIFIED"):
        return False, "live_capital_not_verified", detail
    kill_ok, kill_detail = _kill_switch_clear()
    if not kill_ok:
        return False, kill_detail, detail

    try:
        module = importlib.import_module("bot.capital_authority")
        getter = getattr(module, "get_capital_authority", None)
        if not callable(getter):
            return False, "capital_authority_getter_unavailable", detail
        ca = getter()
    except Exception as exc:
        return False, f"capital_authority_error:{type(exc).__name__}:{exc}", detail

    try:
        detail["hydrated"] = bool(getattr(ca, "is_hydrated", False))
        real_getter = getattr(ca, "get_real_capital", None)
        usable_getter = getattr(ca, "get_usable_capital", None)
        detail["real"] = float(real_getter() if callable(real_getter) else getattr(ca, "total_capital", 0.0) or 0.0)
        detail["usable"] = float(usable_getter() if callable(usable_getter) else getattr(ca, "usable_capital", 0.0) or 0.0)
        detail["broker_count"] = _capital_broker_count(ca)
        detail["fresh"] = _capital_fresh(ca)
    except Exception as exc:
        return False, f"capital_evidence_error:{type(exc).__name__}:{exc}", detail

    ok = bool(
        detail["hydrated"]
        and float(detail["real"]) > 0.0
        and float(detail["usable"]) > 0.0
        and int(detail["broker_count"]) > 0
        and detail["fresh"]
    )
    if not ok:
        return (
            False,
            "capital_not_verified "
            f"hydrated={detail['hydrated']} real={detail['real']:.2f} "
            f"usable={detail['usable']:.2f} brokers={detail['broker_count']} fresh={detail['fresh']}",
            detail,
        )
    return True, "canonical_capital_verified", detail


def _writer_runtime() -> Any:
    for name in ("bot.entrypoint_writer_authority", "entrypoint_writer_authority"):
        module = sys.modules.get(name)
        getter = getattr(module, "get_entrypoint_writer_authority", None) if module is not None else None
        if callable(getter):
            try:
                return getter()
            except Exception:
                continue
    try:
        module = importlib.import_module("bot.entrypoint_writer_authority")
        getter = getattr(module, "get_entrypoint_writer_authority", None)
        return getter() if callable(getter) else None
    except Exception:
        return None


def _renewal_healthy(runtime: Any) -> tuple[bool, str]:
    health = getattr(runtime, "_nija_lease_renewal_health", None)
    if not callable(health):
        return False, "renewal_health_unavailable"
    try:
        ok, reason, age_s, max_age_s = health()
        if not bool(ok):
            return False, f"{reason}:{float(age_s):.1f}>{float(max_age_s):.1f}"
        return True, "renewal_healthy"
    except Exception as exc:
        return False, f"renewal_health_error:{type(exc).__name__}:{exc}"


def _core_thread() -> Any:
    module = sys.modules.get("bot.bot_main") or sys.modules.get("bot_main")
    return getattr(module, "_core_loop_thread", None) if module is not None else None


def _verified_supervised_thread_count() -> tuple[int, str]:
    runtime = _writer_runtime()
    if runtime is None:
        return 0, "writer_runtime_unavailable"
    if not bool(getattr(runtime, "acquired", False)):
        return 0, "writer_not_acquired"
    if bool(getattr(runtime, "lost", False)):
        return 0, "writer_lost"

    heartbeat = getattr(runtime, "_heartbeat_thread", None)
    try:
        heartbeat_alive = bool(
            heartbeat is not None
            and callable(getattr(heartbeat, "is_alive", None))
            and heartbeat.is_alive()
        )
    except Exception:
        heartbeat_alive = False
    if not heartbeat_alive:
        return 0, "writer_heartbeat_thread_not_alive"

    renewal_ok, renewal_detail = _renewal_healthy(runtime)
    if not renewal_ok:
        return 0, f"writer_{renewal_detail}"

    core = _core_thread()
    try:
        core_alive = bool(
            core is not None
            and callable(getattr(core, "is_alive", None))
            and core.is_alive()
        )
    except Exception:
        core_alive = False
    if not core_alive:
        return 0, "core_loop_thread_not_alive"

    # One real, positively identified supervised core loop is sufficient for
    # the coordinator's >0 proof.  Do not count unrelated daemon/helper threads.
    return 1, "core_loop_supervised"


def _canonicalize_startup_coordinator(module: ModuleType) -> ModuleType:
    canonical = getattr(builtins, _CANONICAL_KEY, None)
    if not isinstance(canonical, ModuleType):
        canonical = module
        setattr(builtins, _CANONICAL_KEY, canonical)
    elif canonical is not module:
        canonical_getter = getattr(canonical, "get_startup_coordinator", None)
        if callable(canonical_getter):
            module.get_startup_coordinator = canonical_getter
        if hasattr(canonical, "GLOBAL_STATE"):
            module.GLOBAL_STATE = canonical.GLOBAL_STATE
        LOGGER.critical(
            "STARTUP_COORDINATOR_IDENTITY_V41_REBOUND marker=%s duplicate=%s canonical=%s",
            MARKER,
            getattr(module, "__name__", "unknown"),
            getattr(canonical, "__name__", "unknown"),
        )
    sys.modules["bot.startup_coordinator"] = canonical
    sys.modules["startup_coordinator"] = canonical
    return canonical


def _normalize_transaction_kwargs(coordinator: Any, kwargs: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    normalized = dict(kwargs)
    audit: dict[str, Any] = {
        "capital_promoted": False,
        "threads_repaired": False,
        "capital_reason": "not_checked",
        "thread_reason": "not_checked",
    }

    incoming_capital = str(normalized.get("capital_state", "") or "").strip().upper()
    if incoming_capital in {"", "BOOT", "BOOT_IDLE", "UNKNOWN", "READY"}:
        cap_ok, cap_reason, cap = _verified_capital_evidence()
        audit["capital_reason"] = cap_reason
        if cap_ok:
            normalized["capital_state"] = "RUNNING"
            normalized["capital_hydrated"] = True
            normalized["capital_balance"] = float(cap["real"])
            normalized["capital_stale"] = False
            audit["capital_promoted"] = True
            audit["capital"] = dict(cap)

    bootstrap = str(normalized.get("bootstrap_state", "") or "").strip().upper()
    if bootstrap == "RUNNING_SUPERVISED":
        try:
            snapshot = coordinator.build_snapshot(
                trading_state=str(normalized.get("trading_state", "OFF") or "OFF"),
                activation_intent=bool(normalized.get("activation_intent", False)),
            )
            needs_thread_proof = bool(
                int(getattr(snapshot, "threads_launched", 0) or 0) <= 0
                or not bool(getattr(snapshot, "threads_confirmed_running", False))
            )
        except Exception:
            needs_thread_proof = True
        if needs_thread_proof:
            count, thread_reason = _verified_supervised_thread_count()
            audit["thread_reason"] = thread_reason
            if count > 0:
                recorder = getattr(coordinator, "record_threads_supervised", None)
                if callable(recorder):
                    recorder(count, bootstrap_state="RUNNING_SUPERVISED")
                    audit["threads_repaired"] = True
                    audit["thread_count"] = count
    return normalized, audit


def _patch_startup_coordinator(module: ModuleType) -> bool:
    module = _canonicalize_startup_coordinator(module)
    cls = getattr(module, "StartupCoordinator", None)
    if not isinstance(cls, type) or getattr(cls, _PATCH_ATTR, False):
        return False
    original = getattr(cls, "apply_bootstrap_transaction", None)
    if not callable(original):
        return False

    @wraps(original)
    def apply_bootstrap_transaction_v41(self: Any, *args: Any, **kwargs: Any):
        # The production call site uses keyword arguments.  Preserve positional
        # calls untouched rather than attempting to guess their schema.
        if args:
            return original(self, *args, **kwargs)

        before_dispatch = kwargs.get("dispatch_health_ready")
        normalized, audit = _normalize_transaction_kwargs(self, kwargs)
        if normalized.get("dispatch_health_ready") != before_dispatch:
            raise RuntimeError("v41 invariant violation: dispatch health mutated")

        if audit.get("capital_promoted"):
            cap = audit.get("capital", {})
            LOGGER.critical(
                "ACTIVATION_LIFECYCLE_V41_CAPITAL_HANDOFF marker=%s source_state=%s target_state=RUNNING real=%.2f usable=%.2f brokers=%s fresh=%s",
                MARKER,
                str(kwargs.get("capital_state", "unknown")),
                float(cap.get("real", 0.0) or 0.0),
                float(cap.get("usable", 0.0) or 0.0),
                int(cap.get("broker_count", 0) or 0),
                bool(cap.get("fresh", False)),
            )
        if audit.get("threads_repaired"):
            LOGGER.critical(
                "ACTIVATION_LIFECYCLE_V41_THREAD_HANDOFF marker=%s core_threads=%s bootstrap=RUNNING_SUPERVISED writer_renewal=healthy",
                MARKER,
                int(audit.get("thread_count", 0) or 0),
            )

        result = original(self, **normalized)
        try:
            snapshot = result[0]
            LOGGER.info(
                "ACTIVATION_LIFECYCLE_V41_TRANSACTION marker=%s capital=%s threads=%s/%s authority=%s nonce=%s dispatch_health=%s runtime_authority=%s",
                MARKER,
                getattr(snapshot, "capital_state", "unknown"),
                int(getattr(snapshot, "threads_launched", 0) or 0),
                bool(getattr(snapshot, "threads_confirmed_running", False)),
                bool(getattr(snapshot, "authority_ready", False)),
                bool(getattr(snapshot, "nonce_ready", False)),
                bool(getattr(snapshot, "dispatch_health_ready", False)),
                getattr(snapshot, "runtime_authority_state", "unknown"),
            )
        except Exception:
            pass
        return result

    setattr(apply_bootstrap_transaction_v41, _PATCH_ATTR, True)
    cls.apply_bootstrap_transaction = apply_bootstrap_transaction_v41
    setattr(cls, _PATCH_ATTR, True)
    LOGGER.critical(
        "ACTIVATION_LIFECYCLE_V41_COORDINATOR_PATCHED marker=%s module=%s fail_closed=true",
        MARKER,
        module.__name__,
    )
    return True


def _interesting(name: str) -> bool:
    text = str(name or "")
    return text in {"bot.startup_coordinator", "startup_coordinator"}


def _patch_loaded() -> bool:
    changed = False
    seen: set[int] = set()
    for name in ("bot.startup_coordinator", "startup_coordinator"):
        module = sys.modules.get(name)
        if not isinstance(module, ModuleType) or id(module) in seen:
            continue
        seen.add(id(module))
        try:
            changed = _patch_startup_coordinator(module) or changed
        except Exception as exc:
            LOGGER.exception(
                "ACTIVATION_LIFECYCLE_V41_PATCH_FAILED marker=%s module=%s err=%s",
                MARKER,
                name,
                exc,
            )
    return changed


def install_import_hook() -> bool:
    with _LOCK:
        _patch_loaded()
        if not getattr(builtins, _INSTALL_FLAG, False):
            original_import = builtins.__import__

            @wraps(original_import)
            def importing(name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0):
                result = original_import(name, globals, locals, fromlist, level)
                if _interesting(name):
                    _patch_loaded()
                return result

            builtins.__import__ = importing
            setattr(builtins, _INSTALL_FLAG, True)

        if not getattr(importlib, _IMPORTLIB_FLAG, False):
            original_import_module = importlib.import_module

            @wraps(original_import_module)
            def import_module(name: str, package: Optional[str] = None):
                result = original_import_module(name, package)
                if _interesting(name):
                    _patch_loaded()
                return result

            importlib.import_module = import_module  # type: ignore[assignment]
            setattr(importlib, _IMPORTLIB_FLAG, True)

        os.environ["NIJA_ACTIVATION_LIFECYCLE_HANDOFF_V41_INSTALLED"] = "1"
        LOGGER.critical(
            "ACTIVATION_LIFECYCLE_HANDOFF_V41_INSTALLED marker=%s force_activation=false capital_synthesis=false dispatch_health_bypass=false",
            MARKER,
        )
        return True


def install() -> bool:
    return install_import_hook()
