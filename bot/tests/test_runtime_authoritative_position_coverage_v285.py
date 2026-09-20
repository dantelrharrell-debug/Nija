from __future__ import annotations

import os
import sys
import threading
import types
import unittest
from unittest.mock import patch

from bot import runtime_authoritative_position_coverage_v285_patch as v285


class RuntimeAuthoritativePositionCoverageV285Tests(unittest.TestCase):
    def _broker(self):
        broker = types.SimpleNamespace(
            connected=True,
            broker_type="kraken",
            _startup_position_sync_fetch_ok=True,
            _startup_position_sync_adopted=True,
            _startup_position_sync_symbols=("BTC-USD",),
            _startup_position_sync_error="",
        )
        self.assertTrue(
            v285._record_snapshot_success(
                broker,
                [{"symbol": "BTC-USD", "quantity": 0.01, "entry_price": 50000.0}],
            )
        )
        return broker

    @staticmethod
    def _flight_module(broker, *, completed: bool = False, error=None):
        event = threading.Event()
        if completed:
            event.set()
        module = types.ModuleType(
            "bot.runtime_kraken_position_refresh_liveness_v286_patch"
        )
        module._LAST_PROOF_READY = {id(broker): True}
        module._AUTH_FLIGHTS = {
            id(broker): {
                "event": event,
                "error": error,
                "started_at": 1.0,
            }
        }
        module._AUTH_LOCK = threading.RLock()
        return module

    def test_v399_active_refresh_preserves_current_prior_proof(self):
        broker = self._broker()
        broker._startup_position_sync_fetch_ok = None
        broker._startup_position_sync_adopted = False
        broker._startup_position_sync_error = (
            "Kraken authoritative position Balance pending after 5.0s"
        )
        fake_v286 = self._flight_module(broker)

        with (
            patch.dict(
                sys.modules,
                {"bot.runtime_kraken_position_refresh_liveness_v286_patch": fake_v286},
            ),
            patch.dict(
                os.environ,
                {"NIJA_AUTHORITATIVE_POSITION_SNAPSHOT_MAX_AGE_S": "90"},
                clear=False,
            ),
        ):
            ready, reason = v285._strong_broker_proof(broker)

        self.assertTrue(ready)
        self.assertEqual(
            reason,
            "authoritative_current_position_snapshot_refresh_inflight_v399",
        )

    def test_v399_completed_refresh_still_fails_closed(self):
        broker = self._broker()
        broker._startup_position_sync_fetch_ok = False
        broker._startup_position_sync_adopted = False
        broker._startup_position_sync_error = "completed_exchange_failure"
        fake_v286 = self._flight_module(broker, completed=True)

        with patch.dict(
            sys.modules,
            {"bot.runtime_kraken_position_refresh_liveness_v286_patch": fake_v286},
        ):
            ready, reason = v285._strong_broker_proof(broker)

        self.assertFalse(ready)
        self.assertEqual(reason, "completed_exchange_failure")

    def test_v399_stale_snapshot_still_fails_closed_during_active_refresh(self):
        broker = self._broker()
        broker._startup_position_sync_fetch_ok = None
        broker._startup_position_sync_adopted = False
        broker._startup_position_sync_error = "refresh_pending"
        fake_v286 = self._flight_module(broker)

        snapshot_at = float(
            getattr(
                broker,
                "_nija_authoritative_position_snapshot_at_monotonic_v285",
                0.0,
            )
        )
        self.assertGreater(snapshot_at, 0.0)

        with (
            patch.dict(
                sys.modules,
                {"bot.runtime_kraken_position_refresh_liveness_v286_patch": fake_v286},
            ),
            patch.dict(
                os.environ,
                {"NIJA_AUTHORITATIVE_POSITION_SNAPSHOT_MAX_AGE_S": "30"},
                clear=False,
            ),
            patch.object(v285.time, "monotonic", return_value=snapshot_at + 31.0),
        ):
            ready, reason = v285._strong_broker_proof(broker)

        self.assertFalse(ready)
        self.assertEqual(reason, "refresh_pending")


if __name__ == "__main__":
    unittest.main()
