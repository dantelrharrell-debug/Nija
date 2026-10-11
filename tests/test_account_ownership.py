"""Regression tests for preparation without moving live personal positions."""

import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from bot.account_ownership import account_identity, business_account_profiles, business_credentials
from bot.platform_account_layer import PlatformAccountLayer


class AccountOwnershipTests(unittest.TestCase):
    def test_default_preserves_legacy_identity(self):
        with patch.dict(os.environ, {}, clear=True):
            identity = account_identity("platform")
            self.assertEqual(identity["execution_user_id"], "platform")
            self.assertEqual(identity["ownership_type"], "unverified")
            self.assertEqual(PlatformAccountLayer().get_status().staged_business_accounts, [])

    def test_dante_label_retains_existing_ledger_and_credentials(self):
        env = {
            "NIJA_ACCOUNT_OWNERSHIP_MODE": "dante_personal",
            "KRAKEN_API_KEY": "test-personal-key",
            "KRAKEN_API_SECRET": "test-personal-secret",
        }
        with patch.dict(os.environ, env, clear=True):
            layer = PlatformAccountLayer()
            status = layer.get_status()
            self.assertEqual(status.current_account_identity["owner_id"], "dante")
            self.assertEqual(status.current_account_identity["account_role"], "master_user")
            self.assertEqual(status.current_account_identity["execution_user_id"], "platform")
            self.assertEqual(layer.get_platform_credentials()["api_key"], "test-personal-key")
            self.assertTrue(layer.has_platform_account("KRAKEN"))
            self.assertEqual(len(status.staged_business_accounts), 4)
            self.assertEqual(business_credentials("KRAKEN"), {})

    def test_business_keys_cannot_fill_from_personal_or_partial_keys(self):
        for exchange in ("KRAKEN", "COINBASE", "ALPACA", "OKX"):
            with self.subTest(exchange=exchange):
                env = {
                    f"{exchange}_API_KEY": "test-personal-key",
                    f"{exchange}_API_SECRET": "test-personal-secret",
                    f"{exchange}_NIJA_BUSINESS_API_KEY": "test-business-key",
                }
                self.assertEqual(business_credentials(exchange, env), {})

    def test_okx_requires_own_passphrase(self):
        env = {
            "OKX_NIJA_BUSINESS_API_KEY": "test-business-key",
            "OKX_NIJA_BUSINESS_API_SECRET": "test-business-secret",
            "OKX_PASSPHRASE": "test-personal-passphrase",
        }
        self.assertEqual(business_credentials("OKX", env), {})
        env["OKX_NIJA_BUSINESS_PASSPHRASE"] = "test-business-passphrase"
        self.assertEqual(business_credentials("OKX", env)["passphrase"], "test-business-passphrase")

    def test_duplicate_api_key_rejected(self):
        for suffix in ("API_KEY", "PLATFORM_API_KEY", "USER_DANTE_API_KEY"):
            with self.subTest(suffix=suffix):
                env = {
                    f"KRAKEN_{suffix}": "test-same-key",
                    "KRAKEN_NIJA_BUSINESS_API_KEY": "test-same-key",
                    "KRAKEN_NIJA_BUSINESS_API_SECRET": "test-business-secret",
                }
                with self.assertRaises(ValueError):
                    business_credentials("KRAKEN", env)

    def test_keys_do_not_enable_business_or_replace_legacy_account(self):
        env = {
            "NIJA_ACCOUNT_OWNERSHIP_MODE": "dante_personal",
            "KRAKEN_NIJA_BUSINESS_API_KEY": "test-business-key",
            "KRAKEN_NIJA_BUSINESS_API_SECRET": "test-business-secret",
        }
        with patch.dict(os.environ, env, clear=True):
            self.assertTrue(business_credentials("KRAKEN"))
            layer = PlatformAccountLayer()
            self.assertFalse(layer.has_platform_account("KRAKEN"))
            for profile in business_account_profiles():
                self.assertFalse(profile["enabled"])
                self.assertIsNone(profile["execution_user_id"])

    def test_other_users_unchanged(self):
        with patch.dict(os.environ, {"NIJA_ACCOUNT_OWNERSHIP_MODE": "dante_personal"}, clear=True):
            self.assertEqual(account_identity("daivon_frazier")["owner_id"], "daivon_frazier")

    def test_dashboard_dante_pnl_keeps_legacy_query_key(self):
        from bot import user_dashboard_api as dashboard

        tracker = Mock()
        tracker.get_stats.return_value = {"total_pnl": 12.5}
        tracker.get_recent_trades.return_value = []
        tracker.get_daily_breakdown.return_value = []
        state = SimpleNamespace(balance=50.0, circuit_breaker_triggered=False)
        risk = Mock(_user_states={"platform": state})
        risk.get_state.return_value = state
        controls = Mock(user_kill_switches={"platform": False})
        controls.can_trade.return_value = (False, "existing_gate")
        with patch.dict(os.environ, {"NIJA_ACCOUNT_OWNERSHIP_MODE": "dante_personal"}, clear=True), \
                patch.object(dashboard, "get_user_pnl_tracker", return_value=tracker), \
                patch.object(dashboard, "get_user_risk_manager", return_value=risk), \
                patch.object(dashboard, "get_hard_controls", return_value=controls):
            client = dashboard.app.test_client()
            response = client.get("/api/users")
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["users"][0]["display_name"], "Dante")
            self.assertEqual(data["users"][0]["user_id"], "platform")
            self.assertFalse(data["users"][0]["can_trade"])
            self.assertEqual(len(data["staged_business_accounts"]), 4)
            response = client.get("/api/user/platform/pnl")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json()["owner_id"], "dante")
            self.assertEqual(response.get_json()["stats"]["total_pnl"], 12.5)
            tracker.get_stats.assert_called_with("platform", force_refresh=True)


if __name__ == "__main__":
    unittest.main()
