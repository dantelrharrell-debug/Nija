"""Automatic NIJA user-capacity signal for shard provisioning.

v411 observes the canonical enabled-user registry and publishes a bounded,
machine-readable capacity state.  It does not provision infrastructure, change
writer authority, alter strategy/risk thresholds, connect brokers, or place
orders.  When enabled users exceed configured shard capacity it emits
SCALE_REQUIRED and leaves v410's overflow admission guard fail-closed.
"""
from __future__ import annotations

import json
import logging
import math
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger("nija.runtime_capacity_autoscale_signal_v411")
MARKER = "20260909-runtime-capacity-autoscale-signal-v411"
_READY_FLAG = "NIJA_CAPACITY_AUTOSCALE_SIGNAL_V411_READY"
_STATE_PATH = Path(os.environ.get("NIJA_CAPACITY_STATE_FILE", "/tmp/nija_capacity_state.json"))
_LOCK = threading.RLock()
_THREAD: threading.Thread | None = None
_LAST_SIGNATURE = ""


def _int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = str(os.environ.get(name, str(default)) or str(default)).strip()
    value = int(raw)
    if value < minimum or value > maximum:
        raise ValueError(f"{name}_out_of_range:{value}")
    return value


def _capacity_config() -> tuple[int, int]:
    shard_count = _int_env("NIJA_USER_SHARD_COUNT", 1, 1, 64)
    per_shard = _int_env("NIJA_MAX_USERS_PER_SHARD", 25, 1, 1000)
    return shard_count, per_shard


def _enabled_users() -> list[Any]:
    from config.user_loader import get_user_config_loader

    loader = get_user_config_loader()
    users = list(loader.get_all_enabled_users() or [])
    # Defensive de-duplication by canonical user_id so duplicate config rows do
    # not manufacture a scaling event.
    unique: dict[str, Any] = {}
    for user in users:
        user_id = str(getattr(user, "user_id", "") or "").strip().lower()
        if user_id:
            unique.setdefault(user_id, user)
    return [unique[key] for key in sorted(unique)]


def capacity_snapshot() -> dict[str, Any]:
    shard_count, per_shard = _capacity_config()
    users = _enabled_users()
    enabled = len(users)
    configured_capacity = shard_count * per_shard
    required_shards = max(1, int(math.ceil(enabled / float(per_shard)))) if enabled else 1
    scale_required = required_shards > shard_count
    next_threshold = configured_capacity + 1
    return {
        "marker": MARKER,
        "timestamp": time.time(),
        "status": "SCALE_REQUIRED" if scale_required else "READY",
        "enabled_users": enabled,
        "configured_shards": shard_count,
        "max_users_per_shard": per_shard,
        "configured_capacity": configured_capacity,
        "required_shards": required_shards,
        "additional_shards_required": max(0, required_shards - shard_count),
        "next_scale_trigger_user": next_threshold,
        "overflow_blocked": scale_required,
        "automatic_detection": True,
        "infrastructure_provisioned": False,
        "orders_submitted": False,
        "authority_granted": False,
        "safety_gates_bypassed": False,
    }


def _atomic_write(payload: dict[str, Any]) -> None:
    _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix="nija-capacity-", suffix=".json", dir=str(_STATE_PATH.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, _STATE_PATH)
    finally:
        try:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
        except OSError:
            pass


def publish_capacity_state() -> dict[str, Any]:
    global _LAST_SIGNATURE
    payload = capacity_snapshot()
    _atomic_write(payload)
    signature = json.dumps({k: payload[k] for k in (
        "status", "enabled_users", "configured_shards", "configured_capacity", "required_shards"
    )}, sort_keys=True)
    if signature != _LAST_SIGNATURE:
        _LAST_SIGNATURE = signature
        log = LOGGER.error if payload["status"] == "SCALE_REQUIRED" else LOGGER.critical
        log(
            "CAPACITY_V411_STATE marker=%s status=%s enabled_users=%s configured_shards=%s "
            "capacity=%s required_shards=%s overflow_blocked=%s infrastructure_provisioned=false "
            "orders_submitted=false authority_granted=false safety_gates_bypassed=false",
            MARKER,
            payload["status"],
            payload["enabled_users"],
            payload["configured_shards"],
            payload["configured_capacity"],
            payload["required_shards"],
            str(payload["overflow_blocked"]).lower(),
        )
    return payload


def _monitor() -> None:
    interval = max(2.0, min(60.0, float(os.environ.get("NIJA_CAPACITY_MONITOR_INTERVAL_S", "10") or 10)))
    while True:
        try:
            publish_capacity_state()
            os.environ[_READY_FLAG] = "1"
        except Exception as exc:
            os.environ[_READY_FLAG] = "0"
            LOGGER.exception(
                "CAPACITY_V411_MONITOR_ERROR marker=%s error=%s:%s fail_closed=true",
                MARKER,
                type(exc).__name__,
                exc,
            )
        time.sleep(interval)


def install() -> bool:
    global _THREAD
    with _LOCK:
        try:
            publish_capacity_state()
            if _THREAD is None or not _THREAD.is_alive():
                _THREAD = threading.Thread(target=_monitor, name="CapacityAutoscaleSignalV411", daemon=True)
                _THREAD.start()
            os.environ[_READY_FLAG] = "1"
            LOGGER.critical(
                "CAPACITY_V411_READY marker=%s automatic_detection=true overflow_fail_closed=true "
                "infrastructure_provisioning=false writer_authority_unchanged=true risk_gates_unchanged=true",
                MARKER,
            )
            return True
        except Exception as exc:
            os.environ[_READY_FLAG] = "0"
            LOGGER.exception(
                "CAPACITY_V411_INSTALL_ERROR marker=%s error=%s:%s fail_closed=true",
                MARKER,
                type(exc).__name__,
                exc,
            )
            return False


install_import_hook = install

__all__ = ["MARKER", "capacity_snapshot", "publish_capacity_state", "install", "install_import_hook"]
