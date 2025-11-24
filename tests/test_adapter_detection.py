import unittest
from unittest.mock import patch, MagicMock

import nija_client


class FakeAdapter:
    def __init__(self, client, accounts):
        self.client = client
        self.client_name = getattr(client, "name", "fake")
        self._accounts = accounts

    def get_accounts(self):
        return self._accounts


class TestAdapterDetection(unittest.TestCase):
    @patch("nija_client.create_adapter")
    def test_no_client(self, mock_create_adapter):
        # Simulate create_adapter returning an Adapter with no client
        mock_create_adapter.return_value = FakeAdapter(None, [])
        c = nija_client.CoinbaseClient()
        self.assertFalse(c.is_connected())
        self.assertEqual(c.fetch_accounts(), [])

    @patch("nija_client.create_adapter")
    def test_client_present(self, mock_create_adapter):
        # Simulate adapter with a client and non-empty account list
        fake_client = MagicMock()
        fake_client.name = "mock-client"
        mock_create_adapter.return_value = FakeAdapter(fake_client, [{"id": "acct-1", "balance": "1000"}])
        c = nija_client.CoinbaseClient()
        self.assertTrue(c.is_connected())
        self.assertGreater(len(c.fetch_accounts()), 0)


if __name__ == "__main__":
    unittest.main()
