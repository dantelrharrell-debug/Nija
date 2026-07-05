from __future__ import annotations

import builtins
import logging
import os
import sys
import threading
import time
from types import ModuleType
from typing import Any, Callable

logger = logging.getLogger("nija.fallback_strict_score_floor_adaptive")
_PATCHED = False
_MONITOR_STARTED = False
_WRAP_ATTR = "_nija_fallback_strict_score_floor_adaptive_wrapped_v20260705a"


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default) or default)
    except Exception:
        return default


def _score_from(sig: Any, payload: Any) -> float:
    for source in (sig, payload if isinstance(payload, dict) else None):
        if source is None:
            continue
        for key in ("composite_score", "entry_score", "score", "confidence"):
            try:
                value = getattr(source, key, None) if source is not payload else source.get(key)
                score = float(value or 0.0)
                if score > 0.0:
                    return score
            except Exception:
                continue
    return 0.0


def _threshold_from(sig: Any, payload: Any) -> float:
    for source in (sig, payload if isinstance(payload, dict) else None):
        if source is None:
            continue
        for key in ("threshold_used", "ai_threshold", "entry_threshold", "threshold"):
            try:
                value = getattr(source, key, None) if source is not payload else source.get(key)
                threshold = float(value or 0.0)
                if threshold > 0.0:
                    return threshold
            except Exception:
                continue
    return 0.0


def _adaptive_floor(sig: Any, payload: Any, configured_floor: float) -> float:
    safety_floor = _float_env("NIJA_FALLBACK_ADAPTIVE_SCORE_FLOOR", 30.0)
    threshold = _threshold_from(sig, payload)
    if threshold > 0.0:
        # Require at least ~2x the active Phase-3 floor, but do not require the
        # old hard 40/60 fallback floor during repeated zero-entry cycles.
        safety_floor = max(safety_floor, threshold * 2.0)
    safety_floor = max(20.0, min(safety_floor, 45.0))
    return min(configured_floor, safety_floor)


def _make_adaptive_enforcer(original: Callable[..., Any]) -> Callable[..., Any]:
    if getattr(original, _WRAP_ATTR, False):
        return original

    def _adaptive_enforce(payload: Any, *, sig: Any, symbol: str) -> Any:
        configured = _float_env("NIJA_FALLBACK_STRICT_SCORE_FLOOR", 60.0)
        score = _score_from(sig, payload)
        dynamic_floor = _adaptive_floor(sig, payload, configured)
        old_env = os.environ.get("NIJA_FALLBACK_STRICT_SCORE_FLOOR")
        should_lower = bool(score >= dynamic_floor and dynamic_floor < configured)
        if should_lower:
            os.environ["NIJA_FALLBACK_STRICT_SCORE_FLOOR"] = f"{dynamic_floor:.6f}"
            logger.critical(
                "FALLBACK_STRICT_SCORE_FLOOR_ADAPTIVE_APPLIED marker=20260705a symbol=%s score=%.1f configured_floor=%.1f adaptive_floor=%.1f threshold=%.1f",
                symbol,
                score,
                configured,
                dynamic_floor,
                _threshold_from(sig, payload),
            )
            print(
                f"[NIJA-PRINT] FALLBACK_STRICT_SCORE_FLOOR_ADAPTIVE_APPLIED marker=20260705a symbol={symbol} score={score:.1f} configured_floor={configured:.1f} adaptive_floor={dynamic_floor:.1f}",
                flush=True,
            )
        try:
            return original(payload, sig=sig, symbol=symbol)
        finally:
            if should_lower:
                if old_env is None:
                    os.environ.pop("NIJA_FALLBACK_STRICT_SCORE_FLOOR", None)
                else:
                    os.environ["NIJA_FALLBACK_STRICT_SCORE_FLOOR"] = old_env

    setattr(_adaptive_enforce, _WRAP_ATTR, True)
    setattr(_adaptive_enforce, "__wrapped__", original)
    return _adaptive_enforce


def _patch_core_loop_module(module: ModuleType) -> bool:
    global _PATCHED
    cls = getattr(module, "NijaCoreLoop", None)
    if not isinstance(cls, type):
        return False
    method = getattr(cls, "_build_forced_fallback_entry_analysis", None)
    if not callable(method):
        return False
    globals_map = getattr(method, "__globals__", None)
    if not isinstance(globals_map, dict):
        return False
    original = globals_map.get("_enforce_fallback_positive_ev")
    if not callable(original):
        return False
    if getattr(original, _WRAP_ATTR, False):
        _PATCHED = True
        return True
    globals_map["_enforce_fallback_positive_ev"] = _make_adaptive_enforcer(original)
    _PATCHED = True
    logger.warning(
        "FALLBACK_STRICT_SCORE_FLOOR_ADAPTIVE_PATCHED marker=20260705a module=%s class=%s",
        getattr(module, "__name__", "<unknown>"),
        cls.__name__,
    )
    print(
        f"[NIJA-PRINT] FALLBACK_STRICT_SCORE_FLOOR_ADAPTIVE_PATCHED marker=20260705a module={getattr(module, '__name__', '<unknown>')}",
        flush=True,
    )
    return True


def _try_patch_loaded() -> bool:
    patched = False
    for name in ("bot.nija_core_loop", "nija_core_loop"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            try:
                patched = _patch_core_loop_module(module) or patched
            except Exception as exc:
                logger.warning("FALLBACK_STRICT_SCORE_FLOOR_ADAPTIVE_PATCH_FAILED module=%s err=%s", name, exc)
    return patched


def _start_monitor() -> None:
    global _MONITOR_STARTED
    if _MONITOR_STARTED:
        return
    _MONITOR_STARTED = True

    def _monitor() -> None:
        deadline = time.time() + float(os.getenv("NIJA_PATCH_MONITOR_SECONDS", "300") or "300")
        patched = False
        while time.time() < deadline:
            patched = _try_patch_loaded() or patched
            if patched:
                break
            time.sleep(0.5)
        logger.warning("FALLBACK_STRICT_SCORE_FLOOR_ADAPTIVE_MONITOR_COMPLETE marker=20260705a patched=%s", patched)

    threading.Thread(target=_monitor, name="fallback-score-floor-adaptive-monitor", daemon=True).start()
    logger.warning("FALLBACK_STRICT_SCORE_FLOOR_ADAPTIVE_MONITOR_STARTED marker=20260705a")


def install_import_hook() -> None:
    _try_patch_loaded()
    _start_monitor()
    if getattr(builtins, "_NIJA_FALLBACK_SCORE_FLOOR_ADAPTIVE_IMPORT_HOOK_INSTALLED", False):
        return
    original_import = builtins.__import__

    def guarded_import(name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0) -> Any:
        module = original_import(name, globals, locals, fromlist, level)
        if name in {"bot.nija_core_loop", "nija_core_loop"} or str(name).endswith("nija_core_loop"):
            _try_patch_loaded()
        return module

    builtins.__import__ = guarded_import
    setattr(builtins, "_NIJA_FALLBACK_SCORE_FLOOR_ADAPTIVE_IMPORT_HOOK_INSTALLED", True)
    logger.warning("FALLBACK_STRICT_SCORE_FLOOR_ADAPTIVE_INSTALL_COMPLETE marker=20260705a patched=%s", _PATCHED)


def install() -> None:
    install_import_hook()
