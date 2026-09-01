"""Protective close capability semantics v335.

The canonical v334 exit path proved a real profitable Kraken ETH long was ready
for sale, but ExchangeCapabilityMatrix treated every SPOT ``sell`` as a request
to *open a short*.  Kraken spot correctly reports ``supports_short=False``, so a
verified sell-to-close was rejected as ``short_not_supported:kraken:spot``.

v335 distinguishes those two economic intents without enabling spot shorting.
Only the synchronous canonical submitter call is trusted, and only when all of
these are simultaneously true:

* intent_type is ``exit`` or ``reduce``;
* position_effect is ``close`` or ``reduce``;
* metadata says ``protective_exit=True`` and ``closing_position=True``;
* exit_origin is a known canonical protective-exit origin.

For that narrow scope only, ExchangeCapabilityMatrix receives a transient
``supports_short=True`` runtime override.  This does *not* label the exchange as
short-capable and it does not persist outside the ContextVar scope.  It merely
prevents a SELL that reduces a proven long from being classified as a new short.
All other capability checks (margin, leverage, long support), and every
writer/nonce/risk/kill-switch/minimum-order/order-ack/fill gate remain unchanged.

The trusted-close scope also reasserts v337's final execution-pipeline authority
bindings immediately before dispatch.  Several startup authority patches are
installed later and may legitimately replace module-level assertion functions;
without this late reassertion a verified close can regress to the ordinary
``lifecycle_phase:BOOT`` assertion even though v337 was READY at startup.  The
reassertion changes no lifecycle state and grants nothing by itself: v337 still
re-proves distributed writer authority, startup write authority, nonce, broker
health, kill-switch, SEAK, circuit and stability before a close may pass.

Ordinary Kraken/Coinbase/OKX spot sells, enter_short signals, or callers that
only spoof one exit field remain subject to the normal short-capability and
execution-authority checks.
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

LOGGER = logging.getLogger("nija.runtime_exit_capability_semantics_v335")
MARKER = "20260831-runtime-exit-capability-semantics-v335"
RELEASE_ID = "20260831-runtime-convergence-v335"
_READY_FLAG = "NIJA_RUNTIME_EXIT_CAPABILITY_SEMANTICS_V335_READY"
_SUBMIT_PATCH_ATTR = "_nija_exit_capability_submit_scope_v335"
_MATRIX_PATCH_ATTR = "_nija_exit_capability_matrix_v335"
_INSTALL_FLAG = "_NIJA_RUNTIME_EXIT_CAPABILITY_SEMANTICS_V335"
_LOCK = threading.RLock()
_TRUSTED_CLOSE = contextvars.ContextVar("nija_v335_trusted_protective_close", default=False)

_ALLOWED_ORIGINS = {
    "universal_v67",
    "kraken_account_exit",
}


def _norm(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _trusted_exit_kwargs(kwargs: Mapping[str, Any]) -> bool:
    intent = _norm(kwargs.get("intent_type"))
    effect = _norm(kwargs.get("position_effect"))
    metadata = kwargs.get("metadata_override")
    if not isinstance(metadata, Mapping):
        return False
    origin = _norm(metadata.get("exit_origin"))
    return bool(
        intent in {"exit", "reduce"}
        and effect in {"close", "reduce"}
        and metadata.get("protective_exit") is True
        and metadata.get("closing_position") is True
        and origin in _ALLOWED_ORIGINS
    )


def _reassert_protective_exit_authority() -> bool:
    """Late-bind v337 after any startup wrapper churn.

    This runs only inside ``_TRUSTED_CLOSE``.  It does not call an order, mutate
    lifecycle state, or suppress a failed proof; it only restores v337's wrappers
    around the *current* final pipeline bindings.  If reassertion is unavailable,
    the ordinary pipeline remains fail-closed.
    """
    if not bool(_TRUSTED_CLOSE.get()):
        return False
    try:
        v337 = importlib.import_module("bot.runtime_protective_exit_authority_bridge_v337_patch")
        patcher = getattr(v337, "_patch_pipeline", None)
        if not callable(patcher):
            LOGGER.warning(
                "EXIT_CAPABILITY_V335_AUTHORITY_REASSERT_DEFERRED marker=%s reason=v337_patcher_unavailable "
                "ordinary_authority_unchanged=true safety_gates_bypassed=false",
                MARKER,
            )
            return False
        ready = bool(patcher())
        LOGGER.critical(
            "EXIT_CAPABILITY_V335_AUTHORITY_REASSERT marker=%s ready=%s trusted_close=true "
            "late_binding=true global_lifecycle_mutated=false ordinary_entries_unchanged=true "
            "writer_nonce_health_killswitch_seak_circuit_stability_reproof_preserved=true "
            "ecel_risk_minimum_order_ack_fill_gates_unchanged=true safety_gates_bypassed=false",
            MARKER,
            str(ready).lower(),
        )
        return ready
    except Exception as exc:
        LOGGER.warning(
            "EXIT_CAPABILITY_V335_AUTHORITY_REASSERT_DEFERRED marker=%s reason=%s:%s "
            "ordinary_authority_unchanged=true safety_gates_bypassed=false",
            MARKER,
            type(exc).__name__,
            exc,
        )
        return False


def _patch_submitter() -> bool:
    module = importlib.import_module("bot.pipeline_order_submitter")
    current = getattr(module, "submit_market_order_via_pipeline", None)
    if not callable(current):
        return False
    if bool(getattr(current, _SUBMIT_PATCH_ATTR, False)):
        return True

    @wraps(current)
    def submit_with_close_scope(*args: Any, **kwargs: Any):
        trusted = _trusted_exit_kwargs(kwargs)
        if not trusted:
            return current(*args, **kwargs)
        token = _TRUSTED_CLOSE.set(True)
        try:
            LOGGER.critical(
                "EXIT_CAPABILITY_V335_TRUSTED_CLOSE_SCOPE marker=%s intent=%s effect=%s origin=%s "
                "short_entry_permission_unchanged=true context_local=true safety_gates_bypassed=false",
                MARKER,
                _norm(kwargs.get("intent_type")),
                _norm(kwargs.get("position_effect")),
                _norm((kwargs.get("metadata_override") or {}).get("exit_origin")),
            )
            _reassert_protective_exit_authority()
            return current(*args, **kwargs)
        finally:
            _TRUSTED_CLOSE.reset(token)

    setattr(submit_with_close_scope, _SUBMIT_PATCH_ATTR, True)
    setattr(submit_with_close_scope, "__wrapped__", current)
    module.submit_market_order_via_pipeline = submit_with_close_scope
    return True


def _patch_capability_matrix() -> bool:
    module = importlib.import_module("bot.exchange_capabilities")
    cls = getattr(module, "ExchangeCapabilityMatrix", None)
    if not isinstance(cls, type):
        return False
    current = getattr(cls, "enforce_order_capabilities", None)
    if not callable(current):
        return False
    if bool(getattr(current, _MATRIX_PATCH_ATTR, False)):
        return True

    @wraps(current)
    def enforce_close_semantics(self: Any, *args: Any, **kwargs: Any):
        side = _norm(kwargs.get("side"))
        if not (_TRUSTED_CLOSE.get() and side in {"sell", "short"}):
            return current(self, *args, **kwargs)

        overrides = dict(kwargs.get("runtime_overrides") or {})
        # Only neutralize the mistaken *short-entry* classification.  The
        # original function still performs every other capability check.
        overrides["supports_short"] = True
        patched_kwargs = dict(kwargs)
        patched_kwargs["runtime_overrides"] = overrides
        allowed, reason = current(self, *args, **patched_kwargs)
        LOGGER.critical(
            "EXIT_CAPABILITY_V335_CLOSE_CLASSIFIED marker=%s broker=%s symbol=%s side=%s "
            "allowed=%s reason=%s close_not_short_entry=true persistent_short_support_unchanged=true "
            "margin_leverage_checks_preserved=true safety_gates_bypassed=false",
            MARKER,
            kwargs.get("broker"),
            kwargs.get("symbol"),
            side,
            str(bool(allowed)).lower(),
            reason,
        )
        return allowed, reason

    setattr(enforce_close_semantics, _MATRIX_PATCH_ATTR, True)
    setattr(enforce_close_semantics, "__wrapped__", current)
    cls.enforce_order_capabilities = enforce_close_semantics
    return True


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_exit_capability_semantics_v335"] = _READY_FLAG
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
            matrix_ready = _patch_capability_matrix()
            submitter_ready = _patch_submitter()
            manifest_ready = _register_manifest()
            ready = bool(matrix_ready and submitter_ready and manifest_ready)
        except Exception as exc:
            ready = False
            LOGGER.exception(
                "RUNTIME_EXIT_CAPABILITY_SEMANTICS_V335_INSTALL_FAILED marker=%s error=%s:%s "
                "trading_fail_closed=true spot_shorting_not_enabled=true safety_gates_bypassed=false",
                MARKER, type(exc).__name__, exc,
            )

        os.environ[_READY_FLAG] = "1" if ready else "0"
        setattr(builtins, _INSTALL_FLAG, ready)
        log = LOGGER.critical if ready else LOGGER.error
        log(
            "RUNTIME_EXIT_CAPABILITY_SEMANTICS_V335_%s marker=%s ready=%s "
            "trusted_protective_close_only=true sell_to_close_not_short_entry=true "
            "ordinary_spot_short_gate_preserved=true context_local=true authority_late_reassert=true "
            "writer_nonce_risk_killswitch_minimum_order_ack_fill_gates_unchanged=true "
            "forced_exit=false forced_short=false safety_gates_bypassed=false",
            "READY" if ready else "NOT_READY",
            MARKER,
            str(ready).lower(),
        )
        return ready


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER", "RELEASE_ID", "install", "install_import_hook",
    "_trusted_exit_kwargs", "_TRUSTED_CLOSE", "_reassert_protective_exit_authority",
]
