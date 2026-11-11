"""Synthetic offline startup wiring; these fixtures are never production proof."""
import ast
from dataclasses import replace
from pathlib import Path
import sys
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from bot import kraken_startup_evidence_binding as startup
from bot import pretrade_independent_attestation as attestation
from bot.pretrade_attestation_validation_v452 import REQUIRED, SOURCES, PROOF_BY_SOURCE


@pytest.fixture
def runtime(monkeypatch):
    monkeypatch.setattr(startup, "_factory", None)
    monkeypatch.setattr(startup, "_verify_receipts", None)
    monkeypatch.setattr(attestation, "_COLLECTOR", None)

    class Broker:
        connected = True
        account_type = "platform"
        broker_type = "kraken"
        user_id = None

        def _kraken_private_call(self, *args, **kwargs):
            raise AssertionError("offline test must not contact exchange")

    monkeypatch.setitem(sys.modules, "bot.broker_manager", SimpleNamespace(KrakenBroker=Broker))
    broker = Broker()
    manager = SimpleNamespace(platform_brokers={"kraken": broker})
    strategy = object()
    ids = {field: "reviewed-" + field for field in REQUIRED}

    def provider(field):
        source = SOURCES[field]
        return {
            "account": "platform:kraken", "source": source,
            "provider_id": ids[field], "evidence_id": "synthetic-" + field,
            "verified": True, "read_only": True, "scope_verified": True,
            "observed_at_epoch": time.time(), "authorizes_orders": False,
            "provenance": {
                "account_scope_verified": True, "collector_identity_verified": True,
                "snapshot_complete": True, "complete_pagination_verified": True,
                PROOF_BY_SOURCE[source]: True,
            },
        }

    binding = startup.ReviewedStartupBinding(
        manager, strategy, broker,
        {field: (lambda field=field: provider(field)) for field in REQUIRED},
        ids, {name: object() for name in startup.RECEIPTS},
    )
    verifier = Mock(return_value=True)
    return manager, strategy, broker, binding, verifier


def invoke(runtime, binding=None, verifier=None):
    manager, strategy, _, original, original_verifier = runtime
    startup.register_reviewed_startup_binding(
        lambda **kwargs: original if binding is None else binding,
        verify_receipts=original_verifier if verifier is None else verifier,
    )
    return startup.install_from_canonical_startup(manager, strategy)


def test_missing_registration_ignores_environment(runtime, monkeypatch):
    monkeypatch.setenv("NIJA_COLLECTOR_CERTIFIED", "true")
    assert startup.install_from_canonical_startup(*runtime[:2]) == "trusted_startup_binding_missing"
    assert attestation._COLLECTOR is None


def test_real_installer_validates_all_thirteen_and_never_authorizes(runtime):
    assert invoke(runtime) == "diagnostic_collector_installed"
    runtime[-1].assert_called_once_with(runtime[3])
    report = attestation.inspect_authenticated_attestations("platform:kraken")
    assert all(report["checks"].values())
    assert report["authorizes_orders"] is False


@pytest.mark.parametrize("field", REQUIRED)
def test_each_failed_provider_prevents_atomic_install(runtime, field):
    binding = runtime[3]
    providers = dict(binding.providers)
    providers[field] = lambda: {"verified": False}
    assert invoke(runtime, replace(binding, providers=providers)) == "collector_registration_failed"
    assert attestation._COLLECTOR is None


@pytest.mark.parametrize("value", [False, None, 1, "true"])
def test_receipt_verifier_requires_exact_approval(runtime, value):
    assert invoke(runtime, verifier=lambda binding: value) == "authenticated_release_receipts_required"
    assert attestation._COLLECTOR is None


@pytest.mark.parametrize("receipt", sorted(startup.RECEIPTS))
def test_each_missing_receipt_denies_before_verifier(runtime, receipt):
    receipts = dict(runtime[3].receipts)
    receipts.pop(receipt)
    assert invoke(runtime, replace(runtime[3], receipts=receipts)) == "authenticated_release_receipts_required"
    runtime[-1].assert_not_called()


@pytest.mark.parametrize("field", ["manager", "strategy", "broker"])
def test_different_runtime_identity_rejected(runtime, field):
    assert "mismatch" in invoke(runtime, replace(runtime[3], **{field: object()}))
    runtime[-1].assert_not_called()


def test_disconnected_or_wrong_account_denies(runtime):
    runtime[2].connected = False
    assert invoke(runtime) == "canonical_kraken_binding_mismatch"


def test_wrong_account_denies(runtime):
    runtime[2].account_type = "user"
    runtime[2].user_id = "synthetic-user"
    assert invoke(runtime) == "canonical_kraken_binding_mismatch"


def test_duplicate_registration_denies(runtime):
    invoke(runtime)
    with pytest.raises(ValueError, match="already_registered"):
        startup.register_reviewed_startup_binding(lambda: None, verify_receipts=lambda: True)


@pytest.mark.parametrize("failure", ["stale", "future", "wrong_account", "wrong_id", "authorizes_orders"])
def test_invalid_evidence_is_not_relabelled_or_refreshed(runtime, failure):
    binding = runtime[3]
    field = next(iter(REQUIRED))
    observation = dict(binding.providers[field]())
    if failure == "stale":
        observation["observed_at_epoch"] -= 120
    elif failure == "future":
        observation["observed_at_epoch"] += 120
    elif failure == "wrong_account":
        observation["account"] = "user:synthetic-user:kraken"
    elif failure == "wrong_id":
        observation["provider_id"] = "unreviewed"
    else:
        observation["authorizes_orders"] = True
    providers = dict(binding.providers)
    providers[field] = lambda: observation
    assert invoke(runtime, replace(binding, providers=providers)) == "collector_registration_failed"
    assert attestation._COLLECTOR is None


def test_exceptions_are_sanitized_and_preserve_existing_collector(runtime):
    sentinel = lambda account: {}
    attestation._COLLECTOR = sentinel

    def deny(binding):
        raise RuntimeError("private-provider-data")

    assert invoke(runtime, verifier=deny) == "release_receipt_verification_failed"
    assert attestation._COLLECTOR is sentinel


def test_registries_are_frozen_copies(runtime):
    providers = dict(runtime[3].providers)
    binding = replace(runtime[3], providers=providers)
    providers.clear()
    assert set(binding.providers) == set(REQUIRED)
    with pytest.raises(TypeError):
        binding.providers["unexpected"] = lambda: {}


def test_canonical_handoff_precedes_core_engine_start():
    tree = ast.parse((Path(__file__).parents[1] / "bot/bot_main.py").read_text())
    main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main")
    calls = {node.func.id: node for node in ast.walk(main)
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    hook = calls["install_from_canonical_startup"]
    assert calls["_publish_canonical_strategy_for_runtime"].lineno < hook.lineno
    assert hook.lineno < calls["start_trading_engine"].lineno
    assert [arg.id for arg in hook.args] == ["manager", "strategy"]


@pytest.mark.parametrize("stage", ["factory", "verifier", "collector"])
def test_startup_failure_stage_is_fixed_and_preserves_registry(runtime, stage):
    sentinel = lambda account: {}
    attestation._COLLECTOR = sentinel

    def private_failure(*args, **kwargs):
        raise RuntimeError("private-provider-response-must-never-escape")

    manager, strategy, _, binding, verifier = runtime
    factory = (lambda **kwargs: binding)
    expected = "collector_registration_failed"
    if stage == "factory":
        factory = private_failure
        expected = "startup_binding_factory_failed"
    elif stage == "verifier":
        verifier = private_failure
        expected = "release_receipt_verification_failed"
    else:
        providers = dict(binding.providers)
        providers[REQUIRED[0]] = private_failure
        binding = replace(binding, providers=providers)
    startup.register_reviewed_startup_binding(factory, verify_receipts=verifier)
    assert startup.install_from_canonical_startup(manager, strategy) == expected
    assert attestation._COLLECTOR is sentinel
    if stage == "factory":
        runtime[-1].assert_not_called()
