"""Make stalled-writer liveness consume canonical capital publication freshness.

The legacy v22 stalled-writer guard predates the immutable publication contract.
Its local capital probe can turn a stale snapshot back into fresh when a historic
handoff/first-snapshot latch is present. Production then reports canonical
``capital_ready=False`` while v22 reports ``capital_ready=True`` and keeps the
writer lease indefinitely past its release timeout.

v141 makes immutable CapitalAuthority publication status authoritative for this
liveness guard only. It never changes capital values, extends publication expiry,
marks readiness, clears a kill switch, grants writer/nonce authority, or alters
risk/execution gates.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
from datetime import datetime, timezone
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.stalled_writer_capital_freshness_v141")
MARKER = "20260818-stalled-writer-capital-freshness-v141"
_FLAG = "NIJA_STALLED_WRITER_CAPITAL_FRESHNESS_V141_INSTALLED"
_PATCH_ATTR = "_nija_stalled_writer_capital_freshness_v141"
_LOCK = threading.RLock()
_INSTALLED = False


def _utc(value: Any) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _authority() -> Any:
    for name in ("bot.capital_authority", "capital_authority"):
        try:
            module = importlib.import_module(name)
        except ImportError:
            continue
        getter = getattr(module, "get_capital_authority", None)
        if callable(getter):
            authority = getter()
            if authority is not None:
                return authority
    raise RuntimeError("capital_authority_unavailable")


def _publication_current(authority: Any, *, now: datetime | None = None) -> tuple[bool, str]:
    getter = getattr(authority, "get_snapshot_publication_status", None)
    if not callable(getter):
        return False, "publication_status_unavailable"
    try:
        status = getter()
    except Exception as exc:
        return False, f"publication_status_error:{type(exc).__name__}:{exc}"
    if status is None:
        return False, "publication_status_missing"

    accepted = bool(getattr(status, "accepted", False))
    stale = bool(getattr(status, "stale", True))
    reason = str(getattr(status, "reason", "unknown") or "unknown")
    expiry = _utc(getattr(status, "expiry", None))
    current_time = _utc(now) or datetime.now(timezone.utc)

    if not accepted:
        return False, f"not_accepted:{reason}"
    if stale:
        return False, f"stale:{reason}"
    if expiry is None:
        return False, "publication_expiry_missing"
    if expiry <= current_time:
        return False, "expired_after_publish"
    return True, "current"


def _patch_stalled_writer_guard() -> bool:
    guard = importlib.import_module("bot.stalled_writer_release_guard_v22")

    current_snapshot = getattr(guard, "_capital_snapshot", None)
    if not callable(current_snapshot):
        return False
    if not getattr(current_snapshot, _PATCH_ATTR, False):
        original_snapshot = current_snapshot

        @wraps(original_snapshot)
        def capital_snapshot_v141() -> tuple[bool, float, bool, int]:
            hydrated, capital, legacy_stale, valid_brokers = original_snapshot()
            try:
                current, reason = _publication_current(_authority())
            except Exception as exc:
                current = False
                reason = f"publication_probe_failed:{type(exc).__name__}:{exc}"

            stale = not current
            if stale and bool(hydrated) and float(capital or 0.0) > 0.0 and int(valid_brokers or 0) > 0:
                LOGGER.warning(
                    "STALLED_WRITER_CAPITAL_V141_FAIL_CLOSED marker=%s reason=%s "
                    "legacy_stale=%s hydrated=%s capital=%.8f valid_brokers=%d "
                    "historical_latch_not_freshness=true",
                    MARKER,
                    reason,
                    bool(legacy_stale),
                    bool(hydrated),
                    float(capital or 0.0),
                    int(valid_brokers or 0),
                )
            return bool(hydrated), float(capital or 0.0), bool(stale), int(valid_brokers or 0)

        setattr(capital_snapshot_v141, _PATCH_ATTR, True)
        setattr(capital_snapshot_v141, "_nija_v141_original", original_snapshot)
        guard._capital_snapshot = capital_snapshot_v141

    current_ingest = getattr(guard, "_ingest_authority_snapshot_into_csm", None)
    if callable(current_ingest) and not getattr(current_ingest, _PATCH_ATTR, False):
        original_ingest = current_ingest

        @wraps(original_ingest)
        def ingest_current_publication_only(source: str) -> bool:
            try:
                current, reason = _publication_current(_authority())
            except Exception as exc:
                current = False
                reason = f"publication_probe_failed:{type(exc).__name__}:{exc}"
            if not current:
                LOGGER.warning(
                    "STALLED_WRITER_CAPITAL_V141_CSM_REPLAY_BLOCKED marker=%s source=%s "
                    "reason=%s immutable_publication_authoritative=true",
                    MARKER,
                    source,
                    reason,
                )
                return False
            return bool(original_ingest(source))

        setattr(ingest_current_publication_only, _PATCH_ATTR, True)
        setattr(ingest_current_publication_only, "_nija_v141_original", original_ingest)
        guard._ingest_authority_snapshot_into_csm = ingest_current_publication_only

    return bool(getattr(guard._capital_snapshot, _PATCH_ATTR, False))


def install_import_hook() -> bool:
    global _INSTALLED
    with _LOCK:
        ok = _patch_stalled_writer_guard()
        if not ok:
            os.environ.pop(_FLAG, None)
            raise RuntimeError("stalled_writer_guard_not_patchable")
        os.environ[_FLAG] = "1"
        first = not _INSTALLED
        _INSTALLED = True

    if first:
        LOGGER.critical(
            "STALLED_WRITER_CAPITAL_FRESHNESS_V141_INSTALLED marker=%s "
            "immutable_publication_authoritative=true historical_latch_freshness=false "
            "publication_expiry_extended=false writer_authority_unchanged=true "
            "kill_switch_unchanged=true nonce_unchanged=true risk_gates_unchanged=true "
            "execution_authority_unchanged=true",
            MARKER,
        )
    return True


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_authority",
    "_publication_current",
    "_patch_stalled_writer_guard",
]
