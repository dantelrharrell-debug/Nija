from __future__ import annotations

import builtins
import logging
import os
import sys
from functools import wraps
from types import ModuleType
from typing import Any

logger = logging.getLogger("nija.hard_controls_capital_authority_bridge")
_MARKER = "20260709t"
_HOOK_FLAG = "_NIJA_HARD_CONTROLS_CA_BRIDGE_HOOK_V20260709T"
_CSM_ATTR = "_nija_hard_controls_ca_bridge_csm_v20260709t"
_MODULE_ATTR = "_nija_hard_controls_ca_bridge_module_v20260709t"
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}


def _truthy(name: str, default: str = "false") -> bool:
    return str(os.environ.get(name, default)).strip().lower() in _TRUE


def _f(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        amount = float(value)
        if amount != amount:
            return default
        return amount
    except Exception:
        return default


def _i(value: Any, default: int = 0) -> int:
    try:
        return int(float(value or 0))
    except Exception:
        return default


def _writer_authority_ready() -> tuple[bool, str]:
    state = os.environ.get("NIJA_RUNTIME_TRADING_STATE", "")
    exec_auth = os.environ.get("NIJA_RUNTIME_EXECUTION_AUTHORITY", "")
    token = os.environ.get("NIJA_WRITER_FENCING_TOKEN", "").strip()
    generation = os.environ.get("NIJA_WRITER_LEASE_GENERATION", "").strip()
    ok = bool((state in {"LIVE_ACTIVE", "RUNNING", "RUN_READY"} or exec_auth == "1") and exec_auth == "1" and token and generation)
    return ok, f"state={state or 'unknown'} exec_auth={exec_auth or '0'} token={bool(token)} generation={generation or 'missing'}"


def _capital_authority_snapshot_ready() -> tuple[bool, str, dict[str, Any]]:
    if not _truthy("LIVE_CAPITAL_VERIFIED"):
        return False, "live_capital_not_verified", {}
    if _truthy("DRY_RUN_MODE") or _truthy("PAPER_MODE"):
        return False, "simulation_mode", {}
    writer_ok, writer_detail = _writer_authority_ready()
    if not writer_ok:
        return False, f"writer_authority_not_ready {writer_detail}", {}
    try:
        try:
            from bot.capital_authority import get_capital_authority
        except ImportError:
            from capital_authority import get_capital_authority  # type: ignore[import]
        ca = get_capital_authority()
    except Exception as exc:
        return False, f"capital_authority_unavailable:{exc}", {}

    hydrated = bool(getattr(ca, "is_hydrated", False))
    first_snap = bool(
        getattr(ca, "first_snap_accepted", False)
        or getattr(ca, "_first_snap_accepted", False)
        or getattr(ca, "first_snapshot_accepted", False)
    )
    real = 0.0
    usable = 0.0
    risk = 0.0
    for attr in ("total_capital", "real_capital", "available_capital"):
        real = max(real, _f(getattr(ca, attr, 0.0)))
    for getter_name in ("get_real_capital", "get_total_capital"):
        getter = getattr(ca, getter_name, None)
        if callable(getter):
            try:
                real = max(real, _f(getter()))
            except Exception:
                pass
    for attr in ("usable_capital", "risk_capital", "available_capital"):
        usable = max(usable, _f(getattr(ca, attr, 0.0)))
    getter = getattr(ca, "get_usable_capital", None)
    if callable(getter):
        try:
            usable = max(usable, _f(getter()))
        except Exception:
            pass
    for attr in ("risk_capital", "usable_capital"):
        risk = max(risk, _f(getattr(ca, attr, 0.0)))

    valid_brokers = max(
        _i(getattr(ca, "valid_broker_count", 0)),
        _i(getattr(ca, "registered_broker_count", 0)),
    )
    try:
        broker_values = getattr(ca, "broker_values", None) or getattr(ca, "values", None) or {}
        if isinstance(broker_values, dict):
            valid_brokers = max(valid_brokers, sum(1 for value in broker_values.values() if _f(value) > 0.0))
    except Exception:
        pass
    fresh = True
    for method_name in ("is_fresh", "is_stale"):
        method = getattr(ca, method_name, None)
        if callable(method):
            try:
                if method_name == "is_fresh":
                    fresh = bool(method(ttl_s=_f(os.environ.get("NIJA_HARD_CONTROLS_CA_BRIDGE_TTL_S"), 240.0)))
                else:
                    fresh = not bool(method())
            except TypeError:
                try:
                    fresh = bool(method()) if method_name == "is_fresh" else not bool(method())
                except Exception:
                    pass
            except Exception:
                pass
    min_brokers = max(1, _i(os.environ.get("NIJA_HARD_CONTROLS_CA_BRIDGE_MIN_BROKERS"), 2))
    min_capital = max(1.0, _f(os.environ.get("NIJA_HARD_CONTROLS_CA_BRIDGE_MIN_CAPITAL_USD"), 10.0))
    ready = bool(hydrated and real >= min_capital and usable > 0.0 and valid_brokers >= min_brokers and fresh)
    detail = {
        "hydrated": hydrated,
        "first_snap": first_snap,
        "real": real,
        "usable": usable,
        "risk": risk,
        "valid_brokers": valid_brokers,
        "fresh": fresh,
        "writer": writer_detail,
    }
    if ready:
        return True, f"ca_bridge_ready marker={_MARKER} real={real:.2f} usable={usable:.2f} valid_brokers={valid_brokers} fresh={fresh} {writer_detail}", detail
    return False, f"ca_bridge_not_ready marker={_MARKER} hydrated={hydrated} real={real:.2f} usable={usable:.2f} valid_brokers={valid_brokers} fresh={fresh} {writer_detail}", detail


def _patch_csm_module(module: ModuleType) -> bool:
    cls = getattr(module, "CapitalCSMv2", None)
    if not isinstance(cls, type):
        return False
    patched = False
    original = getattr(cls, "is_live_capital_valid", None)
    if callable(original) and not getattr(original, _CSM_ATTR, False):
        @wraps(original)
        def is_live_capital_valid(self: Any) -> bool:
            try:
                if bool(original(self)):
                    return True
            except Exception:
                pass
            ready, reason, _detail = _capital_authority_snapshot_ready()
            if ready:
                logger.critical("HARD_CONTROLS_CA_BRIDGE_APPLIED marker=%s surface=CapitalCSMv2.is_live_capital_valid detail=%s", _MARKER, reason)
                print(f"[NIJA-PRINT] HARD_CONTROLS_CA_BRIDGE_APPLIED marker={_MARKER} detail={reason}", flush=True)
                return True
            logger.warning("HARD_CONTROLS_CA_BRIDGE_WAITING marker=%s surface=CapitalCSMv2.is_live_capital_valid detail=%s", _MARKER, reason)
            return False
        setattr(is_live_capital_valid, _CSM_ATTR, True)
        setattr(is_live_capital_valid, "__wrapped__", original)
        setattr(cls, "is_live_capital_valid", is_live_capital_valid)
        patched = True

    original_mod_fn = getattr(module, "is_live_capital_valid", None)
    if callable(original_mod_fn) and not getattr(original_mod_fn, _MODULE_ATTR, False):
        @wraps(original_mod_fn)
        def module_is_live_capital_valid() -> bool:
            try:
                if bool(original_mod_fn()):
                    return True
            except Exception:
                pass
            ready, reason, _detail = _capital_authority_snapshot_ready()
            if ready:
                logger.critical("HARD_CONTROLS_CA_BRIDGE_APPLIED marker=%s surface=module.is_live_capital_valid detail=%s", _MARKER, reason)
                return True
            logger.warning("HARD_CONTROLS_CA_BRIDGE_WAITING marker=%s surface=module.is_live_capital_valid detail=%s", _MARKER, reason)
            return False
        setattr(module_is_live_capital_valid, _MODULE_ATTR, True)
        setattr(module_is_live_capital_valid, "__wrapped__", original_mod_fn)
        setattr(module, "is_live_capital_valid", module_is_live_capital_valid)
        patched = True

    if patched:
        logger.warning("HARD_CONTROLS_CA_BRIDGE_PATCHED marker=%s module=%s", _MARKER, getattr(module, "__name__", ""))
        print(f"[NIJA-PRINT] HARD_CONTROLS_CA_BRIDGE_PATCHED marker={_MARKER} module={getattr(module, '__name__', '')}", flush=True)
    return patched


def _try_patch_loaded() -> bool:
    patched = False
    for name, module in list(sys.modules.items()):
        if isinstance(module, ModuleType) and name.endswith("capital_csm_v2"):
            try:
                patched = _patch_csm_module(module) or patched
            except Exception as exc:
                logger.warning("HARD_CONTROLS_CA_BRIDGE_PATCH_FAILED marker=%s module=%s err=%s", _MARKER, name, exc)
    return patched


def install_import_hook() -> None:
    _try_patch_loaded()
    if getattr(builtins, _HOOK_FLAG, False):
        return
    original_import = builtins.__import__

    def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        try:
            if "capital_csm_v2" in str(name):
                _try_patch_loaded()
        except Exception as exc:
            logger.warning("HARD_CONTROLS_CA_BRIDGE_IMPORT_HOOK_FAILED marker=%s name=%s err=%s", _MARKER, name, exc)
        return module

    builtins.__import__ = guarded_import
    setattr(builtins, _HOOK_FLAG, True)
    logger.warning("HARD_CONTROLS_CA_BRIDGE_IMPORT_HOOK marker=%s", _MARKER)


def install() -> None:
    install_import_hook()
