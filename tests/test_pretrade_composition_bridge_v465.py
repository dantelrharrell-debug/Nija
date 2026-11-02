"""Synthetic offline regressions for v465; never live brokerage evidence."""
import copy
import time

import pytest

from bot import pretrade_composition_bridge_v465 as bridge
from bot import pretrade_independent_attestation as inspector
from bot.pretrade_attestation_validation_v452 import REQUIRED, SOURCES, PROOF_BY_SOURCE


ACCOUNT = "platform:kraken"


def fixture_registry(account=ACCOUNT, now=None):
    now = time.time() if now is None else now
    trusted = {field: "provider-" + field for field in REQUIRED}
    observations = {}
    providers = {}
    for field in REQUIRED:
        source = SOURCES[field]
        observation = {
            "account": account,
            "verified": True,
            "read_only": True,
            "scope_verified": True,
            "source": source,
            "provider_id": trusted[field],
            "evidence_id": "real-receipt-" + field,
            "observed_at_epoch": now,
            "provenance": {
                "account_scope_verified": True,
                "collector_identity_verified": True,
                "snapshot_complete": True,
                PROOF_BY_SOURCE[source]: True,
                "complete_pagination_verified": True,
            },
        }
        observations[field] = observation
        providers[field] = lambda row=observation: copy.deepcopy(row)
    return trusted, observations, providers


def test_full_independent_evidence_bridge_remains_non_authorizing(monkeypatch):
    trusted, _, providers = fixture_registry()
    collector = bridge.make_collector({ACCOUNT: providers}, trusted_provider_ids=trusted)
    evidence = collector(ACCOUNT)
    assert evidence["source"] == "authenticated_independent"
    assert set(evidence["checks"]) == set(REQUIRED)
    assert all(evidence["checks"].values())
    assert evidence["authorizes_orders"] is False
    monkeypatch.setattr(inspector, "_COLLECTOR", collector)
    output = inspector.inspect_authenticated_attestations(ACCOUNT)
    assert output["producer_status"] == "checks_passed_diagnostic_only"
    assert output["authorizes_orders"] is False
    assert set(output["checks"]) == set(REQUIRED)
    assert all(output["checks"].values())


def test_registry_requires_every_field_and_unique_authority_class():
    trusted, _, providers = fixture_registry()
    with pytest.raises(ValueError, match="audited_providers_incomplete"):
        bridge.make_collector({ACCOUNT: dict(list(providers.items())[:-1])}, trusted_provider_ids=trusted)
    with pytest.raises(ValueError, match="trusted_provider_registry_incomplete"):
        bridge.make_collector({ACCOUNT: providers}, trusted_provider_ids={})
    trusted["writer_lease"] = trusted["account_identity"]
    with pytest.raises(ValueError, match="cross_authority"):
        bridge.make_collector({ACCOUNT: providers}, trusted_provider_ids=trusted)


def test_no_account_fallback():
    trusted, _, providers = fixture_registry()
    collector = bridge.make_collector({ACCOUNT: providers}, trusted_provider_ids=trusted)
    for name in ("user:other:kraken", "platform:coinbase", "platform:kraken ", "", None):
        with pytest.raises(ValueError, match="unregistered_account_scope"):
            collector(name)


@pytest.mark.parametrize("field,selector,value", [
    ("account_identity", "account", "platform:coinbase"),
    ("broker_balances", "verified", "true"),
    ("protective_exit_readback", "source", "risk_governor"),
    ("position_ledger_reconciliation", "read_only", False),
    ("writer_lease", "provider_id", "caller-injected"),
    ("operator_authorization", "observed_at_epoch", 1.0),
    ("open_order_reconciliation", "scope_verified", None),
])
def test_any_missing_or_untrusted_field_rejected(field, selector, value):
    trusted, observations, providers = fixture_registry()
    observations[field][selector] = value
    collector = bridge.make_collector({ACCOUNT: providers}, trusted_provider_ids=trusted)
    with pytest.raises(ValueError, match="independent_pretrade_provenance_unverified"):
        collector(ACCOUNT)


def test_missing_complete_pagination_denied():
    trusted, observations, providers = fixture_registry()
    observations["open_order_reconciliation"]["provenance"]["complete_pagination_verified"] = False
    collector = bridge.make_collector({ACCOUNT: providers}, trusted_provider_ids=trusted)
    with pytest.raises(ValueError, match="independent_pretrade_provenance_unverified"):
        collector(ACCOUNT)


def test_failed_provider_does_not_install_authority(monkeypatch):
    trusted, _, providers = fixture_registry()
    def fail():
        raise RuntimeError("secret-canary-do-not-log")
    providers["broker_balances"] = fail
    collector = bridge.make_collector({ACCOUNT: providers}, trusted_provider_ids=trusted)
    with pytest.raises(ValueError, match="independent_pretrade_provenance_unverified") as exc:
        collector(ACCOUNT)
    assert "secret-canary" not in str(exc.value)
    monkeypatch.setattr(inspector, "_COLLECTOR", collector)
    output = inspector.inspect_authenticated_attestations(ACCOUNT)
    assert output["producer_status"] == "independent_evidence_rejected"
    assert output["failed_fields"] == ["broker_balances"]
    assert "secret-canary" not in str(output)
    assert not any(output["checks"].values())


def test_install_is_explicit_not_at_import_time(monkeypatch):
    monkeypatch.setattr(inspector, "_COLLECTOR", None)
    assert inspector.inspect_authenticated_attestations(ACCOUNT)["collector_installed"] is False
    trusted, _, providers = fixture_registry()
    bridge.install_audited_collector({ACCOUNT: providers}, trusted_provider_ids=trusted)
    assert inspector.inspect_authenticated_attestations(ACCOUNT)["collector_installed"] is True
    assert inspector.inspect_authenticated_attestations(ACCOUNT)["authorizes_orders"] is False


def test_bad_scope_rejected_before_provider_read():
    trusted, _, providers = fixture_registry()
    for scope in ("platform:other", "platform:kraken:", "user::kraken", "user: x:kraken", "platform:kraken\n"):
        with pytest.raises(ValueError, match="audited_account_scope_invalid"):
            bridge.make_collector({scope: providers}, trusted_provider_ids=trusted)


def test_observations_taken_during_provider_calls_are_not_rejected_as_future():
    trusted, observations, providers = fixture_registry()
    providers["account_identity"] = lambda: {**observations["account_identity"], "observed_at_epoch": time.time()}
    collector = bridge.make_collector({ACCOUNT: providers}, trusted_provider_ids=trusted)
    assert collector(ACCOUNT)["checks"]["account_identity"] is True
