from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from types import ModuleType


ROOT = Path(__file__).resolve().parents[1]
V231 = ROOT / "bot" / "runtime_authority_nonce_truth_convergence_v231_patch.py"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, V231)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _fake_v16() -> ModuleType:
    module = ModuleType("preactivation_readiness_convergence_v16_patch")

    def collect():
        return (
            {
                "broker_connected": True,
                "balance_hydrated": True,
                "authority_ready": False,
                "capital_ready": True,
                "risk_ready": True,
                "strategy_ready": True,
                "execution_ready": False,
                "nonce_ready": False,
                "bootstrap_ready": True,
            },
            {"execution_pipeline_wired": True},
        )

    module._collect_proofs = collect
    return module


def _install_collection(monkeypatch, module, *, nonce_ready: bool, marker_ready: bool):
    v16 = _fake_v16()
    monkeypatch.setattr(module, "_v16", lambda: v16)
    monkeypatch.setattr(
        module,
        "_current_writer_authority_proof",
        lambda: (True, "writer_authority_current"),
    )
    monkeypatch.setattr(
        module,
        "_raw_nonce_authority_proof",
        lambda: (nonce_ready, "raw_nonce_current" if nonce_ready else "raw_nonce_blocked"),
    )
    monkeypatch.setattr(
        module,
        "_execution_marker_proof",
        lambda: (
            marker_ready,
            "execution_marker_current" if marker_ready else "marker_missing",
        ),
    )
    monkeypatch.setattr(module, "_kraken_nonce_required", lambda: True)
    assert module._patch_v16_proof_collection() is True
    return v16


def test_marker_missing_does_not_erase_raw_nonce_readiness(monkeypatch) -> None:
    module = _load("test_nonce_execution_v272_marker_missing")
    v16 = _install_collection(
        monkeypatch,
        module,
        nonce_ready=True,
        marker_ready=False,
    )

    proofs, details = v16._collect_proofs()

    assert proofs["authority_ready"] is True
    assert proofs["nonce_ready"] is True
    assert proofs["execution_ready"] is False
    assert details["v272_raw_nonce_detail"] == "raw_nonce_current"
    assert details["v272_execution_marker_ready"] is False
    assert details["v272_execution_marker_detail"] == "marker_missing"


def test_execution_ready_requires_raw_nonce_and_genuine_marker(monkeypatch) -> None:
    module = _load("test_nonce_execution_v272_both_ready")
    v16 = _install_collection(
        monkeypatch,
        module,
        nonce_ready=True,
        marker_ready=True,
    )

    proofs, details = v16._collect_proofs()

    assert proofs["nonce_ready"] is True
    assert proofs["execution_ready"] is True
    assert details["v272_execution_marker_ready"] is True


def test_valid_execution_marker_cannot_substitute_for_failed_raw_nonce(monkeypatch) -> None:
    module = _load("test_nonce_execution_v272_nonce_failed")
    v16 = _install_collection(
        monkeypatch,
        module,
        nonce_ready=False,
        marker_ready=True,
    )

    proofs, details = v16._collect_proofs()

    assert proofs["nonce_ready"] is False
    assert proofs["execution_ready"] is False
    assert details["v272_raw_nonce_detail"] == "raw_nonce_blocked"
    assert details["v272_execution_marker_ready"] is True


def test_execution_marker_helper_rejects_wrong_provenance(monkeypatch) -> None:
    module = _load("test_nonce_execution_v272_bad_provenance")
    tsm = ModuleType("bot.trading_state_machine")
    tsm._heartbeat_verification_status = lambda: (
        True,
        "",
        {
            "required_stage": "ORDER_VERIFY",
            "stage": "FILL_VERIFY",
            "source": "authority_heartbeat",
            "proof_kind": "authority_liveness",
        },
    )
    monkeypatch.setattr(module, "_tsm", lambda: tsm)

    ready, detail = module._execution_marker_proof()

    assert ready is False
    assert detail.startswith("execution_provenance_invalid:")


def test_nonce_reconciliation_revokes_only_from_raw_nonce_failure(monkeypatch) -> None:
    module = _load("test_nonce_execution_v272_revoke")

    class Readiness:
        def __init__(self):
            self.state = {"nonce_ready": True}
            self.revocations = []

        def snapshot(self):
            return dict(self.state)

        def mark_ready(self, key):
            self.state[key] = True

        def revoke_ready(self, key, reason=""):
            self.state[key] = False
            self.revocations.append((key, reason))

    readiness = Readiness()
    monkeypatch.setattr(module, "_readiness", lambda: readiness)
    monkeypatch.setattr(
        module,
        "_raw_nonce_authority_proof",
        lambda: (False, "nonce_lease_not_ready"),
    )
    monkeypatch.setattr(module, "_kraken_nonce_required", lambda: True)

    ready, detail = module._correct_heartbeat_nonce_truth()

    assert ready is False
    assert detail == "nonce_lease_not_ready"
    assert readiness.state["nonce_ready"] is False
    assert readiness.revocations == [
        ("nonce_ready", "v272_raw_nonce_authority_false")
    ]
