"""Offline unittest coverage: no connections, credentials or production state."""
from __future__ import annotations

import copy
from concurrent.futures import ThreadPoolExecutor
import hashlib
import hmac
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
import unittest
import uuid
from dataclasses import replace

# Import the isolated file, NOT bot.__init__ (which installs runtime patches).
_SPEC = importlib.util.spec_from_file_location(
    "_offline_kraken_redis_evidence_tests", Path(__file__).resolve().parents[1] / "kraken_redis_evidence.py",
)
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)
FIELDS = _MODULE.FIELDS
EvidenceDenied = _MODULE.EvidenceDenied
RedisEvidenceReader = _MODULE.RedisEvidenceReader
ReviewedBinding = _MODULE.ReviewedBinding
ScopeObservation = _MODULE.ScopeObservation
inventory_keys = _MODULE.inventory_keys
offline_manifest = _MODULE.offline_manifest
plan_offline_inventory_record = _MODULE.plan_offline_inventory_record


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class ReadOnlyRedis:
    """Atomic in-memory read test double that rejects every write command."""

    def __init__(self):
        self.values = {}
        self.ttls = {}
        self.executions = 0
        self.commands = []
        self.hook = None
        self.error = None

    def pipeline(self, *, transaction):
        if transaction is not True:
            raise AssertionError("Atomic read transaction required")
        return ReadPipeline(self)


class ReadPipeline:
    """Minimal Redis pipeline preserving byte values and missing-key behavior."""

    def __init__(self, redis):
        self.redis = redis
        self.operations = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def __getattr__(self, command):
        if command not in {"get", "smembers", "pttl"}:
            raise AssertionError("Write or scan attempted: " + command)

        def append(key):
            self.operations.append((command, key))
            return self
        return append

    def execute(self):
        redis = self.redis
        redis.executions += 1
        if redis.error:
            raise redis.error
        if redis.hook:
            redis.hook(redis.executions)
        redis.commands.extend(self.operations)
        result = []
        for command, key in self.operations:
            value = redis.values.get(key)
            if command == "get":
                result.append(value)
            elif command == "smembers":
                result.append(copy.deepcopy(value or set()))
            else:
                result.append(redis.ttls.get(key, -1 if key in redis.values else -2))
        return result


class RedisEvidenceTests(unittest.TestCase):
    """Strict certification denials and field-specific v452 output."""

    def setUp(self):
        self.redis = ReadOnlyRedis()
        self.scope = ScopeObservation(
            account="platform:kraken", api_key_sha256="a" * 64,
            process_lock_value="fence-token:instance=reviewed;boot=reviewed-boot",
            process_generation=12, nonce_owner="nonce-owner",
            nonce_fingerprint="nonce-process-fingerprint", nonce_lease_version=7,
        )
        self.rows = [{
            "account": self.scope.account, "api_key_sha256": self.scope.api_key_sha256,
            "intent_id": "intent-1", "intent_digest": "1" * 64, "kind": "intent",
            "attempt_n": 0, "token": "reservation-token", "state": "filled",
            "order_id": "exchange-order-1", "reconciliation_reference": "offline-history:row-1",
        }]
        # A detached HMAC is used ONLY as a local signature-verifier fixture.
        # Production must independently provision its trust anchor and verifier.
        self.signing_key = b"unit-test-only-not-a-production-credential"
        self.manifest_key, self.members_key, self.record_prefix = inventory_keys(self.scope.account)
        self.binding = ReviewedBinding(
            expected_scope=self.scope, provider_ids=("reviewed:dedup", "reviewed:writer", "reviewed:nonce"),
            review_reference="independent-review:fixture", coverage_sha256="0" * 64,
            submission_routes=("private:AddOrder", "pipeline:retry"),
            deployment_sha256="d" * 64, source_binding_sha256="e" * 64, observe_scope=lambda: self.scope,
            verify_coverage=lambda payload, signature: hmac.compare_digest(
                hmac.new(self.signing_key, payload, hashlib.sha256).hexdigest(), signature),
        )
        self.proof = {
            "account": self.scope.account, "api_key_sha256": self.scope.api_key_sha256,
            "deployment_sha256": self.binding.deployment_sha256,
            "source_binding_sha256": self.binding.source_binding_sha256,
            "provider_ids": dict(zip(FIELDS, self.binding.provider_ids)),
            "review_reference": self.binding.review_reference, "routes": list(self.binding.submission_routes),
            "legacy_submission_disabled": True, "history_start_epoch": 0, "cutover_epoch": 900.0,
            "reconciled_history_sha256": "c" * 64,
            "authoritative_boundary_reference": "reviewed:full-exchange-history-and-cutover",
        }
        self._install_inventory()
        reader = self.reader()
        controls = [
            self.scope.process_lock_value, "12", self.scope.nonce_owner, "7", "7",
            self.scope.nonce_fingerprint, "1700000000001",
        ]
        for (_, key), value in zip(reader._controls(), controls):
            self.redis.values[key] = value.encode()
        for index in (0, 2, 3, 5):
            self.redis.ttls[reader._controls()[index][1]] = 30000

    def _install_inventory(self):
        rows = sorted(self.rows, key=lambda row: row["intent_digest"])
        self.proof["inventory_sha256"] = digest(rows)
        self.proof["record_count"] = len(rows)
        self.binding = replace(self.binding, coverage_sha256=digest(self.proof))
        manifest = {
            "schema": "kraken_inventory_v1", "mode": "reviewed_cutover",
            "account": self.scope.account, "api_key_sha256": self.scope.api_key_sha256,
            "record_count": len(rows), "revision": 1, "coverage": self.proof,
            "signature": hmac.new(self.signing_key, canonical(self.proof).encode(), hashlib.sha256).hexdigest(),
        }
        self.redis.values[self.manifest_key] = canonical(manifest).encode()
        self.redis.values[self.members_key] = {row["intent_digest"].encode() for row in rows}
        for row in rows:
            self.redis.values[self.record_prefix + row["intent_digest"]] = canonical(row).encode()
            self.redis.values["nija:control:v2:idempotency:" + row["intent_digest"]] = (
                row["token"] + "|" + row["state"]).encode()

    def reader(self, clock=None):
        return RedisEvidenceReader(self.redis, self.binding, clock=clock or (lambda: 1000.0))

    def assert_denied(self):
        with self.assertRaises(EvidenceDenied):
            self.reader().collect()

    def test_complete_reviewed_fixture_has_distinct_v452_rows_and_no_writes(self):
        rows = self.reader().collect()
        self.assertEqual(set(rows), set(FIELDS))
        self.assertEqual(len({row["evidence_id"] for row in rows.values()}), 3)
        for index, field in enumerate(FIELDS):
            row = rows[field]
            self.assertEqual(row["provider_id"], self.binding.provider_ids[index])
            self.assertEqual(row["account"], self.scope.account)
            self.assertEqual(row["source"], "writer_authority")
            self.assertTrue(row["verified"] and row["scope_verified"] and row["read_only"])
            self.assertFalse(row["authorizes_orders"])
            self.assertEqual(row["observed_at_epoch"], 1000.0)
            self.assertTrue(all(row["provenance"].values()))
        self.assertTrue(all(command in {"get", "smembers", "pttl"} for command, _ in self.redis.commands))
        again = self.reader().collect()
        self.assertTrue(all(rows[field]["evidence_id"] != again[field]["evidence_id"] for field in FIELDS))

    def test_absent_inventory_is_not_inferred_from_legacy_keys(self):
        del self.redis.values[self.manifest_key]
        self.assert_denied()

    def test_empty_scan_or_caller_boolean_cannot_create_completeness(self):
        self.redis.values[self.manifest_key] = canonical({
            "schema": "kraken_inventory_v1", "mode": "reviewed_cutover", "record_count": 0,
            "complete": True, "snapshot_complete": True, "independently_reviewed": True,
        })
        self.redis.values[self.members_key] = set()
        self.assert_denied()

    def test_offline_manifest_can_never_certify(self):
        self.redis.values[self.manifest_key] = offline_manifest(self.scope.account, self.scope.api_key_sha256)
        self.assert_denied()

    def test_missing_inventory_record_or_fence_denies(self):
        for key in (self.record_prefix + "1" * 64, "nija:control:v2:idempotency:" + "1" * 64):
            with self.subTest(key=key):
                original = self.redis.values.pop(key)
                self.assert_denied()
                self.redis.values[key] = original

    def test_deleted_member_and_adjusted_count_cannot_forge_signed_inventory(self):
        self.redis.values[self.members_key] = set()
        manifest = json.loads(self.redis.values[self.manifest_key])
        manifest["record_count"] = 0
        self.redis.values[self.manifest_key] = canonical(manifest)
        self.assert_denied()

    def test_unknown_pending_submitted_and_unresolved_retries_deny(self):
        for state in ("submitted", "submitted_pending", "pending", "state_unknown", "unknown", "released", ""):
            with self.subTest(state=state):
                self.rows[0]["state"] = state
                self._install_inventory()
                self.assert_denied()

    def test_reconciled_rejection_without_exchange_order_is_terminal(self):
        self.rows[0]["state"] = "reconciled_rejected"
        self.rows[0].pop("order_id")
        self._install_inventory()
        self.assertEqual(set(self.reader().collect()), set(FIELDS))

    def test_duplicate_attempt_or_exchange_order_denies(self):
        other = dict(self.rows[0], intent_digest="2" * 64)
        self.rows.append(other)
        self._install_inventory()
        self.assert_denied()
        other["intent_id"] = "different-intent"
        self._install_inventory()
        self.assert_denied()

    def test_retry_history_must_be_contiguous_and_resolved(self):
        self.rows.append(dict(
            self.rows[0], intent_digest="2" * 64, attempt_n=2, kind="retry", order_id="order-2",
        ))
        self._install_inventory()
        self.assert_denied()
        self.rows[1]["attempt_n"] = 1
        self._install_inventory()
        self.assertEqual(set(self.reader().collect()), set(FIELDS))

    def test_fence_token_state_and_record_scope_must_match(self):
        fence = "nija:control:v2:idempotency:" + "1" * 64
        self.redis.values[fence] = b"other-owner|filled"
        self.assert_denied()
        for change in ({"account": "other:kraken"}, {"api_key_sha256": "b" * 64}):
            with self.subTest(change=change):
                original = copy.deepcopy(self.rows)
                self.rows[0].update(change)
                self._install_inventory()
                self.assert_denied()
                self.rows = original

    def test_all_writer_lineages_owner_fingerprint_and_counters_are_checked(self):
        controls = self.reader()._controls()
        for _, key in controls:
            with self.subTest(key=key):
                original = self.redis.values[key]
                self.redis.values[key] = b"999"
                if key.startswith("nija:kraken:nonce:"):
                    self.redis.values[key] = b"0"
                self.assert_denied()
                self.redis.values[key] = original

    def test_expired_persistent_or_near_expiry_lease_denies(self):
        for index in (0, 2, 3, 5):
            key = self.reader()._controls()[index][1]
            for ttl in (-2, -1, 0, 999, 1000):
                with self.subTest(index=index, ttl=ttl):
                    self.redis.ttls[key] = ttl
                    self.assert_denied()
            self.redis.ttls[key] = 30000

    def test_inventory_and_record_ttls_must_be_persistent(self):
        for key in (self.manifest_key, self.members_key, self.record_prefix + "1" * 64):
            with self.subTest(key=key):
                self.redis.ttls[key] = 60000
                self.assert_denied()
                del self.redis.ttls[key]

    def test_nonce_and_version_counters_must_be_persistent(self):
        for index in (4, 6):
            key = self.reader()._controls()[index][1]
            with self.subTest(key=key):
                self.redis.ttls[key] = 10000
                self.assert_denied()
                del self.redis.ttls[key]

    def test_concurrent_membership_change_is_detected(self):
        def change(execution):
            if execution == 2:
                self.redis.values[self.members_key].add(b"2" * 64)
        self.redis.hook = change
        self.assert_denied()

    def test_generation_or_inventory_change_between_snapshots_denies(self):
        for mode in ("generation", "inventory"):
            with self.subTest(mode=mode):
                self.redis.executions = 0
                def change(execution):
                    if execution == 3:
                        if mode == "generation":
                            self.redis.values[self.binding.process_generation_key] = b"13"
                        else:
                            manifest = json.loads(self.redis.values[self.manifest_key])
                            manifest["revision"] += 1
                            self.redis.values[self.manifest_key] = canonical(manifest)
                self.redis.hook = change
                self.assert_denied()
                self.redis.values[self.binding.process_generation_key] = b"12"
                self._install_inventory()

    def test_scope_and_key_change_before_or_after_reads_denies(self):
        for field in ("account", "api_key_sha256", "nonce_lease_version", "process_generation"):
            with self.subTest(field=field):
                count = [0]
                def observe():
                    count[0] += 1
                    return self.scope if count[0] == 1 else replace(
                        self.scope, **{field: 99 if "version" in field or "generation" in field else "changed"})
                binding = replace(self.binding, observe_scope=observe)
                with self.assertRaises(EvidenceDenied):
                    RedisEvidenceReader(self.redis, binding, clock=lambda: 1000).collect()

    def test_nonce_may_advance_but_not_regress(self):
        nonce_key = self.reader()._controls()[6][1]
        for next_value, accepted in ((1700000000002, True), (1700000000000, False)):
            with self.subTest(next_value=next_value):
                self.redis.executions = 0
                self.redis.values[nonce_key] = b"1700000000001"
                def change(execution):
                    if execution == 3:
                        self.redis.values[nonce_key] = str(next_value).encode()
                self.redis.hook = change
                if accepted:
                    self.reader().collect()
                else:
                    self.assert_denied()

    def test_redis_errors_are_sanitized_and_do_not_fallback(self):
        self.redis.error = RuntimeError("sensitive Redis connection payload")
        with self.assertRaisesRegex(EvidenceDenied, "^redis_evidence_unavailable$"):
            self.reader().collect()

    def test_stale_reversed_invalid_clocks_and_elapsed_lease_expiry_deny(self):
        for times in ((1000, 1061), (1000, 999), (float("nan"),), (1000, 1030)):
            with self.subTest(times=times):
                clock = iter(times)
                with self.assertRaises(EvidenceDenied):
                    self.reader(clock=lambda: next(clock)).collect()

    def test_time_spent_in_independent_verification_is_included_in_freshness(self):
        clock = iter((1000, 1000, 1061))
        with self.assertRaisesRegex(EvidenceDenied, "evidence_stale"):
            self.reader(clock=lambda: next(clock)).collect()

    def test_huge_retry_index_fails_closed_without_unbounded_iteration(self):
        self.rows[0].update(kind="retry", attempt_n=10 ** 100)
        self._install_inventory()
        self.assert_denied()

    def test_independent_verifier_failure_and_error_deny(self):
        def broken_verifier(payload, signature):
            raise RuntimeError("sensitive verifier details")
        for verifier in (lambda payload, signature: False, broken_verifier):
            with self.subTest(verifier=verifier), self.assertRaises(EvidenceDenied):
                RedisEvidenceReader(
                    self.redis, replace(self.binding, verify_coverage=verifier), clock=lambda: 1000,
                ).collect()

    def test_no_signed_full_history_boundary_or_legacy_route_coverage_denies(self):
        for change in (
            {"history_start_epoch": 1}, {"history_start_epoch": False},
            {"legacy_submission_disabled": False}, {"routes": ["private:AddOrder"]},
            {"reconciled_history_sha256": ""}, {"authoritative_boundary_reference": ""},
            {"cutover_epoch": 1001}, {"deployment_sha256": "e" * 64},
            {"source_binding_sha256": "f" * 64}, {"provider_ids": {}},
        ):
            with self.subTest(change=change):
                original = dict(self.proof)
                self.proof.update(change)
                self._install_inventory()
                self.assert_denied()
                self.proof = original

    def test_unpinned_proof_bad_signature_and_unreviewed_binding_deny(self):
        manifest = json.loads(self.redis.values[self.manifest_key])
        manifest["signature"] = "forged"
        self.redis.values[self.manifest_key] = canonical(manifest)
        self.assert_denied()
        self._install_inventory()
        for change in (
            {"coverage_sha256": "f" * 64}, {"review_reference": ""},
            {"verify_coverage": None}, {"provider_ids": ("same", "same", "same")},
        ):
            with self.subTest(change=change), self.assertRaises(EvidenceDenied):
                RedisEvidenceReader(self.redis, replace(self.binding, **change), clock=lambda: 1000).collect()

    def test_malformed_redis_payloads_never_certify(self):
        for key, value in (
            (self.manifest_key, b"\xff"), (self.manifest_key, b"[]"),
            (self.record_prefix + "1" * 64, b"not-json"), (self.members_key, {b"../foreign"}),
        ):
            with self.subTest(key=key, value=value):
                original = self.redis.values[key]
                self.redis.values[key] = value
                self.assert_denied()
                self.redis.values[key] = original


class OfflineInventoryDesignTests(unittest.TestCase):
    """New infrastructure is inert, opt-in and separate from the reader."""

    def setUp(self):
        self.row = {
            "account": "platform:kraken", "api_key_sha256": "a" * 64,
            "intent_digest": "1" * 64, "intent_id": "intent", "attempt_n": 0,
            "kind": "intent", "token": "owner-token", "state": "submitted",
        }

    def test_manifest_is_offline_and_has_no_completeness_or_activation(self):
        manifest = json.loads(offline_manifest("platform:kraken", "a" * 64))
        self.assertEqual(manifest["mode"], "offline_unactivated")
        self.assertNotIn("coverage", manifest)
        self.assertNotIn("signature", manifest)

    def test_reserve_plan_has_atomic_record_index_and_actual_fence_schema(self):
        plan = plan_offline_inventory_record(self.row)
        self.assertEqual(len(plan.keys), 6)
        self.assertEqual(plan.keys[3], "nija:control:v2:idempotency:" + "1" * 64)
        self.assertIn("offline_unactivated", plan.script)
        self.assertIn("SADD", plan.script)
        self.assertIn("EXISTS", plan.script)
        self.assertIn("revision", plan.script)
        self.assertIn("'|submitted'", plan.script)
        self.assertFalse(hasattr(plan, "execute"))
        self.assertFalse(hasattr(plan, "activate"))
        self.assertEqual(json.loads(plan.args[1]), self.row)

    def test_finalize_plan_cas_preserves_owner_identity_and_durable_tombstones(self):
        self.row.update(state="filled", order_id="exchange-1", reconciliation_reference="history:1")
        plan = plan_offline_inventory_record(self.row, finalize=True)
        for guard in ("row.token ~= next.token", "row.attempt_n ~= next.attempt_n", "row.state ~= 'submitted'"):
            self.assertIn(guard, plan.script)
        for command in ("DEL", "EXPIRE", "PEXPIRE", "PSETEX", "INCR"):
            self.assertNotIn("redis.call('" + command + "'", plan.script)

    def test_invalid_fingerprint_token_digest_attempt_and_terminal_proof_deny(self):
        for change in (
            {"api_key_sha256": "not-a-fingerprint"},  # pragma: allowlist secret - invalid synthetic hash
            {"token": "owner|injection"},
            {"intent_digest": "../foreign"}, {"attempt_n": True}, {"attempt_n": 1},
            {"state": "unknown"},
        ):
            with self.subTest(change=change), self.assertRaises(EvidenceDenied):
                plan_offline_inventory_record(dict(self.row, **change))
        with self.assertRaises(EvidenceDenied):
            plan_offline_inventory_record(dict(self.row, state="filled"), finalize=True)


class RealIsolatedRedisTests(unittest.TestCase):
    """Run inert plans only against a private foreground, Unix-socket server."""

    @classmethod
    def setUpClass(cls):
        executable = shutil.which("redis-server")
        if executable is None:
            raise unittest.SkipTest("redis-server executable is unavailable")
        try:
            import redis
        except ImportError:
            raise unittest.SkipTest("Python redis dependency is unavailable") from None
        cls.redis_module = redis
        # Deliberately keep private scratch files inside the repository, never
        # the system temporary directories or any configured production socket.
        cls.directory = Path.cwd() / (".redis-evidence-" + uuid.uuid4().hex[:12])
        cls.directory.mkdir(mode=0o700)
        cls.socket = cls.directory / "redis.sock"
        cls.process = None
        cls.client = None
        try:
            cls.process = subprocess.Popen(
                [
                    executable, "--port", "0", "--bind", "127.0.0.1",
                    "--unixsocket", str(cls.socket), "--unixsocketperm", "700",
                    "--save", "", "--appendonly", "no", "--daemonize", "no",
                    "--dir", str(cls.directory), "--loglevel", "warning",
                ],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            )
            cls.client = redis.Redis(
                unix_socket_path=str(cls.socket), socket_timeout=1, socket_connect_timeout=1,
            )
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if cls.process.poll() is not None:
                    raise AssertionError("Private Redis server exited before readiness")
                if not cls.socket.exists():
                    time.sleep(0.02)
                    continue
                try:
                    if cls.client.ping():
                        return
                except redis.exceptions.ConnectionError:
                    time.sleep(0.02)
            raise AssertionError("Private Redis server did not become responsive")
        except BaseException:
            cls._cleanup_server()
            raise

    @classmethod
    def _cleanup_server(cls):
        if cls.client is not None:
            cls.client.close()
            cls.client.connection_pool.disconnect()
        if cls.process is not None:
            if cls.process.poll() is None:
                cls.process.terminate()  # Explicit owned PID; never name-based killing.
                try:
                    cls.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    cls.process.kill()
                    cls.process.wait(timeout=5)
            if cls.process.stdout is not None:
                cls.process.stdout.close()
        if cls.directory.exists():
            shutil.rmtree(cls.directory)

    @classmethod
    def tearDownClass(cls):
        cls._cleanup_server()

    def setUp(self):
        # This client only knows the newly spawned private Unix socket, port 0.
        self.client.flushdb()
        self.fixture = RedisEvidenceTests(methodName="test_absent_inventory_is_not_inferred_from_legacy_keys")
        self.fixture.setUp()
        self.row = dict(self.fixture.rows[0], state="submitted")
        self.row.pop("order_id")
        self.row.pop("reconciliation_reference")
        self.manifest_key, self.members_key, self.record_prefix = inventory_keys(self.row["account"])

    def install_offline(self):
        self.client.set(
            self.manifest_key, offline_manifest(self.row["account"], self.row["api_key_sha256"]),
        )

    def execute_plan(self, row, *, finalize=False):
        plan = plan_offline_inventory_record(row, finalize=finalize)
        return self.client.eval(plan.script, len(plan.keys), *plan.keys, *plan.args)

    def install_reviewed_fixture(self):
        for key, value in self.fixture.redis.values.items():
            if isinstance(value, set):
                if value:
                    self.client.sadd(key, *value)
            else:
                self.client.set(key, value)
        for key, ttl in self.fixture.redis.ttls.items():
            self.client.pexpire(key, ttl)

    def test_real_concurrent_duplicate_reservation_is_atomic_and_durable(self):
        self.install_offline()
        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(lambda _: self.execute_plan(self.row), range(24)))
        self.assertEqual(results.count(1), 1)
        self.assertEqual(results.count(0), 23)
        manifest = json.loads(self.client.get(self.manifest_key))
        self.assertEqual((manifest["record_count"], manifest["revision"]), (1, 2))
        self.assertEqual(self.client.smembers(self.members_key), {self.row["intent_digest"].encode()})
        plan = plan_offline_inventory_record(self.row)
        self.assertEqual(json.loads(self.client.get(plan.keys[2])), self.row)
        self.assertEqual(self.client.get(plan.keys[3]), b"reservation-token|submitted")
        self.assertEqual(self.client.get(plan.keys[4]), self.row["intent_digest"].encode())
        self.assertTrue(all(self.client.pttl(key) == -1 for key in plan.keys[:5]))
        alternate = dict(self.row, intent_digest="2" * 64)
        self.assertEqual(self.execute_plan(alternate), 0)  # Same attempt, different digest.
        self.assertEqual(self.client.scard(self.members_key), 1)

    def test_real_finalization_rejects_stale_owner_and_preserves_consistent_inventory(self):
        self.install_offline()
        self.assertEqual(self.execute_plan(self.row), 1)
        terminal = dict(
            self.row, state="filled", order_id="exchange-1", reconciliation_reference="history:1",
        )
        for changes in ({"token": "stale-owner"}, {"intent_id": "different-intent"}, {"account": "other:kraken"}):
            with self.subTest(changes=changes):
                candidate = dict(terminal, **changes)
                if "account" in changes:
                    with self.assertRaises(self.redis_module.exceptions.ResponseError):
                        self.execute_plan(candidate, finalize=True)
                else:
                    self.assertEqual(self.execute_plan(candidate, finalize=True), 0)
        self.assertEqual(json.loads(self.client.get(self.manifest_key))["revision"], 2)
        self.assertEqual(self.execute_plan(terminal, finalize=True), 1)
        self.assertEqual(self.execute_plan(terminal, finalize=True), 0)
        plan = plan_offline_inventory_record(terminal, finalize=True)
        self.assertEqual(json.loads(self.client.get(plan.keys[2])), terminal)
        self.assertEqual(self.client.get(plan.keys[3]), b"reservation-token|filled")
        manifest = json.loads(self.client.get(self.manifest_key))
        self.assertEqual((manifest["record_count"], manifest["revision"]), (1, 3))
        self.assertEqual(self.client.scard(self.members_key), 1)
        self.assertTrue(all(self.client.pttl(key) == -1 for key in plan.keys))

    def test_real_duplicate_exchange_order_finalization_is_rejected(self):
        self.install_offline()
        second = dict(self.row, intent_id="second-intent", intent_digest="2" * 64, token="second-owner")
        for row in (self.row, second):
            self.assertEqual(self.execute_plan(row), 1)
        first_terminal = dict(self.row, state="filled", order_id="same-order", reconciliation_reference="history:1")
        second_terminal = dict(second, state="filled", order_id="same-order", reconciliation_reference="history:2")
        self.assertEqual(self.execute_plan(first_terminal, finalize=True), 1)
        self.assertEqual(self.execute_plan(second_terminal, finalize=True), 0)
        self.assertEqual(
            json.loads(self.client.get(self.record_prefix + second["intent_digest"]))["state"], "submitted",
        )
        self.assertEqual(json.loads(self.client.get(self.manifest_key))["record_count"], 2)

    def test_real_invalid_index_type_fails_before_any_reservation_writes(self):
        self.install_offline()
        self.client.set(self.members_key, "not-a-set")
        with self.assertRaises(self.redis_module.exceptions.ResponseError):
            self.execute_plan(self.row)
        plan = plan_offline_inventory_record(self.row)
        self.assertIsNone(self.client.get(plan.keys[2]))
        self.assertIsNone(self.client.get(plan.keys[3]))
        self.assertEqual(json.loads(self.client.get(self.manifest_key))["revision"], 1)

    def test_real_snapshot_has_only_read_commands_and_existing_safeguards_are_unchanged(self):
        self.install_reviewed_fixture()
        before_values = {
            key: self.client.get(key) for _, key in self.fixture.reader()._controls()
        }
        before = self.client.info("commandstats")
        rows = RedisEvidenceReader(self.client, self.fixture.binding, clock=lambda: 1000).collect()
        after = self.client.info("commandstats")
        self.assertEqual(set(rows), set(FIELDS))
        changed = {
            command.removeprefix("cmdstat_") for command, info in after.items()
            if info["calls"] > before.get(command, {}).get("calls", 0)
        }
        self.assertTrue(changed <= {"get", "smembers", "pttl", "multi", "exec", "info"}, changed)
        self.assertEqual(
            before_values, {key: self.client.get(key) for _, key in self.fixture.reader()._controls()},
        )

    def test_real_offline_manifest_can_never_certify_even_with_terminal_records(self):
        self.install_reviewed_fixture()
        self.install_offline()
        manifest = json.loads(self.client.get(self.manifest_key))
        manifest["record_count"] = 1
        self.client.set(self.manifest_key, canonical(manifest))
        with self.assertRaisesRegex(EvidenceDenied, "authoritative_cutover_required"):
            RedisEvidenceReader(self.client, self.fixture.binding, clock=lambda: 1000).collect()

    def test_real_redis_wrongtype_and_authentication_errors_fail_closed(self):
        self.install_reviewed_fixture()
        key = self.record_prefix + self.row["intent_digest"]
        self.client.delete(key)
        self.client.lpush(key, "wrong-type")
        with self.assertRaisesRegex(EvidenceDenied, "^redis_evidence_unavailable$"):
            RedisEvidenceReader(self.client, self.fixture.binding, clock=lambda: 1000).collect()
        unavailable = self.redis_module.Redis(
            unix_socket_path=str(self.socket), password="invalid-offline-fixture-password",
            socket_connect_timeout=0.1,
        )
        try:
            with self.assertRaisesRegex(EvidenceDenied, "^redis_evidence_unavailable$"):
                RedisEvidenceReader(unavailable, self.fixture.binding, clock=lambda: 1000).collect()
        finally:
            unavailable.close()
            unavailable.connection_pool.disconnect()


if __name__ == "__main__":
    unittest.main()
