from __future__ import annotations

import os
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from cryptography.fernet import Fernet

from auth import APIKeyManager
from auth.user_database import UserDatabase
from billing_store import BillingStore
from config.user_loader import UserConfigLoader
from user_live_trading_access import (
    discover_runtime_paid_users,
    evaluate_live_trading_access,
    hydrate_runtime_credentials,
)
from vault import SecureVault
from account_exit_management_recovery_patch import _normal_user_entries_allowed


class _UserDB:
    def __init__(self, users):
        self.users = users

    def get_user(self, user_id):
        return self.users.get(user_id)


class _Billing:
    def __init__(self, records):
        self.records = records

    def get(self, user_id):
        return self.records.get(user_id)

    def list_by_status(self, statuses):
        allowed = {str(s).lower() for s in statuses}
        return [r for r in self.records.values() if r.status.lower() in allowed]


class _Vault:
    def __init__(self, credentials):
        self.credentials = credentials

    def list_user_brokers(self, user_id):
        return sorted(
            broker for uid, broker in self.credentials
            if uid == user_id
        )

    def get_credentials(self, user_id, broker):
        return self.credentials.get((user_id, broker))


class _KeyManager:
    def __init__(self):
        self.calls = []

    def store_user_api_key(self, **kwargs):
        self.calls.append(kwargs)


def _user(*, consent=True, education=False, enabled=True):
    return {
        "user_id": "user_abc123",
        "email": "paid@example.com",
        "enabled": enabled,
        "education_mode": education,
        "consented_to_live_trading": consent,
    }


class PaidUserAccessTests(unittest.TestCase):
    def setUp(self):
        self.uid = "user_abc123"
        self.users = _UserDB({self.uid: _user()})
        self.billing = _Billing({
            self.uid: SimpleNamespace(
                user_id=self.uid,
                status="active",
                current_period_end=int(time.time()) + 3600,
            )
        })
        self.vault = _Vault({
            (self.uid, "kraken"): {
                "api_key": "key",
                "api_secret": "secret",
                "broker": "kraken",
            }
        })

    def test_active_paid_consented_live_user_is_allowed(self):
        decision = evaluate_live_trading_access(
            self.uid,
            user_db=self.users,
            billing_store=self.billing,
            vault=self.vault,
        )
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.blocker, "none")
        self.assertEqual(decision.brokers, ("kraken",))

    def test_unpaid_user_fails_closed(self):
        billing = _Billing({
            self.uid: SimpleNamespace(
                user_id=self.uid,
                status="past_due",
                current_period_end=int(time.time()) + 3600,
            )
        })
        decision = evaluate_live_trading_access(
            self.uid,
            user_db=self.users,
            billing_store=billing,
            vault=self.vault,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.blocker, "paid_entitlement_inactive")

    def test_expired_active_period_fails_closed(self):
        billing = _Billing({
            self.uid: SimpleNamespace(
                user_id=self.uid,
                status="active",
                current_period_end=int(time.time()) - 1,
            )
        })
        decision = evaluate_live_trading_access(
            self.uid,
            user_db=self.users,
            billing_store=billing,
            vault=self.vault,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.blocker, "paid_entitlement_expired")

    def test_missing_consent_fails_closed(self):
        users = _UserDB({self.uid: _user(consent=False)})
        decision = evaluate_live_trading_access(
            self.uid,
            user_db=users,
            billing_store=self.billing,
            vault=self.vault,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.blocker, "live_trading_consent_missing")

    def test_education_mode_fails_closed(self):
        users = _UserDB({self.uid: _user(education=True)})
        decision = evaluate_live_trading_access(
            self.uid,
            user_db=users,
            billing_store=self.billing,
            vault=self.vault,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.blocker, "education_mode_active")

    def test_missing_credentials_fails_closed(self):
        decision = evaluate_live_trading_access(
            self.uid,
            user_db=self.users,
            billing_store=self.billing,
            vault=_Vault({}),
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.blocker, "broker_credentials_missing")

    def test_hydration_is_all_or_nothing(self):
        vault = _Vault({
            (self.uid, "kraken"): {
                "api_key": "key",
                "api_secret": "secret",
                "broker": "kraken",
            },
            (self.uid, "coinbase"): None,
        })
        key_manager = _KeyManager()
        with self.assertRaises(PermissionError):
            hydrate_runtime_credentials(
                self.uid,
                user_db=self.users,
                billing_store=self.billing,
                vault=vault,
                api_key_manager=key_manager,
            )
        self.assertEqual(key_manager.calls, [])

    def test_discovery_returns_independent_runtime_config(self):
        key_manager = _KeyManager()
        configs = discover_runtime_paid_users(
            user_db=self.users,
            billing_store=self.billing,
            vault=self.vault,
            api_key_manager=key_manager,
        )
        self.assertEqual(len(configs), 1)
        cfg = configs[0]
        self.assertEqual(cfg["user_id"], self.uid)
        self.assertEqual(cfg["broker_type"], "kraken")
        self.assertTrue(cfg["independent_trading"])
        self.assertTrue(cfg["active_trading"])
        self.assertTrue(cfg["entitlement_required"])
        self.assertEqual(cfg["source"], "paid_entitlement_vault")
        self.assertEqual(len(key_manager.calls), 1)


class PersistenceTests(unittest.TestCase):
    def test_billing_store_enumerates_only_requested_statuses(self):
        with tempfile.TemporaryDirectory() as td:
            store = BillingStore(os.path.join(td, "users.db"))
            store.upsert(user_id="u_active", status="active")
            store.upsert(user_id="u_due", status="past_due")
            rows = store.list_by_status({"active"})
            self.assertEqual([r.user_id for r in rows], ["u_active"])

    def test_user_database_persists_consent_and_mode(self):
        with tempfile.TemporaryDirectory() as td:
            db = UserDatabase(os.path.join(td, "users.db"))
            self.assertTrue(db.create_user("u1", "u1@example.com", "Password123!"))
            self.assertTrue(db.record_live_trading_consent("u1"))
            self.assertTrue(db.set_education_mode("u1", False))
            user = db.get_user("u1")
            self.assertTrue(user["consented_to_live_trading"])
            self.assertFalse(user["education_mode"])
            self.assertIsNotNone(user["live_trading_consent_at"])
            self.assertIsNotNone(user["risk_acknowledged_at"])

    def test_runtime_loader_merges_dynamic_paid_user_without_static_file(self):
        dynamic = [{
            "user_id": "user_paid1",
            "name": "paid@example.com",
            "account_type": "retail",
            "broker_type": "kraken",
            "enabled": True,
            "description": "Dynamic paid live-trading customer",
            "copy_from_platform": False,
            "disabled_symbols": [],
            "independent_trading": True,
            "active_trading": True,
            "entitlement_required": True,
            "source": "paid_entitlement_vault",
        }]
        with tempfile.TemporaryDirectory() as td:
            loader = UserConfigLoader(config_dir=td)
            with patch(
                "user_live_trading_access.discover_runtime_paid_users",
                return_value=dynamic,
            ):
                self.assertTrue(loader.load_all_users())
            enabled = loader.get_all_enabled_users()
            self.assertEqual(
                [(u.user_id, u.broker_type) for u in enabled],
                [("user_paid1", "kraken")],
            )
            self.assertTrue(enabled[0].entitlement_required)
            self.assertEqual(enabled[0].source, "paid_entitlement_vault")
            # The singleton loader refresh path must be idempotent: registry
            # reads may run repeatedly while looking for newly paid customers.
            again = loader.get_all_enabled_users()
            self.assertEqual(
                [(u.user_id, u.broker_type) for u in again],
                [("user_paid1", "kraken")],
            )


class RuntimeRevocationTests(unittest.TestCase):
    def test_dynamic_entitlement_denial_blocks_normal_entries(self):
        config = SimpleNamespace(
            active_trading=True,
            independent_trading=True,
            entitlement_required=True,
        )
        trader = SimpleNamespace(
            multi_account_manager=SimpleNamespace(
                user_configs={"user_paid": config}
            ),
            should_start_user_independent_thread=lambda user_id: True,
        )
        with patch(
            "user_live_trading_access.entitlement_allows_new_entries",
            return_value=(False, "paid_entitlement_inactive"),
        ):
            self.assertFalse(
                _normal_user_entries_allowed(trader, "user_paid")
            )

    def test_static_operator_account_keeps_existing_entry_policy(self):
        config = SimpleNamespace(
            active_trading=True,
            independent_trading=True,
            entitlement_required=False,
        )
        trader = SimpleNamespace(
            multi_account_manager=SimpleNamespace(
                user_configs={"legacy_user": config}
            ),
            should_start_user_independent_thread=lambda user_id: True,
        )
        self.assertTrue(
            _normal_user_entries_allowed(trader, "legacy_user")
        )


class CredentialPrefixTests(unittest.TestCase):
    def test_dynamic_user_id_wires_short_and_full_broker_prefixes(self):
        key = Fernet.generate_key()
        manager = APIKeyManager(encryption_key=key)
        env_names = (
            "KRAKEN_USER_ABC123_API_KEY",
            "KRAKEN_USER_ABC123_API_SECRET",
        )
        for name in env_names:
            os.environ.pop(name, None)
        try:
            manager.store_user_api_key(
                user_id="user_abc123",
                broker="kraken",
                api_key="key",
                api_secret="secret",
            )
            self.assertEqual(os.environ["KRAKEN_USER_ABC123_API_KEY"], "key")
            self.assertEqual(os.environ["KRAKEN_USER_ABC123_API_SECRET"], "secret")
        finally:
            manager.delete_user_api_key("user_abc123", "kraken")
        for name in env_names:
            self.assertNotIn(name, os.environ)

    def test_production_vault_refuses_ephemeral_encryption_key(self):
        with tempfile.TemporaryDirectory() as td:
            with patch.dict(
                os.environ,
                {"ENVIRONMENT": "production"},
                clear=True,
            ):
                with self.assertRaises(RuntimeError):
                    SecureVault(os.path.join(td, "vault.db"))


if __name__ == "__main__":
    unittest.main()
