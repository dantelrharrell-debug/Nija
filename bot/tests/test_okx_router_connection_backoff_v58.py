from __future__ import annotations

import importlib
import os
from types import SimpleNamespace

import pytest


@pytest.fixture()
def mod(monkeypatch):
    names = (
        "NIJA_DISABLE_OKX",
        "ENABLE_OKX_TRADING",
        "OKX_LIVE_TRADING_ENABLED",
        "NIJA_OKX_EXECUTION_ENABLED",
        "NIJA_OKX_LIVE_TRADING_ENABLED",
        "OKX_API_KEY",
        "OKX_PLATFORM_API_KEY",
        "OKX_API_SECRET",
        "OKX_PLATFORM_API_SECRET",
        "OKX_PASSPHRASE",
        "OKX_API_PASSPHRASE",
        "OKX_PLATFORM_PASSPHRASE",
        "NIJA_OKX_CREDENTIALS_QUARANTINED",
        "NIJA_OKX_CREDENTIAL_QUARANTINE_CODE",
        "NIJA_OKX_RECONNECT_DISABLED",
        "NIJA_OKX_ACTIVATION_STATE",
        "NIJA_OKX_TRADING_READY",
        "NIJA_OKX_FULLY_CONNECTED",
        "NIJA_OKX_ENTRY_ISOLATED",
        "NIJA_OKX_RETRY_STATE",
        "NIJA_OKX_NEXT_RETRY_S",
        "NIJA_WRITER_HEARTBEAT_ACTIVE",
        "NIJA_KRAKEN_TRADING_READY",
        "NIJA_COINBASE_TRADING_READY",
    )
    for name in names:
        monkeypatch.delenv(name, raising=False)
    module = importlib.import_module("bot.okx_router_connection_convergence_patch")
    monkeypatch.setattr(module, "_LAST_DIAGNOSTIC", "")
    return module


def _credentials(monkeypatch):
    monkeypatch.setenv("OKX_API_KEY", "key")
    monkeypatch.setenv("OKX_API_SECRET", "secret")
    monkeypatch.setenv("OKX_PASSPHRASE", "pass")


def test_explicit_disable_is_terminal_and_venue_local(mod, monkeypatch):
    monkeypatch.setenv("NIJA_DISABLE_OKX", "1")
    monkeypatch.setenv("NIJA_KRAKEN_TRADING_READY", "1")
    monkeypatch.setenv("NIJA_COINBASE_TRADING_READY", "1")

    enabled, reason = mod._okx_enabled()
    assert enabled is False
    assert "NIJA_DISABLE_OKX" in reason

    mod._publish_terminal("disabled", reason)

    assert os.environ["NIJA_OKX_ACTIVATION_STATE"] == "disabled"
    assert os.environ["NIJA_OKX_TRADING_READY"] == "0"
    assert os.environ["NIJA_OKX_RECONNECT_DISABLED"] == "1"
    assert os.environ["NIJA_OKX_ENTRY_ISOLATED"] == "1"
    assert os.environ["NIJA_KRAKEN_TRADING_READY"] == "1"
    assert os.environ["NIJA_COINBASE_TRADING_READY"] == "1"


def test_missing_credentials_becomes_terminal_without_connect(mod, monkeypatch):
    monkeypatch.setenv("NIJA_KRAKEN_TRADING_READY", "1")
    monkeypatch.setattr(mod, "_runtime_broker", lambda: (_ for _ in ()).throw(AssertionError("broker lookup must not run")))

    assert mod._converge_connection() is False

    assert os.environ["NIJA_OKX_ACTIVATION_STATE"] == "blocked_credentials"
    assert os.environ["NIJA_OKX_RECONNECT_DISABLED"] == "1"
    assert os.environ["NIJA_KRAKEN_TRADING_READY"] == "1"


def test_fatal_auth_exception_is_terminal(mod, monkeypatch):
    _credentials(monkeypatch)
    monkeypatch.setenv("NIJA_WRITER_HEARTBEAT_ACTIVE", "1")
    monkeypatch.setenv("NIJA_KRAKEN_TRADING_READY", "1")

    class Broker:
        connected = False

        def connect(self):
            raise RuntimeError("50111 invalid API key")

    broker = Broker()
    monkeypatch.setattr(mod, "_runtime_broker", lambda: (object(), broker))
    monkeypatch.setattr(mod, "_attempt_existing_broker_recovery", lambda manager, current: current)

    assert mod._converge_connection() is False

    assert os.environ["NIJA_OKX_ACTIVATION_STATE"] == "authentication_failed"
    assert os.environ["NIJA_OKX_RECONNECT_DISABLED"] == "1"
    assert os.environ["NIJA_OKX_ENTRY_ISOLATED"] == "1"
    assert os.environ["NIJA_KRAKEN_TRADING_READY"] == "1"


def test_transient_connect_failure_uses_backoff_not_terminal(mod, monkeypatch):
    _credentials(monkeypatch)
    monkeypatch.setenv("NIJA_WRITER_HEARTBEAT_ACTIVE", "1")

    class Broker:
        connected = False

        def connect(self):
            raise TimeoutError("temporary network timeout")

    broker = Broker()
    monkeypatch.setattr(mod, "_runtime_broker", lambda: (object(), broker))
    monkeypatch.setattr(mod, "_attempt_existing_broker_recovery", lambda manager, current: current)

    assert mod._converge_connection() is False
    assert os.environ["NIJA_OKX_ACTIVATION_STATE"] == "connection_failed"
    assert os.environ.get("NIJA_OKX_RECONNECT_DISABLED", "0") != "1"
    assert mod._retry_delay(0, "connection_failed") == 2.0
    assert mod._retry_delay(1, "connection_failed") == 5.0
    assert mod._retry_delay(6, "connection_failed") == 300.0
    assert mod._retry_delay(99, "connection_failed") == 300.0


def test_watchdog_stops_immediately_on_terminal_state(mod, monkeypatch):
    calls = {"connection": 0, "sleep": 0}

    monkeypatch.setattr(mod, "_converge_router", lambda: True)

    def terminal_connection():
        calls["connection"] += 1
        mod._publish_terminal("credential_quarantined", "credential_code=50111")
        return False

    monkeypatch.setattr(mod, "_converge_connection", terminal_connection)
    monkeypatch.setattr(mod.time, "sleep", lambda seconds: calls.__setitem__("sleep", calls["sleep"] + 1))

    mod._watchdog()

    assert calls["connection"] == 1
    assert calls["sleep"] == 0
    assert os.environ["NIJA_OKX_ACTIVATION_STATE"] == "credential_quarantined"


def test_watchdog_quarantines_transient_failures_after_four_attempts(mod, monkeypatch):
    calls = {"connection": 0}
    delays = []

    monkeypatch.setattr(mod, "_MAX_TRANSIENT_ATTEMPTS", 4)
    monkeypatch.setattr(mod, "_converge_router", lambda: True)

    def transient_connection():
        calls["connection"] += 1
        mod._set_state("connection_failed")
        return False

    monkeypatch.setattr(mod, "_converge_connection", transient_connection)
    monkeypatch.setattr(mod.time, "sleep", lambda seconds: delays.append(seconds))

    mod._watchdog()

    assert calls["connection"] == 4
    assert delays == [2.0, 5.0, 15.0, 30.0]
    assert os.environ["NIJA_OKX_ENTRY_ISOLATED"] == "1"
    assert os.environ["NIJA_OKX_RETRY_STATE"] == "exhausted"
    assert os.environ["NIJA_OKX_ACTIVATION_STATE"] == "transient_quarantined"


def test_fatal_auth_classifier_is_narrow(mod):
    assert mod._looks_fatal_auth("RuntimeError:50111 invalid API key") is True
    assert mod._looks_fatal_auth("403 forbidden") is True
    assert mod._looks_fatal_auth("TimeoutError:temporary network timeout") is False
    assert mod._looks_fatal_auth("ConnectionError:peer reset") is False
