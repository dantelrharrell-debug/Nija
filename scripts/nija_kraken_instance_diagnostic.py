"""Bounded stdin-only Render inspection; no imports of NIJA or broker requests.

Run with python -B -S on the authorized service. Only fixed diagnostic labels,
credential-presence booleans and public source/deployment digests leave it.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import time

SERVICE = "srv-d98dsr5aeets73fpbaqg"
BASELINE = "cd174134ff4a61824322cecc042d1548bd938a34"
MAX_BYTES = 4 * 1024 * 1024
SIGNALS = {
    "INVALID_API_KEY": ("eapi:invalid key",),
    "INVALID_SIGNATURE": ("eapi:invalid signature",),
    "NONCE_REJECTED": ("eapi:invalid nonce",),
    "PERMISSION_DENIED": ("egeneral:permission denied", "eapi:invalid permission"),
    "ACCOUNT_DISABLED": ("eaccount:account disabled",),
    "TEMPORARY_LOCKOUT": ("eapi:temporary lockout",),
    "CREDENTIAL_PAIR_MISSING_OR_INCOMPLETE": ("credential_pair_missing_or_incomplete",),
    "INVALID_SECRET_ENCODING": ("invalid_secret_encoding",),
    "WRITER_AUTHORITY_UNAVAILABLE": (
        "kraken_nonce_startup_blocked", "canonical process writer authority unavailable",
    ),
    "NONCE_LEASE_UNAVAILABLE": ("nonce authority unavailable",),
    "DNS_FAILURE": ("nameresolutionerror", "name or service not known"),
    "TLS_FAILURE": ("sslerror", "certificate_verify_failed"),
    "TRANSPORT_TIMEOUT": ("readtimeout", "connecttimeout"),
    "TRANSPORT_DISCONNECTED": ("remotedisconnected", "connection aborted"),
    "COLLECTOR_MISSING": ("collector_installed=false", "producer_status=collector_missing"),
    "PRICE_CLIENT_DISCONNECTED": ("kraken api not connected",),
    "AUTHENTICATED_BALANCE_FAILED": ("kraken connection test failed",),
    "AUTHENTICATED_CONNECTION_SUCCEEDED": ("successfully connected to kraken",),
}
STAMP = re.compile(r"(\d{4}-\d\d-\d\d[ T]\d\d:\d\d:\d\d)")


def classify_log(text: str, *, since: float) -> dict[str, int]:
    """Count only recognized labels on timestamped current-process log lines."""
    counts: Counter[str] = Counter()
    for line in text.splitlines():
        match = STAMP.search(line)
        if match is None:
            continue
        try:
            stamp = datetime.fromisoformat(match[1]).replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            continue
        if stamp < since:
            continue
        lowered = line.lower()
        for label, fragments in SIGNALS.items():
            if any(fragment in lowered for fragment in fragments):
                counts[label] += 1
    return dict(counts)


def _read_regular(path: Path, limit: int, *, tail: bool = False) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("regular_file_required")
        if tail:
            os.lseek(fd, max(0, info.st_size - limit), os.SEEK_SET)
        elif info.st_size > limit:
            raise ValueError("file_budget_exceeded")
        return os.read(fd, limit)
    finally:
        os.close(fd)


def inspect_instance() -> dict:
    """Inspect the exact baseline instance without touching runtime authority."""
    if os.environ.get("RENDER_SERVICE_ID") != SERVICE:
        return {"status": "BLOCKED", "reason": "service_identity_mismatch"}
    commit = os.environ.get("RENDER_GIT_COMMIT", "")
    if commit != BASELINE:
        return {"status": "BLOCKED", "reason": "baseline_commit_mismatch"}
    result = {
        "status": "DIAGNOSTIC_ONLY", "service_id": SERVICE, "commit": commit,
        "observed_at_epoch": time.time(), "broker_requests": False,
        "state_changed": False, "allow_new_orders": False,
        "processes": [], "log_signals": {}, "source_sha256": {}, "failures": [],
    }
    try:
        uptime = float(Path("/proc/uptime").read_text().split()[0])
        boot = time.time() - uptime
        ticks = os.sysconf("SC_CLK_TCK")
        for process in Path("/proc").iterdir():
            if not process.name.isdigit() or int(process.name) == os.getpid():
                continue
            try:
                args = (process / "cmdline").read_bytes().split(b"\0")
                if not any(arg in {
                    b"main.py", b"/app/main.py", b"bot.py", b"bot.bot_main",
                    b"/app/scripts/canonical_runtime_launcher_v26.py",
                } for arg in args):
                    continue
                fields = (process / "stat").read_text().rsplit(")", 1)[1].split()
                started = boot + int(fields[19]) / ticks
                environment = dict(
                    item.split(b"=", 1) for item in (process / "environ").read_bytes().split(b"\0")
                    if b"=" in item
                )
                presence = {
                    name: bool(environment.get(name.encode(), b"").strip())
                    for name in (
                        "KRAKEN_PLATFORM_API_KEY", "KRAKEN_PLATFORM_API_SECRET",
                        "KRAKEN_API_KEY", "KRAKEN_API_SECRET", "REDIS_URL", "NIJA_REDIS_URL",
                    )
                }
                result["processes"].append({"started_at_epoch": started, "configured": presence})
            except (OSError, ValueError, IndexError):
                result["failures"].append("runtime_process_inspection_failed")
    except (OSError, ValueError):
        result["failures"].append("process_inventory_unavailable")
    if result["processes"]:
        since = min(row["started_at_epoch"] for row in result["processes"]) - 1
        counts: Counter[str] = Counter()
        for relative in ("nija.log", "nija.log.1", "data/nija.log", "logs/nija.log"):
            path = Path("/app") / relative
            try:
                text = _read_regular(path, MAX_BYTES, tail=True).decode("utf-8", errors="replace")
                counts.update(classify_log(text, since=since))
            except FileNotFoundError:
                continue
            except (OSError, ValueError):
                result["failures"].append("runtime_log_read_failed")
        result["log_signals"] = dict(counts)
        if not counts:
            result["failures"].append("current_process_log_evidence_unavailable")
    else:
        result["failures"].append("canonical_runtime_process_not_found")
    for relative in (
        "bot/broker_manager.py", "bot/canonical_broker_startup_convergence_v24.py",
        "scripts/render_entrypoint.sh", "scripts/production_bootstrap.sh", "start.sh",
    ):
        try:
            result["source_sha256"][relative] = hashlib.sha256(
                _read_regular(Path("/app") / relative, MAX_BYTES)
            ).hexdigest()
        except (OSError, ValueError):
            result["failures"].append("runtime_source_read_failed")
    return result


if __name__ == "__main__":
    print(json.dumps(inspect_instance(), sort_keys=True))
