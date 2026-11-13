"""Atomic account risk publication, with uncached authentication by its owner.

This is a publication mechanism, not a capital/exposure/policy data source.
The reviewed canonical owner must supply the complete original snapshot and
authenticate its current revision on EVERY publish and read. Authentication
must cover all account state changes, including pending submissions, halts and
changes subsequently reverted. A truthy configuration flag is not an owner.

No import/startup hooks, broker calls, global risk inference, approval issuance,
disk writes, collector registration or order authority are supplied here.
Restart begins empty. Old observations are never stamped with publication time.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
import copy
import json
import threading
import time
from typing import Any

from bot.kraken_risk_evidence import make_kraken_risk_limits_provider

MAX_SNAPSHOT_BYTES = 1024 * 1024


class RiskPublicationDenied(ValueError):
    """Fixed, non-sensitive refusal without snapshot or callback contents."""


class _Candidate:
    def __init__(self, value: dict[str, Any]) -> None:
        self.value = value

    def read_snapshot(self, account: str, api_key_sha256: str) -> dict[str, Any]:
        """Supply detached candidate data to the existing validation reader."""
        return copy.deepcopy(self.value)


def _detach(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    # JSON-only copies prevent arbitrary user objects/deepcopy hooks in state.
    # No serialization is written or logged; allow_nan=False rejects NaN/Inf.
    if type(snapshot) is not dict:
        raise RiskPublicationDenied("plain_snapshot_required")
    raw = json.dumps(snapshot, allow_nan=False, sort_keys=True, separators=(",", ":"))
    if len(raw.encode("utf-8")) > MAX_SNAPSHOT_BYTES:
        raise RiskPublicationDenied("snapshot_size_exceeded")
    value = json.loads(raw)
    if value != snapshot:
        raise RiskPublicationDenied("snapshot_types_invalid")
    return value


class ReviewedAccountRiskPublisher:
    """Publish full account snapshots atomically; reject revoked/changed owners.

    ``authenticate_current`` is reviewed trusted code, not a sandbox. It must
    check the exact data and revision against the CURRENT authoritative account
    owners and return literal True. It cannot infer authentication from fields
    supplied by the caller. Its implementation and mutation coverage must be
    audited in the protected composition root before this object is used there.

    ``minimum_revision`` is an independently supplied restart floor, not learned
    from an unverified artifact. In-process high water never decreases. A failed
    publication/read invalidates the previous value; no stale fallback survives.
    Every successful read is detached and preserves the original timestamps.
    """

    def __init__(
        self, *, account_scope: str, approved_api_key_sha256: str,
        reviewed_provider_id: str, reviewed_snapshot_source_id: str,
        reviewed_record_source_ids: Mapping[str, str],
        authenticate_current: Callable[[Mapping[str, Any]], bool],
        minimum_revision: int, independently_reviewed: bool = False,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if (independently_reviewed is not True or not callable(authenticate_current)
                or type(minimum_revision) is not int
                or minimum_revision < 0):
            raise RiskPublicationDenied("reviewed_publication_owner_required")
        self._options = {
            "account_scope": account_scope, "approved_api_key_sha256": approved_api_key_sha256,
            "reviewed_provider_id": reviewed_provider_id,
            "reviewed_snapshot_source_id": reviewed_snapshot_source_id,
            "reviewed_record_source_ids": dict(reviewed_record_source_ids),
            "independently_reviewed": independently_reviewed, "clock": clock,
        }
        # Existing provider construction validates pins; it performs no reads.
        make_kraken_risk_limits_provider(_Candidate({}), **self._options)
        self._authenticate_current = authenticate_current
        self._lock = threading.RLock()
        self._snapshot: dict[str, Any] | None = None
        self._high_water = minimum_revision
        self._record_water: dict[str, tuple[int, dict[str, Any]]] = {}
        self._generation = 0

    def _clear(self) -> None:
        self._generation += 1
        self._snapshot = None

    def _authenticate(self, value: dict[str, Any], generation: int) -> None:
        candidate = copy.deepcopy(value)
        if (self._authenticate_current(candidate) is not True or candidate != value
                or self._generation != generation):
            raise RiskPublicationDenied("current_publication_owner_unverified")

    def _validate(self, value: dict[str, Any]) -> None:
        # Reuse the actual risk reader, including all provenance, protection,
        # exposure, loss, freshness and policy checks. No weaker validator.
        make_kraken_risk_limits_provider(_Candidate(value), **self._options)()

    def _advance_records(self, value: dict[str, Any]) -> None:
        candidates = {}
        for kind in ("capital", "exposure", "policy"):
            row = value.get(kind)
            revision = row.get("revision") if type(row) is dict else None
            if type(revision) is not int or revision <= 0:
                raise RiskPublicationDenied("record_revision_invalid")
            previous = self._record_water.get(kind)
            if previous is not None and (revision < previous[0]
                                         or (revision == previous[0] and row != previous[1])):
                raise RiskPublicationDenied("record_revision_rollback_or_reuse")
            candidates[kind] = (revision, copy.deepcopy(row))
        self._record_water = candidates

    def publish(self, snapshot: Mapping[str, Any]) -> None:
        """Replace one entire authenticated snapshot, never merge partial rows.

        The envelope revision must increase; changed records must advance their
        own revisions, including rejected/blocked account states. A verified new
        revision is consumed before risk validation, so a halt cannot be followed
        by replaying an earlier healthy revision. Failed input leaves no value.
        """
        with self._lock:
            self._clear()
            generation = self._generation
            try:
                value = _detach(snapshot)
                if (value.get("account") != self._options["account_scope"]
                        or value.get("api_key_sha256") != self._options["approved_api_key_sha256"]):
                    raise RiskPublicationDenied("publication_scope_mismatch")
                revision = value.get("revision")
                if type(revision) is not int or revision <= self._high_water:
                    raise RiskPublicationDenied("publication_revision_not_increasing")
                self._authenticate(value, generation)
                self._high_water = revision
                self._advance_records(value)
                self._validate(value)
                self._authenticate(value, generation)
                self._snapshot = value
            except Exception:
                self._clear()
                raise RiskPublicationDenied("risk_publication_rejected") from None

    def invalidate(self) -> None:
        """Immediately withdraw publication on source change/disconnect/halt.

        Source owners must invoke this synchronously on changes, and the current
        owner authenticator must ALSO detect them if publication hooks fail.
        This changes diagnostic evidence only; it clears no trading safety gate.
        """
        with self._lock:
            self._clear()

    def read_snapshot(self, account: str, api_key_sha256: str) -> dict[str, Any]:
        """Return one detached authenticated snapshot without refreshing it."""
        with self._lock:
            try:
                if (account != self._options["account_scope"]
                        or api_key_sha256 != self._options["approved_api_key_sha256"]
                        or self._snapshot is None):
                    raise RiskPublicationDenied("current_publication_unavailable")
                generation = self._generation
                value = copy.deepcopy(self._snapshot)
                self._authenticate(value, generation)
                self._validate(value)
                self._authenticate(value, generation)
                return copy.deepcopy(value)
            except Exception:
                self._clear()
                raise RiskPublicationDenied("risk_publication_read_rejected") from None
