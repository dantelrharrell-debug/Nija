from __future__ import annotations

import os
import types

from bot import preactivation_position_sync_v119_patch as v119


class FakeTable:
    def __init__(self) -> None:
        self.values = {
            "broker_connected": True,
            "balance_hydrated": True,
            "authority_ready": True,
            "capital_ready": True,
            "risk_ready": True,
            "strategy_ready": True,
            "execution_ready": True,
            "nonce_ready": True,
            "bootstrap_ready": True,
            "position_sync_ready": False,
        }

    def snapshot(self):
        return dict(self.values)

    def mark_ready(self, key):
        self.values[key] = True

    def revoke_ready(self, key, reason=""):
        self.values[key] = False


def test_truth_sync_observes_position_sync_without_publishing_it(monkeypatch):
    table = FakeTable()
    v61 = types.SimpleNamespace(
        _KEYS=(
            "broker_connected",
            "balance_hydrated",
            "authority_ready",
            "capital_ready",
            "risk_ready",
            "strategy_ready",
            "execution_ready",
            "nonce_ready",
            "bootstrap_ready",
        ),
        _state_value=lambda: "LIVE_PENDING_CONFIRMATION",
    )
    v16 = types.SimpleNamespace(_mark_proven_readiness=lambda proofs: (True, []))
    monkeypatch.setattr(v119, "_readiness_table_module", lambda: table)

    assert v119._patch_truth_sync(v61, v16) is True
    proofs = {key: True for key in v61._KEYS}
    ready, pending = v16._mark_proven_readiness(proofs)

    assert ready is False
    assert pending == ["position_sync_ready"]
    assert table.values["position_sync_ready"] is False
    assert os.environ["NIJA_PREACTIVATION_READINESS_V16_READY"] == "0"


def test_activation_prerequisites_require_canonical_position_sync(monkeypatch):
    v61 = types.SimpleNamespace(
        _activation_prerequisites=lambda: (True, [], {"legacy": "ready"})
    )
    monkeypatch.setattr(
        v119,
        "_position_sync_truth",
        lambda: (False, "canonical_readiness_table", {"position_sync_ready": False}),
    )

    assert v119._patch_activation_prerequisites(v61) is True
    ready, blockers, details = v61._activation_prerequisites()

    assert ready is False
    assert blockers == ["position_sync_ready"]
    assert details["position_sync_readiness"]["ready"] is False


def test_release_manifest_attests_modern_convergence_flags(monkeypatch):
    manifest = types.SimpleNamespace(_REQUIRED_FLAGS={}, RELEASE_ID="old")

    assert v119._patch_release_manifest(manifest) is True
    assert manifest.RELEASE_ID == v119.RELEASE_ID
    assert manifest._REQUIRED_FLAGS["position_sync_timeout_v98"] == "NIJA_POSITION_SYNC_TIMEOUT_V98_INSTALLED"
    assert manifest._REQUIRED_FLAGS["runtime_convergence_v116"] == "NIJA_RUNTIME_CONVERGENCE_V116_INSTALLED"
    assert manifest._REQUIRED_FLAGS["position_fetch_generation_v117"] == "NIJA_POSITION_FETCH_GENERATION_V117_INSTALLED"
    assert manifest._REQUIRED_FLAGS["terminal_writer_loss_seak_v118"] == "NIJA_TERMINAL_WRITER_LOSS_SEAK_V118_INSTALLED"
    assert manifest._REQUIRED_FLAGS["preactivation_position_sync_v119"] == "NIJA_PREACTIVATION_POSITION_SYNC_V119_INSTALLED"


def test_v119_installs_no_builtins_import_hook():
    import inspect

    source = inspect.getsource(v119.install_import_hook)
    assert "builtins.__import__" not in source
