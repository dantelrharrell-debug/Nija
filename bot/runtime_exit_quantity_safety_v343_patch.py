"""Protective-exit quantity safety v343.

Production on 2026-09-02 showed two terminal exit failures while NIJA was
trying to reduce verified held positions:

* V341 rejected a close when ECEL/minimum-order normalization produced a quote
  notional larger than the independently verified held-position notional.
* legacy broker-submit compatibility code could catch an internal broker
  ``TypeError`` as though it were a call-signature mismatch, obscuring the real
  terminal failure and allowing a second ambiguous invocation attempt.

v343 is monotonic safety hardening.  For a verified protective SELL-to-close,
the terminal base quantity is always capped at the independently verified held
quantity.  A larger ECEL-adjusted quote notional may never enlarge the close.
If the resulting verified quantity is below an exchange minimum the broker may
still reject it normally; NIJA does not fabricate a larger position or bypass
minimum-order rules.

The patch also makes direct-submit invocation signature-aware so a TypeError
raised *inside* a broker implementation is preserved as the real failure rather
than being mistaken for an argument-shape error and retried ambiguously.

Writer, nonce, risk, capital, kill-switch, position-sync, ECEL, broker-health,
minimum-order, ACK and confirmed-fill gates remain authoritative.
"""
from __future__ import annotations

import importlib
import inspect
import logging
import math
import os
import threading
from functools import wraps
from typing import Any, Mapping

LOGGER = logging.getLogger("nija.runtime_exit_quantity_safety_v343")
MARKER = "20260902-runtime-exit-quantity-safety-v343"
RELEASE_ID = "20260902-runtime-convergence-v343"
_READY_FLAG = "NIJA_RUNTIME_EXIT_QUANTITY_SAFETY_V343_READY"
_LOCK = threading.RLock()
_SUBMIT_ATTR = "_nija_signature_safe_submit_v343"


def _f(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value if value is not None else default)
    except (TypeError, ValueError, OverflowError):
        return default
    return out if math.isfinite(out) else default


def _safe_terminal_base_quantity(size_usd: float, metadata: Mapping[str, Any]) -> tuple[float, float, float]:
    """Compile a protective close without ever increasing verified base size."""
    verified = _f(metadata.get("verified_position_quantity"), 0.0)
    price = _f(
        metadata.get("price_hint_usd")
        or metadata.get("reference_price_usd")
        or metadata.get("pretrade_price"),
        0.0,
    )
    notional = _f(size_usd, 0.0)
    if verified <= 0.0:
        raise RuntimeError("V343 verified_position_quantity_missing")
    if price <= 0.0:
        raise RuntimeError("V343 protective_exit_price_missing")
    if notional <= 0.0:
        raise RuntimeError("V343 protective_exit_notional_missing")

    compiled = notional / price
    if compiled <= 0.0:
        raise RuntimeError("V343 compiled_base_quantity_invalid")

    # ECEL/minimum-order normalization is allowed to change quote notional, but
    # it is never authority to manufacture additional base units for an exit.
    terminal = min(verified, compiled)
    if terminal <= 0.0 or terminal > verified * 1.0000001:
        raise RuntimeError("V343 protective_exit_oversell_guard")

    expected = verified * price
    tolerance = max(0.05, expected * 0.02)
    if abs(expected - notional) > tolerance:
        LOGGER.warning(
            "PROTECTIVE_EXIT_V343_NOTIONAL_CLAMP marker=%s verified_base=%.12f price=%.10f "
            "verified_notional=%.8f pipeline_notional=%.8f compiled_base=%.12f terminal_base=%.12f "
            "oversell=false minimum_order_bypass=false safety_gates_bypassed=false",
            MARKER, verified, price, expected, notional, compiled, terminal,
        )
    return terminal, verified, price


def _patch_v341_quantity() -> bool:
    v341 = importlib.import_module("bot.runtime_protective_exit_base_quantity_v341_patch")
    current = getattr(v341, "_terminal_base_quantity", None)
    if not callable(current):
        return False
    v341._terminal_base_quantity = _safe_terminal_base_quantity
    return getattr(v341, "_terminal_base_quantity", None) is _safe_terminal_base_quantity


def _invoke_submit_signature_safe(submit: Any, symbol: str, side: str, quantity: float, kwargs: Mapping[str, Any]):
    """Choose one proven call shape before invocation; never retry an internal TypeError."""
    try:
        sig = inspect.signature(submit)
    except (TypeError, ValueError):
        # Signature cannot be proven.  Preserve the canonical positional shape
        # and let any exception escape unchanged; do not retry after TypeError.
        return submit(symbol, side, float(quantity), **dict(kwargs))

    params = sig.parameters
    if "quantity" in params:
        return submit(symbol=symbol, side=side, quantity=float(quantity), **dict(kwargs))
    if "size" in params:
        return submit(symbol=symbol, side=side, size=float(quantity), **dict(kwargs))

    # Bound methods commonly expose (symbol, side, amount, ...).  The first
    # three positional parameters are sufficient proof for canonical dispatch.
    positional = [
        p for p in params.values()
        if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    if len(positional) >= 3:
        return submit(symbol, side, float(quantity), **dict(kwargs))
    raise RuntimeError("V343 broker submit signature lacks explicit quantity/size contract")


def _patch_v341_submit() -> bool:
    v341 = importlib.import_module("bot.runtime_protective_exit_base_quantity_v341_patch")
    current = getattr(v341, "_submit_base", None)
    if not callable(current):
        return False
    if bool(getattr(current, _SUBMIT_ATTR, False)):
        return True

    @wraps(current)
    def submit_base_v343(broker: Any, symbol: str, side: str, quantity: float, metadata: Mapping[str, Any]):
        submit = getattr(broker, "place_market_order", None)
        if not callable(submit):
            raise RuntimeError("V343 broker lacks place_market_order")
        kwargs: dict[str, Any] = {"size_type": "base"}
        trace_id = str(metadata.get("decision_trace_id") or metadata.get("trace_id") or "").strip()
        if trace_id:
            try:
                sig = inspect.signature(submit)
                if "decision_trace_id" in sig.parameters:
                    kwargs["decision_trace_id"] = trace_id
            except (TypeError, ValueError):
                pass
        return _invoke_submit_signature_safe(submit, symbol, side, float(quantity), kwargs)

    setattr(submit_base_v343, _SUBMIT_ATTR, True)
    setattr(submit_base_v343, "__wrapped__", current)
    v341._submit_base = submit_base_v343
    return True


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_exit_quantity_safety_v343"] = _READY_FLAG
        return True
    except Exception:
        return False


def install_import_hook() -> bool:
    with _LOCK:
        quantity_ready = submit_ready = manifest_ready = False
        try:
            quantity_ready = bool(_patch_v341_quantity())
            submit_ready = bool(_patch_v341_submit())
            manifest_ready = bool(_register_manifest())
        except Exception as exc:
            LOGGER.exception(
                "RUNTIME_EXIT_QUANTITY_SAFETY_V343_INSTALL_ERROR marker=%s error=%s:%s fail_closed=true",
                MARKER, type(exc).__name__, exc,
            )
        ready = bool(quantity_ready and submit_ready and manifest_ready)
        os.environ[_READY_FLAG] = "1" if ready else "0"
        log = LOGGER.critical if ready else LOGGER.error
        log(
            "RUNTIME_EXIT_QUANTITY_SAFETY_V343_%s marker=%s ready=%s "
            "verified_position_caps_exit=true ecel_notional_cannot_enlarge_base=true "
            "internal_typeerror_preserved=true ambiguous_typeerror_retry=false "
            "minimum_order_bypass=false ack_fill_truth_unchanged=true "
            "writer_nonce_risk_capital_killswitch_position_sync_ecel_broker_health_gates_unchanged=true "
            "safety_gates_bypassed=false",
            "READY" if ready else "NOT_READY", MARKER, str(ready).lower(),
        )
        return ready


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER", "RELEASE_ID", "install", "install_import_hook",
    "_safe_terminal_base_quantity", "_invoke_submit_signature_safe",
]
