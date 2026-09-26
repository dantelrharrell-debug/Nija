from __future__ import annotations

import os
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from cryptography.fernet import Fernet

from paid_user_state import (
    RedisBillingStore,
    RedisCredentialVault,
    RedisPaidUserStore,
)
from user_live_trading_access import evaluate_live_trading_access


class FakePipeline:
    def __init__(self, client):
        self.client = client
        self.ops = []

    def hset(self, *args, **kwargs):
        self.ops.append(("hset", args, kwargs))
        return self

    def sadd(self, *args, **kwargs):
        self.ops.append(("sadd", args, kwargs))
        return self

    def srem(self, *args, **kwargs):
        self.ops.append(("srem", args, kwargs))
        return self

    def delete(self, *args, **kwargs):
        self.ops.append(("delete", args, kwargs))
        return self

    def lpush(self, *args, **kwargs):
        self.ops.append(("lpush", args, kwargs))
        return self

    def ltrim(self, *args, **kwargs):
        self.ops.append(("ltrim", args, kwargs))
        return self

    def execute(self):
        out = []
        for name, args, kwargs in self.ops:
            out.append(getattr(self.client, name)(*args, **kwargs))
        self.ops = []
        return out


class FakeRedis:
    def __init__(self):
        self.hashes = {}
        self.sets = {}
        self.values = {}
        self.lists = {}

    def ping(self):
        return True

    def pipeline(self):
        return FakePipeline(self)

    def hset(self, key, mapping=None, **kwargs):
        bucket = self.hashes.setdefault(key, {})
        bucket.update({str(k): str(v) for k, v in (mapping or {}).items()})
        return 1

    def hgetall(self, key):
        return dict(self.hashes.get(key, {}))

    def sadd(self, key, *values):
        bucket = self.sets.setdefault(key, set())
        before = len(bucket)
        bucket.update(str(v) for v in values)
        return len(bucket) - before

    def srem(self, key, *values):
        bucket = self.sets.setdefault(key, set())
        removed = 0
        for value in values:
            if str(value) in bucket:
                bucket.remove(str(value))
                removed += 1
        return removed

    def smembers(self, key):
        return set(self.sets.get(key, set()))

    def set(self, key, value):
        self.values[key] = str(value)
        return True

    def get(self, key):
        return self.values.get(key)

    def delete(self, key):
        existed = key in self.hashes or key in self.values
        self.hashes.pop(key, None)
        self.values.pop(key, None)
        return 1 if existed else 0

    def lpush(self, key, value):
        self.lists.setdefault(key, []).insert(0, str(value))
        return len(self.lists[key])

    def ltrim(self, key, start, end):
        self.lists[key] = self.lists.get(key, [])[start:end + 1]
        return True


class RedisPaidStateTests(unittest.TestCase):
    def setUp(self):
        self.redis = FakeRedis()
        self.key = Fernet.generate_key()
        self.users = RedisPaidUserStore(self.redis)
        self.billing = RedisBillingStore(self.redis)
        self.vault = RedisCredentialVault(self.redis, encryption_key=self.key)
        self.uid = "user_paid_001"

    def _seed_live_user(self):
        self.users.upsert_user(
            self.uid,
            email="paid@example.com",
            enabled=True,
            subscription_tier="pro",
            education_mode=False,
            consented_to_live_trading=True,
        )
        self.billing.upsert(
            user_id=self.uid,
            status="active",
            customer_id="cus_test",
            subscription_id="sub_test",
            current_period_end=int(time.time()) + 3600,
        )
        self.assertTrue(
            self.vault.store_credentials(
                self.uid,
                "kraken",
                "api-key-value",
                "api-secret-value",
                {"paper": False},
            )
        )

    def test_encrypted_credentials_survive_store_recreation(self):
        self._seed_live_user()

        raw = self.redis.hgetall(
            "nija:paid_user:v1:vault:user_paid_001:kraken"
        )
        self.assertNotIn("api-key-value", str(raw))
        self.assertNotIn("api-secret-value", str(raw))

        # Simulate process restart: new store objects, same Redis + same key.
        users2 = RedisPaidUserStore(self.redis)
        billing2 = RedisBillingStore(self.redis)
        vault2 = RedisCredentialVault(self.redis, encryption_key=self.key)

        self.assertEqual(users2.get_user(self.uid)["email"], "paid@example.com")
        self.assertEqual(billing2.get(self.uid).status, "active")
        creds = vault2.get_credentials(self.uid, "kraken")
        self.assertEqual(creds["api_key"], "api-key-value")
        self.assertEqual(creds["api_secret"], "api-secret-value")

    def test_live_access_uses_persistent_redis_records(self):
        self._seed_live_user()
        decision = evaluate_live_trading_access(
            self.uid,
            user_db=self.users,
            billing_store=self.billing,
            vault=self.vault,
        )
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.brokers, ("kraken",))

    def test_past_due_immediately_blocks_new_live_access(self):
        self._seed_live_user()
        self.billing.upsert(
            user_id=self.uid,
            status="past_due",
            subscription_id="sub_test",
            current_period_end=int(time.time()) + 3600,
        )
        decision = evaluate_live_trading_access(
            self.uid,
            user_db=self.users,
            billing_store=self.billing,
            vault=self.vault,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.blocker, "paid_entitlement_inactive")

    def test_expired_period_blocks_even_active_status(self):
        self._seed_live_user()
        self.billing.upsert(
            user_id=self.uid,
            status="active",
            subscription_id="sub_test",
            current_period_end=int(time.time()) - 1,
        )
        decision = evaluate_live_trading_access(
            self.uid,
            user_db=self.users,
            billing_store=self.billing,
            vault=self.vault,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.blocker, "paid_entitlement_expired")

    def test_consent_and_mode_are_persistent(self):
        self.users.upsert_user(
            self.uid,
            email="paid@example.com",
            enabled=True,
            education_mode=True,
            consented_to_live_trading=False,
        )
        self.assertTrue(self.users.record_live_trading_consent(self.uid))
        self.assertTrue(self.users.set_education_mode(self.uid, False))

        restarted = RedisPaidUserStore(self.redis).get_user(self.uid)
        self.assertTrue(restarted["consented_to_live_trading"])
        self.assertFalse(restarted["education_mode"])
        self.assertTrue(restarted["live_trading_consent_at"])
        self.assertTrue(restarted["risk_acknowledged_at"])

    def test_subscription_index_survives_status_changes(self):
        self.billing.upsert(
            user_id=self.uid,
            status="active",
            subscription_id="sub_test",
        )
        self.assertEqual(
            self.billing.find_user_by_subscription("sub_test"),
            self.uid,
        )
        self.assertEqual(
            [r.user_id for r in self.billing.list_by_status({"active"})],
            [self.uid],
        )

        self.billing.upsert(
            user_id=self.uid,
            status="canceled",
            subscription_id="sub_test",
        )
        self.assertEqual(self.billing.list_by_status({"active"}), [])
        self.assertEqual(
            [r.user_id for r in self.billing.list_by_status({"canceled"})],
            [self.uid],
        )

    def test_wrong_encryption_key_cannot_decrypt(self):
        self._seed_live_user()
        wrong = RedisCredentialVault(
            self.redis,
            encryption_key=Fernet.generate_key(),
        )
        self.assertIsNone(wrong.get_credentials(self.uid, "kraken"))

    def test_delete_removes_persistent_credential(self):
        self._seed_live_user()
        self.assertTrue(self.vault.delete_credentials(self.uid, "kraken"))
        self.assertEqual(self.vault.list_user_brokers(self.uid), [])
        self.assertIsNone(self.vault.get_credentials(self.uid, "kraken"))


if __name__ == "__main__":
    unittest.main()
