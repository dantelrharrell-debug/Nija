"""Protective-exit base quantity terminal integrity v341.

Production on 2026-09-01 proved the canonical protective-exit pipeline correctly
compiled a verified Kraken ETH holding (~0.09565 ETH) to ~$234.97 notional, but
the generic direct-broker terminal passed that USD notional through a call path
that Kraken interpreted as base volume.  The resulting 234.97 ETH sell was
correctly rejected as insufficient funds.

v341 is deliberately narrow.  Only a canonical, verified, risk-reducing Kraken
SELL-to-close may use this terminal bridge.  It derives the terminal base volume
from both the independently verified position quantity and the already-validated
pipeline notional/price, uses the smaller positive quantity, and requires their
notional relationship to be consistent.  It then submits with size_type='base'.

All ordinary orders keep the existing router path.  ECEL/minimum-order, writer,
nonce, broker-health, kill-switch, capability, stability, ACK and confirmed-fill
truth remain authoritative.  ACKs are never promoted to fills; v328's strict
exchange-order-id and fill-specific price/notional normalization is reused.
"""
from __future__ import annotations

import builtins
import importlib
import inspect
import logging
import math
import os
import threading
from functools import wraps
from typing import Any, Mapping

LOGGER = logging.getLogger("nija.runtime_protective_exit_base_quantity_v341")
MARKER = "20260901-runtime-protective-exit-base-quantity-v341"
RELEASE_ID = "20260901-runtime-convergence-v341"
_READY_FLAG = "NIJA_RUNTIME_PROTECTIVE_EXIT_BASE_QUANTITY_V341_READY"
_PATCH_ATTR = "_nija_protective_exit_base_quantity_v341"
_INSTALL_FLAG = "_NIJA_RUNTIME_PROTECTIVE_EXIT_BASE_QUANTITY_V341"
_LOCK = threading.RLock()


def _f(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value if value is not None else default)
    except (TypeError, ValueError, OverflowError):
        return default
    return out if math.isfinite(out) else default


def _broker_label(broker: Any, metadata: Mapping[str, Any]) -> str:
    broker_type = getattr(broker, "broker_type", None)
    return str(
        metadata.get("broker_name")
        or getattr(broker_type, "value", broker_type)
        or getattr(broker, "NAME", "")
        or type(broker).__name__
    ).strip().lower()


def _trusted_kraken_long_close(
    broker: Any,
    *,
    side: str,
    metadata: Mapping[str, Any],
) -> bool:
    origin = str(metadata.get("exit_origin") or "").strip().lower()
    return bool(
        _broker_label(broker, metadata) == "kraken"
        and str(side or "").strip().lower() == "sell"
        and metadata.get("closing_position") is True
        and metadata.get("protective_exit") is True
        and origin in {"universal_v67", "kraken_account_exit"}
        and _f(metadata.get("verified_position_quantity"), 0.0) > 0.0
    )


def _terminal_base_quantity(size_usd: float, metadata: Mapping[str, Any]) -> tuple[float, float, float]:
    verified = _f(metadata.get("verified_position_quantity"), 0.0)
    price = _f(
        metadata.get("price_hint_usd")
        or metadata.get("reference_price_usd")
        or metadata.get("pretrade_price"),
        0.0,
    )
    notional = _f(size_usd, 0.0)
    if verified <= 0.0:
        raise RuntimeError("V341 verified_position_quantity_missing")
    if price <= 0.0:
        raise RuntimeError("V341 protective_exit_price_missing")
    if notional <= 0.0:
        raise RuntimeError("V341 protective_exit_notional_missing")

    compiled = notional / price
    if compiled <= 0.0:
        raise RuntimeError("V341 compiled_base_quantity_invalid")

    # The pipeline may normalize quote precision, so compiled quantity can be a
    # few base units smaller than the snapshot.  It must never materially exceed
    # the verified position or imply an unrelated notional.
    expected = verified * price
    tolerance = max(0.05, expected * 0.02)
    if abs(expected - notional) > tolerance:
        raise RuntimeError(
            f"V341 base_notional_mismatch verified={verified:.12f} price={price:.8f} "
            f"expected={expected:.8f} pipeline_notional={notional:.8f} tolerance={tolerance:.8f}"
        )

    terminal = min(verified, compiled)
    if terminal <= 0.0 or terminal > verified * 1.0000001:
        raise RuntimeError("V341 protective_exit_oversell_guard")
    return terminal, verified, price


def _submit_base(broker: Any, symbol: str, side: str, quantity: float, metadata: Mapping[str, Any]):
    submit = getattr(broker, "place_market_order", None)
    if not callable(submit):
        raise RuntimeError("V341 Kraken broker lacks place_market_order")

    kwargs: dict[str, Any] = {"size_type": "base"}
    trace_id = str(metadata.get("decision_trace_id") or metadata.get("trace_id") or "").strip()
    if trace_id:
        try:
            sig = inspect.signature(submit)
            if "decision_trace_id" in sig.parameters:
                kwargs["decision_trace_id"] = trace_id
        except (TypeError, ValueError):
            pass
    try:
        return submit(symbol, side, float(quantity), **kwargs)
    except TypeError:
        return submit(symbol=symbol, side=side, quantity=float(quantity), **kwargs)


def _patch_router() -> bool:
    router = importlib.import_module("bot.multi_broker_execution_router")
    cls = getattr(router, "MultiBrokerExecutionRouter", None)
    if cls is None:
        return False
    current = getattr(cls, "_dispatch_direct_broker_market_order", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    v328 = importlib.import_module("bot.runtime_confirmed_fill_profitability_v328_patch")
    normalize = getattr(v328, "_normalize_dict_fill", None)
    capture_slippage = getattr(v328, "_capture_slippage", None)
    reference_price = getattr(v328, "_reference_price", None)
    if not callable(normalize) or not callable(capture_slippage) or not callable(reference_price):
        return False

    @wraps(current)
    def protective_exit_base_terminal_v341(
        broker: Any,
        *,
        symbol: str,
        side: str,
        size_usd: float,
        metadata: Mapping[str, Any],
    ) -> tuple[float, float]:
        meta = dict(metadata or {})
        if not _trusted_kraken_long_close(broker, side=side, metadata=meta):
            return current(
                broker,
                symbol=symbol,
                side=side,
                size_usd=size_usd,
                metadata=meta,
            )

        quantity, verified, price = _terminal_base_quantity(size_usd, meta)
        LOGGER.critical(
            "PROTECTIVE_EXIT_BASE_QUANTITY_V341_SUBMIT marker=%s broker=kraken symbol=%s side=sell "
            "verified_base=%.12f terminal_base=%.12f pipeline_notional=%.8f reference_price=%.8f "
            "size_type=base oversell=false quote_as_base=false safety_gates_bypassed=false",
            MARKER, symbol, verified, quantity, float(size_usd), price,
        )
        result = _submit_base(broker, symbol, side, quantity, meta)
        if not isinstance(result, Mapping):
            raise RuntimeError(f"V341 unsupported Kraken order response: {result!r}")

        fill_price, filled_usd = normalize(result, symbol=symbol, side=side)
        capture_slippage(side, fill_price, reference_price(meta))
        LOGGER.critical(
            "PROTECTIVE_EXIT_BASE_QUANTITY_V341_CONFIRMED_FILL marker=%s broker=kraken symbol=%s "
            "terminal_base=%.12f fill_price=%.10f filled_usd=%.8f ack_not_fill=true "
            "confirmed_fill_required=true safety_gates_bypassed=false",
            MARKER, symbol, quantity, fill_price, filled_usd,
        )
        return fill_price, filled_usd

    setattr(protective_exit_base_terminal_v341, _PATCH_ATTR, True)
    setattr(protective_exit_base_terminal_v341, "__wrapped__", current)
    cls._dispatch_direct_broker_market_order = staticmethod(protective_exit_base_terminal_v341)
    return True


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_protective_exit_base_quantity_v341"] = _READY_FLAG
        return True
    except Exception:
        return False


def install_import_hook() -> bool:
    with _LOCK:
        if getattr(builtins, _INSTALL_FLAG, False) and os.environ.get(_READY_FLAG) == "1":
            return True
        try:
            if os.environ.get("NIJA_RUNTIME_PROTECTIVE_EXIT_STATE_MACHINE_BRIDGE_V340_READY") != "1":
                raise RuntimeError("v340_not_ready")
            ready = bool(_patch_router() and _register_manifest())
        except Exception as exc:
            ready = False
            LOGGER.exception(
                "RUNTIME_PROTECTIVE_EXIT_BASE_QUANTITY_V341_INSTALL_FAILED marker=%s error=%s:%s "
                "trading_fail_closed=true forced_exit=false safety_gates_bypassed=false",
                MARKER, type(exc).__name__, exc,
            )
        os.environ[_READY_FLAG] = "1" if ready else "0"
        setattr(builtins, _INSTALL_FLAG, ready)
        log = LOGGER.critical if ready else LOGGER.error
        log(
            "RUNTIME_PROTECTIVE_EXIT_BASE_QUANTITY_V341_%s marker=%s ready=%s "
            "kraken_verified_long_close_only=true verified_base_required=true notional_consistency_required=true "
            "terminal_base_uses_min_verified_and_compiled=true oversell_guard=true quote_as_base_blocked=true "
            "ordinary_orders_unchanged=true v328_confirmed_fill_truth_preserved=true "
            "writer_nonce_health_killswitch_ecel_minimum_order_ack_fill_gates_unchanged=true "
            "forced_exit=false safety_gates_bypassed=false",
            "READY" if ready else "NOT_READY", MARKER, str(ready).lower(),
        )
        return ready


def install() -> bool:
    return install_import_hook()


__all__ = ["MARKER", "RELEASE_ID", "install", "install_import_hook", "_terminal_base_quantity"]
