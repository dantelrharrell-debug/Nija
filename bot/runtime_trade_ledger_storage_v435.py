"""Read-only trading-ledger storage evidence, never a durability attestation.

An in-container SQLite file may vanish when Render replaces a container.
This diagnostic distinguishes root overlay/tmpfs from a dedicated filesystem
mount, but a mount alone does not prove a completed migration or working backup.
It never changes orders, connections, entries, exits or kill-switches.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def _mount_rows() -> list[tuple[str, str]]:
    try:
        lines = Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return []
    mounts = []
    for line in lines:
        before, sep, after = line.partition(" - ")
        if not sep:
            continue
        fields, right = before.split(), after.split()
        if len(fields) < 5 or not right:
            continue
        mount = fields[4].replace("\\040", " ").replace("\\011", "\t")
        mounts.append((mount, right[0].lower()))
    return mounts


def inspect_ledger_storage(
    path: str | Path, *, mount_rows: list[tuple[str, str]] | None = None,
) -> dict[str, Any]:
    """Inspect mount metadata without writes or assuming that backup succeeded."""
    actual = Path(path).resolve(strict=False)
    mounts = _mount_rows() if mount_rows is None else mount_rows
    candidate = None
    for mount, fs_type in mounts:
        location = Path(mount).resolve(strict=False)
        if actual == location or location in actual.parents:
            if candidate is None or len(str(location)) > len(str(candidate[0])):
                candidate = (location, str(fs_type or "").lower())
    mountpoint, filesystem = candidate if candidate else (None, "unknown")
    dedicated = bool(
        mountpoint is not None
        and str(mountpoint) != "/"
        and filesystem not in {"overlay", "tmpfs", "ramfs", "unknown"}
    )
    if not mounts:
        reason = "mount_evidence_unavailable"
    elif dedicated:
        reason = "dedicated_mount_detected_migration_and_backup_unverified"
    elif filesystem in {"overlay", "tmpfs", "ramfs"}:
        reason = "ephemeral_filesystem"
    else:
        reason = "dedicated_mount_not_proven"
    return {
        "state": reason,
        "dedicated_mount_detected": dedicated,
        "restart_persistence_verified": False,
        "migration_integrity_verified": False,
        "backup_restore_verified": False,
        "history_completeness_verified": False,
        "ready_for_historical_pnl_certification": False,
        "orders_submitted": False,
        "data_modified": False,
    }


__all__ = ["inspect_ledger_storage"]
