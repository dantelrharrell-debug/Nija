from __future__ import annotations

import importlib
import inspect
import logging
import sys
import textwrap
import threading
import time
from types import ModuleType
from typing import Any, Callable, Optional

logger = logging.getLogger("nija.phase3_fallback_hold_skip")

_ORIGINAL_IMPORT_MODULE: Optional[Callable[..., Any]] = None
_PATCHED_CLASSES: set[str] = set()
_MONITOR_STARTED = False
_INSTALL_LOCK = threading.Lock()
_WRAP_ATTR = "_nija_phase3_fallback_hold_skip_execute_action_wrapped_v20260703w"
_PHASE3_WRAP_ATTR = "_nija_phase3_fallback_hold_skip_phase3_wrapped_v20260703w"
_MARKER = "PHASE3_FALLBACK_HOLD_SKIP_PATCHED marker=20260703w"

_PHASE3_SKIP_BLOCK = '''
                if isinstance(analysis, dict):
                    _phase3_hold_skip = bool(
                        str(analysis.get("action", "")).strip().lower() == "hold"
                        and (
                            analysis.get("blocked_before_execute_action")
                            or analysis.get("skip_before_execute_action")
                            or analysis.get("order_should_not_submit")
                            or analysis.get("fallback_entry_skipped")
                        )
                    )
                    if _phase3_hold_skip:
                        blocked += 1
                        _skip_reason = str(analysis.get("reason") or analysis.get("detail") or "fallback_hold_skip")
                        _skip_stage = str(analysis.get("filter_stage") or "fallback_prefilter")
                        _funnel["profitability"] = ("FAIL", _skip_reason)
                        logger.critical(
                            "PHASE3_FALLBACK_HOLD_SKIP_APPLIED marker=20260703w symbol=%s stage=%s reason=%s action=hold order_submit=false core_loop_skip=true",
                            sig.symbol,
                            _skip_stage,
                            _skip_reason,
                        )
                        print(
                            f"[NIJA-PRINT] PHASE3_FALLBACK_HOLD_SKIP_APPLIED marker=20260703w symbol={sig.symbol} stage={_skip_stage} reason={_skip_reason} core_loop_skip=true",
                            flush=True,
                        )
                        continue
'''


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
                "PHASE3_FALLBACK_HOLD_SKIP_APPLIED marker=20260703w symbol=%s stage=%s reason=%s action=hold order_submit=false submit_boundary=true",
                _symbol,
                stage,
                reason,
            )
            print(
                f"[NIJA-PRINT] PHASE3_FALLBACK_HOLD_SKIP_APPLIED marker=20260703w symbol={_symbol} stage={stage} reason={reason} submit_boundary=true",
                flush=True,
            )
            return False
        return original(self, analysis, symbol, *args, **kwargs)

    setattr(_patched_execute_action, _WRAP_ATTR, True)
    setattr(_patched_execute_action, "__wrapped__", original)
    setattr(cls, "execute_action", _patched_execute_action)
    _PATCHED_CLASSES.add(f"{label}.{cls.__name__}")
    logger.warning("%s class=%s boundary=execute_action", _MARKER, f"{label}.{cls.__name__}")
    print(f"[NIJA-PRINT] PHASE3_FALLBACK_HOLD_SKIP_PATCHED marker=20260703w | class={label}.{cls.__name__} boundary=execute_action", flush=True)
    return True


def _patch_core_loop_phase3(cls: type, *, label: str) -> bool:
    original = getattr(cls, "_phase3_scan_and_enter", None)
    if not callable(original):
        return False
    if getattr(original, _PHASE3_WRAP_ATTR, False):
        _PATCHED_CLASSES.add(f"{label}.{cls.__name__}._phase3_scan_and_enter")
        return True

    try:
        source = textwrap.dedent(inspect.getsource(original))
    except Exception as exc:
        logger.warning("PHASE3_FALLBACK_HOLD_SKIP_PHASE3_SOURCE_UNAVAILABLE marker=20260703w err=%s", exc)
        return False

    needle = "                success = self.apex.execute_action(analysis, sig.symbol)\n"
    if needle not in source:
        logger.warning("PHASE3_FALLBACK_HOLD_SKIP_PHASE3_NEEDLE_MISSING marker=20260703w")
        return False

    patched_source = source.replace(needle, _PHASE3_SKIP_BLOCK + needle, 1)
    namespace = dict(getattr(original, "__globals__", {}))
    try:
        exec(compile(patched_source, "<phase3_fallback_hold_skip_submit_guard>", "exec"), namespace)
        patched = namespace.get("_phase3_scan_and_enter")
        if not callable(patched):
            raise RuntimeError("patched _phase3_scan_and_enter not produced")
    except Exception as exc:
        logger.warning("PHASE3_FALLBACK_HOLD_SKIP_PHASE3_COMPILE_FAILED marker=20260703w err=%s", exc)
        return False

    setattr(patched, _PHASE3_WRAP_ATTR, True)
    setattr(patched, "__wrapped__", original)
    setattr(cls, "_phase3_scan_and_enter", patched)
    _PATCHED_CLASSES.add(f"{label}.{cls.__name__}._phase3_scan_and_enter")
    logger.warning("%s class=%s boundary=phase3_submit", _MARKER, f"{label}.{cls.__name__}")
    print(f"[NIJA-PRINT] PHASE3_FALLBACK_HOLD_SKIP_PATCHED marker=20260703w | class={label}.{cls.__name__} boundary=phase3_submit", flush=True)
    return True


def _patch_core_loop_class(cls: type, *, label: str) -> bool:
    patched = _patch_core_loop_phase3(cls, label=label)
    original_init = getattr(cls, "__init__", None)
    if not callable(original_init):
        return patched
    init_attr = _WRAP_ATTR + "_init"
    if getattr(original_init, init_attr, False):
        _PATCHED_CLASSES.add(f"{label}.{cls.__name__}.__init__")
        return True or patched

    def _patched_init(self: Any, *args: Any, **kwargs: Any) -> Any:
        result = original_init(self, *args, **kwargs)
        try:
            apex = getattr(self, "apex", None)
            if apex is not None:
                _patch_strategy_class(apex.__class__, label=f"{apex.__class__.__module__}")
        except Exception as exc:
            logger.warning("PHASE3_FALLBACK_HOLD_SKIP_APEX_PATCH_FAILED marker=20260703w err=%s", exc)
        return result

    setattr(_patched_init, init_attr, True)
    setattr(_patched_init, "__wrapped__", original_init)
    setattr(cls, "__init__", _patched_init)
    _PATCHED_CLASSES.add(f"{label}.{cls.__name__}.__init__")
    logger.warning("PHASE3_FALLBACK_HOLD_SKIP_CORE_INIT_PATCHED marker=20260703w class=%s", f"{label}.{cls.__name__}")
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

    for _attr_name, obj in list(vars(module).items()):
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
            "PHASE3_FALLBACK_HOLD_SKIP_MONITOR_COMPLETE marker=20260703w patched_any=%s patched_classes=%s",
            patched_any,
            sorted(_PATCHED_CLASSES),
        )

    threading.Thread(target=_monitor, name="phase3-fallback-hold-skip-monitor", daemon=True).start()
    logger.warning("PHASE3_FALLBACK_HOLD_SKIP_MONITOR_STARTED marker=20260703w")


def install_import_hook() -> None:
    global _ORIGINAL_IMPORT_MODULE
    with _INSTALL_LOCK:
        _try_patch_loaded()
        _start_monitor()
        if _ORIGINAL_IMPORT_MODULE is not None:
            logger.warning(
                "PHASE3_FALLBACK_HOLD_SKIP_INSTALL_COMPLETE marker=20260703w already_installed=True patched_classes=%s",
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
            "PHASE3_FALLBACK_HOLD_SKIP_INSTALL_COMPLETE marker=20260703w patched_classes=%s",
            sorted(_PATCHED_CLASSES),
        )
