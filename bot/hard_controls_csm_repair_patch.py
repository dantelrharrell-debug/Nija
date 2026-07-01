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


def _truthy(name: str) -> bool:
    return str(os.environ.get(name, "")).strip().lower() in {"1", "true", "yes", "enabled", "on", "y"}


def _capital_authority_live_ready() -> tuple[bool, str]:
    if not _truthy("LIVE_CAPITAL_VERIFIED"):
        return False, "live_capital_not_verified"
    if _truthy("DRY_RUN_MODE") or _truthy("PAPER_MODE"):
        return False, "simulation_mode"
    try:
        try:
            from bot.capital_authority import get_capital_authority
        except ImportError:
            from capital_authority import get_capital_authority  # type: ignore[import]
        ca = get_capital_authority()
        hydrated = bool(getattr(ca, "is_hydrated", False))
        first_snap = bool(getattr(ca, "first_snap_accepted", False))
        valid_brokers = int(getattr(ca, "valid_broker_count", 0) or 0)
        real = 0.0
        usable = 0.0
        try:
            real = max(real, float(getattr(ca, "total_capital", 0.0) or 0.0))
        except Exception:
            pass
        getter = getattr(ca, "get_real_capital", None)
        if callable(getter):
            try:
                real = max(real, float(getter() or 0.0))
            except Exception:
                pass
        usable_getter = getattr(ca, "get_usable_capital", None)
        if callable(usable_getter):
            try:
                usable = max(usable, float(usable_getter() or 0.0))
            except Exception:
                pass
        fresh = True
        fresh_getter = getattr(ca, "is_fresh", None)
        if callable(fresh_getter):
            try:
                fresh = bool(fresh_getter(ttl_s=180.0))
            except TypeError:
                fresh = bool(fresh_getter())
            except Exception:
                fresh = False
        if hydrated and first_snap and valid_brokers > 0 and real > 0.0 and usable > 0.0 and fresh:
            return True, f"ca_ready real={real:.2f} usable={usable:.2f} valid_brokers={valid_brokers}"
        return False, f"ca_not_ready hydrated={hydrated} first_snap={first_snap} valid_brokers={valid_brokers} real={real:.2f} usable={usable:.2f} fresh={fresh}"
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
    if getattr(original, "_nija_hard_controls_csm_repair_wrapped", False):
        _PATCHED = True
        return True

    def _patched_can_trade(self: Any, user_id: str, *args: Any, **kwargs: Any):
        allowed, reason = original(self, user_id, *args, **kwargs)
        if allowed:
            return allowed, reason
        reason_text = str(reason or "")
        if "CAPITAL NOT VALIDATED" not in reason_text or "CSM-v2" not in reason_text:
            return allowed, reason
        ready, detail = _capital_authority_live_ready()
        if not ready:
            logger.critical(
                "HARD_CONTROLS_CSM_REPAIR_WAITING user_id=%s detail=%s original_reason=%s",
                user_id,
                detail,
                reason_text,
            )
            return allowed, reason
        logger.critical(
            "HARD_CONTROLS_CSM_REPAIR_APPLIED user_id=%s detail=%s original_reason=%s",
            user_id,
            detail,
            reason_text,
        )
        print(
            f"[NIJA-PRINT] HARD_CONTROLS_CSM_REPAIR_APPLIED | user_id={user_id} detail={detail}",
            flush=True,
        )
        return True, None

    setattr(_patched_can_trade, "_nija_hard_controls_csm_repair_wrapped", True)
    setattr(cls, "can_trade", _patched_can_trade)
    _PATCHED = True
    logger.warning("HARD_CONTROLS_CSM_REPAIR_PATCHED module=%s", getattr(module, "__name__", "<unknown>"))
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
        logger.warning("HARD_CONTROLS_CSM_REPAIR_MONITOR_EXPIRED patched=%s", _PATCHED)

    threading.Thread(target=_monitor, name="hard-controls-csm-repair-monitor", daemon=True).start()
    logger.warning("HARD_CONTROLS_CSM_REPAIR_MONITOR_STARTED")


def install_import_hook() -> None:
    global _ORIGINAL_IMPORT_MODULE
    with _INSTALL_LOCK:
        _try_patch_loaded()
        _start_monitor()
        if _ORIGINAL_IMPORT_MODULE is not None:
            logger.warning("HARD_CONTROLS_CSM_REPAIR_INSTALL_COMPLETE already_installed=True patched=%s", _PATCHED)
            return
        _ORIGINAL_IMPORT_MODULE = importlib.import_module

        def _wrapped_import_module(name: str, package: str | None = None):
            module = _ORIGINAL_IMPORT_MODULE(name, package)  # type: ignore[misc]
            if name in {"controls", "bot.controls"}:
                _install_on_module(module)
            return module

        importlib.import_module = _wrapped_import_module  # type: ignore[assignment]
        logger.warning("HARD_CONTROLS_CSM_REPAIR_INSTALL_COMPLETE patched=%s", _PATCHED)
