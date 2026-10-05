"""Exercise short-lived Balance evidence while an older private read is pending."""
from __future__ import annotations

import os
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from bot import runtime_kraken_balance_epoch_handoff_v312_patch as v312
from bot import runtime_kraken_position_refresh_liveness_v286_patch as v286
from bot import trading_strategy as strategy


class KrakenBroker:
    """Broker double that must never receive extra private reads from a waiter."""

    def __init__(self, credential: str = "platform") -> None:
        self.credential = credential
        self.account_identifier = "PLATFORM"
        self._kraken_private_call = Mock(side_effect=AssertionError("duplicate private read"))


class KrakenInflightBalanceHandoffTests(unittest.TestCase):
    def setUp(self) -> None:
        self.credential_patch = patch.object(
            v312, "_credential_key", side_effect=lambda broker: (broker.credential, True)
        )
        self.credential_patch.start()
        self.addCleanup(self.credential_patch.stop)
        self.observations_patch = patch.object(v312, "_OBSERVATIONS", {})
        self.observations_patch.start()
        self.addCleanup(self.observations_patch.stop)

    def test_balance_arriving_during_wait_is_consumed_before_expiry(self) -> None:
        broker = KrakenBroker()
        event = threading.Event()
        flight = {"event": event, "started_at": time.monotonic(), "result": None, "error": None}
        # Reuse an existing pending flight; no worker or broker read may start.
        rows = [{"symbol": "BTC-USD", "quantity": 0.001}]
        recorded = Mock()

        def publish() -> None:
            time.sleep(0.05)
            v312._record_observation(broker, {"error": [], "result": {"XXBT": "0.001"}})

        publisher = threading.Thread(target=publish)
        with (
            patch.dict(os.environ, {"NIJA_RUNTIME_KRAKEN_BALANCE_EPOCH_HANDOFF_V312_READY": "1"}),
            patch.object(v286, "_AUTH_FLIGHTS", {id(broker): flight}),
            patch.object(v286, "_auth_wait_s", return_value=1.0),
            patch.object(v312, "_ttl_s", return_value=0.5),
            patch.object(v286, "_build_authoritative_rows", return_value=rows),
            patch.object(v286, "_record_snapshot_success", recorded),
        ):
            publisher.start()
            started = time.monotonic()
            try:
                result = v286._authoritative_positions(broker)
            finally:
                publisher.join(1)
            self.assertLess(time.monotonic() - started, 0.7)
            self.assertEqual(result, rows)
            recorded.assert_called_once_with(broker, rows)
            self.assertIs(v286._AUTH_FLIGHTS[id(broker)], flight)
            self.assertFalse(event.is_set())
        broker._kraken_private_call.assert_not_called()

    def test_stale_wrong_credential_and_pre_epoch_evidence_cannot_release_waiter(self) -> None:
        broker = KrakenBroker()
        other = KrakenBroker("other")
        flight = {"event": threading.Event(), "started_at": time.monotonic()}
        response = {"error": [], "result": {"ZUSD": "302.03"}}
        with patch.dict(os.environ, {"NIJA_RUNTIME_KRAKEN_BALANCE_EPOCH_HANDOFF_V312_READY": "1"}):
            v312._record_observation(other, response)
            self.assertIsNone(v286._balance_rows_while_waiting(broker, flight))
            v312._record_observation(broker, response)
            v312._OBSERVATIONS[broker.credential]["observed_at"] = time.monotonic() - 31.0
            self.assertIsNone(v286._balance_rows_while_waiting(broker, flight))
            v312._record_observation(broker, response)
            flight["started_at"] = time.monotonic() + 3.0
            self.assertIsNone(v286._balance_rows_while_waiting(broker, flight))
        broker._kraken_private_call.assert_not_called()

    def test_completed_exchange_error_is_not_masked_by_balance_observation(self) -> None:
        broker = KrakenBroker()
        event = threading.Event()
        event.set()
        flight = {
            "event": event, "started_at": time.monotonic(),
            "error": RuntimeError("exchange read failed"), "result": None,
        }
        v312._record_observation(broker, {"error": [], "result": {}})
        with (
            patch.dict(os.environ, {"NIJA_RUNTIME_KRAKEN_BALANCE_EPOCH_HANDOFF_V312_READY": "1"}),
            patch.object(v286, "_AUTH_FLIGHTS", {id(broker): flight}),
            patch.object(v312, "_rows_from_observation") as builder,
        ):
            with self.assertRaisesRegex(RuntimeError, "exchange read failed"):
                v286._authoritative_positions(broker)
            builder.assert_not_called()

    def test_unready_handoff_and_recording_error_fail_closed(self) -> None:
        broker = KrakenBroker()
        flight = {"event": threading.Event(), "started_at": time.monotonic()}
        with patch.dict(os.environ, {"NIJA_RUNTIME_KRAKEN_BALANCE_EPOCH_HANDOFF_V312_READY": "0"}):
            with patch.object(v312, "_fresh_observation") as getter:
                self.assertIsNone(v286._balance_rows_while_waiting(broker, flight))
                getter.assert_not_called()
        v312._record_observation(broker, {"error": [], "result": {}})
        with (
            patch.dict(os.environ, {"NIJA_RUNTIME_KRAKEN_BALANCE_EPOCH_HANDOFF_V312_READY": "1"}),
            patch.object(v312, "_rows_from_observation", side_effect=RuntimeError("recording failed")),
        ):
            self.assertIsNone(v286._balance_rows_while_waiting(broker, flight))

    def test_heartbeat_catches_balance_arriving_between_scheduler_ticks_without_io(self) -> None:
        broker = KrakenBroker()

        def publish() -> None:
            time.sleep(0.05)
            v312._record_observation(broker, {"error": [], "result": {"ZUSD": "302.03"}})

        publisher = threading.Thread(target=publish)
        publisher.start()
        try:
            ok, detail = strategy._kraken_heartbeat_auth_probe(broker, wait_seconds=0.5)
        finally:
            publisher.join(1)
        self.assertTrue(ok)
        self.assertEqual(detail, "kraken_recent_authenticated_balance")
        broker._kraken_private_call.assert_not_called()

    def test_heartbeat_without_balance_remains_bounded_and_fail_closed(self) -> None:
        broker = KrakenBroker()
        started = time.monotonic()
        ok, detail = strategy._kraken_heartbeat_auth_probe(broker, wait_seconds=0.05)
        self.assertFalse(ok)
        self.assertEqual(detail, "kraken_recent_authenticated_balance_unavailable")
        self.assertLess(time.monotonic() - started, 0.5)
        broker._kraken_private_call.assert_not_called()

    def test_heartbeat_uses_existing_configured_auth_timeout_with_hard_cap(self) -> None:
        broker = KrakenBroker()
        for configured, expected in (("12", 12.0), ("999", 30.0), ("bad", 12.0)):
            with (
                patch.dict(os.environ, {"NIJA_HEARTBEAT_AUTH_PROBE_TIMEOUT_S": configured}),
                patch.object(strategy, "_kraken_heartbeat_auth_probe", return_value=(False, "pending")) as probe,
            ):
                self.assertEqual(
                    strategy.TradingStrategy._heartbeat_auth_verify(SimpleNamespace(), broker), (False, "pending")
                )
                probe.assert_called_once_with(broker, wait_seconds=expected)


if __name__ == "__main__":
    unittest.main()
