"""Read-only, non-PII inspection of NIJA's Render lead storage and forwarding.

Run inside the running production instance; never run on an Actions checkout or
build container to infer production data. No external requests or database writes.
"""
from __future__ import annotations

import json
import os
import sqlite3
import urllib.parse
from pathlib import Path
from typing import Callable, Mapping


def _sqlite_summary(path: Path, *, forward: bool = False) -> dict:
    summary: dict = {"exists": path.is_file(), "schema_valid": False, "row_count": None}
    if not summary["exists"]:
        return summary
    try:
        source = path.resolve(strict=True)
        if not source.is_file():
            return summary
        # Never attach SQLite to a live WAL database: even mode=ro may create
        # -shm/-wal files, while immutable=1 could silently omit committed WAL.
        # Inspect the header without SQLite first and fail closed for WAL.
        if source.with_name(source.name + "-journal").exists():
            summary["read_error"] = "rollback_journal_requires_offline_snapshot"
            return summary
        if source.with_name(source.name + "-wal").exists() or source.with_name(source.name + "-shm").exists():
            summary["read_error"] = "wal_database_requires_offline_snapshot"
            return summary
        with source.open("rb") as header_file:
            header = header_file.read(100)
        if len(header) < 100 or header[:16] != b"SQLite format 3\x00":
            summary["read_error"] = "sqlite_header_invalid"
            return summary
        if header[18] == 2 or header[19] == 2:
            summary["read_error"] = "wal_database_requires_offline_snapshot"
            return summary
        # immutable=1 guarantees SQLite will not create journal sidecars.
        # This is a diagnostic only, never proof of a consistent live backup.
        with sqlite3.connect(source.as_uri() + "?mode=ro&immutable=1", uri=True, timeout=3) as db:
            db.execute("PRAGMA query_only=ON")
            # Prevent a huge/corrupt database from making this unbounded.
            budget = [0]
            def limited() -> int:
                budget[0] += 1
                return int(budget[0] > 5000)
            db.set_progress_handler(limited, 1000)
            table = "website_lead_forwarding" if forward else "website_leads"
            required = {"event_key", "state"} if forward else {"event_key", "form_name", "email", "received_at"}
            cols = {row[1] for row in db.execute("PRAGMA table_info(" + table + ")")}
            summary["schema_valid"] = required.issubset(cols)
            if summary["schema_valid"]:
                summary["row_count"] = int(db.execute("SELECT COUNT(*) FROM " + table).fetchone()[0])
    except (OSError, sqlite3.Error, RuntimeError, ValueError):
        summary["read_error"] = "read_only_inspection_failed"
    return summary


def _on_disk(path: Path, disk: Path, mounted: bool) -> bool:
    if not mounted:
        return False
    try:
        return path.resolve().is_relative_to(disk.resolve())
    except (OSError, RuntimeError):
        return False


def inspect(*, environ: Mapping[str, str] | None = None,
            disk: Path = Path("/data"),
            app_default: Path = Path("/app/data/nija_outreach.sqlite3"),
            mount_check: Callable[[Path], bool] | None = None) -> dict:
    env = os.environ if environ is None else environ
    source_key = next((key for key in ("NIJA_LEAD_DB_PATH", "NIJA_OUTREACH_DB_PATH")
                       if env.get(key)), "default")
    active = (Path(str(env[source_key]).strip()) if source_key != "default"
              else app_default)
    disk_mounted = bool((mount_check or (lambda p: p.is_mount()))(disk))
    disk_candidate = disk / "nija_outreach.sqlite3"
    candidates = [("active", active), ("app_default", app_default),
                  ("disk_candidate", disk_candidate)]
    if env.get("NIJA_OUTREACH_DB_PATH"):
        candidates.append(("outreach_override", Path(str(env["NIJA_OUTREACH_DB_PATH"]).strip())))
    seen: set[Path] = set()
    stores = {}
    for name, path in candidates:
        canonical = path.resolve()
        if canonical in seen:
            continue
        seen.add(canonical)
        inspection = _sqlite_summary(path)
        if inspection["exists"]:
            stores[name] = {**inspection, "on_mounted_disk": _on_disk(path, disk, disk_mounted)}

    lead = _sqlite_summary(active)
    lead_durable = _on_disk(active, disk, disk_mounted)
    forward_key = str(env.get("NIJA_LEAD_FORWARD_DB_PATH") or "").strip()
    forward = Path(forward_key) if forward_key else (
        disk / "nija_lead_forwarding.sqlite3" if disk.is_dir() else active)
    forwarding = _sqlite_summary(forward, forward=True)
    forwarding_durable = _on_disk(forward, disk, disk_mounted)
    token_configured = bool(str(env.get("NIJA_LEAD_WEBHOOK_TOKEN")
                            or env.get("NIJA_OUTREACH_SERVICE_TOKEN") or "").strip())
    target = str(env.get("NIJA_LEAD_FORWARD_URL") or "").strip()
    try:
        url = urllib.parse.urlsplit(target)
        valid_https = bool(target and url.scheme == "https" and url.hostname
                           and not url.username and not url.password and url.port != 0)
        hostname = url.hostname if valid_https else None
    except ValueError:
        valid_https = False
        hostname = None
    destination = ("zapier" if hostname == "hooks.zapier.com" else
                   "other_https" if valid_https else "missing_or_invalid")

    issues = []
    if not disk_mounted:
        issues.append("render_persistent_disk_not_verified")
    if not lead["exists"] or not lead["schema_valid"] or lead["row_count"] is None:
        issues.append("lead_database_not_verified")
    if not lead_durable:
        issues.append("active_lead_database_outside_verified_disk")
    if len(stores) > 1:
        issues.append("multiple_potential_lead_databases_require_reconciliation")
    if not forwarding["exists"] or not forwarding["schema_valid"] or forwarding["row_count"] is None:
        issues.append("forward_history_not_verified")
    if not forwarding_durable:
        issues.append("forward_history_outside_verified_disk")
    if not token_configured:
        issues.append("lead_intake_auth_not_configured")
    if not valid_https:
        issues.append("forwarding_https_endpoint_not_configured")

    return {
        "mode": "READ_ONLY", "production_certified": False,
        "site_to_render_verified": False, "authorized_zapier_account_verified": False,
        "customer_data_exposed": False, "network_calls_made": False,
        "lead_db_config_source": source_key,
        "persistent_disk_mounted": disk_mounted,
        "lead_db_on_mounted_disk": lead_durable,
        "lead_database": lead,
        "other_candidate_databases": {key: value for key, value in stores.items() if key != "active"},
        "forward_db_on_mounted_disk": forwarding_durable,
        "forwarding_history": forwarding,
        "lead_intake_auth_configured": token_configured,
        "forwarding_https_configured": valid_https,
        "forwarding_destination_category": destination,
        "issues": issues,
    }


if __name__ == "__main__":
    print(json.dumps(inspect(), sort_keys=True))
