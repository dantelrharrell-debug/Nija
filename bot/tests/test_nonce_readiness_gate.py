import unittest
from unittest.mock import patch

from bot.broker_integration import KrakenBrokerAdapter


class _FakeNonceManager:
    def __init__(self, can_issue: bool, *, ensure_error: Exception | None = None, lease_version: int = 1):
        self._can_issue = can_issue
        self._ensure_error = ensure_error
        self.lease_version = lease_version
        self.calls = []
        self.ensure_calls = []

    def ensure_writer_lock(self, key_id: str) -> None:
        self.ensure_calls.append(key_id)
        if self._ensure_error is not None:
            raise self._ensure_error

    def can_issue_nonce(self, key_id: str) -> bool:
        self.calls.append(key_id)
        return self._can_issue


class _FakeKrakenAPI:
    def __init__(self):
        self.calls = []

    def query_private(self, method, params=None):
        self.calls.append((method, params))
        return {"result": "ok", "method": method, "params": params}


class TestKrakenNonceReadinessGate(unittest.TestCase):
    def test_primary_api_call_is_blocked_when_writer_authority_invalid(self):
        adapter = KrakenBrokerAdapter(api_key="k", api_secret="s")
        adapter.api = _FakeKrakenAPI()
        adapter._distributed_nonce_manager = _FakeNonceManager(can_issue=True)
        adapter._nonce_key_id = "kid"

        with patch(
            "bot.broker_integration.assert_distributed_writer_authority",
            side_effect=RuntimeError("writer fence mismatch"),
        ):
            with self.assertRaises(RuntimeError) as ctx:
                adapter._kraken_api_call_primary("Balance")

        self.assertIn("writer authority is not valid", str(ctx.exception))
        self.assertEqual(adapter.api.calls, [])
        self.assertIsNone(adapter._distributed_nonce_manager)
        self.assertEqual(adapter._nonce_key_id, "")

    def test_primary_api_call_is_blocked_when_nonce_not_ready(self):
        adapter = KrakenBrokerAdapter(api_key="k", api_secret="s")
        adapter.api = _FakeKrakenAPI()
        adapter._distributed_nonce_manager = _FakeNonceManager(can_issue=False)
        adapter._nonce_key_id = "kid"

        with patch(
            "bot.broker_integration.assert_distributed_writer_authority",
            return_value=None,
        ):
            with self.assertRaises(RuntimeError) as ctx:
                adapter._kraken_api_call_primary("Balance")

        self.assertIn("nonce readiness gate blocked API call", str(ctx.exception))
        self.assertEqual(adapter.api.calls, [])

    def test_primary_api_call_is_allowed_when_nonce_ready(self):
        adapter = KrakenBrokerAdapter(api_key="k", api_secret="s")
        adapter.api = _FakeKrakenAPI()
        adapter._distributed_nonce_manager = _FakeNonceManager(can_issue=True)
        adapter._nonce_key_id = "kid"

        with patch(
            "bot.broker_integration.assert_distributed_writer_authority",
            return_value=None,
        ):
            response = adapter._kraken_api_call_primary("Balance")

        self.assertEqual(response.get("result"), "ok")
        self.assertEqual(adapter.api.calls, [("Balance", None)])
        self.assertEqual(adapter._nonce_lease_version, 1)

    def test_secondary_api_call_is_blocked_when_nonce_not_ready(self):
        adapter = KrakenBrokerAdapter(api_key="k", api_secret="s")
        adapter._distributed_nonce_manager = _FakeNonceManager(can_issue=False)
        adapter._nonce_key_id = "kid"

        with patch(
            "bot.broker_integration.assert_distributed_writer_authority",
            return_value=None,
        ):
            with self.assertRaises(RuntimeError) as ctx:
                adapter._kraken_api_call_secondary("Balance")

        self.assertIn("nonce readiness gate blocked API call", str(ctx.exception))

    def test_primary_api_call_drops_nonce_authority_when_lease_is_lost(self):
        adapter = KrakenBrokerAdapter(api_key="k", api_secret="s")
        adapter.api = _FakeKrakenAPI()
        adapter._distributed_nonce_manager = _FakeNonceManager(
            can_issue=True,
            ensure_error=RuntimeError("Redis writer lease rejected"),
        )
        adapter._nonce_key_id = "kid"
        adapter._nonce_lease_version = 2

        with patch(
            "bot.broker_integration.assert_distributed_writer_authority",
            return_value=None,
        ):
            with self.assertRaises(RuntimeError) as ctx:
                adapter._kraken_api_call_primary("Balance")

        self.assertIn("lease unavailable", str(ctx.exception))
        self.assertIsNone(adapter._distributed_nonce_manager)
        self.assertEqual(adapter._nonce_key_id, "")
        self.assertEqual(adapter._nonce_lease_version, 0)


if __name__ == "__main__":
    unittest.main()
