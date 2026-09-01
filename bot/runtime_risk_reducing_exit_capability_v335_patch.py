"""Risk-reducing exit capability classification v335.

Production on 2026-09-01 proved the canonical protective-exit path could carry a
verified Kraken spot long all the way to the capability matrix with the correct
base quantity and all-in notional, but ``ExchangeCapabilityMatrix`` classified
any ``side=sell`` as a new short.  A sell-to-close of an owned spot long is not a
short entry and must not require ``supports_short``.

v335 is deliberately request-local and does NOT change Kraken/Coinbase/OKX spot
short capability.  It uses a ContextVar that is armed only while
``ExecutionPipeline.execute`` handles a strict protective-exit request with all
of these properties:

* intent_type is ``exit`` or ``reduce``;
* position_effect is ``close`` or ``reduce``;
* metadata ``closing_position`` is true; and
* metadata ``protective_exit`` is true.

Inside that exact context, ``enforce_order_capabilities`` receives a copied
runtime-overrides mapping with ``supports_short=True`` only for ``side=sell``.
That suppresses only the semantic misclassification of SELL-to-close as a SHORT
entry.  The original capability function still evaluates market mode, leverage,
margin support, max leverage and account requirements.  Outside the context the
original function is called byte-for-byte with the original arguments.

This patch grants no execution authority and proves no position.  v67/v323/v330
remain responsible for verified quantity/cost basis; v334 creates the explicit
protective-exit request; the existing writer-authorized exit gate, broker-health,
nonce, kill-switch, ECEL, minimum-order, order-ack and fill-confirmation gates all
remain authoritative.  A normal spot short entry remains blocked.
"""
from __future__ import annotations

import builtins
import contextvars
import importlib
import logging
import os
import threading
from functools import wraps
from typing import Any, Mapping

LOGGER = logging.getLogger("nija.runtime_risk_reducing_exit_capability_v335")
MARKER = "20260901-risk-reducing-exit-capability-v335"
RELEASE_ID = "20260901-runtime-convergence-v335"
_READY_FLAG = "NIJA_RUNTIME_RISK_REDUCING_EXIT_CAPABILITY_V335_READY"
_PIPELINE_PATCH_ATTR = "_nija_risk_reducing_exit_context_v335"
_CAP_PATCH_ATTR = "_nija_risk_reducing_exit_capability_v335"
_INSTALL_FLAG = "_NIJA_RUNTIME_RISK_REDUCING_EXIT_CAPABILITY_V335"
_LOCK = threading.RLock()
_EXIT_CONTEXT: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "nija_risk_reducing_exit_capability_v335", default=False
)


def _norm(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _metadata(request: Any) -> Mapping[str, Any]:
    value = getattr(request, "metadata", None)
    return value if isinstance(value, Mapping) else {}


def _strict_protective_exit(request: Any) -> bool:
    intent = _norm(getattr(request, "intent_type", ""))
    effect = _norm(getattr(request, "position_effect", ""))
    meta = _metadata(request)
    return bool(
        intent in {"exit", "reduce"}
        and effect in {"close", "reduce"}
        and meta.get("closing_position") is True
        and meta.get("protective_exit") is True
    )


def _patch_pipeline_context() -> bool:
    module = importlib.import_module("bot.execution_pipeline")
    cls = getattr(module, "ExecutionPipeline", None)
    if not isinstance(cls, type):
        return False
    current = getattr(cls, "execute", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PIPELINE_PATCH_ATTR, False)):
        return True

    @wraps(current)
    def execute_v335(self: Any, request: Any, *args: Any, **kwargs: Any):
        strict_exit = _strict_protective_exit(request)
        token = None
        if strict_exit:
            token = _EXIT_CONTEXT.set(True)
            LOGGER.critical(
                "RISK_REDUCING_EXIT_CAPABILITY_V335_CONTEXT marker=%s account=%s symbol=%s side=%s "
                "intent=%s position_effect=%s closing_position=true protective_exit=true "
                "short_capability_global_unchanged=true execution_authority_granted=false "
                "position_proof_fabricated=false safety_gates_bypassed=false",
                MARKER,
                str(getattr(request, "account_id", "default") or "default"),
                str(getattr(request, "symbol", "") or ""),
                str(getattr(request, "side", "") or ""),
                _norm(getattr(request, "intent_type", "")),
                _norm(getattr(request, "position_effect", "")),
            )
        try:
            return current(self, request, *args, **kwargs)
        finally:
            if token is not None:
                _EXIT_CONTEXT.reset(token)

    setattr(execute_v335, _PIPELINE_PATCH_ATTR, True)
    setattr(execute_v335, "__wrapped__", current)
    cls.execute = execute_v335
    return True


def _patch_capability_matrix() -> bool:
    module = importlib.import_module("bot.exchange_capabilities")
    cls = getattr(module, "ExchangeCapabilityMatrix", None)
    if not isinstance(cls, type):
        return False
    current = getattr(cls, "enforce_order_capabilities", None)
    if not callable(current):
        return False
    if bool(getattr(current, _CAP_PATCH_ATTR, False)):
        return True

    @wraps(current)
    def enforce_exit_aware_capabilities(
        self: Any,
        *,
        broker: str,
        symbol: str,
        side: str,
        asset_class: Any = None,
        account_type: Any = None,
        leverage: Any = None,
        margin_mode: Any = None,
        runtime_overrides: Any = None,
    ):
        if not (_EXIT_CONTEXT.get() and _norm(side) == "sell"):
            return current(
                self,
                broker=broker,
                symbol=symbol,
                side=side,
                asset_class=asset_class,
                account_type=account_type,
                leverage=leverage,
                margin_mode=margin_mode,
                runtime_overrides=runtime_overrides,
            )

        overrides = dict(runtime_overrides or {})
        original_override = overrides.get("supports_short", None)
        overrides["supports_short"] = True
        allowed, reason = current(
            self,
            broker=broker,
            symbol=symbol,
            side=side,
            asset_class=asset_class,
            account_type=account_type,
            leverage=leverage,
            margin_mode=margin_mode,
            runtime_overrides=overrides,
        )
        LOGGER.critical(
            "RISK_REDUCING_EXIT_CAPABILITY_V335_CLASSIFIED marker=%s broker=%s symbol=%s side=%s "
            "sell_to_close=true short_entry=false allowed=%s reason=%s "
            "request_local_override=true prior_supports_short_override=%s "
            "global_capabilities_mutated=false leverage_margin_checks_preserved=true "
            "execution_authority_granted=false safety_gates_bypassed=false",
            MARKER,
            str(broker),
            str(symbol),
            str(side),
            str(bool(allowed)).lower(),
            str(reason),
            str(original_override),
        )
        return allowed, reason

    setattr(enforce_exit_aware_capabilities, _CAP_PATCH_ATTR, True)
    setattr(enforce_exit_aware_capabilities, "__wrapped__", current)
    cls.enforce_order_capabilities = enforce_exit_aware_capabilities

    # Patch the process singleton too if its class was replaced or imported
    # before this installer.  Method lookup on the class is normally sufficient.
    singleton = getattr(module, "EXCHANGE_CAPABILITIES", None)
    if singleton is not None and isinstance(singleton, cls):
        pass
    return True


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_risk_reducing_exit_capability_v335"] = _READY_FLAG
        return True
    except Exception:
        return False


def install_import_hook() -> bool:
    with _LOCK:
        if getattr(builtins, _INSTALL_FLAG, False) and os.environ.get(_READY_FLAG) == "1":
            return True
        try:
            if os.environ.get("NIJA_RUNTIME_CANONICAL_EXIT_SUBMISSION_V334_READY") != "1":
                raise RuntimeError("v334_not_ready")
            pipeline_ready = _patch_pipeline_context()
            capability_ready = _patch_capability_matrix()
            manifest_ready = _register_manifest()
            ready = bool(pipeline_ready and capability_ready and manifest_ready)
        except Exception as exc:
            ready = False
            LOGGER.exception(
                "RISK_REDUCING_EXIT_CAPABILITY_V335_INSTALL_FAILED marker=%s error=%s:%s "
                "trading_fail_closed=true forced_exit=false safety_gates_bypassed=false",
                MARKER, type(exc).__name__, exc,
            )
        os.environ[_READY_FLAG] = "1" if ready else "0"
        setattr(builtins, _INSTALL_FLAG, ready)
        log = LOGGER.critical if ready else LOGGER.error
        log(
            "RUNTIME_RISK_REDUCING_EXIT_CAPABILITY_V335_%s marker=%s ready=%s "
            "strict_exit_context_required=true sell_to_close_not_short=true global_short_capability_unchanged=true "
            "ordinary_spot_short_still_blocked=true request_local_override=true "
            "writer_position_cost_basis_broker_health_nonce_killswitch_risk_minimum_order_fill_gates_unchanged=true "
            "forced_loss_exit=false safety_gates_bypassed=false",
            "READY" if ready else "NOT_READY",
            MARKER,
            str(ready).lower(),
        )
        return ready


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER", "RELEASE_ID", "install", "install_import_hook",
    "_strict_protective_exit", "_EXIT_CONTEXT",
]
