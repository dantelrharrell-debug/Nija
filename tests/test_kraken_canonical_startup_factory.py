"""Synthetic source owners/signers; never live certification or broker evidence."""
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from test_kraken_startup_receipts import fixture  # noqa: F401 -- shared synthetic signing fixture
from bot import kraken_canonical_startup_factory as root
from bot import kraken_startup_evidence_binding as startup
from bot import pretrade_independent_attestation as attestation
from bot.kraken_six_source_binding_contract_v490 import EXPECTED_OWNERS
from bot.pretrade_attestation_validation_v452 import REQUIRED


@pytest.fixture
def wiring(fixture, monkeypatch):
    binding = fixture.binding
    private_call = Mock(side_effect=AssertionError("offline test must not call exchange"))
    monkeypatch.setattr(type(binding.broker), "_kraken_private_call", private_call, raising=False)
    sources = root.ReviewedCanonicalKrakenSources(
        manager=binding.manager, strategy=binding.strategy, broker=binding.broker,
        independent_open_intents=Mock(side_effect=AssertionError("no ledger read at construction")),
        independent_positions=Mock(side_effect=AssertionError("no ledger read at construction")),
        independent_remaining={field: binding.providers[field] for field in EXPECTED_OWNERS},
        reviewed_source_owners=dict(EXPECTED_OWNERS), monitoring_category=object(), receipts=binding.receipts,
    )
    return SimpleNamespace(
        signed=fixture, sources=sources, resolve=Mock(return_value=sources), review=Mock(return_value=True),
        private_call=private_call,
    )


def factory(wiring):
    return root.make_canonical_kraken_startup_factory(
        trust=wiring.signed.trust, resolve_sources=wiring.resolve, review_sources=wiring.review,
    )


def invoke(wiring):
    return factory(wiring)(manager=wiring.sources.manager, strategy=wiring.sources.strategy)


def test_real_provider_construction_binds_all_thirteen_without_io_or_install(wiring):
    binding = invoke(wiring)
    assert set(binding.providers) == set(REQUIRED)
    assert len({id(p) for p in binding.providers.values()}) == 13
    assert binding.manager is wiring.sources.manager
    assert binding.strategy is wiring.sources.strategy
    assert binding.broker is wiring.sources.broker
    assert dict(binding.reviewed_provider_ids) == dict(wiring.signed.trust.reviewed_provider_ids)
    for field in EXPECTED_OWNERS:
        assert binding.providers[field] is wiring.sources.independent_remaining[field]
    wiring.private_call.assert_not_called()
    wiring.sources.independent_open_intents.assert_not_called()
    wiring.sources.independent_positions.assert_not_called()
    wiring.review.assert_called_with(wiring.sources)
    assert attestation._COLLECTOR is None


@pytest.mark.parametrize("field", tuple(EXPECTED_OWNERS))
def test_each_missing_independent_source_denies_before_composition(wiring, monkeypatch, field):
    remaining = dict(wiring.sources.independent_remaining)
    remaining.pop(field)
    wiring.resolve.return_value = replace(wiring.sources, independent_remaining=remaining)
    compose = Mock()
    monkeypatch.setattr(root, "compose_authenticated_kraken_collector_sources", compose)
    with pytest.raises(root.CanonicalKrakenStartupDenied):
        invoke(wiring)
    compose.assert_not_called()
    wiring.private_call.assert_not_called()


@pytest.mark.parametrize("field", ("manager", "strategy", "broker"))
def test_foreign_object_owner_denies_before_composition(wiring, monkeypatch, field):
    wiring.resolve.return_value = replace(wiring.sources, **{field: object()})
    compose = Mock()
    monkeypatch.setattr(root, "compose_authenticated_kraken_collector_sources", compose)
    with pytest.raises(root.CanonicalKrakenStartupDenied):
        invoke(wiring)
    compose.assert_not_called()


@pytest.mark.parametrize("result", (False, None, 1, "true"))
def test_review_must_be_literal_true(wiring, monkeypatch, result):
    wiring.review.return_value = result
    compose = Mock()
    monkeypatch.setattr(root, "compose_authenticated_kraken_collector_sources", compose)
    with pytest.raises(root.CanonicalKrakenStartupDenied):
        invoke(wiring)
    compose.assert_not_called()


def test_changed_broker_or_review_during_composition_denies(wiring):
    wiring.review.side_effect = [True, False]
    with pytest.raises(root.CanonicalKrakenStartupDenied):
        invoke(wiring)
    assert attestation._COLLECTOR is None


def test_broker_replacement_after_review_denies(wiring):
    def review(sources):
        if wiring.review.call_count == 2:
            sources.manager.platform_brokers["kraken"] = type(sources.broker)()
        return True
    wiring.review.side_effect = review
    # Recheck the owner after the final review callback, even when the old
    # broker remains connected.
    with pytest.raises(root.CanonicalKrakenStartupDenied):
        invoke(wiring)
    assert attestation._COLLECTOR is None


@pytest.mark.parametrize("mode", ("missing", "disconnected", "foreign", "member", "duplicate"))
def test_wrong_canonical_broker_denies_before_resolution(wiring, mode):
    manager = wiring.sources.manager
    broker = wiring.sources.broker
    if mode == "missing":
        manager.platform_brokers = {}
    elif mode == "disconnected":
        broker.connected = False
    elif mode == "foreign":
        manager.platform_brokers = {"kraken": object()}
    elif mode == "member":
        broker.account_type, broker.user_id = "user", "synthetic-member"
    else:
        class Alias:
            value = "kraken"
        manager.platform_brokers[Alias()] = broker
    with pytest.raises(root.CanonicalKrakenStartupDenied):
        invoke(wiring)
    wiring.resolve.assert_not_called()


def test_source_and_receipt_maps_are_copied_and_frozen(wiring):
    original = dict(wiring.sources.receipts)
    changed = replace(wiring.sources, receipts=original)
    original.clear()
    assert set(changed.receipts) == startup.RECEIPTS
    for mapping in (changed.receipts, changed.independent_remaining, changed.reviewed_source_owners):
        with pytest.raises(TypeError):
            mapping["synthetic"] = "mutation"


def test_resolver_errors_do_not_disclose_private_payload(wiring, capsys):
    canary = "synthetic-private-resolver-error"
    wiring.resolve.side_effect = ValueError(canary)
    with pytest.raises(root.CanonicalKrakenStartupDenied) as caught:
        invoke(wiring)
    assert canary not in str(caught.value) + repr(caught.value) + capsys.readouterr().out
    assert caught.value.__suppress_context__ is True
    assert canary not in repr(wiring.sources)


def test_authenticated_registration_and_real_atomic_install_are_non_authorizing(wiring, monkeypatch):
    # Synthetic provider bodies isolate startup/receipt/atomic installation.
    # The separate first test exercises real provider construction.
    monkeypatch.setattr(root, "compose_authenticated_kraken_collector_sources",
                        Mock(return_value=wiring.signed.binding.providers))
    root.register_canonical_kraken_collector_startup(
        trust=wiring.signed.trust, resolve_sources=wiring.resolve, review_sources=wiring.review,
        clock=lambda: wiring.signed.now,
    )
    wiring.resolve.assert_not_called()
    assert startup.install_from_canonical_startup(wiring.sources.manager, wiring.sources.strategy) == (
        "diagnostic_collector_installed"
    )
    report = attestation.inspect_authenticated_attestations("platform:kraken")
    assert all(report["checks"].values())
    assert report["authorizes_orders"] is False


def test_untrusted_receipts_do_not_sample_sources_or_replace_collector(wiring, monkeypatch):
    sampled = Mock()
    monkeypatch.setattr(root, "compose_authenticated_kraken_collector_sources",
                        Mock(return_value={field: sampled for field in REQUIRED}))
    wiring.resolve.return_value = replace(
        wiring.sources, receipts={kind: "untrusted-synthetic" for kind in startup.RECEIPTS},
    )
    sentinel = object()
    monkeypatch.setattr(attestation, "_COLLECTOR", sentinel)
    root.register_canonical_kraken_collector_startup(
        trust=wiring.signed.trust, resolve_sources=wiring.resolve, review_sources=wiring.review,
        clock=lambda: wiring.signed.now,
    )
    assert startup.install_from_canonical_startup(wiring.sources.manager, wiring.sources.strategy) == (
        "authenticated_release_receipts_required"
    )
    sampled.assert_not_called()
    assert attestation._COLLECTOR is sentinel
