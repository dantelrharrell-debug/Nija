"""v458: live authority proof reconciliation and truth are fail closed.

The tested handler never authorizes orders: it only updates/readbacks canonical
readiness and independently checks the real kill-switch before an authority
proof can be repaired from the current writer-lease probe.
"""
from __future__ import annotations

import types

from bot import post_activation_proof_loss_v133_patch as v133


class _Table:
    def __init__(self, refuse_ready=False):
        self.values = {key: False for key in v133._CRITICAL_KEYS}
        self.refuse_ready = refuse_ready

    def mark_ready(self, key):
        if not self.refuse_ready:
            self.values[key] = True

    def revoke_ready(self, key, reason=""):
        self.values[key] = False

    def snapshot(self):
        return dict(self.values)


def _install_import_stubs(monkeypatch, *, stop_active, writer_ready=True, table=None):
    original = v133.importlib.import_module
    calls = []

    def fake_import(name):
        if name == "bot.kill_switch":
            if isinstance(stop_active, Exception):
                raise stop_active
            return types.SimpleNamespace(
                get_kill_switch=lambda: types.SimpleNamespace(
                    is_active=lambda: stop_active
                )
            )
        if name == "bot.runtime_authority_nonce_truth_convergence_v231_patch":
            calls.append("writer")
            return types.SimpleNamespace(
                _current_writer_authority_proof=lambda: (writer_ready, "writer")
            )
        if name == "bot.readiness_table":
            return table
        return original(name)

    monkeypatch.setattr(v133.importlib, "import_module", fake_import)
    return calls


def test_stop_active_blocks_repair_even_with_healthy_writer(monkeypatch):
    calls = _install_import_stubs(monkeypatch, stop_active=True)
    evidence = {"authority_ready": False, "execution_ready": False}
    assert v133._reconcile_current_authority_proof(evidence)["authority_ready"] is False
    assert calls == []


def test_stop_unknown_or_unavailable_blocks_authority_repair(monkeypatch):
    for stop in ("false", None, RuntimeError("stop reader unavailable")):
        with monkeypatch.context() as m:
            calls = _install_import_stubs(m, stop_active=stop)
            assert v133._reconcile_current_authority_proof(
                {"authority_ready": False}
            )["authority_ready"] is False
            assert calls == []


def test_writer_probe_requires_literal_true(monkeypatch):
    for result in (1, "true", {"ready": True}):
        with monkeypatch.context() as m:
            calls = _install_import_stubs(m, stop_active=False, writer_ready=result)
            assert v133._reconcile_current_authority_proof(
                {"authority_ready": False}
            )["authority_ready"] is False
            assert calls == ["writer"]


def test_valid_writer_and_independently_clear_stop_repair_authority(monkeypatch):
    calls = _install_import_stubs(monkeypatch, stop_active=False)
    observed = v133._reconcile_current_authority_proof(
        {"authority_ready": False, "execution_ready": False}
    )
    assert observed["authority_ready"] is True
    assert observed["execution_ready"] is False
    assert calls == ["writer"]


def test_truthy_non_boolean_execution_proof_is_revoked(monkeypatch):
    table = _Table()
    _install_import_stubs(monkeypatch, stop_active=False, table=table)
    facts = {key: True for key in v133._CRITICAL_KEYS}
    facts["execution_ready"] = "false"
    after, pending = v133._revoke_false_readiness(facts)
    assert after["execution_ready"] is False
    assert pending == ["execution_ready"]
    assert after["authority_ready"] is True


def test_unsuccessful_readiness_publisher_stays_pending(monkeypatch):
    table = _Table(refuse_ready=True)
    _install_import_stubs(monkeypatch, stop_active=False, table=table)
    facts = {key: True for key in v133._CRITICAL_KEYS}
    after, pending = v133._revoke_false_readiness(facts)
    assert after["execution_ready"] is False
    assert "execution_ready" in pending
    assert len(pending) == len(v133._CRITICAL_KEYS)
