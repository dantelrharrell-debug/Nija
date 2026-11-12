"""Synthetic owners only; exercise actual native construction and atomic denial."""
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from test_kraken_startup_receipts import fixture  # noqa: F401 -- synthetic signers
from test_kraken_canonical_startup_factory import wiring  # noqa: F401 -- canonical objects
from test_kraken_canonical_native_source_bindings import native  # noqa: F401 -- native pair
from test_kraken_protected_startup_root import protected  # noqa: F401 -- protected fixture
from bot import kraken_native_four_source_binding as four_root
from bot import kraken_canonical_startup_factory as root
from bot import kraken_protected_startup_root as protected_root
from bot import kraken_startup_evidence_binding as startup
from bot import pretrade_independent_attestation as attestation
from bot.kraken_ledger_evidence import ReviewedLedgerBinding
from bot.kraken_operator_authorization import GeneralApprovalBinding
from bot.kraken_redis_evidence import ReviewedBinding, ScopeObservation, FIELDS as REDIS_FIELDS
from bot.pretrade_attestation_validation_v452 import REQUIRED


@pytest.fixture
def four(wiring, tmp_path):
    t = wiring.signed.trust
    unavailable = "synthetic-private-source-failure"
    redis = SimpleNamespace(pipeline=Mock(side_effect=RuntimeError(unavailable)))
    scope = ScopeObservation("platform:kraken", t.api_key_sha256, "synthetic-process:1", 1,
                             "synthetic-nonce-owner", "synthetic-fingerprint", 1)
    redis_binding = ReviewedBinding(
        expected_scope=scope, provider_ids=tuple(t.reviewed_provider_ids[k] for k in REDIS_FIELDS),
        review_reference="synthetic-reviewed-cutover", coverage_sha256="e" * 64,
        submission_routes=("synthetic-route",), deployment_sha256=t.image_sha256,
        source_binding_sha256="f" * 64, observe_scope=Mock(return_value=scope),
        verify_coverage=Mock(side_effect=AssertionError("no coverage verification at construction")),
    )
    ledger = ReviewedLedgerBinding(
        broker=wiring.sources.broker, account="platform:kraken",
        provider_id=t.reviewed_provider_ids["position_ledger_reconciliation"],
        api_key_sha256=t.api_key_sha256, account_sha256=t.account_iiban_sha256,
        ledger_path=tmp_path / "certified.sqlite3", persistent_root=tmp_path,
        monitoring_category=wiring.sources.monitoring_category,
    )
    operator = four_root.ReviewedOperatorSource(
        binding=GeneralApprovalBinding(
            "platform:kraken", t.account_iiban_sha256, t.api_key_sha256,
            "spot", ("diagnostics",), t.release_id, t.reviewed_provider_ids["operator_authorization"],
        ),
        operator_public_keys={"synthetic-operator": t.public_keys["independent_review"]},
        revocation_public_key=t.public_keys["backup_restore"],
        read_records=Mock(side_effect=RuntimeError(unavailable)),
    )
    risk = four_root.ReviewedRiskSource(
        source=SimpleNamespace(read_snapshot=Mock(side_effect=RuntimeError(unavailable))),
        source_id="synthetic-risk-owner",
        record_source_ids={k: "synthetic-" + k for k in ("capital", "exposure", "policy")},
    )
    bundle = four_root.ReviewedNativeFourSources(
        manager=wiring.sources.manager, strategy=wiring.sources.strategy, broker=wiring.sources.broker,
        service_id=t.service_id, release_id=t.release_id, image_sha256=t.image_sha256,
        ledger_binding=ledger, review_ledger_binding=Mock(return_value=True),
        redis=four_root.ReviewedRedisSource(redis, redis_binding), operator=operator, risk=risk,
    )
    review = Mock(return_value=True)
    sources = replace(
        wiring.sources,
        independent_remaining={k: wiring.sources.independent_remaining[k]
                               for k in ("kill_switch_clear", "position_sync")},
        native_four_sources=bundle, review_native_four_sources=review,
    )
    wiring.resolve.return_value = sources
    return SimpleNamespace(wiring=wiring, sources=sources, bundle=bundle, review=review, redis=redis)


def invoke(four):
    w = four.wiring
    return root.make_canonical_kraken_startup_factory(
        trust=w.signed.trust, resolve_sources=w.resolve, review_sources=w.review,
    )(manager=w.sources.manager, strategy=w.sources.strategy)


def assert_no_source_reads(four):
    four.redis.pipeline.assert_not_called()
    four.bundle.redis.binding.observe_scope.assert_not_called()
    four.bundle.redis.binding.verify_coverage.assert_not_called()
    four.bundle.operator.read_records.assert_not_called()
    four.bundle.risk.source.read_snapshot.assert_not_called()
    four.wiring.private_call.assert_not_called()
    four.sources.independent_positions.assert_not_called()
    four.sources.independent_open_intents.assert_not_called()
    assert not four.bundle.ledger_binding.ledger_path.exists()


def test_actual_four_native_constructors_reach_the_canonical_registry_without_reads(four, monkeypatch):
    spies = {}
    for name in ("make_kraken_ledger_evidence_provider", "RedisEvidenceReader",
                 "make_general_operator_authorization_provider", "make_kraken_risk_limits_provider"):
        spies[name] = Mock(wraps=getattr(four_root, name))
        monkeypatch.setattr(four_root, name, spies[name])
    binding = invoke(four)
    assert set(binding.providers) == set(REQUIRED)
    assert len({id(p) for p in binding.providers.values()}) == 13
    assert binding.providers["kill_switch_clear"] is four.sources.independent_remaining["kill_switch_clear"]
    for spy in spies.values():
        assert spy.call_count == 1
    assert spies["make_kraken_ledger_evidence_provider"].call_args.args == (four.bundle.ledger_binding,)
    assert spies["RedisEvidenceReader"].call_args.args == (four.redis, four.bundle.redis.binding)
    risk = spies["make_kraken_risk_limits_provider"].call_args
    assert risk.args == (four.bundle.risk.source,)
    assert risk.kwargs["approved_api_key_sha256"] == four.wiring.signed.trust.api_key_sha256
    assert risk.kwargs["reviewed_provider_id"] == four.wiring.signed.trust.reviewed_provider_ids["risk_limits"]
    assert risk.kwargs["reviewed_record_source_ids"] == four.bundle.risk.record_source_ids
    assert four.review.call_count == 2
    four.bundle.review_ledger_binding.assert_called_once_with(four.bundle.ledger_binding)
    assert_no_source_reads(four)
    assert attestation._COLLECTOR is None


def test_combined_native_four_and_pair_construct_all_thirteen_without_external_six_callbacks(four, native):
    w = four.wiring
    w.resolve.return_value = replace(
        native.sources, independent_remaining={}, native_four_sources=four.bundle,
        review_native_four_sources=four.review,
    )
    binding = invoke(four)
    assert len(binding.providers) == 13
    assert len({id(p) for p in binding.providers.values()}) == 13
    native.review.assert_called_once_with(native.binding)
    assert_no_source_reads(four)
    native.redis.pipeline.assert_not_called()
    native.switch.get_status.assert_not_called()


@pytest.mark.parametrize("field", ["manager", "strategy", "broker"])
def test_foreign_canonical_owner_denies_before_native_review(four, field):
    four.wiring.resolve.return_value = replace(
        four.sources, native_four_sources=replace(four.bundle, **{field: object()}),
    )
    with pytest.raises(root.CanonicalKrakenStartupDenied):
        invoke(four)
    four.review.assert_not_called()
    assert_no_source_reads(four)


@pytest.mark.parametrize("field,value", [
    ("service_id", "foreign-service"), ("release_id", "b" * 40), ("image_sha256", "a" * 64),
])
def test_foreign_release_denies_before_native_review(four, field, value):
    four.wiring.resolve.return_value = replace(
        four.sources, native_four_sources=replace(four.bundle, **{field: value}),
    )
    with pytest.raises(root.CanonicalKrakenStartupDenied):
        invoke(four)
    four.review.assert_not_called()
    assert_no_source_reads(four)


@pytest.mark.parametrize("component,field,value", [
    ("ledger_binding", "account", "user:offline:kraken"),
    ("ledger_binding", "api_key_sha256", "f" * 64),
    ("ledger_binding", "account_sha256", "f" * 64),
    ("ledger_binding", "provider_id", "foreign-ledger"),
    ("ledger_binding", "broker", object()),
    ("ledger_binding", "monitoring_category", object()),
    ("operator", "account", "user:offline:kraken"),
    ("operator", "api_key_sha256", "f" * 64),
    ("operator", "account_iiban_sha256", "f" * 64),
    ("operator", "release_id", "b" * 40),
    ("operator", "provider_id", "foreign-operator"),
])
def test_native_account_key_provider_and_category_pins_must_match(four, component, field, value):
    original = getattr(four.bundle, component)
    changed = replace(original.binding, **{field: value}) if component == "operator" else replace(
        original, **{field: value},
    )
    if component == "operator":
        changed = replace(original, binding=changed)
    four.wiring.resolve.return_value = replace(
        four.sources, native_four_sources=replace(four.bundle, **{component: changed}),
    )
    with pytest.raises(root.CanonicalKrakenStartupDenied):
        invoke(four)
    four.review.assert_not_called()
    assert_no_source_reads(four)


@pytest.mark.parametrize("change", ["account", "key", "providers", "client"])
def test_redis_scope_registry_and_existing_client_are_required(four, change):
    binding = four.bundle.redis.binding
    if change == "account":
        binding = replace(binding, expected_scope=replace(binding.expected_scope, account="user:offline:kraken"))
    elif change == "key":
        binding = replace(binding, expected_scope=replace(binding.expected_scope, api_key_sha256="f" * 64))
    elif change == "providers":
        binding = replace(binding, provider_ids=tuple(reversed(binding.provider_ids)))
    source = four_root.ReviewedRedisSource(object() if change == "client" else four.redis, binding)
    four.wiring.resolve.return_value = replace(
        four.sources, native_four_sources=replace(four.bundle, redis=source),
    )
    with pytest.raises(root.CanonicalKrakenStartupDenied):
        invoke(four)
    four.review.assert_not_called()
    assert_no_source_reads(four)


@pytest.mark.parametrize("result", [False, None, 1, "true"])
def test_unverified_or_truthy_review_does_not_construct_native_readers(four, result):
    four.review.return_value = result
    with pytest.raises(root.CanonicalKrakenStartupDenied):
        invoke(four)
    four.bundle.review_ledger_binding.assert_not_called()
    assert_no_source_reads(four)


@pytest.mark.parametrize("field,value", [
    ("native_four_sources", None), ("native_four_sources", object()),
    ("review_native_four_sources", None), ("review_native_four_sources", True),
])
def test_partial_native_binding_denies_without_fallback(four, field, value):
    four.wiring.resolve.return_value = replace(four.sources, **{field: value})
    with pytest.raises(root.CanonicalKrakenStartupDenied):
        invoke(four)
    assert_no_source_reads(four)


def test_native_mode_cannot_overwrite_external_sources(four):
    four.wiring.resolve.return_value = replace(
        four.sources, independent_remaining=four.wiring.sources.independent_remaining,
    )
    with pytest.raises(root.CanonicalKrakenStartupDenied):
        invoke(four)
    four.review.assert_not_called()
    assert_no_source_reads(four)


def test_complete_six_owner_map_remains_mandatory(four):
    owners = dict(four.sources.reviewed_source_owners)
    owners.pop("risk_limits")
    four.wiring.resolve.return_value = replace(four.sources, reviewed_source_owners=owners)
    with pytest.raises(root.CanonicalKrakenStartupDenied):
        invoke(four)
    four.review.assert_not_called()
    assert_no_source_reads(four)


def test_missing_account_risk_records_and_operator_roots_still_deny(four):
    for changed in (
        replace(four.bundle, risk=replace(four.bundle.risk, record_source_ids={})),
        replace(four.bundle, operator=replace(four.bundle.operator, operator_public_keys={})),
    ):
        four.wiring.resolve.return_value = replace(four.sources, native_four_sources=changed)
        with pytest.raises(root.CanonicalKrakenStartupDenied):
            invoke(four)
    assert_no_source_reads(four)


def test_revoked_review_after_construction_preserves_installed_collector(four, monkeypatch):
    previous = object()
    monkeypatch.setattr(attestation, "_COLLECTOR", previous)
    four.review.side_effect = [True, False]
    with pytest.raises(root.CanonicalKrakenStartupDenied):
        invoke(four)
    assert attestation._COLLECTOR is previous
    assert_no_source_reads(four)


def test_duplicate_wrapper_samples_real_reader_only_at_observation(four, monkeypatch):
    binding = invoke(four)
    rows = {field: {"synthetic": field} for field in REDIS_FIELDS}
    collect = Mock(return_value=rows)
    monkeypatch.setattr(four_root.RedisEvidenceReader, "collect", collect)
    assert binding.providers["duplicate_order_fence"]() is rows["duplicate_order_fence"]
    collect.assert_called_once_with()
    assert_no_source_reads(four)


@pytest.mark.parametrize("rows", [{}, {"duplicate_order_fence": {}}, None])
def test_incomplete_redis_collection_is_never_promoted_to_evidence(four, monkeypatch, rows):
    binding = invoke(four)
    monkeypatch.setattr(four_root.RedisEvidenceReader, "collect", Mock(return_value=rows))
    with pytest.raises(four_root.NativeFourSourceBindingDenied):
        binding.providers["duplicate_order_fence"]()


def test_native_unavailable_observations_are_redacted_and_non_authorizing(four):
    binding = invoke(four)
    for field in ("position_ledger_reconciliation", "duplicate_order_fence", "risk_limits"):
        with pytest.raises(ValueError) as caught:
            binding.providers[field]()
        assert "synthetic-private-source-failure" not in str(caught.value)
    result = binding.providers["operator_authorization"]()
    assert result["verified"] is False
    assert result["authorizes_orders"] is False
    four.wiring.private_call.assert_not_called()


def test_signed_final_interpreter_hook_reaches_actual_four_native_constructors(four, protected):
    protected.bridge.build.side_effect = lambda **kw: replace(four.sources, receipts=kw["receipts"])
    assert protected_root.register_from_protected_root() == "protected_startup_factory_registered"
    binding = startup._factory(manager=four.sources.manager, strategy=four.sources.strategy)
    assert len(binding.providers) == 13
    assert startup._verify_receipts(binding) is True
    assert_no_source_reads(four)
    assert attestation._COLLECTOR is None


def test_real_atomic_install_still_denies_missing_native_evidence(four, protected, monkeypatch):
    previous = object()
    monkeypatch.setattr(attestation, "_COLLECTOR", previous)
    protected.bridge.build.side_effect = lambda **kw: replace(four.sources, receipts=kw["receipts"])

    def compose(**kw):
        return {**four.wiring.signed.binding.providers, **kw["independent_remaining"]}

    monkeypatch.setattr(root, "compose_authenticated_kraken_collector_sources", compose)
    assert protected_root.register_from_protected_root() == "protected_startup_factory_registered"
    assert startup.install_from_canonical_startup(four.sources.manager, four.sources.strategy) == (
        "collector_registration_failed"
    )
    assert attestation._COLLECTOR is previous
    four.wiring.private_call.assert_not_called()


def test_public_key_and_risk_record_maps_are_frozen(four):
    for mapping in (four.bundle.operator.operator_public_keys, four.bundle.risk.record_source_ids):
        with pytest.raises(TypeError):
            mapping["synthetic-new"] = "mutation"
    assert "synthetic-operator" not in repr(four.bundle)
    assert "synthetic-operator" not in repr(four.bundle.operator)


@pytest.mark.parametrize("component", ["ledger_binding", "redis", "operator", "risk"])
def test_untyped_native_owner_is_rejected(four, component):
    four.wiring.resolve.return_value = replace(
        four.sources, native_four_sources=replace(four.bundle, **{component: object()}),
    )
    with pytest.raises(root.CanonicalKrakenStartupDenied):
        invoke(four)
    assert_no_source_reads(four)


def test_native_ledger_reviewer_remains_mandatory(four):
    four.bundle.review_ledger_binding.return_value = False
    with pytest.raises(root.CanonicalKrakenStartupDenied):
        invoke(four)
    assert_no_source_reads(four)


def test_constructor_alias_cannot_hide_reused_native_provider(four, monkeypatch):
    provider = Mock()
    monkeypatch.setattr(four_root, "make_kraken_ledger_evidence_provider", Mock(return_value=provider))
    monkeypatch.setattr(four_root, "make_general_operator_authorization_provider", Mock(return_value=provider))
    with pytest.raises(root.CanonicalKrakenStartupDenied):
        invoke(four)
    provider.assert_not_called()
    assert_no_source_reads(four)


@pytest.mark.parametrize("field", sorted(four_root.FIELDS))
def test_review_revocation_before_observation_does_not_read_a_source(four, field):
    binding = invoke(four)
    four.review.return_value = False
    with pytest.raises(four_root.NativeFourSourceBindingDenied):
        binding.providers[field]()
    assert_no_source_reads(four)


def test_review_revocation_during_observation_discards_returned_evidence(four, monkeypatch):
    binding = invoke(four)
    row = {"synthetic": "not-production-evidence"}
    monkeypatch.setattr(four_root.RedisEvidenceReader, "collect",
                        Mock(return_value={field: row for field in REDIS_FIELDS}))
    four.review.side_effect = [True, False]
    with pytest.raises(four_root.NativeFourSourceBindingDenied):
        binding.providers["duplicate_order_fence"]()


def test_replaced_canonical_broker_denies_before_observation(four):
    binding = invoke(four)
    four.sources.manager.platform_brokers["kraken"] = object()
    with pytest.raises(four_root.NativeFourSourceBindingDenied):
        binding.providers["duplicate_order_fence"]()
    assert_no_source_reads(four)


def test_native_source_exceptions_never_escape_with_private_text(four, monkeypatch):
    binding = invoke(four)
    marker = "synthetic-private-reader-exception"
    monkeypatch.setattr(four_root.RedisEvidenceReader, "collect", Mock(side_effect=RuntimeError(marker)))
    with pytest.raises(four_root.NativeFourSourceBindingDenied) as caught:
        binding.providers["duplicate_order_fence"]()
    assert marker not in str(caught.value)
    assert caught.value.__suppress_context__ is True


def test_source_trust_maps_copy_caller_data(four):
    public = dict(four.bundle.operator.operator_public_keys)
    records = dict(four.bundle.risk.record_source_ids)
    operator = replace(four.bundle.operator, operator_public_keys=public)
    risk = replace(four.bundle.risk, record_source_ids=records)
    public.clear()
    records.clear()
    assert operator.operator_public_keys
    assert set(risk.record_source_ids) == {"capital", "exposure", "policy"}
