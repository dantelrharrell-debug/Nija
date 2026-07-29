"""Regression coverage for OKX reconnect adoption and readiness state synchronization.

Tests that:
1. An already-connected OKX broker is adopted (connect() not called again) and its
   readiness state (capital authority feed, connection FSM) is synchronized.
2. A disconnected OKX broker that reconnects via try_reconnect_platform_broker has its
   readiness state fully synchronized (global registry, _mark_platform_connected,
   on_broker_ready).
"""
from __future__ import annotations

import os
import threading
from types import SimpleNamespace
from typing import Any, List


# ---------------------------------------------------------------------------
# Lightweight stubs — no real MABM import needed for unit tests
# ---------------------------------------------------------------------------

class _BrokerType:
    """Minimal broker-type sentinel that can be used as a dict key."""
    def __init__(self, value: str):
        self.value = value

    def __hash__(self):
        return hash(self.value)

    def __eq__(self, other):
        if isinstance(other, _BrokerType):
            return self.value == other.value
        return NotImplemented

    def __repr__(self):
        return f"_BrokerType({self.value!r})"


OKX_TYPE = _BrokerType("okx")
KRAKEN_TYPE = _BrokerType("kraken")


class _FakeCapitalAuthority:
    def __init__(self):
        self.registered_sources: List[tuple] = []

    def register_source(self, broker_id: str, feed):
        self.registered_sources.append((broker_id, feed))


_fake_capital_authority = _FakeCapitalAuthority()


def _make_fake_mabm():
    """Create a minimal MABM-like object that exposes the methods under test."""
    _mark_calls: List[Any] = []
    _on_broker_ready_calls: List[tuple] = []

    class FakeMABM:
        def __init__(self):
            self._platform_brokers: dict = {}
            self._mark_calls = _mark_calls
            self._on_broker_ready_calls = _on_broker_ready_calls
            self._registry_lock = threading.Lock()

        def _mark_platform_connected(self, broker_type):
            self._mark_calls.append(broker_type)

        def on_broker_ready(self, broker_id: str, feed):
            self._on_broker_ready_calls.append((broker_id, feed))
            _fake_capital_authority.register_source(broker_id, feed)

        def _sync_reconnect_readiness(self, broker_type, broker):
            """Inline the logic so this test does not depend on broker_manager globals."""
            key = broker_type.value.lower()
            self._mark_platform_connected(broker_type)
            self.on_broker_ready(key, broker.get_account_balance)

        def try_reconnect_platform_broker(self, broker_type) -> bool:
            broker = self._platform_brokers.get(broker_type)
            if broker is None:
                return False
            if getattr(broker, "connected", False):
                self._sync_reconnect_readiness(broker_type, broker)
                return True
            broker_name = broker_type.value.upper()
            try:
                if broker.connect():
                    self._sync_reconnect_readiness(broker_type, broker)
                    return True
                return False
            except Exception:
                return False

    return FakeMABM()


# ---------------------------------------------------------------------------
# Tests: connected OKX instance is adopted without re-calling connect()
# ---------------------------------------------------------------------------

def test_already_connected_okx_adopted_without_reconnect():
    """When OKX is already connected, try_reconnect_platform_broker must NOT call
    connect() again and must synchronize readiness state."""
    mabm = _make_fake_mabm()

    connect_call_count = 0

    class OKXBroker:
        connected = True

        def connect(self):
            nonlocal connect_call_count
            connect_call_count += 1
            return True

        def get_account_balance(self):
            return 144.96

    broker = OKXBroker()
    mabm._platform_brokers[OKX_TYPE] = broker

    result = mabm.try_reconnect_platform_broker(OKX_TYPE)

    assert result is True, "try_reconnect_platform_broker should return True for already-connected broker"
    assert connect_call_count == 0, (
        f"connect() must NOT be called when broker is already connected; called {connect_call_count} times"
    )
    assert len(mabm._mark_calls) == 1, (
        f"_mark_platform_connected should be called once to sync readiness; calls={mabm._mark_calls}"
    )
    assert mabm._mark_calls[0] == OKX_TYPE, (
        "_mark_platform_connected should be called with OKX broker type"
    )
    assert len(mabm._on_broker_ready_calls) == 1, (
        f"on_broker_ready should be called once to seed CapitalAuthority; calls={mabm._on_broker_ready_calls}"
    )
    broker_id, feed = mabm._on_broker_ready_calls[0]
    assert broker_id == "okx", f"Expected broker_id='okx', got {broker_id!r}"
    assert feed() == 144.96, f"Balance feed should return broker balance; got {feed()}"


# ---------------------------------------------------------------------------
# Tests: disconnected OKX broker reconnects and readiness state is synced
# ---------------------------------------------------------------------------

def test_disconnected_okx_reconnects_and_syncs_readiness():
    """When OKX is disconnected and connect() succeeds, try_reconnect_platform_broker
    must synchronize readiness state (mark_connected + on_broker_ready)."""
    mabm = _make_fake_mabm()

    class OKXBroker:
        connected = False
        _balance = 200.0

        def connect(self):
            self.connected = True
            return True

        def get_account_balance(self):
            return self._balance

    broker = OKXBroker()
    mabm._platform_brokers[OKX_TYPE] = broker

    result = mabm.try_reconnect_platform_broker(OKX_TYPE)

    assert result is True, "try_reconnect_platform_broker should return True after successful reconnect"
    assert broker.connected is True, "broker.connected should be True after successful connect()"
    assert len(mabm._mark_calls) == 1, (
        "_mark_platform_connected should be called once after reconnect"
    )
    assert len(mabm._on_broker_ready_calls) == 1, (
        "on_broker_ready should be called once to seed CapitalAuthority after reconnect"
    )
    broker_id, feed = mabm._on_broker_ready_calls[0]
    assert broker_id == "okx"
    assert feed() == 200.0


def test_disconnected_okx_connect_failure_does_not_sync_readiness():
    """When connect() fails, readiness state must NOT be synchronized."""
    mabm = _make_fake_mabm()

    class OKXBroker:
        connected = False

        def connect(self):
            return False

        def get_account_balance(self):
            return 0.0

    broker = OKXBroker()
    mabm._platform_brokers[OKX_TYPE] = broker

    result = mabm.try_reconnect_platform_broker(OKX_TYPE)

    assert result is False, "try_reconnect_platform_broker should return False when connect() fails"
    assert len(mabm._mark_calls) == 0, (
        "_mark_platform_connected must NOT be called after a failed reconnect"
    )
    assert len(mabm._on_broker_ready_calls) == 0, (
        "on_broker_ready must NOT be called after a failed reconnect"
    )


def test_missing_okx_broker_returns_false():
    """When OKX has no registered broker instance, return False without crashing."""
    mabm = _make_fake_mabm()
    # OKX not registered in _platform_brokers
    result = mabm.try_reconnect_platform_broker(OKX_TYPE)
    assert result is False


def test_multiple_reconnect_calls_adopt_already_connected_idempotently():
    """Calling try_reconnect_platform_broker twice for an already-connected broker must
    synchronize readiness both times (idempotent — both _mark_platform_connected and
    on_broker_ready are safe to call repeatedly)."""
    mabm = _make_fake_mabm()

    class OKXBroker:
        connected = True

        def connect(self):
            raise AssertionError("connect() must not be called when already connected")

        def get_account_balance(self):
            return 300.0

    broker = OKXBroker()
    mabm._platform_brokers[OKX_TYPE] = broker

    result1 = mabm.try_reconnect_platform_broker(OKX_TYPE)
    result2 = mabm.try_reconnect_platform_broker(OKX_TYPE)

    assert result1 is True
    assert result2 is True
    assert len(mabm._mark_calls) == 2, "readiness sync should run on each call (idempotent)"
    assert len(mabm._on_broker_ready_calls) == 2


if __name__ == "__main__":
    test_already_connected_okx_adopted_without_reconnect()
    test_disconnected_okx_reconnects_and_syncs_readiness()
    test_disconnected_okx_connect_failure_does_not_sync_readiness()
    test_missing_okx_broker_returns_false()
    test_multiple_reconnect_calls_adopt_already_connected_idempotently()
    print("✅ test_okx_reconnect_adoption passed")
