from __future__ import annotations

from scripts import apply_execution_proof_recovery_retry_v401 as v401


def _target_source() -> str:
    return """import importlib
import logging
import threading

LOGGER = logging.getLogger(__name__)
_LAST_DIAGNOSTIC: dict[str, float] = {}


def _log_due(_key, interval_s=30.0):
    return True


def _v367():
    raise NotImplementedError


def recover_execution_proof_once():
    return 0


def _patch_v367_recovery() -> bool:
    return True


def install_import_hook() -> bool:
    ready = True
    if ready:
        try:
            recover_execution_proof_once()
        except Exception:
            LOGGER.debug("v372 immediate recovery deferred", exc_info=True)
    return ready
"""


def test_retry_worker_waits_for_canonical_execution_readiness(tmp_path, monkeypatch):
    target = tmp_path / "runtime_kraken_margin_execution_proof_liveness_v372_patch.py"
    target.write_text(_target_source(), encoding="utf-8")
    monkeypatch.setattr(v401, "TARGET", target)

    v401.main()

    patched = target.read_text(encoding="utf-8")
    compile(patched, str(target), "exec")

    assert 'importlib.import_module("bot.readiness_table")' in patched
    assert 'table.get("execution_ready", False)' in patched
    assert 'detail=canonical_execution_ready persistent_monitor=true' in patched
    assert 'future_expiry_recovery_enabled=true' in patched
    assert 'canonical_execution_ready_became_false' in patched
    assert 'canonical_execution_ready=false retry_continues=true' in patched
    assert 'marker_probe = getattr(v367, "_execution_marker_ready", None)' not in patched

    ready_block = patched.split(
        "EXECUTION_PROOF_RECOVERY_RETRY_V401_ARMED", 1
    )[1].split("recovered = recover_execution_proof_once()", 1)[0]
    assert "return" not in ready_block
    assert "continue" in ready_block

    recovered_block = patched.split(
        "EXECUTION_PROOF_RECOVERY_RETRY_V401_EVIDENCE_RECOVERED", 1
    )[1].split("except Exception as exc:", 1)[0]
    assert "return" not in recovered_block
