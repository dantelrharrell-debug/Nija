"""NIJA Python startup defaults and execution safety wiring.

This file is imported automatically by Python when the repository root is on
``sys.path``.  Keep it small, deterministic, and defensive.

Applied guards:
- Normalize OKX US-region REST defaults and quoted credentials.
- Enforce live minimum order-size env values at >= $50 unless explicitly higher.
- Install lightweight import-time wrappers that run stale pending-order
  reconciliation before each scan/cycle.
- Emit WARNING telemetry around execute_action() so the signal -> execution
  handoff is visible in Railway logs.
"""

from __future__ import annotations

import builtins
import logging
import os
from functools import wraps
from typing import Any

logger = logging.getLogger("nija.startup_patch")


def _clean(value: str | None) -> str:
    text = str(value or "").strip().lstrip("\ufeff")
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
        text = text[1:-1].strip()
    return text.strip().strip('"').strip("'").strip()


def _env_truthy(name: str) -> bool:
    return str(os.environ.get(name, "")).strip().lower() in {"1", "true", "yes", "on", "y"}


def _float_env(name: str, default: float = 0.0) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


# US OKX accounts require the US regional REST host. Normalize legacy global
# hosts before broker_manager initializes, while preserving explicit custom
# non-global overrides.
_okx_base_url = _clean(os.getenv("OKX_BASE_URL")).rstrip("/")
if not _okx_base_url or _okx_base_url in {"https://www.okx.com", "https://openapi.okx.com"}:
    os.environ["OKX_BASE_URL"] = "https://us.okx.com"
os.environ.setdefault("OKX_US_REGION", "true")

# Normalize quoted Railway credential values without logging or exposing them.
for _name in (
    "OKX_API_KEY",
    "OKX_API_SECRET",
    "OKX_API_PASSPHRASE",
    "OKX_PASSPHRASE",
):
    if _name in os.environ:
        os.environ[_name] = _clean(os.environ.get(_name))

# Runtime defaults used by startup safety modules.
os.environ.setdefault("NIJA_STARTUP_POSITION_SYNC_ENABLED", "true")
os.environ.setdefault("NIJA_BROKER_SCOPED_POSITION_CAP", "true")
os.environ.setdefault("NIJA_PROFITABILITY_GUARD_ENABLED", "true")
os.environ.setdefault("NIJA_LOG_TRADE_DECISIONS", "true")
os.environ.setdefault("NIJA_PENDING_ORDER_TIMEOUT_S", "90")

# Live mode must use order sizes large enough to clear venue notional/fee rules.
_LIVE_MINIMUM_ENV_KEYS = (
    "MIN_TRADE_USD",
    "MIN_CASH_TO_BUY",
    "KRAKEN_MIN_NOTIONAL_USD",
    "COINBASE_MIN_ORDER_USD",
    "OKX_MIN_ORDER_USD",
)
_live_mode = _env_truthy("LIVE_CAPITAL_VERIFIED") and not _env_truthy("DRY_RUN_MODE") and not _env_truthy("PAPER_MODE")
if _live_mode:
    for _key in _LIVE_MINIMUM_ENV_KEYS:
        _current = _float_env(_key, 0.0)
        if _current < 50.0:
            os.environ[_key] = "50"

_PATCHED_ATTR = "__nija_pending_reconciler_patched__"
_ORIGINAL_IMPORT = builtins.__import__


def _resolve_pending_sources(instance: Any) -> tuple[Any, Any]:
    apex = getattr(instance, "apex", None)
    broker = (
        getattr(instance, "broker", None)
        or getattr(instance, "broker_client", None)
        or getattr(apex, "broker", None)
        or getattr(apex, "broker_client", None)
        or getattr(apex, "active_broker", None)
    )
    pending_orders = (
        getattr(instance, "pending_orders", None)
        or getattr(instance, "_pending_orders", None)
        or getattr(apex, "pending_orders", None)
        or getattr(apex, "_pending_orders", None)
    )
    return broker, pending_orders


def _run_pending_reconcile(instance: Any, label: str) -> None:
    try:
        try:
            from bot.pending_order_reconciler import reconcile_stale_pending_orders
        except ImportError:
            from pending_order_reconciler import reconcile_stale_pending_orders  # type: ignore[import]
        broker, pending_orders = _resolve_pending_sources(instance)
        result = reconcile_stale_pending_orders(
            owner=instance,
            broker=broker,
            pending_orders=pending_orders,
            timeout_s=_float_env("NIJA_PENDING_ORDER_TIMEOUT_S", 90.0),
        )
        if any((result.cleared, result.filled, result.cancelled, result.errors)):
            logger.warning(
                "PENDING_ORDER_RECONCILE_RESULT label=%s cleared=%d filled=%d cancelled=%d still_pending=%d errors=%d",
                label,
                result.cleared,
                result.filled,
                result.cancelled,
                result.still_pending,
                result.errors,
            )
    except Exception as exc:
        logger.warning("PENDING_ORDER_RECONCILE_ERROR label=%s error=%s", label, exc)


def _wrap_cycle_method(cls: type, method_name: str) -> None:
    original = getattr(cls, method_name, None)
    if not callable(original) or getattr(original, _PATCHED_ATTR, False):
        return

    @wraps(original)
    def _wrapped(self: Any, *args: Any, **kwargs: Any):
        _run_pending_reconcile(self, f"{cls.__name__}.{method_name}")
        return original(self, *args, **kwargs)

    setattr(_wrapped, _PATCHED_ATTR, True)
    setattr(cls, method_name, _wrapped)
    logger.warning("PENDING_ORDER_RECONCILER_WIRED class=%s method=%s", cls.__name__, method_name)


def _wrap_execute_action(cls: type) -> None:
    original = getattr(cls, "execute_action", None)
    if not callable(original) or getattr(original, _PATCHED_ATTR, False):
        return

    @wraps(original)
    def _wrapped(self: Any, analysis: Any, symbol: str, *args: Any, **kwargs: Any):
        try:
            action = analysis.get("action") if isinstance(analysis, dict) else None
            size = analysis.get("position_size") if isinstance(analysis, dict) else None
            logger.warning("EXECUTE_ACTION_ENTRY symbol=%s action=%s size=%s", symbol, action, size)
        except Exception:
            logger.warning("EXECUTE_ACTION_ENTRY symbol=%s action=<unavailable>", symbol)
        try:
            result = original(self, analysis, symbol, *args, **kwargs)
            if result:
                logger.warning("EXECUTE_ACTION_RESULT symbol=%s success=True", symbol)
            else:
                logger.warning("EXECUTE_ACTION_RESULT symbol=%s success=False reason=execute_action_returned_false", symbol)
            return result
        except Exception as exc:
            logger.exception("EXECUTE_ACTION_EXCEPTION symbol=%s error=%s", symbol, exc)
            raise

    setattr(_wrapped, _PATCHED_ATTR, True)
    setattr(cls, "execute_action", _wrapped)
    logger.warning("EXECUTE_ACTION_TELEMETRY_WIRED class=%s", cls.__name__)


def _patch_module(module: Any) -> None:
    if module is None:
        return
    try:
        core_cls = getattr(module, "NijaCoreLoop", None)
        if isinstance(core_cls, type):
            for method_name in ("run_cycle", "run_scan_phase", "_phase3_scan_and_enter"):
                _wrap_cycle_method(core_cls, method_name)
    except Exception as exc:
        logger.warning("STARTUP_PATCH_CORE_LOOP_ERROR module=%s error=%s", getattr(module, "__name__", "?"), exc)
    try:
        apex_cls = getattr(module, "NIJAApexStrategyV71", None)
        if isinstance(apex_cls, type):
            _wrap_execute_action(apex_cls)
    except Exception as exc:
        logger.warning("STARTUP_PATCH_APEX_ERROR module=%s error=%s", getattr(module, "__name__", "?"), exc)
    try:
        strategy_cls = getattr(module, "TradingStrategy", None)
        if isinstance(strategy_cls, type):
            _wrap_cycle_method(strategy_cls, "run_cycle")
    except Exception as exc:
        logger.warning("STARTUP_PATCH_TRADING_STRATEGY_ERROR module=%s error=%s", getattr(module, "__name__", "?"), exc)


def _patched_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
    module = _ORIGINAL_IMPORT(name, globals, locals, fromlist, level)
    target_names = {name, getattr(module, "__name__", name)}
    if any(t.endswith(("nija_core_loop", "nija_apex_strategy_v71", "trading_strategy")) for t in target_names):
        _patch_module(module)
        for attr in ("nija_core_loop", "nija_apex_strategy_v71", "trading_strategy"):
            _patch_module(getattr(module, attr, None))
    return module


if not getattr(builtins.__import__, "__nija_startup_patch_installed__", False):
    setattr(_patched_import, "__nija_startup_patch_installed__", True)
    builtins.__import__ = _patched_import
