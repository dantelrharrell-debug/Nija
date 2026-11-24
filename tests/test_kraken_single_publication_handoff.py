"""Test real v286/v312 publication and v98 verification with fake Balance data."""

import threading
import time
import unittest
from unittest.mock import patch

from bot import position_sync_failure_truth_v98_patch as v98
from bot import runtime_authoritative_position_coverage_v285_patch as v285
from bot import runtime_kraken_balance_epoch_handoff_v312_patch as v312
from bot import runtime_kraken_position_refresh_liveness_v286_patch as v286


class FixtureKraken:
    broker_type = "kraken"
    account_identifier = "offline"
    connected = True

    def _kraken_private_call(self, *_args, **_kwargs):
        raise AssertionError("the handoff must not issue a private request")


class TestSinglePublicationHandoff(unittest.TestCase):
    def setUp(self):
        self.broker = FixtureKraken()
        self.proxy = v286._KrakenAuthoritativeProxy(self.broker)
        self.flight = {"event": threading.Event(), "started_at": time.monotonic()}
        self.addCleanup(patch.stopall)
        patch.dict(v286.os.environ, {"NIJA_RUNTIME_KRAKEN_BALANCE_EPOCH_HANDOFF_V312_READY": "1"}).start()
        patch.object(v312, "_OBSERVATIONS", {}).start()
        patch.object(v312, "_credential_key", return_value=("fixture", True)).start()
        self.price = patch.object(v286, "_cached_price", return_value=10.0).start()
        self.observe("1")

    def observe(self, btc):
        assert v312._record_observation(self.broker, {"result": {"XXBT": btc}, "error": []})

    def handoff(self):
        return v286._balance_rows_while_waiting(self.broker, self.flight)

    def check(self, rows):
        return v286._check_v98_fetch_result(
            self.proxy, rows, lambda broker, candidate: v98._reuse_exact_kraken_snapshot(broker, candidate, v285)
        )[0]

    def test_same_observation_copied_without_repricing_or_advancing(self):
        first = self.handoff()
        generation = self.broker._nija_authoritative_position_raw_generation_v286
        stamp = self.broker._nija_authoritative_position_snapshot_at_monotonic_v285
        self.price.return_value = 11.0
        second = self.handoff()
        self.assertEqual(first, second)
        self.assertIsNot(first[0], second[0])
        self.assertEqual(generation, self.broker._nija_authoritative_position_raw_generation_v286)
        self.assertEqual(stamp, self.broker._nija_authoritative_position_snapshot_at_monotonic_v285)
        self.assertTrue(self.check(first))
        self.assertTrue(self.check(second))

    def test_different_observation_does_not_overwrite_outstanding_handoff(self):
        first = self.handoff()
        self.observe("2")
        self.assertIsNone(self.handoff())
        self.assertTrue(self.check(first))

    def test_expired_observation_does_not_return_cached_rows(self):
        first = self.handoff()
        v312._OBSERVATIONS["fixture"]["observed_at"] -= 1000
        self.broker._nija_authoritative_position_snapshot_at_monotonic_v285 -= 1000
        self.assertIsNone(self.handoff())
        self.assertFalse(self.check(first))

    def test_other_writer_does_not_republish_or_reuse_old_rows(self):
        first = self.handoff()
        new_rows = [dict(first[0], quantity=9)]
        generation = v286._record_snapshot_success(self.broker, new_rows)
        self.assertIsNone(self.handoff())
        self.assertEqual(generation, self.broker._nija_authoritative_position_raw_generation_v286)
        self.assertFalse(self.check(first))

    def test_matching_balance_under_a_different_credential_is_not_reused(self):
        self.handoff()
        with patch.object(v312, "_credential_key", return_value=("different", True)):
            self.observe("1")
            self.assertIsNone(self.handoff())

    def test_new_flight_can_use_fresh_observation(self):
        self.handoff()
        self.flight = {"event": threading.Event(), "started_at": time.monotonic()}
        self.observe("2")
        self.assertEqual(self.handoff()[0]["quantity"], 2)

    def test_failed_worker_still_prevents_handoff(self):
        self.flight["error"] = RuntimeError("fixture error")
        self.flight["event"].set()
        self.assertIsNone(self.handoff())
