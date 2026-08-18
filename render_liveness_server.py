"""Minimal Render liveness and NIJA trading-readiness endpoints.

``/healthz`` reports process liveness so Render can complete a zero-downtime
deployment while the replacement waits fail-closed for writer authority.
``/readyz`` reports strict trading readiness. Because this HTTP server is a
separate process, it reads an atomic state file published by the trading process
instead of relying on stale inherited environment variables.
"""

from __future__ import annotations

import json
import os
import signal
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional

_STARTED_AT = time.time()
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8").strip()
    except (FileNotFoundError, PermissionError, OSError):
        return None


def _bytes_to_mb(value: Optional[str]) -> Optional[float]:
    if value is None or value == "max":
        return None
    try:
        return round(max(0, int(value)) / (1024 * 1024), 3)
    except (TypeError, ValueError):
        return None


def _parse_proc_status(path: Path) -> dict[str, str]:
    raw = _read_text(path)
    if raw is None:
        return {}
    parsed: dict[str, str] = {}
    for line in raw.splitlines():
        key, separator, value = line.partition(":")
        if separator:
            parsed[key.strip()] = value.strip()
    return parsed


def _runtime_process_snapshot(proc_root: Path = Path("/proc")) -> dict[str, object]:
    """Return bounded runtime RSS/thread telemetry without importing psutil."""
    try:
        candidates = sorted(
            (path for path in proc_root.iterdir() if path.name.isdigit()),
            key=lambda path: int(path.name),
        )
    except (FileNotFoundError, PermissionError, OSError):
        return {}

    for process_dir in candidates:
        try:
            command = (process_dir / "cmdline").read_bytes().replace(b"\0", b" ").decode(
                "utf-8", errors="replace"
            )
        except (FileNotFoundError, PermissionError, OSError):
            continue
        if "canonical_runtime_launcher_v26.py" not in command:
            continue

        status = _parse_proc_status(process_dir / "status")
        rss_text = str(status.get("VmRSS", "0 kB")).split()[0]
        try:
            rss_mb = round(max(0, int(rss_text)) / 1024, 3)
        except (TypeError, ValueError):
            rss_mb = None
        try:
            thread_count: Optional[int] = max(0, int(status.get("Threads", "0")))
        except (TypeError, ValueError):
            thread_count = None
        return {
            "runtime_pid": int(process_dir.name),
            "runtime_rss_mb": rss_mb,
            "runtime_threads": thread_count,
        }
    return {}


def _memory_snapshot(
    cgroup_root: Path = Path("/sys/fs/cgroup"),
    proc_root: Path = Path("/proc"),
) -> dict[str, object]:
    """Read cgroup v2/v1 memory pressure plus canonical runtime RSS."""
    current_raw = _read_text(cgroup_root / "memory.current")
    limit_raw = _read_text(cgroup_root / "memory.max")
    peak_raw = _read_text(cgroup_root / "memory.peak")
    events_raw = _read_text(cgroup_root / "memory.events")

    if current_raw is None:
        legacy = cgroup_root / "memory"
        current_raw = _read_text(legacy / "memory.usage_in_bytes")
        limit_raw = _read_text(legacy / "memory.limit_in_bytes")
        peak_raw = _read_text(legacy / "memory.max_usage_in_bytes")
        events_raw = _read_text(legacy / "memory.failcnt")

    current_mb = _bytes_to_mb(current_raw)
    limit_mb = _bytes_to_mb(limit_raw)
    peak_mb = _bytes_to_mb(peak_raw)
    details: dict[str, object] = {
        "memory_current_mb": current_mb,
        "memory_limit_mb": limit_mb,
        "memory_peak_mb": peak_mb,
        "memory_utilization_percent": (
            round(current_mb * 100 / limit_mb, 2)
            if current_mb is not None and limit_mb not in {None, 0}
            else None
        ),
    }

    events: dict[str, int] = {}
    if events_raw is not None:
        for line in events_raw.splitlines():
            parts = line.split()
            if len(parts) == 2:
                try:
                    events[parts[0]] = int(parts[1])
                except ValueError:
                    continue
        if not events and events_raw.isdigit():
            events["failcnt"] = int(events_raw)
    details["memory_oom_count"] = events.get("oom", 0)
    details["memory_oom_kill_count"] = events.get("oom_kill", 0)
    details["memory_fail_count"] = events.get("failcnt", 0)
    details.update(_runtime_process_snapshot(proc_root))
    return details


def _truthy_value(value: Any) -> bool:
    return str(value or "").strip().lower() in _TRUE


def _truthy(name: str, default: str = "") -> bool:
    return _truthy_value(os.environ.get(name, default))


def _is_render_runtime() -> bool:
    if _truthy("RENDER"):
        return True
    return any(
        str(os.environ.get(name, "") or "").strip()
        for name in (
            "RENDER_SERVICE_ID",
            "RENDER_SERVICE_NAME",
            "RENDER_INSTANCE_ID",
            "RENDER_GIT_COMMIT",
        )
    )


def _state_path() -> Path:
    return Path(
        str(
            os.environ.get(
                "NIJA_RENDER_READINESS_STATE_FILE",
                "/tmp/nija_render_readiness.json",
            )
            or "/tmp/nija_render_readiness.json"
        )
    ).expanduser()


def _read_shared_state() -> tuple[Optional[dict[str, Any]], Optional[float], str]:
    path = _state_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return None, None, "invalid_payload"
        timestamp = float(payload.get("timestamp") or 0.0)
        age = max(0.0, time.time() - timestamp) if timestamp > 0 else float("inf")
        try:
            max_age = max(
                2.0,
                float(os.environ.get("NIJA_RENDER_READINESS_MAX_AGE_S", "10") or "10"),
            )
        except (TypeError, ValueError):
            max_age = 10.0
        if age > max_age:
            return None, age, "stale"
        return payload, age, "ok"
    except FileNotFoundError:
        return None, None, "missing"
    except Exception as exc:
        return None, None, f"read_error:{type(exc).__name__}"


def _secondary_policy_from_env() -> str:
    explicit = str(os.environ.get("NIJA_SECONDARY_VENUE_POLICY", "") or "").strip().lower()
    if explicit in {"broker_local", "global_all_required", "optional"}:
        return explicit
    return "broker_local" if _truthy("NIJA_REQUIRE_SECONDARY_VENUES_READY") else "optional"


def _environment_snapshot() -> dict[str, Any]:
    return {
        "state": os.environ.get("NIJA_RUNTIME_TRADING_STATE", "OFF"),
        "writer_authority": os.environ.get("NIJA_RUNTIME_EXECUTION_AUTHORITY", "0"),
        "reconciliation_complete": os.environ.get(
            "NIJA_RECONCILIATION_COMPLETE", "false"
        ),
        "reconciliation_status": os.environ.get(
            "NIJA_RECONCILIATION_STATUS", "PENDING"
        ),
        "position_sync_ready": os.environ.get(
            "NIJA_POSITION_SYNC_ACTIVATION_READY", "0"
        ),
        "runtime_release_id": os.environ.get("NIJA_RUNTIME_RELEASE_ID", "unknown"),
        "strict_secondary_venues": os.environ.get(
            "NIJA_REQUIRE_SECONDARY_VENUES_READY", "false"
        ),
        "secondary_venue_policy": _secondary_policy_from_env(),
        "required_venues_ready": os.environ.get("NIJA_REQUIRED_VENUES_READY", "0"),
        "global_trading_ready": os.environ.get(
            "NIJA_GLOBAL_TRADING_READY",
            os.environ.get("NIJA_MULTI_BROKER_TRADING_READY", "0"),
        ),
        "multi_broker_trading_ready": os.environ.get(
            "NIJA_MULTI_BROKER_TRADING_READY", "0"
        ),
        "required_venues": os.environ.get(
            "NIJA_REQUIRED_LIVE_VENUES", "coinbase,okx"
        ),
        "required_venues_missing": os.environ.get(
            "NIJA_REQUIRED_VENUES_MISSING", ""
        ),
        "active_live_venues": os.environ.get("NIJA_ACTIVE_LIVE_VENUES", ""),
        "degraded_live_venues": os.environ.get("NIJA_DEGRADED_LIVE_VENUES", ""),
        "coinbase_activation_state": os.environ.get(
            "NIJA_COINBASE_ACTIVATION_STATE", "unknown"
        ),
        "coinbase_connected": os.environ.get("NIJA_COINBASE_CONNECTED", "0"),
        "coinbase_trading_ready": os.environ.get(
            "NIJA_COINBASE_TRADING_READY", "0"
        ),
        "coinbase_balance_observed": os.environ.get(
            "NIJA_COINBASE_BALANCE_OBSERVED", "0"
        ),
        "coinbase_funding_status": os.environ.get(
            "NIJA_COINBASE_FUNDING_STATUS", "unobserved"
        ),
        "coinbase_spendable_quote": os.environ.get(
            "NIJA_COINBASE_SPENDABLE_QUOTE", "unobserved"
        ),
        "okx_activation_state": os.environ.get(
            "NIJA_OKX_ACTIVATION_STATE", "unknown"
        ),
        "okx_connected": os.environ.get("NIJA_OKX_CONNECTED", "0"),
        "okx_trading_ready": os.environ.get("NIJA_OKX_TRADING_READY", "0"),
        "okx_balance_observed": os.environ.get("NIJA_OKX_BALANCE_OBSERVED", "0"),
        "okx_funding_status": os.environ.get("NIJA_OKX_FUNDING_STATUS", "unobserved"),
        "okx_spendable_quote": os.environ.get("NIJA_OKX_SPENDABLE_QUOTE", "unobserved"),
        "commit": os.environ.get("GIT_COMMIT_SHORT", "unknown"),
    }


def _safe_render_startup_snapshot() -> dict[str, Any]:
    required = os.environ.get("NIJA_REQUIRED_LIVE_VENUES", "coinbase,okx")
    return {
        "state": "OFF",
        "writer_authority": "0",
        "reconciliation_complete": "0",
        "reconciliation_status": "PENDING",
        "position_sync_ready": "0",
        "runtime_release_id": os.environ.get("NIJA_RUNTIME_RELEASE_ID", "unknown"),
        "strict_secondary_venues": os.environ.get(
            "NIJA_REQUIRE_SECONDARY_VENUES_READY", "true"
        ),
        "secondary_venue_policy": _secondary_policy_from_env(),
        "required_venues_ready": "0",
        "global_trading_ready": "0",
        "multi_broker_trading_ready": "0",
        "required_venues": required,
        "required_venues_missing": required,
        "active_live_venues": "",
        "degraded_live_venues": "",
        "coinbase_activation_state": "unobserved",
        "coinbase_connected": "0",
        "coinbase_trading_ready": "0",
        "coinbase_balance_observed": "0",
        "coinbase_funding_status": "unobserved",
        "coinbase_spendable_quote": "unobserved",
        "okx_activation_state": "unobserved",
        "okx_connected": "0",
        "okx_trading_ready": "0",
        "okx_balance_observed": "0",
        "okx_funding_status": "unobserved",
        "okx_spendable_quote": "unobserved",
        "commit": os.environ.get("GIT_COMMIT_SHORT", "unknown"),
    }


def _normalised_policy(snapshot: dict[str, Any]) -> str:
    explicit = str(snapshot.get("secondary_venue_policy") or "").strip().lower()
    if explicit in {"broker_local", "global_all_required", "optional"}:
        return explicit
    return "broker_local" if _truthy_value(snapshot.get("strict_secondary_venues")) else "optional"


def _global_ready_from_snapshot(snapshot: dict[str, Any], required_ready: bool) -> bool:
    for key in ("global_trading_ready", "multi_broker_trading_ready"):
        if key in snapshot:
            return _truthy_value(snapshot.get(key))
    active = str(snapshot.get("active_live_venues") or "").strip().strip(",")
    if active:
        return True
    # Backward compatibility for old state files that predate broker-local fields.
    return required_ready


def _readiness() -> tuple[bool, dict[str, object]]:
    shared, age, shared_status = _read_shared_state()
    if shared is not None:
        snapshot = shared
        source = "shared_file"
    elif _is_render_runtime():
        # The early server may inherit stale dashboard variables. Until the live
        # trading process publishes a fresh file, Render readiness is always false.
        snapshot = _safe_render_startup_snapshot()
        source = "safe_render_startup"
    else:
        snapshot = _environment_snapshot()
        source = "process_env"

    state = str(snapshot.get("state") or "OFF")
    writer_raw = str(snapshot.get("writer_authority") or "0")
    writer_ready = _truthy_value(writer_raw)
    strict = _truthy_value(snapshot.get("strict_secondary_venues"))
    policy = _normalised_policy(snapshot)
    required_ready = _truthy_value(snapshot.get("required_venues_ready"))
    global_ready = _global_ready_from_snapshot(snapshot, required_ready)
    reconciliation_reported = any(
        key in snapshot
        for key in ("reconciliation_complete", "reconciliation_status")
    )
    reconciliation_complete = _truthy_value(snapshot.get("reconciliation_complete"))
    reconciliation_status = str(
        snapshot.get("reconciliation_status") or "PENDING"
    ).strip().upper()
    reconciliation_ready = (
        reconciliation_complete
        and reconciliation_status in {"CLEAN", "CLEAN_START"}
    ) if reconciliation_reported else True
    position_sync_reported = "position_sync_ready" in snapshot
    position_sync_ready = (
        _truthy_value(snapshot.get("position_sync_ready"))
        if position_sync_reported
        else True
    )

    if policy == "global_all_required":
        venue_policy_ready = required_ready
    else:
        # broker_local and optional policies require at least one independently
        # executable live venue but do not require every secondary venue.
        venue_policy_ready = global_ready

    ready = (
        state == "LIVE_ACTIVE"
        and writer_ready
        and venue_policy_ready
        and reconciliation_ready
        and position_sync_ready
    )

    details: dict[str, object] = {
        "status": "ready" if ready else "not_ready",
        "state": state,
        "writer_authority": writer_raw,
        "reconciliation_complete": reconciliation_complete,
        "reconciliation_status": reconciliation_status,
        "reconciliation_ready": reconciliation_ready,
        "position_sync_ready": position_sync_ready,
        "runtime_release_id": snapshot.get("runtime_release_id", "unknown"),
        "strict_secondary_venues": strict,
        "secondary_venue_policy": policy,
        "required_venues_ready": required_ready,
        "global_trading_ready": global_ready,
        "venue_policy_ready": venue_policy_ready,
        "required_venues": snapshot.get("required_venues", "coinbase,okx"),
        "required_venues_missing": snapshot.get("required_venues_missing", ""),
        "active_live_venues": snapshot.get("active_live_venues", ""),
        "degraded_live_venues": snapshot.get("degraded_live_venues", ""),
        "coinbase_activation_state": snapshot.get(
            "coinbase_activation_state", "unknown"
        ),
        "coinbase_connected": snapshot.get("coinbase_connected", "0"),
        "coinbase_trading_ready": snapshot.get("coinbase_trading_ready", "0"),
        "coinbase_balance_observed": snapshot.get("coinbase_balance_observed", "0"),
        "coinbase_funding_status": snapshot.get("coinbase_funding_status", "unobserved"),
        "coinbase_spendable_quote": snapshot.get("coinbase_spendable_quote", "unobserved"),
        "okx_activation_state": snapshot.get("okx_activation_state", "unknown"),
        "okx_connected": snapshot.get("okx_connected", "0"),
        "okx_trading_ready": snapshot.get("okx_trading_ready", "0"),
        "okx_balance_observed": snapshot.get("okx_balance_observed", "0"),
        "okx_funding_status": snapshot.get("okx_funding_status", "unobserved"),
        "okx_spendable_quote": snapshot.get("okx_spendable_quote", "unobserved"),
        "readiness_source": source,
        "shared_state_status": shared_status,
        "shared_state_age_seconds": round(age, 3) if age is not None else None,
        "uptime_seconds": round(time.time() - _STARTED_AT, 3),
        "commit": snapshot.get("commit", os.environ.get("GIT_COMMIT_SHORT", "unknown")),
    }
    details.update(_memory_snapshot())
    return ready, details


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler contract
        if self.path not in {"/", "/health", "/healthz", "/status", "/readyz"}:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        ready, details = _readiness()
        if self.path == "/readyz":
            payload_obj = details
            status_code = 200 if ready else 503
        else:
            payload_obj = dict(details)
            payload_obj["status"] = "alive"
            payload_obj["trading_ready"] = ready
            status_code = 200

        payload = json.dumps(payload_obj, separators=(",", ":")).encode("utf-8")
        try:
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError):
            return

    def log_message(self, fmt: str, *args: object) -> None:
        return


def main() -> int:
    try:
        port = int(os.environ.get("PORT", "5000") or "5000")
    except ValueError:
        port = 5000

    server = ThreadingHTTPServer(("0.0.0.0", port), _Handler)
    server.daemon_threads = True
    server.allow_reuse_address = True

    stop = threading.Event()

    def _shutdown(signum: int, frame: object) -> None:
        del signum, frame
        if not stop.is_set():
            stop.set()
            threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)
    print(
        f"RENDER_EARLY_LIVENESS_READY port={port} readiness_path=/readyz "
        f"state_file={_state_path()}",
        flush=True,
    )
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
