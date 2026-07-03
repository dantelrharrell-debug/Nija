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
_PHASE3_WRAP_ATTR = "_nija_phase3_fallback_hold_skip_phase3_wrapped_v20260703z"
_MARKER = "PHASE3_FALLBACK_HOLD_SKIP_PATCHED marker=20260703z"
_CORE_LOOP_MODULES = {"bot.nija_core_loop", "nija_core_loop"}
_TRUTHY_ENV_VALUES = {"1", "true", "t", "yes", "y", "enabled", "on"}

_SKIP_BLOCK = """
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
                            "PHASE3_FALLBACK_HOLD_SKIP_APPLIED marker=20260703z symbol=%s stage=%s reason=%s action=hold core_loop_skip=true",
                            sig.symbol,
                            _skip_stage,
                            _skip_reason,
                        )
                        print(
                            f"[NIJA-PRINT] PHASE3_FALLBACK_HOLD_SKIP_APPLIED marker=20260703z symbol={sig.symbol} stage={_skip_stage} reason={_skip_reason} core_loop_skip=true",
                            flush=True,
                        )
                        continue
"""


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
            "PHASE3_FALLBACK_HOLD_SKIP_TARGET_SKIPPED marker=20260703z module=%s file=%s reason=not_core_loop_file",
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


def _reapply_phase3_scan_budget(module: ModuleType, *, label: str) -> None:
    """Re-wrap Phase 3 with the broker-aware scan-budget patch after source replacement.

    This fallback patch intentionally recompiles _phase3_scan_and_enter from
    nija_core_loop.py. That source replacement can erase wrapper-based patches
    that were installed earlier, including the broker-specific OKX symbol filter.
    Re-applying phase3_scan_budget_patch here preserves the hold-skip safety fix
    while keeping OKX scans constrained to listed OKX instruments.
    """
    if not _env_truthy("NIJA_REAPPLY_PHASE3_SCAN_BUDGET_AFTER_HOLD_SKIP", True):
        logger.warning(
            "PHASE3_SCAN_BUDGET_REAPPLY_DISABLED marker=20260703z class=%s env=NIJA_REAPPLY_PHASE3_SCAN_BUDGET_AFTER_HOLD_SKIP",
            label,
        )
        return

    patch_mod = None
    for mod_name in ("bot.phase3_scan_budget_patch", "phase3_scan_budget_patch"):
        try:
            patch_mod = importlib.import_module(mod_name)
            break
        except Exception as exc:
            logger.debug("PHASE3_SCAN_BUDGET_REAPPLY_IMPORT_SKIPPED marker=20260703z module=%s err=%s", mod_name, exc)
    if patch_mod is None:
        logger.warning("PHASE3_SCAN_BUDGET_REAPPLY_FAILED marker=20260703z class=%s reason=module_unavailable", label)
        return

    try:
        installer = getattr(patch_mod, "_install_on_module", None)
        if callable(installer):
            reapplied = bool(installer(module))
            logger.warning(
                "PHASE3_SCAN_BUDGET_REAPPLIED_AFTER_HOLD_SKIP marker=20260703z class=%s reapplied=%s method=_install_on_module",
                label,
                reapplied,
            )
            print(
                f"[NIJA-PRINT] PHASE3_SCAN_BUDGET_REAPPLIED_AFTER_HOLD_SKIP marker=20260703z class={label} reapplied={reapplied}",
                flush=True,
            )
            return

        hook = getattr(patch_mod, "install_import_hook", None)
        if callable(hook):
            hook()
            logger.warning(
                "PHASE3_SCAN_BUDGET_REAPPLIED_AFTER_HOLD_SKIP marker=20260703z class=%s reapplied=unknown method=install_import_hook",
                label,
            )
            return

        logger.warning("PHASE3_SCAN_BUDGET_REAPPLY_FAILED marker=20260703z class=%s reason=no_supported_installer", label)
    except Exception as exc:
        logger.warning("PHASE3_SCAN_BUDGET_REAPPLY_FAILED marker=20260703z class=%s err=%s", label, exc)


def _patch_core_loop_phase3(module: ModuleType, cls: type, *, label: str) -> bool:
    if not _is_core_loop_module(module):
        return False

    current = getattr(cls, "_phase3_scan_and_enter", None)
    if not callable(current):
        logger.debug(
            "PHASE3_FALLBACK_HOLD_SKIP_TARGET_SKIPPED marker=20260703z class=%s reason=no_phase3_method",
            f"{label}.{getattr(cls, '__name__', '<unknown>')}",
        )
        return False
    if getattr(current, _PHASE3_WRAP_ATTR, False):
        _PATCHED_CLASSES.add(f"{label}.{cls.__name__}._phase3_scan_and_enter")
        return True

    try:
        source, lineno = _function_source_from_file(module, "_phase3_scan_and_enter")
    except Exception as exc:
        logger.warning("PHASE3_FALLBACK_HOLD_SKIP_FILE_SOURCE_FAILED marker=20260703z err=%s", exc)
        return False

    needle = "success = self.apex.execute_action(analysis, sig.symbol)"
    if needle not in source:
        logger.warning("PHASE3_FALLBACK_HOLD_SKIP_PHASE3_NEEDLE_MISSING marker=20260703z file_source=true")
        return False

    patched_source = source.replace(needle, _SKIP_BLOCK + "                " + needle, 1)

    # Compile the generated function with the real nija_core_loop module globals.
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
        logger.warning("PHASE3_FALLBACK_HOLD_SKIP_PHASE3_COMPILE_FAILED marker=20260703z err=%s", exc)
        return False

    setattr(patched, _PHASE3_WRAP_ATTR, True)
    setattr(patched, "__wrapped__", current)
    setattr(cls, "_phase3_scan_and_enter", patched)
    _PATCHED_CLASSES.add(f"{label}.{cls.__name__}._phase3_scan_and_enter")
    logger.warning("%s class=%s source=file line=%s", _MARKER, f"{label}.{cls.__name__}", lineno)
    print(f"[NIJA-PRINT] PHASE3_FALLBACK_HOLD_SKIP_PATCHED marker=20260703z | class={label}.{cls.__name__} source=file line={lineno}", flush=True)

    _reapply_phase3_scan_budget(module, label=f"{label}.{cls.__name__}")
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
        logger.warning("PHASE3_FALLBACK_HOLD_SKIP_MONITOR_COMPLETE marker=20260703z patched_any=%s patched_classes=%s", patched_any, sorted(_PATCHED_CLASSES))

    threading.Thread(target=_monitor, name="phase3-fallback-hold-skip-monitor", daemon=True).start()
    logger.warning("PHASE3_FALLBACK_HOLD_SKIP_MONITOR_STARTED marker=20260703z")


def install_import_hook() -> None:
    global _ORIGINAL_IMPORT_MODULE
    with _INSTALL_LOCK:
        _try_patch_loaded()
        _start_monitor()
        if _ORIGINAL_IMPORT_MODULE is not None:
            logger.warning("PHASE3_FALLBACK_HOLD_SKIP_INSTALL_COMPLETE marker=20260703z already_installed=True patched_classes=%s", sorted(_PATCHED_CLASSES))
            return
        _ORIGINAL_IMPORT_MODULE = importlib.import_module

        def _wrapped_import_module(name: str, package: str | None = None):
            module = _ORIGINAL_IMPORT_MODULE(name, package)  # type: ignore[misc]
            if name in _CORE_LOOP_MODULES:
                _install_on_module(module)
            _try_patch_loaded()
            return module

        importlib.import_module = _wrapped_import_module  # type: ignore[assignment]
        logger.warning("PHASE3_FALLBACK_HOLD_SKIP_INSTALL_COMPLETE marker=20260703z patched_classes=%s", sorted(_PATCHED_CLASSES))
