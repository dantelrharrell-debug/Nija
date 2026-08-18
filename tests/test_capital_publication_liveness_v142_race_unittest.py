from __future__ import annotations

import unittest
from types import SimpleNamespace

from bot.kill_switch_coordinator_sync_patch import _prepare_capital_publication_liveness


class CapitalPublicationLivenessV142RaceTests(unittest.TestCase):
    def test_tracked_refresh_without_published_worker_handle_is_not_rolled_early(self) -> None:
        coordinator = SimpleNamespace(
            _in_flight=True,
            _nija_v142_flight_generation=11,
            _nija_v142_flight_timed_out=False,
        )
        manager = SimpleNamespace(_capital_coordinator=coordinator)
        rollovers: list[str] = []

        fake = SimpleNamespace(
            _nija_startup_chain_prepared=False,
            _coordinator_in_flight_v142=lambda manager: True,
            _flight_age_s=lambda owner: 0.01,
            _runtime_pipeline_deadline_seconds=lambda: 55.0,
        )

        def rollover(target_manager, *, expected_old=None, reason):
            rollovers.append(str(reason))
            return None

        fake._rollover_coordinator = rollover

        self.assertTrue(_prepare_capital_publication_liveness(fake))
        self.assertTrue(fake._coordinator_in_flight_v142(manager))
        self.assertEqual(rollovers, [])

    def test_missing_worker_handle_after_deadline_is_rolled_fail_closed(self) -> None:
        coordinator = SimpleNamespace(
            _in_flight=True,
            _nija_v142_flight_generation=12,
            _nija_v142_flight_timed_out=False,
        )
        replacement = SimpleNamespace(_in_flight=False)
        manager = SimpleNamespace(_capital_coordinator=coordinator)
        reasons: list[str] = []

        fake = SimpleNamespace(
            _nija_startup_chain_prepared=False,
            _coordinator_in_flight_v142=lambda manager: True,
            _flight_age_s=lambda owner: 61.0,
            _runtime_pipeline_deadline_seconds=lambda: 55.0,
        )

        def rollover(target_manager, *, expected_old=None, reason):
            self.assertIs(expected_old, coordinator)
            reasons.append(str(reason))
            target_manager._capital_coordinator = replacement
            return replacement

        fake._rollover_coordinator = rollover

        self.assertTrue(_prepare_capital_publication_liveness(fake))
        self.assertFalse(fake._coordinator_in_flight_v142(manager))
        self.assertIs(manager._capital_coordinator, replacement)
        self.assertEqual(reasons, ["coordinator_worker_handle_missing_after_deadline"])


if __name__ == "__main__":
    unittest.main()
