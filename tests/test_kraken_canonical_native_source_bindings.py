"""Synthetic owners/signers only; construct real readers without broker access."""
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from test_kraken_startup_receipts import fixture  # noqa: F401 -- shared synthetic signers
from test_kraken_canonical_startup_factory import wiring  # noqa: F401 -- shared canonical owners
from test_kraken_protected_startup_root import protected  # noqa: F401 -- signed private-file fixture
from bot import kraken_canonical_startup_factory as root
from bot import kraken_collector_composition_v487 as composition
from bot import kraken_protected_startup_root as protected_root
from bot import kraken_startup_evidence_binding as startup
from bot import pretrade_independent_attestation as attestation
from bot.kraken_kill_switch_evidence import ReviewedKillSwitchBinding
from bot.kraken_six_source_binding_contract_v490 import EXPECTED_OWNERS
from bot.pretrade_attestation_validation_v452 import REQUIRED

RUNTIME_FIELDS = {"kill_switch_clear", "position_sync"}
EXTERNAL_FIELDS = set(EXPECTED_OWNERS) - RUNTIME_FIELDS


@pytest.fixture
def native(wiring):
    switch = SimpleNamespace(
        get_status=Mock(side_effect=AssertionError("no status read during construction")),
        DURABLE_REDIS_KEY="offline:reviewed-clearance",
    )
    redis = SimpleNamespace(pipeline=Mock(side_effect=AssertionError("no Redis read during construction")))
    binding = ReviewedKillSwitchBinding(
        account="platform:kraken", api_key_sha256=wiring.signed.trust.api_key_sha256,
        provider_id=wiring.signed.trust.reviewed_provider_ids["kill_switch_clear"],
        durable_key=switch.DURABLE_REDIS_KEY, clearance_sha256="a" * 64,
        kill_switch=switch, redis_client=redis,
    )
    review = Mock(return_value=True)
    sources = replace(
        wiring.sources,
        independent_remaining={field: wiring.sources.independent_remaining[field] for field in EXTERNAL_FIELDS},
        kill_switch_binding=binding, review_kill_switch_binding=review,
    )
    wiring.resolve.return_value = sources
    return SimpleNamespace(wiring=wiring, sources=sources, binding=binding,
                           review=review, switch=switch, redis=redis)


def invoke(native):
    w = native.wiring
    factory = root.make_canonical_kraken_startup_factory(
        trust=w.signed.trust, resolve_sources=w.resolve, review_sources=w.review,
    )
    return factory(manager=w.sources.manager, strategy=w.sources.strategy)


def test_real_native_pair_uses_exact_canonical_broker_and_existing_owners(native, monkeypatch):
    kill = Mock(wraps=composition.make_kraken_kill_switch_provider)
    positions = Mock(wraps=composition.make_kraken_position_sync_provider)
    monkeypatch.setattr(composition, "make_kraken_kill_switch_provider", kill)
    monkeypatch.setattr(composition, "make_kraken_position_sync_provider", positions)
    binding = invoke(native)
    assert set(binding.providers) == set(REQUIRED)
    assert len({id(provider) for provider in binding.providers.values()}) == 13
    for field in EXTERNAL_FIELDS:
        assert binding.providers[field] is native.sources.independent_remaining[field]
    kill.assert_called_once_with(native.binding, review_binding=native.review)
    kwargs = positions.call_args.kwargs
    assert positions.call_count == 1
    assert positions.call_args.args == (native.wiring.sources.broker,)
    assert kwargs["independent_positions"] is native.sources.independent_positions
    assert kwargs["approved_api_key_sha256"] == native.wiring.signed.trust.api_key_sha256
    assert kwargs["approved_iban_sha256"] == native.wiring.signed.trust.account_iiban_sha256
    assert kwargs["reviewed_provider_id"] == native.wiring.signed.trust.reviewed_provider_ids["position_sync"]
    assert kwargs["reviewed_ledger_provider_id"] == (
        native.wiring.signed.trust.reviewed_provider_ids["position_ledger_reconciliation"]
    )
    native.review.assert_called_once_with(native.binding)
    assert native.wiring.review.call_count == 2
    native.switch.get_status.assert_not_called()
    native.redis.pipeline.assert_not_called()
    native.wiring.private_call.assert_not_called()
    native.sources.independent_positions.assert_not_called()
    assert attestation._COLLECTOR is None


@pytest.mark.parametrize("field", sorted(EXTERNAL_FIELDS))
def test_each_required_external_source_still_denies_before_native_construction(native, monkeypatch, field):
    remaining = dict(native.sources.independent_remaining)
    remaining.pop(field)
    native.wiring.resolve.return_value = replace(native.sources, independent_remaining=remaining)
    constructor = Mock()
    monkeypatch.setattr(composition, "make_kraken_kill_switch_provider", constructor)
    with pytest.raises(root.CanonicalKrakenStartupDenied):
        invoke(native)
    constructor.assert_not_called()
    native.review.assert_not_called()


@pytest.mark.parametrize("field", sorted(EXPECTED_OWNERS))
def test_reviewed_owner_map_still_covers_all_six(native, monkeypatch, field):
    owners = dict(native.sources.reviewed_source_owners)
    owners[field] = "foreign-owner"
    native.wiring.resolve.return_value = replace(native.sources, reviewed_source_owners=owners)
    constructor = Mock()
    monkeypatch.setattr(composition, "make_kraken_kill_switch_provider", constructor)
    with pytest.raises(root.CanonicalKrakenStartupDenied):
        invoke(native)
    constructor.assert_not_called()


@pytest.mark.parametrize("attribute,value", [
    ("kill_switch_binding", None), ("kill_switch_binding", object()),
    ("review_kill_switch_binding", None), ("review_kill_switch_binding", True),
])
def test_partial_or_untyped_native_binding_denies(native, attribute, value):
    native.wiring.resolve.return_value = replace(native.sources, **{attribute: value})
    with pytest.raises(root.CanonicalKrakenStartupDenied):
        invoke(native)
    native.review.assert_not_called()
    native.redis.pipeline.assert_not_called()


@pytest.mark.parametrize("attribute,value", [
    ("account", "user:offline:kraken"), ("api_key_sha256", "f" * 64),
    ("provider_id", "unreviewed-clearance-provider"),
])
def test_native_binding_must_match_approved_scope_and_provider_registry(native, attribute, value):
    native.wiring.resolve.return_value = replace(
        native.sources, kill_switch_binding=replace(native.binding, **{attribute: value}),
    )
    with pytest.raises(root.CanonicalKrakenStartupDenied):
        invoke(native)
    native.review.assert_not_called()


@pytest.mark.parametrize("value", [False, None, 1, "true"])
def test_native_binding_review_requires_literal_true(native, value):
    native.review.return_value = value
    with pytest.raises(root.CanonicalKrakenStartupDenied):
        invoke(native)
    native.redis.pipeline.assert_not_called()
    native.switch.get_status.assert_not_called()


def test_mixed_external_and_native_mode_does_not_overwrite_supplied_readers(native):
    remaining = {**native.sources.independent_remaining,
                 "kill_switch_clear": lambda: {}, "position_sync": lambda: {}}
    native.wiring.resolve.return_value = replace(native.sources, independent_remaining=remaining)
    with pytest.raises(root.CanonicalKrakenStartupDenied):
        invoke(native)
    native.review.assert_not_called()


def test_reused_external_callable_denies_before_review(native):
    remaining = dict(native.sources.independent_remaining)
    first, second = sorted(EXTERNAL_FIELDS)[:2]
    remaining[first] = remaining[second]
    native.wiring.resolve.return_value = replace(native.sources, independent_remaining=remaining)
    with pytest.raises(root.CanonicalKrakenStartupDenied):
        invoke(native)
    native.review.assert_not_called()


def test_noncallable_external_source_denies_before_review(native):
    remaining = {**native.sources.independent_remaining, "risk_limits": None}
    native.wiring.resolve.return_value = replace(native.sources, independent_remaining=remaining)
    with pytest.raises(root.CanonicalKrakenStartupDenied):
        invoke(native)
    native.review.assert_not_called()


def test_native_constructor_cannot_reuse_an_external_source(native, monkeypatch):
    existing = next(iter(native.sources.independent_remaining.values()))
    monkeypatch.setattr(composition, "make_kraken_kill_switch_provider", Mock(return_value=existing))
    with pytest.raises(root.CanonicalKrakenStartupDenied):
        invoke(native)
    native.wiring.private_call.assert_not_called()
    assert attestation._COLLECTOR is None


def test_revoked_whole_source_review_after_construction_preserves_collector(native, monkeypatch):
    previous = object()
    monkeypatch.setattr(attestation, "_COLLECTOR", previous)
    native.wiring.review.side_effect = [True, False]
    with pytest.raises(root.CanonicalKrakenStartupDenied):
        invoke(native)
    assert attestation._COLLECTOR is previous
    native.redis.pipeline.assert_not_called()


def test_signed_protected_root_can_reach_the_real_native_pair(native, protected):
    protected.bridge.build.side_effect = lambda **kwargs: replace(native.sources, receipts=kwargs["receipts"])
    assert protected_root.register_from_protected_root() == "protected_startup_factory_registered"
    binding = startup._factory(manager=native.sources.manager, strategy=native.sources.strategy)
    assert len(binding.providers) == 13
    assert startup._verify_receipts(binding) is True
    native.review.assert_called_once_with(native.binding)
    native.wiring.private_call.assert_not_called()
    native.redis.pipeline.assert_not_called()
    assert attestation._COLLECTOR is None


def test_unavailable_native_reads_still_prevent_actual_atomic_install(native, protected, monkeypatch):
    previous = object()
    monkeypatch.setattr(attestation, "_COLLECTOR", previous)
    protected.bridge.build.side_effect = lambda **kwargs: replace(native.sources, receipts=kwargs["receipts"])

    def compose(**kwargs):
        # Other observations are synthetic. The native pair is real and denies
        # because its Redis/broker observations are unavailable, never invented.
        return {**native.wiring.signed.binding.providers, **kwargs["independent_remaining"]}

    monkeypatch.setattr(root, "compose_authenticated_kraken_collector_sources", compose)
    assert protected_root.register_from_protected_root() == "protected_startup_factory_registered"
    assert startup.install_from_canonical_startup(native.sources.manager, native.sources.strategy) == (
        "collector_registration_failed"
    )
    assert attestation._COLLECTOR is previous


def test_direct_shared_helper_requires_independent_review(native):
    with pytest.raises(composition.KrakenCollectorBindingDenied, match="independent_review_required"):
        composition.compose_reviewed_kraken_runtime_sources(
            broker=native.sources.broker,
            approved_api_key_sha256=native.wiring.signed.trust.api_key_sha256,
            approved_iban_sha256=native.wiring.signed.trust.account_iiban_sha256,
            reviewed_provider_ids=native.wiring.signed.trust.reviewed_provider_ids,
            independent_positions=native.sources.independent_positions,
            independent_remaining=native.sources.independent_remaining,
            monitoring_category=native.sources.monitoring_category,
            kill_switch_binding=native.binding, review_kill_switch_binding=native.review,
        )
    native.review.assert_not_called()
