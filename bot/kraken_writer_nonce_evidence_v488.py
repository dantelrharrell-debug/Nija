"""v488: read-only, account-pinned Kraken writer and nonce evidence.

Uses the EXISTING connected KrakenBrokerAdapter, its exact nonce manager,
the canonical read-only process writer assertion and Redis diagnostic reads.
Never creates a client, issues a nonce, acquires/renews a lease, writes an order,
changes ledger state, registers a collector, or grants execution authority.

Both observations are v452 single-field diagnostics. A separately approved
account/key inventory and real runtime integration review are required.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import time
from collections.abc import Callable, Mapping
from typing import Any

from bot.kraken_authenticated_key_info_v477 import _sha256_fingerprint
from scripts.nija_kraken_readonly_history_collector_v441 import _broker_account_scope

FIELDS = ("writer_lease", "nonce_sequence")
_MAX_AGE_S = 60.0
_MIN_TTL_MS = 5000
_MISSING = object()


class KrakenWriterEvidenceDenied(ValueError):
    """Non-sensitive, fixed denial code; never include key or Redis payload."""


def _identifier(value: Any) -> bool:
    return isinstance(value, str) and bool(value) and value == value.strip() and not any(
        char.isspace() for char in value
    )


def _positive_int(value: Any) -> bool:
    return type(value) is int and value > 0


def _finite_nonnegative(value: Any) -> bool:
    return (type(value) in (float, int) and math.isfinite(value) and value >= 0)


def _nonce_bindings(broker: Any, api: Any) -> tuple[Any, Any, Any]:
    manager = getattr(broker, "_distributed_nonce_manager", _MISSING)
    if manager is _MISSING:
        manager = getattr(broker, "nonce_manager", None)
    key_id = getattr(broker, "_nonce_key_id", _MISSING)
    if key_id is _MISSING:
        key_id = getattr(broker, "api_key_id", None)
    generator = getattr(broker, "_nonce_generator", _MISSING)
    if generator is _MISSING:
        generator = getattr(api, "_nonce", None)
    return manager, key_id, generator


def make_kraken_writer_nonce_providers(
    broker: Any, *, account_scope: str, approved_api_key_sha256: str,
    reviewed_provider_ids: Mapping[str, str],
    independently_reviewed: bool = False,
    clock: Callable[[], float] = time.time,
) -> Mapping[str, Callable[[], Mapping[str, Any]]]:
    """Create two distinct v452 writers from the real read-only runtime APIs.

    This only supports the explicitly reviewed default platform Kraken key.
    A production composition root must independently prove that the approved
    fingerprint and broker account map to that key before invoking it.
    """
    if independently_reviewed is not True:
        raise KrakenWriterEvidenceDenied("independent_review_required")
    if account_scope != "platform:kraken":
        raise KrakenWriterEvidenceDenied("platform_kraken_scope_required")
    try:
        key_pin = _sha256_fingerprint(approved_api_key_sha256)
    except Exception:
        raise KrakenWriterEvidenceDenied("reviewed_key_pin_required") from None
    if (not isinstance(reviewed_provider_ids, Mapping)
            or set(reviewed_provider_ids) != set(FIELDS)
            or any(not _identifier(reviewed_provider_ids[field]) for field in FIELDS)
            or not callable(clock)):
        raise KrakenWriterEvidenceDenied("reviewed_writer_provider_ids_required")

    def read(field: str) -> Mapping[str, Any]:
        try:
            started = clock()
            if not _finite_nonnegative(started) or started <= 0:
                raise KrakenWriterEvidenceDenied("observation_clock_invalid")
            if getattr(broker, "connected", False) is not True:
                raise KrakenWriterEvidenceDenied("broker_disconnected")
            if _broker_account_scope(broker) != account_scope:
                raise KrakenWriterEvidenceDenied("broker_scope_mismatch")
            api = getattr(broker, "api", None)
            key = getattr(api, "key", None)
            broker_key = getattr(broker, "api_key", key)
            if (not isinstance(key, str) or not key
                    or not isinstance(broker_key, str) or key != broker_key
                    or not hmac.compare_digest(
                        hashlib.sha256(key.encode("utf-8")).hexdigest(), key_pin)):
                raise KrakenWriterEvidenceDenied("broker_key_pin_mismatch")
            if (getattr(broker, "_gateway_url", "")
                    or getattr(broker, "_gateway_only_mode", False)):
                raise KrakenWriterEvidenceDenied("direct_nonce_owner_required")
            expected_key_id = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
            manager, nonce_key_id, generator = _nonce_bindings(broker, api)
            if (manager is None or nonce_key_id != expected_key_id
                    or getattr(manager, "_redis", None) is None
                    or getattr(manager, "_strict_redis_lease", None) is not True
                    or not callable(getattr(manager, "get_writer_lease_status", None))
                    or not callable(getattr(manager, "get_last_nonce", None))):
                raise KrakenWriterEvidenceDenied("exact_redis_nonce_owner_missing")
            api_generator = getattr(api, "_nonce", None)
            if (not callable(generator)
                    or api_generator is not generator):
                raise KrakenWriterEvidenceDenied("nonce_dispatch_binding_changed")

            # This canonical assertion reads the process Redis fence; it never
            # acquires or renews any lock. Do not call can_issue_nonce() here:
            # that method may invoke ensure_writer_lease() and mutate Redis.
            from bot.execution_authority_context import assert_distributed_writer_authority
            assert_distributed_writer_authority()

            def status() -> tuple[str, int, int, float]:
                row = manager.get_writer_lease_status(expected_key_id)
                if (not isinstance(row, Mapping) or row.get("enabled") is not True
                        or row.get("key_id") != expected_key_id
                        or row.get("error") not in (None, "")
                        or not _identifier(row.get("owner_id"))
                        or row.get("owner_id") != getattr(manager, "_owner_id", None)
                        or row.get("owner_fingerprint") != getattr(manager, "_owner_fingerprint", None)
                        or not _positive_int(row.get("token"))
                        or not _positive_int(row.get("ttl_remaining_ms"))
                        or row["ttl_remaining_ms"] < _MIN_TTL_MS
                        or not _finite_nonnegative(row.get("stable_for_s"))):
                    raise KrakenWriterEvidenceDenied("redis_writer_lease_unverified")
                return (row["owner_id"], row["token"],
                        row["ttl_remaining_ms"], float(row["stable_for_s"]))

            first = status()
            local_version = getattr(manager, "lease_version", None)
            broker_version = getattr(broker, "_nonce_lease_version", local_version)
            if (not _positive_int(local_version) or local_version != first[1]
                    or not _positive_int(broker_version) or broker_version != first[1]):
                raise KrakenWriterEvidenceDenied("nonce_generation_mismatch")
            nonce_counter = None
            if field == "nonce_sequence":
                left = manager.get_last_nonce(expected_key_id)
                right = manager.get_last_nonce(expected_key_id)
                if (not _positive_int(left) or not _positive_int(right) or right < left):
                    raise KrakenWriterEvidenceDenied("nonce_counter_unverified")
                nonce_counter = right
            second = status()
            assert_distributed_writer_authority()
            finished = clock()
            if (not _finite_nonnegative(finished)
                    or not 0 <= finished - started <= _MAX_AGE_S
                    or first[:2] != second[:2]
                    or second[2] < _MIN_TTL_MS
                    or not _finite_nonnegative(second[3])
                    or getattr(broker, "connected", False) is not True
                    or _broker_account_scope(broker) != account_scope
                    or getattr(broker, "_nonce_lease_version", first[1]) != first[1]
                    or getattr(manager, "lease_version", None) != first[1]
                    or getattr(api, "key", None) != key
                    or getattr(api, "_nonce", None) is not generator):
                raise KrakenWriterEvidenceDenied("writer_evidence_changed_or_stale")
            current_manager, current_key_id, current_generator = _nonce_bindings(broker, api)
            if (current_manager is not manager or current_key_id != expected_key_id
                    or current_generator is not generator):
                raise KrakenWriterEvidenceDenied("writer_evidence_changed_or_stale")

            digest = hashlib.sha256(json.dumps(
                [field, account_scope, first[0], first[1], nonce_counter, repr(started)],
                separators=(",", ":"),
            ).encode("utf-8")).hexdigest()
            return {
                "account": account_scope,
                "source": "writer_authority",
                "provider_id": reviewed_provider_ids[field],
                "evidence_id": digest,
                "verified": True,
                "read_only": True,
                "scope_verified": True,
                "observed_at_epoch": started,
                "authorizes_orders": False,
                "provenance": {
                    "account_scope_verified": True,
                    "collector_identity_verified": True,
                    "snapshot_complete": True,
                    "writer_fencing_verified": True,
                },
            }
        except KrakenWriterEvidenceDenied:
            raise
        except Exception:
            raise KrakenWriterEvidenceDenied("writer_runtime_unavailable") from None

    return {field: (lambda field=field: read(field)) for field in FIELDS}


__all__ = ["FIELDS", "KrakenWriterEvidenceDenied", "make_kraken_writer_nonce_providers"]
