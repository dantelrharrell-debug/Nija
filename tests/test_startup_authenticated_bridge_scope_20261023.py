"""Regression coverage for strict pretrade diagnostic account scope."""
from bot.startup_authenticated_bridge_v456 import evaluate_authenticated_startup_candidate


def test_whitespace_account_scope_is_denied_without_collector():
    for account in ("platform: kraken", "platform:\tkraken", "platform:\nkraken"):
        result = evaluate_authenticated_startup_candidate(
            account, {}, pending_execution=False, posttrade_verified=False,
        )
        assert result["activation_allowed"] is False
        assert result["pretrade_candidate_ready"] is False
        assert result["account_scope"] is None
        assert "authenticated_pretrade_certificate" in result["missing"]


def test_no_external_facts_do_not_authorize_valid_scope():
    result = evaluate_authenticated_startup_candidate(
        "platform:kraken", {}, pending_execution=False, posttrade_verified=False,
    )
    assert result["diagnostic_only"] is True
    assert result["activation_allowed"] is False
    assert result["pretrade_candidate_ready"] is False
