#!/usr/bin/env python3
"""Make v372 execution-proof recovery retry after broker hydration (v401).

The v372 recovery path is safe and evidence-only: authenticated OpenPositions
metadata identifies an exact opening order id, authenticated QueryOrders proves a
final fill, v328 validates fill truth, and v346 owns the execution marker.  The
production liveness gap is that v372 calls this recovery only once during early
startup, before account brokers are hydrated.

This patch adds a single daemon retry worker that stops naturally once canonical
execution proof exists.  It never submits/cancels an order, fabricates a marker,
grants readiness, changes writer/nonce/risk/capital/position/kill-switch gates,
or forces activation.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "bot" / "runtime_kraken_margin_execution_proof_liveness_v372_patch.py"
MARKER = "20260907-execution-proof-recovery-retry-v401"


def main() -> None:
    text = TARGET.read_text(encoding="utf-8")
    if MARKER in text:
        print("EXECUTION_PROOF_RECOVERY_RETRY_V401_ALREADY_APPLIED")
        return

    globals_old = '''_LAST_DIAGNOSTIC: dict[str, float] = {}\n\n\n'''
    globals_new = '''_LAST_DIAGNOSTIC: dict[str, float] = {}\n_RECOVERY_THREAD: threading.Thread | None = None\n_RECOVERY_STOP = threading.Event()\nRECOVERY_RETRY_MARKER = "20260907-execution-proof-recovery-retry-v401"\n\n\n'''
    if globals_old not in text:
        raise RuntimeError("v401 globals anchor not found")
    text = text.replace(globals_old, globals_new, 1)

    worker_anchor = '''def _patch_v367_recovery() -> bool:\n'''
    worker_code = '''def _recovery_worker() -> None:\n    while not _RECOVERY_STOP.wait(5.0):\n        try:\n            v367 = _v367()\n            marker_probe = getattr(v367, "_execution_marker_ready", None)\n            if callable(marker_probe):\n                try:\n                    ready, detail = marker_probe()\n                except Exception:\n                    ready, detail = False, "probe_exception"\n                if ready:\n                    LOGGER.critical(\n                        "EXECUTION_PROOF_RECOVERY_RETRY_V401_COMPLETE marker=%s "\n                        "detail=%s orders_submitted=false orders_cancelled=false "\n                        "execution_proof_fabricated=false forced_activation=false "\n                        "safety_gates_bypassed=false",\n                        RECOVERY_RETRY_MARKER, str(detail or "ready"),\n                    )\n                    return\n            recovered = recover_execution_proof_once()\n            if recovered:\n                LOGGER.critical(\n                    "EXECUTION_PROOF_RECOVERY_RETRY_V401_EVIDENCE_RECOVERED marker=%s "\n                    "exact_authenticated_fill_required=true orders_submitted=false "\n                    "orders_cancelled=false execution_proof_fabricated=false "\n                    "forced_activation=false safety_gates_bypassed=false",\n                    RECOVERY_RETRY_MARKER,\n                )\n                return\n        except Exception as exc:\n            if _log_due("v401_worker_error"):\n                LOGGER.info(\n                    "EXECUTION_PROOF_RECOVERY_RETRY_V401_DEFERRED marker=%s "\n                    "error=%s:%s trading_fail_closed=true orders_submitted=false "\n                    "execution_proof_fabricated=false safety_gates_bypassed=false",\n                    RECOVERY_RETRY_MARKER, type(exc).__name__, exc,\n                )\n\n\ndef _start_recovery_worker() -> None:\n    global _RECOVERY_THREAD\n    if _RECOVERY_THREAD is not None and _RECOVERY_THREAD.is_alive():\n        return\n    _RECOVERY_STOP.clear()\n    _RECOVERY_THREAD = threading.Thread(\n        target=_recovery_worker,\n        name="KrakenExecutionProofRecoveryV401",\n        daemon=True,\n    )\n    _RECOVERY_THREAD.start()\n    LOGGER.critical(\n        "EXECUTION_PROOF_RECOVERY_RETRY_V401_READY marker=%s "\n        "read_only_until_exact_fill_proven=true exact_queryorders_required=true "\n        "orders_submitted=false orders_cancelled=false execution_proof_fabricated=false "\n        "forced_activation=false safety_gates_bypassed=false",\n        RECOVERY_RETRY_MARKER,\n    )\n\n\n'''
    if worker_anchor not in text:
        raise RuntimeError("v401 worker anchor not found")
    text = text.replace(worker_anchor, worker_code + worker_anchor, 1)

    install_old = '''        if ready:\n            try:\n                recover_execution_proof_once()\n            except Exception:\n                LOGGER.debug("v372 immediate recovery deferred", exc_info=True)\n        return ready\n'''
    install_new = '''        if ready:\n            try:\n                recover_execution_proof_once()\n            except Exception:\n                LOGGER.debug("v372 immediate recovery deferred", exc_info=True)\n            _start_recovery_worker()\n        return ready\n'''
    if install_old not in text:
        raise RuntimeError("v401 install anchor not found")
    text = text.replace(install_old, install_new, 1)

    TARGET.write_text(text, encoding="utf-8")
    print(
        "EXECUTION_PROOF_RECOVERY_RETRY_V401_PATCH_APPLIED "
        "retry_after_hydration=true exact_queryorders_required=true "
        "orders_submitted=false orders_cancelled=false execution_proof_fabricated=false "
        "forced_activation=false safety_gates_bypassed=false"
    )


if __name__ == "__main__":
    main()
