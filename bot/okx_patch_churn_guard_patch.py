from __future__ import annotations

import builtins
import logging
import sys
from functools import wraps
from types import ModuleType
from typing import Any, Callable, Optional

logger = logging.getLogger("nija.okx_patch_churn_guard")
_MARKER = "20260709aw"
_HOOK = "_NIJA_OKX_PATCH_CHURN_GUARD_HOOK_20260709AW"
_GUARDED = "_nija_okx_patch_churn_guarded_20260709aw"
_TARGETS = {
    "bot.broker_manager",
    "broker_manager",
    "bot.broker_integration",
    "broker_integration",
    "bot.multi_account_broker_manager",
    "multi_account_broker_manager",
    "bot.multi_broker_execution_router",
    "multi_broker_execution_router",
}


def _has_marker_chain(fn: Any, marker: str, max_depth: int = 32) -> bool:
    seen: set[int] = set()
    current = fn
    for _ in range(max_depth):
        if not callable(current) or id(current) in seen:
            return False
        seen.add(id(current))
        if bool(getattr(current, marker, False)):
            return True
        current = getattr(current, "__wrapped__", None)
    return False


def _narrow_interesting(name: str) -> bool:
    lowered = str(name or "").lower()
    return lowered in _TARGETS or "okx" in lowered


def _guard_instid_module(module: ModuleType) -> bool:
    if getattr(module, _GUARDED, False):
        return True
    marker = str(getattr(module, "_ORDER_WRAP_ATTR", ""))
    normalize = getattr(module, "_normalize_inst_id", None)
    if not marker or not callable(normalize):
        return False

    def _wrap_order_class(okx_cls: type, module_name: str) -> bool:
        patched = False
        for method_name in ("place_market_order", "execute_order", "place_order"):
            current = getattr(okx_cls, method_name, None)
            if not callable(current) or _has_marker_chain(current, marker):
                continue

            def _make_wrapper(fn: Callable[..., Any], name: str):
                @wraps(fn)
                def _patched_order(self: Any, symbol: Any, side: Any, quantity: Any, *args: Any, **kwargs: Any) -> Any:
                    before = str(symbol or "")
                    after = normalize(before)
                    if after != before:
                        module.logger.critical(
                            "OKX_ORDER_SYMBOL_NORMALIZED marker=%s method=%s before=%s after=%s",
                            module._MARKER,
                            name,
                            before,
                            after,
                        )
                    return fn(self, after, side, quantity, *args, **kwargs)

                setattr(_patched_order, marker, True)
                setattr(_patched_order, "__wrapped__", fn)
                return _patched_order

            setattr(okx_cls, method_name, _make_wrapper(current, method_name))
            patched = True
        return patched

    module._wrap_order_class = _wrap_order_class
    module._interesting_module = _narrow_interesting
    setattr(module, _GUARDED, True)
    logger.warning("OKX_PATCH_CHURN_GUARD_APPLIED marker=%s target=instid", _MARKER)
    return True


def _guard_final_module(module: ModuleType) -> bool:
    if getattr(module, _GUARDED, False):
        return True
    marker = str(getattr(module, "_ORDER_WRAP_ATTR", ""))
    parse = getattr(module, "_parse_order_call", None)
    normalize = getattr(module, "_normalize_inst_id", None)
    call_base = getattr(module, "_call_base", None)
    to_float = getattr(module, "_f", None)
    if not marker or not all(callable(fn) for fn in (parse, normalize, call_base, to_float)):
        return False

    def _wrap_order_class(okx_cls: type, module_name: str) -> bool:
        patched = False
        for method_name in ("place_market_order", "execute_order", "place_order"):
            current = getattr(okx_cls, method_name, None)
            if not callable(current) or _has_marker_chain(current, marker):
                continue

            def _make_wrapper(fn: Callable[..., Any], name: str):
                @wraps(fn)
                def _patched_order(self: Any, *args: Any, **kwargs: Any) -> Any:
                    symbol, side, quantity, payload, remaining, parsed_kwargs, shape = parse(args, kwargs)
                    inst_id = normalize(symbol)
                    order_side = str(side or "").lower().strip()
                    order_qty = to_float(quantity, 0.0)
                    if not inst_id or not order_side or order_qty <= 0:
                        reason = (
                            f"OKX_CALLSHAPE_BLOCK missing_or_invalid_order_fields method={name} "
                            f"symbol={symbol!r} side={side!r} quantity={quantity!r} shape={shape}"
                        )
                        module.logger.critical("%s marker=%s", reason, module._MARKER)
                        return {
                            "status": "error",
                            "error": reason,
                            "error_code": "OKX_CALLSHAPE_BLOCK",
                            "symbol": inst_id,
                            "side": order_side,
                            "quantity": quantity,
                        }
                    module.logger.critical(
                        "FINAL_OKX_SUBMIT_CALL marker=%s method=%s symbol=%s side=%s quantity=%s shape=%s",
                        module._MARKER,
                        name,
                        inst_id,
                        order_side,
                        order_qty,
                        shape,
                    )
                    return call_base(
                        fn,
                        self,
                        symbol=inst_id,
                        side=order_side,
                        quantity=order_qty,
                        payload=payload,
                        remaining=remaining,
                        kwargs=parsed_kwargs,
                        method_name=name,
                    )

                setattr(_patched_order, marker, True)
                setattr(_patched_order, "__wrapped__", fn)
                return _patched_order

            setattr(okx_cls, method_name, _make_wrapper(current, method_name))
            try:
                module._PATCHED_ORDER_CLASSES.add(
                    f"{getattr(okx_cls, '__module__', '')}.{getattr(okx_cls, '__name__', '')}.{method_name}"
                )
            except Exception:
                pass
            patched = True
        return patched

    module._wrap_order_class = _wrap_order_class
    module._interesting_module = _narrow_interesting
    setattr(module, _GUARDED, True)
    logger.warning("OKX_PATCH_CHURN_GUARD_APPLIED marker=%s target=final", _MARKER)
    return True


def _guard_module(name: str, module: ModuleType) -> bool:
    if name.endswith("okx_order_instid_payload_repair_patch"):
        return _guard_instid_module(module)
    if name.endswith("okx_final_order_submission_bridge_patch"):
        return _guard_final_module(module)
    return False


def _guard_loaded() -> bool:
    guarded = False
    for name in (
        "bot.okx_order_instid_payload_repair_patch",
        "okx_order_instid_payload_repair_patch",
        "bot.okx_final_order_submission_bridge_patch",
        "okx_final_order_submission_bridge_patch",
    ):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            guarded = _guard_module(name, module) or guarded
    return guarded


def install_import_hook() -> None:
    _guard_loaded()
    if getattr(builtins, _HOOK, False):
        return
    original_import = builtins.__import__

    def importing(name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        if str(name).endswith(("okx_order_instid_payload_repair_patch", "okx_final_order_submission_bridge_patch")):
            _guard_loaded()
        return module

    builtins.__import__ = importing
    setattr(builtins, _HOOK, True)
    logger.warning("OKX_PATCH_CHURN_GUARD_INSTALL_COMPLETE marker=%s guarded=%s", _MARKER, _guard_loaded())


def install() -> None:
    install_import_hook()
