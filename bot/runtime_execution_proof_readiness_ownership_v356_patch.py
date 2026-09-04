"""Execution-proof ownership for canonical ``execution_ready`` (v356).

Production on 2026-09-04 proved a concrete semantic regression: the strategy
publication helper marked ``execution_ready`` merely because a connected entry
broker was wired, while the canonical v238/v346 execution marker still reported
``marker_missing``.  That transiently published a readiness truth that had no
confirmed-fill proof.

v356 gives strategy publication only its legitimate ownership:
``strategy_ready``.  ``execution_ready`` remains owned by the canonical
execution-proof path (v169/v231/v238/v346 and successors).

This patch does not create or modify an execution marker, treat ACK/order IDs as
fills, submit orders, force activation, clear kill switches/rejection history,
or weaken writer/nonce/risk/capital/position/ECEL/minimum-order/fill gates.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
from typing import Any

LOGGER = logging.getLogger("nija.runtime_execution_proof_readiness_ownership_v356")
MARKER = "20260904-runtime-execution-proof-readiness-ownership-v356"
RELEASE_ID = "20260904-runtime-convergence-v356"
_READY_FLAG = "NIJA_RUNTIME_EXECUTION_PROOF_READINESS_OWNERSHIP_V356_READY"
_PATCH_ATTR = "_nija_execution_proof_readiness_ownership_v356"
_LOCK = threading.RLock()


def _strategy_module() -> Any:
    return importlib.import_module("bot.strategy_publication_patch")


def _patch_strategy_publish() -> bool:
    module = _strategy_module()
    current = getattr(module, "_publish", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    def publish_v356(strategy: Any) -> None:
        # Preserve strategy publication side effects exactly, but do not grant
        # execution readiness.  A connected broker proves wiring, not a fill.
        module._PUBLISHED = strategy
        for target in module._modules():
            try:
                setattr(target, "nija_live_strategy", strategy)
                setattr(target, "trading_strategy", strategy)
                state = getattr(target, "_initialized_state", None)
                if not isinstance(state, dict):
                    state = {}
                    setattr(target, "_initialized_state", state)
                state["strategy"] = strategy
                state["trading_strategy"] = strategy
            except Exception:
                continue

        module.logger.critical(
            "STRATEGY_PUBLICATION_READY type=%s broker=%s broker_connected=%s core_loop=%s symbols=%s",
            type(strategy).__name__,
            type(getattr(strategy, "broker", None)).__name__
            if getattr(strategy, "broker", None) is not None else "none",
            bool(getattr(getattr(strategy, "broker", None), "connected", False)),
            bool(getattr(strategy, "nija_core_loop", None)),
            len(getattr(strategy, "symbols", []) or []),
        )

        try:
            readiness = importlib.import_module("bot.readiness_table")
            mark_ready = getattr(readiness, "mark_ready", None)
            if callable(mark_ready):
                mark_ready("strategy_ready")
            module.logger.info(
                "STRATEGY_PUBLICATION_V356_READINESS strategy_ready=true "
                "execution_ready_unchanged=true execution_proof_owner=canonical_v169_v231_v238_v346"
            )
        except Exception as exc:
            module.logger.debug("STRATEGY_PUBLICATION_V356_READINESS_MARK_FAILED err=%s", exc)

        # Preserve the existing bootstrap recheck.  Since execution_ready is no
        # longer synthesized here, the bootstrap remains fail closed until the
        # canonical execution proof owner marks it legitimately.
        try:
            bootstrap = importlib.import_module("bot.post_lock_capital_refresh_patch")
            maybe = getattr(bootstrap, "_maybe_mark_bootstrap", None)
            if callable(maybe):
                maybe("strategy_publication")
        except Exception as exc:
            module.logger.debug("STRATEGY_PUBLICATION_V356_BOOTSTRAP_CHECK_FAILED err=%s", exc)

    publish_v356.__name__ = "publish_v356"
    setattr(publish_v356, _PATCH_ATTR, True)
    setattr(publish_v356, "__wrapped__", current)
    module._publish = publish_v356
    return True


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_execution_proof_readiness_ownership_v356"] = _READY_FLAG
        return True
    except Exception:
        return False


def install_import_hook() -> bool:
    with _LOCK:
        publish_ok = False
        manifest_ok = False
        try:
            publish_ok = _patch_strategy_publish()
            manifest_ok = _register_manifest()
        except Exception:
            LOGGER.exception(
                "RUNTIME_EXECUTION_PROOF_READINESS_OWNERSHIP_V356_INSTALL_ERROR marker=%s fail_closed=true",
                MARKER,
            )
        ready = bool(publish_ok and manifest_ok)
        os.environ[_READY_FLAG] = "1" if ready else "0"
        log = LOGGER.critical if ready else LOGGER.error
        log(
            "RUNTIME_EXECUTION_PROOF_READINESS_OWNERSHIP_V356_%s marker=%s ready=%s "
            "strategy_publication_execution_grant_removed=%s canonical_execution_proof_required=true "
            "ack_not_fill=true order_id_not_fill=true marker_not_fabricated=true forced_activation=false "
            "writer_nonce_risk_capital_position_killswitch_ecel_minimum_order_fill_gates_unchanged=true "
            "protective_exits_unchanged=true safety_gates_bypassed=false",
            "READY" if ready else "NOT_READY",
            MARKER,
            str(ready).lower(),
            str(publish_ok).lower(),
        )
        return ready


def install() -> bool:
    return install_import_hook()


__all__ = ["MARKER", "RELEASE_ID", "install", "install_import_hook", "_patch_strategy_publish"]
