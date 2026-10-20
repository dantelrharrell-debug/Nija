from bot.pretrade_authenticated_provider_adapter_v453 import collect_independent_pretrade_evidence
from bot.pretrade_attestation_validation_v452 import REQUIRED


def test_missing_producers_fail_closed():
    result = collect_independent_pretrade_evidence({}, now_epoch=1000.0)
    assert not result["certificate"]["certified"]
    assert set(result["provider_errors"]) == set(REQUIRED)
    assert result["activation_allowed"] is False


def test_provider_errors_are_fail_closed():
    def broken():
        raise RuntimeError("private api unavailable")
    result = collect_independent_pretrade_evidence(
        {"account_identity": broken}, now_epoch=1000.0
    )
    assert result["provider_errors"]["account_identity"] == "provider_exception:RuntimeError"
    assert not result["certificate"]["certified"]


def test_healthy_injected_providers_are_still_non_authorizing():
    providers = {
        name: (lambda: {"verified": True, "source": "authenticated_broker",
                        "observed_at_epoch": 1000.0})
        for name in REQUIRED
    }
    result = collect_independent_pretrade_evidence(providers, now_epoch=1000.0)
    assert result["certificate"]["certified"] is True
    assert result["certificate"]["authorizes_orders"] is False
    assert result["activation_allowed"] is False
