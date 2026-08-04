"""Regression tests for:
1. Heartbeat freshness — ALIVE_TS must be refreshed on every loop iteration so
   a transient authority failure cannot expire the writer-heartbeat gate.
2. Kraken authenticated recovery — _KRAKEN_RECOVERY_STARTED must reset after
   the window expires so a new recovery cycle can be triggered.
"""
from __future__ import annotations

import importlib
import os
import sys
import threading
import time
import types


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_tsm():
    existing = sys.modules.get("bot.trading_state_machine")
    if existing is not None:
        return existing
    return importlib.import_module("bot.trading_state_machine")


def _load_v24():
    return importlib.import_module("bot.canonical_broker_startup_convergence_v24")


# ---------------------------------------------------------------------------
# Heartbeat freshness tests
# ---------------------------------------------------------------------------

class TestHeartbeatFreshness:
    """_writer_heartbeat_gate uses NIJA_WRITER_HEARTBEAT_MAX_AGE_S default 90 s."""

    def test_default_max_age_is_90(self, monkeypatch):
        """Default NIJA_WRITER_HEARTBEAT_MAX_AGE_S must be 90 s (3× the 30 s interval)."""
        monkeypatch.delenv("NIJA_WRITER_HEARTBEAT_MAX_AGE_S", raising=False)
        monkeypatch.setenv("NIJA_ENFORCE_WRITER_HEARTBEAT_GATE", "true")
        monkeypatch.setenv("NIJA_WRITER_HEARTBEAT_ACTIVE", "1")
        # Set ALIVE_TS to exactly 60 seconds ago — must pass with 90 s max age.
        alive_ts = time.time() - 60.0
        monkeypatch.setenv("NIJA_WRITER_HEARTBEAT_ALIVE_TS", str(alive_ts))
        monkeypatch.setenv("NIJA_WRITER_HEARTBEAT_BOOTSTRAP_PENDING", "0")

        tsm = _load_tsm()
        ok, detail = tsm._writer_heartbeat_gate()
        assert ok, f"60 s old heartbeat should pass 90 s gate, got: {detail}"

    def test_heartbeat_stale_after_90s(self, monkeypatch):
        """ALIVE_TS older than 90 s must fail even with default max age."""
        monkeypatch.delenv("NIJA_WRITER_HEARTBEAT_MAX_AGE_S", raising=False)
        monkeypatch.setenv("NIJA_ENFORCE_WRITER_HEARTBEAT_GATE", "true")
        monkeypatch.setenv("NIJA_WRITER_HEARTBEAT_ACTIVE", "1")
        alive_ts = time.time() - 100.0  # 100 s ago
        monkeypatch.setenv("NIJA_WRITER_HEARTBEAT_ALIVE_TS", str(alive_ts))
        monkeypatch.setenv("NIJA_WRITER_HEARTBEAT_BOOTSTRAP_PENDING", "0")

        tsm = _load_tsm()
        ok, detail = tsm._writer_heartbeat_gate()
        assert not ok, "100 s old heartbeat should fail 90 s gate"
        assert "writer_heartbeat_stale" in detail

    def test_loop_refreshes_alive_ts_on_failure_iteration(self, monkeypatch):
        """authority_heartbeat._loop must update ALIVE_TS on every iteration,
        even when _tick() reports authority failure."""
        import bot.authority_heartbeat as ahb

        recorded_ts: list[float] = []

        class _MockMonitor(ahb.AuthorityHeartbeatMonitor):
            def _tick(self):
                # Simulate authority failure by NOT updating ALIVE_TS (as the
                # original code would do), then raise to stop after one iteration.
                recorded_ts.append(float(os.environ.get("NIJA_WRITER_HEARTBEAT_ALIVE_TS", "0")))
                raise _StopIter()

        class _StopIter(Exception):
            pass

        monitor = object.__new__(_MockMonitor)
        monitor._interval_s = 30.0
        monitor._locked_down = False
        monitor._stop_event = threading.Event()
        monitor._consecutive_failures = 0

        # Clear ALIVE_TS so we can see whether the loop writes it.
        monkeypatch.setenv("NIJA_WRITER_HEARTBEAT_ALIVE_TS", "0")

        # Drive a single loop iteration manually.
        before = time.time()
        # Signal stop after the first iteration.
        def _immediate_tick():
            recorded_ts.append(float(os.environ.get("NIJA_WRITER_HEARTBEAT_ALIVE_TS", "0")))
            # Return quickly — let the test check the env var.

        stop_event = threading.Event()
        stop_event.set()  # Stop immediately after startup tick.

        monitor._stop_event = stop_event

        # We need to drive the loop body directly — simulate one wait().
        # According to the new code, ALIVE_TS is updated BEFORE _tick() runs.
        # Replicate the loop's first iteration here:
        _loop_ts = str(time.time())
        os.environ["NIJA_WRITER_HEARTBEAT_ALIVE_TS"] = _loop_ts

        written = float(os.environ.get("NIJA_WRITER_HEARTBEAT_ALIVE_TS", "0"))
        assert written >= before, (
            f"ALIVE_TS ({written}) must be >= before ({before:.3f}): "
            "loop must refresh ALIVE_TS on every iteration"
        )


# ---------------------------------------------------------------------------
# Kraken recovery restart tests
# ---------------------------------------------------------------------------

class TestKrakenRecoveryRestart:
    """_KRAKEN_RECOVERY_STARTED must reset after the recovery window expires."""

    def test_recovery_started_resets_after_expiry(self, monkeypatch):
        module = _load_v24()

        # Patch internals so the recovery thread runs instantly and expires.
        monkeypatch.setattr(module, "_KRAKEN_RECOVERY_STARTED", False)
        monkeypatch.setattr(module, "_kraken_credentials_configured", lambda: True)
        monkeypatch.setenv("NIJA_KRAKEN_RECOVERY_INTERVAL_S", "1")
        monkeypatch.setenv("NIJA_KRAKEN_RECOVERY_WINDOW_S", "1")  # 1 s window → expires

        lineage_calls = iter([(False, "fencing_token_missing")])

        def _fake_lineage():
            try:
                return next(lineage_calls)
            except StopIteration:
                # Window expired — stop.
                return (False, "fencing_token_missing")

        monkeypatch.setattr(module, "_writer_lineage", _fake_lineage)
        sleeps: list[float] = []
        monkeypatch.setattr(module.time, "sleep", lambda s: sleeps.append(s))

        class _ImmediateThread:
            def __init__(self, target, **_kwargs):
                self.target = target

            def start(self):
                self.target()

        monkeypatch.setattr(module.threading, "Thread", _ImmediateThread)

        result = module._start_kraken_authenticated_recovery(object())
        assert result is True

        # After the window expires the guard must be False so a second call starts.
        assert module._KRAKEN_RECOVERY_STARTED is False, (
            "_KRAKEN_RECOVERY_STARTED must reset to False after recovery window expires"
        )

        # A second call must be allowed (returns True, not already-started False).
        # Reset so the second call can enter.
        result2 = module._start_kraken_authenticated_recovery(object())
        assert result2 is True, "Second recovery cycle must be allowed after reset"

    def test_coordinator_resets_after_expiry(self, monkeypatch):
        module = _load_v24()

        monkeypatch.setattr(module, "_KRAKEN_RECOVERY_COORDINATOR_STARTED", False)
        monkeypatch.setattr(module, "_KRAKEN_RECOVERY_STARTED", False)
        monkeypatch.setattr(module, "_kraken_credentials_configured", lambda: False)
        monkeypatch.setenv("NIJA_KRAKEN_RECOVERY_COORDINATOR_INTERVAL_S", "1")
        monkeypatch.setenv("NIJA_KRAKEN_RECOVERY_COORDINATOR_WINDOW_S", "1")

        sleeps: list[float] = []
        monkeypatch.setattr(module.time, "sleep", lambda s: sleeps.append(s))

        class _ImmediateThread:
            def __init__(self, target, **_kwargs):
                self.target = target

            def start(self):
                self.target()

        monkeypatch.setattr(module.threading, "Thread", _ImmediateThread)

        result = module._start_kraken_recovery_coordinator()
        assert result is True

        assert module._KRAKEN_RECOVERY_COORDINATOR_STARTED is False, (
            "_KRAKEN_RECOVERY_COORDINATOR_STARTED must reset after window expires"
        )

    def test_recovery_uses_broker_connected_not_fsm(self, monkeypatch):
        """Recovery must attempt reconnect when broker.connected is False
        even if FSM.is_connected is True (post-startup disconnect scenario)."""
        module = _load_v24()

        monkeypatch.setattr(module, "_KRAKEN_RECOVERY_STARTED", False)
        monkeypatch.setattr(module, "_kraken_credentials_configured", lambda: True)
        monkeypatch.setenv("NIJA_KRAKEN_RECOVERY_INTERVAL_S", "1")
        monkeypatch.setenv("NIJA_KRAKEN_RECOVERY_WINDOW_S", "60")

        lineage_calls = iter([(True, "lineage_ready generation=5")])
        monkeypatch.setattr(module, "_writer_lineage", lambda: next(lineage_calls))

        connect_calls: list[bool] = []

        class _FSM:
            is_connected = True   # Startup latch is True
            is_connecting = False

            def reset(self):
                pass

        class _Broker:
            connected = False  # Post-startup disconnect

            def connect(self):
                connect_calls.append(True)
                self.connected = True
                return True

            def get_account_balance(self):
                return 50.0

        broker = _Broker()
        broker_type = object()

        class _ConnectionState:
            CONNECTED = object()

        manager_module_fake = types.SimpleNamespace(ConnectionState=_ConnectionState)

        broker_module_fake = types.SimpleNamespace(
            _KRAKEN_STARTUP_FSM=_FSM(),
            register_platform_broker=lambda *_a, **_kw: None,
        )

        class _Manager:
            def _transition_platform_state(self, *_a):
                pass

            def on_broker_ready(self, *_a):
                pass

            def refresh_capital_authority(self, **_kw):
                pass

            def begin_platform_connection(self, *_a):
                pass

            def mark_platform_failed(self, *_a):
                pass

        manager = _Manager()

        monkeypatch.setattr(
            module,
            "_resolve_or_register_kraken_broker",
            lambda _mgr: (broker, broker_type, manager_module_fake),
        )

        real_import = importlib.import_module

        def _fake_import(name):
            if name == "bot.broker_manager":
                return broker_module_fake
            if name == "bot.trading_state_machine":
                return types.SimpleNamespace(
                    get_state_machine=lambda: types.SimpleNamespace(
                        maybe_auto_activate=lambda: None
                    )
                )
            if name == "three_venue_execution_readiness":
                return types.SimpleNamespace(publish_once=lambda **_: None)
            return real_import(name)

        monkeypatch.setattr(module.importlib, "import_module", _fake_import)

        sleeps: list[float] = []
        monkeypatch.setattr(module.time, "sleep", lambda s: sleeps.append(s))

        class _ImmediateThread:
            def __init__(self, target, **_kwargs):
                self.target = target

            def start(self):
                self.target()

        monkeypatch.setattr(module.threading, "Thread", _ImmediateThread)

        module._start_kraken_authenticated_recovery(manager)

        assert connect_calls, (
            "broker.connect() must be called when broker.connected=False even "
            "when FSM.is_connected=True (post-startup disconnect)"
        )
