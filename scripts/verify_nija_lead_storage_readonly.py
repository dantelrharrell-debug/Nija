#!/usr/bin/env python3
"""Read-only NIJA Render lead/forward storage placement and integrity preflight.

This is NOT a production-data backup, a sender, a migration, or certification of
IONOS/Render ownership. It must never create a missing SQLite database.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
from pathlib import Path
import sqlite3
import sys
from typing import Any


TABLE_SPECS = {
    "intake": ("website_leads", {"event_key", "form_name", "email", "submitted_at", "received_at", "source_payload_json"}),
    "forward": ("website_lead_forwarding", {"event_key", "state", "lease_until", "lease_token"}),
}


def configured_paths(environ: dict[str, str] | None = None) -> tuple[Path, Path]:
    """Mirror current render_lead_intake.py defaults without importing app code."""
    env = os.environ if environ is None else environ
    # Mirror runtime precedence: select first truthy value, then trim.
    # Whitespace-only primary overrides must fail closed, not fall through.
    raw_lead = str(env.get("NIJA_LEAD_DB_PATH") or env.get("NIJA_OUTREACH_DB_PATH")
                   or "/app/data/nija_outreach.sqlite3").strip()
    lead = Path(raw_lead) if raw_lead else Path(".")
    override = str(env.get("NIJA_LEAD_FORWARD_DB_PATH") or "").strip()
    forward = Path(override) if override else (Path("/data/nija_lead_forwarding.sqlite3") if Path("/data").is_dir() else lead)
    return lead, forward


def _has_symlink(path: Path) -> bool:
    probe = path
    while True:
        if probe.is_symlink():
            return True
        if probe.parent == probe:
            return False
        probe = probe.parent


def _unsafe_live_sqlite_state(path: Path) -> str | None:
    """Refuse WAL and rollback sidecars before opening SQLite."""
    for suffix in ("-wal", "-shm", "-journal"):
        if Path(str(path) + suffix).exists():
            return "active_sqlite_sidecar_requires_consistent_snapshot"
    try:
        with path.open("rb") as source:
            header = source.read(100)
    except OSError:
        return "sqlite_header_unavailable"
    if len(header) < 100 or header[:16] != b"SQLite format 3\x00":
        return "sqlite_header_invalid"
    # mode=ro may create -shm when SQLite opens a WAL-mode database.
    if header[18] == 2 or header[19] == 2:
        return "wal_database_requires_consistent_snapshot"
    return None


def inspect_database(path: Path, expected_root: Path, kind: str) -> dict[str, Any]:
    """Inspect aggregate counts only. Do not fetch customer email or payload."""
    table, required = TABLE_SPECS[kind]
    result: dict[str, Any] = {
        "path": str(path), "exists": False, "under_expected_root": False,
        "sqlite_integrity": "unverified", "schema": "unverified", "row_count": None,
        "status": "UNVERIFIED",
    }
    if kind == "forward":
        result["alias_schema"] = "unverified"
        result["alias_row_count"] = None
    if not path.is_absolute() or not expected_root.is_absolute():
        result["reason"] = "relative_path_rejected"
        return result
    if _has_symlink(path) or _has_symlink(expected_root):
        result["reason"] = "symlink_path_rejected"
        return result
    if not expected_root.is_dir():
        result["reason"] = "expected_persistent_root_not_available"
        return result
    try:
        result["under_expected_root"] = path.resolve().is_relative_to(expected_root.resolve()) and path.resolve() != expected_root.resolve()
    except (OSError, RuntimeError):
        result["reason"] = "path_resolution_failed"
        return result
    if not path.is_file():
        result["reason"] = "database_unavailable_not_zero_rows"
        return result
    result["exists"] = True
    if path.name.lower() in {"trade_ledger.db", "users.db", "positions.db"}:
        result["reason"] = "restricted_non_lead_database"
        return result
    unsafe_state = _unsafe_live_sqlite_state(path)
    if unsafe_state:
        result["reason"] = unsafe_state
        return result
    try:
        before = path.stat()
    except OSError:
        result["reason"] = "sqlite_stat_unavailable"
        return result
    try:
        # immutable=1 prevents SQLite from creating sidecars. WAL databases
        # are refused above. This is a diagnostic, never a live snapshot.
        with contextlib.closing(sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True, timeout=2)) as conn:
            conn.execute("PRAGMA query_only = ON")
            quick = conn.execute("PRAGMA quick_check").fetchall()
            result["sqlite_integrity"] = "ok" if quick == [("ok",)] else "failed"
            if result["sqlite_integrity"] != "ok":
                result["reason"] = "sqlite_integrity_failed"
                return result
            # sqlite_master and PRAGMA table_info are metadata-only reads.
            present = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()
            if not present:
                result["schema"] = "missing_required_table"
                result["reason"] = "missing_required_table"
                return result
            columns = {row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')}
            if not required.issubset(columns):
                result["schema"] = "missing_required_columns"
                result["reason"] = "missing_required_columns"
                return result
            result["schema"] = "expected_columns_present"
            result["row_count"] = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            if kind == "forward":
                alias = "website_lead_forward_aliases"
                exists = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (alias,)
                ).fetchone()
                if not exists:
                    result["alias_schema"] = "missing_required_table"
                    result["reason"] = "missing_forward_alias_table"
                    return result
                alias_columns = {row[1] for row in conn.execute(f'PRAGMA table_info("{alias}")')}
                if not {"source_key", "legacy_key", "created_at"}.issubset(alias_columns):
                    result["alias_schema"] = "missing_required_columns"
                    result["reason"] = "missing_forward_alias_columns"
                    return result
                result["alias_schema"] = "expected_columns_present"
                result["alias_row_count"] = conn.execute(f'SELECT COUNT(*) FROM "{alias}"').fetchone()[0]
    except (sqlite3.Error, OSError, ValueError) as exc:
        result["reason"] = "sqlite_read_failed:" + type(exc).__name__
        return result
    post_state = _unsafe_live_sqlite_state(path)
    try:
        after = path.stat()
    except OSError:
        result["reason"] = "sqlite_stat_unavailable_after_read"
        return result
    if post_state or (before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_ino, after.st_size, after.st_mtime_ns):
        result["reason"] = post_state or "concurrent_database_change_requires_snapshot"
        result["row_count"] = None
        if kind == "forward":
            result["alias_row_count"] = None
        return result
    if not result["under_expected_root"]:
        result["reason"] = "outside_expected_persistent_root"
        return result
    result["status"] = "PLACEMENT_AND_LOCAL_INTEGRITY_CHECKED"
    return result


def audit(intake: Path, forward: Path, root: Path) -> dict[str, Any]:
    one = inspect_database(intake, root, "intake")
    two = inspect_database(forward, root, "forward")
    same = intake.resolve() == forward.resolve()
    local = (not same and one["status"] == "PLACEMENT_AND_LOCAL_INTEGRITY_CHECKED"
             and two["status"] == "PLACEMENT_AND_LOCAL_INTEGRITY_CHECKED")
    return {
        "kind": "NIJA_LEAD_STORAGE_READONLY_PREFLIGHT_V1",
        "intake": one,
        "forwarding": two,
        "separate_databases": not same,
        "local_placement_and_integrity": "checked" if local else "UNVERIFIED",
        "provider_disk_mount_and_retention": "UNVERIFIED_EXTERNAL_EVIDENCE_REQUIRED",
        "off_host_immutable_backup": "UNVERIFIED_EXTERNAL_EVIDENCE_REQUIRED",
        "independent_isolated_restore": "UNVERIFIED_EXTERNAL_EVIDENCE_REQUIRED",
        "ionos_live_runtime_and_sender": "UNVERIFIED_EXTERNAL_EVIDENCE_REQUIRED",
        "production_pipeline_certified": False,
        "sends_or_mutations_performed": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--intake-db", type=Path, help="Explicit intake DB file. Never created.")
    parser.add_argument("--forward-db", type=Path, help="Explicit forwarding DB file. Never created.")
    parser.add_argument("--expected-persistent-root", type=Path, default=Path("/data"))
    args = parser.parse_args(argv)
    default_intake, default_forward = configured_paths()
    result = audit(args.intake_db or default_intake, args.forward_db or default_forward, args.expected_persistent_root)
    print(json.dumps(result, indent=2, sort_keys=True))
    # An incomplete/unsafe inspection is a failure, never a zero count.
    return 0 if result["local_placement_and_integrity"] == "checked" else 2


if __name__ == "__main__":
    sys.exit(main())
