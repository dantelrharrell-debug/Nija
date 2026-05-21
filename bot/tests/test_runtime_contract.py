from __future__ import annotations

import os
import tempfile
import threading
import unittest

from bot.runtime_contract import build_canonical_intent_id, evaluate_runtime_contract
from bot.runtime_correlation import (
    get_runtime_correlation,
    runtime_correlation_scope,
    set_runtime_correlation,
)
from bot.single_execution_authority_kernel import RejectionReason, SingleExecutionAuthorityKernel


def _fresh_kernel() -> SingleExecutionAuthorityKernel:
    kernel = SingleExecutionAuthorityKernel()
    kernel._dedup_guard = None
    kernel._dedup_guard_loaded = True
    kernel._hardening = None
    kernel._hardening_loaded = True
    kernel._health_monitor = None
    kernel._health_loaded = True
    return kernel


class TestRuntimeContractIntentId(unittest.TestCase):
    def test_intent_id_is_deterministic_for_same_material(self):
        first = build_canonical_intent_id(
            symbol="BTC-USD",
            side="buy",
            size_usd=150.25,
            strategy="APEX",
            account_id="acc-1",
            cycle_id="cycle-a",
            trace_id="trace-a",
            now_ts=1_700_000_000.0,
        )
        second = build_canonical_intent_id(
            symbol="BTC-USD",
            side="buy",
            size_usd=150.25,
            strategy="APEX",
            account_id="acc-1",
            cycle_id="cycle-a",
            trace_id="trace-a",
            now_ts=1_700_000_000.0,
        )
        self.assertEqual(first, second)

    def test_runtime_contract_release_ready_defaults_true(self):
        status = evaluate_runtime_contract()
        self.assertTrue(status.release_ready)
        self.assertTrue(status.quiet_runtime)
        self.assertTrue(status.idempotent_runtime)


class TestRuntimeCorrelationIsolation(unittest.TestCase):
    def test_context_is_thread_isolated(self):
        set_runtime_correlation(cycle_id="main-cycle")
        captured = {}

        def worker():
            captured["before"] = get_runtime_correlation()
            with runtime_correlation_scope(cycle_id="child-cycle", trace_id="t-child"):
                captured["inside"] = get_runtime_correlation()
            captured["after"] = get_runtime_correlation()

        t = threading.Thread(target=worker)
        t.start()
        t.join()

        self.assertEqual(get_runtime_correlation().get("cycle_id"), "main-cycle")
        self.assertEqual(captured.get("before"), {})
        self.assertEqual(captured.get("inside", {}).get("cycle_id"), "child-cycle")
        self.assertEqual(captured.get("after"), {})


class TestSeakIdempotentReplay(unittest.TestCase):
    def test_same_intent_id_is_blocked_after_release(self):
        kernel = _fresh_kernel()
        token = kernel.acquire(
            symbol="BTC-USD",
            side="buy",
            size_usd=100.0,
            strategy="S1",
            extra={"intent_id": "intent-replay-1"},
        )
        self.assertTrue(token.granted)
        kernel.release(token)

        duplicate = kernel.acquire(
            symbol="BTC-USD",
            side="buy",
            size_usd=100.0,
            strategy="S1",
            extra={"intent_id": "intent-replay-1"},
        )
        self.assertFalse(duplicate.granted)
        self.assertEqual(duplicate.rejection_reason, RejectionReason.DUPLICATE_REQUEST)

    def test_intent_id_journal_blocks_replay_after_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal = os.path.join(tmp, "seak-idempotency.json")
            old_path = os.environ.get("NIJA_SEAK_IDEMPOTENCY_JOURNAL_PATH")
            os.environ["NIJA_SEAK_IDEMPOTENCY_JOURNAL_PATH"] = journal
            try:
                first = _fresh_kernel()
                token = first.acquire(
                    symbol="ETH-USD",
                    side="sell",
                    size_usd=55.0,
                    strategy="S2",
                    extra={"intent_id": "intent-restart-1"},
                )
                self.assertTrue(token.granted)
                first.release(token)

                second = _fresh_kernel()
                replay = second.acquire(
                    symbol="ETH-USD",
                    side="sell",
                    size_usd=55.0,
                    strategy="S2",
                    extra={"intent_id": "intent-restart-1"},
                )
                self.assertFalse(replay.granted)
                self.assertEqual(replay.rejection_reason, RejectionReason.DUPLICATE_REQUEST)
            finally:
                if old_path is None:
                    os.environ.pop("NIJA_SEAK_IDEMPOTENCY_JOURNAL_PATH", None)
                else:
                    os.environ["NIJA_SEAK_IDEMPOTENCY_JOURNAL_PATH"] = old_path
