"""
Safety gate tests for live-mode validation and execution safeguards.
"""

import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, ".")

from bot import trading_state_machine as tsm
from bot.broker_manager import BrokerType
from bot.independent_broker_trader import IndependentBrokerTrader
from bot.minimum_notional_gate import MinimumNotionalGate, NotionalGateConfig
import bot.distributed_nonce_manager as dnm
import bot.independent_broker_trader as ibt


class RecordingEvent:
    def __init__(self) -> None:
        self.wait_calls: list[float | None] = []
        self._is_set = False

    def wait(self, timeout: float | None = None) -> bool:
        self.wait_calls.append(timeout)
        self._is_set = True
        return True

    def is_set(self) -> bool:
        return self._is_set


def test_live_mode_passes_when_reconciliation_not_yet_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """The reconciliation gate should pass (not block) when reconciliation has not run
    yet (status=missing, complete=false).  This avoids the startup race condition where
    MABM tries to activate the state machine before the first trading cycle — and
    therefore before reconciliation has had a chance to run and set the status."""
    monkeypatch.setenv("NIJA_REQUIRE_STARTUP_RECONCILIATION", "true")
    monkeypatch.setenv("NIJA_RECONCILIATION_OVERRIDE", "false")
    monkeypatch.setenv("NIJA_RECONCILIATION_COMPLETE", "false")
    monkeypatch.setenv("NIJA_RECONCILIATION_STATUS", "")
    monkeypatch.setenv("NIJA_SAFE_START_REQUIRED", "false")
    monkeypatch.setenv("NIJA_EMERGENCY_LOCAL_FALLBACK_ACTIVE", "false")
    monkeypatch.setenv("NIJA_RUNTIME_DEGRADED_MODE", "false")
    monkeypatch.setenv("NIJA_BYPASS_STARTUP_RECONCILIATION", "false")

    ok, _ = tsm._startup_reconciliation_gate()
    assert ok, "Gate should pass when reconciliation has not run yet (initial startup)"


def test_live_mode_blocked_with_discrepancies_found(monkeypatch: pytest.MonkeyPatch) -> None:
    """The reconciliation gate must block when reconciliation completed with
    DISCREPANCIES_FOUND and the operator escape valve is not set."""
    monkeypatch.setenv("NIJA_REQUIRE_STARTUP_RECONCILIATION", "true")
    monkeypatch.setenv("NIJA_RECONCILIATION_OVERRIDE", "false")
    monkeypatch.setenv("NIJA_RECONCILIATION_COMPLETE", "true")
    monkeypatch.setenv("NIJA_RECONCILIATION_STATUS", "DISCREPANCIES_FOUND")
    monkeypatch.setenv("NIJA_SAFE_START_REQUIRED", "false")
    monkeypatch.setenv("NIJA_EMERGENCY_LOCAL_FALLBACK_ACTIVE", "false")
    monkeypatch.setenv("NIJA_RUNTIME_DEGRADED_MODE", "false")
    monkeypatch.setenv("NIJA_BYPASS_STARTUP_RECONCILIATION", "false")
    monkeypatch.setenv("NIJA_ALLOW_DISCREPANCY_TRADING", "false")

    ok, reason = tsm._startup_reconciliation_gate()
    assert not ok
    assert "DISCREPANCIES_FOUND" in reason


def test_heartbeat_executes_once(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    marker_path = tmp_path / "heartbeat.flag"
    monkeypatch.setenv("HEARTBEAT_MARKER_PATH", str(marker_path))

    def run_heartbeat_twice() -> int:
        executions = 0
        for _ in range(2):
            if not tsm._heartbeat_verified():
                marker_path.parent.mkdir(parents=True, exist_ok=True)
                marker_path.write_text("verified")
                executions += 1
        return executions

    assert run_heartbeat_twice() == 1


def test_nonce_gate_blocks_execution_on_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NIJA_ENFORCE_NONCE_WRITER_LEASE", "true")
    monkeypatch.setenv("NIJA_NONCE_LEASE_RETRIES", "1")
    monkeypatch.setenv("KRAKEN_PLATFORM_API_KEY", "test-key")

    class DummyDNM:
        def ensure_writer_lock(self, key_id: str) -> None:
            raise RuntimeError("nonce mismatch")

    monkeypatch.setattr(dnm, "get_distributed_nonce_manager", lambda: DummyDNM())

    ok, reason = tsm._nonce_writer_lease_gate()
    assert not ok
    assert "nonce mismatch" in reason


def test_min_notional_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MIN_NOTIONAL_OVERRIDE", "10")
    gate = MinimumNotionalGate(NotionalGateConfig())
    ok, reason = gate.validate_entry_size("BTC-USD", 1.0, broker_name="kraken")
    assert not ok
    assert "below minimum" in (reason or "").lower()


def test_jitter_applied_per_account(monkeypatch: pytest.MonkeyPatch) -> None:
    delays = iter([31.0, 33.0])
    monkeypatch.setattr(ibt.random, "uniform", lambda _a, _b: next(delays))
    monkeypatch.setattr(ibt, "get_platform_account_layer", None)

    trader = IndependentBrokerTrader(MagicMock(), MagicMock())

    event_a = RecordingEvent()
    event_b = RecordingEvent()

    trader.run_user_trading_loop(BrokerType.COINBASE, broker=None, stop_flag=event_a, user_id="user_a")
    trader.run_user_trading_loop(BrokerType.COINBASE, broker=None, stop_flag=event_b, user_id="user_b")

    assert event_a.wait_calls and event_b.wait_calls
    assert event_a.wait_calls[0] != event_b.wait_calls[0]
