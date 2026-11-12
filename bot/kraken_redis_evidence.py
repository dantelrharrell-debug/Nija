"""Unactivated, read-only Redis evidence and explicitly offline inventory design.

Existing schemas:
* control.decision_context.UserScopedIdempotencyRegistry stores opaque account
  hashes as ``nija:control:v2:idempotency:<digest> = token|state`` with TTLs.
  Released/reconciled-rejected entries are DELETED. Neither SCAN nor an empty
  keyspace proves history completeness or account ownership.
* distributed_nonce_manager uses separate owner, fingerprint, lease_version,
  version_counter and nonce keys. Its generation is NOT the process generation.
* execution_authority_context uses a configured process lock and generation.
* deterministic_entry_validator.AttemptRecord and retry_handler are local
  retry decisions, NOT an authoritative durable submission inventory.

Consequently existing production data alone can NEVER certify complete order
history here. Canonical startup may construct its explicitly reviewed read-only
reader; it creates no clients and has no inventory activation/migration runner.
The proposed inventory is opt-in and
backward-compatible (existing key formats unchanged). Its offline write plan
must not be deployed without an independent review covering EVERY submission
and retry route, authoritative historical reconciliation, and an enforced
cutover that disables legacy/untracked writers. A caller boolean is not proof.

The independent composition root must pin provider identities, account/key and
signed coverage digest, and supply a separately reviewed signature verifier and
read-only scope observer. The verifier is a TRUST BOUNDARY, not a convenience
callback that may simply return True. This module cannot establish that trust
on its own. Offline manifests are deliberately uncertifiable.

Conservative limitation: all inventoried fences must still exist and match,
including historical terminal records. Expired/deleted legacy fences therefore
deny certification; this design does not silently reconstruct their history.
Coverage signs the complete inventory digest: every subsequent inventory change
requires fresh independent snapshot review/signing, not just revision updates.
The Lua plans have NOT been activated or integrated with submission dispatch.
Every row expires at read-start plus the minimum lease PTTL across both reads,
capped at 60 seconds. Duplicate evidence additionally expires with the earliest
expiring existing reservation fence; persistent fences cannot extend a lease.
No evidence produced here grants authority or replaces any execution safeguard.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

FIELDS = ("duplicate_order_fence", "writer_lease", "nonce_sequence")
_TERMINAL = frozenset({"filled", "cancelled", "reconciled_rejected"})
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_PREFIX = "nija:kraken:evidence:inventory:v1:"
_FENCE_PREFIX = "nija:control:v2:idempotency:"
_MAX_RECORDS = 10000


class EvidenceDenied(ValueError):
    """Fixed, non-sensitive failure reason; no Redis payload is included."""


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise EvidenceDenied(code)


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) and value == value.strip()


def _positive(value: Any) -> bool:
    return type(value) is int and value > 0


def _epoch(value: Any) -> bool:
    return type(value) in (float, int) and math.isfinite(value) and value > 0


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _decode(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="strict")
    _require(isinstance(value, str), "missing_or_invalid_record")
    return value


def inventory_keys(account: str) -> tuple[str, str, str]:
    """Return manifest, member index and durable-record prefix; never access Redis."""
    _require(_text(account), "account_required")
    prefix = _PREFIX + hashlib.sha256(account.encode()).hexdigest()
    return prefix + ":manifest", prefix + ":members", prefix + ":record:"


@dataclass(frozen=True)
class ScopeObservation:
    """Read-only runtime scope and both independent fencing lineages."""

    account: str
    api_key_sha256: str
    process_lock_value: str
    process_generation: int
    nonce_owner: str
    nonce_fingerprint: str
    nonce_lease_version: int


@dataclass(frozen=True)
class ReviewedBinding:
    """Externally approved pins; instantiate ONLY in an independently reviewed root.

    ``verify_coverage`` verifies a detached signature over canonical UTF-8 bytes
    against an independently provisioned trust anchor. ``coverage_sha256`` must
    also come from that review, NOT from the Redis manifest being inspected.
    ``source_binding_sha256`` pins the separately reviewed artifact binding the
    collector implementation, scope observer and signature verifier to these
    exact account/key/provider/deployment pins. Its hash is NOT self-attestation:
    the independent composition root must authenticate the artifact itself.
    No boolean ``independently_reviewed`` or completeness override is accepted.
    """

    expected_scope: ScopeObservation
    provider_ids: tuple[str, str, str]
    review_reference: str
    coverage_sha256: str
    submission_routes: tuple[str, ...]
    deployment_sha256: str
    source_binding_sha256: str
    observe_scope: Callable[[], ScopeObservation]
    verify_coverage: Callable[[bytes, str], bool]
    process_lock_key: str = "nija:writer_lock:global"
    process_generation_key: str = "nija:lease:generation"


class RedisEvidenceReader:
    """Read supplied Redis only using GET/SMEMBERS/PTTL in atomic transactions."""

    def __init__(
        self, redis_client: Any, binding: ReviewedBinding, *, clock: Callable[[], float] = time.time,
    ) -> None:
        self._redis = redis_client
        self._binding = binding
      …973 tokens truncated…mbership is not completeness. The signed boundary below supplies that.
        # Re-read it with every record so additions/deletions cannot be missed.
        control_ops = self._controls()
        ttl_ops = [("pttl", control_ops[i][1]) for i in (0, 2, 3, 5, 4, 6)]
        operations = control_ops + ttl_ops + [
            ("get", manifest_key), ("smembers", members_key), ("pttl", manifest_key), ("pttl", members_key),
        ]
        operations += [("get", record_prefix + member) for member in members]
        operations += [("pttl", record_prefix + member) for member in members]
        # Each member is the exact digest from decision_context.build_key().
        operations += [("get", _FENCE_PREFIX + member) for member in members]
        operations += [("pttl", _FENCE_PREFIX + member) for member in members]
        result = self._transaction(operations)
        _require(result[11:13] == [-1, -1], "nonce_counters_not_durable")
        manifest_raw, membership, manifest_ttl, membership_ttl = result[13:17]
        _require(
            manifest_raw == first_manifest and sorted(_decode(item) for item in membership) == members,
            "inventory_changed",
        )
        _require(manifest_ttl == -1 and (membership_ttl == -1 or not members and membership_ttl == -2),
                 "inventory_not_durable")
        count = len(members)
        records = [json.loads(_decode(item)) for item in result[17:17 + count]]
        record_ttls = result[17 + count:17 + 2 * count]
        _require(all(ttl == -1 for ttl in record_ttls), "inventory_not_durable")
        fences = [_decode(item) for item in result[17 + 2 * count:17 + 3 * count]]
        fence_ttls = result[17 + 3 * count:]
        manifest = json.loads(_decode(manifest_raw))
        _require(isinstance(manifest, dict) and all(isinstance(row, dict) for row in records), "inventory_invalid")
        _require(
            manifest.get("record_count") == count and type(manifest.get("record_count")) is int,
            "inventory_count_mismatch",
        )
        for member, row in zip(members, records):
            _require(row.get("intent_digest") == member, "inventory_record_mismatch")
        return result[:7], manifest, records, fences, result[7:11], fence_ttls

    def _coverage(self, manifest: dict[str, Any], rows: list[dict[str, Any]], now: float) -> None:
        binding = self._binding
        proof = manifest.get("coverage")
        _require(
            manifest.get("schema") == "kraken_inventory_v1"
            and manifest.get("mode") == "reviewed_cutover"
            and isinstance(proof, dict) and _text(manifest.get("signature")),
            "authoritative_cutover_required",
        )
        _require(_digest(proof) == binding.coverage_sha256, "coverage_pin_mismatch")
        _require(
            proof.get("account") == binding.expected_scope.account
            and manifest.get("account") == binding.expected_scope.account
            and manifest.get("api_key_sha256") == binding.expected_scope.api_key_sha256
            and proof.get("api_key_sha256") == binding.expected_scope.api_key_sha256
            and proof.get("deployment_sha256") == binding.deployment_sha256
            and proof.get("source_binding_sha256") == binding.source_binding_sha256
            and proof.get("provider_ids") == dict(zip(FIELDS, binding.provider_ids))
            and proof.get("review_reference") == binding.review_reference
            and proof.get("routes") == list(binding.submission_routes)
            and proof.get("legacy_submission_disabled") is True
            and proof.get("history_start_epoch") == 0
            and type(proof.get("history_start_epoch")) is int
            and _epoch(proof.get("cutover_epoch")) and proof["cutover_epoch"] <= now
            and _HEX.fullmatch(proof.get("reconciled_history_sha256", "")) is not None
            and _text(proof.get("authoritative_boundary_reference")),
            "incomplete_history_or_legacy_path",
        )
        # Pin the complete immutable inventory, not merely a caller-supplied
        # count. Deleting a member AND its record cannot forge completeness.
        # Any new reservation requires newly reviewed/signed snapshot coverage.
        _require(
            proof.get("inventory_sha256") == _digest(rows)
            and type(proof.get("record_count")) is int
            and proof["record_count"] == len(rows),
            "inventory_coverage_mismatch",
        )
        _require(
            binding.verify_coverage(_canonical(proof).encode(), manifest["signature"]) is True,
            "coverage_signature_unverified",
        )
        _require(_positive(manifest.get("revision")), "inventory_revision_invalid")

    def _validate_snapshot(self, snapshot: tuple, started: float, elapsed_ms: float) -> int:
        controls, manifest, rows, fences, ttls, fence_ttls = snapshot
        scope = self._binding.expected_scope
        decoded = [_decode(value) for value in controls]
        expected = [
            scope.process_lock_value, str(scope.process_generation), scope.nonce_owner,
            str(scope.nonce_lease_version), str(scope.nonce_lease_version), scope.nonce_fingerprint,
        ]
        _require(decoded[:6] == expected, "writer_ownership_or_generation_conflict")
        _require(all(type(ttl) is int and ttl > elapsed_ms + 1000 for ttl in ttls), "writer_lease_expired")
        _require(
            all(type(ttl) is int and (ttl == -1 or ttl > elapsed_ms + 1000) for ttl in fence_ttls),
            "intent_fence_expired",
        )
        _require(decoded[6].isdigit() and int(decoded[6]) > 0, "nonce_missing_or_invalid")
        self._coverage(manifest, rows, started)
        attempts: set[tuple[str, int]] = set()
        orders: set[str] = set()
        for row, fence in zip(rows, fences):
            _require(row.get("account") == scope.account, "record_account_mismatch")
            _require(row.get("api_key_sha256") == scope.api_key_sha256, "record_fingerprint_mismatch")
            _require(row.get("state") in _TERMINAL, "unresolved_submission_or_retry")
            _require(
                row.get("kind") in {"intent", "retry"} and _text(row.get("intent_id"))
                and type(row.get("attempt_n")) is int and row["attempt_n"] >= 0
                and (row["kind"] == "intent") == (row["attempt_n"] == 0)
                and _text(row.get("token")) and "|" not in row["token"]
                and _text(row.get("reconciliation_reference")),
                "record_invalid",
            )
            attempt = (row["intent_id"], row["attempt_n"])
            _require(attempt not in attempts, "duplicate_attempt")
            attempts.add(attempt)
            order_id = row.get("order_id")
            if row["state"] in {"filled", "cancelled"}:
                _require(_text(order_id), "terminal_order_missing")
            if order_id is not None:
                _require(_text(order_id) and order_id not in orders, "duplicate_order")
                orders.add(order_id)
            _require(fence == row["token"] + "|" + row["state"], "intent_fence_mismatch")
        for intent_id, attempt_n in attempts:
            _require(attempt_n <= len(attempts), "retry_history_missing")
            _require(all((intent_id, index) in attempts for index in range(attempt_n)), "retry_history_missing")
        return int(decoded[6])

    def collect(self) -> dict[str, dict[str, Any]]:
        """Return all three distinct v452 diagnostics, or deny the entire snapshot."""
        try:
            started = self._clock()
            _require(_epoch(started), "observation_clock_invalid")
            expected = self._binding.expected_scope
            _require(self._binding.observe_scope() == expected, "account_scope_changed")
            first = self._snapshot()
            left = self._validate_snapshot(first, started, 0)
            second = self._snapshot()
            finished = self._clock()
            _require(_epoch(finished) and 0 <= finished - started <= 60, "evidence_stale")
            right = self._validate_snapshot(second, started, (finished - started) * 1000)
            _require(
                all(ttl > (finished - started) * 1000 + 1000 for ttl in first[4]),
                "writer_lease_expired",
            )
            _require(first[0][:6] == second[0][:6] and first[1:4] == second[1:4],
                     "concurrent_inventory_or_generation_change")
            _require(right >= left, "nonce_regressed")
            _require(self._binding.observe_scope() == expected, "account_scope_changed")
            returned_at = self._clock()
            _require(_epoch(returned_at) and 0 <= returned_at - started <= 60, "evidence_stale")
            _require(returned_at >= finished, "observation_clock_invalid")
            _require(
                all(ttl > (returned_at - started) * 1000 + 1000 for ttl in first[4] + second[4]),
                "writer_lease_expired",
            )
            fence_ttls = first[5] + second[5]
            _require(
                all(ttl == -1 or ttl > (returned_at - started) * 1000 + 1000 for ttl in fence_ttls),
                "intent_fence_expired",
            )
            # Anchor ALL deadlines to read-start, never the later read/return
            # time. Both lineages fence every field; duplicate history also
            # depends on every existing expiring reservation remaining present.
            lease_lifetime = min(60.0, min(first[4] + second[4]) / 1000)
            expiring_fences = [ttl / 1000 for ttl in fence_ttls if ttl > 0]
            duplicate_lifetime = min([lease_lifetime] + expiring_fences)
            collection_id = uuid.uuid4().hex
            return {
                field: {
                    "account": expected.account, "source": "writer_authority",
                    "provider_id": provider, "evidence_id": collection_id + ":" + field,
                    "verified": True, "read_only": True, "scope_verified": True,
                    "observed_at_epoch": started, "authorizes_orders": False,
                    "expires_at_epoch": started + (
                        duplicate_lifetime if field == "duplicate_order_fence" else lease_lifetime
                    ),
                    "provenance": {
                        "account_scope_verified": True, "collector_identity_verified": True,
                        "snapshot_complete": True, "writer_fencing_verified": True,
                    },
                }
                for field, provider in zip(FIELDS, self._binding.provider_ids)
            }
        except EvidenceDenied:
            raise
        except Exception:
            raise EvidenceDenied("redis_evidence_unavailable") from None


# Separate, inert WRITE DESIGN. No execution API and no runtime registration.
# Each operation guards the OFFLINE manifest and updates the durable record,
# membership, revision/count and existing-format fence in one Redis Lua call.
# Production activation must be implemented elsewhere after independent review.
OFFLINE_RESERVE_LUA = """
local member_type = redis.call('TYPE', KEYS[2]).ok
if member_type ~= 'none' and member_type ~= 'set' then
    return redis.error_reply('inventory_type_invalid')
end
local raw = redis.call('GET', KEYS[1])
if not raw then return redis.error_reply('offline_manifest_required') end
local m = cjson.decode(raw)
if m.mode ~= 'offline_unactivated' or m.schema ~= 'kraken_inventory_v1' then
    return redis.error_reply('offline_only')
end
if type(m.record_count) ~= 'number' or type(m.revision) ~= 'number' then
    return redis.error_reply('manifest_invalid')
end
if redis.call('EXISTS', KEYS[3]) == 1 or redis.call('SISMEMBER', KEYS[2], ARGV[1]) == 1
   or redis.call('EXISTS', KEYS[5]) == 1
   or redis.call('EXISTS', KEYS[4]) == 1 then return 0 end
local row = cjson.decode(ARGV[2])
if row.account ~= m.account or row.api_key_sha256 ~= m.api_key_sha256 then
    return redis.error_reply('scope_mismatch')
end
redis.call('SET', KEYS[3], ARGV[2])
redis.call('SET', KEYS[5], ARGV[1])
redis.call('SADD', KEYS[2], ARGV[1])
redis.call('SET', KEYS[4], row.token .. '|submitted')
m.record_count = m.record_count + 1
m.revision = m.revision + 1
redis.call('SET', KEYS[1], cjson.encode(m))
return 1
"""

OFFLINE_FINALIZE_LUA = """
local raw = redis.call('GET', KEYS[1])
if not raw then return redis.error_reply('offline_manifest_required') end
local m = cjson.decode(raw)
if m.mode ~= 'offline_unactivated' or m.schema ~= 'kraken_inventory_v1' then
    return redis.error_reply('offline_only')
end
if type(m.revision) ~= 'number' then return redis.error_reply('manifest_invalid') end
local old = redis.call('GET', KEYS[3])
if not old or redis.call('SISMEMBER', KEYS[2], ARGV[1]) ~= 1 then return 0 end
local row = cjson.decode(old)
local next = cjson.decode(ARGV[2])
if row.account ~= m.account or row.api_key_sha256 ~= m.api_key_sha256
   or row.state ~= 'submitted' or row.token ~= next.token or row.account ~= next.account
   or row.api_key_sha256 ~= next.api_key_sha256 or row.intent_id ~= next.intent_id
   or row.attempt_n ~= next.attempt_n or row.kind ~= next.kind
   or row.intent_digest ~= next.intent_digest
   or redis.call('GET', KEYS[4]) ~= row.token .. '|submitted'
   or redis.call('GET', KEYS[5]) ~= ARGV[1] then return 0 end
if next.state ~= 'filled' and next.state ~= 'cancelled' and next.state ~= 'reconciled_rejected' then
    return redis.error_reply('terminal_reconciliation_required')
end
local has_order = next.order_id ~= nil and next.order_id ~= cjson.null
if has_order and redis.call('EXISTS', KEYS[6]) == 1 then return 0 end
redis.call('SET', KEYS[3], ARGV[2])
redis.call('SET', KEYS[4], next.token .. '|' .. next.state)
if has_order then redis.call('SET', KEYS[6], ARGV[1]) end
m.revision = m.revision + 1
redis.call('SET', KEYS[1], cjson.encode(m))
return 1
"""


@dataclass(frozen=True)
class OfflineInventoryOperation:
    """Inert Lua/KEYS/ARGV proposal; there is deliberately no execute method."""

    script: str
    keys: tuple[str, ...]
    args: tuple[str, ...]


def offline_manifest(account: str, api_key_sha256: str) -> str:
    """Build an uncertifiable manifest; no Redis access or activation is performed."""
    inventory_keys(account)
    _require(_HEX.fullmatch(api_key_sha256 or "") is not None, "fingerprint_required")
    return _canonical({
        "schema": "kraken_inventory_v1", "mode": "offline_unactivated", "account": account,
        "api_key_sha256": api_key_sha256, "record_count": 0, "revision": 1,
    })


def plan_offline_inventory_record(row: Mapping[str, Any], *, finalize: bool = False) -> OfflineInventoryOperation:
    """Plan atomic offline reservation/finalization without touching any client.

    The digest must be obtained from the real decision_context.build_key(),
    never by hashing an invented alternate intent schema. Retries need their
    own reservation digest and contiguous AttemptRecord-compatible attempt_n.
    Terminal records and member indexes never expire or disappear in this
    design. No tombstone is deleted, and a duplicate reservation fails closed.
    """
    row = dict(row)
    _require(_text(row.get("account")) and _HEX.fullmatch(row.get("api_key_sha256", "")) is not None,
             "record_scope_required")
    digest = row.get("intent_digest")
    _require(isinstance(digest, str) and _HEX.fullmatch(digest) is not None, "intent_digest_required")
    _require(
        _text(row.get("token")) and "|" not in row["token"] and _text(row.get("intent_id"))
        and type(row.get("attempt_n")) is int and row["attempt_n"] >= 0
        and row.get("kind") in {"intent", "retry"}
        and (row["kind"] == "intent") == (row["attempt_n"] == 0),
        "record_invalid",
    )
    _require(
        row.get("state") in _TERMINAL if finalize else row.get("state") == "submitted",
        "record_state_invalid",
    )
    if finalize:
        _require(_text(row.get("reconciliation_reference")), "reconciliation_required")
        _require(row["state"] == "reconciled_rejected" or _text(row.get("order_id")), "terminal_order_missing")
        _require(row.get("order_id") is None or _text(row["order_id"]), "terminal_order_invalid")
    manifest, members, prefix = inventory_keys(row["account"])
    attempt_key = prefix + "attempt:" + _digest([row["account"], row["intent_id"], row["attempt_n"]])
    order_key = prefix + "order:" + _digest([row["account"], row.get("order_id")])
    return OfflineInventoryOperation(
        OFFLINE_FINALIZE_LUA if finalize else OFFLINE_RESERVE_LUA,
        (manifest, members, prefix + digest, _FENCE_PREFIX + digest, attempt_key, order_key),
        (digest, _canonical(row)),
    )
