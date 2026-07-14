"""Repair the Phase 3 candidate-to-execution handoff.

Root cause
----------
The core loop admits/scored market frames with 50 candles, but the execution
loop re-fetches the same symbol and historically required 100 candles. A valid
ranked candidate could therefore disappear after selection without ever calling
``execute_action``. A second exchange fetch also made the handoff vulnerable to
short/empty transient responses.

This patch keeps the existing safety, liquidity, TPE, risk, and profitability
gates intact. It only:

* aligns the execution-frame minimum with the scoring minimum (50 candles), and
* reuses the already-validated frame for the remainder of the same cycle.

The source repair mutates the deepest live ``_phase3_scan_and_enter`` function
object in place. Existing wrappers retain references to that same object, so the
fix works even when several runtime patches already wrap the method.
"""

from __future__ import annotations

import builtins
import inspect
import logging
import os
import sys
import textwrap
import threading
import time
from functools import wraps
from types import FunctionType, ModuleType
from typing import Any, Iterable

logger = logging.getLogger("nija.phase3_execution_handoff_repair")

_MARKER = "20260713c"
_CANONICAL_MODULE = "bot.nija_core_loop"
_PHASE3_PATCH_ATTR = f"_nija_phase3_exec_threshold_repaired_{_MARKER}"
_FETCH_PATCH_ATTR = f"_nija_phase3_frame_cache_repaired_{_MARKER}"
_HOOK_ATTR = f"_NIJA_PHASE3_EXEC_HANDOFF_HOOK_{_MARKER}"
_INSTALL_LOCK = threading.RLock()
_MIN_CANDLES = 50


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)) or default)
    except (TypeError, ValueError):
        return float(default)


def _iter_function_graph(root: Any) -> Iterable[FunctionType]:
    """Yield wrapper/base functions reachable from ``root`` exactly once."""
    pending = [root]
    seen: set[int] = set()
    while pending:
        candidate = pending.pop(0)
        if not isinstance(candidate, FunctionType):
            continue
        identity = id(candidate)
        if identity in seen:
            continue
        seen.add(identity)
        yield candidate

        wrapped = getattr(candidate, "__wrapped__", None)
        if isinstance(wrapped, FunctionType):
            pending.append(wrapped)

        closure = getattr(candidate, "__closure__", None) or ()
        for cell in closure:
            try:
                value = cell.cell_contents
            except ValueError:
                continue
            if isinstance(value, FunctionType):
                pending.append(value)


def _find_phase3_source_function(method: Any) -> FunctionType | None:
    needle = "if df is None or len(df) < 100:"
    for function in _iter_function_graph(method):
        try:
            source = inspect.getsource(function)
        except (OSError, IOError, TypeError):
            continue
        if needle in source and function.__name__ == "_phase3_scan_and_enter":
            return function
    return None


def _compile_repaired_phase3(target: FunctionType) -> FunctionType:
    source_lines, start_line = inspect.getsourcelines(target)
    source = textwrap.dedent("".join(source_lines))

    threshold_needle = "if df is None or len(df) < 100:"
    if source.count(threshold_needle) != 1:
        raise RuntimeError(
            "phase3 execution threshold signature changed; expected exactly one "
            f"{threshold_needle!r}, found {source.count(threshold_needle)}"
        )

    repaired = source.replace(
        threshold_needle,
        "if df is None or len(df) < 50:",
        1,
    )
    repaired = repaired.replace(
        '"df_len=%d (need>=100) at execution time; "',
        '"df_len=%d (need>=50) at execution time; "',
        1,
    )
    repaired = repaired.replace(
        '"symbol passed scoring (need>=50) but failed exec re-fetch. "',
        '"execution frame fell below the shared 50-candle minimum. "',
        1,
    )
    repaired = repaired.replace(
        'f"df_len={_df_exec_len} threshold=100 — "',
        'f"df_len={_df_exec_len} threshold=50 — "',
        1,
    )

    # Preserve useful traceback line numbers even though only one method is
    # recompiled. The function has no closure variables; globals remain the
    # canonical nija_core_loop module dictionary.
    padded_source = ("\n" * max(0, start_line - 1)) + repaired
    namespace: dict[str, Any] = {}
    code = compile(padded_source, target.__code__.co_filename, "exec")
    exec(code, target.__globals__, namespace)
    replacement = namespace.get(target.__name__)
    if not isinstance(replacement, FunctionType):
        raise RuntimeError("recompiled Phase 3 function was not produced")
    if replacement.__code__.co_freevars != target.__code__.co_freevars:
        raise RuntimeError("recompiled Phase 3 closure contract changed")
    return replacement


def _repair_phase3_threshold(cls: type) -> bool:
    current = getattr(cls, "_phase3_scan_and_enter", None)
    if not callable(current):
        return False

    target = _find_phase3_source_function(current)
    if target is None:
        logger.warning(
            "PHASE3_EXEC_HANDOFF_SOURCE_NOT_FOUND marker=%s class=%s",
            _MARKER,
            getattr(cls, "__name__", "unknown"),
        )
        return False
    if getattr(target, _PHASE3_PATCH_ATTR, False):
        return True

    replacement = _compile_repaired_phase3(target)
    target.__code__ = replacement.__code__
    target.__defaults__ = replacement.__defaults__
    target.__kwdefaults__ = replacement.__kwdefaults__
    target.__annotations__ = dict(getattr(replacement, "__annotations__", {}) or {})
    setattr(target, _PHASE3_PATCH_ATTR, True)

    logger.critical(
        "PHASE3_EXECUTION_THRESHOLD_ALIGNED marker=%s class=%s scoring_min=%d execution_min=%d",
        _MARKER,
        getattr(cls, "__name__", "unknown"),
        _MIN_CANDLES,
        _MIN_CANDLES,
    )
    print(
        f"[NIJA-PRINT] PHASE3_EXECUTION_THRESHOLD_ALIGNED marker={_MARKER} "
        f"scoring_min={_MIN_CANDLES} execution_min={_MIN_CANDLES}",
        flush=True,
    )
    return True


def _wrap_fetch_df_cache(cls: type) -> bool:
    original = getattr(cls, "_fetch_df", None)
    if not callable(original):
        return False
    if getattr(original, _FETCH_PATCH_ATTR, False):
        return True

    @wraps(original)
    def _cached_fetch(self: Any, broker: Any, symbol: Any, *args: Any, **kwargs: Any):
        ttl_s = max(1.0, _env_float("NIJA_PHASE3_FRAME_CACHE_TTL_S", 60.0))
        key = (id(broker), str(symbol or "").upper())
        now = time.monotonic()

        lock = getattr(self, "_nija_phase3_frame_cache_lock", None)
        if lock is None:
            lock = threading.RLock()
            setattr(self, "_nija_phase3_frame_cache_lock", lock)
        cache = getattr(self, "_nija_phase3_frame_cache", None)
        if not isinstance(cache, dict):
            cache = {}
            setattr(self, "_nija_phase3_frame_cache", cache)

        with lock:
            cached = cache.get(key)
            if cached is not None:
                cached_at, cached_df = cached
                try:
                    cached_len = len(cached_df)
                except Exception:
                    cached_len = 0
                if now - float(cached_at) <= ttl_s and cached_len >= _MIN_CANDLES:
                    logger.debug(
                        "PHASE3_FRAME_CACHE_HIT marker=%s symbol=%s candles=%d age_s=%.3f",
                        _MARKER,
                        key[1],
                        cached_len,
                        now - float(cached_at),
                    )
                    return cached_df
                cache.pop(key, None)

        result = original(self, broker, symbol, *args, **kwargs)
        try:
            result_len = len(result) if result is not None else 0
        except Exception:
            result_len = 0
        if result_len >= _MIN_CANDLES:
            with lock:
                cache[key] = (now, result)
                # Keep the cache bounded on long-running processes.
                if len(cache) > 256:
                    oldest = sorted(cache.items(), key=lambda item: float(item[1][0]))[:64]
                    for old_key, _ in oldest:
                        cache.pop(old_key, None)
            logger.debug(
                "PHASE3_FRAME_CACHE_STORE marker=%s symbol=%s candles=%d",
                _MARKER,
                key[1],
                result_len,
            )
        return result

    setattr(_cached_fetch, _FETCH_PATCH_ATTR, True)
    setattr(_cached_fetch, "__wrapped__", original)
    setattr(cls, "_fetch_df", _cached_fetch)
    logger.critical(
        "PHASE3_VALIDATED_FRAME_REUSE_PATCHED marker=%s class=%s ttl_s=%.1f",
        _MARKER,
        getattr(cls, "__name__", "unknown"),
        max(1.0, _env_float("NIJA_PHASE3_FRAME_CACHE_TTL_S", 60.0)),
    )
    return True


def _patch_module(module: ModuleType | None) -> bool:
    if not isinstance(module, ModuleType):
        return False
    if getattr(module, "__name__", "") != _CANONICAL_MODULE:
        return False
    cls = getattr(module, "NijaCoreLoop", None)
    if not isinstance(cls, type):
        return False

    threshold_ok = _repair_phase3_threshold(cls)
    cache_ok = _wrap_fetch_df_cache(cls)
    if threshold_ok and cache_ok:
        logger.warning(
            "PHASE3_EXECUTION_HANDOFF_REPAIRED marker=%s module=%s",
            _MARKER,
            _CANONICAL_MODULE,
        )
    return threshold_ok and cache_ok


def _try_patch_loaded() -> bool:
    module = sys.modules.get(_CANONICAL_MODULE)
    return _patch_module(module if isinstance(module, ModuleType) else None)


def install_import_hook() -> None:
    """Install an idempotent import hook and patch an already-loaded core loop."""
    with _INSTALL_LOCK:
        _try_patch_loaded()
        if getattr(builtins, _HOOK_ATTR, False):
            return

        original_import = builtins.__import__

        def _guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
            module = original_import(name, globals, locals, fromlist, level)
            try:
                loaded = sys.modules.get(_CANONICAL_MODULE)
                if isinstance(loaded, ModuleType):
                    _patch_module(loaded)
            except Exception as exc:  # fail open; startup must continue with loud telemetry
                logger.exception(
                    "PHASE3_EXECUTION_HANDOFF_PATCH_FAILED marker=%s import=%s error=%s",
                    _MARKER,
                    name,
                    exc,
                )
            return module

        builtins.__import__ = _guarded_import
        setattr(builtins, _HOOK_ATTR, True)
        logger.warning(
            "PHASE3_EXECUTION_HANDOFF_HOOK_INSTALLED marker=%s canonical_module=%s",
            _MARKER,
            _CANONICAL_MODULE,
        )
