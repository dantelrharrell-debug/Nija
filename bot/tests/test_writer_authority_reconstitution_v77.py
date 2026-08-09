from __future__ import annotations

import importlib
import os
import types
import unittest


class FakeRedis:
    def __init__(self, lock_key: str, lock_value: str, generation: int, pttl: int = 60000):
        self.values = {lock_key: lock_value, "nija:lease:generation": str(generation)}
        self.lock_key = lock_key
        self._pttl = pttl

    def get(self, key):
        return self.values.get(key)

    def pttl(self, key):
        return self._pttl if key == self.lock_key else -2


class WriterAuthorityReconstitutionV77Tests(unittest.TestCase):
    def setUp(self):
        self.mod = importlib.import_module("bot.writer_authority_reconstitution_v77_patch")
        self.saved = {key: os.environ.get(key) for key in (
            "NIJA_WRITER_LEASE_ACQUIRED",
            "NIJA_WRITER_LEASE_GENERATION",
            "NIJA_WRITER_GENERATION",
            "NIJA_WRITER_FENCING_TOKEN",
            "NIJA_LEASE_GENERATION_KEY",
        )}

    def tearDown(self):
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def runtime(self, generation=3405, lock_value="owner-abc", token="fence-3405", pttl=60000):
        lock_key = "nija:writer:lock"
        return types.SimpleNamespace(
            acquired=True,
            lost=False,
            _local_fallback=False,
            _generation=generation,
            _token=token,
            _lock_key=lock_key,
            _lock_value=lock_value,
            _client=FakeRedis(lock_key, lock_value, generation, pttl),
        )

    def test_exact_owner_proof_uses_runtime_and_redis_not_env_generation(self):
        os.environ["NIJA_WRITER_LEASE_GENERATION"] = "0"
        os.environ.pop("NIJA_WRITER_LEASE_ACQUIRED", None)
        proof, reason = self.mod.exact_owner_proof(self.runtime())
        self.assertIsNotNone(proof)
        self.assertEqual(proof["generation"], 3405)
        self.assertEqual(reason, "exact_runtime_redis_owner")

    def test_foreign_redis_lock_is_never_adopted(self):
        runtime = self.runtime()
        runtime._client.values[runtime._lock_key] = "different-owner"
        proof, reason = self.mod.exact_owner_proof(runtime)
        self.assertIsNone(proof)
        self.assertEqual(reason, "redis_lock_owner_mismatch")

    def test_generation_mismatch_is_never_adopted(self):
        runtime = self.runtime()
        runtime._client.values["nija:lease:generation"] = "3406"
        proof, reason = self.mod.exact_owner_proof(runtime)
        self.assertIsNone(proof)
        self.assertIn("redis_generation_mismatch", reason)

    def test_expired_lock_is_never_reconstituted(self):
        proof, reason = self.mod.exact_owner_proof(self.runtime(pttl=0))
        self.assertIsNone(proof)
        self.assertIn("ttl_not_positive", reason)

    def test_publish_repairs_complete_local_lineage_after_proof(self):
        runtime = self.runtime()
        proof, _ = self.mod.exact_owner_proof(runtime)
        self.mod._ensure_renewal_worker = lambda _runtime: None
        self.mod._refresh_canonical_heartbeat = lambda generation, source: True
        ok, generation, reason = self.mod.publish_local_lineage(proof, "unit")
        self.assertTrue(ok)
        self.assertEqual(generation, 3405)
        self.assertEqual(reason, "exact_owner_reconstituted")
        self.assertEqual(os.environ["NIJA_WRITER_LEASE_ACQUIRED"], "1")
        self.assertEqual(os.environ["NIJA_WRITER_LEASE_GENERATION"], "3405")
        self.assertEqual(os.environ["NIJA_WRITER_GENERATION"], "3405")
        self.assertEqual(os.environ["NIJA_WRITER_FENCING_TOKEN"], "fence-3405")


if __name__ == "__main__":
    unittest.main()
