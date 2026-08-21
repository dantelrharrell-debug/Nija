"""Canonical capital publication identity recovery v178.

Production evidence on 2026-08-21 showed an exact duplicate refresh could be
correctly rejected by CapitalAuthority as ``snapshot_not_newer`` while the
rejection itself replaced the publication-status object with
``accepted=False, stale=True``. The underlying canonical snapshot remained
hydrated, complete across all expected brokers, positive, and younger than its
original immutable expiry, but readiness consumers then treated it as stale.

v178 repairs only that status-poisoning case. It recognizes the candidate only
when its ``computed_at`` exactly matches BOTH the canonical typed snapshot and
``CapitalAuthority.last_updated``; the broker aggregation must still be
complete, capital must remain positive, and the existing publication expiry
must still be in the future. The original expiry is preserved exactly. Older
candidates, incomplete aggregation, zero capital, expired snapshots, and all
other rejection reasons remain rejected and fail closed.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
from contextlib import nullcontext
from datetime import datetime, timezone
from functools import wraps
from types import ModuleType
from typing import Any

LOGGER = logging.getLogger("nija.runtime_capital_publication_identity_v178")
MARKER = "20260821-runtime-capital-publication-identity-v178"
RELEASE_ID = "20260821-runtime-convergence-v178"
_READY_FLAG = "NIJA_RUNTIME_CAPITAL_PUBLICATION_IDENTITY_V178_READY"
_PATCH_ATTR = "_nija_runtime_capital_publication_identity_v178"
_LOCK = threading.RLock()


def _utc(value: Any) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _broker_entries(snapshot: Any) -> int:
    balances = getattr(snapshot, "broker_balances", None)
    if isinstance(balances, dict):
        return len([key for key in balances if str(getattr(key, "value", key) or "").strip()])
    try:
        return max(0, int(getattr(snapshot, "broker_count", 0) or 0))
    except (TypeError, ValueError):
        return 0


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


def _real_capital(authority: Any, snapshot: Any) -> float:
    values: list[float] = []
    for obj, attr in (
        (snapshot, "real_capital"),
        (snapshot, "total_capital"),
        (authority, "real_capital"),
        (authority, "total_capital"),
    ):
        try:
            values.append(float(getattr(obj, attr, 0.0) or 0.0))
        except Exception:
            pass
    for name in ("get_real_capital", "get_total_capital"):
        method = getattr(authority, name, None)
        if callable(method):
            try:
                values.append(float(method() or 0.0))
            except Exception:
                pass
    return max(values or [0.0])


def _repair_same_publication_status(
    authority: Any,
    module: ModuleType,
    snapshot: Any,
    *,
    source: str,
    now: datetime | None = None,
) -> tuple[bool, str]:
    """Restore status only for the exact still-current canonical publication."""
    lock = getattr(authority, "_lock", None)
    context = lock if hasattr(lock, "__enter__") else nullcontext()
    current_time = _utc(now) or datetime.now(timezone.utc)

    with context:
        status = getattr(authority, "_last_snapshot_publication", None)
        if status is None:
            return False, "publication_status_missing"
        reason = str(getattr(status, "reason", "") or "")
        if reason != "snapshot_not_newer":
            return False, f"reason_not_repairable:{reason or 'unknown'}"
        if bool(getattr(status, "accepted", False)) or not bool(getattr(status, "stale", True)):
            return False, "status_already_current"

        candidate_ts = _utc(getattr(snapshot, "computed_at", None))
        last_updated = _utc(getattr(authority, "last_updated", None))
        expiry = _utc(getattr(status, "expiry", None))
        status_ts = _utc(getattr(status, "timestamp", None))
        if candidate_ts is None or last_updated is None or expiry is None:
            return False, "timestamp_or_expiry_missing"
        if expiry <= current_time:
            return False, "publication_expired"
        if candidate_ts != last_updated:
            return False, "candidate_not_current_last_updated"
        if status_ts is not None and status_ts != candidate_ts:
            return False, "status_identity_mismatch"

        getter = getattr(authority, "get_typed_snapshot", None)
        if not callable(getter):
            return False, "canonical_snapshot_getter_missing"
        try:
            canonical = getter()
        except Exception as exc:
            return False, f"canonical_snapshot_error:{type(exc).__name__}:{exc}"
        if canonical is None:
            return False, "canonical_snapshot_missing"
        canonical_ts = _utc(getattr(canonical, "computed_at", None))
        if canonical_ts != candidate_ts:
            return False, "canonical_identity_mismatch"

        contributed = _broker_entries(canonical)
        required = max(1, _expected_brokers(authority, canonical))
        opportunistic = bool(getattr(authority, "_opportunistic", False))
        threshold = 1 if opportunistic else required
        if contributed < threshold:
            return False, f"incomplete_broker_aggregation:{contributed}/{threshold}"
        real = _real_capital(authority, canonical)
        if real <= 0.0:
            return False, "capital_not_positive"

        status_cls = getattr(module, "SnapshotPublicationStatus", None)
        if status_cls is None:
            return False, "status_class_missing"
        authority._last_snapshot_publication = status_cls(
            accepted=True,
            stale=False,
            reason="accepted_existing_canonical_publication",
            timestamp=candidate_ts,
            expiry=getattr(status, "expiry", None),
        )

    LOGGER.critical(
        "CAPITAL_V178_SAME_PUBLICATION_RESTORED marker=%s source=%s "
        "computed_at=%s expiry=%s contributed=%d required=%d real=%.8f "
        "candidate_republished=false publication_expiry_extended=false "
        "freshness_ttl_unchanged=true trading_fail_closed_on_mismatch=true",
        MARKER,
        source,
        candidate_ts.isoformat(),
        expiry.isoformat(),
        contributed,
        threshold,
        real,
    )
    return True, "restored_exact_current_publication"


def _repair_existing_authority(module: ModuleType) -> tuple[bool, str]:
    getter = getattr(module, "get_capital_authority", None)
    if not callable(getter):
        return False, "authority_getter_missing"
    try:
        authority = getter()
    except Exception as exc:
        return False, f"authority_getter_error:{type(exc).__name__}:{exc}"
    if authority is None:
        return False, "authority_missing"
    typed = getattr(authority, "get_typed_snapshot", None)
    if not callable(typed):
        return False, "canonical_snapshot_getter_missing"
    try:
        snapshot = typed()
    except Exception as exc:
        return False, f"canonical_snapshot_error:{type(exc).__name__}:{exc}"
    if snapshot is None:
        return False, "canonical_snapshot_missing"
    return _repair_same_publication_status(
        authority,
        module,
        snapshot,
        source="install_probe",
    )


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
    original = current

    @wraps(original)
    def publish_v178(self: Any, snapshot: Any, writer_id: str) -> bool:
        result = bool(original(self, snapshot, writer_id))
        if not result:
            repaired, _ = _repair_same_publication_status(
                self,
                module,
                snapshot,
                source="publish_snapshot",
            )
            if repaired:
                return False
        return result

    setattr(publish_v178, _PATCH_ATTR, True)
    setattr(publish_v178, "__wrapped__", original)
    cls.publish_snapshot = publish_v178
    return True


def _patch_release_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_capital_publication_identity_v178"] = _READY_FLAG
        return True
    except Exception:
        return False


def install() -> bool:
    with _LOCK:
        try:
            module = importlib.import_module("bot.capital_authority")
        except Exception as exc:
            os.environ[_READY_FLAG] = "0"
            LOGGER.critical(
                "RUNTIME_CAPITAL_PUBLICATION_IDENTITY_V178_FAILED marker=%s "
                "reason=capital_authority_import error=%s:%s trading_fail_closed=true",
                MARKER,
                type(exc).__name__,
                exc,
            )
            return False

        authority_ok = _patch_capital_authority(module)
        manifest_ok = _patch_release_manifest()
        ready = bool(authority_ok and manifest_ok)
        os.environ[_READY_FLAG] = "1" if ready else "0"
        repaired = False
        repair_reason = "not_attempted"
        if ready:
            repaired, repair_reason = _repair_existing_authority(module)
        if not ready:
            LOGGER.critical(
                "RUNTIME_CAPITAL_PUBLICATION_IDENTITY_V178_FAILED marker=%s authority=%s "
                "manifest=%s trading_fail_closed=true",
                MARKER,
                str(authority_ok).lower(),
                str(manifest_ok).lower(),
            )
            return False
        LOGGER.critical(
            "RUNTIME_CAPITAL_PUBLICATION_IDENTITY_V178 marker=%s ready=true "
            "exact_canonical_identity_required=true complete_broker_aggregation_required=true "
            "positive_capital_required=true immutable_expiry_preserved=true "
            "install_probe_repaired=%s install_probe_reason=%s "
            "candidate_republished=false freshness_ttl_unchanged=true "
            "safety_gates_bypassed=false",
            MARKER,
            str(repaired).lower(),
            repair_reason,
        )
        return True


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "RELEASE_ID",
    "install",
    "install_import_hook",
    "_repair_same_publication_status",
    "_repair_existing_authority",
    "_patch_capital_authority",
]
