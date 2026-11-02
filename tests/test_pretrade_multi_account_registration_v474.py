"""Fail-closed regression tests for the multi-account reviewed collector boundary."""
import importlib
import time

import pytest

from bot.pretrade_attestation_validation_v452 import (
    PROOF_BY_SOURCE, REQUIRED, SOURCES,
)
from bot import pretrade_independent_attestation as inspector

registration = importlib.import_module("bot.pretrade_multi_account_registration_v474")


def _observation(account, field, *, observed_at=None):
    source = SOURCES[field]
    return {
        "account": account,
        "verified": True,
        "read_only": True,
        "scope_verified": True,
        "source": source,
        "provider_id": "reviewed-" + field,
        "evidence_id": "evidence-" + account + "-" + field,
        "observed_at_epoch": time.time() if observed_at is None else observed_at,
        "provenance": {
            "account_scope_verified": True,
            "collector_identity_verified": True,
            "snapshot_complete": True,
            "complete_pagination_verified": True,
            PROOF_BY_SOURCE[source]: True,
        },
    }


def _providers(account="platform:kraken"):
    return {
        field: (lambda field=field: _observation(account, field))
        for field in REQUIRED
    }


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
        providers_by_account={
            "platform:kraken": _providers("platform:kraken"),
            "platform:okx": _providers("platform:okx"),
        },
        trusted_provider_ids=_identities(), independently_reviewed=True,
    )
    assert len(calls) == 1
    for account in ("platform:kraken", "platform:okx"):
        result = calls[0](account)
        assert result["source"] == "authenticated_independent"
        assert result["authorizes_orders"] is False
        assert set(result["checks"]) == set(REQUIRED)
        assert all(result["checks"].values())
    with pytest.raises(ValueError, match="unregistered_account_scope"):
        calls[0]("platform:coinbase")


def test_failed_evidence_preserves_the_installed_collector(monkeypatch):
    previous = lambda _account: {"previous": True}
    monkeypatch.setattr(inspector, "_COLLECTOR", previous)
    invalid = _providers()
    invalid["protective_exit_readback"] = lambda: _observation(
        "platform:kraken", "protective_exit_readback",
        observed_at=time.time() - 61,
    )

    with pytest.raises(ValueError, match="independent_pretrade_provenance_unverified"):
        registration.register_reviewed_account_registry(
            providers_by_account={"platform:kraken": invalid},
            trusted_provider_ids=_identities(), independently_reviewed=True,
        )

    assert inspector._COLLECTOR is previous


def test_empty_evidence_preserves_the_installed_collector(monkeypatch):
    previous = lambda _account: {"previous": True}
    monkeypatch.setattr(inspector, "_COLLECTOR", previous)
    empty = {field: (lambda: {}) for field in REQUIRED}

    with pytest.raises(ValueError, match="independent_pretrade_provenance_unverified"):
        registration.register_reviewed_account_registry(
            providers_by_account={"platform:kraken": empty},
            trusted_provider_ids=_identities(), independently_reviewed=True,
        )

    assert inspector._COLLECTOR is previous


def test_duplicate_provider_ids_fail_before_collector_replacement(monkeypatch):
    calls = []
    monkeypatch.setattr(registration, "install_authenticated_collector", calls.append)
    identities = _identities()
    identities["account_identity"] = identities["account_permissions"]

    with pytest.raises(ValueError, match="unique_complete_provider_registry_required"):
        registration.register_reviewed_account_registry(
            providers_by_account={"platform:kraken": _providers()},
            trusted_provider_ids=identities, independently_reviewed=True,
        )

    assert calls == []


@pytest.mark.parametrize("field", REQUIRED)
@pytest.mark.parametrize("defect", ["false", "stale", "wrong_account", "wrong_provider", "exception"])
def test_each_of_thirteen_fields_must_pass_before_install(monkeypatch, field, defect, caplog):
    previous = lambda _account: {"previous": True}
    monkeypatch.setattr(inspector, "_COLLECTOR", previous)
    providers = _providers()

    def rejected():
        row = _observation("platform:kraken", field)
        if defect == "false":
            row["verified"] = False
        elif defect == "stale":
            row["observed_at_epoch"] = time.time() - 61
        elif defect == "wrong_account":
            row["account"] = "user:someone_else:kraken"
        elif defect == "wrong_provider":
            row["provider_id"] = "not-reviewed"
        else:
            raise RuntimeError("secret-canary-never-serialize")
        return row

    providers[field] = rejected
    with pytest.raises(registration.IndependentEvidenceRejected) as exc:
        registration.register_reviewed_account_registry(
            providers_by_account={"platform:kraken": providers},
            trusted_provider_ids=_identities(), independently_reviewed=True,
        )
    assert exc.value.failed_fields == (field,)
    assert inspector._COLLECTOR is previous
    assert "collector_replaced=false" in caplog.text
    assert "secret-canary" not in caplog.text


def test_platform_registration_can_preserve_separate_reviewed_member_accounts(monkeypatch):
    monkeypatch.setattr(inspector, "_COLLECTOR", None)
    accounts = ("platform:kraken", "user:member:kraken", "platform:okx")
    registration.register_reviewed_account_registry(
        providers_by_account={account: _providers(account) for account in accounts},
        trusted_provider_ids=_identities(), independently_reviewed=True,
    )
    for account in accounts:
        report = inspector.inspect_authenticated_attestations(account)
        assert report["producer_status"] == "checks_passed_diagnostic_only"
        assert report["collector_installed"] is True
        assert report["authorizes_orders"] is False
    unknown = inspector.inspect_authenticated_attestations("user:unregistered:kraken")
    assert not any(unknown["checks"].values())
    assert unknown["authorizes_orders"] is False
