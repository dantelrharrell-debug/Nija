"""Fail-closed regression tests for the multi-account reviewed collector boundary."""
import importlib

import pytest

from bot.pretrade_attestation_validation_v452 import REQUIRED

registration = importlib.import_module("bot.pretrade_multi_account_registration_v474")


def _providers():
    return {field: (lambda: {}) for field in REQUIRED}


def _identities():
    return {field: "reviewed-" + field for field in REQUIRED}


def test_requires_review(monkeypatch):
    calls = []
    monkeypatch.setattr(registration, "install_authenticated_collector", calls.append)
    with pytest.raises(PermissionError, match="independent_provider_review_required"):
        registration.register_reviewed_account_registry(
            providers_by_account={"platform:kraken": _providers()},
            trusted_provider_ids=_identities(),
        )
    assert calls == []


def test_partial_second_account_does_not_install(monkeypatch):
    calls = []
    monkeypatch.setattr(registration, "install_authenticated_collector", calls.append)
    partial = _providers()
    partial.pop(REQUIRED[0])
    with pytest.raises(ValueError, match="complete_provider_registry_required"):
        registration.register_reviewed_account_registry(
            providers_by_account={"platform:kraken": _providers(), "platform:okx": partial},
            trusted_provider_ids=_identities(), independently_reviewed=True,
        )
    assert calls == []


def test_invalid_scope_does_not_install(monkeypatch):
    calls = []
    monkeypatch.setattr(registration, "install_authenticated_collector", calls.append)
    with pytest.raises(ValueError, match="audited_account_scope_invalid"):
        registration.register_reviewed_account_registry(
            providers_by_account={"platform:kraken": _providers(), "platform:unknown": _providers()},
            trusted_provider_ids=_identities(), independently_reviewed=True,
        )
    assert calls == []


def test_cross_authority_reuse_does_not_install(monkeypatch):
    calls = []
    monkeypatch.setattr(registration, "install_authenticated_collector", calls.append)
    identities = _identities()
    identities["writer_lease"] = identities["account_identity"]
    with pytest.raises(ValueError, match="cross_authority_provider_identity_reuse"):
        registration.register_reviewed_account_registry(
            providers_by_account={"platform:kraken": _providers()},
            trusted_provider_ids=identities, independently_reviewed=True,
        )
    assert calls == []


def test_complete_registry_installs_once_and_never_authorizes_orders(monkeypatch):
    calls = []
    monkeypatch.setattr(registration, "install_authenticated_collector", calls.append)
    registration.register_reviewed_account_registry(
        providers_by_account={"platform:kraken": _providers(), "platform:okx": _providers()},
        trusted_provider_ids=_identities(), independently_reviewed=True,
    )
    assert len(calls) == 1
    for account in ("platform:kraken", "platform:okx"):
        with pytest.raises(ValueError, match="independent_pretrade_provenance_unverified"):
            calls[0](account)
    with pytest.raises(ValueError, match="unregistered_account_scope"):
        calls[0]("platform:coinbase")
