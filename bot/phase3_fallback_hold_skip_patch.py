from __future__ import annotations

import importlib
import logging
import sys
import threading
import time
from types import ModuleType
from typing import Any, Callable, Optional

logger = logging.getLogger("nija.phase3_fallback_hold_skip")

_ORIGINAL_IMPORT_MODULE: Optional[Callable[..., Any]] = None
_PATCHED_CLASSES: set[str] = set()
_MONITOR_STARTED = False
_INSTALL_LOCK = threading.Lock()
_WRAP_ATTR = "_nija_phase3_fallback_hold_skip_execute_action_wrapped_v20260703v"
_MARKER = "PHASE3_FALLBACK_HOLD_SKIP_PATCHED marker=20260703v"


def _analysis_is_hold_skip(analysis: Any) -> tuple[bool, str, str]:
    if not isinstance(analysis, dict):
        return False, "", ""
    action = str(analysis.get("action", "")).strip().lower()
    blocked = bool(
        analysis.get("blocked_before_execute_action")
        or analysis.get("skip_before_execute_action")
        or analysis.get("order_should_not_submit")
        or analysis.get("fallback_entry_skipped")
    )
    if action == "hold" and blocked:
        reason = str(analysis.get("reason") or analysis.get("detail") or "fallback_hold_skip")
        stage = str(analysis.get("filter_stage") or "fallback_prefilter")
        return True, reason, stage
    if blocked and analysis.get("forced_fallback") is False and analysis.get("fallback_entry") is False:
        reason = str(analysis.get("reason") or analysis.get("detail") or "fallback_pre_execution_skip")
        stage = str(analysis.get("filter_stage") or "fallback_prefilter")
        return True, reason, stage
    return False, "", ""


def _patch_strategy_class(cls: type, *, label: str) -> bool:
    original = getattr(cls, "execute_action", None)
    if not callable(original):
        return False
    if getattr(original, _WRAP_ATTR, False):
        _PATCHED_CLASSES.add(f"{label}.{cls.__name__}")
        return True

    def _patched_execute_action(self: Any, analysis: Any, symbol: Any = None, *args: Any, **kwargs: Any) -> Any:
        should_skip, reason, stage = _analysis_is_hold_skip(analysis)
        if should_skip:
            _symbol = str(symbol or (analysis.get("symbol") if isinstance(analysis, dict) else "UNKNOWN") or "UNKNOWN")
            logger.warning(
                "PHASE3_FALLBACK_HOLD_SKIP_APPLIED marker=20260703v symbol=%s stage=%s reason=%s action=hold order_submit=false",
                _symbol,
                stage,
                reason,
            )
            print(
                f"[NIJA-PRINT] PHASE3_FALLBACK_HOLD_SKIP_APPLIED marker=20260703v symbol={_symbol} stage={stage} reason={reason}",
                flush=True,
            )
            return False
        return original(self, analysis, symbol, *args, **kwargs)

    setattr(_patched_execute_action, _WRAP_ATTR, True)
    setattr(_patched_execute_action, "__wrapped__", original)
    setattr(cls, "execute_action", _patched_execute_action)
    _PATCHED_CLASSES.add(f"{label}.{cls.__name__}")
    logger.warning("%s class=%s", _MARKER, f"{label}.{cls.__name__}")
    print(f"[NIJA-PRINT] PHASE3_FALLBACK_HOLD_SKIP_PATCHED marker=20260703v | class={label}.{cls.__name__}", flush=True)
    return True


def _patch_core_loop_class(cls: type, *, label: str) -> bool:
    """Patch NijaCoreLoop.__init__ so any apex object attached to it is guarded.

    This is a submit-boundary guard, not a gate bypass. It only converts analysis
    objects already marked as pre-execution hold skips into no-submit results.
    """
    original_init = getattr(cls, "__init__", None)
    if not callable(original_init):
        return False
    init_attr = _WRAP_ATTR + "_init"
    if getattr(original_init, init_attr, False):
        _PATCHED_CLASSES.add(f"{label}.{cls.__name__}.__init__")
        return True

    def _patched_init(self: Any, *args: Any, **kwargs: Any) -> Any:
        result = original_init(self, *args, **kwargs)
        try:
            apex = getattr(self, "apex", None)
            if apex is not None:
                _patch_strategy_class(apex.__class__, label=f"{apex.__class__.__module__}")
        except Exception as exc:
            logger.warning("PHASE3_FALLBACK_HOLD_SKIP_APEX_PATCH_FAILED marker=20260703v err=%s", exc)
        return result

    setattr(_patched_init, init_attr, True)
    setattr(_patched_init, "__wrapped__", original_init)
    setattr(cls, "__init__", _patched_init)
    _PATCHED_CLASSES.add(f"{label}.{cls.__name__}.__init__")
    logger.warning("PHASE3_FALLBACK_HOLD_SKIP_CORE_INIT_PATCHED marker=20260703v class=%s", f"{label}.{cls.__name__}")
    return True


def _install_on_module(module: ModuleType) -> bool:
    patched = False
    module_name = getattr(module, "__name__", "<unknown>")

    core_cls = getattr(module, "NijaCoreLoop", None)
    if isinstance(core_cls, type):
        patched = _patch_core_loop_class(core_cls, label=module_name) or patched

    for attr in ("NIJAApexStrategyV71", "NijaApexStrategyV71", "APEXStrategy", "TradingStrategy"):
        cls = getattr(module, attr, None)
        if isinstance(cls, type) and callable(getattr(cls, "execute_action", None)):
            patched = _patch_strategy_class(cls, label=module_name) or patched

    # Generic fallback: patch any class in the module with execute_action.
    for attr_name, obj in list(vars(module).items()):
        if isinstance(obj, type) and callable(getattr(obj, "execute_action", None)):
            patched = _patch_strategy_class(obj, label=module_name) or patched

    return patched


def _try_patch_loaded() -> bool:
    patched = False
    for name, module in list(sys.modules.items()):
        if not isinstance(module, ModuleType):
            continue
        if (
            name in {"bot.nija_core_loop", "nija_core_loop", "bot.nija_apex_strategy_v71", "nija_apex_strategy_v71", "bot.trading_strategy", "trading_strategy"}
            or hasattr(module, "NijaCoreLoop")
            or hasattr(module, "NIJAApexStrategyV71")
        ):
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
        logger.warning(
            "PHASE3_FALLBACK_HOLD_SKIP_MONITOR_COMPLETE marker=20260703v patched_any=%s patched_classes=%s",
            patched_any,
            sorted(_PATCHED_CLASSES),
        )

    threading.Thread(target=_monitor, name="phase3-fallback-hold-skip-monitor", daemon=True).start()
    logger.warning("PHASE3_FALLBACK_HOLD_SKIP_MONITOR_STARTED marker=20260703v")


def install_import_hook() -> None:
    global _ORIGINAL_IMPORT_MODULE
    with _INSTALL_LOCK:
        _try_patch_loaded()
        _start_monitor()
        if _ORIGINAL_IMPORT_MODULE is not None:
            logger.warning(
                "PHASE3_FALLBACK_HOLD_SKIP_INSTALL_COMPLETE marker=20260703v already_installed=True patched_classes=%s",
                sorted(_PATCHED_CLASSES),
            )
            return
        _ORIGINAL_IMPORT_MODULE = importlib.import_module

        def _wrapped_import_module(name: str, package: str | None = None):
            module = _ORIGINAL_IMPORT_MODULE(name, package)  # type: ignore[misc]
            if (
                name in {"bot.nija_core_loop", "nija_core_loop", "bot.nija_apex_strategy_v71", "nija_apex_strategy_v71", "bot.trading_strategy", "trading_strategy"}
                or hasattr(module, "NijaCoreLoop")
                or hasattr(module, "NIJAApexStrategyV71")
            ):
                _install_on_module(module)
            _try_patch_loaded()
            return module

        importlib.import_module = _wrapped_import_module  # type: ignore[assignment]
        logger.warning(
            "PHASE3_FALLBACK_HOLD_SKIP_INSTALL_COMPLETE marker=20260703v patched_classes=%s",
            sorted(_PATCHED_CLASSES),
        )
