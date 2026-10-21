from bot.pretrade_authenticated_provider_adapter_v453 import collect_independent_pretrade_evidence
from bot.pretrade_attestation_validation_v452 import REQUIRED, SOURCES, PROOF_BY_SOURCE

ACCOUNT = "platform:kraken"
TRUSTED = {name: "trusted-" + SOURCES[name] for name in REQUIRED}


def test_missing_producers_fail_closed():
    result = collect_independent_pretrade_evidence(
        {}, account=ACCOUNT, trusted_provider_ids=TRUSTED, now_epoch=1000,
    )
    assert not result["certificate"]["certified"]
    assert set(result["provider_errors"]) == set(REQUIRED)
    assert result["activation_allowed"] is False


def test_provider_errors_are_fail_closed():
    def broken():
        raise RuntimeError("private api unavailable")
    result = collect_independent_pretrade_evidence(
        {"account_identity": broken},
        account=ACCOUNT, trusted_provider_ids=TRUSTED, now_epoch=1000,
    )
    assert result["provider_errors"]["account_identity"] == "provider_exception:RuntimeError"
    assert not result["certificate"]["certified"]


def test_self_reported_success_is_not_certification():
    providers = {
        name: lambda: {"verified": True, "source": "authenticated_broker",
                      "observed_at_epoch": 1000.0}
        for name in REQUIRED
    }
    result = collect_independent_pretrade_evidence(
        providers, account=ACCOUNT, trusted_provider_ids=TRUSTED, now_epoch=1000,
    )
    assert not result["certificate"]["certified"]
    assert result["activation_allowed"] is False


def test_independently_bound_read_only_diagnostics_never_authorize():
    def make(field):
        source = SOURCES[field]
        return {
            "account": ACCOUNT, "verified": True, "read_only": True,
            "scope_verified": True, "source": source,
            "provider_id": TRUSTED[field], "evidence_id": "read-" + field,
            "observed_at_epoch": 1000.0,
            "provenance": {
                "account_scope_verified": True,
                "collector_identity_verified": True,
                "snapshot_complete": True,
                "complete_pagination_verified": True,
                PROOF_BY_SOURCE[source]: True,
            },
        }
    providers = {field: (lambda f=field: make(f)) for field in REQUIRED}
    result = collect_independent_pretrade_evidence(
        providers, account=ACCOUNT, trusted_provider_ids=TRUSTED, now_epoch=1000,
    )
    assert result["certificate"]["certified"] is True
    assert result["certificate"]["authorizes_orders"] is False
    assert result["activation_allowed"] is False
    assert result["read_only"] is True
