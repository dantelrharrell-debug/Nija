#!/usr/bin/env python3
"""Read-only NIJA account-state path and file-presence diagnostic.

A path diagnostic is not a history/backup/restoration/execution attestation.
No source records are copied, deleted, repaired, or written by this module.
The repository's historical ledger recovery gates remain authoritative.
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
SQLITE_HEADER = b"SQLite format 3\x00"


def _mounts() -> list[tuple[Path, str]]:
    """Read kernel mount metadata; never infer mount presence from a directory."""
    try:
        lines = Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return []
    result: list[tuple[Path, str]] = []
    for line in lines:
        left, sep, right = line.partition(" - ")
        fields, right_fields = left.split(), right.split()
        if sep and len(fields) > 4 and right_fields:
            path = fields[4]
            for source, target in (("\\040", " "), ("\\011", "\t"), ("\\012", "\n"), ("\\134", "\\")):
                path = path.replace(source, target)
            result.append((Path(path), right_fields[0].lower()))
    return result


def _canonical(path: Path) -> Path | None:
    try:
        return path.resolve(strict=False)
    except (OSError, RuntimeError):
        return None


def _inside(target: Path, root: Path) -> bool:
    """A path belongs to a mount only when its resolved target is inside it."""
    normalized = _canonical(target)
    boundary = _canonical(root)
    return bool(normalized and boundary and (normalized == boundary or boundary in normalized.parents))


def _is_dedicated_mount(root: Path, mounts: Iterable[tuple[Path, str]]) -> bool:
    """Require an explicit non-ephemeral mount at the requested root."""
    canonical = _canonical(root)
    if canonical in (None, Path("/")) or not root.is_dir() or root.is_symlink():
        return False
    invalid = {"overlay", "tmpfs", "ramfs", "unknown", "", "proc", "sysfs", "devpts", "squashfs"}
    return any(_canonical(path) == canonical and fs.lower() not in invalid for path, fs in mounts)


def _inventory(folder: Path) -> dict[str, Any]:
    """Inventory account JSON without logging symbols, users, or raw contents."""
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
    files, total = 0, 0
    for path in entries:
        if path.is_symlink() or not path.is_file() or path.suffix.lower() != ".json":
            return {"state": "unexpected_or_symlink_entry", "files": files, "stable": False}
        try:
            before = path.stat()
            if before.st_size > MAX_BYTES_PER_FILE:
                return {"state": "oversize_file", "files": files, "stable": False}
            with path.open("rb") as handle:
                raw = handle.read(MAX_BYTES_PER_FILE + 1)
            if len(raw) > MAX_BYTES_PER_FILE:
                return {"state": "oversize_file", "files": files, "stable": False}
            # JSON object is the shared top-level shape of account positions
            # and EntryPriceStore files; no semantic cost-basis proof follows.
            parsed = json.loads(raw)
            if not isinstance(parsed, dict):
                return {"state": "unexpected_json_shape", "files": files, "stable": False}
            after = path.stat()
            if (before.st_size, before.st_mtime_ns, before.st_ino) != (
                after.st_size, after.st_mtime_ns, after.st_ino
            ) or after.st_size != len(raw):
                return {"state": "changing_during_read", "files": files, "stable": False}
        except (OSError, UnicodeError, ValueError):
            return {"state": "unreadable_or_invalid_json", "files": files, "stable": False}
        manifest.update(path.name.encode("utf-8", "surrogatepass"))
        manifest.update(b"\x00")
        manifest.update(hashlib.sha256(raw).digest())
        files += 1
        total += after.st_size
    return {
        "state": "read_only_inventory",
        "files": files,
        "bytes": total,
        "directory_empty": files == 0,
        "inventory_sha256": manifest.hexdigest(),
        "stable": True,
        "historical_completeness_proven": False,
    }


def _ledger_observation(ledger: Path) -> str:
    """Check only file presence and header, not SQLite integrity or WAL."""
    if ledger.is_symlink():
        return "symlink_ledger_rejected"
    if not ledger.is_file():
        return "ledger_file_missing"
    try:
        before = ledger.stat()
        with ledger.open("rb") as handle:
            header = handle.read(len(SQLITE_HEADER))
        after = ledger.stat()
        if (before.st_size, before.st_mtime_ns, before.st_ino) != (
            after.st_size, after.st_mtime_ns, after.st_ino
        ):
            return "ledger_changed_during_read"
        if header != SQLITE_HEADER:
            return "sqlite_header_missing_or_invalid"
        return "sqlite_header_observed_integrity_not_tested"
    except OSError:
        return "ledger_unreadable"


def inspect(
    persistent_root: Path,
    ledger: Path,
    positions: Path,
    entry_prices: Path,
    *,
    mounts: Iterable[tuple[Path, str]] | None = None,
    legacy_root: Path | None = None,
) -> dict[str, Any]:
    """Fail closed on absent evidence; never authorize observation."""
    observed = _mounts() if mounts is None else list(mounts)
    mounted = _is_dedicated_mount(persistent_root, observed)
    paths = {
        "trading_ledger": ledger,
        "account_positions": positions,
        "account_entry_prices": entry_prices,
    }
    aligned = {name: _inside(path, persistent_root) for name, path in paths.items()}
    ledger_state = _ledger_observation(ledger)
    stores = {
        "account_positions": _inventory(positions),
        "account_entry_prices": _inventory(entry_prices),
    }
    legacy: dict[str, Any] = {}
    legacy_not_preserved = False
    if legacy_root is not None:
        for kind, name in (("account_positions", "positions"), ("account_entry_prices", "entry_prices")):
            legacy_path = legacy_root / name
            legacy[kind] = _inventory(legacy_path)
            # A separate populated legacy directory and an empty new store
            # must not be presented as a completed migration.
            if _canonical(legacy_path) != _canonical(paths[kind]):
                if legacy[kind].get("files", 0) > 0 and stores[kind].get("files", 0) == 0:
                    legacy_not_preserved = True
    problems: list[str] = []
    if not mounted:
        problems.append("dedicated_mount_unverified")
    for name, is_aligned in aligned.items():
        if not is_aligned:
            problems.append("outside_persistent_mount:" + name)
    if ledger_state != "sqlite_header_observed_integrity_not_tested":
        problems.append(ledger_state)
    for name, inventory in stores.items():
        if not inventory.get("stable", False):
            problems.append(name + ":" + str(inventory.get("state")))
    if legacy_not_preserved:
        problems.append("populated_legacy_store_not_observed_in_new_store")

    if not all(aligned.values()):
        status = "STORAGE_PATHS_OUTSIDE_PERSISTENT_DISK"
    elif not mounted:
        status = "DEDICATED_MOUNT_UNVERIFIED"
    elif ledger_state != "sqlite_header_observed_integrity_not_tested":
        status = "TRADING_LEDGER_FILE_UNVERIFIED"
    elif any(not x.get("stable", False) for x in stores.values()):
        status = "ACCOUNT_STORE_FILES_UNVERIFIED"
    elif legacy_not_preserved:
        status = "LEGACY_ACCOUNT_STATE_NOT_PRESERVED"
    else:
        status = "PATHS_AND_FILES_PRESENT_HISTORY_NOT_CERTIFIED"
    aligned_and_present = bool(not problems)
    return {
        "status": status,
        "persistent_root": str(persistent_root),
        "dedicated_mount_observed": mounted,
        "path_within_persistent_root": aligned,
        "trading_ledger_file_observed": ledger_state == "sqlite_header_observed_integrity_not_tested",
        "trading_ledger_file_state": ledger_state,
        "account_store_inventories": stores,
        "optional_legacy_inventories": legacy,
        "possible_unmigrated_legacy_state": legacy_not_preserved,
        "incomplete_evidence": problems,
        "storage_paths_aligned": aligned_and_present,
        "sqlite_integrity_verified": False,
        "off_host_backup_verified": False,
        "isolated_restore_verified": False,
        "historical_entries_verified": False,
        "protective_exit_coverage_verified": False,
        "strategy_pnl_verified": False,
        "execution_proof_fresh_verified": False,
        "execution_authorized": False,
        "eligible_for_24h_observation": False,
        "files_written_or_copied": False,
        "broker_or_trading_permissions_changed": False,
        "next": "Preserve old and current JSON/SQLite off-host; independently verify restore and broker evidence before any operator-approved cutover.",
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
        report = inspect(args.persistent_root, args.ledger, args.positions_dir,
                         args.entry_prices_dir, legacy_root=args.legacy_root)
        print(json.dumps(report, sort_keys=True, indent=2))
        # Success only means presence/alignment, NEVER observation eligibility.
        return 0 if report["storage_paths_aligned"] else 2
    except (OSError, ValueError, RuntimeError) as exc:
        print(json.dumps({"status": "FAILED_CLOSED", "error_type": type(exc).__name__,
                          "eligible_for_24h_observation": False, "files_written_or_copied": False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
