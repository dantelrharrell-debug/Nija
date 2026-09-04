"""Canonical capital-readiness mode decoupling v358.

Repairs a circular readiness dependency in the legacy v16 proof collector:
``capital_ready`` was gated by live-mode selection even when canonical capital
authority was already hydrated, fresh, funded, and broker-backed. Trading mode
is an activation policy; it is not evidence about whether capital itself is
valid.

Safety contract:
- derive capital readiness only from the existing current v16 capital proof;
- require hydrated, non-stale, positive real capital and a registered broker;
- do not change execution_ready, execution proof, trading state, kill switch,
  writer/nonce authority, or position/exit behavior;
- never force activation and never fabricate capital or fills.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
from typing import Any

LOGGER = logging.getLogger("nija.runtime_capital_readiness_mode_decoupling_v358")
MARKER = "20260903-runtime-capital-readiness-mode-decoupling-v358"
_READY_FLAG = "NIJA_RUNTIME_CAPITAL_READINESS_MODE_DECOUPLING_V358_READY"
_LOCK = threading.RLock()
_INSTALLED = False


def _import_v16() -> Any:
    try:
        return importlib.import_module("preactivation_readiness_convergence_v16_patch")
    except Exception:
        return importlib.import_module("bot.preactivation_readiness_convergence_v16_patch")


def _capital_proof_ready(capital: dict[str, Any]) -> bool:
    try:
        hydrated = bool(capital.get("hydrated", False))
        stale = bool(capital.get("stale", True))
        real = float(capital.get("real", 0.0) or 0.0)
        registered = int(float(capital.get("registered", 0) or 0))
    except (TypeError, ValueError, OverflowError):
        return False
    return bool(hydrated and not stale and real > 0.0 and registered > 0)


def _patch_v16_collector() -> bool:
    v16 = _import_v16()
    current = getattr(v16, "_collect_proofs", None)
    if not callable(current):
        return False
    if getattr(current, "_nija_v358_capital_mode_decoupled", False):
        return True

    original = current

    def collect_proofs_v358():
        proofs, details = original()
        proofs = dict(proofs or {})
        details = dict(details or {})

        capital = details.get("capital")
        if not isinstance(capital, dict):
            try:
                capital = dict(v16._capital_snapshot())
            except Exception:
                capital = {}

        capital_ready = _capital_proof_ready(capital)
        proofs["capital_ready"] = capital_ready
        details["capital_ready_v358"] = capital_ready
        details["capital_ready_mode_decoupled"] = True
        details["capital_ready_source"] = str(capital.get("source", "v16_current_capital") or "v16_current_capital")

        if capital_ready:
            LOGGER.info(
                "CAPITAL_READINESS_V358_ACCEPTED marker=%s hydrated=true stale=false real=%.2f registered=%d live_mode_dependency=false activation_unchanged=true execution_ready_unchanged=true",
                MARKER,
                float(capital.get("real", 0.0) or 0.0),
                int(float(capital.get("registered", 0) or 0)),
            )
        else:
            LOGGER.warning(
                "CAPITAL_READINESS_V358_PENDING marker=%s hydrated=%s stale=%s real=%s registered=%s live_mode_dependency=false trading_fail_closed=true",
                MARKER,
                bool(capital.get("hydrated", False)),
                bool(capital.get("stale", True)),
                capital.get("real", 0.0),
                capital.get("registered", 0),
            )
        return proofs, details

    collect_proofs_v358._nija_v358_capital_mode_decoupled = True
    collect_proofs_v358.__wrapped__ = original
    v16._collect_proofs = collect_proofs_v358
    return True


def _patch_release_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if isinstance(required, dict):
            required["runtime_capital_readiness_mode_decoupling_v358"] = _READY_FLAG
            return True
    except Exception:
        pass
    return False


def install_import_hook() -> bool:
    global _INSTALLED
    with _LOCK:
        try:
            ok = bool(_patch_v16_collector() and _patch_release_manifest())
        except Exception as exc:
            LOGGER.exception(
                "RUNTIME_CAPITAL_READINESS_V358_INSTALL_FAILED marker=%s err=%s:%s trading_fail_closed=true",
                MARKER,
                type(exc).__name__,
                exc,
            )
            ok = False
        os.environ[_READY_FLAG] = "1" if ok else "0"
        _INSTALLED = ok
        if ok:
            LOGGER.critical(
                "RUNTIME_CAPITAL_READINESS_MODE_DECOUPLING_V358_READY marker=%s ready=true hydrated_required=true stale_false_required=true positive_real_required=true registered_broker_required=true live_mode_dependency=false execution_ready_unchanged=true execution_proof_unchanged=true forced_activation=false safety_gates_bypassed=false",
                MARKER,
            )
        return ok


def install() -> bool:
    return install_import_hook()


__all__ = ["MARKER", "install", "install_import_hook", "_capital_proof_ready", "_patch_v16_collector"]
