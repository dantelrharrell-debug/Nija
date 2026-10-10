#!/usr/bin/env python3
"""Read-only NIJA account-state durability audit; never authorizes live trading.

Diagnoses mismatches between the mounted ledger disk and account-scoped JSON
state stores. It does not migrate, copy, delete, restore, or write any records.
Directory alignment alone is NOT proof that historical data survived.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable

MAX_FILES = 1000
MAX_BYTES_PER_FILE = 16 * 1024 * 1024


def _mounts() -> list[tuple[Path, str]]:
    """Read Linux mount metadata without changing the filesystem."""
    try:
        lines = Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return []
    result: list[tuple[Path, str]] = []
    for line in lines:
        left, sep, right = line.partition(" - ")
        fields = left.split()
        fs = right.split()
        if sep and len(fields) > 4 and fs:
            mount_path = fields[4].replace("\\040", " ").replace("\\011", "\t")
            result.append((Path(mount_path), fs[0].lower()))
    return result


def _inside(target: Path, root: Path) -> bool:
    """Resolve existing symlinks before checking a containment boundary."""
    normalized = target.resolve(strict=False)
    boundary = root.resolve(strict=False)
    return normalized == boundary or boundary in normalized.parents


def _is_dedicated_mount(root: Path, mounts: Iterable[tuple[Path, str]]) -> bool:
    """Fail closed on an absent, overlay, tmpfs, or unknown root mount."""
    canonical = root.resolve(strict=False)
    if canonical == Path("/"):
        return False
    return any(
        path.resolve(strict=False) == canonical
        and fs not in {"overlay", "tmpfs", "ramfs", "unknown", ""}
        for path, fs in mounts
    )


def _inventory(folder: Path) -> dict[str, Any]:
    """Hash metadata and bounded file contents, not private trading records."""
    if folder.is_symlink():
        return {"state": "symlink_directory_rejected", "files": 0, "stable": False}
    if not folder.is_dir():
        return {"state": "missing_directory", "files": 0, "stable": False}
    try:
        entries = sorted(folder.iterdir(), key=lambda item: item.name)
    except OSError:
        return {"state": "unreadable_directory", "files": 0, "stable": False}
    if len(entries) > MAX_FILES:
        return {"state": "too_many_entries", "files": len(entries), "stable": False}
    manifest = hashlib.sha256()
    files = 0
    total = 0
    for path in entries:
        if path.is_symlink() or not path.is_file() or path.suffix.lower() != ".json":
            return {"state": "unexpected_or_symlink_entry", "files": files, "stable": False}
        try:
            before = path.stat()
            if before.st_size > MAX_BYTES_PER_FILE:
                return {"state": "oversize_file", "files": files, "stable": False}
            content_hash = hashlib.sha256()
            with path.open("rb") as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b""):
                    content_hash.update(block)
            after = path.stat()
            if (before.st_size, before.st_mtime_ns, before.st_ino) != (
                after.st_size, after.st_mtime_ns, after.st_ino
            ):
                return {"state": "changing_during_read", "files": files, "stable": False}
        except OSError:
            return {"state": "unreadable_file", "files": files, "stable": False}
        # Relative names are hashed; no user/account names or data are emitted.
        manifest.update(path.name.encode("utf-8", "surrogatepass"))
        manifest.update(b"\x00")
        manifest.update(content_hash.digest())
        files += 1
        total += after.st_size
    return {
        "state": "read_only_inventory",
        "files": files,
        "bytes": total,
        "inventory_sha256": manifest.hexdigest(),
        "stable": True,
    }


def inspect(
    persistent_root: Path,
    ledger: Path,
    positions: Path,
    entry_prices: Path,
    *,
    mounts: Iterable[tuple[Path, str]] | None = None,
    legacy_root: Path | None = None,
) -> dict[str, Any]:
    """Report configuration and artifacts without certifying lost history."""
    observed = _mounts() if mounts is None else list(mounts)
    mounted = _is_dedicated_mount(persistent_root, observed)
    aligned = {
        "trading_ledger": _inside(ledger, persistent_root),
        "account_positions": _inside(positions, persistent_root),
        "account_entry_prices": _inside(entry_prices, persistent_root),
    }
    ledger_exists = ledger.is_file() and not ledger.is_symlink()
    stores = {
        "account_positions": _inventory(positions),
        "account_entry_prices": _inventory(entry_prices),
    }
    legacy: dict[str, Any] = {}
    if legacy_root is not None:
        for kind, name in (("account_positions", "positions"), ("account_entry_prices", "entry_prices")):
            legacy[kind] = _inventory(legacy_root / name)
    return {
        "status": (
            "STORAGE_PATHS_OUTSIDE_PERSISTENT_DISK"
            if not all(aligned.values()) else
            "DEDICATED_MOUNT_UNVERIFIED"
            if not mounted else
            "PATHS_ALIGNED_HISTORY_NOT_CERTIFIED"
        ),
        "persistent_root": str(persistent_root),
        "dedicated_mount_observed": mounted,
        "path_within_persistent_root": aligned,
        "trading_ledger_file_observed": ledger_exists,
        "account_store_inventories": stores,
        "optional_legacy_inventories": legacy,
        "storage_paths_aligned": bool(mounted and all(aligned.values())),
        "ledger_integrity_verified": False,
        "off_host_backup_verified": False,
        "isolated_restore_verified": False,
        "historical_entries_verified": False,
        "strategy_pnl_verified": False,
        "execution_authorized": False,
        "eligible_for_24h_observation": False,
        "files_written_or_copied": False,
        "broker_or_trading_permissions_changed": False,
        "next": "Preserve any /app/data state off-host; compare hashes and authenticated exchange evidence before operator-approved migration."
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--persistent-root", type=Path, default=Path("/data"))
    parser.add_argument("--ledger", type=Path, default=Path(os.getenv("NIJA_TRADE_LEDGER_DB_PATH") or "/data/trade_ledger.db"))
    parser.add_argument("--positions-dir", type=Path, default=Path(os.getenv("NIJA_ACCOUNT_POSITION_STATE_DIR") or "data/positions"))
    parser.add_argument("--entry-prices-dir", type=Path, default=Path(os.getenv("NIJA_ACCOUNT_ENTRY_PRICE_STATE_DIR") or "data/entry_prices"))
    parser.add_argument("--legacy-root", type=Path, default=None)
    args = parser.parse_args()
    try:
        report = inspect(
            args.persistent_root, args.ledger, args.positions_dir,
            args.entry_prices_dir, legacy_root=args.legacy_root,
        )
        print(json.dumps(report, sort_keys=True, indent=2))
        return 0 if report["storage_paths_aligned"] else 2
    except (OSError, ValueError) as exc:
        print(json.dumps({"status": "FAILED_CLOSED", "error_type": type(exc).__name__,
                          "eligible_for_24h_observation": False, "files_written_or_copied": False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
