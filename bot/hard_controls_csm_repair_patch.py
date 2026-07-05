from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
import time
from types import ModuleType
from typing import Any, Callable, Optional

logger = logging.getLogger("nija.hard_controls_csm_repair")
_ORIGINAL_IMPORT_MODULE: Optional[Callable[..., Any]] = None
_PATCHED = False
_MONITOR_STARTED = False
_INSTALL_LOCK = threading.Lock()
_MARKER = "20260705d"


def _truthy(name: str) -> bool:
    return str(os.environ.get(name, "")).strip().lower() in {"1", "true", "yes", "enabled", "on", "y"}


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value or 0)
    except Exception:
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value or 0.0)
    except Exception:
        return default


def _writer_authority_ok() -> tuple[bool, str]:
    """Require live writer authority markers when accepting a freshness-latched snapshot."""
    state = os.environ.get("NIJA_RUNTIME_TRADING_STATE", "")
    execution_authority = os.environ.get("NIJA_RUNTIME_EXECUTION_AUTHORITY", "")
    token = os.environ.get("NIJA_WRITER_FENCING_TOKEN", "").strip()
    generation = os.environ.get("NIJA_WRITER_LEASE_GENERATION", "").strip()
    live_state_ok = state in {"LIVE_ACTIVE", "RUNNING", "RUN_READY"} or execution_authority == "1"
    ok = bool(live_state_ok and execution_authority == "1" and token and generation)
    return ok, f"state={state or 'unknown'} exec_auth={execution_authority or '0'} token={bool(token)} generation={generation or 'missing'}"


def _capital_authority_live_ready() -> tuple[bool, str]:
    """Return whether CapitalAuthority proves live capital is execution-safe.

    This repair does not force trades and does not ignore balance safety. It only
    handles the startup race where CSM-v2/HardControls still says INITIALIZING
    while CapitalAuthority already has a real hydrated first snapshot, positive
    usable capital, and multiple valid brokers.  Zero capital, simulation mode,
    missing writer authority, and missing broker coverage still fail closed.
    """

    if not _truthy("LIVE_CAPITAL_VERIFIED"):
        return False, "live_capital_not_verified"
    if _truthy("DRY_RUN_MODE") or _truthy("PAPER_MODE"):
        return False, "simulation_mode"
    writer_ok, writer_detail = _writer_authority_ok()
    if not writer_ok:
        return False, f"writer_not_ready {writer_detail}"
    try:
        try:
            from bot.capital_authority import get_capital_authority
        except ImportError:
            from capital_authority import get_capital_authority  # type: ignore[import]
        ca = get_capital_authority()
        hydrated = bool(getattr(ca, "is_hydrated", False))
        first_snap = bool(getattr(ca, "first_snap_accepted", False))
        valid_brokers = _safe_int(getattr(ca, "valid_broker_count", 0))
        registered_brokers = _safe_int(getattr(ca, "registered_broker_count", 0))
        real = 0.0
        usable = 0.0
        for attr in ("total_capital", "real_capital", "available_capital"):
            real = max(real, _safe_float(getattr(ca, attr, 0.0)))
        getter = getattr(ca, "get_real_capital", None)
        if callable(getter):
            try:
                real = max(real, _safe_float(getter()))
            except Exception:
                pass
        for attr in ("usable_capital", "risk_capital"):
            usable = max(usable, _safe_float(getattr(ca, attr, 0.0)))
        usable_getter = getattr(ca, "get_usable_capital", None)
        if callable(usable_getter):
            try:
                usable = max(usable, _safe_float(usable_getter()))
            except Exception:
                pass
        fresh = True
        fresh_getter = getattr(ca, "is_fresh", None)
        if callable(fresh_getter):
            try:
                fresh = bool(fresh_getter(ttl_s=float(os.environ.get("NIJA_HARD_CONTROLS_CAPITAL_FRESH_TTL_S", "180") or "180")))
            except TypeError:
                fresh = bool(fresh_getter())
            except Exception:
                fresh = False

        broker_min = max(1, _safe_int(os.environ.get("NIJA_HARD_CONTROLS_MIN_VALID_BROKERS", "2"), 2))
        broker_ok = valid_brokers >= broker_min or (registered_brokers >= broker_min and real > 0.0)
        strict_ready = hydrated and broker_ok and real > 0.0 and usable > 0.0 and fresh
        freshness_latch_ready = (
            hydrated
            and first_snap
            and broker_ok
            and valid_brokers >= broker_min
            and real > 0.0
            and usable > 0.0
            and not fresh
            and _truthy("NIJA_ALLOW_FIRST_SNAPSHOT_FRESHNESS_LATCH") is not False
        )
        if strict_ready or freshness_latch_ready:
            mode = "ca_ready" if strict_ready else "ca_ready_freshness_latched"
            return True, (
                f"{mode} marker={_MARKER} real={real:.2f} usable={usable:.2f} "
                f"valid_brokers={valid_brokers} registered_brokers={registered_brokers} "
                f"hydrated={hydrated} first_snap={first_snap} fresh={fresh} {writer_detail}"
            )
        return False, (
            f"ca_not_ready marker={_MARKER} hydrated={hydrated} first_snap={first_snap} "
            f"valid_brokers={valid_brokers} registered_brokers={registered_brokers} "
            f"real={real:.2f} usable={usable:.2f} fresh={fresh} {writer_detail}"
        )
    except Exception as exc:
        return False, f"ca_probe_failed:{exc}"


def _install_on_module(module: ModuleType) -> bool:
    global _PATCHED
    cls = getattr(module, "HardControls", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "can_trade", None)
    if not callable(original):
        return False
    if getattr(original, "_nija_hard_controls_csm_repair_wrapped_v20260705d", False):
        _PATCHED = True
        return True

    def _patched_can_trade(self: Any, user_id: str, *args: Any, **kwargs: Any):
        allowed, reason = original(self, user_id, *args, **kwargs)
        if allowed:
            return allowed, reason
        reason_text = str(reason or "")
        if "CAPITAL NOT VALIDATED" not in reason_text:
            return allowed, reason
        ready, detail = _capital_authority_live_ready()
        if not ready:
            logger.critical(
                "HARD_CONTROLS_CSM_REPAIR_WAITING marker=%s user_id=%s detail=%s original_reason=%s",
                _MARKER,
                user_id,
                detail,
                reason_text,
            )
            return allowed, reason
        logger.critical(
            "HARD_CONTROLS_CSM_REPAIR_APPLIED marker=%s user_id=%s detail=%s original_reason=%s",
            _MARKER,
            user_id,
            detail,
            reason_text,
        )
        print(
            f"[NIJA-PRINT] HARD_CONTROLS_CSM_REPAIR_APPLIED marker={_MARKER} | user_id={user_id} detail={detail}",
            flush=True,
        )
        return True, None

    setattr(_patched_can_trade, "_nija_hard_controls_csm_repair_wrapped_v20260705d", True)
    setattr(_patched_can_trade, "__wrapped__", original)
    setattr(cls, "can_trade", _patched_can_trade)
    _PATCHED = True
    logger.warning("HARD_CONTROLS_CSM_REPAIR_PATCHED marker=%s module=%s", _MARKER, getattr(module, "__name__", "<unknown>"))
    return True


def _try_patch_loaded() -> bool:
    patched = False
    for name in ("controls", "bot.controls"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            patched = _install_on_module(module) or patched
    return patched


def _start_monitor() -> None:
    global _MONITOR_STARTED
    if _MONITOR_STARTED:
        return
    _MONITOR_STARTED = True

    def _monitor() -> None:
        deadline = time.time() + float(os.environ.get("NIJA_PATCH_MONITOR_SECONDS", "240") or "240")
        while time.time() < deadline:
            if _try_patch_loaded():
                return
            time.sleep(0.25)
        logger.warning("HARD_CONTROLS_CSM_REPAIR_MONITOR_EXPIRED marker=%s patched=%s", _MARKER, _PATCHED)

    threading.Thread(target=_monitor, name="hard-controls-csm-repair-monitor", daemon=True).start()
    logger.warning("HARD_CONTROLS_CSM_REPAIR_MONITOR_STARTED marker=%s", _MARKER)


def install_import_hook() -> None:
    global _ORIGINAL_IMPORT_MODULE
    with _INSTALL_LOCK:
        _try_patch_loaded()
        _start_monitor()
        if _ORIGINAL_IMPORT_MODULE is not None:
            logger.warning("HARD_CONTROLS_CSM_REPAIR_INSTALL_COMPLETE marker=%s already_installed=True patched=%s", _MARKER, _PATCHED)
            return
        _ORIGINAL_IMPORT_MODULE = importlib.import_module

        def _wrapped_import_module(name: str, package: str | None = None):
            module = _ORIGINAL_IMPORT_MODULE(name, package)  # type: ignore[misc]
            if name in {"controls", "bot.controls"}:
                _install_on_module(module)
            return module

        importlib.import_module = _wrapped_import_module  # type: ignore[assignment]
        logger.warning("HARD_CONTROLS_CSM_REPAIR_INSTALL_COMPLETE marker=%s patched=%s", _MARKER, _PATCHED)
