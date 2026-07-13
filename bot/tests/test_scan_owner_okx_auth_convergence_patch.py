from __future__ import annotations

import os
import threading
import time
from types import ModuleType, SimpleNamespace

import scan_owner_okx_auth_convergence_patch as patch


def _result(scored: int = 7):
    return SimpleNamespace(
        symbols_scored=scored,
        entries_taken=1,
        entries_blocked=0,
        exits_taken=0,
        next_interval=30,
        errors=[],
        metadata={},
    )


def test_overlapping_scan_reuses_owner_result(monkeypatch):
    module = ModuleType("bot.nija_core_loop")
    calls = {"count": 0}

    class NijaCoreLoop:
        account_id = "platform"
        broker = SimpleNamespace(account_id="platform", broker_name="kraken")

        def run_scan_phase(self, *args, **kwargs):
            calls["count"] += 1
            time.sleep(0.15)
            return _result(11)

    module.NijaCoreLoop = NijaCoreLoop
    monkeypatch.setenv("NIJA_ACCOUNT_SCAN_LOCK_TIMEOUT_S", "0.01")
    monkeypatch.setenv("NIJA_DUPLICATE_SCAN_RESULT_WAIT_S", "2")
    assert patch._patch_core(module) is True

    loop = NijaCoreLoop()
    results = []
    threads = [threading.Thread(target=lambda: results.append(loop.run_scan_phase(broker=loop.broker))) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=3)

    assert calls["count"] == 1
    assert len(results) == 2
    assert all(result.symbols_scored == 11 for result in results)


def test_identity_prefers_owner_account_when_broker_is_ambiguous():
    broker = SimpleNamespace(broker_name="kraken")
    owner = SimpleNamespace(account_id="tania_gilbert", broker=broker)
    assert patch._identity(broker, owner) == "tania_gilbert:kraken"


def test_okx_recursive_wrappers_are_collapsed(monkeypatch):
    module = ModuleType("bot.broker_manager")
    auth = ModuleType("broker_auth_recovery_patch")
    auth.normalize_okx_environment = lambda: True
    auth.normalize_coinbase_environment = lambda: False
    auth._alternate_okx_url = lambda url: "https://www.okx.com" if "us.okx" in url else ""
    monkeypatch.setitem(__import__("sys").modules, "broker_auth_recovery_patch", auth)
    monkeypatch.setenv("OKX_BASE_URL", "https://us.okx.com")

    calls = {"count": 0}

    class OKXBroker:
        base_url = ""
        connected = False
        client = None

        def connect(self):
            calls["count"] += 1
            return True

    base = OKXBroker.connect

    def wrapper_one(self):
        return wrapper_two(self)

    def wrapper_two(self):
        return wrapper_one(self)

    wrapper_one.__wrapped__ = base
    wrapper_two.__wrapped__ = wrapper_one
    wrapper_one._nija_auth_recovery_20260711n = True
    wrapper_two._nija_auth_v2 = True
    OKXBroker.connect = wrapper_two
    module.OKXBroker = OKXBroker

    assert patch._patch_brokers(module) is True
    broker = OKXBroker()
    assert broker.connect() is True
    assert calls["count"] == 1
    assert broker.base_url == "https://us.okx.com"


def test_invalid_coinbase_pem_isolated_before_base_connect(monkeypatch):
    module = ModuleType("bot.broker_manager")
    auth = ModuleType("broker_auth_recovery_patch")
    auth.normalize_coinbase_environment = lambda: False
    auth.normalize_okx_environment = lambda: True
    monkeypatch.setitem(__import__("sys").modules, "broker_auth_recovery_patch", auth)

    calls = {"count": 0}

    class CoinbaseBroker:
        connected = True

        def connect(self):
            calls["count"] += 1
            raise AssertionError("SDK should not be called")

    module.CoinbaseBroker = CoinbaseBroker
    assert patch._patch_brokers(module) is True
    broker = CoinbaseBroker()
    assert broker.connect() is False
    assert broker.connected is False
    assert calls["count"] == 0
