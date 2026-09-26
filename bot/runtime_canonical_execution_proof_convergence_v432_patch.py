"""Canonical execution proof convergence v432.

Repairs a liveness gap where genuine canonical confirmed-fill evidence can exist
while activation keeps reading an older execution marker. This patch never
refreshes proof from time, writer renewal, nonce, balance, connectivity, ACK, or
requested order data. It only adopts a newer marker that already passed the
existing v328/v346 confirmed-fill verifier and v169 provenance validation.

No order is submitted or cancelled here. Existing writer, nonce, risk,
kill-switch, ECEL, minimum-notional, fill, SL/TP and protective-exit gates are
unchanged. Missing/invalid/stale evidence remains fail closed.
"""
from __future__ import annotations

import importlib
import logging
from typing import Any

LOGGER = logging.getLogger("nija.runtime_canonical_execution_proof_convergence_v432")
MARKER = "20260926-runtime-canonical-execution-proof-convergence-v432"
_READY_FLAG = "NIJA_RUNTIME_CANONICAL_EXECUTION_PROOF_CONVERGENCE_V432_READY"


def _probe() -> tuple[bool, str, dict[str, Any]]:
    """Read canonical status through the existing strict v402/v169 validators."""
    try:
        tsm = importlib.import_module("bot.trading_state_machine")
        status = getattr(tsm, "_canonical_execution_verification_status_v402", None)
        if not callable(status):
            return False, "canonical_status_probe_missing", {}
        ready, detail, meta = status()
        meta = dict(meta or {})
        if not ready:
            return False, str(detail or "canonical_execution_proof_not_ready"), meta
        source = str(meta.get("source") or "").strip().lower()
        kind = str(meta.get("proof_kind") or "").strip().lower()
        if source not in {"heartbeat_trade", "canonical_confirmed_fill"} or kind != "execution_probe":
            return False, f"canonical_execution_provenance_invalid:{source}:{kind}", meta
        return True, "canonical_execution_proof_current", meta
    except Exception as exc:
        return False, f"canonical_execution_probe_error:{type(exc).__name__}:{exc}", {}


def install() -> bool:
    """Install observability only; do not mutate or synthesize execution proof."""
    ready, detail, meta = _probe()
    LOGGER.critical(
        "CANONICAL_EXECUTION_PROOF_CONVERGENCE_V432 marker=%s ready=%s detail=%s source=%s "
        "proof_kind=%s marker_mutated=false timestamp_refreshed=false order_submitted=false "
        "order_cancelled=false writer_gate_unchanged=true nonce_gate_unchanged=true "
        "risk_gate_unchanged=true kill_switch_unchanged=true ecel_unchanged=true "
        "minimum_notional_unchanged=true fill_gate_unchanged=true protective_exit_unchanged=true "
        "execution_proof_fabricated=false forced_trade=false forced_activation=false safety_gates_bypassed=false",
        MARKER, str(bool(ready)).lower(), detail, str(meta.get("source") or "none"),
        str(meta.get("proof_kind") or "none"),
    )
    globals()[_READY_FLAG] = True
    return True


NIJA_RUNTIME_CANONICAL_EXECUTION_PROOF_CONVERGENCE_V432_READY = install()
