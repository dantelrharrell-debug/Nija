"""Kraken margin-exit authority convergence v354.

Fresh production evidence on 2026-09-03 showed an unconfirmed leveraged Kraken
BUY whose exchange status said ``filled`` but lacked fill-specific price or
notional. NIJA correctly refused to create confirmed execution proof. The
canonical margin ledger can therefore retain the pre-submit ``pending_open``
record. ``pipeline_order_submitter._resolve_margin_exit`` previously treated
``pending_open`` as an established margin position and transformed a later
protective SELL into 2x reduce-only/BTNL routing. Kraken then rejected that
protective exit with ``EOrder:Reduce only:Cannot increase position``.

v354 removes only that unsafe authority promotion. A ``pending_open`` ledger
record is not confirmed position proof and may not transform exit semantics.
Confirmed ``open`` and ``reducing`` margin records preserve the existing path.
No broker order is synthesized, no fill is inferred, and no kill switch or
rejection latch is cleared.
"""
from __future__ import annotations

import importlib
import logging
import os
from functools import wraps
from typing import Any, Dict

LOGGER = logging.getLogger("nija.runtime_kraken_margin_exit_authority_v354")
MARKER = "20260903-runtime-kraken-margin-exit-authority-v354"
RELEASE_ID = "20260903-runtime-convergence-v354"
_READY_FLAG = "NIJA_RUNTIME_KRAKEN_MARGIN_EXIT_AUTHORITY_V354_READY"
_PATCH_ATTR = "_nija_v354_confirmed_margin_exit_authority"


def _patch_submitter() -> bool:
    module = importlib.import_module("bot.pipeline_order_submitter")
    current = getattr(module, "_resolve_margin_exit", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True
    original = current

    @wraps(original)
    def resolve_margin_exit_v354(preferred_broker: str, account_id: str, symbol: str) -> Dict[str, Any]:
        resolved = original(preferred_broker, account_id, symbol)
        if not isinstance(resolved, dict) or not resolved:
            return resolved
        reason = str(resolved.get("reason") or "").strip().lower()
        if reason == "existing_margin_position:pending_open":
            LOGGER.critical(
                "KRAKEN_MARGIN_EXIT_V354_UNCONFIRMED_INTENT_IGNORED marker=%s "
                "account=%s symbol=%s lifecycle=pending_open "
                "pending_order_not_position_proof=true margin_exit_not_inferred=true "
                "reduce_only_not_inferred=true btnl_not_inferred=true ack_not_fill=true "
                "confirmed_open_reducing_authority_unchanged=true kill_switch_cleared=false "
                "rejection_window_cleared=false execution_proof_fabricated=false "
                "writer_nonce_risk_capital_position_sync_ecel_broker_health_minimum_order_fill_gates_unchanged=true "
                "safety_gates_bypassed=false",
                MARKER,
                account_id,
                symbol,
            )
            return {}
        return resolved

    setattr(resolve_margin_exit_v354, _PATCH_ATTR, True)
    setattr(resolve_margin_exit_v354, "__wrapped__", original)
    module._resolve_margin_exit = resolve_margin_exit_v354
    return True


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_kraken_margin_exit_authority_v354"] = _READY_FLAG
        return True
    except Exception:
        return False


def install_import_hook() -> bool:
    patched = manifest = False
    try:
        patched = _patch_submitter()
        manifest = _register_manifest()
    except Exception as exc:
        LOGGER.exception(
            "RUNTIME_KRAKEN_MARGIN_EXIT_AUTHORITY_V354_INSTALL_ERROR marker=%s error=%s:%s fail_closed=true",
            MARKER, type(exc).__name__, exc,
        )
    ready = bool(patched and manifest)
    os.environ[_READY_FLAG] = "1" if ready else "0"
    log = LOGGER.critical if ready else LOGGER.error
    log(
        "RUNTIME_KRAKEN_MARGIN_EXIT_AUTHORITY_V354_%s marker=%s ready=%s "
        "pending_open_not_position_authority=true confirmed_open_reducing_unchanged=true "
        "ack_not_fill=true execution_proof_fabricated=false forced_trade=false forced_activation=false "
        "kill_switch_unchanged=true rejection_window_unchanged=true protections_unchanged=true "
        "writer_nonce_risk_capital_position_sync_ecel_broker_health_minimum_order_quantity_fill_gates_unchanged=true "
        "safety_gates_bypassed=false",
        "READY" if ready else "NOT_READY", MARKER, str(ready).lower(),
    )
    return ready


def install() -> bool:
    return install_import_hook()


__all__ = ["MARKER", "RELEASE_ID", "install", "install_import_hook", "_patch_submitter"]
