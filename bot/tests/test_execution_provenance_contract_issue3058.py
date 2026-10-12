"""Regression checks for the current v169/v402 execution-proof source contract.

These deliberately do NOT grant trading authority. They expose the current
canonical-confirmed-fill policy mismatch for review before any repair.
"""
from bot.runtime_execution_capital_integrity_v169_patch import _execution_provenance_valid


def test_heartbeat_execution_provenance_remains_valid():
    allowed, detail = _execution_provenance_valid(
        {"source": "heartbeat_trade", "proof_kind": "execution_probe"},
        "ORDER_VERIFY",
    )
    assert allowed, detail


def test_canonical_confirmed_fill_is_not_silently_authorized():
    # The preactivation collector contains a canonical fill path, but the v169
    # guard currently expects heartbeat_trade. Keep this fail-closed until
    # independent broker-fill provenance validation is implemented and tested.
    allowed, detail = _execution_provenance_valid(
        {"source": "canonical_confirmed_fill", "proof_kind": "execution_probe"},
        "FILL_VERIFY",
    )
    assert not allowed
    assert "execution_proof_source_invalid" in detail


def test_authority_heartbeat_cannot_masquerade_as_order_proof():
    allowed, _ = _execution_provenance_valid(
        {"source": "authority_heartbeat", "proof_kind": "authority_liveness"},
        "ORDER_VERIFY",
    )
    assert not allowed


def test_wrong_proof_kind_is_rejected_even_with_valid_source():
    allowed, _ = _execution_provenance_valid(
        {"source": "heartbeat_trade", "proof_kind": "authority_liveness"},
        "FILL_VERIFY",
    )
    assert not allowed
