from __future__ import annotations

import os
import sys
from types import ModuleType

import critical_runtime_repairs_v10 as repair


def test_coinbase_terminal_owner_blocks_recursive_connect_and_publishes_private_probe(monkeypatch):
    funding = ModuleType("bot.coinbase_funding_readiness_repair_patch")
    funding.recover_coinbase_environment = lambda: True
    funding._measure_spendable = lambda broker: 42.5
    funding._publish_ready = lambda spendable: os.environ.__setitem__("TEST_SPENDABLE", str(spendable))
    terminal = ModuleType("coinbase_connect_recursion_terminal_guard")
    terminal._private_probe = lambda broker: (True, "FakeCoinbase.get_accounts")
    monkeypatch.setitem(sys.modules, funding.__name__, funding)
    monkeypatch.setitem(sys.modules, terminal.__name__, terminal)

    class CoinbaseBroker:
        def connect(self):
            return self.connect()

    assert repair._patch_coinbase_class(CoinbaseBroker)
    broker = CoinbaseBroker()
    assert broker.connect() is True
    assert broker.connected is True
    assert os.environ["NIJA_COINBASE_CONNECTED"] == "1"
    assert os.environ["NIJA_COINBASE_SPENDABLE_QUOTE"] == "42.50000000"
    assert getattr(CoinbaseBroker.connect, "_nija_coinbase_failfast_20260713b") is True
    assert getattr(CoinbaseBroker.connect, "_nija_coinbase_connection_funding_v3") is True


def test_okx_terminal_owner_prevents_same_thread_reentry(monkeypatch):
    class OKXBroker:
        def __init__(self):
            self.connected = False
            self.base_url = ""

        def connect(self):
            return self.connect()

    monkeypatch.setenv("OKX_BASE_URL", "https://us.okx.com")
    assert repair._patch_okx_class(OKXBroker)
    broker = OKXBroker()
    assert broker.connect() is False
    assert broker.connected is False
    assert broker.base_url == "https://us.okx.com"
    assert os.environ["NIJA_OKX_FUNDING_STATUS"] == "connect_recursion_blocked"
    assert getattr(OKXBroker.connect, "_nija_final_okx_endpoint_e") is True


def test_zero_signal_state_repair_is_reapplied(monkeypatch):
    calls = []
    patch = ModuleType("bot.zero_signal_streak_state_repair_patch")
    patch._install_on_core_loop = lambda module: calls.append(module.__name__) or True
    core = ModuleType("bot.nija_core_loop")
    monkeypatch.setitem(sys.modules, patch.__name__, patch)
    monkeypatch.setitem(sys.modules, core.__name__, core)

    assert repair._repair_zero_signal_state() is True
    assert calls == ["bot.nija_core_loop"]


def test_unwrap_detects_cycles():
    def first():
        return None

    def second():
        return None

    first.__wrapped__ = second
    second.__wrapped__ = first
    _base, depth, cycle = repair._unwrap(first)
    assert cycle is True
    assert depth >= 2
