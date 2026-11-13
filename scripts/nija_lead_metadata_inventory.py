"""Inventory lead-file metadata only; never open file contents or SQLite.

Run with python -B -S in the existing instance. Output is private operational
metadata, not proof of database validity, recoverability, or workflow ownership.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import stat
from typing import Mapping

PATH_KEYS = ("NIJA_LEAD_DB_PATH", "NIJA_OUTREACH_DB_PATH", "NIJA_LEAD_FORWARD_DB_PATH")
SAFE_PATH = re.compile(r"/[A-Za-z0-9_./ -]+\Z")
SIDECARS = ("-wal", "-shm", "-journal")


def safe_path(value: str) -> bool:
    """Reject relative paths, URLs, control characters and traversal."""
    return bool(SAFE_PATH.fullmatch(value)) and ".." not in Path(value).parts


def metadata(path: Path, persistent_root: Path) -> dict:
    """Use lstat only; do not follow links or read file bytes."""
    result = {"path": str(path), "status": "UNVERIFIED", "row_count": None}
    try:
        # Refuse symlink parents too; never traverse a lead path into trading data.
        for parent in (path, *path.parents):
            if stat.S_ISLNK(parent.lstat().st_mode):
                return dict(result, reason="symlink_requires_owner_review")
        info = path.lstat()
        mounted = persistent_root.is_mount()
        on_root = path.is_relative_to(persistent_root)
        result.update(
            status="METADATA_ONLY", regular_file=stat.S_ISREG(info.st_mode),
            size_bytes=info.st_size, uid=info.st_uid, gid=info.st_gid,
            mode=oct(stat.S_IMODE(info.st_mode)), mtime_ns=info.st_mtime_ns,
            device=info.st_dev, inode=info.st_ino,
            under_expected_root=on_root, expected_root_is_mount=mounted,
            persistence="mount_metadata_only" if mounted and on_root else "unverified",
        )
    except FileNotFoundError:
        result["reason"] = "missing_not_zero_records"
    except OSError:
        result["reason"] = "metadata_inaccessible"
    return result


def inventory(environ: Mapping[str, str] | None = None,
              persistent_root: Path = Path("/data"),
              app_root: Path = Path("/app/data")) -> dict:
    """Inspect explicit overrides and lead-named files in two bounded directories."""
    env = os.environ if environ is None else environ
    paths = {app_root / "nija_outreach.sqlite3", persistent_root / "nija_outreach.sqlite3",
             persistent_root / "nija_lead_forwarding.sqlite3"}
    overrides = {}
    for key in PATH_KEYS:
        raw = env.get(key)
        if raw is None:
            overrides[key] = {"configured": False}
        elif safe_path(raw.strip()):
            overrides[key] = {"configured": True, "path": raw.strip()}
            paths.add(Path(raw.strip()))
        else:
            overrides[key] = {"configured": True, "status": "invalid_or_redacted_path"}
    discovery = {}
    for root in (app_root, persistent_root):
        try:
            if root.is_symlink():
                discovery[str(root)] = "symlink_not_traversed"
                continue
            # Bounded, nonrecursive inventory. Incomplete discovery is explicit.
            with os.scandir(root) as entries:
                for index, entry in enumerate(entries):
                    if index >= 1000:
                        discovery[str(root)] = "truncated_requires_review"
                        break
                    name = entry.name.lower()
                    if ("lead" in name or "outreach" in name) and name.endswith((".db", ".sqlite", ".sqlite3")):
                        candidate = root / entry.name
                        if safe_path(str(candidate)):
                            paths.add(candidate)
                else:
                    discovery[str(root)] = "top_level_only"
        except OSError:
            discovery[str(root)] = "inaccessible_or_missing"
    files = []
    for path in sorted(paths):
        if not safe_path(str(path)):
            continue
        item = metadata(path, persistent_root)
        item["sidecars"] = [metadata(Path(str(path) + suffix), persistent_root) for suffix in SIDECARS]
        files.append(item)
    return {
        "observed_at_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "FILESYSTEM_METADATA_ONLY", "sqlite_opened": False,
        "production_certified": False, "backup_verified": False,
        "effective_path_precedence": "first_truthy_lead_then_outreach_then_default_trim_after_selection",
        "lead_path_overrides": overrides, "discovery": discovery, "candidates": files,
        "limitations": ["not_exhaustive", "not_schema_or_record_evidence", "not_runtime_ownership_proof"],
    }


if __name__ == "__main__":
    print(json.dumps(inventory(), indent=2, sort_keys=True))
