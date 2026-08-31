from __future__ import annotations

import importlib
import os
import sys
import threading
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / "bot" / "runtime_activation_liveness_v321_patch.py"
V320 = ROOT / "bot" / "runtime_platform_position_sync_isolation_v320_patch.py"


def _module():
    return importlib.import_module("bot.runtime_activation_liveness_v321_patch")


def test_v321_static_safety_contract_and_v320_chain() -> None:
    text = PATCH.read_text(encoding="utf-8")
    v320 = V320.read_text(encoding="utf-8")

    assert "_platform_candidates" in text
    assert "NIJA_EXECUTION_READY_VENUES" in text
    assert "_FLIGHTS" in text
    assert "duplicate_private_read=false" in text
    assert "ordinary_orders_unchanged=true" in text
    assert "position_snapshot_ttl_unchanged=true" in text
    assert "readiness_fabricated=false" in text
    assert "execution_proof_fabricated=false" in text
    assert "forced_activation=false" in text
    assert "safety_gates_bypassed=false" in text
    assert "runtime_activation_liveness_v321_patch" in v320
    assert "activation_liveness_v321=true" in v320

    forbidden = (
        "NIJA_EXECUTION_READY_VENUES\"] =",
        "NIJA_RUNTIME_TRADING_STATE\"] = \"LIVE_ACTIVE\"",
        "_startup_position_sync_adopted = True",
        "_startup_position_sync_fetch_ok = True",
        "place_market_order(",
        "place_order(",
        "_FLIGHTS.pop(",
        "_FLIGHT_CANCEL",
    )
    for token in forbidden:
        assert token not in text


def test_v321_strong_platform_discovery_delegates_to_v285(monkeypatch) -> None:
    patch = _module()
    broker = object()
    fake_v285 = types.ModuleType("bot.runtime_authoritative_position_coverage_v285_patch")
    fake_v285._platform_candidates = lambda manager: [("kraken", broker)]
    monkeypatch.setitem(sys.modules, fake_v285.__name__, fake_v285)

    assert patch._strong_platform_candidates(object()) == [("kraken", broker)]


def test_v321_heartbeat_busy_failover_uses_only_another_canonical_ready_venue(monkeypatch) -> None:
    patch = _module()

    class Broker:
        def __init__(self, name: str) -> None:
            self.name = name
            self.broker_type = name

    class AliveWorker:
        def is_alive(self) -> bool:
            return True

    kraken = Broker("kraken")
    coinbase = Broker("coinbase")

    fake_v210 = types.ModuleType("bot.runtime_heartbeat_auth_probe_bound_v210_patch")
    fake_v210._LOCK = threading.RLock()
    fake_v210._AUTH_READ_METHODS = ("get_account_balance",)
    fake_v210._FLIGHTS = {(id(kraken), "get_account_balance"): AliveWorker()}
    monkeypatch.setitem(sys.modules, fake_v210.__name__, fake_v210)
    monkeypatch.setenv("NIJA_EXECUTION_READY_VENUES", "kraken,coinbase")

    class Manager:
        platform_brokers = {"kraken": kraken, "coinbase": coinbase}

    class Strategy:
        multi_account_manager = Manager()
        broker_manager = None
        broker = None

        @staticmethod
        def _broker_key_from_obj(broker):
            return broker.name

        def _select_entry_broker(self, candidates):
            values = list(candidates.values())
            if not values:
                return None, "", "none"
            selected = values[0]
            return selected, selected.name, "ok"

    strategy = Strategy()

    def original(self):
        return kraken

    wrapped = patch._wrap_heartbeat_selector(original)
    thread = threading.current_thread()
    prior_name = thread.name
    thread.name = "HeartbeatTrade"
    try:
        selected = wrapped(strategy)
    finally:
        thread.name = prior_name

    assert selected is coinbase
    assert strategy.broker is coinbase
    assert fake_v210._FLIGHTS[(id(kraken), "get_account_balance")].is_alive()
    assert os.environ["NIJA_EXECUTION_READY_VENUES"] == "kraken,coinbase"


def test_v321_does_not_change_selection_outside_heartbeat_thread(monkeypatch) -> None:
    patch = _module()

    class Broker:
        broker_type = "kraken"

    broker = Broker()
    fake_v210 = types.ModuleType("bot.runtime_heartbeat_auth_probe_bound_v210_patch")
    fake_v210._LOCK = threading.RLock()
    fake_v210._AUTH_READ_METHODS = ("get_account_balance",)
    fake_v210._FLIGHTS = {}
    monkeypatch.setitem(sys.modules, fake_v210.__name__, fake_v210)

    class Strategy:
        pass

    wrapped = patch._wrap_heartbeat_selector(lambda self: broker)
    assert wrapped(Strategy()) is broker
