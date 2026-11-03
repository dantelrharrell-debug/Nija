"""Read-only, PII-free reconciliation of NIJA's durable lead delivery state.

Run on an authenticated existing Render instance. No writes, external calls,
lead replays, CRM updates, trading operations, or credential disclosures.
An aggregate read does not independently certify downstream delivery.
"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
import urllib.parse
from pathlib import Path
from typing import Callable, Mapping

REVIEW_CATEGORIES = frozenset(("HTTP_422_email", "HTTP_422_phone", "HTTP_422_review"))
LEAD_STATES = frozenset(("synced", "pending", "needs_review"))
FORWARD_STATES = frozenset(("pending", "sending", "sent"))


def _on_disk(path: Path, mount: Path, mounted: bool) -> bool:
    try:
        return bool(mounted and path.resolve().is_relative_to(mount.resolve()))
    except (OSError, RuntimeError):
        return False


def _read_counts(path: Path, *, forwarding: bool) -> dict:
    try:
        resolved = path.resolve()
        if not resolved.is_file():
            return {"status": "missing"}
        if any(Path(str(resolved) + suffix).exists() for suffix in ("-wal", "-shm")):
            return {"status": "live_wal_requires_consistent_snapshot"}
        # An active or hot rollback journal can make immutable=1 read stale data.
        # Refuse rather than treating a potentially inconsistent live read as evidence.
        if Path(str(resolved) + "-journal").exists():
            return {"status": "rollback_journal_requires_consistent_snapshot"}
        with resolved.open("rb") as file:
            header = file.read(100)
        if len(header) < 100 or header[:16] != b"SQLite format 3" + bytes((0,)):
            return {"status": "invalid_sqlite_header"}
        if header[18] == 2 or header[19] == 2:
            return {"status": "wal_mode_requires_consistent_snapshot"}
        with closing(sqlite3.connect(resolved.as_uri() + "?mode=ro&immutable=1", uri=True, timeout=3)) as db:
            db.execute("PRAGMA query_only=ON")
            budget = [0]

            def progress() -> int:
                budget[0] += 1
                return int(budget[0] > 5000)

            db.set_progress_handler(progress, 1000)
            if forwarding:
                cols = {row[1] for row in db.execute("PRAGMA table_info(website_lead_forwarding)")}
                if not {"event_key", "state"}.issubset(cols):
                    return {"status": "schema_unverified"}
                states = {key: 0 for key in sorted(FORWARD_STATES)}
                states["other"] = 0
                for state, count in db.execute("SELECT state, COUNT(*) FROM website_lead_forwarding GROUP BY state"):
                    states[state if state in FORWARD_STATES else "other"] += int(count)
                return {"status": "read_only_counts", "forwarding_states": states}
            cols = {row[1] for row in db.execute("PRAGMA table_info(website_leads)")}
            if not {"event_key", "email", "received_at"}.issubset(cols):
                return {"status": "schema_unverified"}
            events, unique, latest = db.execute(
                "SELECT COUNT(*), COUNT(DISTINCT NULLIF(lower(trim(email)), '')), "
                "MAX(received_at) FROM website_leads"
            ).fetchone()
            result = {
                "status": "read_only_counts", "lead_events": int(events),
                "unique_emails": int(unique), "last_received_at": latest,
            }
            crm_cols = {row[1] for row in db.execute("PRAGMA table_info(website_lead_crm_sync)")}
            if {"state", "last_error_code"}.issubset(crm_cols):
                states = {key: 0 for key in sorted(LEAD_STATES)}
                states["other"] = 0
                for state, count in db.execute(
                    "SELECT state, COUNT(*) FROM website_lead_crm_sync GROUP BY state"
                ):
                    states[state if state in LEAD_STATES else "other"] += int(count)
                reasons = {}
                for code, count in db.execute(
                    "SELECT last_error_code, COUNT(*) FROM website_lead_crm_sync "
                    "WHERE state='needs_review' GROUP BY last_error_code"
                ):
                    category = code if code in REVIEW_CATEGORIES else "other"
                    reasons[category] = reasons.get(category, 0) + int(count)
                result["crm_state_counts"] = states
                result["crm_review_categories"] = reasons
            else:
                result["crm_state"] = "schema_unverified"
            return result
    except (OSError, sqlite3.Error, RuntimeError, ValueError, TypeError):
        return {"status": "unverified"}


def inspect(*, environ: Mapping[str, str] | None = None,
            disk: Path = Path("/data"),
            app_default: Path = Path("/app/data/nija_outreach.sqlite3"),
            mount_check: Callable[[Path], bool] | None = None) -> dict:
    env = os.environ if environ is None else environ
    # Match render_lead_intake._db_path exactly: select the first TRUTHY raw
    # override, then strip it. A whitespace-only primary value must not fall
    # through to the secondary override, and "~" is never expanded at runtime.
    raw_active = str(env.get("NIJA_LEAD_DB_PATH") or env.get("NIJA_OUTREACH_DB_PATH")
                     or app_default)
    active_value = raw_active.strip()
    active = Path(active_value) if active_value else None
    override = str(env.get("NIJA_LEAD_FORWARD_DB_PATH") or "").strip()
    forward = (Path(override) if override else
               disk / "nija_lead_forwarding.sqlite3" if disk.is_dir() else active)
    mounted = bool((mount_check or (lambda path: path.is_mount()))(disk))
    url = str(env.get("NIJA_LEAD_FORWARD_URL") or "").strip()
    try:
        parsed = urllib.parse.urlsplit(url)
        https_ok = bool(url and parsed.scheme == "https" and parsed.hostname
                        and not parsed.username and not parsed.password and parsed.port != 0)
        category = ("zapier" if https_ok and parsed.hostname == "hooks.zapier.com"
                    else "other_https" if https_ok else "missing_or_invalid")
    except ValueError:
        https_ok = False
        category = "missing_or_invalid"
    return {
        "mode": "READ_ONLY", "production_pipeline_certified": False,
        "bulk_replay_authorized": False, "zapier_account_verified": False,
        "storage_mount_verified": mounted,
        "lead_db_on_mounted_disk": _on_disk(active, disk, mounted) if active else False,
        "forward_history_on_mounted_disk": _on_disk(forward, disk, mounted) if forward else False,
        "lead_database": (_read_counts(active, forwarding=False) if active else
                          {"status": "invalid_runtime_path"}),
        "forward_history": (_read_counts(forward, forwarding=True) if forward else
                            {"status": "invalid_runtime_path"}),
        "configured_forwarding_https": https_ok,
        "configured_forwarding_category": category,
        "configured_intake_auth": bool(str(env.get("NIJA_LEAD_WEBHOOK_TOKEN")
                                          or env.get("NIJA_OUTREACH_SERVICE_TOKEN") or "").strip()),
        "customer_information_exposed": False,
        "data_mutated": False, "network_requests_sent": False,
    }


if __name__ == "__main__":
    print(json.dumps(inspect(), sort_keys=True))
