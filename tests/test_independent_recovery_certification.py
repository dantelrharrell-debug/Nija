"""A fresh execution proof cannot substitute for independent safety evidence."""
from __future__ import annotations

import pytest

from bot.startup_recovery_readonly import classify_observed_snapshot


READINESS = dict.fromkeys((
    "broker_connected", "authority_ready", "capital_ready", "risk_ready",
    "strategy_ready", "nonce_ready", "position_sync_ready", "execution_ready",
), True)
ATTESTATIONS = dict.fromkeys((
    "kill_switch_clear", "startup_attempts_reconciled",
    "protective_exits_verified", "ledger_reconciled",
), True)


@pytest.mark.parametrize("key,reason", [
    ("kill_switch_clear", "kill_switch"), ("startup_attempts_reconciled", "startup_attempts"),
    ("protective_exits_verified", "protective_exits"), ("ledger_reconciled", "ledger"),
])
@pytest.mark.parametrize("unproven", [False, None, "false", "true", 1, {}, {"verified": True}])
def test_every_independent_attestation_requires_literal_true(key, reason, unproven):
    decision = classify_observed_snapshot(READINESS, **{**ATTESTATIONS, key: unproven})
    assert decision.state == "READ_ONLY_RECOVERY"
    assert decision.reasons == (reason,)
    assert decision.allow_new_orders is False


def test_defaults_keep_exits_and_ledger_uncertified_despite_fresh_execution():
    decision = classify_observed_snapshot(READINESS)
    assert "protective_exits" in decision.reasons
    assert "ledger" in decision.reasons
    assert decision.allow_new_orders is False


def test_even_complete_diagnostics_never_authorize_or_start_observation():
    decision = classify_observed_snapshot(READINESS, **ATTESTATIONS)
    assert decision.state == "VERIFICATION_COMPLETE"
    assert decision.reasons == ()
    assert decision.allow_new_orders is False
