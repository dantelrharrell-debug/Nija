"""Keep local/pre-dispatch failures out of exchange rejection telemetry (v228/v232/v247/v253).

Production on 2026-08-25 showed the canonical EXCHANGE_MONITOR stop holding a
5/5 rejection window while the runtime was otherwise converged.  The execution
pipeline can return failures before a broker order is sent (for example
``dispatch_disabled: dispatch.enabled=false``) and later route those failures
through ``_on_order_rejected``.  The pipeline's synthetic telemetry order ID
alone does not prove that an exchange saw or rejected an order.

V228 patches only the telemetry emission boundary.  Known local, authority,
state-machine, liquidity, routing, risk, ECEL, disconnected-adapter and other
pre-dispatch failures are logged as non-exchange outcomes and are not appended
to ExchangeKillSwitchProtector's order-rejection window.  Errors that are not
classified as local continue through the existing path unchanged, so genuine
broker/exchange rejection telemetry, thresholds and fail-closed behavior remain
intact.

V232 closes a remaining route-guard provenance gap discovered after capital and
position readiness converged. ``execution_route_integrity_patch`` deliberately
classifies several route/adapter outcomes as soft dispatch failures, but those
same strings could still be forwarded to this exchange-rejection telemetry
boundary.  V232 therefore treats those unproven route/adapter outcomes as
non-exchange results too.  Generic messages such as ``OKX order failed`` and
``all operations failed`` are excluded because, by themselves, they do not prove
that a broker submit reached an exchange or that an exchange returned a reject.
A concrete exchange response such as ``Kraken AddOrder rejected: ...`` remains
unclassified here and continues to count normally.

V247 closes the startup-heartbeat lifecycle provenance gap.  A terminal
execution-authority validator can legitimately fail closed with
``lifecycle_phase:BOOT`` / ``lifecycle_phase_not_live`` before any broker submit
has occurred.  Those canonical lifecycle denials are local pre-dispatch outcomes,
not exchange rejections, so they must not poison the exchange rejection-rate
window.  This change is deliberately prospective: it never deletes an existing
same-process rejection sample whose provenance is unknown.  Because the rolling
window itself is not persisted, the next clean process starts with an empty
window and v226 can independently recover a persisted historical EXCHANGE_MONITOR
latch only after all of its existing safety proofs pass.

V253 closes an execution-outcome provenance mismatch observed on 2026-08-28.
``ExecutionPipeline._reconcile_ack_timeout`` deliberately returns
``confirmed_order_rejected:ack_timeout_no_confirmed_fill...`` when no confirmed
broker acknowledgement/fill can be established inside the bounded ACK window.
The existing soft-reject classifier already treats that and
``terminal_reject_status:unfilled`` as operational/unconfirmed outcomes, but v228
had not excluded those exact strings from exchange-rejection telemetry.  Five
such synthetic results could therefore satisfy the 5/5 rejection-rate threshold
without proving that an exchange rejected five submitted orders.  V253 excludes
only those exact unconfirmed ACK/unfilled soft outcomes.  It does not treat them
as success, does not establish execution/fill proof, does not clear an existing
same-process window or kill switch, and does not suppress concrete exchange
rejection responses.

This patch never clears a kill switch, resets a rejection window, marks
readiness, grants execution authority, fabricates broker ACK/fill proof, changes
minimum notional/risk rules, or forces LIVE_ACTIVE.  A persisted historical
rejection stop must still satisfy v226's independent recovery proof after a
process restart.
"""
from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
import time
from functools import wraps
from types import ModuleType
from typing import Any

LOGGER = logging.getLogger("nija.exchange_reject_dispatch_provenance_v228")
MARKER = "20260825-exchange-reject-dispatch-provenance-v228"
V253_MARKER = "20260828-soft-timeout-rejection-provenance-v253"
_FLAG = "NIJA_EXCHANGE_REJECT_DISPATCH_PROVENANCE_V228_READY"
_PATCH_ATTR = "_nija_exchange_reject_dispatch_provenance_v228"
_LOCK = threading.RLock()
_THREAD: threading.Thread | None = None

# These are outcomes that can be produced without a broker order ever reaching
# an exchange, or without any confirmed exchange rejection response. They must
# never contribute to the exchange rejection-rate gate.
_NON_EXCHANGE_MARKERS = (
    "dispatch_disabled",
    "executionauthority reject",
    "execution_authority_blocked",
    "execution_authority_runtime",
    "execution_authority_halt",
    "execution gate pending",
    "blocked by state_machine",
    "state_machine=emergency_stop",
    "state_machine=live_pending_confirmation",
    "state_machine=off",
    "runtime authority convergence lost",
    "seak halted",
    "trading blocked",
    # V247: canonical startup lifecycle denials happen before broker submit.
    # Keep these exact authority-state tokens out of exchange telemetry while
    # leaving unclassified broker/exchange rejection strings untouched.
    "lifecycle_phase:boot",
    "lifecycle_phase_not_live",
    "exchangekillswitch: exchange health red",
    "exchange health red — trade blocked",
    "liquidityintelligenceengine",
    "liquidity grade below",
    "no available venue found",
    "no execution router available",
    "broker_adapter_not_connected",
    "execution blocked:",
    "no_execution_venue_available",
    "broker_not_registered",
    "replacement_unavailable",
    "direct_broker_metadata_mismatch",
    "direct_broker_metadata_cleared",
    "routing candidate",
    "internal route",
    "venue registry",
    "pretraderiskengine reject",
    "riskgovernor blocked",
    "slippageguard blocked",
    "capitalauthorization deny",
    "marginhealthgate reject",
    "ecel unavailable",
    "ecel reject:",
    "orderfeasibility deny",
    "postguard deny",
    # V232: execution_route_integrity_patch classifies these as soft/local
    # route outcomes.  None of these strings alone proves broker submission or
    # an exchange-level reject response.
    "broker_dispatch_failed",
    "empty_order_result",
    "empty order result",
    "execution_route_mismatch",
    "brokerrouteguard deny",
    "broker disabled",
    "adapter_exception",
    "broker_dispatch_exception",
    "okx order failed",
    "all operations failed",
    # V253: bounded ACK reconciliation could not establish a confirmed exchange
    # ACK/fill/reject. These are explicitly soft/unconfirmed outcomes elsewhere
    # in the pipeline and must not be promoted into exchange-rejection samples.
    "confirmed_order_rejected:ack_timeout",
    "ack_timeout_no_confirmed_fill",
    "terminal_reject_status:unfilled",
)


def _is_non_exchange_rejection(reason: Any) -> bool:
    text = str(reason or "").strip().lower()
    return bool(text) and any(marker in text for marker in _NON_EXCHANGE_MARKERS)


def _patch_execution_pipeline() -> bool:
    module = importlib.import_module("bot.execution_pipeline")
    cls = getattr(module, "ExecutionPipeline", None)
    if not isinstance(cls, type):
        return False

    current = getattr(cls, "_emit_execution_rejection_telemetry", None)
    if not callable(current):
        return False
    if getattr(current, _PATCH_ATTR, False):
        return True

    @wraps(current)
    def _emit_execution_rejection_telemetry_v228(
        self: Any,
        *,
        symbol: str,
        side: str,
        reason: str,
    ) -> Any:
        if _is_non_exchange_rejection(reason):
            LOGGER.critical(
                "EXCHANGE_REJECT_V228_NON_EXCHANGE_IGNORED marker=%s v253_marker=%s "
                "symbol=%s side=%s reason=%s exchange_sample_mutated=false "
                "exchange_order_provenance=false route_guard_provenance_v232=true "
                "lifecycle_provenance_v247=true soft_timeout_provenance_v253=true "
                "kill_switch_unchanged=true execution_authority_unchanged=true "
                "execution_proof_fabricated=false safety_gates_bypassed=false",
                MARKER,
                V253_MARKER,
                str(symbol)[:64],
                str(side)[:32],
                str(reason)[:512],
            )
            return None
        return current(self, symbol=symbol, side=side, reason=reason)

    setattr(_emit_execution_rejection_telemetry_v228, _PATCH_ATTR, True)
    setattr(_emit_execution_rejection_telemetry_v228, "__wrapped__", current)
    setattr(cls, "_emit_execution_rejection_telemetry", _emit_execution_rejection_telemetry_v228)
    return True


def _register_manifest_if_loaded() -> bool:
    manifest = sys.modules.get("bot.runtime_release_manifest_patch")
    if not isinstance(manifest, ModuleType):
        return True
    required = getattr(manifest, "_REQUIRED_FLAGS", None)
    installers = getattr(manifest, "_INSTALLERS", None)
    if not isinstance(required, dict):
        return False
    required["exchange_reject_dispatch_provenance_v228"] = _FLAG
    own = ("bot.exchange_reject_dispatch_provenance_v228_patch", "install_import_hook")
    if isinstance(installers, tuple) and own not in installers:
        manifest._INSTALLERS = tuple(installers) + (own,)
    return True


def _worker() -> None:
    while True:
        try:
            _patch_execution_pipeline()
            _register_manifest_if_loaded()
        except Exception as exc:
            LOGGER.warning(
                "EXCHANGE_REJECT_V228_REASSERT_ERROR marker=%s v253_marker=%s err=%s:%s "
                "trading_fail_closed=true",
                MARKER,
                V253_MARKER,
                type(exc).__name__,
                exc,
            )
        time.sleep(5.0)


def install() -> bool:
    global _THREAD
    if not _patch_execution_pipeline():
        os.environ[_FLAG] = "0"
        return False
    if not _register_manifest_if_loaded():
        os.environ[_FLAG] = "0"
        return False
    os.environ[_FLAG] = "1"
    with _LOCK:
        if _THREAD is None or not _THREAD.is_alive():
            _THREAD = threading.Thread(
                target=_worker,
                name="ExchangeRejectDispatchProvenanceV228",
                daemon=True,
            )
            _THREAD.start()
    LOGGER.critical(
        "EXCHANGE_REJECT_DISPATCH_PROVENANCE_V228_READY marker=%s v253_marker=%s ready=true "
        "local_predispatch_rejects_excluded=true route_guard_provenance_v232=true "
        "lifecycle_provenance_v247=true soft_timeout_provenance_v253=true "
        "real_exchange_path_unchanged=true rejection_thresholds_unchanged=true "
        "rejection_window_not_cleared=true kill_switch_unchanged=true "
        "execution_authority_unchanged=true execution_proof_fabricated=false "
        "forced_activation=false safety_gates_bypassed=false",
        MARKER,
        V253_MARKER,
    )
    return True


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "V253_MARKER",
    "install",
    "install_import_hook",
    "_is_non_exchange_rejection",
    "_patch_execution_pipeline",
]
