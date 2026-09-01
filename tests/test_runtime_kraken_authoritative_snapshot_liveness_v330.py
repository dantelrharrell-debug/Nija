from __future__ import annotations

import threading
import time
import unittest
from types import SimpleNamespace

from bot import runtime_kraken_authoritative_snapshot_liveness_v330_patch as v330


class KrakenAuthoritativeSnapshotLivenessV330Test(unittest.TestCase):
    def test_timeout_recovery_uses_actual_reused_flight_epoch(self) -> None:
        broker = SimpleNamespace(account_identifier="PLATFORM")
        flight_started = time.monotonic() - 8.0
        flight = {
            "event": threading.Event(),
            "started_at": flight_started,
            "result": None,
            "error": None,
        }
        calls: list[str] = []
        not_before_seen: list[float] = []

        def original(_broker):
            calls.append("authoritative_wait")
            raise TimeoutError("old authoritative flight still pending")

        fake_v286 = SimpleNamespace(
            _authoritative_positions=original,
            _AUTH_FLIGHTS={id(broker): flight},
            _AUTH_LOCK=threading.RLock(),
        )

        # A genuine same-credential Balance arrived after the underlying flight
        # began but before the newest bounded retry started.
        observed_at = time.monotonic() - 2.0

        def fresh_observation(_broker, *, not_before):
            not_before_seen.append(float(not_before))
            self.assertAlmostEqual(float(not_before), flight_started, places=5)
            self.assertGreaterEqual(observed_at, float(not_before))
            return {
                "response": {"error": [], "result": {"XXBT": "0.001"}},
                "observed_at": observed_at,
                "age_s": max(0.0, time.monotonic() - observed_at),
            }

        def rows_from_observation(_broker, observation):
            self.assertEqual(observation["response"]["result"]["XXBT"], "0.001")
            return [{"symbol": "BTC-USD", "quantity": 0.001, "authoritative_balance": True}]

        fake_v312 = SimpleNamespace(
            _fresh_observation=fresh_observation,
            _rows_from_observation=rows_from_observation,
        )
        original_v286 = v330._v286
        original_v312 = v330._v312
        try:
            v330._v286 = lambda: fake_v286
            v330._v312 = lambda: fake_v312
            self.assertTrue(v330._patch_timeout_epoch_recovery())
            rows = fake_v286._authoritative_positions(broker)
        finally:
            v330._v286 = original_v286
            v330._v312 = original_v312

        self.assertEqual(
            rows,
            [{"symbol": "BTC-USD", "quantity": 0.001, "authoritative_balance": True}],
        )
        self.assertEqual(calls, ["authoritative_wait"])
        self.assertEqual(len(not_before_seen), 1)
        self.assertAlmostEqual(not_before_seen[0], flight_started, places=5)
        self.assertIs(fake_v286._AUTH_FLIGHTS[id(broker)], flight)
        self.assertFalse(flight["event"].is_set())

    def test_timeout_without_genuine_same_flight_observation_remains_fail_closed(self) -> None:
        broker = SimpleNamespace(account_identifier="PLATFORM")
        flight_started = time.monotonic() - 8.0
        flight = {"event": threading.Event(), "started_at": flight_started}
        calls: list[str] = []

        def original(_broker):
            calls.append("authoritative_wait")
            raise TimeoutError("still pending")

        fake_v286 = SimpleNamespace(
            _authoritative_positions=original,
            _AUTH_FLIGHTS={id(broker): flight},
            _AUTH_LOCK=threading.RLock(),
        )
        fake_v312 = SimpleNamespace(
            _fresh_observation=lambda _broker, *, not_before: None,
            _rows_from_observation=lambda _broker, observation: self.fail("must not build rows"),
        )
        original_v286 = v330._v286
        original_v312 = v330._v312
        try:
            v330._v286 = lambda: fake_v286
            v330._v312 = lambda: fake_v312
            self.assertTrue(v330._patch_timeout_epoch_recovery())
            with self.assertRaisesRegex(TimeoutError, "still pending"):
                fake_v286._authoritative_positions(broker)
        finally:
            v330._v286 = original_v286
            v330._v312 = original_v312

        self.assertEqual(calls, ["authoritative_wait"])
        self.assertIs(fake_v286._AUTH_FLIGHTS[id(broker)], flight)
        self.assertFalse(flight["event"].is_set())

    @staticmethod
    def _fake_v285(age_by_broker):
        def platform_candidates(_manager):
            return []

        def snapshot_status(broker):
            age_s, ready = age_by_broker[id(broker)]
            return ready, "current" if ready else "stale", (), age_s, 7

        return SimpleNamespace(
            _platform_candidates=platform_candidates,
            _snapshot_status=snapshot_status,
            _refresh_interval_s=lambda: 49.5,
            _connected=lambda broker: bool(getattr(broker, "connected", False)),
            _label=lambda value: str(value).lower(),
        )

    def _run_refresh_candidates(self, fake_v285, platform_brokers):
        original_v285 = v330._v285
        try:
            v330._v285 = lambda: fake_v285
            self.assertTrue(v330._patch_proactive_kraken_refresh())
            return fake_v285._platform_candidates(SimpleNamespace(platform_brokers=platform_brokers))
        finally:
            v330._v285 = original_v285

    def test_proactive_refresh_adds_only_current_aged_kraken(self) -> None:
        kraken = SimpleNamespace(connected=True)
        coinbase = SimpleNamespace(connected=True)
        fake_v285 = self._fake_v285(
            {id(kraken): (50.0, True), id(coinbase): (50.0, True)}
        )
        candidates = self._run_refresh_candidates(
            fake_v285,
            {"kraken": kraken, "coinbase": coinbase},
        )
        self.assertEqual(candidates, [("kraken", kraken)])

    def test_proactive_refresh_rejects_young_kraken(self) -> None:
        broker = SimpleNamespace(connected=True)
        fake_v285 = self._fake_v285({id(broker): (40.0, True)})
        self.assertEqual(self._run_refresh_candidates(fake_v285, {"kraken": broker}), [])

    def test_proactive_refresh_rejects_stale_kraken(self) -> None:
        broker = SimpleNamespace(connected=True)
        fake_v285 = self._fake_v285({id(broker): (70.0, False)})
        self.assertEqual(self._run_refresh_candidates(fake_v285, {"kraken": broker}), [])

    def test_proactive_refresh_rejects_disconnected_kraken(self) -> None:
        broker = SimpleNamespace(connected=False)
        fake_v285 = self._fake_v285({id(broker): (70.0, True)})
        self.assertEqual(self._run_refresh_candidates(fake_v285, {"kraken": broker}), [])


if __name__ == "__main__":
    unittest.main()
