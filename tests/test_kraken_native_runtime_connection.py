"""Offline execution of the native broker used by the Render composition root."""
import base64
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import subprocess
import sys
import threading
import types
from unittest.mock import Mock

import pytest

from bot import broker_manager as bm

SECRET = base64.b64encode(b"offline-test-only").decode("ascii")


@pytest.fixture
def runtime(monkeypatch):
    for name in tuple(os.environ):
        if name.startswith(("KRAKEN_", "NIJA_KRAKEN_GATEWAY")):
            monkeypatch.delenv(name)
    monkeypatch.setenv("KRAKEN_PLATFORM_API_KEY", "offline-platform-key")
    monkeypatch.setenv("KRAKEN_PLATFORM_API_SECRET", SECRET)
    manager = types.SimpleNamespace(
        platform_brokers={}, _broker_payload_fsm={},
        _mark_platform_connected=Mock(), has_attempted_connections=lambda: False,
    )
    manager.register_broker = lambda name, broker: manager.platform_brokers.update({name: broker})
    module = types.ModuleType("bot.multi_account_broker_manager")
    module.get_broker_manager = lambda: manager
    module.multi_account_broker_manager = manager
    tracker = types.ModuleType("bot.position_tracker")
    tracker.PositionTracker = Mock()
    monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setitem(sys.modules, tracker.__name__, tracker)
    monkeypatch.setattr(bm, "CONNECTION_STABILITY_AVAILABLE", False)
    monkeypatch.setattr(bm, "CIRCUIT_BREAKER_AVAILABLE", False)
    monkeypatch.setattr(bm, "_KRAKEN_STARTUP_FSM", bm.KrakenStartupFSM())
    monkeypatch.setattr(bm, "_kraken_clock_readiness", lambda: (True, "verified", {}))
    monkeypatch.setattr(bm, "_feed_kraken_platform_capital_authority", Mock())
    monkeypatch.setattr(bm, "get_kraken_rate_profile", None)
    monkeypatch.setattr(bm, "is_nonce_trading_paused", lambda: False)
    monkeypatch.setattr(bm, "get_kraken_api_lock", lambda: threading.RLock())
    monkeypatch.setattr(bm.time, "sleep", lambda _: None)
    monkeypatch.setattr(bm.KrakenBroker, "_initialize_kraken_market_data", Mock())
    monkeypatch.setattr(bm.KrakenBroker, "_initialize_nonce_manager", Mock(return_value=True))
    nonce = Mock()
    nonce._redis = object()
    nonce.get_nonce.return_value = 101
    nonce.get_last_nonce.return_value = 101
    monkeypatch.setattr("bot.distributed_nonce_manager.get_distributed_nonce_manager", lambda: nonce)
    state = types.SimpleNamespace(
        manager=manager, clients=[], nonce=nonce,
        balance={"error": [], "result": {"ZUSD": "100.0"}},
        before_balance=lambda: None,
    )

    class FakeAPI:
        def __init__(self, *, key, secret):
            self.key, self.secret = key, secret
            self.session = Mock()
            self.query_private = Mock(side_effect=self.read)
            state.clients.append(self)

        def read(self, method, params):
            assert method in {"Balance", "TradeBalance"}, "no exchange mutations permitted"
            self._nonce()
            if method == "Balance":
                state.before_balance()
                return state.balance
            return {"error": [], "result": {"eb": "100", "tb": "100"}}

    import krakenex
    import pykrakenapi
    monkeypatch.setattr(krakenex, "API", FakeAPI)
    monkeypatch.setattr(pykrakenapi, "KrakenAPI", lambda api: types.SimpleNamespace(api=api))
    return state


def test_native_authenticated_connection_registers_exact_client_before_probe(runtime):
    broker = bm.KrakenBroker()

    def assert_registered():
        assert runtime.manager.platform_brokers.get("kraken") is broker

    runtime.before_balance = assert_registered
    assert broker.connect() is True
    assert broker.connected is True
    assert broker._is_available is True
    assert broker._connection_stage == "connected"
    assert broker._connection_generation == 1
    assert broker.api is runtime.clients[0]
    assert broker.kraken_api.api is broker.api
    assert broker.nonce_manager is runtime.nonce
    assert bm._KRAKEN_STARTUP_FSM.is_connected
    assert runtime.manager.platform_brokers["kraken"] is broker
    assert [call.args[0] for call in broker.api.query_private.call_args_list] == ["Balance", "TradeBalance"]
    assert broker.connect() is True
    assert len(runtime.clients) == 1


@pytest.mark.parametrize("balance", [
    {"error": ["EAPI:Invalid key"], "result": {}},
    {"error": ["EAPI:Invalid signature"], "result": {}},
    {"error": ["EGeneral:Permission denied"], "result": {}},
    {"result": {"ZUSD": "100"}},
    {"error": [], "result": []},
])
def test_native_failed_auth_or_malformed_reply_discards_all_clients(runtime, balance):
    runtime.balance = balance
    broker = bm.KrakenBroker()
    assert broker.connect() is False
    assert broker.api is None
    assert broker.kraken_api is None
    assert broker.nonce_manager is None
    assert broker._kraken_private_call_nonce is None
    assert broker.connected is False
    assert broker._connection_already_complete is False
    assert broker._is_available is False
    assert not bm._KRAKEN_STARTUP_FSM.is_connected
    assert broker._connection_generation == 0
    runtime.clients[0].session.close.assert_called_once()


@pytest.mark.parametrize("key,secret", [
    ("", ""), ("", SECRET), ("offline-platform-key", ""),
    (" ", SECRET), ("offline-platform-key", "not-base64"),
])
def test_native_invalid_configuration_makes_no_private_requests(runtime, monkeypatch, key, secret):
    monkeypatch.setenv("KRAKEN_PLATFORM_API_KEY", key)
    monkeypatch.setenv("KRAKEN_PLATFORM_API_SECRET", secret)
    broker = bm.KrakenBroker()
    assert broker.connect() is False
    assert runtime.clients == []
    assert broker.credentials_configured is False


def test_native_partial_platform_pair_does_not_mix_with_legacy_secret(runtime, monkeypatch):
    monkeypatch.delenv("KRAKEN_PLATFORM_API_SECRET")
    monkeypatch.setenv("KRAKEN_API_KEY", "offline-other-account")
    monkeypatch.setenv("KRAKEN_API_SECRET", SECRET)
    broker = bm.KrakenBroker()
    assert broker.connect() is False
    assert broker.last_connection_error == "CREDENTIAL_PAIR_MISSING_OR_INCOMPLETE"
    assert not runtime.clients


def test_native_writer_denial_prevents_private_probe(runtime, monkeypatch):
    monkeypatch.setattr(bm.KrakenBroker, "_initialize_nonce_manager", lambda _: False)
    broker = bm.KrakenBroker()
    assert broker.connect() is False
    runtime.clients[0].query_private.assert_not_called()
    assert broker._connection_stage == "writer_authority"
    assert broker.api is None


def test_native_client_not_published_before_writer_and_nonce_binding(runtime, monkeypatch):
    broker = bm.KrakenBroker()

    def verify_unpublished():
        assert broker.api is None
        assert broker.kraken_api is None
        assert broker._initializing_api is runtime.clients[0]
        return True

    monkeypatch.setattr(broker, "_initialize_nonce_manager", verify_unpublished)
    assert broker.connect()
    assert broker._initializing_api is None
    assert broker.api._nonce is broker._kraken_private_call_nonce


def test_native_nonce_lease_failure_discards_unpublished_client(runtime):
    runtime.nonce.ensure_writer_lock.side_effect = RuntimeError("lease unavailable")
    broker = bm.KrakenBroker()
    assert broker.connect() is False
    assert broker.api is None
    assert broker._initializing_api is None
    assert broker.nonce_manager is None
    assert broker._connection_stage == "nonce_ownership"
    runtime.clients[0].query_private.assert_not_called()
    runtime.clients[0].session.close.assert_called_once()


def test_native_missing_client_cannot_reuse_connected_startup_latch(runtime):
    broker = bm.KrakenBroker()
    broker.connected = broker._connection_already_complete = True
    bm._KRAKEN_STARTUP_FSM.mark_connected()
    assert broker.connect() is True
    assert len(runtime.clients) == 1
    assert broker.api is runtime.clients[0]


def test_native_reconnect_failure_and_recovery_use_new_transport(runtime):
    broker = bm.KrakenBroker()
    assert broker.connect()
    first = broker.api
    broker.connected = False
    runtime.balance = {"error": ["EAPI:Invalid key"], "result": {}}
    assert broker.connect() is False
    assert broker.api is None
    assert broker._balance_last_updated is None
    assert broker._available_cash_last_updated is None
    first.session.close.assert_called_once()
    runtime.balance = {"error": [], "result": {"ZUSD": "100"}}
    assert broker.connect()
    assert broker.api is not first
    assert broker.api is not runtime.clients[1]
    assert broker._connection_generation == 2
    assert broker.last_connection_error == ""


def test_native_simultaneous_connects_perform_one_handshake(runtime):
    entered, release = threading.Event(), threading.Event()

    def wait_for_release():
        entered.set()
        assert release.wait(5)

    runtime.before_balance = wait_for_release
    broker = bm.KrakenBroker()
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(broker.connect)
        assert entered.wait(5)
        second = pool.submit(broker.connect)
        release.set()
        assert first.result(timeout=5) is True
        assert second.result(timeout=5) is True
    assert len(runtime.clients) == 1
    assert broker._connection_generation == 1


def test_native_platform_and_user_clients_remain_independent(runtime, monkeypatch):
    platform = bm.KrakenBroker()
    assert platform.connect()
    monkeypatch.setenv("KRAKEN_USER_MEMBER_API_KEY", "offline-member-key")
    monkeypatch.setenv("KRAKEN_USER_MEMBER_API_SECRET", SECRET)
    member = bm.KrakenBroker(account_type=bm.AccountType.USER, user_id="member")
    assert member.connect()
    assert member.api is not platform.api
    assert member.api.key != platform.api.key
    assert runtime.manager.platform_brokers["kraken"] is platform


@pytest.mark.parametrize("variables,expected", [
    ({"KRAKEN_API_KEY": "legacy", "KRAKEN_API_SECRET": "legacy-secret"}, "legacy"),
    ({"KRAKEN_PLATFORM_API_KEY": "canonical", "KRAKEN_API_SECRET": "unrelated"}, "canonical"),
    ({"KRAKEN_MASTER_KEY": "master", "KRAKEN_PRIVATE_KEY": "unrelated"}, ""),
    ({"KRAKEN_MASTER_KEY": "master", "KRAKEN_MASTER_SECRET": "paired"}, "master"),
])
def test_render_alias_normalization_never_builds_hybrid_pairs(variables, expected):
    scripts = Path(__file__).resolve().parents[1] / "scripts"
    assert 'source "${ROOT_DIR}/scripts/kraken_credential_aliases.sh"' in (
        scripts / "render_entrypoint.sh"
    ).read_text()
    assert 'source "${SCRIPT_DIR}/kraken_credential_aliases.sh"' in (
        scripts / "production_bootstrap.sh"
    ).read_text()
    command = (
        'source "$1"; source "$1"; '
        'printf "%s|%s" "${KRAKEN_PLATFORM_API_KEY:-}" "${KRAKEN_PLATFORM_API_SECRET:-}"'
    )
    result = subprocess.run(
        ["bash", "-eu", "-c", command, "_", str(scripts / "kraken_credential_aliases.sh")],
        env={"PATH": os.defpath, **variables},
        check=True, capture_output=True, text=True,
    )
    key, secret = result.stdout.splitlines()[-1].split("|")
    assert key == expected
    if "KRAKEN_PLATFORM_API_KEY" in variables:
        assert secret == ""
    assert "unrelated" not in result.stdout
