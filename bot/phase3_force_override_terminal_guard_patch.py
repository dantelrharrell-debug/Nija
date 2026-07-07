from __future__ import annotations

import ast
import importlib
import logging
import os
import sys
import textwrap
import threading
import time
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Optional

logger = logging.getLogger("nija.phase3_force_override_terminal_guard")

_MARKER = "PHASE3_FORCE_OVERRIDE_TERMINAL_GUARD_PATCHED marker=20260707k"
_PATCHED_ATTR = "_nija_phase3_force_override_terminal_guard_20260707k"
_CANONICAL_CORE_LOOP_MODULE = "bot.nija_core_loop"
_ORIGINAL_IMPORT_MODULE: Optional[Callable[..., Any]] = None
_INSTALL_LOCK = threading.Lock()
_MONITOR_STARTED = False
_PATCHED_CLASSES: set[str] = set()
_TRUTHY = {"1", "true", "yes", "on", "y", "enabled"}

_NON_OVERRIDEABLE_MARKERS = (
    "terminal_risk_hard_block",
    "hard_sector_limit_block",
    "entry_blocked_terminal_risk_hard_block",
    "portfolio exposure limit reached",
    "position blocked by risk engine",
    "sector limit enforcement",
    "hard sector limit block",
    "global_exposure_cap",
    "pretraderiskengine reject",
    "no_funded_broker_route",
    "zero_size_order",
    "zero_size_order_blocked",
)


def _env_truthy(name: str, default: str = "false") -> bool:
    return str(os.getenv(name, default)).strip().lower() in _TRUTHY


def _nija_phase3_non_overrideable_reason(reason: Any) -> bool:
    text = str(reason or "").strip().lower()
    return any(marker in text for marker in _NON_OVERRIDEABLE_MARKERS)


def _is_core_loop_module(module: ModuleType) -> bool:
    return str(getattr(module, "__name__", "")) == _CANONICAL_CORE_LOOP_MODULE


def _function_source_from_file(module: ModuleType, func_name: str) -> tuple[str, int]:
    path = Path(str(getattr(module, "__file__", "")))
    if not path.exists():
        raise FileNotFoundError(f"module file not found: {path}")
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
            segment = ast.get_source_segment(text, node)
            if not segment:
                raise RuntimeError(f"source segment missing for {func_name}")
            return textwrap.dedent(segment), int(getattr(node, "lineno", 0) or 0)
    raise RuntimeError(f"function {func_name} not found in {path}")


def _phase3_hold_skip_block() -> str:
    for module_name in ("bot.phase3_fallback_hold_skip_patch", "phase3_fallback_hold_skip_patch"):
        try:
            module = importlib.import_module(module_name)
            block = getattr(module, "_SKIP_BLOCK", "")
            if isinstance(block, str) and "PHASE3_FALLBACK_HOLD_SKIP_APPLIED" in block:
                return block
        except Exception:
            continue
    return ""


def _install_terminal_guard() -> bool:
    for module_name in ("bot.live_execution_terminal_guard_patch", "live_execution_terminal_guard_patch"):
        try:
            module = importlib.import_module(module_name)
            installer = getattr(module, "install_import_hook", None) or getattr(module, "install", None)
            if callable(installer):
                installer()
                logger.warning("PHASE3_FORCE_OVERRIDE_TERMINAL_GUARD_INSTALLED_DOWNSTREAM marker=20260707k module=%s", module_name)
                return True
        except Exception as exc:
            logger.debug("terminal guard install attempt failed module=%s err=%s", module_name, exc)
    logger.warning("PHASE3_FORCE_OVERRIDE_TERMINAL_GUARD_DOWNSTREAM_UNAVAILABLE marker=20260707k")
    return False


def _patch_core_loop(module: ModuleType) -> bool:
    if not _is_core_loop_module(module):
        return False
    cls = getattr(module, "NijaCoreLoop", None)
    if not isinstance(cls, type):
        return False

    current = getattr(cls, "_phase3_scan_and_enter", None)
    if not callable(current):
        return False
    if getattr(current, _PATCHED_ATTR, False):
        _PATCHED_CLASSES.add(f"{getattr(module, '__name__', '')}.{cls.__name__}")
        return True

    try:
        source, lineno = _function_source_from_file(module, "_phase3_scan_and_enter")
    except Exception as exc:
        logger.warning("PHASE3_FORCE_OVERRIDE_TERMINAL_GUARD_SOURCE_FAILED marker=20260707k err=%s", exc)
        return False

    patched_source = source
    changes: list[str] = []

    override_needle = "                            if _force_tpe_bypass:\n"
    override_replacement = "                            if _force_tpe_bypass and not _nija_phase3_non_overrideable_reason(_tpe_reason):\n"
    if override_needle in patched_source:
        patched_source = patched_source.replace(override_needle, override_replacement, 1)
        changes.append("tpe_force_override_non_overrideable_guard")
    else:
        logger.warning("PHASE3_FORCE_OVERRIDE_TERMINAL_GUARD_TPE_NEEDLE_MISSING marker=20260707k")

    direct_needle = "        if _force_direct_bypass and entries == 0 and _best_volume_symbol:\n"
    direct_replacement = '        if _force_direct_bypass and entries == 0 and _best_volume_symbol and _env_truthy("NIJA_ALLOW_FORCE_TRADE_DIRECT_FALLBACK", "false"):\n'
    if direct_needle in patched_source:
        patched_source = patched_source.replace(direct_needle, direct_replacement, 1)
        changes.append("force_trade_direct_opt_in_guard")
    else:
        logger.warning("PHASE3_FORCE_OVERRIDE_TERMINAL_GUARD_DIRECT_NEEDLE_MISSING marker=20260707k")

    skip_block = _phase3_hold_skip_block()
    skip_needle = 'logger.critical(\n                    "✅ [Phase3] SIGNAL PASSED all gates | symbol=%s action=%s "'
    if skip_block and "PHASE3_FALLBACK_HOLD_SKIP_APPLIED" not in patched_source and skip_needle in patched_source:
        patched_source = patched_source.replace(skip_needle, skip_block + "                " + skip_needle, 1)
        changes.append("fallback_hold_skip_preserved")
    elif skip_block and "PHASE3_FALLBACK_HOLD_SKIP_APPLIED" in patched_source:
        changes.append("fallback_hold_skip_already_present")
    elif not skip_block:
        logger.warning("PHASE3_FORCE_OVERRIDE_TERMINAL_GUARD_SKIP_BLOCK_UNAVAILABLE marker=20260707k")
    else:
        logger.warning("PHASE3_FORCE_OVERRIDE_TERMINAL_GUARD_SKIP_NEEDLE_MISSING marker=20260707k")

    if not changes:
        return False

    namespace = dict(vars(module))
    for key, value in getattr(current, "__globals__", {}).items():
        namespace.setdefault(key, value)
    namespace.setdefault("_env_truthy", getattr(module, "_env_truthy", _env_truthy))
    namespace["_nija_phase3_non_overrideable_reason"] = _nija_phase3_non_overrideable_reason
    namespace.setdefault("logger", getattr(module, "logger", logging.getLogger("nija.core_loop")))

    try:
        exec(compile(patched_source, "<phase3_force_override_terminal_guard>", "exec"), namespace, namespace)
        patched = namespace.get("_phase3_scan_and_enter")
        if not callable(patched):
            raise RuntimeError("patched function not produced")
    except Exception as exc:
        logger.warning("PHASE3_FORCE_OVERRIDE_TERMINAL_GUARD_COMPILE_FAILED marker=20260707k err=%s", exc)
        return False

    setattr(patched, _PATCHED_ATTR, True)
    setattr(patched, "__wrapped__", current)
    setattr(cls, "_phase3_scan_and_enter", patched)
    key = f"{getattr(module, '__name__', '')}.{cls.__name__}"
    _PATCHED_CLASSES.add(key)
    logger.warning(
        "%s class=%s source=file line=%s changes=%s direct_fallback_requires=NIJA_ALLOW_FORCE_TRADE_DIRECT_FALLBACK",
        _MARKER,
        key,
        lineno,
        ",".join(changes),
    )
    print(
        f"[NIJA-PRINT] PHASE3_FORCE_OVERRIDE_TERMINAL_GUARD_PATCHED marker=20260707k class={key} changes={','.join(changes)}",
        flush=True,
    )
    return True


def _try_patch_loaded() -> bool:
    module = sys.modules.get(_CANONICAL_CORE_LOOP_MODULE)
    if isinstance(module, ModuleType):
        return _patch_core_loop(module)
    return False


def _start_monitor() -> None:
    global _MONITOR_STARTED
    if _MONITOR_STARTED:
        return
    _MONITOR_STARTED = True

    def _monitor() -> None:
        deadline = time.time() + float(os.environ.get("NIJA_PATCH_MONITOR_SECONDS", "240") or "240")
        patched_any = False
        while time.time() < deadline:
            patched_any = _try_patch_loaded() or patched_any
            if patched_any:
                break
            time.sleep(1.0)
        logger.warning(
            "PHASE3_FORCE_OVERRIDE_TERMINAL_GUARD_MONITOR_COMPLETE marker=20260707k patched_any=%s patched_classes=%s",
            patched_any,
            sorted(_PATCHED_CLASSES),
        )

    threading.Thread(target=_monitor, name="phase3-force-override-terminal-guard", daemon=True).start()
    logger.warning("PHASE3_FORCE_OVERRIDE_TERMINAL_GUARD_MONITOR_STARTED marker=20260707k")


def install_import_hook() -> None:
    global _ORIGINAL_IMPORT_MODULE
    with _INSTALL_LOCK:
        _install_terminal_guard()
        _try_patch_loaded()
        _start_monitor()
        if _ORIGINAL_IMPORT_MODULE is not None:
            return
        _ORIGINAL_IMPORT_MODULE = importlib.import_module

        def _wrapped_import_module(name: str, package: str | None = None):
            module = _ORIGINAL_IMPORT_MODULE(name, package)  # type: ignore[misc]
            if name == _CANONICAL_CORE_LOOP_MODULE:
                _patch_core_loop(module)
            return module

        importlib.import_module = _wrapped_import_module  # type: ignore[assignment]
        logger.warning(
            "PHASE3_FORCE_OVERRIDE_TERMINAL_GUARD_INSTALL_COMPLETE marker=20260707k patched_classes=%s",
            sorted(_PATCHED_CLASSES),
        )


def install() -> None:
    install_import_hook()
