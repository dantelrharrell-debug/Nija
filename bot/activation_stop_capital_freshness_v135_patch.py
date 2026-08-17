"""Protected-stop authority and capital freshness convergence v135.

Production v134 proved that current capital/readiness proof convergence is
working, but two remaining contradictions can still make runtime truth oscillate:

* ``trading_state_machine._is_authority_ready`` may bootstrap
  ``authority_ready=True`` from writer proof alone while the kill switch is
  active.  v16/v133 correctly revoke that same proof because protected stops are
  part of authority readiness.
* ``CapitalAuthority.get_snapshot_publication_status`` returns the publication
  object captured at publish time.  Once its expiry passes, callers can observe
  ``is_fresh=False`` together with ``publication.stale=False``.

This patch makes those readers agree without clearing a kill switch, extending
capital freshness, granting nonce/execution authority, or forcing LIVE_ACTIVE.
It also makes the existing v78 freshness-bounded refresh patch a hard runtime
release dependency so slow venue reads cannot monopolize a refresh past the
canonical capital TTL.
"""
from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
import time
from datetime import datetime, timezone
from functools import wraps
from types import ModuleType
from typing import Any, Optional

LOGGER = logging.getLogger("nija.activation_stop_capital_freshness_v135")
MARKER = "20260817-activation-stop-capital-freshness-v135"
RELEASE_ID = "20260817-runtime-convergence-v135"
_FLAG = "NIJA_ACTIVATION_STOP_CAPITAL_FRESHNESS_V135_INSTALLED"
_LOCK = threading.RLock()
_MONITOR_STARTED = False
_LAST_BLOCK_SIGNATURE = ""


def _kill_switch_state(tsm: ModuleType) -> tuple[Optional[bool], str]:
    """Return the current kill-switch state, failing closed on probe errors."""
    probe = getattr(tsm, "_kill_switch_is_active", None)
    if callable(probe):
        try:
            active, detail = probe()
            if active is None:
                return None, str(detail or "kill_switch_state_unknown")
            return bool(active), str(detail or "")
        except Exception as exc:
            return None, f"kill_switch_probe_failed:{type(exc).__name__}:{exc}"
    try:
        try:
            module = importlib.import_module("bot.kill_switch")
        except Exception:
            module = importlib.import_module("kill_switch")
        return bool(module.get_kill_switch().is_active()), ""
    except Exception as exc:
        return None, f"kill_switch_probe_failed:{type(exc).__name__}:{exc}"


def _revoke_authority(reason: str) -> None:
    """Publish fail-closed authority truth without touching nonce readiness."""
    os.environ["NIJA_AUTHORITY_READY"] = "0"
    try:
        try:
            table = importlib.import_module("bot.readiness_table")
        except Exception:
            table = importlib.import_module("readiness_table")
        revoke = getattr(table, "revoke_ready", None)
        if callable(revoke):
            revoke("authority_ready", reason=reason)
    except Exception as exc:
        LOGGER.warning(
            "AUTHORITY_V135_REVOKE_PUBLISH_FAILED marker=%s reason=%s err=%s:%s",
            MARKER,
            reason,
            type(exc).__name__,
            exc,
        )


def _log_authority_block(reason: str, detail: str) -> None:
    global _LAST_BLOCK_SIGNATURE
    signature = f"{reason}:{detail}"
    with _LOCK:
        if signature == _LAST_BLOCK_SIGNATURE:
            return
        _LAST_BLOCK_SIGNATURE = signature
    LOGGER.critical(
        "AUTHORITY_V135_PROTECTED_STOP_BLOCK marker=%s reason=%s detail=%s "
        "writer_nonce_unchanged=true execution_authority_unchanged=true kill_switch_unchanged=true",
        MARKER,
        reason,
        detail or "none",
    )


def _patch_tsm_authority(tsm: ModuleType) -> bool:
    """Prevent writer-only bootstrap from contradicting an active/unknown stop."""
    current = getattr(tsm, "_is_authority_ready", None)
    if not callable(current):
        return False
    if getattr(current, "_nija_v135_kill_switch_scoped", False):
        return True

    original = current

    @wraps(original)
    def authority_ready_v135() -> bool:
        active, detail = _kill_switch_state(tsm)
        if active is not False:
            reason = (
                "v135_kill_switch_active"
                if active is True
                else "v135_kill_switch_state_unknown"
            )
            _revoke_authority(reason)
            _log_authority_block(reason, detail)
            return False
        return bool(original())

    setattr(authority_ready_v135, "_nija_v135_kill_switch_scoped", True)
    setattr(authority_ready_v135, "_nija_v135_original", original)
    tsm._is_authority_ready = authority_ready_v135
    LOGGER.critical(
        "AUTHORITY_V135_TSM_PATCHED marker=%s module=%s "
        "protected_stop_blocks_bootstrap=true fail_closed_unknown=true",
        MARKER,
        getattr(tsm, "__name__", "unknown"),
    )
    return True


def _ensure_aware_utc(value: Any) -> Any:
    if value is None or not isinstance(value, datetime):
        return value
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _status_with_runtime_expiry(
    status: Any,
    status_type: Any,
    *,
    now: Optional[datetime] = None,
) -> Any:
    """Return *status* with stale=True once its immutable expiry has passed."""
    if status is None or bool(getattr(status, "stale", True)):
        return status
    expiry = _ensure_aware_utc(getattr(status, "expiry", None))
    if not isinstance(expiry, datetime):
        return status
    current = _ensure_aware_utc(now or datetime.now(timezone.utc))
    if current < expiry:
        return status

    accepted = bool(getattr(status, "accepted", False))
    prior_reason = str(getattr(status, "reason", "") or "").strip()
    reason = "expired_after_publish" if accepted else prior_reason or "publication_expired"
    try:
        return status_type(
            accepted=accepted,
            stale=True,
            reason=reason,
            timestamp=getattr(status, "timestamp", None),
            expiry=getattr(status, "expiry", None),
        )
    except Exception:
        return status


def _status_dict(status: Any) -> dict[str, Any]:
    def _iso(value: Any) -> Any:
        return value.isoformat() if isinstance(value, datetime) else value

    return {
        "accepted": bool(getattr(status, "accepted", False)),
        "stale": bool(getattr(status, "stale", True)),
        "reason": str(getattr(status, "reason", "") or ""),
        "timestamp": _iso(getattr(status, "timestamp", None)),
        "expiry": _iso(getattr(status, "expiry", None)),
    }


def _patch_capital_publication_status(module: ModuleType) -> bool:
    """Make publication status and diagnostics honor elapsed expiry at read time."""
    cls = getattr(module, "CapitalAuthority", None)
    status_type = getattr(module, "SnapshotPublicationStatus", None)
    if not isinstance(cls, type) or status_type is None:
        return False

    current_status = getattr(cls, "get_snapshot_publication_status", None)
    if not callable(current_status):
        return False
    if not getattr(current_status, "_nija_v135_runtime_expiry", False):
        original_status = current_status

        @wraps(original_status)
        def get_status_v135(self: Any) -> Any:
            status = original_status(self)
            return _status_with_runtime_expiry(status, status_type)

        setattr(get_status_v135, "_nija_v135_runtime_expiry", True)
        setattr(get_status_v135, "_nija_v135_original", original_status)
        cls.get_snapshot_publication_status = get_status_v135

    current_snapshot = getattr(cls, "get_snapshot", None)
    if callable(current_snapshot) and not getattr(
        current_snapshot, "_nija_v135_runtime_expiry", False
    ):
        original_snapshot = current_snapshot

        @wraps(original_snapshot)
        def get_snapshot_v135(self: Any) -> dict[str, Any]:
            result = dict(original_snapshot(self))
            try:
                status = self.get_snapshot_publication_status()
                # Keep the existing diagnostics key synchronized with the
                # canonical getter.  Do not alter capital values or freshness.
                if "snapshot_publication" in result:
                    result["snapshot_publication"] = _status_dict(status)
            except Exception:
                pass
            return result

        setattr(get_snapshot_v135, "_nija_v135_runtime_expiry", True)
        setattr(get_snapshot_v135, "_nija_v135_original", original_snapshot)
        cls.get_snapshot = get_snapshot_v135

    LOGGER.critical(
        "CAPITAL_PUBLICATION_EXPIRY_V135_CONVERGED marker=%s module=%s "
        "runtime_expiry_authoritative=true freshness_extended=false",
        MARKER,
        getattr(module, "__name__", "unknown"),
    )
    return True


def _install_v78() -> bool:
    """Install the existing freshness-bounded capital refresh continuity patch."""
    try:
        module = importlib.import_module("bot.capital_refresh_live_continuity_v78_patch")
        installer = getattr(module, "install_import_hook", None) or getattr(module, "install", None)
        if not callable(installer) or not bool(installer()):
            return False
        return os.environ.get("NIJA_CAPITAL_REFRESH_LIVE_CONTINUITY_V78_INSTALLED") == "1"
    except Exception as exc:
        LOGGER.critical(
            "CAPITAL_REFRESH_V78_REQUIRED_INSTALL_FAILED marker=%s err=%s:%s",
            MARKER,
            type(exc).__name__,
            exc,
            exc_info=True,
        )
        return False


def _patch_release_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["capital_refresh_live_continuity_v78"] = (
            "NIJA_CAPITAL_REFRESH_LIVE_CONTINUITY_V78_INSTALLED"
        )
        required["activation_stop_capital_freshness_v135"] = _FLAG
        manifest.RELEASE_ID = RELEASE_ID
        return True
    except Exception:
        return False


def _patch_loaded_targets() -> tuple[bool, bool]:
    authority_ok = False
    capital_ok = False
    seen_tsm: set[int] = set()
    for name in ("bot.trading_state_machine", "trading_state_machine"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType) and id(module) not in seen_tsm:
            seen_tsm.add(id(module))
            authority_ok = _patch_tsm_authority(module) or authority_ok
    if not authority_ok:
        try:
            authority_ok = _patch_tsm_authority(importlib.import_module("bot.trading_state_machine"))
        except Exception:
            authority_ok = False

    seen_ca: set[int] = set()
    for name in ("bot.capital_authority", "capital_authority"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType) and id(module) not in seen_ca:
            seen_ca.add(id(module))
            capital_ok = _patch_capital_publication_status(module) or capital_ok
    if not capital_ok:
        try:
            capital_ok = _patch_capital_publication_status(importlib.import_module("bot.capital_authority"))
        except Exception:
            capital_ok = False
    return authority_ok, capital_ok


def _monitor() -> None:
    while True:
        try:
            authority_ok, capital_ok = _patch_loaded_targets()
            if not authority_ok or not capital_ok:
                LOGGER.warning(
                    "V135_OWNER_REASSERT_PENDING marker=%s authority=%s capital=%s fail_closed=true",
                    MARKER,
                    authority_ok,
                    capital_ok,
                )
        except Exception as exc:
            LOGGER.warning(
                "V135_OWNER_REASSERT_ERROR marker=%s err=%s:%s fail_closed=true",
                MARKER,
                type(exc).__name__,
                exc,
            )
        time.sleep(5.0)


def install() -> bool:
    global _MONITOR_STARTED
    with _LOCK:
        v78_ok = _install_v78()
        authority_ok, capital_ok = _patch_loaded_targets()
        manifest_ok = _patch_release_manifest()
        ok = bool(v78_ok and authority_ok and capital_ok and manifest_ok)
        if not ok:
            os.environ.pop(_FLAG, None)
            LOGGER.critical(
                "ACTIVATION_STOP_CAPITAL_FRESHNESS_V135_INSTALL_FAILED marker=%s "
                "v78=%s authority=%s capital=%s manifest=%s trading_fail_closed=true",
                MARKER,
                v78_ok,
                authority_ok,
                capital_ok,
                manifest_ok,
            )
            return False
        os.environ[_FLAG] = "1"
        if not _MONITOR_STARTED:
            _MONITOR_STARTED = True
            threading.Thread(
                target=_monitor,
                name="ActivationStopCapitalFreshnessV135",
                daemon=True,
            ).start()
        LOGGER.critical(
            "ACTIVATION_STOP_CAPITAL_FRESHNESS_V135_INSTALLED marker=%s release=%s "
            "v78_required=true protected_stop_authority=true publication_expiry_dynamic=true "
            "kill_switch_unchanged=true nonce_unchanged=true execution_authority_unchanged=true "
            "force_live=false",
            MARKER,
            RELEASE_ID,
        )
        return True


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "RELEASE_ID",
    "install",
    "install_import_hook",
    "_kill_switch_state",
    "_patch_tsm_authority",
    "_status_with_runtime_expiry",
    "_patch_capital_publication_status",
]
