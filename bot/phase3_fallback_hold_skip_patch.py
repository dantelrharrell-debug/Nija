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
_REAPPLIED_CLASSES: set[str] = set()
_REAPPLY_FAILURES_LOGGED: set[str] = set()
_MONITOR_STARTED = False
_INSTALL_LOCK = threading.Lock()

_PHASE3_WRAP_ATTR = "_nija_phase3_fallback_hold_skip_phase3_wrapped_v20260707j"
_MARKER = "PHASE3_FALLBACK_HOLD_SKIP_PATCHED marker=20260707j"
_CANONICAL_CORE_LOOP_MODULE = "bot.nija_core_loop"
_TRUTHY_ENV_VALUES = {"1", "true", "t", "yes", "y", "enabled", "on"}

_SKIP_BLOCK = """
                if isinstance(analysis, dict):
                    _action_text = str(analysis.get("action", "")).strip().lower()
                    _filter_stage_text = str(analysis.get("filter_stage", "")).strip().lower()
                    _reason_text = str(analysis.get("reason") or analysis.get("detail") or "")
                    _reason_low = _reason_text.lower()
                    _haystack = " ".join(str(v) for v in analysis.values()).lower()
                    _terminal_risk_hit = bool(
                        "terminal_risk_hard_block" in _filter_stage_text
                        or "terminal_risk_hard_block" in _reason_low
                        or "terminal_risk_hard_block" in _haystack
                        or "hard_sector_limit_block" in _reason_low
                        or "hard_sector_limit_block" in _haystack
                        or "entry_blocked_terminal_risk_hard_block" in _reason_low
                        or "portfolio exposure limit reached" in _reason_low
                        or "position blocked by risk engine" in _reason_low
                        or "hard sector limit block" in _reason_low
                    )
                    _market_safety_hit = bool(
                        "trade not eligible" in _reason_low
                        or "outside safe range" in _reason_low
                        or "avoiding extremes" in _reason_low
                        or ("rsi" in _reason_low and "outside" in _reason_low)
                        or "fallback_illiquid_policy_blocked" in _reason_low
                        or "illiquid_policy_hard_block" in _reason_low
                        or analysis.get("order_should_not_submit")
                        or analysis.get("blocked_before_execute_action")
                        or analysis.get("skip_before_execute_action")
                        or analysis.get("fallback_entry_skipped")
                    )
                    _terminal_risk_hold = bool(
                        _action_text == "hold"
                        and (
                            analysis.get("allowed") is False
                            or analysis.get("passed_gate") is False
                            or analysis.get("signal") is False
                            or _terminal_risk_hit
                        )
                    )
                    _unsafe_fallback_submit = bool(_terminal_risk_hit or _market_safety_hit)
                    _hold_skip = bool(
                        (_action_text == "hold" and (_terminal_risk_hold or _market_safety_hit))
                        or _unsafe_fallback_submit
                    )
                    if _hold_skip:
                        blocked += 1
                        _skip_reason = _reason_text or str(analysis.get("filter_stage") or "fallback_hold_skip")
                        _skip_stage = str(analysis.get("filter_stage") or ("terminal_risk_hard_block" if _terminal_risk_hit else "fallback_prefilter"))
                        _funnel["profitability"] = ("FAIL", _skip_reason)
                        logger.critical(
                            "PHASE3_FALLBACK_HOLD_SKIP_APPLIED marker=20260707j symbol=%s stage=%s reason=%s action=%s core_loop_skip=true terminal_risk=%s market_safety=%s pre_pass_log=true",
                            sig.symbol,
                            _skip_stage,
                            _skip_reason,
                            _action_text,
                            _terminal_risk_hit,
                            _market_safety_hit,
                        )
                        print(
                            f"[NIJA-PRINT] PHASE3_FALLBACK_HOLD_SKIP_APPLIED marker=20260707j symbol={sig.symbol} stage={_skip_stage} reason={_skip_reason} action={_action_text} core_loop_skip=true terminal_risk={_terminal_risk_hit} market_safety={_market_safety_hit} pre_pass_log=true",
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
    if module_name != _CANONICAL_CORE_LOOP_MODULE:
        return False
    module_file = str(getattr(module, "__file__", "") or "")
    if module_file and Path(module_file).name != "nija_core_loop.py":
        logger.debug(
            "PHASE3_FALLBACK_HOLD_SKIP_TARGET_SKIPPED marker=20260707j module=%s file=%s reason=not_core_loop_file",
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


def _import_patch_module(module_name: str) -> ModuleType | None:
    existing = sys.modules.get(module_name)
    if isinstance(existing, ModuleType):
        return existing
    try:
        return importlib.import_module(module_name)
    except Exception as exc:
        key = f"{module_name}:import"
        if key not in _REAPPLY_FAILURES_LOGGED:
            _REAPPLY_FAILURES_LOGGED.add(key)
            logger.warning(
                "PHASE3_PATCH_REAPPLY_IMPORT_FAILED marker=20260707j module=%s err=%s",
                module_name,
                exc,
            )
        else:
            logger.debug(
                "PHASE3_PATCH_REAPPLY_IMPORT_FAILED_REPEAT marker=20260707j module=%s err=%s",
                module_name,
                exc,
            )
        return None


def _run_reapply_installer(module: ModuleType, patch_module_name: str, installer_name: str, *, label: str) -> bool:
    patch_mod = _import_patch_module(patch_module_name)
    if patch_mod is None:
        return False
    installer = getattr(patch_mod, installer_name, None)
    if not callable(installer):
        key = f"{patch_module_name}:{installer_name}"
        if key not in _REAPPLY_FAILURES_LOGGED:
            _REAPPLY_FAILURES_LOGGED.add(key)
            logger.warning(
                "PHASE3_PATCH_REAPPLY_FAILED marker=20260707j class=%s module=%s reason=no_supported_installer",
                label,
                patch_module_name,
            )
        return False
    try:
        return bool(installer(module))
    except Exception as exc:
        key = f"{patch_module_name}:{type(exc).__name__}"
        if key not in _REAPPLY_FAILURES_LOGGED:
            _REAPPLY_FAILURES_LOGGED.add(key)
            logger.warning(
                "PHASE3_PATCH_REAPPLY_FAILED marker=20260707j class=%s module=%s err=%s",
                label,
                patch_module_name,
                exc,
            )
        else:
            logger.debug(
                "PHASE3_PATCH_REAPPLY_FAILED_REPEAT marker=20260707j class=%s module=%s err=%s",
                label,
                patch_module_name,
                exc,
            )
        return False


def _reapply_phase3_wrappers(module: ModuleType, *, label: str) -> None:
    if not _env_truthy("NIJA_REAPPLY_PHASE3_SCAN_BUDGET_AFTER_HOLD_SKIP", True):
        logger.warning(
            "PHASE3_SCAN_BUDGET_REAPPLY_DISABLED marker=20260707j class=%s env=NIJA_REAPPLY_PHASE3_SCAN_BUDGET_AFTER_HOLD_SKIP",
            label,
        )
        return

    scan_reapplied = _run_reapply_installer(
        module,
        "bot.phase3_scan_budget_patch",
        "_install_on_module",
        label=label,
    )
    force_reapplied = _run_reapply_installer(
        module,
        "bot.phase3_force_next_preserve_selection_patch",
        "_install_on_module",
        label=label,
    )

    key = f"{label}:scan={scan_reapplied}:force={force_reapplied}"
    if key not in _REAPPLIED_CLASSES:
        _REAPPLIED_CLASSES.add(key)
        logger.warning(
            "PHASE3_WRAPPERS_REAPPLIED_AFTER_HOLD_SKIP marker=20260707j class=%s scan_budget=%s force_next=%s canonical_module=%s",
            label,
            scan_reapplied,
            force_reapplied,
            _CANONICAL_CORE_LOOP_MODULE,
        )
        print(
            f"[NIJA-PRINT] PHASE3_WRAPPERS_REAPPLIED_AFTER_HOLD_SKIP marker=20260707j class={label} scan_budget={scan_reapplied} force_next={force_reapplied}",
            flush=True,
        )


def _patch_core_loop_phase3(module: ModuleType, cls: type, *, label: str) -> bool:
    if not _is_core_loop_module(module):
        return False

    current = getattr(cls, "_phase3_scan_and_enter", None)
    if not callable(current):
        logger.debug(
            "PHASE3_FALLBACK_HOLD_SKIP_TARGET_SKIPPED marker=20260707j class=%s reason=no_phase3_method",
            f"{label}.{getattr(cls, '__name__', '<unknown>')}",
        )
        return False
    if getattr(current, _PHASE3_WRAP_ATTR, False):
        _PATCHED_CLASSES.add(f"{label}.{cls.__name__}._phase3_scan_and_enter")
        return True

    try:
        source, lineno = _function_source_from_file(module, "_phase3_scan_and_enter")
    except Exception as exc:
        logger.warning("PHASE3_FALLBACK_HOLD_SKIP_FILE_SOURCE_FAILED marker=20260707j err=%s", exc)
        return False

    needle = "logger.critical(\n                    \"✅ [Phase3] SIGNAL PASSED all gates | symbol=%s action=%s \""
    if needle not in source:
        needle = "logger.critical(\n                    \"🚀 [CoreLoop] SUBMITTING ORDER | symbol=%s side=%s action=%s \""
        if needle not in source:
            needle = "success = self.apex.execute_action(analysis, sig.symbol)"
            if needle not in source:
                logger.warning("PHASE3_FALLBACK_HOLD_SKIP_PHASE3_NEEDLE_MISSING marker=20260707j file_source=true")
                return False

    patched_source = source.replace(needle, _SKIP_BLOCK + "                " + needle, 1)

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
        logger.warning("PHASE3_FALLBACK_HOLD_SKIP_PHASE3_COMPILE_FAILED marker=20260707j err=%s", exc)
        return False

    setattr(patched, _PHASE3_WRAP_ATTR, True)
    setattr(patched, "__wrapped__", current)
    setattr(cls, "_phase3_scan_and_enter", patched)
    patch_key = f"{label}.{cls.__name__}._phase3_scan_and_enter"
    _PATCHED_CLASSES.add(patch_key)
    logger.warning("%s class=%s source=file line=%s canonical_module=%s", _MARKER, f"{label}.{cls.__name__}", lineno, _CANONICAL_CORE_LOOP_MODULE)
    print(
        f"[NIJA-PRINT] PHASE3_FALLBACK_HOLD_SKIP_PATCHED marker=20260707j | class={label}.{cls.__name__} source=file line={lineno}",
        flush=True,
    )

    _reapply_phase3_wrappers(module, label=f"{label}.{cls.__name__}")
    return True


def _install_on_module(module: ModuleType) -> bool:
    if not _is_core_loop_module(module):
        return False
    cls = getattr(module, "NijaCoreLoop", None)
    if isinstance(cls, type):
        return _patch_core_loop_phase3(module, cls, label=getattr(module, "__name__", "<unknown>"))
    return False


def _try_patch_loaded() -> bool:
    module = sys.modules.get(_CANONICAL_CORE_LOOP_MODULE)
    if isinstance(module, ModuleType):
        return _install_on_module(module)
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
            "PHASE3_FALLBACK_HOLD_SKIP_MONITOR_COMPLETE marker=20260707j patched_any=%s patched_classes=%s canonical_module=%s",
            patched_any,
            sorted(_PATCHED_CLASSES),
            _CANONICAL_CORE_LOOP_MODULE,
        )

    threading.Thread(target=_monitor, name="phase3-fallback-hold-skip-monitor", daemon=True).start()
    logger.warning("PHASE3_FALLBACK_HOLD_SKIP_MONITOR_STARTED marker=20260707j canonical_module=%s", _CANONICAL_CORE_LOOP_MODULE)


def install_import_hook() -> None:
    global _ORIGINAL_IMPORT_MODULE
    with _INSTALL_LOCK:
        _try_patch_loaded()
        _start_monitor()
        if _ORIGINAL_IMPORT_MODULE is not None:
            logger.debug(
                "PHASE3_FALLBACK_HOLD_SKIP_INSTALL_COMPLETE marker=20260707j already_installed=True patched_classes=%s",
                sorted(_PATCHED_CLASSES),
            )
            return
        _ORIGINAL_IMPORT_MODULE = importlib.import_module

        def _wrapped_import_module(name: str, package: str | None = None):
            module = _ORIGINAL_IMPORT_MODULE(name, package)  # type: ignore[misc]
            if name == _CANONICAL_CORE_LOOP_MODULE:
                _install_on_module(module)
            return module

        importlib.import_module = _wrapped_import_module  # type: ignore[assignment]
        logger.warning(
            "PHASE3_FALLBACK_HOLD_SKIP_INSTALL_COMPLETE marker=20260707j patched_classes=%s canonical_module=%s",
            sorted(_PATCHED_CLASSES),
            _CANONICAL_CORE_LOOP_MODULE,
        )
