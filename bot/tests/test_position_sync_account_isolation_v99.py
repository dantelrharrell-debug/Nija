from __future__ import annotations

import types
import unittest
from enum import Enum

from bot import position_sync_account_isolation_v99_patch as v99
from bot import position_sync_core_handoff_v95_patch as v95


class _BrokerType(Enum):
    KRAKEN = "kraken"
    COINBASE = "coinbase"


class _Broker:
    connected = True

    def __init__(self, synced: bool) -> None:
        self._startup_position_sync_adopted = synced


class PositionSyncAccountIsolationV99Tests(unittest.TestCase):
    def test_platform_ready_is_not_blocked_by_unsynced_user(self) -> None:
        manager = types.SimpleNamespace(
            platform_brokers={
                _BrokerType.KRAKEN: _Broker(True),
                _BrokerType.COINBASE: _Broker(True),
            },
            user_brokers={
                "daivon_frazier": {_BrokerType.KRAKEN: _Broker(False)},
            },
        )

        platform_ready, platform_pending, platform_status = v99._platform_position_sync_status(manager)
        self.assertTrue(platform_ready)
        self.assertEqual(platform_pending, [])
        self.assertEqual(
            platform_status,
            {"platform:kraken": True, "platform:coinbase": True},
        )

        all_ready, all_pending, all_status = v95.position_sync_status(manager)
        self.assertFalse(all_ready)
        self.assertEqual(all_pending, ["user:daivon_frazier:kraken"])
        self.assertFalse(all_status["user:daivon_frazier:kraken"])

    def test_unsynced_platform_still_blocks_global_readiness(self) -> None:
        manager = types.SimpleNamespace(
            platform_brokers={
                _BrokerType.KRAKEN: _Broker(True),
                _BrokerType.COINBASE: _Broker(False),
            },
            user_brokers={
                "daivon_frazier": {_BrokerType.KRAKEN: _Broker(True)},
            },
        )

        ready, pending, status = v99._platform_position_sync_status(manager)
        self.assertFalse(ready)
        self.assertEqual(pending, ["platform:coinbase"])
        self.assertFalse(status["platform:coinbase"])

    def test_empty_platform_set_is_fail_closed(self) -> None:
        manager = types.SimpleNamespace(
            platform_brokers={},
            user_brokers={
                "daivon_frazier": {_BrokerType.KRAKEN: _Broker(True)},
            },
        )
        ready, pending, status = v99._platform_position_sync_status(manager)
        self.assertFalse(ready)
        self.assertEqual(pending, [])
        self.assertEqual(status, {})

    def test_copy_trade_submitter_blocks_only_until_user_sync_is_real(self) -> None:
        calls: list[dict] = []

        def submitter(*args, **kwargs):
            calls.append(dict(kwargs))
            return {"status": "filled", "order_id": "ok"}

        guarded = v99._guard_submitter(submitter)
        broker = _Broker(False)

        blocked = guarded(
            broker=broker,
            symbol="BTC/USD",
            side="buy",
            quantity=10.0,
            size_type="quote",
            strategy="CopyTradeEngine",
        )
        self.assertEqual(blocked["status"], "skipped")
        self.assertFalse(blocked["position_sync_ready"])
        self.assertEqual(calls, [])

        broker._startup_position_sync_adopted = True
        allowed = guarded(
            broker=broker,
            symbol="BTC/USD",
            side="buy",
            quantity=10.0,
            size_type="quote",
            strategy="CopyTradeEngine",
        )
        self.assertEqual(allowed["status"], "filled")
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
