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
_MARKER = "20260709an"
_HOOK_FLAG = "_NIJA_PHASE3_SCAN_STALL_GUARD_HOOK_20260709AN"
_PHASE3_PATCH_ATTR = "_nija_phase3_scan_stall_guard_20260709an"
_FETCH_PATCH_ATTR = "_nija_phase3_fetch_deadline_guard_20260709an"
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


def _df_len(df: Any) -> int:
    try:
        return int(len(df))
    except Exception:
        return 0


def _has_volume(df: Any) -> bool:
    try:
        return bool("volume" in getattr(df, "columns", []))
    except Exception:
        return False


def _recent_volume_positive(df: Any) -> bool:
    if not _has_volume(df):
        return False
    try:
        vol = df["volume"].tail(20)
        return bool(float(vol.max() or 0.0) > 0.0 or float(vol.iloc[-1] or 0.0) > 0.0)
    except Exception:
        return False


def _cacheable_df(df: Any) -> bool:
    min_rows = max(10, _int_env("NIJA_PHASE3_MARKET_DATA_CACHE_MIN_ROWS", 50))
    return df is not None and _df_len(df) >= min_rows and _has_volume(df) and _recent_volume_positive(df)


def _weak_df(df: Any) -> bool:
    if df is None:
        return True
    if _df_len(df) < 10:
        return True
    if not _has_volume(df):
        return True
    if not _recent_volume_positive(df):
        return True
    return False


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
        cursor = int(
            getattr(
                owner,
                "_nija_phase3_scan_cursor_20260709an",
                getattr(owner, "_nija_phase3_scan_cursor_20260709am", getattr(owner, "_nija_phase3_scan_cursor_20260709al", 0)),
            )
            or 0
        )
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
        setattr(owner, "_nija_phase3_scan_cursor_20260709an", next_cursor)
        setattr(owner, "_nija_phase3_scan_cursor_20260709am", next_cursor)
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
            deadline = float(
                getattr(
                    self,
                    "_nija_phase3_deadline_ts_20260709an",
                    getattr(self, "_nija_phase3_deadline_ts_20260709am", getattr(self, "_nija_phase3_deadline_ts_20260709al", 0.0)),
                )
                or 0.0
            )
            symbol = str(args[1] if len(args) > 1 else kwargs.get("symbol", "unknown") or "unknown")
            deadline_elapsed = deadline > 0.0 and time.monotonic() > deadline
            cache_active = bool(getattr(self, "_nija_phase3_market_data_cache_active_20260709an", False))
            cache = getattr(self, "_nija_phase3_market_data_cache_20260709an", None)
            if not isinstance(cache, dict):
                cache = {}
                try:
                    setattr(self, "_nija_phase3_market_data_cache_20260709an", cache)
                except Exception:
                    pass

            if deadline_elapsed:
                if _truthy("NIJA_PHASE3_FETCH_DEADLINE_SKIP_ENABLED", False):
                    cached = cache.get(symbol) if cache_active else None
                    if _cacheable_df(cached):
                        logger.warning(
                            "PHASE3_SELECTED_CANDIDATE_CACHE_REUSED marker=%s symbol=%s reason=deadline_elapsed_hard_skip_cache_hit rows=%d",
                            _MARKER,
                            symbol,
                            _df_len(cached),
                        )
                        return cached
                    logger.warning(
                        "PHASE3_SCAN_STALL_GUARD_DEADLINE_SKIP marker=%s symbol=%s reason=phase3_deadline_elapsed hard_skip=true cache_hit=false",
                        _MARKER,
                        symbol,
                    )
                    return None
                logger.warning(
                    "PHASE3_SELECTED_CANDIDATE_PRESERVE_FETCH marker=%s symbol=%s reason=deadline_elapsed_allow_fetch hard_skip=false",
                    _MARKER,
                    symbol,
                )

            started = time.monotonic()
            result = original_fetch(self, *args, **kwargs)
            elapsed = time.monotonic() - started

            if cache_active and _cacheable_df(result):
                try:
                    cache[symbol] = result
                    logger.debug(
                        "PHASE3_MARKET_DATA_CACHE_STORED marker=%s symbol=%s rows=%d",
                        _MARKER,
                        symbol,
                        _df_len(result),
                    )
                except Exception:
                    pass
            elif cache_active and _weak_df(result):
                cached = cache.get(symbol)
                if _cacheable_df(cached):
                    logger.warning(
                        "PHASE3_SELECTED_CANDIDATE_CACHE_REUSED marker=%s symbol=%s reason=late_fetch_weak_or_insufficient fetched_rows=%d cached_rows=%d",
                        _MARKER,
                        symbol,
                        _df_len(result),
                        _df_len(cached),
                    )
                    return cached

            slow_s = max(0.25, _float_env("NIJA_PHASE3_SLOW_FETCH_LOG_S", 2.5))
            if elapsed >= slow_s:
                logger.warning(
                    "PHASE3_SCAN_STALL_GUARD_SLOW_FETCH marker=%s symbol=%s elapsed_s=%.2f deadline_elapsed=%s",
                    _MARKER,
                    symbol,
                    elapsed,
                    deadline_elapsed,
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
            previous_deadline_an = getattr(self, "_nija_phase3_deadline_ts_20260709an", 0.0)
            previous_deadline_am = getattr(self, "_nija_phase3_deadline_ts_20260709am", 0.0)
            previous_deadline_al = getattr(self, "_nija_phase3_deadline_ts_20260709al", 0.0)
            previous_cache_active = getattr(self, "_nija_phase3_market_data_cache_active_20260709an", False)
            previous_cache = getattr(self, "_nija_phase3_market_data_cache_20260709an", None)
            deadline_ts = time.monotonic() + timeout_s
            setattr(self, "_nija_phase3_deadline_ts_20260709an", deadline_ts)
            setattr(self, "_nija_phase3_deadline_ts_20260709am", deadline_ts)
            setattr(self, "_nija_phase3_deadline_ts_20260709al", deadline_ts)
            setattr(self, "_nija_phase3_market_data_cache_active_20260709an", True)
            setattr(self, "_nija_phase3_market_data_cache_20260709an", {})
            logger.critical(
                "PHASE3_SCAN_STALL_GUARD_WINDOW marker=%s original_symbols=%d selected_symbols=%d cursor=%d next_cursor=%d available_slots=%s deadline_s=%.1f hard_deadline_skip=%s cache_same_cycle_market_data=true",
                _MARKER,
                int(meta.get("original", 0)),
                int(meta.get("selected", 0)),
                int(meta.get("cursor", 0)),
                int(meta.get("next_cursor", 0)),
                available_slots,
                timeout_s,
                _truthy("NIJA_PHASE3_FETCH_DEADLINE_SKIP_ENABLED", False),
            )
            print(
                f"[NIJA-PRINT] PHASE3_SCAN_STALL_GUARD_WINDOW marker={_MARKER} original={meta.get('original', 0)} selected={meta.get('selected', 0)} cursor={meta.get('cursor', 0)} next={meta.get('next_cursor', 0)} hard_skip={_truthy('NIJA_PHASE3_FETCH_DEADLINE_SKIP_ENABLED', False)} cache=true",
                flush=True,
            )
            started = time.monotonic()
            try:
                result = original_phase3(self, broker, snapshot, selected, available_slots, *args, **kwargs)
            finally:
                try:
                    setattr(self, "_nija_phase3_deadline_ts_20260709an", previous_deadline_an)
                    setattr(self, "_nija_phase3_deadline_ts_20260709am", previous_deadline_am)
                    setattr(self, "_nija_phase3_deadline_ts_20260709al", previous_deadline_al)
                    setattr(self, "_nija_phase3_market_data_cache_active_20260709an", previous_cache_active)
                    if isinstance(previous_cache, dict):
                        setattr(self, "_nija_phase3_market_data_cache_20260709an", previous_cache)
                    else:
                        setattr(self, "_nija_phase3_market_data_cache_20260709an", {})
                except Exception:
                    pass
            elapsed = time.monotonic() - started
            if elapsed >= timeout_s:
                logger.warning(
                    "PHASE3_SCAN_STALL_GUARD_OVER_DEADLINE marker=%s elapsed_s=%.2f deadline_s=%.2f selected_symbols=%d original_symbols=%d action=preserved_ranked_candidates_cache_enabled",
                    _MARKER,
                    elapsed,
                    timeout_s,
                    int(meta.get("selected", 0)),
                    int(meta.get("original", 0)),
                )
            else:
                logger.info(
                    "PHASE3_SCAN_STALL_GUARD_COMPLETE marker=%s elapsed_s=%.2f selected_symbols=%d original_symbols=%d cache_enabled=true",
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
        logger.warning(
            "PHASE3_SCAN_STALL_GUARD_PATCHED marker=%s module=%s preserve_selected_candidates=true cache_same_cycle_market_data=true",
            _MARKER,
            getattr(module, "__name__", "unknown"),
        )
        print(
            f"[NIJA-PRINT] PHASE3_SCAN_STALL_GUARD_PATCHED marker={_MARKER} preserve_selected_candidates=true cache_same_cycle_market_data=true",
            flush=True,
        )
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
    logger.warning("PHASE3_SCAN_STALL_GUARD_INSTALL_COMPLETE marker=%s preserve_selected_candidates=true cache_same_cycle_market_data=true", _MARKER)


def install() -> None:
    install_import_hook()
