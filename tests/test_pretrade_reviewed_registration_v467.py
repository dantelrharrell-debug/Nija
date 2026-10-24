"""Offline fail-closed tests for explicit reviewed collector registration."""
import pytest

from bot.pretrade_attestation_validation_v452 import REQUIRED
from bot.pretrade_reviewed_registration_v467 import register_reviewed_pretrade_providers


def _providers():
    return {field: (lambda: {}) for field in REQUIRED}


def _identities():
    return {field: "reviewed-provider-" + field for field in REQUIRED}


def test_review_required_before_install(monkeypatch):
    called = []
    monkeypatch.setattr(
        "bot.pretrade_reviewed_registration_v467.install_audited_collector",
        lambda *args, **kwargs: called.append((args, kwargs)),
    )
    with pytest.raises(PermissionError, match="independent_provider_review_required"):
        register_reviewed_pretrade_providers(
            account_scope="platform:kraken",
            providers=_providers(),
            trusted_provider_ids=_identities(),
        )
    assert called == []


@pytest.mark.parametrize("scope", ["", "platform:kraken ", "platform:unknown", "user::kraken"])
def test_invalid_account_scope_rejected_by_v465(monkeypatch, scope):
    # Real v465 scope validation, not a simulated provider acceptance.
    with pytest.raises(ValueError):
        register_reviewed_pretrade_providers(
            account_scope=scope,
            providers=_providers(),
            trusted_provider_ids=_identities(),
            independently_reviewed=True,
        )


def test_missing_provider_rejected(monkeypatch):
    called = []
    monkeypatch.setattr(
        "bot.pretrade_reviewed_registration_v467.install_audited_collector",
        lambda *args, **kwargs: called.append((args, kwargs)),
    )
    providers = _providers()
    providers.pop(REQUIRED[0])
    with pytest.raises(ValueError, match="complete_provider_registry_required"):
        register_reviewed_pretrade_providers(
            account_scope="platform:kraken", providers=providers,
            trusted_provider_ids=_identities(), independently_reviewed=True,
        )
    assert called == []


def test_missing_trusted_identity_rejected(monkeypatch):
    called = []
    monkeypatch.setattr(
        "bot.pretrade_reviewed_registration_v467.install_audited_collector",
        lambda *args, **kwargs: called.append((args, kwargs)),
    )
    identities = _identities()
    identities.pop(REQUIRED[0])
    with pytest.raises(ValueError, match="complete_trusted_provider_registry_required"):
        register_reviewed_pretrade_providers(
            account_scope="platform:kraken", providers=_providers(),
            trusted_provider_ids=identities, independently_reviewed=True,
        )
    assert called == []


def test_cross_authority_provider_reuse_rejected():
    identities = _identities()
    identities["account_permissions"] = identities["writer_lease"]
    with pytest.raises(ValueError, match="cross_authority_provider_identity_reuse"):
        register_reviewed_pretrade_providers(
            account_scope="platform:kraken", providers=_providers(),
            trusted_provider_ids=identities, independently_reviewed=True,
        )


def test_valid_registration_is_diagnostic_only(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "bot.pretrade_reviewed_registration_v467.install_audited_collector",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    register_reviewed_pretrade_providers(
        account_scope="platform:kraken", providers=_providers(),
        trusted_provider_ids=_identities(), independently_reviewed=True,
    )
    assert len(calls) == 1
    assert set(calls[0][0][0]) == {"platform:kraken"}
    assert set(calls[0][1]["trusted_provider_ids"]) == set(REQUIRED)
