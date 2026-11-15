"""Synthetic signing fixtures; never production review or approval evidence."""
import base64
import hashlib
import json
import sys
import time
from dataclasses import replace
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from bot import kraken_startup_evidence_binding as startup
from bot import pretrade_independent_attestation as attestation
from bot.kraken_operator_authorization import _canonical
from bot.kraken_startup_receipts import (
    CONTRACT, StartupReceiptTrust, make_startup_receipt_verifier, register_signed_kraken_startup,
)
from bot.pretrade_attestation_validation_v452 import REQUIRED, SOURCES, PROOF_BY_SOURCE


@pytest.fixture
def fixture(monkeypatch):
    now = time.time()
    monkeypatch.setattr(startup, "_factory", None)
    monkeypatch.setattr(startup, "_verify_receipts", None)
    monkeypatch.setattr(attestation, "_COLLECTOR", None)

    class Broker:
        connected = True
        account_type = "platform"
        broker_type = "kraken"
        user_id = None

    monkeypatch.setitem(sys.modules, "bot.broker_manager", SimpleNamespace(KrakenBroker=Broker))
    broker = Broker()
    manager = SimpleNamespace(platform_brokers={"kraken": broker})
    strategy = object()
    ids = {field: "synthetic-reviewed-" + field for field in REQUIRED}
    keys = {kind: Ed25519PrivateKey.generate() for kind in startup.RECEIPTS}
    trust = StartupReceiptTrust(
        service_id="srv-d98dsr5aeets73fpbaqg", release_id="a" * 40,
        image_sha256="b" * 64, account_iiban_sha256="c" * 64, api_key_sha256="d" * 64,
        reviewed_provider_ids=ids,
        public_keys={kind: key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw,
        ) for kind, key in keys.items()}, maximum_receipt_age_s=60,
    )
    monkeypatch.setenv("RENDER_SERVICE_ID", trust.service_id)
    monkeypatch.setenv("RENDER_GIT_COMMIT", trust.release_id)
    payloads = {kind: {
        "contract": CONTRACT, "kind": kind, "evidence_id": "synthetic-" + kind,
        "artifact_sha256": "e" * 64, "status": "certified",
        "service_id": trust.service_id, "release_id": trust.release_id,
        "image_sha256": trust.image_sha256, "account": "platform:kraken",
        "account_iiban_sha256": trust.account_iiban_sha256, "api_key_sha256": trust.api_key_sha256,
        "provider_registry_sha256": hashlib.sha256(_canonical(ids)).hexdigest(),
        "approved_at_epoch": now - 1, "expires_at_epoch": now + 30,
    } for kind in startup.RECEIPTS}

    def sign(kind, payload):
        signature = base64.b64encode(keys[kind].sign(_canonical(payload))).decode()
        return json.dumps({"payload": payload, "signature": signature})

    def provider(field):
        source = SOURCES[field]
        return {
            "account": "platform:kraken", "source": source, "provider_id": ids[field],
            "evidence_id": "synthetic-" + field, "verified": True, "read_only": True,
            "scope_verified": True, "observed_at_epoch": now, "authorizes_orders": False,
            "provenance": {
                "account_scope_verified": True, "collector_identity_verified": True,
                "snapshot_complete": True, "complete_pagination_verified": True,
                PROOF_BY_SOURCE[source]: True,
            },
        }

    binding = startup.ReviewedStartupBinding(
        manager, strategy, broker, {field: lambda field=field: provider(field) for field in REQUIRED},
        ids, {kind: sign(kind, payload) for kind, payload in payloads.items()},
    )
    return SimpleNamespace(now=now, trust=trust, binding=binding, payloads=payloads, sign=sign, keys=keys)


def changed_receipt(fixture, field, value):
    kind = "independent_review"
    payload = {**fixture.payloads[kind], field: value}
    return replace(fixture.binding, receipts={**fixture.binding.receipts, kind: fixture.sign(kind, payload)})


def test_authentic_receipts_use_real_atomic_installer_and_never_authorize(fixture):
    register_signed_kraken_startup(lambda **kwargs: fixture.binding, fixture.trust, clock=lambda: fixture.now)
    assert startup.install_from_canonical_startup(fixture.binding.manager, fixture.binding.strategy) == (
        "diagnostic_collector_installed"
    )
    report = attestation.inspect_authenticated_attestations("platform:kraken")
    assert all(report["checks"].values())
    assert report["authorizes_orders"] is False


def test_invalid_receipt_never_observes_sources_or_replaces_existing_registry(fixture, monkeypatch):
    calls = []
    providers = {field: (lambda field=field: calls.append(field)) for field in REQUIRED}
    binding = replace(changed_receipt(fixture, "api_key_sha256", "f" * 64), providers=providers)
    previous = object()
    monkeypatch.setattr(attestation, "_COLLECTOR", previous)
    register_signed_kraken_startup(lambda **kwargs: binding, fixture.trust, clock=lambda: fixture.now)
    assert startup.install_from_canonical_startup(binding.manager, binding.strategy) == (
        "authenticated_release_receipts_required"
    )
    assert calls == []
    assert attestation._COLLECTOR is previous


@pytest.mark.parametrize("tick", [float("nan"), True, -1])
def test_invalid_observation_clock_denies(fixture, tick):
    assert make_startup_receipt_verifier(fixture.trust, clock=lambda: tick)(fixture.binding) is False


@pytest.mark.parametrize("field", ["RENDER_SERVICE_ID", "RENDER_GIT_COMMIT"])
def test_actual_runtime_identity_must_match_signed_context(fixture, monkeypatch, field):
    monkeypatch.delenv(field)
    verify = make_startup_receipt_verifier(fixture.trust, clock=lambda: fixture.now)
    assert verify(fixture.binding) is False
    monkeypatch.setenv(field, "different-runtime")
    assert verify(fixture.binding) is False


def test_runtime_change_during_verification_denies(fixture, monkeypatch):
    ticks = 0

    def clock():
        nonlocal ticks
        ticks += 1
        if ticks == 2:
            monkeypatch.setenv("RENDER_GIT_COMMIT", "different-runtime")
        return fixture.now

    assert make_startup_receipt_verifier(fixture.trust, clock=clock)(fixture.binding) is False


@pytest.mark.parametrize("field,value", [
    ("contract", "different-contract"), ("kind", "backup_restore"), ("status", "pending"),
    ("service_id", "different-service"), ("release_id", "f" * 40), ("image_sha256", "f" * 64),
    ("account", "user:synthetic:kraken"), ("account_iiban_sha256", "f" * 64),
    ("api_key_sha256", "f" * 64), ("provider_registry_sha256", "f" * 64),
    ("evidence_id", ""), ("artifact_sha256", "not-a-digest"),
    ("approved_at_epoch", True), ("expires_at_epoch", True),
])
def test_signed_wrong_scope_or_invalid_payload_is_denied(fixture, field, value):
    assert make_startup_receipt_verifier(fixture.trust, clock=lambda: fixture.now)(
        changed_receipt(fixture, field, value),
    ) is False
    assert attestation._COLLECTOR is None


@pytest.mark.parametrize("kind", sorted(startup.RECEIPTS))
def test_each_missing_or_wrong_signer_receipt_preserves_collector(fixture, kind):
    receipts = dict(fixture.binding.receipts)
    receipts.pop(kind)
    verify = make_startup_receipt_verifier(fixture.trust, clock=lambda: fixture.now)
    assert verify(replace(fixture.binding, receipts=receipts)) is False
    wrong = dict(fixture.trust.public_keys)
    other = next(name for name in startup.RECEIPTS if name != kind)
    wrong[kind] = wrong[other]
    assert make_startup_receipt_verifier(replace(fixture.trust, public_keys=wrong), clock=lambda: fixture.now)(
        fixture.binding,
    ) is False
    assert attestation._COLLECTOR is None


@pytest.mark.parametrize("case", ["expired", "future", "old", "clock_rollback", "expires_during_check"])
def test_time_and_expiry_are_checked_before_and_after_verification(fixture, case):
    binding = fixture.binding
    ticks = [fixture.now, fixture.now]
    if case == "expired":
        binding = changed_receipt(fixture, "expires_at_epoch", fixture.now)
    elif case == "future":
        binding = changed_receipt(fixture, "approved_at_epoch", fixture.now + 1)
    elif case == "old":
        binding = changed_receipt(fixture, "approved_at_epoch", fixture.now - 61)
    elif case == "clock_rollback":
        ticks[1] -= 1
    else:
        ticks[1] += 31
    assert make_startup_receipt_verifier(fixture.trust, clock=iter(ticks).__next__)(binding) is False


@pytest.mark.parametrize("raw", [None, {}, b"unsigned", "", "x" * 16385,
                                   '{"payload":{},"payload":{},"signature":""}'])
def test_unsigned_mutable_oversized_or_ambiguous_receipts_deny(fixture, raw):
    binding = replace(fixture.binding, receipts={**fixture.binding.receipts, "independent_review": raw})
    assert make_startup_receipt_verifier(fixture.trust, clock=lambda: fixture.now)(binding) is False


def test_tampered_signature_reused_evidence_and_registry_substitution_deny(fixture):
    verify = make_startup_receipt_verifier(fixture.trust, clock=lambda: fixture.now)
    envelope = json.loads(fixture.binding.receipts["independent_review"])
    envelope["payload"]["artifact_sha256"] = "f" * 64
    assert verify(replace(fixture.binding, receipts={
        **fixture.binding.receipts, "independent_review": json.dumps(envelope),
    })) is False
    assert verify(changed_receipt(fixture, "evidence_id", "synthetic-backup_restore")) is False
    ids = dict(fixture.binding.reviewed_provider_ids)
    ids[next(iter(ids))] = "substituted-provider"
    assert verify(replace(fixture.binding, reviewed_provider_ids=ids)) is False
    callback = next(iter(fixture.binding.providers.values()))
    assert verify(replace(fixture.binding, providers={field: callback for field in REQUIRED})) is False


@pytest.mark.parametrize("field,value", [
    ("release_id", "not-a-commit"), ("image_sha256", "missing"), ("public_keys", {}),
    ("reviewed_provider_ids", {}), ("maximum_receipt_age_s", True),
    ("maximum_receipt_age_s", float("inf")), ("maximum_receipt_age_s", 0),
])
def test_incomplete_trust_configuration_cannot_register(fixture, field, value):
    with pytest.raises(ValueError, match="reviewed_startup_trust_pins_required"):
        replace(fixture.trust, **{field: value})
    assert startup._factory is None


def test_trust_inputs_are_frozen_and_diagnostics_never_log_receipts(fixture, caplog):
    with pytest.raises(TypeError):
        fixture.trust.public_keys["independent_review"] = b"untrusted"
    with pytest.raises(TypeError):
        fixture.trust.reviewed_provider_ids["account_identity"] = "untrusted"
    canary = "private-receipt-canary"
    broken = replace(fixture.binding, receipts={**fixture.binding.receipts, "independent_review": canary})
    assert make_startup_receipt_verifier(fixture.trust, clock=lambda: fixture.now)(broken) is False
    assert canary not in caplog.text
