"""Tests for fresh account-bound pretrade evidence, no trade authorization."""
from bot.account_bound_pretrade_proof_v454 import CHECKS, assess


def good():
    return {key: {"verified": True, "account": "platform:kraken",
                  "source": "account_authenticated", "observed_at": 1000.0}
            for key in CHECKS}


def test_idle_account_can_pass_observation_without_recent_trade():
    outcome = assess(good(), account="platform:kraken", now=1001.0)
    assert outcome.pretrade_checks_pass
    assert not outcome.can_submit_orders


def test_stale_wrong_account_and_missing_protection_fail():
    facts = good()
    facts["protective_exits"]["observed_at"] = 800.0
    facts["ledger_restore"]["account"] = "another-account"
    del facts["writer_lease"]
    result = assess(facts, account="platform:kraken", now=1001.0)
    assert not result.pretrade_checks_pass
    assert "protective_exits" in result.rejected
    assert "ledger_restore" in result.rejected
    assert "writer_lease" in result.missing
    assert not result.can_submit_orders


def test_missing_context_fails_closed():
    result = assess(good(), account="", now=float("nan"))
    assert not result.pretrade_checks_pass
    assert "invalid_request_context" in result.rejected
    assert not result.can_submit_orders


def test_false_claims_are_not_accepted():
    facts = good()
    facts["emergency_stop_clear"]["verified"] = "true"
    result = assess(facts, account="platform:kraken", now=1001.0)
    assert not result.pretrade_checks_pass
    assert "emergency_stop_clear" in result.rejected
