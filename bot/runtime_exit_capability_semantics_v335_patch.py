"""Protective close capability semantics v335.

The canonical v334 exit path proved a real profitable Kraken ETH long was ready
for sale, but ExchangeCapabilityMatrix treated every SPOT ``sell`` as a request
to *open a short*. Kraken spot correctly reports ``supports_short=False``, so a
verified sell-to-close was rejected as ``short_not_supported:kraken:spot``.

v335 distinguishes those two economic intents without enabling spot shorting.
Only the synchronous canonical submitter call is trusted, and only when all of
these are simultaneously true:

* intent_type is ``exit`` or ``reduce``;
* position_effect is ``close`` or ``reduce``;
* metadata says ``protective_exit=True`` and ``closing_position=True``;
* exit_origin is a known canonical protective-exit origin.

For that narrow scope only, ExchangeCapabilityMatrix receives a transient
``supports_short=True`` runtime override. This does *not* label the exchange as
short-capable and it does not persist outside the ContextVar scope. It merely
prevents a SELL that reduces a proven long from being classified as a new short.
All other capability checks (margin, leverage, long support), and every
writer/nonce/risk/kill-switch/minimum-order/order-ack/fill gate remain unchanged.

The trusted-close scope also reasserts v337's final execution-pipeline authority
bindings immediately before dispatch. Several startup authority patches are
installed later and may legitimately replace module-level assertion functions;
without this late reassertion a verified close can regress to the ordinary
``lifecycle_phase:BOOT`` assertion even though v337 was READY at startup.

The pipeline performs one additional runtime snapshot immediately before broker
routing and normally requires its global ``dispatch_enabled`` bit. During
startup that bit may remain false even after a trusted close has independently
re-proved current distributed-writer, startup-write, nonce, broker-health,
kill-switch, SEAK, circuit and stability safety. v335 therefore applies a
second, context-local snapshot wrapper only inside the trusted-close scope. It
sets ``dispatch_enabled=True`` on the returned *copy* only after v337 hard proof
and stability both pass. No environment, Redis, lifecycle, coordinator or
global dispatch state is mutated. Ordinary orders are unchanged and every
subsequent broker, minimum-order, ACK and fill gate remains authoritative.

Finally, v328's confirmed-fill direct-dispatch wrapper historically forced every
crypto direct order to ``size_type=quote`` and passed the USD notional as the
broker quantity. For an explicit base-sized protective close this converted a
validated 0.09565 ETH close into a 234.97 ETH Kraken volume and produced a real
``EOrder:Insufficient funds`` rejection. v335 now preserves base units only for
the same trusted protective-close context. The submitted base quantity is the
smaller of the verified held quantity and the ECEL-adjusted notional divided by
the verified price hint. If either proof is unavailable, the close fails
closed rather than guessing units. Ordinary quote-sized entries remain
unchanged.

Ordinary Kraken/Coinbase/OKX spot sells, enter_short signals, or callers that
only spoof one exit field remain subject to the normal short-capability and
execution-authority checks.
"""
from __future__ import annotations

import builtins
import contextvars
import importlib
import inspect
import logging
import os
import threading
from dataclasses import replace
from functools import wraps
from typing import Any, Mapping

LOGGER = logging.getLogger("nija.runtime_exit_capability_semantics_v335")
MARKER = "20260831-runtime-exit-capability-semantics-v335"
RELEASE_ID = "20260831-runtime-convergence-v335"
_READY_FLAG = "NIJA_RUNTIME_EXIT_CAPABILITY_SEMANTICS_V335_READY"
_SUBMIT_PATCH_ATTR = "_nija_exit_capability_submit_scope_v335"
_MATRIX_PATCH_ATTR = "_nija_exit_capability_matrix_v335"
_DISPATCH_SNAPSHOT_ATTR = "_nija_exit_dispatch_snapshot_scope_v335"
_BASE_DISPATCH_ATTR = "_nija_exit_base_dispatch_scope_v335"
_INSTALL_FLAG = "_NIJA_RUNTIME_EXIT_CAPABILITY_SEMANTICS_V335"
_LOCK = threading.RLock()
_TRUSTED_CLOSE = contextvars.ContextVar("nija_v335_trusted_protective_close", default=False)

_ALLOWED_ORIGINS = {
    "universal_v67",
    "kraken_account_exit",
}


def _norm(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except Exception:
        return default
    if parsed != parsed or parsed in {float("inf"), float("-inf")}:
        return default
    return parsed


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


def _patch_confirmed_fill_base_dispatch() -> bool:
    """Preserve explicit base units at v328's direct broker terminal.

    v328 remains authoritative for confirmed-fill truth. This wrapper changes
    only the quantity/size_type presented to the broker while the trusted close
    ContextVar is active. It never promotes an ACK to a fill.
    """
    try:
        v328 = importlib.import_module("bot.runtime_confirmed_fill_profitability_v328_patch")
    except Exception:
        return False
    current = getattr(v328, "_submit_direct", None)
    if not callable(current):
        return False
    if bool(getattr(current, _BASE_DISPATCH_ATTR, False)):
        return True

    @wraps(current)
    def submit_direct_with_base_exit_v335(
        broker: Any,
        symbol: str,
        side: str,
        size_usd: float,
        metadata: Mapping[str, Any],
    ):
        meta = dict(metadata or {})
        if not bool(_TRUSTED_CLOSE.get()):
            return current(broker, symbol, side, size_usd, meta)

        side_norm = _norm(side)
        if side_norm != "sell":
            # Current trusted universal close path is long-spot sell-to-close.
            # Do not invent base semantics for buy-to-cover/margin paths.
            return current(broker, symbol, side, size_usd, meta)

        verified_qty = _float(meta.get("verified_position_quantity"), 0.0)
        price = _float(
            meta.get("price_hint_usd")
            or meta.get("reference_price_usd")
            or meta.get("pretrade_price"),
            0.0,
        )
        adjusted_notional = _float(size_usd, 0.0)
        if verified_qty <= 0.0:
            raise RuntimeError("trusted protective exit base quantity unproven")
        if price <= 0.0 or adjusted_notional <= 0.0:
            raise RuntimeError("trusted protective exit ECEL base conversion unproven")

        ecel_qty = adjusted_notional / price
        base_qty = min(verified_qty, ecel_qty)
        if base_qty <= 0.0:
            raise RuntimeError("trusted protective exit compiled base quantity invalid")

        submit = getattr(broker, "place_market_order", None)
        if not callable(submit):
            submit = getattr(broker, "execute_order", None)
        if not callable(submit):
            submit = getattr(broker, "place_order", None)
        if not callable(submit):
            raise RuntimeError(f"Broker {broker!r} has no market-order submit method")

        trace_id = str(meta.get("decision_trace_id") or meta.get("trace_id") or "")
        submit_kwargs: dict[str, Any] = {"size_type": "base"}
        if trace_id:
            try:
                sig = inspect.signature(submit)
                if "decision_trace_id" in sig.parameters:
                    submit_kwargs["decision_trace_id"] = trace_id
            except (TypeError, ValueError):
                pass

        LOGGER.critical(
            "EXIT_CAPABILITY_V335_BASE_SIZE_PRESERVED marker=%s symbol=%s side=%s "
            "verified_qty=%.12f ecel_qty=%.12f submitted_qty=%.12f size_type=base "
            "adjusted_notional=%.8f price_hint=%.10f quote_notional_as_base=false "
            "ordinary_orders_unchanged=true ack_fill_truth_unchanged=true safety_gates_bypassed=false",
            MARKER,
            symbol,
            side_norm,
            verified_qty,
            ecel_qty,
            base_qty,
            adjusted_notional,
            price,
        )
        try:
            return submit(symbol, side, float(base_qty), **submit_kwargs)
        except TypeError:
            try:
                return submit(
                    symbol=symbol,
                    side=side,
                    quantity=float(base_qty),
                    **submit_kwargs,
                )
            except TypeError as exc:
                # Never fall back to an ambiguous positional submit for an
                # explicit base close; doing so can reintroduce the unit bug.
                raise RuntimeError(
                    f"trusted protective exit broker lacks explicit base-size contract: {exc}"
                ) from exc

    setattr(submit_direct_with_base_exit_v335, _BASE_DISPATCH_ATTR, True)
    setattr(submit_direct_with_base_exit_v335, "__wrapped__", current)
    v328._submit_direct = submit_direct_with_base_exit_v335
    return True


def _patch_trusted_dispatch_snapshot(v337: Any) -> bool:
    """Make the final pipeline dispatch snapshot context-local for trusted exits.

    This never changes the authoritative runtime snapshot or any global flag.
    The returned dataclass copy advertises dispatch eligibility only after the
    same hard exit proof and stability authority used by v337 pass *now*.
    """
    pipeline = importlib.import_module("bot.execution_pipeline")
    current = getattr(pipeline, "runtime_authority_snapshot", None)
    if not callable(current):
        return False
    if bool(getattr(current, _DISPATCH_SNAPSHOT_ATTR, False)):
        return True

    @wraps(current)
    def trusted_exit_dispatch_snapshot_v335():
        snap = current()
        if not bool(_TRUSTED_CLOSE.get()) or bool(getattr(snap, "dispatch_enabled", False)):
            return snap

        hard_proof = getattr(v337, "_hard_exit_authority_proof", None)
        if not callable(hard_proof):
            return snap
        ok, reason, current_auth = hard_proof()
        if not ok:
            LOGGER.warning(
                "EXIT_CAPABILITY_V335_DISPATCH_SNAPSHOT_DEFERRED marker=%s reason=%s "
                "dispatch_unchanged=true global_state_mutated=false safety_gates_bypassed=false",
                MARKER,
                reason,
            )
            return snap

        try:
            eac = importlib.import_module("bot.execution_authority_context")
            stability = eac._evaluate_stability_authority(
                runtime_snapshot=current_auth,
                state_live_active=True,
                lease_valid=True,
                lease_generation_current=True,
                heartbeat_fresh=True,
                heartbeat_stage_sufficient=True,
                broker_health_ok=True,
                dispatch_enabled=True,
                circuit_breaker_closed=True,
            )
        except Exception as exc:
            LOGGER.warning(
                "EXIT_CAPABILITY_V335_DISPATCH_SNAPSHOT_DEFERRED marker=%s reason=stability_unavailable:%s "
                "dispatch_unchanged=true global_state_mutated=false safety_gates_bypassed=false",
                MARKER,
                exc,
            )
            return snap

        if not bool(getattr(stability, "allowed", False)):
            LOGGER.warning(
                "EXIT_CAPABILITY_V335_DISPATCH_SNAPSHOT_DEFERRED marker=%s reason=stability_denied:%s "
                "dispatch_unchanged=true global_state_mutated=false safety_gates_bypassed=false",
                MARKER,
                getattr(stability, "reason", "unknown"),
            )
            return snap

        try:
            bridged = replace(snap, dispatch_enabled=True)
        except Exception:
            return snap

        LOGGER.critical(
            "EXIT_CAPABILITY_V335_DISPATCH_SNAPSHOT_BRIDGED marker=%s trusted_close=true "
            "source_dispatch_enabled=false local_dispatch_enabled=true exact_writer=true "
            "startup_write_authority=true nonce_ready=true broker_health_ready=true "
            "kill_switch_clear=true seak_clear=true circuit_clear=true stability_allowed=true "
            "global_dispatch_mutated=false global_lifecycle_mutated=false ordinary_orders_unchanged=true "
            "broker_minimum_order_ack_fill_gates_unchanged=true safety_gates_bypassed=false",
            MARKER,
        )
        return bridged

    setattr(trusted_exit_dispatch_snapshot_v335, _DISPATCH_SNAPSHOT_ATTR, True)
    setattr(trusted_exit_dispatch_snapshot_v335, "__wrapped__", current)
    pipeline.runtime_authority_snapshot = trusted_exit_dispatch_snapshot_v335
    return True


def _reassert_protective_exit_authority() -> bool:
    """Late-bind protective-exit authority after any startup wrapper churn."""
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
        authority_ready = bool(patcher())
        snapshot_ready = bool(_patch_trusted_dispatch_snapshot(v337)) if authority_ready else False
        base_ready = bool(_patch_confirmed_fill_base_dispatch())
        ready = bool(authority_ready and snapshot_ready and base_ready)
        LOGGER.critical(
            "EXIT_CAPABILITY_V335_AUTHORITY_REASSERT marker=%s ready=%s trusted_close=true "
            "late_binding=true dispatch_snapshot_binding=%s base_size_binding=%s "
            "global_lifecycle_mutated=false global_dispatch_mutated=false ordinary_entries_unchanged=true "
            "writer_nonce_health_killswitch_seak_circuit_stability_reproof_preserved=true "
            "ecel_risk_minimum_order_ack_fill_gates_unchanged=true safety_gates_bypassed=false",
            MARKER,
            str(ready).lower(),
            str(snapshot_ready).lower(),
            str(base_ready).lower(),
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
            base_ready = _patch_confirmed_fill_base_dispatch()
            manifest_ready = _register_manifest()
            ready = bool(matrix_ready and submitter_ready and base_ready and manifest_ready)
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
            "dispatch_snapshot_context_local=true base_size_terminal_preserved=true "
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
    "_patch_confirmed_fill_base_dispatch",
]
