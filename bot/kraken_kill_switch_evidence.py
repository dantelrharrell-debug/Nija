"""Read-only durable kill-switch evidence through the existing Redis authority.

No clearing, signing, client construction, registration or order authorization.
The trusted root must independently review the exact global-to-account binding
and the legitimacy of the pinned clearance record. A runtime-observed hash is
not approval. WATCH detects changes, including change-and-revert, during a read.
This observation does not replace the existing per-order kill-switch check.
"""
from __future__ import annotations

import copy
import hashlib
import hmac
import json
import math
import os
import re
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


class KrakenKillSwitchDenied(ValueError):
    """Fixed denial code; never expose Redis records or exception contents."""


@dataclass(frozen=True, eq=False)
class ReviewedKillSwitchBinding:
    """Object and account pins supplied by independent production review."""

    account: str
    api_key_sha256: str
    provider_id: str
    durable_key: str
    clearance_sha256: str
    kill_switch: Any = field(repr=False)
    redis_client: Any = field(repr=False)


def _require(value: bool, reason: str) -> None:
    if not value:
        raise KrakenKillSwitchDenied(reason)


def _identifier(value: Any) -> bool:
    return (isinstance(value, str) and bool(value) and value == value.strip()
            and not any(c.isspace() for c in value))


def _finite(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        _require(key not in result, "durable_record_duplicate_field")
        result[key] = value
    return result


def _clearance(raw: Any, now: float) -> str:
    _require(isinstance(raw, (bytes, str)) and 0 < len(raw) <= 65536,
             "explicit_durable_clearance_required")
    try:
        row = json.loads(raw, object_pairs_hook=_unique_object)
        _require(isinstance(row, dict), "durable_record_invalid")
        _require(row.get("is_active") is False, "durable_clearance_not_clear")
        _require(type(row.get("schema")) is int and row["schema"] == 2,
                 "durable_clearance_schema_unreviewed")
        _require(isinstance(row.get("reason"), str) and bool(row["reason"].strip()),
                 "durable_clearance_reason_missing")
        stamp = datetime.fromisoformat(row["timestamp"])
        _require(stamp.tzinfo is not None and 0 < stamp.timestamp() <= now,
                 "durable_clearance_timestamp_invalid")
        encoded = json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except KrakenKillSwitchDenied:
        raise
    except Exception:
        raise KrakenKillSwitchDenied("durable_record_invalid") from None
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def make_kraken_kill_switch_provider(
    binding: ReviewedKillSwitchBinding, *,
    review_binding: Callable[[ReviewedKillSwitchBinding], bool],
    clock: Callable[[], float] = time.time,
) -> Callable[[], Mapping[str, Any]]:
    """Bind actual Redis and local kill-switch reads to one reviewed account.

``review_binding`` must verify independently approved object identity, account,
key, Redis deployment and clearance provenance. It is rechecked on each read.
The clearance hash is canonical UTF-8 JSON (sorted keys, compact separators,
no NaN). Its timestamp records the historical clearance event, not freshness.
Freshness comes from this uncached read and never exceeds sixty seconds.
Redis GET/PTTL are the only data commands; WATCH/MULTI/EXEC change no data.
    """
    try:
        _require(type(binding) is ReviewedKillSwitchBinding and callable(review_binding)
                 and review_binding(binding) is True, "independent_binding_review_required")
        _require(binding.account == "platform:kraken", "reviewed_platform_scope_required")
        _require(all(_identifier(v) for v in (binding.provider_id, binding.durable_key)),
                 "reviewed_source_identity_required")
        _require(all(isinstance(v, str) and re.fullmatch(r"[a-f0-9]{64}", v)
                     for v in (binding.api_key_sha256, binding.clearance_sha256)),
                 "reviewed_fingerprints_required")
        _require(callable(clock) and callable(getattr(binding.kill_switch, "get_status", None))
                 and callable(getattr(binding.redis_client, "pipeline", None)),
                 "existing_authority_interfaces_required")
    except KrakenKillSwitchDenied:
        raise
    except Exception:
        raise KrakenKillSwitchDenied("binding_review_failed") from None

    def local_status() -> Mapping[str, Any]:
        _require(getattr(binding.kill_switch, "DURABLE_REDIS_KEY", None) == binding.durable_key,
                 "durable_key_binding_changed")
        # get_status is read-only. is_active may persist a filesystem-triggered
        # stop, so this evidence provider must never invoke it.
        status = copy.deepcopy(binding.kill_switch.get_status())
        _require(isinstance(status, Mapping) and status.get("is_active") is False
                 and status.get("kill_file_exists") is False, "local_kill_switch_not_clear")
        _require(os.environ.get("NIJA_KILL_SWITCH", "").strip().lower()
                 not in {"1", "true", "yes", "on"}, "deployment_kill_switch_active")
        return status

    def observe() -> Mapping[str, Any]:
        try:
            _require(review_binding(binding) is True, "binding_review_revoked")
            started, monotonic = clock(), time.monotonic()
            _require(_finite(started), "observation_clock_invalid")
            with binding.redis_client.pipeline() as pipe:
                pipe.watch(binding.durable_key)
                raw = pipe.get(binding.durable_key)
                digest = _clearance(raw, started)
                _require(hmac.compare_digest(digest, binding.clearance_sha256),
                         "clearance_not_independently_approved")
                first = local_status()
                _require(review_binding(binding) is True, "binding_review_revoked")
                _require(local_status() == first, "local_kill_switch_changed")
                pipe.multi()
                pipe.get(binding.durable_key)
                pipe.pttl(binding.durable_key)
                rows = pipe.execute()
                _require(isinstance(rows, (list, tuple)) and len(rows) == 2
                         and rows[0] == raw and type(rows[1]) is int and rows[1] == -1,
                         "durable_clearance_changed_or_expiring")
            _require(local_status() == first, "local_kill_switch_changed")
            _require(review_binding(binding) is True, "binding_review_revoked")
            finished = clock()
            _require(_finite(finished) and 0 <= finished - started < 60
                     and 0 <= time.monotonic() - monotonic < 60, "observation_stale")
            return {
                "account": binding.account, "source": "risk_governor",
                "provider_id": binding.provider_id, "evidence_id": uuid.uuid4().hex,
                "verified": True, "read_only": True, "scope_verified": True,
                "observed_at_epoch": started, "expires_at_epoch": started + 60,
                "authorizes_orders": False,
                "provenance": {
                    "account_scope_verified": True, "collector_identity_verified": True,
                    "snapshot_complete": True, "risk_state_verified": True,
                },
            }
        except KrakenKillSwitchDenied:
            raise
        except Exception:
            # Includes WatchError, missing Redis permissions, transport errors,
            # malformed responses and reviewer failure. Never retry a changed stop.
            raise KrakenKillSwitchDenied("kill_switch_read_unverified") from None

    return observe
