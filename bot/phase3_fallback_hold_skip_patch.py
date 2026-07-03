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

logger = logging.getLogger("nija.phase3_fallback_hold_skip")

_ORIGINAL_IMPORT_MODULE: Optional[Callable[..., Any]] = None
_PATCHED_CLASSES: set[str] = set()
_MONITOR_STARTED = False
_INSTALL_LOCK = threading.Lock()
_PHASE3_WRAP_ATTR = "_nija_phase3_fallback_hold_skip_phase3_wrapped_v20260703y"
_MARKER = "PHASE3_FALLBACK_HOLD_SKIP_PATCHED marker=20260703y"
_CORE_LOOP_MODULES = {"bot.nija_core_loop", "nija_core_loop"}
_TRUTHY_ENV_VALUES = {"1", "true", "t", "yes", "y", "enabled", "on"}

_SKIP_BLOCK = '''
                if isinstance(analysis, dict):
                    _hold_skip = bool(
                        str(analysis.get("action", "")).strip().lower() == "hold"
                        and (
                            analysis.get("blocked_before_execute_action")
                            or analysis.get("skip_before_execute_action")
                            or analysis.get("order_should_not_submit")
                            or analysis.get("fallback_entry_skipped")
                        )
                    )
                    if _hold_skip:
                        blocked += 1
                        _skip_reason = str(analysis.get("reason") or analysis.get("detail") or "fallback_hold_skip")
                        _skip_stage = str(analysis.get("filter_stage") or "fallback_prefilter")
                        _funnel["profitability"] = ("FAIL", _skip_reason)
                        logger.critical(
                            "PHASE3_FALLBACK_HOLD_SKIP_APPLIED marker=20260703y symbol=%s stage=%s reason=%s action=hold core_loop_skip=true",
                            sig.symbol,
                            _skip_stage,
                            _skip_reason,
                        )
                        print(
                            f"[NIJA-PRINT] PHASE3_FALLBACK_HOLD_SKIP_APPLIED marker=20260703y symbol={sig.symbol} stage={_skip_stage} reason={_skip_reason} core_loop_skip=true",
                            flush=True,
                        )
                        continue
'''


def _env_truthy(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return bool(default)
    return str(raw).strip().lower() in _TRUTHY_ENV_VALUES


def _is_core_loop_module(module: ModuleType) -> bool:
    module_name = str(getattr(module, "__name__", ""))
    if module_name not in _CORE_LOOP_MODULES:
        return False
    module_file = str(getattr(module, "__file__", "") or "")
    if module_file and Path(module_file).name != "nija_core_loop.py":
        logger.debug(
            "PHASE3_FALLBACK_HOLD_SKIP_TARGET_SKIPPED marker=20260703y module=%s file=%s reason=not_core_loop_file",
            module_name,
            module_file,
        )
        return False
    return True


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


def _patch_core_loop_phase3(module: ModuleType, cls: type, *, label: str) -> bool:
    if not _is_core_loop_module(module):
        return False

    current = getattr(cls, "_phase3_scan_and_enter", None)
    if not callable(current):
        logger.debug(
            "PHASE3_FALLBACK_HOLD_SKIP_TARGET_SKIPPED marker=20260703y class=%s reason=no_phase3_method",
            f"{label}.{getattr(cls, '__name__', '<unknown>')}",
        )
        return False
    if getattr(current, _PHASE3_WRAP_ATTR, False):
        _PATCHED_CLASSES.add(f"{label}.{cls.__name__}._phase3_scan_and_enter")
        return True

    try:
        source, lineno = _function_source_from_file(module, "_phase3_scan_and_enter")
    except Exception as exc:
        logger.warning("PHASE3_FALLBACK_HOLD_SKIP_FILE_SOURCE_FAILED marker=20260703y err=%s", exc)
        return False

    needle = "success = self.apex.execute_action(analysis, sig.symbol)"
    if needle not in source:
        logger.warning("PHASE3_FALLBACK_HOLD_SKIP_PHASE3_NEEDLE_MISSING marker=20260703y file_source=true")
        return False

    patched_source = source.replace(needle, _SKIP_BLOCK + "                " + needle, 1)

    # Compile the generated function with the real nija_core_loop module globals.
    # The runtime can wrap _phase3_scan_and_enter before this patch installs;
    # using current.__globals__ in that case points at the wrapper module instead
    # of bot.nija_core_loop and drops names such as _env_truthy, MIN_SCORE_HARD_FLOOR,
    # logger, and FORCE_NEXT_CYCLE.  Start with vars(module), then backfill any
    # wrapper-only globals without overriding core-loop symbols.
    namespace = dict(vars(module))
    for key, value in getattr(current, "__globals__", {}).items():
        namespace.setdefault(key, value)
    namespace.setdefault("_env_truthy", getattr(module, "_env_truthy", _env_truthy))
    namespace.setdefault("logger", getattr(module, "logger", logging.getLogger("nija.core_loop")))

    try:
        exec(compile(patched_source, "<phase3_fallback_hold_skip_file_source>", "exec"), namespace, namespace)
        patched = namespace.get("_phase3_scan_and_enter")
        if not callable(patched):
            raise RuntimeError("patched function not produced")
    except Exception as exc:
        logger.warning("PHASE3_FALLBACK_HOLD_SKIP_PHASE3_COMPILE_FAILED marker=20260703y err=%s", exc)
        return False

    setattr(patched, _PHASE3_WRAP_ATTR, True)
    setattr(patched, "__wrapped__", current)
    setattr(cls, "_phase3_scan_and_enter", patched)
    _PATCHED_CLASSES.add(f"{label}.{cls.__name__}._phase3_scan_and_enter")
    logger.warning("%s class=%s source=file line=%s", _MARKER, f"{label}.{cls.__name__}", lineno)
    print(f"[NIJA-PRINT] PHASE3_FALLBACK_HOLD_SKIP_PATCHED marker=20260703y | class={label}.{cls.__name__} source=file line={lineno}", flush=True)
    return True


def _install_on_module(module: ModuleType) -> bool:
    if not _is_core_loop_module(module):
        return False
    cls = getattr(module, "NijaCoreLoop", None)
    if isinstance(cls, type):
        return _patch_core_loop_phase3(module, cls, label=getattr(module, "__name__", "<unknown>"))
    return False


def _try_patch_loaded() -> bool:
    patched = False
    for name, module in list(sys.modules.items()):
        if name in _CORE_LOOP_MODULES and isinstance(module, ModuleType):
            patched = _install_on_module(module) or patched
    return patched


def _start_monitor() -> None:
    global _MONITOR_STARTED
    if _MONITOR_STARTED:
        return
    _MONITOR_STARTED = True

    def _monitor() -> None:
        deadline = time.time() + 300.0
        patched_any = False
        while time.time() < deadline:
            patched_any = _try_patch_loaded() or patched_any
            if patched_any:
                break
            time.sleep(1.0)
        logger.warning("PHASE3_FALLBACK_HOLD_SKIP_MONITOR_COMPLETE marker=20260703y patched_any=%s patched_classes=%s", patched_any, sorted(_PATCHED_CLASSES))

    threading.Thread(target=_monitor, name="phase3-fallback-hold-skip-monitor", daemon=True).start()
    logger.warning("PHASE3_FALLBACK_HOLD_SKIP_MONITOR_STARTED marker=20260703y")


def install_import_hook() -> None:
    global _ORIGINAL_IMPORT_MODULE
    with _INSTALL_LOCK:
        _try_patch_loaded()
        _start_monitor()
        if _ORIGINAL_IMPORT_MODULE is not None:
            logger.warning("PHASE3_FALLBACK_HOLD_SKIP_INSTALL_COMPLETE marker=20260703y already_installed=True patched_classes=%s", sorted(_PATCHED_CLASSES))
            return
        _ORIGINAL_IMPORT_MODULE = importlib.import_module

        def _wrapped_import_module(name: str, package: str | None = None):
            module = _ORIGINAL_IMPORT_MODULE(name, package)  # type: ignore[misc]
            if name in _CORE_LOOP_MODULES:
                _install_on_module(module)
            _try_patch_loaded()
            return module

        importlib.import_module = _wrapped_import_module  # type: ignore[assignment]
        logger.warning("PHASE3_FALLBACK_HOLD_SKIP_INSTALL_COMPLETE marker=20260703y patched_classes=%s", sorted(_PATCHED_CLASSES))