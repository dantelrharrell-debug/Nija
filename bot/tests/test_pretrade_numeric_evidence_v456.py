"""Reject malformed numeric evidence without an unhandled exception."""
from bot.account_bound_pretrade_proof_v454 import CHECKS, assess


def records():
    return {k: {"verified": True, "account": "platform:kraken",
                "source": "verified_read_only", "observed_at": 1000.0}
            for k in CHECKS}


def test_huge_integer_timestamp_fails_closed():
    data = records()
    data["protective_exits"]["observed_at"] = 10 ** 1000
    result = assess(data, account="platform:kraken", now=1001.0)
    assert result.pretrade_checks_pass is False
    assert "protective_exits" in result.rejected
    assert result.can_submit_orders is False


def test_huge_clock_and_ttl_fail_closed():
    for kwargs in ({"now": 10 ** 1000}, {"now": 1001.0, "ttl_seconds": 10 ** 1000}):
        result = assess(records(), account="platform:kraken", **kwargs)
        assert result.pretrade_checks_pass is False
        assert "invalid_request_context" in result.rejected
        assert result.can_submit_orders is False
