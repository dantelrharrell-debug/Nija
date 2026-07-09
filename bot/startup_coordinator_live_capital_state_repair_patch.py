from __future__ import annotations

import builtins
import logging
import os
import sys
import time
from functools import wraps
from types import ModuleType
from typing import Any

logger = logging.getLogger("nija.startup_coordinator_live_capital_state_repair")
_MARKER = "20260709ak"
_HOOK_FLAG = "_NIJA_STARTUP_COORDINATOR_LIVE_CAPITAL_STATE_REPAIR_HOOK_20260709AK"
_BUILD_PATCH_ATTR = "_nija_live_capital_state_repair_build_snapshot_20260709ak"
_APPLY_PATCH_ATTR = "_nija_live_capital_state_repair_apply_bootstrap_20260709ak"
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}
_LAST_REPAIR_TS = 0.0


def _truthy(name: str, default: str = "false") -> bool:
    raw = os.environ.get(name)
    if raw is None:
        raw = default
    return str(raw).strip().lower() in _TRUE


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)) or default)
    except Exception:
        return default


def _capital_probe() -> dict[str, Any]:
    detail: dict[str, Any] = {
        "hydrated": False,
        "first_snap": False,
        "valid_brokers": 0,
        "real": 0.0,
        "usable": 0.0,
        "fresh": True,
        "source": "unavailable",
    }
    try:
        try:
            from bot.capital_authority import get_capital_authority
        except ImportError:
            from capital_authority import get_capital_authority  # type: ignore[import]
        ca = get_capital_authority()
        detail["source"] = "capital_authority"
        detail["hydrated"] = bool(getattr(ca, "is_hydrated", False))
        detail["first_snap"] = bool(
            getattr(ca, "first_snap_accepted", False)
            or getattr(ca, "_first_snap_accepted", False)
            or getattr(ca, "first_snapshot_accepted", False)
        )
        for attr in ("valid_broker_count", "registered_broker_count", "ca_valid_brokers"):
            try:
                detail["valid_brokers"] = max(int(detail["valid_brokers"]), int(getattr(ca, attr, 0) or 0))
            except Exception:
                pass
        balances = getattr(ca, "broker_balances", None) or getattr(ca, "_broker_balances", None)
        if isinstance(balances, dict):
            detail["valid_brokers"] = max(int(detail["valid_brokers"]), len([v for v in balances.values() if v is not None]))
        for attr in ("total_capital", "real_capital", "usable_capital", "available_capital"):
            try:
                value = float(getattr(ca, attr, 0.0) or 0.0)
                if "usable" in attr or "available" in attr:
                    detail["usable"] = max(float(detail["usable"]), value)
                else:
                    detail["real"] = max(float(detail["real"]), value)
            except Exception:
                pass
        for method_name, target in (("get_real_capital", "real"), ("get_usable_capital", "usable")):
            getter = getattr(ca, method_name, None)
            if callable(getter):
                try:
                    detail[target] = max(float(detail[target]), float(getter() or 0.0))
                except Exception:
                    pass
        fresh_getter = getattr(ca, "is_fresh", None)
        if callable(fresh_getter):
            try:
                detail["fresh"] = bool(fresh_getter(ttl_s=180.0))
            except TypeError:
                detail["fresh"] = bool(fresh_getter())
            except Exception:
                detail["fresh"] = False
    except Exception as exc:
        detail["source"] = f"capital_authority_error:{exc}"

    if float(detail["usable"] or 0.0) <= 0.0 and float(detail["real"] or 0.0) > 0.0:
        detail["usable"] = float(detail["real"])
    return detail


def _kill_switch_clear() -> tuple[bool, str]:
    try:
        try:
            from bot.kill_switch import get_kill_switch
        except ImportError:
            from kill_switch import get_kill_switch  # type: ignore[import]
        active = bool(get_kill_switch().is_active())
        return (not active), "kill_switch_active" if active else "kill_switch_clear"
    except Exception as exc:
        return False, f"kill_switch_probe_failed:{exc}"


def _live_capital_ready() -> tuple[bool, str, dict[str, Any]]:
    if not _truthy("LIVE_CAPITAL_VERIFIED"):
        return False, "live_capital_not_verified", {}
    if _truthy("DRY_RUN_MODE") or _truthy("PAPER_MODE"):
        return False, "simulation_mode", {}
    if os.environ.get("NIJA_RUNTIME_TRADING_STATE", "").strip().upper() != "LIVE_ACTIVE":
        return False, "runtime_state_not_live_active", {}
    kill_ok, kill_detail = _kill_switch_clear()
    if not kill_ok:
        return False, kill_detail, {}
    if not str(os.environ.get("NIJA_WRITER_FENCING_TOKEN", "") or "").strip():
        return False, "writer_fencing_token_missing", {}
    if not str(os.environ.get("NIJA_WRITER_LEASE_GENERATION", "") or "").strip():
        return False, "writer_lease_generation_missing", {}

    probe = _capital_probe()
    hydrated = bool(probe.get("hydrated"))
    valid_brokers = int(probe.get("valid_brokers") or 0)
    real = float(probe.get("real") or 0.0)
    usable = float(probe.get("usable") or 0.0)
    fresh = bool(probe.get("fresh"))
    if not (hydrated and valid_brokers > 0 and real > 0.0 and usable > 0.0 and fresh):
        return (
            False,
            f"capital_not_ready hydrated={hydrated} valid_brokers={valid_brokers} real={real:.2f} usable={usable:.2f} fresh={fresh} source={probe.get('source')}",
            probe,
        )
    return (
        True,
        f"verified_live_capital hydrated={hydrated} first_snap={bool(probe.get('first_snap'))} valid_brokers={valid_brokers} real={real:.2f} usable={usable:.2f} fresh={fresh} source={probe.get('source')}",
        probe,
    )


def _repair_coordinator_capital(coordinator: Any, source: str) -> bool:
    global _LAST_REPAIR_TS
    ok, detail, probe = _live_capital_ready()
    if not ok:
        logger.warning("STARTUP_COORDINATOR_LIVE_CAPITAL_REPAIR_WAITING marker=%s source=%s detail=%s", _MARKER, source, detail)
        return False

    now = time.monotonic()
    throttle_s = max(0.0, _float_env("NIJA_STARTUP_COORDINATOR_CAPITAL_REPAIR_THROTTLE_S", 1.0))
    if throttle_s > 0 and now - _LAST_REPAIR_TS < throttle_s:
        return False
    _LAST_REPAIR_TS = now

    try:
        before = coordinator.build_snapshot(trading_state="LIVE_ACTIVE", activation_intent=True) if source != "build_snapshot" else None
    except Exception:
        before = None

    before_state = str(getattr(before, "capital_state", "unknown") if before is not None else "unknown")
    before_commit = int(getattr(before, "last_committed_snapshot_version", 0) or 0) if before is not None else 0
    real = float(probe.get("real") or 0.0)

    try:
        coordinator.record_capital_state(
            state="RUNNING",
            hydrated=True,
            balance=real,
            stale=False,
        )
        coordinator.record_activation_requested(
            requested=True,
            source=f"startup_coordinator_live_capital_repair:{source}:marker={_MARKER}",
        )
        after = coordinator.build_snapshot(trading_state="LIVE_ACTIVE", activation_intent=True)
        proof = coordinator.evaluate_system_readiness_proof(after)
        if bool(getattr(proof, "passed", False)):
            try:
                coordinator.finalize_activation_commit(after)
            except Exception as exc:
                logger.warning(
                    "STARTUP_COORDINATOR_LIVE_CAPITAL_REPAIR_COMMIT_SKIPPED marker=%s source=%s err=%s",
                    _MARKER,
                    source,
                    exc,
                )
        else:
            logger.warning(
                "STARTUP_COORDINATOR_LIVE_CAPITAL_REPAIR_PROOF_PENDING marker=%s source=%s first_blocking_gate=%s failed_gates=%s after_capital_state=%s runtime_authority=%s lifecycle=%s",
                _MARKER,
                source,
                getattr(proof, "first_blocking_gate", "unknown"),
                getattr(proof, "failed_gates", []),
                getattr(after, "capital_state", "unknown"),
                getattr(after, "runtime_authority_state", "unknown"),
                getattr(after, "lifecycle_phase", "unknown"),
            )
        logger.critical(
            "STARTUP_COORDINATOR_LIVE_CAPITAL_REPAIRED marker=%s source=%s before_capital_state=%s before_commit=%s after_capital_state=%s after_capital=%.2f runtime_authority=%s lifecycle=%s detail=%s",
            _MARKER,
            source,
            before_state,
            before_commit,
            getattr(after, "capital_state", "unknown"),
            float(getattr(after, "capital_balance", 0.0) or 0.0),
            getattr(after, "runtime_authority_state", "unknown"),
            getattr(after, "lifecycle_phase", "unknown"),
            detail,
        )
        print(
            f"[NIJA-PRINT] STARTUP_COORDINATOR_LIVE_CAPITAL_REPAIRED marker={_MARKER} source={source} capital=${real:.2f}",
            flush=True,
        )
        return True
    except Exception as exc:
        logger.warning("STARTUP_COORDINATOR_LIVE_CAPITAL_REPAIR_FAILED marker=%s source=%s err=%s", _MARKER, source, exc)
        return False


def _patch_startup_coordinator_module(module: ModuleType) -> bool:
    cls = getattr(module, "StartupCoordinator", None)
    if not isinstance(cls, type):
        return False
    patched = False

    original_build = getattr(cls, "build_snapshot", None)
    if callable(original_build) and not getattr(original_build, _BUILD_PATCH_ATTR, False):
        @wraps(original_build)
        def build_snapshot_with_live_capital_repair(self: Any, *args: Any, **kwargs: Any):
            trading_state = str(kwargs.get("trading_state", "") or (args[0] if args else "") or "").strip().upper()
            try:
                snap = original_build(self, *args, **kwargs)
            except Exception:
                raise
            try:
                cap_state = str(getattr(snap, "capital_state", "") or "").strip().upper()
                lifecycle = str(getattr(snap, "lifecycle_phase", "") or "").strip().upper()
                env_live = os.environ.get("NIJA_RUNTIME_TRADING_STATE", "").strip().upper() == "LIVE_ACTIVE"
                if env_live and (trading_state in {"", "UNKNOWN", "LIVE_ACTIVE"}) and (
                    cap_state in {"", "BOOT", "BOOT_IDLE", "UNKNOWN"} or lifecycle == "BOOT"
                ):
                    if _repair_coordinator_capital(self, "build_snapshot"):
                        snap = original_build(self, *args, **kwargs)
            except Exception as exc:
                logger.warning("STARTUP_COORDINATOR_LIVE_CAPITAL_BUILD_REPAIR_ERROR marker=%s err=%s", _MARKER, exc)
            return snap

        setattr(build_snapshot_with_live_capital_repair, _BUILD_PATCH_ATTR, True)
        setattr(cls, "build_snapshot", build_snapshot_with_live_capital_repair)
        patched = True

    original_apply = getattr(cls, "apply_bootstrap_transaction", None)
    if callable(original_apply) and not getattr(original_apply, _APPLY_PATCH_ATTR, False):
        @wraps(original_apply)
        def apply_bootstrap_transaction_with_capital_repair(self: Any, *args: Any, **kwargs: Any):
            try:
                if os.environ.get("NIJA_RUNTIME_TRADING_STATE", "").strip().upper() == "LIVE_ACTIVE":
                    _repair_coordinator_capital(self, "pre_apply_bootstrap_transaction")
            except Exception:
                pass
            result = original_apply(self, *args, **kwargs)
            try:
                if os.environ.get("NIJA_RUNTIME_TRADING_STATE", "").strip().upper() == "LIVE_ACTIVE":
                    _repair_coordinator_capital(self, "post_apply_bootstrap_transaction")
            except Exception:
                pass
            return result

        setattr(apply_bootstrap_transaction_with_capital_repair, _APPLY_PATCH_ATTR, True)
        setattr(cls, "apply_bootstrap_transaction", apply_bootstrap_transaction_with_capital_repair)
        patched = True

    if patched:
        logger.warning("STARTUP_COORDINATOR_LIVE_CAPITAL_REPAIR_PATCHED marker=%s module=%s", _MARKER, getattr(module, "__name__", "unknown"))
        print(f"[NIJA-PRINT] STARTUP_COORDINATOR_LIVE_CAPITAL_REPAIR_PATCHED marker={_MARKER}", flush=True)
    return patched


def _patch_execution_authority_module(module: ModuleType) -> bool:
    original = getattr(module, "can_execute", None)
    if not callable(original) or getattr(original, "_nija_live_capital_repair_can_execute_20260709ak", False):
        return bool(getattr(original, "_nija_live_capital_repair_can_execute_20260709ak", False))

    @wraps(original)
    def can_execute_with_live_capital_repair(*args: Any, **kwargs: Any):
        try:
            try:
                from bot.startup_coordinator import get_startup_coordinator
            except ImportError:
                from startup_coordinator import get_startup_coordinator  # type: ignore[import]
            _repair_coordinator_capital(get_startup_coordinator(), "pre_can_execute")
        except Exception:
            pass
        decision = original(*args, **kwargs)
        reason = str(getattr(decision, "reason", "") or getattr(decision, "reason_detail", "") or "").lower()
        if not bool(getattr(decision, "allowed", False)) and ("capital_state=boot_idle" in reason or "lifecycle_phase:boot" in reason or "lifecycle.phase" in reason):
            try:
                from bot.startup_coordinator import get_startup_coordinator
            except ImportError:
                from startup_coordinator import get_startup_coordinator  # type: ignore[import]
            if _repair_coordinator_capital(get_startup_coordinator(), "post_can_execute_block"):
                decision = original(*args, **kwargs)
        return decision

    setattr(can_execute_with_live_capital_repair, "_nija_live_capital_repair_can_execute_20260709ak", True)
    setattr(module, "can_execute", can_execute_with_live_capital_repair)
    logger.warning("STARTUP_COORDINATOR_LIVE_CAPITAL_EXEC_AUTH_PATCHED marker=%s module=%s", _MARKER, getattr(module, "__name__", "unknown"))
    return True


def _patch_loaded() -> None:
    for name in ("bot.startup_coordinator", "startup_coordinator"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            try:
                _patch_startup_coordinator_module(module)
            except Exception as exc:
                logger.warning("STARTUP_COORDINATOR_LIVE_CAPITAL_REPAIR_PATCH_FAILED marker=%s module=%s err=%s", _MARKER, name, exc)
    for name in ("bot.execution_authority_context", "execution_authority_context"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            try:
                _patch_execution_authority_module(module)
            except Exception as exc:
                logger.warning("STARTUP_COORDINATOR_LIVE_CAPITAL_EXEC_AUTH_PATCH_FAILED marker=%s module=%s err=%s", _MARKER, name, exc)


def install_import_hook() -> None:
    _patch_loaded()
    if getattr(builtins, _HOOK_FLAG, False):
        return
    original_import = builtins.__import__

    def importing(name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        text = str(name)
        if text.endswith("startup_coordinator") or text.endswith("execution_authority_context") or text in {"bot.startup_coordinator", "startup_coordinator", "bot.execution_authority_context", "execution_authority_context"}:
            _patch_loaded()
        return module

    builtins.__import__ = importing
    setattr(builtins, _HOOK_FLAG, True)
    logger.warning("STARTUP_COORDINATOR_LIVE_CAPITAL_REPAIR_INSTALL_COMPLETE marker=%s", _MARKER)


def install() -> None:
    install_import_hook()
