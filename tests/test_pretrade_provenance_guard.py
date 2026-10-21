from bot import pretrade_independent_attestation as att


def test_claimed_authentication_without_verified_provenance_fails_closed(monkeypatch):
    payload = {
        "account": "kraken:platform",
        "source": "authenticated_independent",
        "read_only": True,
        "scope_verified": True,
        "observed_at_epoch": 1000,
        "checks": {key: True for key in att.FIELDS},
    }
    monkeypatch.setattr(att, "_COLLECTOR", lambda account: payload)
    assert not any(att.current_authenticated_attestations("kraken:platform", now=1001).values())


def test_incomplete_pagination_rejects_pretrade_certificate(monkeypatch):
    payload = {
        "account": "kraken:platform",
        "source": "authenticated_independent",
        "read_only": True,
        "scope_verified": True,
        "observed_at_epoch": 1000,
        "checks": {key: True for key in att.FIELDS},
        "provenance": {
            "authenticated_broker_read_verified": True,
            "ledger_snapshot_verified": True,
            "complete_pagination_verified": False,
            "collector_identity_verified": True,
            "account_scope_verified": True,
        },
    }
    monkeypatch.setattr(att, "_COLLECTOR", lambda account: payload)
    assert not any(att.current_authenticated_attestations("kraken:platform", now=1001).values())
