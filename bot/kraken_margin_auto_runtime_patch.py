"""Runtime convergence bridge for account-scoped Kraken spot margin.

v223 preserves KrakenBroker.place_market_order()'s native public call shape and
injects margin fields only at the private AddOrder payload boundary.  This keeps
all existing nonce, writer-authority, validation, maker/market fallback, txid,
and fill checks on the canonical broker path while ensuring leverage actually
reaches Kraken.
"""

from __future__ import annotations

import builtins
import logging
import os
import sys
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from types import ModuleType
from typing import Any, Callable, Dict, Iterator, Optional

logger = logging.getLogger("nija.kraken_margin_auto_runtime")
_MARKER = "20260824-kraken-margin-callshape-v223"
_ORIGINAL_IMPORT: Optional[Callable[..., Any]] = None
_LOCK = threading.RLock()
_PATCHED_MODULES: set[tuple[str, int]] = set()
_MARGIN_ORDER_PARAMS: ContextVar[Optional[Dict[str, Any]]] = ContextVar(
    "nija_kraken_margin_order_params_v223",
    default=None,
)


def _is_kraken(broker: Any) -> bool:
    if broker is None:
        return False
    values = (
        type(broker).__name__,
        getattr(broker, "NAME", ""),
        getattr(getattr(broker, "broker_type", None), "value", getattr(broker, "broker_type", "")),
    )
    return any("kraken" in str(value or "").lower() for value in values)


def _account_id(broker: Any, metadata: Dict[str, Any]) -> str:
    for value in (
        metadata.get("account_id"),
        getattr(broker, "account_identifier", None),
        getattr(broker, "account_id", None),
        getattr(broker, "user_id", None),
    ):
        text = str(value or "").strip().lower()
        if text and text not in {"none", "kraken"}:
            return text
    return "platform"


def _install_defaults() -> None:
    os.environ.setdefault("NIJA_KRAKEN_MARGIN_ENABLED", "true")
    os.environ.setdefault("NIJA_KRAKEN_AUTO_MARGIN_ENABLED", "true")
    os.environ.setdefault("NIJA_KRAKEN_MARGIN_DEFAULT_LEVERAGE", "2")
    os.environ.setdefault("NIJA_KRAKEN_AUTO_MARGIN_LONG_ONLY", "true")
    os.environ.setdefault("NIJA_KRAKEN_MARGIN_HARD_MAX_LEVERAGE", "3")


def _patch_capability_matrix(module: ModuleType) -> bool:
    matrix = getattr(module, "EXCHANGE_CAPABILITIES", None)
    market_mode = getattr(module, "MarketMode", None)
    capability_cls = getattr(module, "ExchangeCapabilities", None)
    if matrix is None or market_mode is None or capability_cls is None:
        return False
    try:
        mode = market_mode.MARGIN
        matrix._capabilities.setdefault("kraken", {})[mode] = capability_cls(
            broker_name="kraken",
            market_mode=mode,
            supports_long=True,
            supports_short=True,
            supports_margin=True,
            supports_leverage=True,
            max_leverage=3.0,
            requires_margin_account=False,
            has_stop_loss=True,
            has_take_profit=True,
            has_trailing_stop=False,
            taker_fee=0.0026,
            maker_fee=0.0016,
            spread_cost=0.001,
        )
        logger.warning("KRAKEN_MARGIN_CAPABILITY_INSTALLED marker=%s max_leverage=3x", _MARKER)
        return True
    except Exception as exc:
        logger.warning("KRAKEN_MARGIN_CAPABILITY_INSTALL_FAILED marker=%s error=%s", _MARKER, exc)
        return False


def _normalize_margin_result(result: Any, *, size_usd: float, metadata: Dict[str, Any]) -> tuple[float, float]:
    if isinstance(result, tuple) and len(result) >= 2:
        return float(result[0] or 0.0), float(result[1] or size_usd)
    if not isinstance(result, dict):
        raise RuntimeError(f"Unsupported Kraken margin response: {result!r}")
    status = str(result.get("status") or result.get("state") or "").strip().lower()
    if status in {"error", "failed", "rejected", "canceled", "cancelled"}:
        raise RuntimeError(str(result.get("error") or result.get("message") or status))
    fill_price = float(
        result.get("filled_price")
        or result.get("average_filled_price")
        or result.get("average_fill_price")
        or result.get("avg_price")
        or result.get("price")
        or metadata.get("price_hint_usd")
        or 0.0
    )
    filled_usd = float(
        result.get("filled_size_usd")
        or result.get("filled_value")
        or result.get("notional_usd")
        or result.get("size_usd")
        or size_usd
    )
    order_id = result.get("order_id") or result.get("id") or result.get("exchange_order_id")
    if fill_price <= 0 and not order_id:
        raise RuntimeError(f"Kraken margin order acknowledged without fill price/order id: {result!r}")
    return fill_price, filled_usd


def _clamp_leverage(value: Any) -> int:
    try:
        return min(3, max(1, int(float(value or 1))))
    except Exception:
        return 1


@contextmanager
def _margin_order_scope(leverage: Any, reduce_only: bool) -> Iterator[None]:
    lev = _clamp_leverage(leverage)
    if lev <= 1:
        yield
        return
    token = _MARGIN_ORDER_PARAMS.set(
        {
            "leverage": str(lev),
            "reduce_only": bool(reduce_only),
        }
    )
    try:
        yield
    finally:
        _MARGIN_ORDER_PARAMS.reset(token)


def _patch_kraken_class(cls: type) -> bool:
    """Patch the canonical private-call boundary, never the broker's public signature."""
    current = getattr(cls, "_kraken_private_call", None)
    if not callable(current):
        return False
    if getattr(current, "_nija_kraken_margin_addorder_v223", False):
        return True
    original = current

    @wraps(original)
    def private_call_v223(self: Any, method: str, params: Optional[Dict[str, Any]] = None, *args: Any, **kwargs: Any) -> Any:
        payload = dict(params or {})
        scoped = _MARGIN_ORDER_PARAMS.get()
        if scoped and str(method or "").strip().lower() == "addorder":
            leverage = str(scoped.get("leverage") or "").strip()
            reduce_only = bool(scoped.get("reduce_only"))
            existing_leverage = payload.get("leverage")
            if existing_leverage not in (None, "") and str(existing_leverage) != leverage:
                raise RuntimeError(
                    f"KRAKEN_MARGIN_PAYLOAD_CONFLICT:leverage existing={existing_leverage} scoped={leverage}"
                )
            payload["leverage"] = leverage
            if reduce_only:
                existing_reduce = payload.get("reduce_only")
                if existing_reduce not in (None, True, 1, "1", "true", "True"):
                    raise RuntimeError(
                        f"KRAKEN_MARGIN_PAYLOAD_CONFLICT:reduce_only existing={existing_reduce} scoped=true"
                    )
                payload["reduce_only"] = True
            logger.critical(
                "KRAKEN_MARGIN_ADDORDER_V223 marker=%s account=%s pair=%s side=%s leverage=%sx "
                "reduce_only=%s native_place_market_order_callshape=true spot_fallback=false",
                _MARKER,
                _account_id(self, {}),
                payload.get("pair") or "unknown",
                payload.get("type") or "unknown",
                leverage,
                str(reduce_only).lower(),
            )
        return original(self, method, payload, *args, **kwargs)

    setattr(private_call_v223, "_nija_kraken_margin_addorder_v223", True)
    setattr(private_call_v223, "__wrapped__", original)
    setattr(cls, "_kraken_private_call", private_call_v223)
    logger.warning(
        "KRAKEN_MARGIN_PRIVATE_CALL_PATCHED marker=%s class=%s native_public_signature_preserved=true",
        _MARKER,
        getattr(cls, "__name__", "unknown"),
    )
    return True


def _patch_kraken_adapter(module: ModuleType) -> bool:
    patched = False
    for name in dir(module):
        cls = getattr(module, name, None)
        if not isinstance(cls, type) or "kraken" not in name.lower():
            continue
        patched = _patch_kraken_class(cls) or patched
    return patched


def _patch_router(module: ModuleType) -> bool:
    cls = getattr(module, "MultiBrokerExecutionRouter", None)
    if not isinstance(cls, type):
        return False
    current = getattr(cls, "_dispatch_direct_broker_market_order", None)
    if not callable(current):
        return False
    if getattr(current, "_nija_kraken_margin_dispatch_v223", False):
        return True
    original = current

    def dispatch_direct_broker_market_order(
        broker: Any,
        *,
        symbol: str,
        side: str,
        size_usd: float,
        metadata: Dict[str, Any],
    ) -> tuple[float, float]:
        meta = dict(metadata or {})
        leverage = _clamp_leverage(meta.get("leverage"))
        if not _is_kraken(broker) or leverage <= 1:
            return original(
                broker,
                symbol=symbol,
                side=side,
                size_usd=size_usd,
                metadata=meta,
            )

        reduce_only = meta.get("reduce_only") is True
        account = _account_id(broker, meta)
        try:
            from bot.kraken_margin_engine import get_margin_engine, margin_account_scope

            engine = get_margin_engine(account_id=account, adapter=broker)
            allowed, reason = engine.is_margin_trade_allowed(
                is_reducing=reduce_only,
                adapter=broker,
            )
            pair_values = engine.get_pair_leverages(symbol, side, adapter=broker)
            if not allowed:
                raise RuntimeError(reason)
            if leverage not in pair_values:
                raise RuntimeError(f"pair_leverage_unavailable:{pair_values or 'none'}")
            if not _patch_kraken_class(type(broker)):
                raise RuntimeError("kraken_private_addorder_boundary_unavailable")
            submit = getattr(broker, "place_market_order", None)
            if not callable(submit):
                raise RuntimeError(f"Broker {broker!r} has no place_market_order method")

            logger.critical(
                "KRAKEN_MARGIN_ORDER_COMPILED marker=%s account=%s symbol=%s side=%s "
                "notional=$%.2f leverage=%sx reduce_only=%s native_callshape=true",
                _MARKER,
                account,
                symbol,
                side,
                float(size_usd),
                leverage,
                reduce_only,
            )
            with margin_account_scope(account, adapter=broker), _margin_order_scope(leverage, reduce_only):
                # IMPORTANT: preserve the canonical KrakenBroker public signature.
                # The scoped private-call wrapper adds leverage/reduce_only only to
                # the AddOrder payload created inside place_market_order().
                result = submit(
                    symbol,
                    side,
                    float(size_usd),
                    size_type="quote",
                )
            fill_price, filled_usd = _normalize_margin_result(
                result,
                size_usd=float(size_usd),
                metadata=meta,
            )
            logger.critical(
                "KRAKEN_MARGIN_ORDER_ACK marker=%s account=%s symbol=%s leverage=%sx "
                "reduce_only=%s native_callshape=true",
                _MARKER,
                account,
                symbol,
                leverage,
                reduce_only,
            )
            return fill_price, filled_usd
        except Exception as exc:
            logger.error(
                "KRAKEN_MARGIN_DISPATCH_BLOCKED marker=%s account=%s symbol=%s side=%s "
                "leverage=%sx reduce_only=%s reason=%s spot_fallback=false",
                _MARKER,
                account,
                symbol,
                side,
                leverage,
                reduce_only,
                exc,
            )
            raise

    setattr(dispatch_direct_broker_market_order, "_nija_kraken_margin_dispatch_v223", True)
    setattr(dispatch_direct_broker_market_order, "__wrapped__", original)
    setattr(cls, "_dispatch_direct_broker_market_order", staticmethod(dispatch_direct_broker_market_order))
    logger.warning("KRAKEN_MARGIN_ROUTER_BRIDGE_PATCHED marker=%s native_callshape=true", _MARKER)
    return True


def _patch_module(module: ModuleType) -> bool:
    key = (str(getattr(module, "__name__", "")), id(module))
    with _LOCK:
        if key in _PATCHED_MODULES:
            return True
        name = str(getattr(module, "__name__", ""))
        patched = False
        if name.endswith("exchange_capabilities"):
            patched = _patch_capability_matrix(module) or patched
        if name.endswith("multi_broker_execution_router"):
            patched = _patch_router(module) or patched
        if name.endswith(("broker_integration", "kraken_broker", "broker_manager")):
            patched = _patch_kraken_adapter(module) or patched
        if patched:
            _PATCHED_MODULES.add(key)
        return patched


def _patch_loaded() -> None:
    suffixes = (
        "exchange_capabilities",
        "multi_broker_execution_router",
        "broker_integration",
        "kraken_broker",
        "broker_manager",
    )
    for name, module in list(sys.modules.items()):
        if isinstance(module, ModuleType) and name.endswith(suffixes):
            try:
                _patch_module(module)
            except Exception as exc:
                logger.debug("KRAKEN_MARGIN_PATCH_WAIT module=%s error=%s", name, exc)


def install_import_hook() -> None:
    global _ORIGINAL_IMPORT
    _install_defaults()
    _patch_loaded()
    if _ORIGINAL_IMPORT is not None:
        return
    _ORIGINAL_IMPORT = builtins.__import__
    local = threading.local()

    def import_hook(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        module = _ORIGINAL_IMPORT(name, globals, locals, fromlist, level)  # type: ignore[misc]
        if getattr(local, "active", False):
            return module
        local.active = True
        try:
            _patch_loaded()
        finally:
            local.active = False
        return module

    builtins.__import__ = import_hook  # type: ignore[assignment]
    _patch_loaded()
    logger.critical(
        "KRAKEN_MARGIN_AUTO_RUNTIME_INSTALLED marker=%s enabled=%s auto=%s "
        "default_leverage=%s hard_max=3x long_only=%s native_public_callshape=true "
        "addorder_payload_injection=true spot_fallback=false",
        _MARKER,
        os.environ.get("NIJA_KRAKEN_MARGIN_ENABLED"),
        os.environ.get("NIJA_KRAKEN_AUTO_MARGIN_ENABLED"),
        os.environ.get("NIJA_KRAKEN_MARGIN_DEFAULT_LEVERAGE"),
        os.environ.get("NIJA_KRAKEN_AUTO_MARGIN_LONG_ONLY"),
    )


__all__ = [
    "install_import_hook",
    "_patch_capability_matrix",
    "_patch_router",
    "_patch_kraken_adapter",
    "_patch_kraken_class",
    "_margin_order_scope",
]
