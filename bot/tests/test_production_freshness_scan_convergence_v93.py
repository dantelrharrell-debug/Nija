from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
import threading
import time
import types
import unittest

from bot import production_freshness_scan_convergence_v93_patch as v93


class ProductionFreshnessScanConvergenceV93Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.keys = (
            "NIJA_CAPITAL_FRESHNESS_TTL_S",
            "NIJA_CAPITAL_STALE_TIMEOUT_S",
            "NIJA_CAPITAL_WATCHDOG_INTERVAL_S",
            "NIJA_CAPITAL_REFRESH_FINALIZE_HEADROOM_S",
            "NIJA_DUPLICATE_SCAN_RESULT_WAIT_S",
            "NIJA_SCAN_ORPHAN_RESET_MIN_AGE_S",
            "NIJA_SCAN_LIVE_OWNER_WARN_AGE_S",
        )
        self.previous = {key: os.environ.get(key) for key in self.keys}
        for key in self.keys:
            os.environ.pop(key, None)

    def tearDown(self) -> None:
        for key, value in self.previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_default_refresh_budget_ceiling_finishes_before_freshness_expiry(self):
        self.assertEqual(v93.continuity_budget_ceiling_s(), 45.0)

    def test_v78_budget_is_only_shortened(self):
        fake = types.ModuleType("fake_v78")
        fake.fetch_budget_seconds = lambda: 60.0
        self.assertTrue(v93._patch_v78(fake))
        self.assertEqual(fake.fetch_budget_seconds(), 45.0)

        os.environ["NIJA_CAPITAL_REFRESH_FETCH_BUDGET_SECONDS"] = "10"
        fake2 = types.ModuleType("fake_v78_2")
        fake2.fetch_budget_seconds = lambda: 10.0
        self.assertTrue(v93._patch_v78(fake2))
        self.assertEqual(fake2.fetch_budget_seconds(), 10.0)

    def test_runtime_cadence_is_bounded_but_never_relaxes_freshness(self):
        os.environ["NIJA_CAPITAL_FRESHNESS_TTL_S"] = "90"
        os.environ["NIJA_CAPITAL_STALE_TIMEOUT_S"] = "80"
        os.environ["NIJA_CAPITAL_WATCHDOG_INTERVAL_S"] = "50"
        os.environ["NIJA_DUPLICATE_SCAN_RESULT_WAIT_S"] = "300"

        values = v93._bound_runtime_cadence_env()

        self.assertLessEqual(values["stale_trigger_s"], 30.0)
        self.assertLessEqual(values["watchdog_interval_s"], 10.0)
        self.assertLessEqual(values["duplicate_scan_wait_s"], 15.0)
        self.assertGreaterEqual(v93.continuity_budget_ceiling_s(), 5.0)

    def test_capital_publication_status_expires_dynamically(self):
        class Status:
            def __init__(self, accepted, stale, reason, timestamp, expiry):
                self.accepted = accepted
                self.stale = stale
                self.reason = reason
                self.timestamp = timestamp
                self.expiry = expiry

        class Authority:
            def __init__(self, status):
                self.status = status

            def get_snapshot_publication_status(self):
                return self.status

        fake = types.ModuleType("fake_capital_authority")
        fake.SnapshotPublicationStatus = Status
        fake.CapitalAuthority = Authority
        self.assertTrue(v93._patch_capital_authority(fake))

        now = datetime.now(timezone.utc)
        authority = Authority(Status(True, False, "accepted", now - timedelta(seconds=100), now - timedelta(seconds=1)))
        expired = authority.get_snapshot_publication_status()
        self.assertTrue(expired.stale)
        self.assertEqual(expired.reason, "snapshot_expired")

        authority.status = Status(True, False, "accepted", now, now + timedelta(seconds=30))
        fresh = authority.get_snapshot_publication_status()
        self.assertFalse(fresh.stale)
        self.assertEqual(fresh.reason, "accepted")

    def test_orphaned_scan_owner_is_reclaimed_only_when_thread_is_dead(self):
        class ScanState:
            def __init__(self):
                self.lock = threading.Lock()
                self.complete = threading.Event()
                self.result = None
                self.owner_thread_id = None
                self.started_at = 0.0

        fake = types.ModuleType("fake_scan")
        fake.ScanState = ScanState
        fake._SCAN_STATES_GUARD = threading.RLock()
        dead = ScanState()
        dead.owner_thread_id = 999999999
        dead.started_at = time.monotonic() - 120.0
        fake._SCAN_STATES = {"platform:coinbase": dead}

        result = v93._sweep_scan_states_once(fake)

        self.assertEqual(result["orphan_reset"], 1)
        self.assertIsNot(fake._SCAN_STATES["platform:coinbase"], dead)
        self.assertIsNone(fake._SCAN_STATES["platform:coinbase"].owner_thread_id)

    def test_live_scan_owner_is_never_replaced(self):
        class ScanState:
            def __init__(self):
                self.lock = threading.Lock()
                self.complete = threading.Event()
                self.result = None
                self.owner_thread_id = threading.get_ident()
                self.started_at = time.monotonic() - 240.0

        fake = types.ModuleType("fake_scan_live")
        fake.ScanState = ScanState
        fake._SCAN_STATES_GUARD = threading.RLock()
        state = ScanState()
        fake._SCAN_STATES = {"platform:coinbase": state}

        result = v93._sweep_scan_states_once(fake)

        self.assertEqual(result["orphan_reset"], 0)
        self.assertEqual(result["live_stalled"], 1)
        self.assertIs(fake._SCAN_STATES["platform:coinbase"], state)

    def test_v64_bridge_reapplies_loaded_target_patches(self):
        fake = types.ModuleType("fake_v64")
        calls = []
        fake._patch_loaded = lambda: calls.append("patched") or True

        self.assertTrue(v93._patch_v64_bridge(fake))
        self.assertEqual(calls, ["patched"])


if __name__ == "__main__":
    unittest.main()
