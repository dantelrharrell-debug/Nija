from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
import time
from types import ModuleType
from typing import Any, Callable, Optional

logger = logging.getLogger("nija.live_capital_first_snapshot_latch")
_MARKER = "20260705g"
_INSTALL_LOCK = threading.Lock()
_ORIGINAL_IMPORT_MODULE: Optional[Callable[..., Any]] = None
_MONITOR_STARTED = False
_PATCHED = False


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


def _ca_positive_snapshot() -> tuple[bool, str]:
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
        getter = getattr(ca, "get_usable_capital", None)
        if callable(getter):
            try:
                usable = max(usable, _safe_float(getter()))
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
        broker_min = max(1, _safe_int(os.environ.get("NIJA_FIRST_SNAPSHOT_LATCH_MIN_VALID_BROKERS", "2"), 2))
        broker_ok = valid_brokers >= broker_min or (registered_brokers >= broker_min and real > 0.0)
        ok = hydrated and first_snap and broker_ok and real > 0.0 and usable > 0.0
        detail = (
            f"marker={_MARKER} hydrated={hydrated} first_snap={first_snap} "
            f"valid_brokers={valid_brokers} registered_brokers={registered_brokers} "
            f"real={real:.2f} usable={usable:.2f} fresh={fresh}"
        )
        return ok, detail
    except Exception as exc:
        return False, f"capital_probe_failed:{exc}"


def _patch_bootstrap_module(module: ModuleType) -> bool:
    global _PATCHED
    original = getattr(module, "_capital_ready", None)
    if not callable(original) or getattr(original, "_nija_first_snapshot_latch_v20260705g", False):
        return False

    def _capital_ready_with_first_snapshot() -> tuple[bool, str]:
        ok, detail = _ca_positive_snapshot()
        if ok:
            logger.critical("LIVE_CAPITAL_FIRST_SNAPSHOT_LATCH_APPLIED marker=%s surface=execution_bootstrap_authority detail=%s", _MARKER, detail)
            print(f"[NIJA-PRINT] LIVE_CAPITAL_FIRST_SNAPSHOT_LATCH_APPLIED marker={_MARKER} surface=execution_bootstrap_authority detail={detail}", flush=True)
            return True, detail
        return original()

    setattr(_capital_ready_with_first_snapshot, "_nija_first_snapshot_latch_v20260705g", True)
    setattr(_capital_ready_with_first_snapshot, "__wrapped__", original)
    setattr(module, "_capital_ready", _capital_ready_with_first_snapshot)
    _PATCHED = True
    logger.warning("LIVE_CAPITAL_FIRST_SNAPSHOT_LATCH_PATCHED marker=%s module=%s", _MARKER, getattr(module, "__name__", "<unknown>"))
    return True


def _try_patch_loaded() -> bool:
    patched = False
    for name in ("bot.execution_bootstrap_authority_repair_patch", "execution_bootstrap_authority_repair_patch"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            patched = _patch_bootstrap_module(module) or patched
    return patched


def _start_monitor() -> None:
    global _MONITOR_STARTED
    if _MONITOR_STARTED:
        return
    _MONITOR_STARTED = True

    def _monitor() -> None:
        deadline = time.time() + float(os.environ.get("NIJA_PATCH_MONITOR_SECONDS", "300") or "300")
        while time.time() < deadline:
            if _try_patch_loaded():
                return
            time.sleep(0.25)
        logger.warning("LIVE_CAPITAL_FIRST_SNAPSHOT_LATCH_MONITOR_EXPIRED marker=%s patched=%s", _MARKER, _PATCHED)

    threading.Thread(target=_monitor, name="live-capital-first-snapshot-latch-monitor", daemon=True).start()
    logger.warning("LIVE_CAPITAL_FIRST_SNAPSHOT_LATCH_MONITOR_STARTED marker=%s", _MARKER)


def install_import_hook() -> None:
    global _ORIGINAL_IMPORT_MODULE
    with _INSTALL_LOCK:
        os.environ.setdefault("NIJA_ALLOW_FIRST_SNAPSHOT_FRESHNESS_LATCH", "true")
        _try_patch_loaded()
        _start_monitor()
        if _ORIGINAL_IMPORT_MODULE is not None:
            logger.warning("LIVE_CAPITAL_FIRST_SNAPSHOT_LATCH_INSTALL_COMPLETE marker=%s already_installed=True patched=%s", _MARKER, _PATCHED)
            return
        _ORIGINAL_IMPORT_MODULE = importlib.import_module

        def _wrapped_import_module(name: str, package: str | None = None):
            module = _ORIGINAL_IMPORT_MODULE(name, package)  # type: ignore[misc]
            if name in {"bot.execution_bootstrap_authority_repair_patch", "execution_bootstrap_authority_repair_patch"}:
                _patch_bootstrap_module(module)
            return module

        importlib.import_module = _wrapped_import_module  # type: ignore[assignment]
        logger.warning("LIVE_CAPITAL_FIRST_SNAPSHOT_LATCH_INSTALL_COMPLETE marker=%s patched=%s env=%s", _MARKER, _PATCHED, os.environ.get("NIJA_ALLOW_FIRST_SNAPSHOT_FRESHNESS_LATCH"))
        print(f"[NIJA-PRINT] LIVE_CAPITAL_FIRST_SNAPSHOT_LATCH_INSTALL_COMPLETE marker={_MARKER}", flush=True)


def install() -> None:
    install_import_hook()
