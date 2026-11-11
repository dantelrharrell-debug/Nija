"""Read-only attestation denial matrix; no broker I/O or order submission."""
from bot import pretrade_independent_attestation as attestation


def test_invalid_account_scopes_are_denied(monkeypatch):
    monkeypatch.setattr(attestation, "_COLLECTOR", lambda _: (_ for _ in ()).throw(
        AssertionError("collector must not run for invalid account")))
    for account in (None, "", " platform:kraken", "platform:kraken ", "platform: kraken"):
        result = attestation.inspect_authenticated_attestations(account, now=1000)
        assert result["producer_status"] == "account_scope_invalid"
        assert result["authorizes_orders"] is False
        assert all(value is False for value in result["checks"].values())


def test_stale_and_future_observations_denied(monkeypatch):
    for observed in (900, 1001):
        monkeypatch.setattr(attestation, "_COLLECTOR", lambda account: {
            "account": account, "observed_at_epoch": observed,
        })
        result = attestation.inspect_authenticated_attestations("platform:kraken", now=1000)
        assert result["producer_status"] == "observation_missing_future_or_stale"
        assert result["authorizes_orders"] is False


def test_untrusted_source_denied(monkeypatch):
    monkeypatch.setattr(attestation, "_COLLECTOR", lambda account: {
        "account": account, "observed_at_epoch": 1000,
        "source": "local_synthetic", "read_only": True, "scope_verified": True,
    })
    result = attestation.inspect_authenticated_attestations("platform:kraken", now=1000)
    assert result["authorizes_orders"] is False
    assert all(value is False for value in result["checks"].values())
