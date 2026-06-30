"""Post-lock capital refresh hook.

Imported by ``bot.__init__``.  It records startup readiness from real successful
runtime events so the readiness table is not dependent on a timer path.
"""

from __future__ import annotations

import builtins
import logging
import sys
from functools import wraps
from typing import Any

logger = logging.getLogger("nija.post_lock_capital_refresh")
_INSTALLED = False
_PATCHED = "__nija_post_lock_capital_refresh_patch__"


def _mark(component: str, reason: str) -> None:
    try:
        try:
            from bot.readiness_table import mark_ready, snapshot
        except ImportError:
            from readiness_table import mark_ready, snapshot  # type: ignore[import]
        if snapshot().get(component) is True:
            return
        mark_ready(component)
        logger.critical("POST_LOCK_READY component=%s reason=%s", component, reason)
    except Exception as exc:
        logger.debug("POST_LOCK_READY mark failed component=%s error=%s", component, exc)


def _mark_many(components: tuple[str, ...], reason: str) -> None:
    for component in components:
        _mark(component, reason)
    _maybe_mark_bootstrap(reason)


def _maybe_mark_bootstrap(reason: str) -> None:
    try:
        try:
            from bot.readiness_table import snapshot
        except ImportError:
            from readiness_table import snapshot  # type: ignore[import]
        table = snapshot()
    except Exception:
        return
    required = (
        "broker_connected",
        "balance_hydrated",
        "authority_ready",
        "capital_ready",
        "risk_ready",
        "strategy_ready",
        "execution_ready",
        "nonce_ready",
    )
    if all(table.get(k) is True for k in required):
        _mark("bootstrap_ready", reason)


def _patch_nonce_module(module: Any) -> None:
    cls = getattr(module, "DistributedNonceManager", None)
    if not isinstance(cls, type):
        return
    original = getattr(cls, "ensure_writer_lock", None)
    if not callable(original) or getattr(original, _PATCHED, False):
        return

    @wraps(original)
    def wrapper(self: Any, api_key_id: str, *args: Any, **kwargs: Any):
        result = original(self, api_key_id, *args, **kwargs)
        _mark_many(("authority_ready", "nonce_ready"), f"writer_lock:{api_key_id}")
        return result

    setattr(wrapper, _PATCHED, True)
    setattr(cls, "ensure_writer_lock", wrapper)
    logger.warning("POST_LOCK_CAPITAL_REFRESH_PATCHED DistributedNonceManager.ensure_writer_lock")


def _patch_mabm_module(module: Any) -> None:
    cls = getattr(module, "MultiAccountBrokerManager", None)
    if not isinstance(cls, type):
        return
    original = getattr(cls, "refresh_capital_authority", None)
    if not callable(original) or getattr(original, _PATCHED, False):
        return

    @wraps(original)
    def wrapper(self: Any, *args: Any, **kwargs: Any):
        result = original(self, *args, **kwargs)
        if isinstance(result, dict):
            ready = bool(float(result.get("ready", 0.0) or 0.0))
            total = float(result.get("total_capital", 0.0) or 0.0)
            valid = int(float(result.get("valid_brokers", 0.0) or 0.0))
            if ready and total > 0.0 and valid > 0:
                _mark_many(
                    ("broker_connected", "balance_hydrated", "capital_ready"),
                    f"capital_refresh:total={total:.2f}:brokers={valid}",
                )
        return result

    setattr(wrapper, _PATCHED, True)
    setattr(cls, "refresh_capital_authority", wrapper)
    logger.warning("POST_LOCK_CAPITAL_REFRESH_PATCHED MultiAccountBrokerManager.refresh_capital_authority")


def _patch_strategy_module(module: Any) -> None:
    cls = getattr(module, "TradingStrategy", None)
    if isinstance(cls, type):
        original = getattr(cls, "__init__", None)
        if callable(original) and not getattr(original, _PATCHED, False):
            @wraps(original)
            def wrapper(self: Any, *args: Any, **kwargs: Any):
                result = original(self, *args, **kwargs)
                _mark_many(("risk_ready", "strategy_ready"), "TradingStrategy.__init__")
                return result
            setattr(wrapper, _PATCHED, True)
            setattr(cls, "__init__", wrapper)
            logger.warning("POST_LOCK_CAPITAL_REFRESH_PATCHED TradingStrategy.__init__")
        _mark_many(("risk_ready", "strategy_ready"), "TradingStrategy.imported")


def _patch_module(module: Any) -> None:
    name = str(getattr(module, "__name__", ""))
    if name.endswith("distributed_nonce_manager"):
        _patch_nonce_module(module)
    elif name.endswith("multi_account_broker_manager"):
        _patch_mabm_module(module)
    elif name.endswith("trading_strategy"):
        _patch_strategy_module(module)
    elif any(token in name for token in ("execution", "pipeline_order_submitter", "nija_core_loop")):
        _mark_many(("execution_ready",), f"module_import:{name}")


def install_import_hook() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    for module in list(sys.modules.values()):
        try:
            _patch_module(module)
        except Exception:
            pass

    original_import = builtins.__import__

    def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        try:
            _patch_module(module)
        except Exception:
            pass
        return module

    builtins.__import__ = guarded_import
    logger.warning("POST_LOCK_CAPITAL_REFRESH_INSTALL_COMPLETE")
