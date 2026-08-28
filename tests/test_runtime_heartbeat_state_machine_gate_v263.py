from types import SimpleNamespace

import bot.runtime_heartbeat_state_machine_gate_v263_patch as v263


def _pending_result():
    return SimpleNamespace(
        error="Execution gate pending (state_machine=LIVE_PENDING_CONFIRMATION)"
    )


def test_v263_leaves_non_state_machine_denials_unchanged(monkeypatch):
    denial = SimpleNamespace(error="PreTradeRiskEngine reject: risk_limit")

    def original(_self, _request, _t_start):
        return denial

    monkeypatch.setattr(
        v263,
        "_verified_startup_probe",
        lambda: (True, "HEARTBEAT_TRADE"),
    )
    wrapped = v263._wrap_gate(original, "test.execution_pipeline")

    assert wrapped(object(), object(), 0.0) is denial


def test_v263_leaves_pending_gate_closed_without_verified_probe(monkeypatch):
    denial = _pending_result()

    def original(_self, _request, _t_start):
        return denial

    monkeypatch.setattr(
        v263,
        "_verified_startup_probe",
        lambda: (False, "startup_probe_denied"),
    )
    wrapped = v263._wrap_gate(original, "test.execution_pipeline")

    assert wrapped(object(), object(), 0.0) is denial


def test_v263_allows_only_verified_heartbeat_past_pending_state_gate(monkeypatch):
    denial = _pending_result()

    def original(_self, _request, _t_start):
        return denial

    monkeypatch.setattr(
        v263,
        "_verified_startup_probe",
        lambda: (True, "HEARTBEAT_TRADE"),
    )
    wrapped = v263._wrap_gate(original, "test.execution_pipeline")

    # Returning None means only this pipeline gate continues. Downstream risk,
    # ECEL, broker, acknowledgement and fill gates still run normally.
    assert wrapped(object(), object(), 0.0) is None


def test_v263_recognizes_only_pipeline_state_machine_pending_denial():
    assert v263._is_state_machine_pending_denial(_pending_result()) is True
    assert (
        v263._is_state_machine_pending_denial(
            SimpleNamespace(error="Execution gate blocked: safety_controller unavailable")
        )
        is False
    )
    assert v263._is_state_machine_pending_denial(None) is False
