"""NIJA Python startup defaults and execution safety wiring.

This file is imported automatically by Python when the repository root is on
``sys.path``.  Keep it small, deterministic, and defensive.

Applied guards:
- Normalize OKX US-region REST defaults and quoted credentials.
- Enforce live minimum order-size env values at >= $50 unless explicitly higher.
- Install lightweight import-time wrappers that run stale pending/open-order
  reconciliation before each scan/cycle.
- Emit WARNING telemetry around execute_action() so the signal -> execution
  handoff is visible in Railway logs.
- Clear unsafe writer-lock bypass once a Redis writer lease/fencing token is
  present, so runtime authority converges back to strict Redis authority.
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


def _redis_authority_materialized() -> bool:
    """Return True once Redis single-writer authority has concrete lineage."""
    token = _clean(os.environ.get("NIJA_WRITER_FENCING_TOKEN"))
    generation = _clean(os.environ.get("NIJA_WRITER_LEASE_GENERATION"))
    heartbeat = _clean(os.environ.get("NIJA_WRITER_HEARTBEAT_ACTIVE"))
    return bool(token or generation or heartbeat in {"1", "true", "TRUE", "yes", "on"})


def _normalize_authority_after_redis_lease(label: str = "startup") -> None:
    """Disable emergency local-writer bypass after Redis authority is present.

    Railway env can still contain NIJA_UNSAFE_BYPASS_DISTRIBUTED_LOCK=true from
    an emergency deploy. Once Redis writer lineage exists, continuing to honor
    that bypass creates false STARTUP_OBSERVER_STANDBY warnings and can confuse
    authority checks. This guard switches the process back to strict Redis
    authority in-memory without requiring an immediate Railway variable edit.
    """
    if not _redis_authority_materialized():
        return
    changed = []
    for key in (
        "NIJA_UNSAFE_BYPASS_DISTRIBUTED_LOCK",
        "NIJA_DISABLE_WRITER_LOCK",
        "NIJA_FORCE_LOCAL_WRITER_LOCK_FALLBACK",
        "NIJA_CONFIRM_BYPASS_RISKS",
    ):
        if _env_truthy(key):
            os.environ[key] = "false"
            changed.append(key)
    if changed:
        os.environ["NIJA_REQUIRE_DISTRIBUTED_LOCK"] = "true"
        os.environ["NIJA_STRICT_REDIS_LEASE"] = "1"
        os.environ["NIJA_AUTHORITY_NORMALIZED_AFTER_REDIS_LEASE"] = "1"
        logger.warning(
            "AUTHORITY_NORMALIZED_AFTER_REDIS_LEASE label=%s cleared=%s require_distributed_lock=true strict_redis_lease=1",
            label,
            ",".join(changed),
        )


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
os.environ.setdefault("NIJA_RECONCILE_BROKER_OPEN_ORDERS", "true")

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
        or getattr(instance, "active_broker", None)
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


def _broker_name(broker: Any) -> str:
    return str(
        getattr(broker, "name", None)
        or getattr(broker, "broker_name", None)
        or getattr(broker, "exchange", None)
        or broker.__class__.__name__
        if broker is not None
        else "unknown"
    )


def _fetch_broker_open_orders(broker: Any) -> list[Any]:
    if broker is None or not _env_truthy("NIJA_RECONCILE_BROKER_OPEN_ORDERS"):
        return []
    for method_name in (
        "get_open_orders",
        "fetch_open_orders",
        "list_open_orders",
        "open_orders",
        "get_pending_orders",
    ):
        method = getattr(broker, method_name, None)
        if not callable(method):
            continue
        try:
            response = method()
            if response is None:
                return []
            if isinstance(response, dict):
                for key in ("orders", "open_orders", "data", "result"):
                    value = response.get(key)
                    if isinstance(value, list):
                        return list(value)
                return [response]
            if isinstance(response, (list, tuple, set)):
                return list(response)
            return [response]
        except TypeError:
            # Some broker methods require a symbol; skip instead of blocking startup.
            continue
        except Exception as exc:
            logger.warning("BROKER_OPEN_ORDER_FETCH_ERROR broker=%s method=%s error=%s", _broker_name(broker), method_name, exc)
            return []
    return []


def _run_pending_reconcile(instance: Any, label: str) -> None:
    _normalize_authority_after_redis_lease(label)
    try:
        try:
            from bot.pending_order_reconciler import reconcile_stale_pending_orders
        except ImportError:
            from pending_order_reconciler import reconcile_stale_pending_orders  # type: ignore[import]
        broker, pending_orders = _resolve_pending_sources(instance)
        broker_open_orders = _fetch_broker_open_orders(broker)
        orders = list(pending_orders or []) + list(broker_open_orders or [])
        result = reconcile_stale_pending_orders(
            owner=instance,
            broker=broker,
            pending_orders=orders,
            timeout_s=_float_env("NIJA_PENDING_ORDER_TIMEOUT_S", 90.0),
        )
        if broker_open_orders:
            logger.warning(
                "BROKER_OPEN_ORDER_RECONCILE_CHECK label=%s broker=%s open_orders=%d cleared=%d filled=%d cancelled=%d still_pending=%d errors=%d",
                label,
                _broker_name(broker),
                len(broker_open_orders),
                result.cleared,
                result.filled,
                result.cancelled,
                result.still_pending,
                result.errors,
            )
        elif any((result.cleared, result.filled, result.cancelled, result.errors)):
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


def _wrap_connect_method(cls: type) -> None:
    original = getattr(cls, "connect", None)
    if not callable(original) or getattr(original, _PATCHED_ATTR, False):
        return

    @wraps(original)
    def _wrapped(self: Any, *args: Any, **kwargs: Any):
        result = original(self, *args, **kwargs)
        _normalize_authority_after_redis_lease(f"{cls.__name__}.connect")
        try:
            # Immediately classify broker-held funds after connect so Kraken held
            # balances are surfaced before the scan phase.
            orders = _fetch_broker_open_orders(self)
            if orders:
                try:
                    from bot.pending_order_reconciler import reconcile_stale_pending_orders
                except ImportError:
                    from pending_order_reconciler import reconcile_stale_pending_orders  # type: ignore[import]
                reconcile_result = reconcile_stale_pending_orders(
                    owner=self,
                    broker=self,
                    pending_orders=orders,
                    timeout_s=_float_env("NIJA_PENDING_ORDER_TIMEOUT_S", 90.0),
                )
                logger.warning(
                    "STARTUP_BROKER_OPEN_ORDER_RECONCILE broker=%s open_orders=%d cleared=%d filled=%d cancelled=%d still_pending=%d errors=%d",
                    _broker_name(self),
                    len(orders),
                    reconcile_result.cleared,
                    reconcile_result.filled,
                    reconcile_result.cancelled,
                    reconcile_result.still_pending,
                    reconcile_result.errors,
                )
        except Exception as exc:
            logger.warning("STARTUP_BROKER_OPEN_ORDER_RECONCILE_ERROR broker=%s error=%s", _broker_name(self), exc)
        return result

    setattr(_wrapped, _PATCHED_ATTR, True)
    setattr(cls, "connect", _wrapped)
    logger.warning("BROKER_CONNECT_RECONCILE_WIRED class=%s", cls.__name__)


def _wrap_execute_action(cls: type) -> None:
    original = getattr(cls, "execute_action", None)
    if not callable(original) or getattr(original, _PATCHED_ATTR, False):
        return

    @wraps(original)
    def _wrapped(self: Any, analysis: Any, symbol: str, *args: Any, **kwargs: Any):
        _normalize_authority_after_redis_lease(f"{cls.__name__}.execute_action")
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
    for cls_name in ("KrakenBroker", "CoinbaseBroker", "OKXBroker", "OkxBroker"):
        try:
            broker_cls = getattr(module, cls_name, None)
            if isinstance(broker_cls, type):
                _wrap_connect_method(broker_cls)
        except Exception as exc:
            logger.warning("STARTUP_PATCH_BROKER_ERROR module=%s class=%s error=%s", getattr(module, "__name__", "?"), cls_name, exc)


def _patched_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
    module = _ORIGINAL_IMPORT(name, globals, locals, fromlist, level)
    target_names = {name, getattr(module, "__name__", name)}
    if any(t.endswith(("nija_core_loop", "nija_apex_strategy_v71", "trading_strategy", "broker_manager")) for t in target_names):
        _patch_module(module)
        for attr in ("nija_core_loop", "nija_apex_strategy_v71", "trading_strategy", "broker_manager"):
            _patch_module(getattr(module, attr, None))
    return module


if not getattr(builtins.__import__, "__nija_startup_patch_installed__", False):
    setattr(_patched_import, "__nija_startup_patch_installed__", True)
    builtins.__import__ = _patched_import
    _normalize_authority_after_redis_lease("sitecustomize_install")
