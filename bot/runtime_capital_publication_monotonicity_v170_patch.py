"""Capital publication/CSM monotonicity repair v170.

Production on 2026-08-20 exposed two remaining split-brain paths:

* CapitalAuthority could label a fresh positive 2/3 snapshot accepted because
  its local publication gate required only one valid broker entry;
* CapitalCSMv2 could ingest the coordinator's pre-augmentation 2/3 object after
  v43/v169 had already published a canonical 3/3 CapitalAuthority snapshot,
  then v34 could publish readiness from that stale object identity.

v170 makes the accepted publication monotonic and makes downstream readiness
consume the exact canonical CapitalAuthority publication.  Production on
2026-08-23 exposed one remaining mutation-order gap: when no publication was
currently valid, base CapitalAuthority could apply a fresh 2/3 candidate before
v170 relabelled the attempt rejected/stale.  The rejected candidate then remained
in the canonical in-memory snapshot and could look fresh to readers that inspect
CapitalAuthority state separately from publication status.

The v199 hardening in this module rejects every incomplete live candidate before
calling the base publish path.  An existing complete canonical snapshot remains
unchanged (and remains stale when its immutable expiry has elapsed) until a new
complete snapshot is available.  No partial candidate may refresh last_updated,
replace broker balances, or replace the typed canonical snapshot.

This patch never extends freshness, promotes stale capital, fabricates a broker
balance, changes the v168 thread ceiling, clears a kill switch, grants
nonce/writer authority, or forces activation.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
from datetime import datetime, timezone
from functools import wraps
from types import ModuleType
from typing import Any

LOGGER = logging.getLogger("nija.runtime_capital_publication_monotonicity_v170")
MARKER = "20260820-runtime-capital-publication-monotonicity-v170"
V199_MARKER = "20260823-capital-partial-premutation-v199"
_READY_FLAG = "NIJA_RUNTIME_CAPITAL_PUBLICATION_MONOTONICITY_V170_READY"
_PATCH_ATTR = "_nija_runtime_capital_publication_monotonicity_v170"
_CSM_ATTR = "_nija_runtime_capital_csm_canonical_v170"
_LOCK = threading.RLock()

_REJECTION_REASONS_THAT_MUST_NOT_POISON_CURRENT = {
    "snapshot_not_newer",
    "snapshot expired before publish",
    "snapshot expired while waiting to publish",
}


def _utc(value: Any) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _expected_brokers(authority: Any, snapshot: Any = None) -> int:
    for value in (
        getattr(snapshot, "expected_brokers", None) if snapshot is not None else None,
        getattr(authority, "expected_brokers", None),
        getattr(authority, "_expected_brokers", None),
    ):
        try:
            parsed = int(value or 0)
        except (TypeError, ValueError):
            parsed = 0
        if parsed > 0:
            return parsed
    return 1


def _broker_entries(snapshot: Any) -> int:
    balances = getattr(snapshot, "broker_balances", None)
    if isinstance(balances, dict):
        return len(
            [
                key
                for key in balances
                if str(getattr(key, "value", key) or "").strip()
            ]
        )
    try:
        return max(0, int(getattr(snapshot, "broker_count", 0) or 0))
    except (TypeError, ValueError):
        return 0


def _snapshot_complete(authority: Any, snapshot: Any) -> tuple[bool, int, int]:
    contributed = _broker_entries(snapshot)
    expected = max(1, _expected_brokers(authority, snapshot))
    # Opportunistic capital is already rejected in live mode by CapitalAuthority.
    # Retain the existing paper/dry-run exception without weakening live mode.
    opportunistic = bool(getattr(authority, "_opportunistic", False))
    threshold = 1 if opportunistic else expected
    return contributed >= threshold, contributed, threshold


def _raw_status(authority: Any) -> Any:
    lock = getattr(authority, "_lock", None)
    if lock is None:
        return getattr(authority, "_last_snapshot_publication", None)
    with lock:
        return getattr(authority, "_last_snapshot_publication", None)


def _status_current(status: Any, now: datetime | None = None) -> bool:
    if status is None:
        return False
    if not bool(getattr(status, "accepted", False)) or bool(getattr(status, "stale", True)):
        return False
    expiry = _utc(getattr(status, "expiry", None))
    if expiry is None:
        return False
    current = _utc(now) or datetime.now(timezone.utc)
    return current < expiry


def _current_status(authority: Any) -> Any:
    getter = getattr(authority, "get_snapshot_publication_status", None)
    if callable(getter):
        try:
            return getter()
        except Exception:
            pass
    return _raw_status(authority)


def _same_publication(snapshot: Any, status: Any) -> bool:
    snap_ts = _utc(getattr(snapshot, "computed_at", None))
    status_ts = _utc(getattr(status, "timestamp", None))
    return snap_ts is not None and status_ts is not None and snap_ts == status_ts


def _set_status(
    authority: Any,
    module: ModuleType,
    *,
    accepted: bool,
    stale: bool,
    reason: str,
    timestamp: Any,
    expiry: Any,
) -> bool:
    status_cls = getattr(module, "SnapshotPublicationStatus", None)
    if status_cls is None:
        return False
    try:
        replacement = status_cls(
            accepted=bool(accepted),
            stale=bool(stale),
            reason=str(reason or ""),
            timestamp=timestamp,
            expiry=expiry,
        )
    except Exception:
        return False
    lock = getattr(authority, "_lock", None)
    if lock is None:
        authority._last_snapshot_publication = replacement
    else:
        with lock:
            authority._last_snapshot_publication = replacement
    return True


def _restore_status(authority: Any, status: Any) -> None:
    if status is None:
        return
    lock = getattr(authority, "_lock", None)
    if lock is None:
        authority._last_snapshot_publication = status
    else:
        with lock:
            authority._last_snapshot_publication = status


def _patch_capital_authority(module: ModuleType | None = None) -> bool:
    if module is None:
        try:
            module = importlib.import_module("bot.capital_authority")
        except Exception:
            return False
    cls = getattr(module, "CapitalAuthority", None)
    if not isinstance(cls, type):
        return False
    current = getattr(cls, "publish_snapshot", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    @wraps(current)
    def publish_v170(self: Any, snapshot: Any, writer_id: str) -> bool:
        previous_raw = _raw_status(self)
        previous_current = _status_current(_current_status(self))
        complete, contributed, required = _snapshot_complete(self, snapshot)

        # v199: reject every incomplete candidate BEFORE the base authority can
        # mutate _broker_balances, last_updated, or _last_typed_snapshot.  When
        # a complete current publication exists, preserve its exact status and
        # immutable expiry.  When no current publication exists, record a stale
        # rejection status only; canonical capital state remains untouched.
        if not complete:
            if previous_current:
                LOGGER.warning(
                    "CAPITAL_V170_PARTIAL_PRESERVED marker=%s v199_marker=%s "
                    "contributed=%d required=%d prior_expiry=%s candidate_mutated=false "
                    "canonical_snapshot_preserved=true broker_balances_preserved=true "
                    "last_updated_preserved=true freshness_extended=false "
                    "publication_expiry_extended=false",
                    MARKER,
                    V199_MARKER,
                    contributed,
                    required,
                    getattr(previous_raw, "expiry", None),
                )
                return False

            _set_status(
                self,
                module,
                accepted=False,
                stale=True,
                reason=f"incomplete_broker_aggregation:{contributed}/{required}",
                timestamp=getattr(snapshot, "computed_at", None),
                expiry=getattr(previous_raw, "expiry", None),
            )
            LOGGER.critical(
                "CAPITAL_V199_PARTIAL_PREMUTATION_REJECTED marker=%s v170_marker=%s "
                "contributed=%d required=%d prior_publication_current=false "
                "candidate_mutated=false canonical_snapshot_preserved=true "
                "broker_balances_preserved=true last_updated_preserved=true "
                "accepted=false stale=true freshness_extended=false "
                "publication_expiry_extended=false trading_fail_closed=true",
                V199_MARKER,
                MARKER,
                contributed,
                required,
            )
            return False

        result = bool(current(self, snapshot, writer_id))
        after = _raw_status(self)
        after_reason = str(getattr(after, "reason", "") or "")

        # Older/expired rejected attempts describe the rejected candidate, not
        # the newer current publication.  Restore the exact prior status object,
        # including its original expiry, so the status is monotonic.
        if (
            not result
            and previous_current
            and after_reason in _REJECTION_REASONS_THAT_MUST_NOT_POISON_CURRENT
        ):
            _restore_status(self, previous_raw)
            LOGGER.warning(
                "CAPITAL_V170_REJECTION_STATUS_PRESERVED marker=%s reason=%s prior_expiry=%s "
                "freshness_extended=false stale_promoted=false",
                MARKER,
                after_reason,
                getattr(previous_raw, "expiry", None),
            )
        return result

    setattr(publish_v170, _PATCH_ATTR, True)
    setattr(publish_v170, "__wrapped__", current)
    cls.publish_snapshot = publish_v170
    return True


def _canonical_snapshot_for_csm(incoming: Any) -> tuple[Any, str]:
    try:
        ca = importlib.import_module("bot.capital_authority").get_capital_authority()
        status = _current_status(ca)
        canonical = ca.get_typed_snapshot()
    except Exception as exc:
        return incoming, f"authority_unavailable:{type(exc).__name__}"
    if not _status_current(status):
        return incoming, "authority_publication_not_current"
    if canonical is None or not _same_publication(canonical, status):
        return incoming, "authority_snapshot_identity_mismatch"
    complete, contributed, required = _snapshot_complete(ca, canonical)
    if not complete:
        return incoming, f"authority_snapshot_incomplete:{contributed}/{required}"
    return canonical, "canonical_authority_publication"


def _patch_csm_v2() -> bool:
    try:
        module = importlib.import_module("bot.capital_csm_v2")
    except Exception:
        return False
    cls = getattr(module, "CapitalCSMv2", None)
    if not isinstance(cls, type):
        return False
    current = getattr(cls, "ingest_snapshot", None)
    if not callable(current):
        return False
    if bool(getattr(current, _CSM_ATTR, False)):
        return True

    @wraps(current)
    def ingest_v170(self: Any, snapshot: Any) -> Any:
        canonical, reason = _canonical_snapshot_for_csm(snapshot)
        if canonical is not snapshot:
            LOGGER.info(
                "CAPITAL_CSM_V170_CANONICALIZED marker=%s incoming_brokers=%d canonical_brokers=%d "
                "incoming_real=%.8f canonical_real=%.8f reason=%s",
                MARKER,
                _broker_entries(snapshot),
                _broker_entries(canonical),
                float(getattr(snapshot, "real_capital", 0.0) or 0.0),
                float(getattr(canonical, "real_capital", 0.0) or 0.0),
                reason,
            )
        return current(self, canonical)

    setattr(ingest_v170, _CSM_ATTR, True)
    setattr(ingest_v170, "__wrapped__", current)
    cls.ingest_snapshot = ingest_v170
    return True


def _patch_v34_handoff() -> bool:
    """Defense in depth: a raw partial object can never publish v34 readiness."""
    try:
        module = importlib.import_module("bot.capital_readiness_handoff_v34")
        current = getattr(module, "_snapshot_valid", None)
    except Exception:
        return False
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    @wraps(current)
    def snapshot_valid_v170(snapshot: Any) -> bool:
        if not bool(current(snapshot)):
            return False
        try:
            ca = importlib.import_module("bot.capital_authority").get_capital_authority()
            status = _current_status(ca)
            complete, contributed, required = _snapshot_complete(ca, snapshot)
            if not complete or not _status_current(status) or not _same_publication(snapshot, status):
                LOGGER.warning(
                    "CAPITAL_V34_V170_HANDOFF_BLOCKED marker=%s contributed=%d required=%d "
                    "publication_current=%s same_publication=%s trading_fail_closed=true",
                    MARKER,
                    contributed,
                    required,
                    str(_status_current(status)).lower(),
                    str(_same_publication(snapshot, status)).lower(),
                )
                return False
            return True
        except Exception:
            return False

    setattr(snapshot_valid_v170, _PATCH_ATTR, True)
    setattr(snapshot_valid_v170, "__wrapped__", current)
    module._snapshot_valid = snapshot_valid_v170
    return True


def _patch_release_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_capital_publication_monotonicity_v170"] = _READY_FLAG
        return True
    except Exception:
        return False


def install() -> bool:
    with _LOCK:
        authority_ok = _patch_capital_authority()
        csm_ok = _patch_csm_v2()
        handoff_ok = _patch_v34_handoff()
        manifest_ok = _patch_release_manifest()
        ready = bool(authority_ok and csm_ok and handoff_ok and manifest_ok)
        os.environ[_READY_FLAG] = "1" if ready else "0"
        if not ready:
            LOGGER.critical(
                "RUNTIME_CAPITAL_PUBLICATION_MONOTONICITY_V170_FAILED marker=%s authority=%s "
                "csm=%s handoff=%s manifest=%s trading_fail_closed=true",
                MARKER,
                str(authority_ok).lower(),
                str(csm_ok).lower(),
                str(handoff_ok).lower(),
                str(manifest_ok).lower(),
            )
            return False
        LOGGER.critical(
            "RUNTIME_CAPITAL_PUBLICATION_MONOTONICITY_V170 marker=%s ready=true "
            "complete_broker_entries_required=true zero_balance_entry_counts=true "
            "rejected_attempt_status_monotonic=true csm_uses_canonical_publication=true "
            "v34_partial_handoff_blocked=true partial_premutation_reject_v199=true "
            "freshness_extended=false publication_expiry_extended=false "
            "stale_promoted=false safety_gates_bypassed=false",
            MARKER,
        )
        return True


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "V199_MARKER",
    "install",
    "install_import_hook",
    "_snapshot_complete",
    "_status_current",
    "_same_publication",
    "_canonical_snapshot_for_csm",
]
