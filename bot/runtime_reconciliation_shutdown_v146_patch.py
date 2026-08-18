"""NIJA startup reconciliation and shutdown convergence v146.

The v144 entry gate correctly requires explicit restart-reconciliation truth,
but the canonical startup path already performs account-scoped, authoritative
position snapshots through ``position_sync_dispatch_authority_v96_patch`` and
did not bridge that proof into ``NIJA_RECONCILIATION_*``.  As a result, a
healthy live startup remained permanently fail-closed with ``status=missing``.

This patch publishes ``CLEAN_START`` only when at least one connected broker is
present and every connected platform/user broker has completed its authoritative
startup position snapshot.  A missing or regressed snapshot revokes the proof
before readiness-table publication.  Explicit discrepancy/failure outcomes are
never overwritten.

The companion source changes in ``nija_core_loop`` and ``bot_main`` make normal
core-loop waits interruptible so a failed startup can release writer authority
without waiting on an unrelated 30/150 second sleep.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
from functools import wraps
from types import ModuleType
from typing import Any


LOGGER = logging.getLogger("nija.runtime_reconciliation_shutdown_v146")
MARKER = "20260818-runtime-reconciliation-shutdown-v146"
RELEASE_ID = "20260818-runtime-convergence-v146"
_FLAG = "NIJA_RUNTIME_RECONCILIATION_SHUTDOWN_V146_READY"
_PATCH_ATTR = "_nija_runtime_reconciliation_shutdown_v146"
_LOCK = threading.RLock()
_INSTALLED = False
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}
_TERMINAL_FAILURE_STATUSES = {
    "DISCREPANCIES_FOUND",
    "FAILED",
    "FAILURE",
    "ERROR",
    "UNSAFE",
}


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in _TRUE


def _position_sync_truth(module: ModuleType, manager: Any) -> tuple[bool, list[str], dict[str, bool]]:
    """Return strict position-sync truth without treating zero brokers as ready."""
    if manager is None:
        return False, [], {}
    try:
        v95 = module._v95_module()
        ready, pending, status = v95.position_sync_status(manager)
        normalized = {str(name): bool(value) for name, value in dict(status or {}).items()}
        connected = dict(v95._connected_brokers(manager) or {})
        connected_names = {str(name) for name in connected}
        status_names = set(normalized)
        fetch_pending = sorted(
            str(name)
            for name, broker in connected.items()
            if getattr(broker, "_startup_position_sync_fetch_ok", None) is not True
        )
        all_pending = sorted(
            set(str(name) for name in (pending or []))
            | set(fetch_pending)
            | connected_names.symmetric_difference(status_names)
        )
        authoritative = (
            bool(connected_names)
            and connected_names == status_names
            and bool(ready)
            and not all_pending
        )
        return authoritative, all_pending, normalized
    except Exception as exc:
        LOGGER.warning(
            "STARTUP_RECONCILIATION_V146_POSITION_SYNC_ERROR marker=%s error=%s:%s fail_closed=true",
            MARKER,
            type(exc).__name__,
            exc,
        )
        return False, [], {}


def _publish_reconciliation_truth(
    ready: bool,
    pending: list[str],
    status: dict[str, bool],
    *,
    source: str,
) -> bool:
    """Publish or revoke reconciliation truth in fail-closed write order."""
    authoritative = bool(ready and status and all(status.values()))
    previous_status = str(os.environ.get("NIJA_RECONCILIATION_STATUS", "") or "").strip().upper()
    previous_complete = _truthy(os.environ.get("NIJA_RECONCILIATION_COMPLETE"))

    # An explicit discrepancy/failure is stronger evidence than a later
    # position-only snapshot and must remain fail-closed for review, even if
    # its producer failed before publishing the completion bit.
    if previous_status in _TERMINAL_FAILURE_STATUSES:
        LOGGER.error(
            "STARTUP_RECONCILIATION_V146_FAILURE_PRESERVED marker=%s source=%s status=%s position_sync_ready=%s",
            MARKER,
            source,
            previous_status,
            str(authoritative).lower(),
        )
        return False

    if authoritative:
        # Promotion order is safety-sensitive: publish the accepted status
        # before flipping completion true so readers never see complete+missing.
        final_status = previous_status if previous_status in {"CLEAN", "CLEAN_START"} else "CLEAN_START"
        os.environ["NIJA_RECONCILIATION_STATUS"] = final_status
        os.environ["NIJA_RECONCILIATION_COMPLETE"] = "true"
        changed = not previous_complete or previous_status != final_status
        log = LOGGER.warning if changed else LOGGER.debug
        log(
            "STARTUP_RECONCILIATION_V146_READY marker=%s source=%s status=%s brokers=%s authoritative_snapshots=true",
            MARKER,
            source,
            final_status,
            sorted(status),
        )
        return True

    # Revocation order is the inverse: completion becomes false before the
    # descriptive status changes, preventing a transient complete+clean read.
    os.environ["NIJA_RECONCILIATION_COMPLETE"] = "false"
    os.environ["NIJA_RECONCILIATION_STATUS"] = "PENDING"
    changed = previous_complete or previous_status != "PENDING"
    log = LOGGER.warning if changed else LOGGER.debug
    log(
        "STARTUP_RECONCILIATION_V146_PENDING marker=%s source=%s pending=%s status=%s fail_closed=true",
        MARKER,
        source,
        sorted(str(value) for value in pending),
        status,
    )
    return False


def _patch_position_sync_publication(module: ModuleType) -> bool:
    """Bridge position truth before v96 emits the readiness-table edge."""
    current = getattr(module, "publish_position_sync_readiness", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    @wraps(current)
    def publish_v146(manager: Any, *, source: str) -> tuple[bool, list[str], dict[str, bool]]:
        # Publish reconciliation first. v96 then writes position_sync_ready and
        # synchronously notifies StartupCoordinator, which now observes both
        # proofs in the same readiness transition.
        ready, pending, status = _position_sync_truth(module, manager)
        _publish_reconciliation_truth(ready, pending, status, source=source)

        reported_ready, reported_pending, reported_status = current(
            manager,
            source=source,
        )
        final_ready, final_pending, final_status = _position_sync_truth(
            module,
            manager,
        )

        # v95's historical status only inspected the adopted marker. Correct a
        # stale/legacy true result when its independent fetch proof is absent.
        if bool(reported_ready) != final_ready:
            try:
                readiness = module._readiness_module()
                readiness.set_ready(
                    module.READINESS_KEY,
                    final_ready,
                    allow_regression=True,
                )
                os.environ["NIJA_POSITION_SYNC_ACTIVATION_READY"] = (
                    "1" if final_ready else "0"
                )
                os.environ["NIJA_POSITION_SYNC_DISPATCH_READY"] = (
                    "1" if final_ready else "0"
                )
                LOGGER.warning(
                    "STARTUP_RECONCILIATION_V146_FETCH_PROOF_CORRECTED marker=%s "
                    "source=%s reported_ready=%s final_ready=%s "
                    "reported_pending=%s reported_status=%s",
                    MARKER,
                    source,
                    str(bool(reported_ready)).lower(),
                    str(final_ready).lower(),
                    list(reported_pending or []),
                    dict(reported_status or {}),
                )
            except Exception:
                final_ready = False
                final_pending = sorted(set(final_pending) | {"readiness_correction_failed"})
                LOGGER.exception(
                    "STARTUP_RECONCILIATION_V146_READINESS_CORRECTION_FAILED "
                    "marker=%s source=%s fail_closed=true",
                    MARKER,
                    source,
                )

        # Reconcile a broker-set race that occurred between the pre-publication
        # snapshot and v96's own snapshot. A regression is immediately revoked;
        # a promotion is followed by an explicit coordinator reconciliation.
        if (
            final_ready != ready
            or final_pending != pending
            or final_status != status
        ):
            promoted = _publish_reconciliation_truth(
                final_ready,
                final_pending,
                final_status,
                source=f"{source}:post_publish_race",
            )
            if promoted and not ready:
                try:
                    from bot.readiness_table import get_version, snapshot
                    from bot.startup_coordinator import get_startup_coordinator

                    get_startup_coordinator().record_readiness(
                        key="startup_reconciliation",
                        value=True,
                        version=get_version(),
                        table=snapshot(),
                    )
                except Exception:
                    LOGGER.debug(
                        "STARTUP_RECONCILIATION_V146_RECONCILE_NOTIFY_SKIPPED marker=%s",
                        MARKER,
                        exc_info=True,
                    )
        return final_ready, final_pending, final_status

    setattr(publish_v146, _PATCH_ATTR, True)
    setattr(publish_v146, "__wrapped__", current)
    module.publish_position_sync_readiness = publish_v146
    return True


def _own_release() -> bool:
    """Make v146 the terminal runtime manifest owner after successful install."""
    manifest = importlib.import_module("bot.runtime_release_manifest_patch")
    required = getattr(manifest, "_REQUIRED_FLAGS", None)
    if not isinstance(required, dict):
        return False
    required["runtime_reconciliation_shutdown_v146"] = _FLAG
    manifest.DECLARED_RELEASE_ID = RELEASE_ID
    manifest.RELEASE_ID = RELEASE_ID
    os.environ["NIJA_RUNTIME_RELEASE_ID"] = RELEASE_ID

    for module_name in (
        "bot.runtime_quality_hardening_v144_patch",
        "bot.runtime_startup_convergence_v145_patch",
    ):
        module = importlib.import_module(module_name)
        module.RELEASE_ID = RELEASE_ID
    return True


def install_import_hook() -> bool:
    """Install the reconciliation bridge and publish the v146 release proof."""
    global _INSTALLED
    with _LOCK:
        try:
            position_sync = importlib.import_module(
                "bot.position_sync_dispatch_authority_v96_patch"
            )
            installer = getattr(position_sync, "install_import_hook", None)
            if callable(installer) and installer() is False:
                raise RuntimeError("position_sync_v96_installer_returned_false")
            bridge_ok = _patch_position_sync_publication(position_sync)
            release_ok = _own_release()
            ready = bool(bridge_ok and release_ok)
        except Exception as exc:
            ready = False
            LOGGER.critical(
                "RUNTIME_RECONCILIATION_SHUTDOWN_V146_FAILED marker=%s error=%s:%s trading_fail_closed=true",
                MARKER,
                type(exc).__name__,
                exc,
                exc_info=True,
            )

        os.environ[_FLAG] = "1" if ready else "0"
        _INSTALLED = ready
        if ready:
            LOGGER.info(
                "RUNTIME_RECONCILIATION_SHUTDOWN_V146_INSTALLED marker=%s "
                "release=%s authoritative_position_bridge=true "
                "zero_broker_fail_closed=true discrepancy_preserved=true "
                "shutdown_interruptible=true",
                MARKER,
                RELEASE_ID,
            )
        return ready


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER",
    "RELEASE_ID",
    "install",
    "install_import_hook",
    "_position_sync_truth",
    "_publish_reconciliation_truth",
    "_patch_position_sync_publication",
    "_own_release",
]
