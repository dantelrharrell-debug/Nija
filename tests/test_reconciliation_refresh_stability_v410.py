from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
BOT = ROOT / "bot"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v146 = _load(
    "runtime_reconciliation_shutdown_v146_refresh_stability_under_test",
    BOT / "runtime_reconciliation_shutdown_v146_patch.py",
)


class ReconciliationRefreshStabilityV410Tests(unittest.TestCase):
    @staticmethod
    def _position_module(broker):
        class V95:
            platform_position_sync_status = staticmethod(lambda _manager: None)

            @staticmethod
            def position_sync_status(_manager):
                return True, [], {"platform:kraken": True}

            @staticmethod
            def _connected_brokers(_manager):
                return {"platform:kraken": broker}

        module = types.ModuleType("fake_position_sync_v96_refresh_stability")
        module._v95_module = lambda: V95
        return module

    def test_exact_current_strong_proof_survives_transient_legacy_flag_clear(self) -> None:
        broker = types.SimpleNamespace(
            _startup_position_sync_fetch_ok=None,
            _startup_position_sync_error="Kraken authoritative position Balance pending after 5.0s",
        )
        fake_v285 = types.ModuleType(
            "bot.runtime_authoritative_position_coverage_v285_patch"
        )
        fake_v285._strong_broker_proof = lambda candidate: (
            candidate is broker,
            "authoritative_current_position_snapshot_refresh_inflight_v399",
        )

        with patch.dict(
            sys.modules,
            {"bot.runtime_authoritative_position_coverage_v285_patch": fake_v285},
        ):
            ready, pending, status = v146._position_sync_truth(
                self._position_module(broker),
                object(),
            )

        self.assertTrue(ready)
        self.assertEqual(pending, [])
        self.assertEqual(status, {"platform:kraken": True})

    def test_completed_or_stale_strong_proof_still_fails_closed(self) -> None:
        broker = types.SimpleNamespace(
            _startup_position_sync_fetch_ok=False,
            _startup_position_sync_error="completed_exchange_failure",
        )
        fake_v285 = types.ModuleType(
            "bot.runtime_authoritative_position_coverage_v285_patch"
        )
        fake_v285._strong_broker_proof = lambda _candidate: (
            False,
            "stale_position_snapshot:age_s=95.0:max_age_s=90.0",
        )

        with patch.dict(
            sys.modules,
            {"bot.runtime_authoritative_position_coverage_v285_patch": fake_v285},
        ):
            ready, pending, status = v146._position_sync_truth(
                self._position_module(broker),
                object(),
            )

        self.assertFalse(ready)
        self.assertEqual(pending, ["platform:kraken"])
        self.assertEqual(status, {"platform:kraken": True})

    def test_existing_legacy_fetch_success_does_not_depend_on_v285(self) -> None:
        broker = types.SimpleNamespace(
            _startup_position_sync_fetch_ok=True,
            _startup_position_sync_error=None,
        )
        fake_v285 = types.ModuleType(
            "bot.runtime_authoritative_position_coverage_v285_patch"
        )

        def should_not_run(_candidate):
            raise AssertionError("strong proof should not run for legacy success")

        fake_v285._strong_broker_proof = should_not_run

        with patch.dict(
            sys.modules,
            {"bot.runtime_authoritative_position_coverage_v285_patch": fake_v285},
        ):
            ready, pending, status = v146._position_sync_truth(
                self._position_module(broker),
                object(),
            )

        self.assertTrue(ready)
        self.assertEqual(pending, [])
        self.assertEqual(status, {"platform:kraken": True})


if __name__ == "__main__":
    unittest.main()
