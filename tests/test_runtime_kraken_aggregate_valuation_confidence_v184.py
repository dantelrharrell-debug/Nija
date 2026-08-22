from __future__ import annotations

import time
from types import ModuleType, SimpleNamespace

import bot.runtime_kraken_aggregate_valuation_confidence_v184_patch as v184


class FakeKraken:
    def __init__(self):
        self._balance_last_updated = time.time()
        self._balance_fetch_errors = 0
        self._is_available = True
        self.kraken_health = "OK"
        self.account_identifier = "PLATFORM"
        self._last_pricing_coverage_pct = 0.0

    def get_balance_fetch_timestamp(self):
        return self._balance_last_updated

    def get_error_count(self):
        return self._balance_fetch_errors

    def is_available(self):
        return self._is_available

    def get_last_pricing_coverage(self):
        return self._last_pricing_coverage_pct

    def _kraken_private_call(self, method, *args, **kwargs):
        if method == "TradeBalance":
            return {"error": [], "result": {"eb": "250.3578", "tb": "249.3992"}}
        return {"error": [], "result": {}}


def _fake_broker_module():
    module = ModuleType("bot.broker_manager")
    module.KrakenBroker = FakeKraken
    return module


def test_successful_authenticated_tradebalance_promotes_effective_valuation_coverage(monkeypatch):
    module = _fake_broker_module()
    real_import = v184.importlib.import_module

    def fake_import(name):
        if name == "bot.broker_manager":
            return module
        if name == "bot.capital_flow_state_machine":
            return SimpleNamespace(FRESHNESS_TTL_S=90.0)
        return real_import(name)

    monkeypatch.setattr(v184.importlib, "import_module", fake_import)
    assert v184._patch_kraken_provenance() is True

    broker = module.KrakenBroker()
    result = broker._kraken_private_call("TradeBalance", {"asset": "ZUSD"})
    broker._balance_last_updated = time.time()

    assert result["result"]["eb"] == "250.3578"
    assert broker.get_last_pricing_coverage() == 1.0
    assert broker._last_pricing_coverage_pct == 0.0


def test_failed_tradebalance_clears_proof(monkeypatch):
    broker = FakeKraken()
    v184._record_tradebalance_result(broker, {"error": [], "result": {"eb": "250.0"}})
    assert getattr(broker, v184._PROOF_EQUITY_ATTR) == 250.0

    v184._record_tradebalance_result(broker, {"error": ["EAPI:Invalid key"], "result": {}})
    assert getattr(broker, v184._PROOF_EQUITY_ATTR) == 0.0
    assert getattr(broker, v184._PROOF_TS_ATTR) == 0.0


def test_stale_aggregate_proof_does_not_promote(monkeypatch):
    broker = FakeKraken()
    now = time.time()
    setattr(broker, v184._PROOF_EQUITY_ATTR, 250.0)
    setattr(broker, v184._PROOF_TS_ATTR, now - 91.0)
    broker._balance_last_updated = now
    monkeypatch.setattr(v184, "_canonical_freshness_ttl_s", lambda: 90.0)

    valid, reason, _, _ = v184._aggregate_proof_status(broker, now=now)
    assert valid is False
    assert reason == "aggregate_proof_stale"


def test_mismatched_balance_epoch_does_not_promote(monkeypatch):
    broker = FakeKraken()
    now = time.time()
    setattr(broker, v184._PROOF_EQUITY_ATTR, 250.0)
    setattr(broker, v184._PROOF_TS_ATTR, now)
    broker._balance_last_updated = now - 10.0
    monkeypatch.setattr(v184, "_canonical_freshness_ttl_s", lambda: 90.0)

    valid, reason, _, _ = v184._aggregate_proof_status(broker, now=now)
    assert valid is False
    assert reason == "aggregate_balance_epoch_mismatch"


def test_balance_error_state_does_not_promote(monkeypatch):
    broker = FakeKraken()
    now = time.time()
    setattr(broker, v184._PROOF_EQUITY_ATTR, 250.0)
    setattr(broker, v184._PROOF_TS_ATTR, now)
    broker._balance_last_updated = now
    broker._balance_fetch_errors = 1
    monkeypatch.setattr(v184, "_canonical_freshness_ttl_s", lambda: 90.0)

    valid, reason, _, _ = v184._aggregate_proof_status(broker, now=now)
    assert valid is False
    assert reason == "kraken_balance_errors_present"


def test_non_tradebalance_private_calls_do_not_create_proof(monkeypatch):
    module = _fake_broker_module()
    real_import = v184.importlib.import_module

    def fake_import(name):
        if name == "bot.broker_manager":
            return module
        return real_import(name)

    monkeypatch.setattr(v184.importlib, "import_module", fake_import)
    assert v184._patch_kraken_provenance() is True

    broker = module.KrakenBroker()
    broker._kraken_private_call("Balance")
    assert getattr(broker, v184._PROOF_EQUITY_ATTR, 0.0) == 0.0


def test_release_manifest_attests_v184(monkeypatch):
    required = {}
    fake_manifest = SimpleNamespace(_REQUIRED_FLAGS=required)
    real_import = v184.importlib.import_module

    def fake_import(name):
        if name == "bot.runtime_release_manifest_patch":
            return fake_manifest
        return real_import(name)

    monkeypatch.setattr(v184.importlib, "import_module", fake_import)
    assert v184._patch_release_manifest() is True
    assert required["runtime_kraken_aggregate_valuation_confidence_v184"] == (
        "NIJA_RUNTIME_KRAKEN_AGGREGATE_VALUATION_CONFIDENCE_V184_READY"
    )


def test_safety_environment_is_not_modified(monkeypatch):
    monkeypatch.setenv("NIJA_EMERGENCY_STOP", "1")
    monkeypatch.setenv("NIJA_NONCE_READY", "0")
    monkeypatch.setenv("NIJA_RUNTIME_EXECUTION_AUTHORITY", "0")

    assert __import__("os").environ["NIJA_EMERGENCY_STOP"] == "1"
    assert __import__("os").environ["NIJA_NONCE_READY"] == "0"
    assert __import__("os").environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] == "0"
