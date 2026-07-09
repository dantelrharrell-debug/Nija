from __future__ import annotations

import builtins
import logging
import os
import sys
import time
from functools import wraps
from types import ModuleType
from typing import Any, Iterable

logger = logging.getLogger("nija.phase3_scan_stall_guard")
_MARKER = "20260709al"
_HOOK_FLAG = "_NIJA_PHASE3_SCAN_STALL_GUARD_HOOK_20260709AL"
_PHASE3_PATCH_ATTR = "_nija_phase3_scan_stall_guard_20260709al"
_FETCH_PATCH_ATTR = "_nija_phase3_fetch_deadline_guard_20260709al"
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}


def _truthy(name: str, default: bool = True) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in _TRUE


def _int_env(name: str, default: int) -> int:
    try:
        return int(float(os.environ.get(name, str(default)) or default))
    except Exception:
        return default


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)) or default)
    except Exception:
        return default


def _as_symbol_list(symbols: Iterable[Any] | None) -> list[Any]:
    if symbols is None:
        return []
    try:
        return list(symbols)
    except TypeError:
        return []


def _window_symbols(owner: Any, symbols: Iterable[Any] | None, available_slots: int) -> tuple[list[Any], dict[str, int]]:
    original = _as_symbol_list(symbols)
    total = len(original)
    if total <= 0:
        return original, {"original": 0, "selected": 0, "cursor": 0, "next_cursor": 0}
    if not _truthy("NIJA_PHASE3_SCAN_STALL_GUARD_ENABLED", True):
        return original, {"original": total, "selected": total, "cursor": 0, "next_cursor": 0}

    hard_limit = max(10, _int_env("NIJA_PHASE3_SCAN_MAX_SYMBOLS", 80))
    slot_count = max(1, int(available_slots or 1))
    slot_window = max(20, slot_count * max(5, _int_env("NIJA_PHASE3_SCAN_SYMBOLS_PER_SLOT", 10)))
    limit = min(total, max(10, min(hard_limit, slot_window)))
    if total <= limit:
        return original, {"original": total, "selected": total, "cursor": 0, "next_cursor": 0}

    try:
        cursor = int(getattr(owner, "_nija_phase3_scan_cursor_20260709al", 0) or 0)
    except Exception:
        cursor = 0
    cursor %= total
    end = cursor + limit
    if end <= total:
        selected = original[cursor:end]
    else:
        selected = original[cursor:] + original[: end - total]
    next_cursor = end % total
    try:
        setattr(owner, "_nija_phase3_scan_cursor_20260709al", next_cursor)
    except Exception:
        pass
    return selected, {"original": total, "selected": len(selected), "cursor": cursor, "next_cursor": next_cursor}


def _patch_core_loop_module(module: ModuleType) -> bool:
    cls = getattr(module, "NijaCoreLoop", None)
    if not isinstance(cls, type):
        return False
    patched = False

    original_fetch = getattr(cls, "_fetch_df", None)
    if callable(original_fetch) and not getattr(original_fetch, _FETCH_PATCH_ATTR, False):
        @wraps(original_fetch)
        def fetch_df_with_phase3_deadline(self: Any, *args: Any, **kwargs: Any):
            deadline = float(getattr(self, "_nija_phase3_deadline_ts_20260709al", 0.0) or 0.0)
            if deadline > 0.0 and time.monotonic() > deadline:
                symbol = args[1] if len(args) > 1 else kwargs.get("symbol", "unknown")
                logger.warning(
                    "PHASE3_SCAN_STALL_GUARD_DEADLINE_SKIP marker=%s symbol=%s reason=phase3_deadline_elapsed",
                    _MARKER,
                    symbol,
                )
                return None
            started = time.monotonic()
            result = original_fetch(self, *args, **kwargs)
            elapsed = time.monotonic() - started
            slow_s = max(0.25, _float_env("NIJA_PHASE3_SLOW_FETCH_LOG_S", 2.5))
            if elapsed >= slow_s:
                symbol = args[1] if len(args) > 1 else kwargs.get("symbol", "unknown")
                logger.warning(
                    "PHASE3_SCAN_STALL_GUARD_SLOW_FETCH marker=%s symbol=%s elapsed_s=%.2f",
                    _MARKER,
                    symbol,
                    elapsed,
                )
            return result

        setattr(fetch_df_with_phase3_deadline, _FETCH_PATCH_ATTR, True)
        setattr(cls, "_fetch_df", fetch_df_with_phase3_deadline)
        patched = True

    original_phase3 = getattr(cls, "_phase3_scan_and_enter", None)
    if callable(original_phase3) and not getattr(original_phase3, _PHASE3_PATCH_ATTR, False):
        @wraps(original_phase3)
        def phase3_with_stall_guard(self: Any, broker: Any, snapshot: Any, symbols: Any, available_slots: int, *args: Any, **kwargs: Any):
            selected, meta = _window_symbols(self, symbols, int(available_slots or 0))
            timeout_s = max(5.0, _float_env("NIJA_PHASE3_SCAN_DEADLINE_S", 24.0))
            previous_deadline = getattr(self, "_nija_phase3_deadline_ts_20260709al", 0.0)
            setattr(self, "_nija_phase3_deadline_ts_20260709al", time.monotonic() + timeout_s)
            logger.critical(
                "PHASE3_SCAN_STALL_GUARD_WINDOW marker=%s original_symbols=%d selected_symbols=%d cursor=%d next_cursor=%d available_slots=%s deadline_s=%.1f",
                _MARKER,
                int(meta.get("original", 0)),
                int(meta.get("selected", 0)),
                int(meta.get("cursor", 0)),
                int(meta.get("next_cursor", 0)),
                available_slots,
                timeout_s,
            )
            print(
                f"[NIJA-PRINT] PHASE3_SCAN_STALL_GUARD_WINDOW marker={_MARKER} original={meta.get('original', 0)} selected={meta.get('selected', 0)} cursor={meta.get('cursor', 0)} next={meta.get('next_cursor', 0)}",
                flush=True,
            )
            started = time.monotonic()
            try:
                result = original_phase3(self, broker, snapshot, selected, available_slots, *args, **kwargs)
            finally:
                try:
                    setattr(self, "_nija_phase3_deadline_ts_20260709al", previous_deadline)
                except Exception:
                    pass
            elapsed = time.monotonic() - started
            if elapsed >= timeout_s:
                logger.warning(
                    "PHASE3_SCAN_STALL_GUARD_OVER_DEADLINE marker=%s elapsed_s=%.2f deadline_s=%.2f selected_symbols=%d original_symbols=%d",
                    _MARKER,
                    elapsed,
                    timeout_s,
                    int(meta.get("selected", 0)),
                    int(meta.get("original", 0)),
                )
            else:
                logger.info(
                    "PHASE3_SCAN_STALL_GUARD_COMPLETE marker=%s elapsed_s=%.2f selected_symbols=%d original_symbols=%d",
                    _MARKER,
                    elapsed,
                    int(meta.get("selected", 0)),
                    int(meta.get("original", 0)),
                )
            return result

        setattr(phase3_with_stall_guard, _PHASE3_PATCH_ATTR, True)
        setattr(cls, "_phase3_scan_and_enter", phase3_with_stall_guard)
        patched = True

    if patched:
        logger.warning("PHASE3_SCAN_STALL_GUARD_PATCHED marker=%s module=%s", _MARKER, getattr(module, "__name__", "unknown"))
        print(f"[NIJA-PRINT] PHASE3_SCAN_STALL_GUARD_PATCHED marker={_MARKER}", flush=True)
    return patched


def _patch_loaded() -> None:
    for name in ("bot.nija_core_loop", "nija_core_loop"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            try:
                _patch_core_loop_module(module)
            except Exception as exc:
                logger.warning("PHASE3_SCAN_STALL_GUARD_PATCH_FAILED marker=%s module=%s err=%s", _MARKER, name, exc)


def install_import_hook() -> None:
    _patch_loaded()
    if getattr(builtins, _HOOK_FLAG, False):
        return
    original_import = builtins.__import__

    def importing(name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        text = str(name)
        if text.endswith("nija_core_loop") or text in {"bot.nija_core_loop", "nija_core_loop"}:
            _patch_loaded()
        return module

    builtins.__import__ = importing
    setattr(builtins, _HOOK_FLAG, True)
    logger.warning("PHASE3_SCAN_STALL_GUARD_INSTALL_COMPLETE marker=%s", _MARKER)


def install() -> None:
    install_import_hook()
