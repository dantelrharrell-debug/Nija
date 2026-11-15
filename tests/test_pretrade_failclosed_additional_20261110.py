"""Offline fail-closed tests; never contact a brokerage or authorize orders."""
from bot import pretrade_independent_attestation as attestation


def test_wrong_account_scope_fails(monkeypatch):
    monkeypatch.setattr(attestation, "_COLLECTOR", lambda account: {
        "account": "platform:other", "source": "authenticated_independent",
        "observed_at_epoch": 1000, "read_only": True, "scope_verified": True,
    })
    result = attestation.inspect_authenticated_attestations("platform:kraken", now=1000)
    assert result["authorizes_orders"] is False
    assert all(v is False for v in result["checks"].values())


def test_future_observation_fails(monkeypatch):
    monkeypatch.setattr(attestation, "_COLLECTOR", lambda account: {
        "account": account, "observed_at_epoch": 2000,
    })
    result = attestation.inspect_authenticated_attestations("platform:kraken", now=1000)
    assert result["producer_status"] == "observation_missing_future_or_stale"
    assert result["authorizes_orders"] is False


def test_collector_exception_fails(monkeypatch):
    def broken(_account):
        raise RuntimeError("private read unavailable")
    monkeypatch.setattr(attestation, "_COLLECTOR", broken)
    result = attestation.inspect_authenticated_attestations("platform:kraken", now=1000)
    assert result["producer_status"] == "collector_exception"
    assert result["authorizes_orders"] is False
    assert all(v is False for v in result["checks"].values())
