from __future__ import annotations

import base64
import json
from types import ModuleType

from bot import coinbase_funding_readiness_repair_patch as patch


def test_combined_json_recovers_key_and_private_key(monkeypatch):
    pem = "-----BEGIN EC PRIVATE KEY-----\nQUJDREVGRw==\n-----END EC PRIVATE KEY-----\n"
    monkeypatch.setenv(
        "COINBASE_CDP_CREDENTIALS",
        json.dumps({"name": "organizations/test/apiKeys/key", "privateKey": pem.replace("\n", "\\n")}),
    )
    monkeypatch.delenv("COINBASE_API_KEY", raising=False)
    monkeypatch.delenv("COINBASE_API_SECRET", raising=False)
    monkeypatch.delenv("NIJA_COINBASE_BALANCE_OBSERVED", raising=False)
    monkeypatch.delenv("NIJA_COINBASE_FUNDING_STATUS", raising=False)

    assert patch.recover_coinbase_environment() is True
    assert patch.os.environ["COINBASE_API_KEY"] == "organizations/test/apiKeys/key"
    assert patch.os.environ["COINBASE_API_SECRET"].startswith("-----BEGIN EC PRIVATE KEY-----\n")
    assert patch.os.environ["NIJA_COINBASE_BALANCE_OBSERVED"] == "0"
    assert patch.os.environ["NIJA_COINBASE_FUNDING_STATUS"] == "unobserved"


def test_base64_private_key_is_decoded(monkeypatch):
    pem = "-----BEGIN PRIVATE KEY-----\nQUJDREVGRw==\n-----END PRIVATE KEY-----\n"
    monkeypatch.setenv("COINBASE_API_KEY", "organizations/test/apiKeys/key")
    monkeypatch.setenv("COINBASE_API_SECRET", base64.b64encode(pem.encode()).decode())

    assert patch.recover_coinbase_environment() is True
    assert "BEGIN PRIVATE KEY" in patch.os.environ["COINBASE_API_SECRET"]


def test_spendable_payload_sums_usd_and_usdc():
    payload = {
        "usd": 100.0,
        "accounts": {"ignored": 1},
        "wallet": {"currency": "USDC", "available_balance": {"value": "44.29"}},
    }
    assert patch._spendable_from_payload(payload) == 144.29


def test_measure_spendable_ignores_cached_balance_when_client_is_none():
    """A broker with client=None must return 0 from _measure_spendable.

    Cached attributes like _balance_cache must not make an uninitialized client
    appear funded/ready for trading.
    """

    class Broker:
        def __init__(self):
            self.client = None  # uninitialized
            self._balance_cache = {"usd": 999.0, "trading_balance": 999.0}
            self.balance_cache = {"usd": 999.0}

    assert patch._measure_spendable(Broker()) == 0.0


def test_measure_spendable_reads_cache_when_client_is_present():
    """A broker with a live client may use _balance_cache as a fallback."""

    class Broker:
        def __init__(self):
            self.client = object()  # non-None — client is initialised
            self._balance_cache = {"usd": 250.0}

    assert patch._measure_spendable(Broker()) == 250.0


def test_patch_broker_module_detects_marker_inside_wrapper_chain():
    def original(self):
        return True

    def recovery(self):
        return original(self)

    setattr(recovery, patch._PATCH_ATTR, True)
    recovery.__wrapped__ = original

    def outer(self):
        return recovery(self)

    outer.__wrapped__ = recovery

    class CoinbaseBroker:
        connect = outer

    module = ModuleType("bot.broker_manager")
    module.CoinbaseBroker = CoinbaseBroker
    before = CoinbaseBroker.connect

    assert patch._patch_broker_module(module) is True
    assert CoinbaseBroker.connect is before


def test_connect_wrapper_blocks_same_thread_reentry(monkeypatch):
    class CoinbaseBroker:
        def __init__(self):
            self.connected = False
            self._is_available = True

        def connect(self):
            return self.connect()

    module = ModuleType("bot.broker_manager")
    module.CoinbaseBroker = CoinbaseBroker
    monkeypatch.setenv("COINBASE_API_KEY", "organizations/test/apiKeys/key")
    monkeypatch.setenv(
        "COINBASE_API_SECRET",
        "-----BEGIN EC PRIVATE KEY-----\nTEST\n-----END EC PRIVATE KEY-----",
    )

    assert patch._patch_broker_module(module) is True
    broker = CoinbaseBroker()

    assert broker.connect() is False
    assert broker.connected is False
    assert broker._is_available is False
    assert patch.os.environ["NIJA_COINBASE_FUNDING_STATUS"] == "connect_recursion_blocked"
