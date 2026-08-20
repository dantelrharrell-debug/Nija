from __future__ import annotations

import threading
from types import SimpleNamespace

import bot.runtime_activation_convergence_v163_patch as v163


class BrokerType:
    def __init__(self, value: str):
        self.value = value


class Broker:
    def __init__(self, *, connected=True, adopted=False, fetch_ok=None):
        self.connected = connected
        self._startup_position_sync_adopted = adopted
        self._startup_position_sync_fetch_ok = fetch_ok
        self._startup_position_sync_error = None


class Manager:
    def __init__(self, brokers):
        self.platform_brokers = brokers


def test_position_discovery_requires_fetch_proof_even_when_adopted(monkeypatch):
    coinbase = Broker(adopted=True, fetch_ok=None)
    okx = Broker(adopted=True, fetch_ok=True)
    manager = Manager({BrokerType("coinbase"): coinbase, BrokerType("okx"): okx})

    pending = v163._connected_platform_brokers_requiring_proof(manager)

    assert pending == [("coinbase", coinbase)]


def test_position_discovery_ignores_disconnected_broker(monkeypatch):
    kraken = Broker(connected=False, adopted=False, fetch_ok=False)
    manager = Manager({BrokerType("kraken"): kraken})
    assert v163._connected_platform_brokers_requiring_proof(manager) == []


def test_worker_does_not_finish_on_adopted_without_fetch_proof(monkeypatch):
    broker = Broker(adopted=True, fetch_ok=False)
    manager = Manager({BrokerType("coinbase"): broker})
    calls = []
    published = []

    class FakeSync:
        @staticmethod
        def _get_entry_price_store():
            return None

        @staticmethod
        def _adopt_broker_positions(broker_arg, name, eps):
            calls.append(name)
            broker_arg._startup_position_sync_adopted = True
            if len(calls) == 1:
                broker_arg._startup_position_sync_fetch_ok = False
                broker_arg._startup_position_sync_error = "proof_missing"
            else:
                broker_arg._startup_position_sync_fetch_ok = True
                broker_arg._startup_position_sync_error = None

    fake_v108 = SimpleNamespace(
        _retry_policy=lambda: (3, 0.01, 0.01),
        _publish_readiness=lambda manager, source: published.append(source),
        _ACTIVE=set(),
        _LOCK=threading.RLock(),
    )
    fake_v161 = SimpleNamespace(_startup_sync_module=lambda: FakeSync)
    monkeypatch.setattr(v163, "_v108", lambda: fake_v108)
    monkeypatch.setattr(v163, "_v161", lambda: fake_v161)
    monkeypatch.setattr(v163.time, "sleep", lambda _: None)

    key = (id(manager), id(broker))
    fake_v108._ACTIVE.add(key)
    v163._position_worker_v163(manager, "coinbase", broker, key, "test")

    assert calls == ["platform:coinbase", "platform:coinbase"]
    assert broker._startup_position_sync_adopted is True
    assert broker._startup_position_sync_fetch_ok is True
    assert any(value.endswith("attempt_1") for value in published)
    assert any(value.endswith("attempt_2") for value in published)
    assert key not in fake_v108._ACTIVE


def test_transient_nonce_maturity_is_distinct_from_real_nonce_faults():
    assert v163._transient_nonce_maturity(
        "LIVE TRADING BLOCKED: last_error=nonce lease unstable (stable_for=27.7s required=30.0s)"
    ) is True
    assert v163._transient_nonce_maturity("nonce too low") is False
    assert v163._transient_nonce_maturity(
        "nonce lease unstable; final_verify=lease_identity_changed"
    ) is False
    assert v163._transient_nonce_maturity(
        "nonce lease unstable; final_verify=stability_regressed"
    ) is False


def test_clear_historical_breaker_only_for_transient_maturity():
    tsm = SimpleNamespace(
        _EXECUTION_CIRCUIT_BREAKER_LOCK=threading.Lock(),
        _EXECUTION_CIRCUIT_BREAKER_COUNTS={"nonce_drift": 3, "rejected_orders": 1},
        _EXECUTION_CIRCUIT_BREAKER_TRIPPED=True,
        _EXECUTION_CIRCUIT_BREAKER_REASON=(
            "nonce_drift threshold=3 detail=LIVE TRADING BLOCKED: "
            "nonce lease unstable (stable_for=27.7s required=30.0s)"
        ),
    )

    assert v163._clear_historical_maturity_breaker(tsm) is True
    assert tsm._EXECUTION_CIRCUIT_BREAKER_TRIPPED is False
    assert tsm._EXECUTION_CIRCUIT_BREAKER_REASON == ""
    assert "nonce_drift" not in tsm._EXECUTION_CIRCUIT_BREAKER_COUNTS
    assert tsm._EXECUTION_CIRCUIT_BREAKER_COUNTS["rejected_orders"] == 1


def test_unrelated_breaker_is_not_cleared():
    tsm = SimpleNamespace(
        _EXECUTION_CIRCUIT_BREAKER_LOCK=threading.Lock(),
        _EXECUTION_CIRCUIT_BREAKER_COUNTS={"nonce_drift": 3},
        _EXECUTION_CIRCUIT_BREAKER_TRIPPED=True,
        _EXECUTION_CIRCUIT_BREAKER_REASON="nonce_drift threshold=3 detail=nonce too low",
    )
    assert v163._clear_historical_maturity_breaker(tsm) is False
    assert tsm._EXECUTION_CIRCUIT_BREAKER_TRIPPED is True
