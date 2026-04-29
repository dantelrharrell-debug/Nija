"""Helpers for identifying the current runtime instance in logs and locks."""

from __future__ import annotations

import json
import os
import socket
import time


def _runtime_boot_id() -> str:
    """Return a stable per-process boot id for the current runtime."""
    boot_id = os.environ.get("NIJA_INSTANCE_BOOT_ID", "").strip()
    if boot_id:
        return boot_id
    boot_id = f"{int(time.time() * 1000)}-{os.getpid()}"
    os.environ["NIJA_INSTANCE_BOOT_ID"] = boot_id
    return boot_id


def current_instance_identity() -> dict[str, str]:
    """Return normalized instance metadata for the current process."""
    hostname = socket.gethostname().strip() or "unknown-host"
    container_id = os.environ.get("HOSTNAME", "").strip() or hostname
    deployment_id = os.environ.get("RAILWAY_DEPLOYMENT_ID", "").strip()
    replica_id = (
        os.environ.get("RAILWAY_REPLICA_ID", "").strip()
        or os.environ.get("RAILWAY_REPLICA_NAME", "").strip()
    )
    service_id = os.environ.get("RAILWAY_SERVICE_ID", "").strip()
    pid = str(os.getpid())
    boot_id = _runtime_boot_id()
    instance_id = deployment_id or replica_id or container_id or f"{hostname}-{pid}"
    return {
        "instance_id": instance_id,
        "hostname": hostname,
        "container_id": container_id,
        "deployment_id": deployment_id,
        "replica_id": replica_id,
        "service_id": service_id,
        "pid": pid,
        "boot_id": boot_id,
    }


def format_instance_identity(identity: dict[str, str] | None = None) -> str:
    """Render instance metadata as a compact lock-safe string."""
    identity = identity or current_instance_identity()
    ordered_keys = (
        "instance_id",
        "hostname",
        "pid",
        "container_id",
        "deployment_id",
        "replica_id",
        "service_id",
        "boot_id",
    )
    key_map = {
        "instance_id": "instance",
        "hostname": "host",
        "container_id": "container",
        "deployment_id": "deployment",
        "replica_id": "replica",
        "service_id": "service",
        "pid": "pid",
        "boot_id": "boot",
    }
    parts: list[str] = []
    for key in ordered_keys:
        value = str(identity.get(key, "") or "").strip()
        if value:
            parts.append(f"{key_map[key]}={value}")
    return ";".join(parts)


def parse_distributed_lock_holder(raw_holder: str) -> dict[str, str]:
    """Parse current and legacy Redis lock-holder formats into metadata."""
    raw_value = str(raw_holder or "").strip()
    token = ""
    owner_raw = raw_value
    if ":" in raw_value:
        token, owner_raw = raw_value.split(":", 1)

    parsed: dict[str, str] = {
        "raw": raw_value,
        "token": token,
        "owner_raw": owner_raw,
        "format": "empty" if not raw_value else "unknown",
    }

    if not owner_raw:
        parsed["display"] = token or "<missing-holder>"
        return parsed

    if "=" in owner_raw:
        parsed["format"] = "kv"
        for fragment in owner_raw.split(";"):
            if "=" not in fragment:
                continue
            key, value = fragment.split("=", 1)
            normalized_key = {
                "instance": "instance_id",
                "host": "hostname",
                "container": "container_id",
                "deployment": "deployment_id",
                "replica": "replica_id",
                "service": "service_id",
                "pid": "pid",
                "boot": "boot_id",
            }.get(key.strip(), key.strip())
            parsed[normalized_key] = value.strip()
    else:
        legacy_parts = owner_raw.split(":")
        if len(legacy_parts) >= 3:
            parsed["format"] = "legacy"
            parsed["hostname"] = legacy_parts[0].strip()
            parsed["pid"] = legacy_parts[1].strip()
            parsed["boot_id"] = ":".join(legacy_parts[2:]).strip()
            parsed["instance_id"] = parsed["hostname"] or owner_raw

    display_identity = {
        "instance_id": parsed.get("instance_id", "") or parsed.get("hostname", "") or owner_raw,
        "hostname": parsed.get("hostname", ""),
        "container_id": parsed.get("container_id", ""),
        "deployment_id": parsed.get("deployment_id", ""),
        "replica_id": parsed.get("replica_id", ""),
        "service_id": parsed.get("service_id", ""),
        "pid": parsed.get("pid", ""),
        "boot_id": parsed.get("boot_id", ""),
    }
    parsed["display"] = format_instance_identity(display_identity)
    return parsed


def inspect_lock_holder(current_identity: dict[str, str], holder_info: dict[str, str]) -> dict[str, object]:
    """Compare the current instance against a parsed lock holder."""
    holder_instance = str(holder_info.get("instance_id", "") or "").strip()
    holder_container = str(holder_info.get("container_id", "") or "").strip()
    holder_hostname = str(holder_info.get("hostname", "") or "").strip()
    holder_deployment = str(holder_info.get("deployment_id", "") or "").strip()
    holder_replica = str(holder_info.get("replica_id", "") or "").strip()
    holder_pid = str(holder_info.get("pid", "") or "").strip()

    current_instance = str(current_identity.get("instance_id", "") or "").strip()
    current_container = str(current_identity.get("container_id", "") or "").strip()
    current_hostname = str(current_identity.get("hostname", "") or "").strip()
    current_deployment = str(current_identity.get("deployment_id", "") or "").strip()
    current_replica = str(current_identity.get("replica_id", "") or "").strip()
    current_pid = str(current_identity.get("pid", "") or "").strip()

    same_instance = bool(holder_instance and current_instance and holder_instance == current_instance)
    same_container = bool(holder_container and current_container and holder_container == current_container)
    same_hostname = bool(holder_hostname and current_hostname and holder_hostname == current_hostname)
    same_deployment = bool(holder_deployment and current_deployment and holder_deployment == current_deployment)
    same_replica = bool(holder_replica and current_replica and holder_replica == current_replica)
    same_pid = bool(holder_pid and current_pid and holder_pid == current_pid)

    if not holder_info.get("raw"):
        relationship = "missing-holder"
    elif same_instance or (same_container and same_pid):
        relationship = "same-instance"
    elif same_deployment and same_replica:
        relationship = "same-replica"
    elif same_deployment:
        relationship = "same-deployment"
    elif same_container:
        relationship = "same-container"
    elif same_hostname:
        relationship = "same-host"
    elif holder_info.get("format") == "legacy":
        relationship = "legacy-holder"
    else:
        relationship = "other-instance"

    summary = (
        f"relationship={relationship} current={format_instance_identity(current_identity)} "
        f"holder={holder_info.get('display', '<missing-holder>')}"
    )
    return {
        "relationship": relationship,
        "same_instance": same_instance,
        "same_container": same_container,
        "same_hostname": same_hostname,
        "same_deployment": same_deployment,
        "same_replica": same_replica,
        "same_pid": same_pid,
        "summary": summary,
    }


def parse_writer_lock_metadata(raw_meta: str) -> dict[str, object]:
    """Parse optional writer-lock metadata stored beside the Redis lock key."""
    raw_value = str(raw_meta or "").strip()
    parsed: dict[str, object] = {
        "raw": raw_value,
        "present": bool(raw_value),
        "instance": {},
        "display": "<missing-meta>",
    }
    if not raw_value:
        return parsed

    try:
        payload = json.loads(raw_value)
    except Exception as exc:
        parsed["error"] = str(exc)
        parsed["display"] = "<invalid-meta>"
        return parsed

    if not isinstance(payload, dict):
        parsed["error"] = "metadata payload is not an object"
        parsed["display"] = "<invalid-meta>"
        return parsed

    instance = payload.get("instance") if isinstance(payload.get("instance"), dict) else {}
    heartbeat_at = payload.get("heartbeat_at")
    acquired_at = payload.get("acquired_at")
    now = time.time()
    heartbeat_age_s = None
    if isinstance(heartbeat_at, (int, float)):
        heartbeat_age_s = max(0.0, now - float(heartbeat_at))

    parsed.update(
        {
            "token": str(payload.get("token", "") or ""),
            "heartbeat_at": heartbeat_at,
            "acquired_at": acquired_at,
            "heartbeat_age_s": heartbeat_age_s,
            "instance": instance,
            "display": format_instance_identity(instance) if instance else "<missing-meta-instance>",
        }
    )
    return parsed