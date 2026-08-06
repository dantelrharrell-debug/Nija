"""Canonical writer-authority status publisher."""

from __future__ import annotations

import importlib
import logging
import os
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("nija.writer_authority")
_TRUTHY = {"1", "true", "yes", "on", "enabled", "y"}


@dataclass(frozen=True)
class WriterAuthorityStatus:
    ready: bool
    state: str
    checks: dict[str, bool]
    missing: tuple[str, ...]
    source: str
    reason: str


def _env_truthy(name: str) -> bool:
    return str(os.environ.get(name, "") or "").strip().lower() in _TRUTHY


def _fallback_status() -> WriterAuthorityStatus:
    ready = _env_truthy("NIJA_WRITER_READY") or _env_truthy("WRITER_READY")
    state = str(os.environ.get("NIJA_WRITER_STATE", "") or "").strip().upper() or "UNKNOWN"
    checks = {"fallback_env_writer_ready": ready}
    missing = tuple() if ready else ("fallback_env_writer_ready",)
    reason = "ready" if ready else "fallback_env_writer_ready_false"
    return WriterAuthorityStatus(
        ready=ready,
        state=state,
        checks=checks,
        missing=missing,
        source="env_fallback",
        reason=reason,
    )


class WriterAuthority:
    """Canonical writer-authority reader with ACTIVE-state invariant enforcement."""

    @staticmethod
    def get_status(
        *,
        force_refresh: bool = False,
        enforce_active_invariant: bool = False,
    ) -> WriterAuthorityStatus:
        writer_state = str(os.environ.get("NIJA_WRITER_STATE", "") or "").strip().upper() or "UNKNOWN"
        token = str(os.environ.get("NIJA_WRITER_FENCING_TOKEN", "") or "").strip()
        generation = str(os.environ.get("NIJA_WRITER_LEASE_GENERATION", "") or "").strip()
        lease_flag = _env_truthy("NIJA_WRITER_LEASE_ACQUIRED")
        state_allows_execution = writer_state in {"ACTIVE", "REFRESHING"}
        lease_effective = bool(lease_flag or (state_allows_execution and token))
        heartbeat_active = _env_truthy("NIJA_WRITER_HEARTBEAT_ACTIVE")
        heartbeat_alive_ts_raw = str(os.environ.get("NIJA_WRITER_HEARTBEAT_ALIVE_TS", "") or "").strip()
        try:
            heartbeat_alive_ts = float(heartbeat_alive_ts_raw or 0.0)
        except (TypeError, ValueError):
            heartbeat_alive_ts = 0.0
        try:
            heartbeat_max_age_s = max(
                5.0,
                float(
                    os.environ.get(
                        "NIJA_RUNTIME_AUTHORITY_CONVERGENCE_HEARTBEAT_MAX_AGE_S",
                        "90.0",
                    )
                    or 90.0
                ),
            )
        except (TypeError, ValueError):
            heartbeat_max_age_s = 90.0
        heartbeat_age_s = max(0.0, time.time() - heartbeat_alive_ts) if heartbeat_alive_ts > 0.0 else float("inf")
        heartbeat_healthy = bool(
            heartbeat_active and heartbeat_alive_ts > 0.0 and heartbeat_age_s <= heartbeat_max_age_s
        )
        heartbeat_effective = bool(heartbeat_healthy or writer_state == "REFRESHING")
        core_thread_alive = _env_truthy("NIJA_CORE_THREAD_ALIVE")
        local_authority_observed = False
        local_authority_acquired = False
        local_authority_lost = False
        local_instance_id = ""
        try:
            try:
                authority_module = importlib.import_module("bot.entrypoint_writer_authority")
            except ImportError:
                authority_module = importlib.import_module("entrypoint_writer_authority")
            getter = getattr(authority_module, "get_entrypoint_writer_authority", None)
            if callable(getter):
                authority = getter()
                local_authority_observed = True
                local_authority_acquired = bool(getattr(authority, "acquired", False))
                local_authority_lost = bool(getattr(authority, "lost", False))
                result = getattr(authority, "result", None)
                local_instance_id = str(
                    getattr(result, "instance_id", "")
                    or getattr(authority, "_instance_id", "")
                    or ""
                )
                if not core_thread_alive:
                    runtime_core = getattr(authority, "_core_thread", None)
                    alive_reader = getattr(runtime_core, "is_alive", None)
                    core_thread_alive = bool(alive_reader()) if callable(alive_reader) else False
        except Exception:
            pass

        local_authority_gate = bool(
            (not local_authority_observed)
            or (local_authority_acquired and not local_authority_lost)
        )
        try:
            try:
                module = importlib.import_module("bot.execution_authority_context")
            except ImportError:
                module = importlib.import_module("execution_authority_context")
            getter = getattr(module, "get_distributed_writer_authority_status", None)
            if not callable(getter):
                distributed_status: dict[str, Any] = {}
            else:
                distributed_status = dict(getter(force_refresh=force_refresh) or {})
        except Exception as exc:
            logger.debug("WRITER_AUTHORITY_DISTRIBUTED_STATUS_UNAVAILABLE err=%s", exc)
            distributed_status = {}

        distributed_required = bool(distributed_status.get("effective_strict_required", False))
        distributed_ok = bool(distributed_status.get("ok", False))
        distributed_override = _env_truthy("NIJA_FORCE_LOCAL_WRITER_LOCK_FALLBACK")
        distributed_gate_ok = bool(
            (not distributed_required)
            or distributed_ok
            or distributed_override
            or (local_authority_observed and local_authority_acquired and not local_authority_lost)
        )

        checks = {
            "lease_acquired": lease_effective,
            "fencing_token_active": bool(token),
            "generation_present": bool(generation),
            "state_allows_execution": state_allows_execution,
            "heartbeat_active": heartbeat_active,
            "heartbeat_healthy": heartbeat_healthy,
            "core_thread_alive": core_thread_alive,
            "local_authority_gate": local_authority_gate,
            "distributed_authority_required": distributed_required,
            "distributed_authority_ok": distributed_ok,
            "distributed_authority_gate": distributed_gate_ok,
        }
        ready = bool(
            lease_effective
            and bool(token)
            and bool(generation)
            and state_allows_execution
            and heartbeat_effective
            and core_thread_alive
            and local_authority_gate
            and distributed_gate_ok
        )
        missing = tuple(name for name, ok in checks.items() if not ok and name not in {"distributed_authority_required"})
        reason = "ready" if ready else f"missing:{','.join(missing) if missing else 'unknown'}"
        status = WriterAuthorityStatus(
            ready=ready,
            state=writer_state,
            checks={
                **checks,
                "local_authority_observed": local_authority_observed,
                "local_authority_acquired": local_authority_acquired,
                "local_authority_lost": local_authority_lost,
                "local_instance_id_present": bool(local_instance_id),
            },
            missing=missing,
            source="writer_authority.get_status",
            reason=reason,
        )
        if distributed_status:
            status.checks["redis_reachable"] = bool(distributed_status.get("redis_reachable", False))
            status.checks["authority_verified"] = bool(distributed_status.get("ok", False))
            status.checks["distributed_strict_required"] = distributed_required

        if not status.checks:
            status = _fallback_status()

        if status.state == "ACTIVE" and not status.ready:
            logger.critical(
                "WRITER_STATE_INCONSISTENT state=ACTIVE writer_ready=False missing=%s checks=%s",
                ",".join(status.missing) if status.missing else "unknown",
                status.checks,
            )
            if enforce_active_invariant:
                raise RuntimeError(
                    "WRITER_STATE_INCONSISTENT: state=ACTIVE writer_ready=False "
                    f"missing={','.join(status.missing) if status.missing else 'unknown'}"
                )
        return status
