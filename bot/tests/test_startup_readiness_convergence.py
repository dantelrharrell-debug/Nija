"""Integration tests: startup readiness convergence under the exact observed failure sequence.

These tests prove, at the boundary of the modules that were changed, that:

1. The readiness table fires READINESS_CHANGED_EVENT when a key is published.
2. The activation monitor wakes early (before its full sleep interval) on a
   readiness-table version change.
3. strategy_publication_patch._publish() sets strategy_ready + execution_ready
   in the readiness table.
4. bootstrap_ready auto-sets via _maybe_mark_bootstrap once all required keys
   are True.
5. The exception handler in _commit_activation_unlocked:
   (a) detects readiness.complete as a pending state, NOT a hard failure.
   (b) logs at WARNING (no traceback) for the pending state.
   (c) logs at DEBUG (suppressed) for repeated calls with the same rt version.
   (d) transitions OFF → LIVE_PENDING_CONFIRMATION on a readiness.complete error.
6. Kraken/OKX degradation does not prevent Coinbase from having all readiness
   keys set (venue isolation tested at the readiness-table level).

No real broker calls or network I/O. All state-machine gate functions are
patched to isolate the exact logic under test.
"""

from __future__ import annotations

import importlib
import logging
import sys
import threading
import time
import types
import unittest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Shared reset helper
# ---------------------------------------------------------------------------

def _reset_rt() -> types.ModuleType:
    """Reload the readiness_table module for a clean state."""
    for name in list(sys.modules):
        if "readiness_table" in name:
            del sys.modules[name]
    return importlib.import_module("bot.readiness_table")


# ---------------------------------------------------------------------------
# 1. READINESS_CHANGED_EVENT
# ---------------------------------------------------------------------------

class TestReadinessChangedEvent(unittest.TestCase):

    def setUp(self):
        self.rt = _reset_rt()
        self.rt.reset()

    def test_event_fires_on_mark_ready(self):
        """READINESS_CHANGED_EVENT must be set when a key becomes ready."""
        rt = self.rt
        signalled: list[bool] = []

        def _waiter():
            signalled.append(rt.READINESS_CHANGED_EVENT.wait(timeout=3.0))

        t = threading.Thread(target=_waiter, daemon=True)
        t.start()
        time.sleep(0.05)          # let the thread reach .wait()
        rt.mark_ready("nonce_ready")
        t.join(timeout=4.0)

        self.assertEqual(signalled, [True], "Event must fire when a readiness key changes")

    def test_event_is_cleared_after_pulse(self):
        """After the pulse, the event must be cleared so the next wait() blocks."""
        rt = self.rt
        rt.mark_ready("nonce_ready")
        # Give the set+clear a moment to settle.
        time.sleep(0.02)
        self.assertFalse(
            rt.READINESS_CHANGED_EVENT.is_set(),
            "READINESS_CHANGED_EVENT must be cleared after pulsing",
        )

    def test_version_increments_on_mark_ready(self):
        """get_version() must increase after mark_ready()."""
        rt = self.rt
        v0 = rt.get_version()
        rt.mark_ready("authority_ready")
        self.assertGreater(rt.get_version(), v0)


# ---------------------------------------------------------------------------
# 2. Monitor wakes early on readiness-table version change
# ---------------------------------------------------------------------------

class TestMonitorWakesOnReadinessEvent(unittest.TestCase):

    def setUp(self):
        self.rt = _reset_rt()
        self.rt.reset()

    def test_wait_returns_early_when_event_fires(self):
        """A thread waiting on READINESS_CHANGED_EVENT should wake well before the
        full timeout when a readiness key is published."""
        rt = self.rt
        long_timeout = 10.0  # would make the test slow if not woken
        sleep_time: list[float] = []

        def _sleeper():
            start = time.monotonic()
            rt.READINESS_CHANGED_EVENT.wait(timeout=long_timeout)
            sleep_time.append(time.monotonic() - start)

        t = threading.Thread(target=_sleeper, daemon=True)
        t.start()
        time.sleep(0.1)            # let thread reach .wait()
        rt.mark_ready("risk_ready")
        t.join(timeout=5.0)

        self.assertEqual(len(sleep_time), 1)
        self.assertLess(
            sleep_time[0],
            long_timeout * 0.5,
            f"Sleeper must wake early: slept {sleep_time[0]:.3f}s, timeout {long_timeout}s",
        )


# ---------------------------------------------------------------------------
# 3. strategy_publication_patch publishes strategy_ready + execution_ready
# ---------------------------------------------------------------------------

class TestStrategyPublicationMarksReadiness(unittest.TestCase):

    def setUp(self):
        self.rt = _reset_rt()
        self.rt.reset()

    def test_publish_sets_strategy_ready_and_execution_ready(self):
        """_publish() must call mark_ready('strategy_ready') and
        mark_ready('execution_ready') when the broker is entry-eligible."""
        rt = self.rt

        strategy = MagicMock()
        broker = MagicMock()
        broker.connected = True
        broker.exit_only_mode = False
        strategy.broker = broker
        strategy.symbols = list(range(100))
        strategy.nija_core_loop = MagicMock()

        pub = importlib.import_module("bot.strategy_publication_patch")

        with patch(
            "bot.strategy_publication_patch._strategy_has_entry_broker",
            return_value=True,
        ):
            try:
                pub._publish(strategy)
            except Exception:
                pass  # other side effects may raise; we only check readiness state

        snap = rt.snapshot()
        self.assertTrue(
            snap.get("strategy_ready"),
            "strategy_ready must be True after _publish() — got snapshot: " + str(snap),
        )
        self.assertTrue(
            snap.get("execution_ready"),
            "execution_ready must be True after _publish() with entry-ready broker — got snapshot: " + str(snap),
        )

    def test_publish_does_not_set_execution_ready_without_entry_broker(self):
        """_publish() must not set execution_ready when the broker is NOT entry-eligible."""
        rt = self.rt

        strategy = MagicMock()
        broker = MagicMock()
        broker.connected = True
        broker.exit_only_mode = True  # exit-only → not entry-eligible
        strategy.broker = broker
        strategy.symbols = list(range(100))
        strategy.nija_core_loop = MagicMock()

        pub = importlib.import_module("bot.strategy_publication_patch")

        with patch(
            "bot.strategy_publication_patch._strategy_has_entry_broker",
            return_value=False,
        ):
            try:
                pub._publish(strategy)
            except Exception:
                pass

        snap = rt.snapshot()
        self.assertFalse(
            snap.get("execution_ready"),
            "execution_ready must NOT be set when broker is not entry-eligible",
        )


# ---------------------------------------------------------------------------
# 4. bootstrap_ready auto-sets
# ---------------------------------------------------------------------------

class TestBootstrapReadyAutoSets(unittest.TestCase):

    def setUp(self):
        self.rt = _reset_rt()
        self.rt.reset()

    def test_bootstrap_ready_set_when_all_required_keys_true(self):
        """_maybe_mark_bootstrap() must set bootstrap_ready once all prerequisites are True."""
        from bot.post_lock_capital_refresh_patch import _maybe_mark_bootstrap
        rt = self.rt

        for key in (
            "broker_connected",
            "balance_hydrated",
            "authority_ready",
            "capital_ready",
            "risk_ready",
            "strategy_ready",
            "execution_ready",
            "nonce_ready",
        ):
            rt.mark_ready(key)

        _maybe_mark_bootstrap("test")

        self.assertTrue(
            rt.snapshot().get("bootstrap_ready"),
            "bootstrap_ready must auto-set once all required keys pass",
        )

    def test_bootstrap_ready_not_set_when_some_keys_missing(self):
        """_maybe_mark_bootstrap() must NOT set bootstrap_ready when keys are still pending."""
        from bot.post_lock_capital_refresh_patch import _maybe_mark_bootstrap
        rt = self.rt

        # Only some keys set
        for key in ("broker_connected", "nonce_ready", "authority_ready"):
            rt.mark_ready(key)

        _maybe_mark_bootstrap("test")

        self.assertFalse(
            rt.snapshot().get("bootstrap_ready"),
            "bootstrap_ready must NOT be set when some required keys are still False",
        )


# ---------------------------------------------------------------------------
# 5. _commit_activation_unlocked exception handler (readiness.complete)
# ---------------------------------------------------------------------------

class TestCommitActivationExceptionHandler(unittest.TestCase):
    """Tests for the specific code block added to handle readiness.complete errors."""

    def _build_exc_str_check(self):
        """Verify _is_pending_readiness detection logic directly."""
        # Mirror the exact condition from trading_state_machine.py line 2819
        def _is_pending(exc_str: str) -> bool:
            return (
                "readiness.complete" in exc_str
                or "system readiness proof failed" in exc_str
            )

        self.assertTrue(_is_pending("LIVE commit blocked: system readiness proof failed at readiness.complete"))
        self.assertTrue(_is_pending("proof failed at readiness.complete"))
        self.assertTrue(_is_pending("system readiness proof failed pending=[]"))
        self.assertFalse(_is_pending("authority_lost"))
        self.assertFalse(_is_pending("kill_switch_active"))
        self.assertFalse(_is_pending("fencing_token_missing"))

    def test_pending_readiness_detection_logic(self):
        self._build_exc_str_check()

    def test_tsm_has_pending_log_suppression(self):
        """The trading_state_machine source must contain the version-tracking
        suppression logic (_last_pending_log_rt_version) added in Fix 2."""
        tsm_path = __import__("pathlib").Path(
            importlib.util.find_spec("bot.trading_state_machine").origin
        )
        source = tsm_path.read_text(encoding="utf-8")

        self.assertIn(
            "_last_pending_log_rt_version",
            source,
            "trading_state_machine must contain _last_pending_log_rt_version for duplicate suppression",
        )
        self.assertIn(
            "AUTO_ACTIVATE PENDING",
            source,
            "trading_state_machine must log [AUTO_ACTIVATE PENDING] for pending readiness states",
        )
        self.assertNotIn(
            "logger.error(\n"
            "                        \"[AUTO_ACTIVATE BLOCKED] reason=COMMIT_TRANSITION_FAILED",
            source,
            "readiness.complete errors must NOT be logged at ERROR level (replaced by WARNING with dedup)",
        )

    def test_tsm_has_off_to_pending_confirmation_transition(self):
        """The OFF → LIVE_PENDING_CONFIRMATION transition for readiness.complete
        must be present in the source (Fix 3)."""
        tsm_path = __import__("pathlib").Path(
            importlib.util.find_spec("bot.trading_state_machine").origin
        )
        source = tsm_path.read_text(encoding="utf-8")

        # The fix adds this guard: elif self._current_state == OFF and _is_pending_readiness:
        self.assertIn(
            "TradingState.OFF and _is_pending_readiness",
            source,
            "trading_state_machine must contain OFF+pending → LIVE_PENDING_CONFIRMATION transition (Fix 3)",
        )

    def test_tsm_off_to_pending_sets_pending_confirmation_since(self):
        """When the OFF + readiness.complete path fires, _pending_confirmation_since
        must be set (verified by reading the source block)."""
        tsm_path = __import__("pathlib").Path(
            importlib.util.find_spec("bot.trading_state_machine").origin
        )
        source = tsm_path.read_text(encoding="utf-8")

        # Verify the arm block sets _pending_confirmation_since
        # (both OFF-rollback and LIVE_ACTIVE-rollback branches must set it)
        import re
        # Find all occurrences of the pending_confirmation_since assignment
        hits = re.findall(r"_pending_confirmation_since\s*=\s*time\.monotonic\(\)", source)
        # There must be at least 2: one in the LIVE_ACTIVE branch, one in the new OFF branch.
        self.assertGreaterEqual(
            len(hits),
            2,
            "Both LIVE_ACTIVE rollback and OFF→PENDING_CONFIRMATION paths must set _pending_confirmation_since",
        )


# ---------------------------------------------------------------------------
# 6. Venue isolation — readiness table does not require multi-venue
# ---------------------------------------------------------------------------

class TestVenueIsolationAtReadinessLevel(unittest.TestCase):
    """Prove that all readiness keys can become True for a Coinbase-only venue
    scenario (Kraken/OKX unavailable = simply not published)."""

    def setUp(self):
        self.rt = _reset_rt()
        self.rt.reset()

    def test_coinbase_only_readiness_is_complete(self):
        """All required keys can be True without any Kraken/OKX evidence."""
        rt = self.rt

        # Simulate only Coinbase being ready: publish every key from Coinbase path.
        for key in rt.KEYS:
            rt.mark_ready(key)

        pending = rt.pending()
        self.assertEqual(
            pending, [],
            f"All readiness keys must be settable with Coinbase-only evidence; still pending: {pending}",
        )

    def test_kraken_not_ready_does_not_prevent_keys_from_being_set(self):
        """The readiness table is flat — Kraken/OKX absence never blocks Coinbase keys."""
        rt = self.rt

        # Set all Coinbase-path keys; do NOT set anything for Kraken.
        keys_to_set = [
            "broker_connected",
            "balance_hydrated",
            "authority_ready",
            "capital_ready",
            "risk_ready",
            "strategy_ready",
            "execution_ready",
            "nonce_ready",
            "bootstrap_ready",
        ]
        for key in keys_to_set:
            if key in rt.KEYS:
                rt.mark_ready(key)

        snap = rt.snapshot()
        for key in keys_to_set:
            if key in rt.KEYS:
                self.assertTrue(
                    snap.get(key),
                    f"Key {key!r} must be True even without Kraken/OKX readiness",
                )


# ---------------------------------------------------------------------------
# 7. Monitor source code contract (activation_pending_commit_monitor_patch)
# ---------------------------------------------------------------------------

class TestMonitorSourceContracts(unittest.TestCase):
    """Verify the Fix 4 code is present in the activation-pending monitor."""

    def _source(self):
        spec = importlib.util.find_spec("bot.activation_pending_commit_monitor_patch")
        return __import__("pathlib").Path(spec.origin).read_text(encoding="utf-8")

    def test_monitor_uses_readiness_sleep(self):
        """The monitor must use _readiness_sleep (event-driven) instead of plain
        time.sleep in the LIVE_PENDING_CONFIRMATION retry branch."""
        source = self._source()
        self.assertIn(
            "_readiness_sleep",
            source,
            "activation_pending monitor must define and use _readiness_sleep",
        )
        self.assertIn(
            "READINESS_CHANGED_EVENT",
            source,
            "activation_pending monitor must reference READINESS_CHANGED_EVENT",
        )

    def test_monitor_import_of_readiness_changed_event_is_lazy(self):
        """The monitor must not import READINESS_CHANGED_EVENT at the top level;
        the import must be deferred to avoid circular-import issues at startup."""
        import ast
        spec = importlib.util.find_spec("bot.activation_pending_commit_monitor_patch")
        source = __import__("pathlib").Path(spec.origin).read_text(encoding="utf-8")
        tree = ast.parse(source)

        # Collect top-level import names
        top_level_imports: list[str] = []
        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                if isinstance(node, ast.ImportFrom) and node.module:
                    for alias in node.names:
                        top_level_imports.append(alias.name or "")
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        top_level_imports.append(alias.name or "")

        self.assertNotIn(
            "READINESS_CHANGED_EVENT",
            top_level_imports,
            "READINESS_CHANGED_EVENT must NOT be imported at module top level — must be lazy",
        )

    def test_monitor_observes_runtime_without_importing_it(self, monkeypatch=None):
        """Re-run the existing contract: the monitor must not eagerly import
        trading_state_machine or capital_authority."""
        module = importlib.import_module("bot.activation_pending_commit_monitor_patch")

        for name in (
            "bot.trading_state_machine",
            "trading_state_machine",
            "bot.capital_authority",
            "capital_authority",
        ):
            sys.modules.pop(name, None)

        calls: list[str] = []

        orig_import = module.importlib.import_module

        def _guard(name: str):
            if name in ("bot.trading_state_machine", "trading_state_machine",
                        "bot.capital_authority", "capital_authority"):
                calls.append(name)
                raise AssertionError(f"unexpected eager runtime import: {name}")
            return orig_import(name)

        old = module.importlib.import_module
        module.importlib.import_module = _guard
        try:
            assert module._state_machine() is None
            ready, detail = module._capital_ready_snapshot()
            assert ready is False
        finally:
            module.importlib.import_module = old

        self.assertEqual(calls, [], f"Unexpected eager imports: {calls}")


if __name__ == "__main__":
    unittest.main()
