import unittest
from unittest.mock import patch

from bot.trading_strategy import TradingStrategy


class _NonceFlakyBroker:
    def __init__(self) -> None:
        self._calls = 0

    def get_account_balance(self):
        self._calls += 1
        if self._calls == 1:
            raise RuntimeError("EAPI:Invalid nonce")
        return {"balance": 1.0}


class _AlwaysFailBroker:
    def get_account_balance(self):
        raise RuntimeError("EAPI:Invalid nonce")


class _NonNonceFailBroker:
    def get_account_balance(self):
        raise RuntimeError("EAuth:Invalid key")


class TestHeartbeatAuthNonceRecovery(unittest.TestCase):
    def setUp(self) -> None:
        self.strategy = TradingStrategy.__new__(TradingStrategy)

    def test_auth_probe_recovers_nonce_and_passes(self) -> None:
        broker = _NonceFlakyBroker()
        with patch.object(
            TradingStrategy,
            "_recover_nonce_auth_probe",
            return_value=(True, "probe_server_sync"),
        ) as recover:
            ok, detail = self.strategy._heartbeat_auth_verify(broker)
        self.assertTrue(ok)
        self.assertEqual(detail, "get_account_balance:nonce_recovered")
        recover.assert_called_once()

    def test_auth_probe_nonce_recovery_failure_blocks(self) -> None:
        broker = _AlwaysFailBroker()
        with patch.object(
            TradingStrategy,
            "_recover_nonce_auth_probe",
            return_value=(False, "redis_unavailable"),
        ) as recover:
            ok, detail = self.strategy._heartbeat_auth_verify(broker)
        self.assertFalse(ok)
        self.assertIn("nonce_recovery=redis_unavailable", detail)
        recover.assert_called_once()

    def test_non_nonce_auth_failure_does_not_trigger_recovery(self) -> None:
        broker = _NonNonceFailBroker()
        with patch.object(
            TradingStrategy,
            "_recover_nonce_auth_probe",
            return_value=(True, "probe_server_sync"),
        ) as recover:
            ok, detail = self.strategy._heartbeat_auth_verify(broker)
        self.assertFalse(ok)
        self.assertIn("EAuth:Invalid key", detail)
        recover.assert_not_called()


if __name__ == "__main__":
    unittest.main()
