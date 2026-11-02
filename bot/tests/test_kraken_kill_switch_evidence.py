"""Synthetic authority fixtures; these tests never certify a real account."""
from dataclasses import replace
import hashlib
import json
from types import SimpleNamespace

import pytest

from bot.kraken_kill_switch_evidence import (
    KrakenKillSwitchDenied, ReviewedKillSwitchBinding, make_kraken_kill_switch_provider,
)
from bot.pretrade_attestation_validation_v452 import (
    REQUIRED, SOURCES, PROOF_BY_SOURCE, evaluate_pretrade_certificate,
)

NOW = 1800000000.0
CLEAR = {"is_active": False, "schema": 2, "reason": "synthetic reviewed clearance",
         "timestamp": "2026-01-01T00:00:00+00:00"}


def digest(row):
    return hashlib.sha256(json.dumps(row, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class Pipeline:
    def __init__(self, owner):
        self.owner = owner
        self.queued = False
        self.commands = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.owner.closed = True

    def watch(self, key):
        self.commands.append(("WATCH", key))

    def get(self, key):
        self.commands.append(("GET", key))
        return self if self.queued else self.owner.raw

    def pttl(self, key):
        self.commands.append(("PTTL", key))
        return self

    def multi(self):
        self.queued = True

    def execute(self):
        if self.owner.changed:
            raise RuntimeError("synthetic secret exception must not escape")
        return [self.owner.raw, self.owner.ttl]


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.delenv("NIJA_KILL_SWITCH", raising=False)
    client = SimpleNamespace(raw=json.dumps(CLEAR), ttl=-1, changed=False, closed=False)
    client.pipe = Pipeline(client)
    client.pipeline = lambda: client.pipe
    status = {"is_active": False, "kill_file_exists": False, "recent_history": []}
    kill = SimpleNamespace(DURABLE_REDIS_KEY="synthetic:kill", get_status=lambda: status)
    binding = ReviewedKillSwitchBinding(
        "platform:kraken", hashlib.sha256(b"synthetic-test-key").hexdigest(),
        "synthetic-risk-clearance", kill.DURABLE_REDIS_KEY, digest(CLEAR), kill, client,
    )
    return binding, client, status


def provider(binding, **kwargs):
    return make_kraken_kill_switch_provider(
        binding, review_binding=kwargs.pop("review_binding", lambda b: b is binding),
        clock=kwargs.pop("clock", lambda: NOW), **kwargs,
    )


def test_real_record_shape_produces_only_non_authorizing_v452_evidence(setup):
    binding, client, _ = setup
    result = provider(binding)()
    assert result["source"] == "risk_governor"
    assert result["authorizes_orders"] is False
    assert result["observed_at_epoch"] == NOW
    assert result["expires_at_epoch"] == NOW + 60
    assert "reason" not in json.dumps(result)
    assert client.closed
    assert [cmd for cmd, _ in client.pipe.commands] == ["WATCH", "GET", "GET", "PTTL"]


@pytest.mark.parametrize("raw", [None, "", "[]", "{}", "not json",
    '{"is_active": false,"is_active":true}',
    json.dumps({**CLEAR, "is_active": True}),
    json.dumps({**CLEAR, "is_active": 0}),
    json.dumps({**CLEAR, "schema": True}),
    json.dumps({**CLEAR, "schema": 3}),
    json.dumps({**CLEAR, "reason": ""}),
    json.dumps({**CLEAR, "timestamp": "2026-01-01T00:00:00"}),
    json.dumps({**CLEAR, "timestamp": "2099-01-01T00:00:00+00:00"}),
])
def test_absent_malformed_active_and_unreviewed_records_deny(setup, raw):
    binding, client, _ = setup
    client.raw = raw
    with pytest.raises(KrakenKillSwitchDenied):
        provider(binding)()


@pytest.mark.parametrize("ttl", [-2, 0, 1, 60000, False])
def test_clearance_must_be_durable_without_expiry(setup, ttl):
    binding, client, _ = setup
    client.ttl = ttl
    with pytest.raises(KrakenKillSwitchDenied, match="changed_or_expiring"):
        provider(binding)()


@pytest.mark.parametrize("flag", ["is_active", "kill_file_exists"])
def test_local_veto(setup, flag):
    binding, _, status = setup
    status[flag] = True
    with pytest.raises(KrakenKillSwitchDenied, match="local_kill_switch_not_clear"):
        provider(binding)()


def test_deployment_veto(setup, monkeypatch):
    monkeypatch.setenv("NIJA_KILL_SWITCH", "true")
    with pytest.raises(KrakenKillSwitchDenied, match="deployment_kill_switch_active"):
        provider(setup[0])()


def test_watch_change_or_transport_failure_denies_without_leaking(setup):
    binding, client, _ = setup
    client.changed = True
    with pytest.raises(KrakenKillSwitchDenied) as error:
        provider(binding)()
    assert str(error.value) == "kill_switch_read_unverified"
    assert client.closed


def test_approved_pin_cannot_be_derived_from_current_record(setup):
    binding, client, _ = setup
    client.raw = json.dumps({**CLEAR, "reason": "different clearance"})
    with pytest.raises(KrakenKillSwitchDenied, match="not_independently_approved"):
        provider(binding)()


def test_review_required_and_revocation_rechecked(setup):
    binding = setup[0]
    with pytest.raises(KrakenKillSwitchDenied, match="independent_binding_review_required"):
        provider(binding, review_binding=lambda _: False)
    approved = True
    observe = provider(binding, review_binding=lambda _: approved)
    approved = False
    with pytest.raises(KrakenKillSwitchDenied, match="binding_review_revoked"):
        observe()


@pytest.mark.parametrize("finish", [NOW - 1, NOW + 60, float("nan"), True])
def test_clock_and_collection_lifetime_deny(setup, finish):
    ticks = iter([NOW, finish])
    with pytest.raises(KrakenKillSwitchDenied):
        provider(setup[0], clock=lambda: next(ticks))()


def test_existing_v452_accepts_only_correct_source_and_expires(setup):
    result = provider(setup[0])()
    ids = {name: "synthetic-" + name for name in REQUIRED}
    ids["kill_switch_clear"] = result["provider_id"]
    observations = {name: {
        "account": "platform:kraken", "source": SOURCES[name], "provider_id": ids[name],
        "evidence_id": "synthetic-evidence-" + name, "verified": True,
        "read_only": True, "scope_verified": True, "observed_at_epoch": NOW,
        "provenance": {"account_scope_verified": True, "collector_identity_verified": True,
                       "snapshot_complete": True, "complete_pagination_verified": True,
                       PROOF_BY_SOURCE[SOURCES[name]]: True},
    } for name in REQUIRED}
    observations["kill_switch_clear"] = result
    report = evaluate_pretrade_certificate(observations, account="platform:kraken",
                                          trusted_provider_ids=ids, now_epoch=NOW)
    assert report["certified"] is True
    report = evaluate_pretrade_certificate(observations, account="platform:kraken",
                                          trusted_provider_ids=ids, now_epoch=NOW + 60)
    assert report["certified"] is False


def test_wrong_account_and_changed_key_binding_deny(setup):
    binding = setup[0]
    with pytest.raises(KrakenKillSwitchDenied, match="platform_scope"):
        provider(replace(binding, account="user:other:kraken"))
    observe = provider(binding)
    binding.kill_switch.DURABLE_REDIS_KEY = "different"
    with pytest.raises(KrakenKillSwitchDenied, match="binding_changed"):
        observe()


def test_existing_composition_connects_two_runtime_sources_without_installing(setup, monkeypatch):
    from bot import kraken_collector_composition_v487 as composition

    binding = setup[0]
    ids = {name: "synthetic-" + name for name in REQUIRED}
    ids["kill_switch_clear"] = binding.provider_id
    called = []
    monkeypatch.setattr(composition, "register_reviewed_account_registry", lambda **_: called.append(True))
    options = dict(
        broker=SimpleNamespace(_kraken_private_call=lambda *a, **k: (_ for _ in ()).throw(AssertionError("unexpected broker I/O"))),
        approved_api_key_sha256=binding.api_key_sha256,
        approved_iban_sha256=hashlib.sha256(b"synthetic-iban").hexdigest(),
        reviewed_provider_ids=ids, independent_open_intents=lambda: {},
        independent_positions=lambda: {}, monitoring_category=object(), independently_reviewed=True,
        kill_switch_binding=binding, review_kill_switch_binding=lambda b: b is binding,
        independent_remaining={name: (lambda name=name: {"field": name})
                               for name in composition.OTHER_FIELDS - {"kill_switch_clear", "position_sync"}},
        clock=lambda: NOW,
    )
    providers = composition.compose_reviewed_kraken_providers(**options)
    assert set(providers) == set(REQUIRED)
    assert len({id(p) for p in providers.values()}) == 13
    assert providers["kill_switch_clear"]()["verified"] is True
    assert called == []
    options["approved_api_key_sha256"] = hashlib.sha256(b"different-test-key").hexdigest()
    with pytest.raises(composition.KrakenCollectorBindingDenied, match="binding_mismatch"):
        composition.compose_reviewed_kraken_providers(**options)
