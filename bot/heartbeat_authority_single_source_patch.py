"""Canonical heartbeat freshness bridge for writer authority and SAFE_START.

This module unifies the three historically independent heartbeat surfaces:

* ``NIJA_WRITER_HEARTBEAT_ALIVE_TS`` (environment telemetry)
* ``heartbeat_verified.flag`` (activation marker)
* :mod:`bot.heartbeat_state` (canonical in-process state)

Every successful writer heartbeat is published through one refresh operation,
and every authority/activation freshness check is derived from the canonical
HeartbeatState using monotonic time.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from types import ModuleType
from typing import Any

try:
    from bot.heartbeat_state import get_heartbeat_state
except ImportError:
    from heartbeat_state import get_heartbeat_state  # type: ignore[import]

logger = logging.getLogger("nija.heartbeat_authority_single_source")
_PATCHED = "_NIJA_HEARTBEAT_SINGLE_SOURCE_PATCHED"
_LOCK = threading.RLock()
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}


def _truthy(name: str) -> bool:
    return str(os.environ.get(name, "") or "").strip().lower() in _TRUE


def _generation() -> int:
    raw = (
        os.environ.get("NIJA_WRITER_LEASE_GENERATION", "")
        or os.environ.get("NIJA_WRITER_GENERATION", "")
        or "0"
    )
    try:
        return int(str(raw).strip() or "0")
    except (TypeError, ValueError):
        return 0


def heartbeat_max_age_s() -> float:
    """Return the single freshness policy used by every authority reader."""
    raw = os.environ.get("NIJA_WRITER_HEARTBEAT_MAX_AGE_S", "120")
    try:
        value = max(5.0, float(raw or 120.0))
    except (TypeError, ValueError):
        value = 120.0
    # Keep the legacy knob synchronized for diagnostics/backward compatibility.
    os.environ["NIJA_RUNTIME_AUTHORITY_CONVERGENCE_HEARTBEAT_MAX_AGE_S"] = str(value)
    return value


def _marker_path() -> Path:
    return Path(os.environ.get("HEARTBEAT_MARKER_PATH", "./data/heartbeat_verified.flag"))


def _marker_stage() -> str:
    return (
        os.environ.get("NIJA_AUTHORITY_HEARTBEAT_MARKER_STAGE", "").strip().upper()
        or "FILL_VERIFY"
    )


def _write_marker(epoch_ts: float) -> None:
    """Atomically write the activation marker with the same heartbeat timestamp."""
    marker = _marker_path()
    marker.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "stage": _marker_stage(),
        "verified_at_epoch": epoch_ts,
        "source": "heartbeat_authority_single_source",
    }
    tmp = marker.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    tmp.replace(marker)


def refresh_heartbeat(*, source: str, generation: int | None = None) -> float:
    """Refresh every heartbeat surface from one successful heartbeat event.

    Publication is all-or-nothing from the authority readers' point of view:
    the marker is written first, then env telemetry and canonical state receive
    the exact same epoch timestamp. If marker publication fails, no new
    canonical heartbeat is recorded and callers retry on the next cycle.
    """
    gen = _generation() if generation is None else int(generation)
    if gen <= 0:
        logger.debug("HEARTBEAT_REFRESH skipped source=%s reason=generation_missing", source)
        return 0.0

    with _LOCK:
        epoch_ts = time.time()
        mono_ts = time.monotonic()
        _write_marker(epoch_ts)
        os.environ["NIJA_WRITER_HEARTBEAT_ACTIVE"] = "1"
        os.environ["NIJA_WRITER_HEARTBEAT_ALIVE_TS"] = f"{epoch_ts:.6f}"
        os.environ["NIJA_WRITER_HEARTBEAT_LAST_TS"] = f"{epoch_ts:.6f}"
        get_heartbeat_state().record_heartbeat(
            generation=gen,
            marker_timestamp=epoch_ts,
            timestamp=epoch_ts,
            monotonic_timestamp=mono_ts,
        )

    logger.info(
        "HEARTBEAT_REFRESH heartbeat_ts=%.6f generation=%s source=%s marker=%s",
        epoch_ts,
        gen,
        source,
        _marker_path(),
    )
    return epoch_ts


def _safe_refresh(*, source: str, generation: int | None = None) -> bool:
    """Publish one heartbeat without terminating the owning renewal thread."""
    try:
        return refresh_heartbeat(source=source, generation=generation) > 0.0
    except Exception as exc:
        logger.error(
            "HEARTBEAT_REFRESH_FAILED source=%s generation=%s marker=%s err=%s",
            source,
            generation if generation is not None else _generation(),
            _marker_path(),
            exc,
            exc_info=True,
        )
        return False


def heartbeat_check(*, source: str) -> tuple[bool, float, float, float, bool]:
    """Return ``healthy, now_epoch, heartbeat_ts, age_s, authoritative``."""
    gen = _generation()
    max_age = heartbeat_max_age_s()
    healthy, age_s, authoritative, heartbeat_ts = get_heartbeat_state().health_for_generation(
        expected_generation=gen,
        max_age_s=max_age,
    )
    now_epoch = time.time()
    logger.info(
        "HEARTBEAT_CHECK now=%.6f heartbeat_ts=%.6f age=%.3f healthy=%s "
        "authoritative=%s generation=%s source=%s",
        now_epoch,
        heartbeat_ts,
        age_s,
        healthy,
        authoritative,
        gen,
        source,
    )
    return healthy, now_epoch, heartbeat_ts, age_s, authoritative


def _patch_entrypoint_writer_authority(module: ModuleType) -> None:
    cls = getattr(module, "EntrypointWriterAuthority", None)
    if cls is None or getattr(cls, _PATCHED, False):
        return

    original_publish = getattr(cls, "_publish_env", None)
    if callable(original_publish):
        def _publish_env(self: Any, *args: Any, **kwargs: Any) -> Any:
            result = original_publish(self, *args, **kwargs)
            _safe_refresh(
                source="entrypoint_writer_authority.publish_env",
                generation=int(getattr(self, "_generation", 0) or _generation()),
            )
            return result
        cls._publish_env = _publish_env

    original_tick = getattr(cls, "_heartbeat_tick", None)
    if callable(original_tick):
        def _heartbeat_tick(self: Any, *args: Any, **kwargs: Any):
            result = original_tick(self, *args, **kwargs)
            try:
                ok = bool(result[0])
            except Exception:
                ok = False
            if ok:
                _safe_refresh(
                    source="entrypoint_writer_authority.heartbeat_tick",
                    generation=int(getattr(self, "_generation", 0) or _generation()),
                )
            return result
        cls._heartbeat_tick = _heartbeat_tick

    setattr(cls, _PATCHED, True)
    logger.warning("HEARTBEAT_SINGLE_SOURCE_ENTRYPOINT_PATCHED module=%s", module.__name__)


def _patch_authority_heartbeat(module: ModuleType) -> None:
    cls = getattr(module, "AuthorityHeartbeatMonitor", None)
    if cls is None or getattr(cls, _PATCHED, False):
        return
    original_tick = getattr(cls, "_tick", None)
    if callable(original_tick):
        def _tick(self: Any, *args: Any, **kwargs: Any):
            result = original_tick(self, *args, **kwargs)
            if (
                not bool(getattr(self, "_locked_down", False))
                and int(getattr(self, "_consecutive_failures", 0) or 0) == 0
                and _truthy("NIJA_WRITER_HEARTBEAT_ACTIVE")
            ):
                _safe_refresh(source="authority_heartbeat.tick")
            return result
        cls._tick = _tick
    setattr(cls, _PATCHED, True)
    logger.warning("HEARTBEAT_SINGLE_SOURCE_MONITOR_PATCHED module=%s", module.__name__)


def _patch_writer_authority(module: ModuleType) -> None:
    if getattr(module, _PATCHED, False):
        return

    def _canonical_heartbeat_health(*, generation: str, max_age_s: float):
        try:
            gen = int(str(generation or "").strip() or "0")
        except (TypeError, ValueError):
            gen = 0
        healthy, age_s, authoritative, _ts = get_heartbeat_state().health_for_generation(
            expected_generation=gen,
            max_age_s=heartbeat_max_age_s(),
        )
        return healthy, age_s, authoritative

    module._canonical_heartbeat_health = _canonical_heartbeat_health
    setattr(module, _PATCHED, True)
    logger.warning("HEARTBEAT_SINGLE_SOURCE_WRITER_AUTHORITY_PATCHED module=%s", module.__name__)


def _patch_trading_state_machine(module: ModuleType) -> None:
    if getattr(module, _PATCHED, False):
        return

    original_gate = getattr(module, "_writer_heartbeat_gate", None)

    def _writer_heartbeat_gate() -> tuple[bool, str]:
        if not _truthy("NIJA_ENFORCE_WRITER_HEARTBEAT_GATE") and (
            "NIJA_ENFORCE_WRITER_HEARTBEAT_GATE" in os.environ
        ):
            return True, ""

        if not _truthy("NIJA_WRITER_HEARTBEAT_ACTIVE"):
            try:
                try:
                    from bot.authority_heartbeat import start_authority_heartbeat
                except ImportError:
                    from authority_heartbeat import start_authority_heartbeat  # type: ignore[import]
                start_authority_heartbeat()
            except Exception as exc:
                logger.warning("HEARTBEAT_GATE_EAGER_START_FAILED err=%s", exc)

        healthy, _now, _ts, age_s, authoritative = heartbeat_check(
            source="safe_start.writer_heartbeat_gate"
        )
        max_age = heartbeat_max_age_s()
        logger.info(
            "ACTIVATION_HEARTBEAT_GATE age=%.3f max_age=%.3f healthy=%s active=%s authoritative=%s",
            age_s,
            max_age,
            healthy,
            _truthy("NIJA_WRITER_HEARTBEAT_ACTIVE"),
            authoritative,
        )
        if not _truthy("NIJA_WRITER_HEARTBEAT_ACTIVE"):
            return False, "writer_heartbeat_inactive"
        if not authoritative:
            return False, "writer_heartbeat_uninitialized"
        if not healthy:
            return False, f"writer_heartbeat_stale age_s={age_s:.1f} max_age_s={max_age:.1f}"
        return True, ""

    module._writer_heartbeat_gate = _writer_heartbeat_gate
    setattr(module, _PATCHED, True)
    logger.warning(
        "HEARTBEAT_SINGLE_SOURCE_SAFE_START_PATCHED module=%s original_gate=%s",
        module.__name__,
        bool(callable(original_gate)),
    )


def _patch_runtime_authority_convergence(module: ModuleType) -> None:
    """Replace the legacy env/wall-clock convergence freshness reader."""
    if getattr(module, _PATCHED, False):
        return

    def _heartbeat_ready() -> tuple[bool, str]:
        token = os.environ.get("NIJA_WRITER_FENCING_TOKEN", "").strip()
        generation = (
            os.environ.get("NIJA_WRITER_LEASE_GENERATION", "").strip()
            or os.environ.get("NIJA_WRITER_GENERATION", "").strip()
        )
        truthy = getattr(module, "_truthy")
        if not truthy("NIJA_WRITER_LEASE_ACQUIRED"):
            singleton_probe = getattr(module, "_singleton_lease_acquired", None)
            if not callable(singleton_probe) or not singleton_probe():
                return False, "writer_lease_not_acquired"
            token = os.environ.get("NIJA_WRITER_FENCING_TOKEN", "").strip()
            generation = (
                os.environ.get("NIJA_WRITER_LEASE_GENERATION", "").strip()
                or os.environ.get("NIJA_WRITER_GENERATION", "").strip()
            )
        if not token:
            try:
                try:
                    from bot.execution_authority_context import get_distributed_writer_authority_status
                except ImportError:
                    from execution_authority_context import get_distributed_writer_authority_status  # type: ignore[import]
                get_distributed_writer_authority_status(force_refresh=True)
                token = os.environ.get("NIJA_WRITER_FENCING_TOKEN", "").strip()
            except Exception:
                pass
        if not token or not generation:
            return False, f"writer_token_or_generation_missing token={bool(token)} generation={generation or 'missing'}"
        if not truthy("NIJA_WRITER_HEARTBEAT_ACTIVE"):
            return False, "heartbeat_inactive"
        if not truthy("NIJA_CORE_THREAD_ALIVE"):
            return False, "core_thread_not_alive"
        if truthy("KRAKEN_NONCE_LEASE_REQUIRED"):
            try:
                try:
                    from bot.execution_authority_context import _runtime_nonce_authority_status
                except ImportError:
                    from execution_authority_context import _runtime_nonce_authority_status  # type: ignore[import]
                nonce_ok, nonce_detail = _runtime_nonce_authority_status()
                if not nonce_ok:
                    return False, f"nonce_manager_not_ready:{nonce_detail or 'blocked'}"
            except Exception as exc:
                return False, f"nonce_manager_status_unavailable:{exc}"

        healthy, _now, _ts, age_s, authoritative = heartbeat_check(
            source="runtime_authority_convergence"
        )
        max_age = heartbeat_max_age_s()
        if not authoritative:
            return False, "heartbeat_uninitialized"
        if not healthy:
            return False, f"heartbeat_stale age_s={age_s:.1f} max_age_s={max_age:.1f}"
        return True, f"heartbeat_ready age_s={age_s:.1f} generation={generation}"

    module._heartbeat_ready = _heartbeat_ready
    setattr(module, _PATCHED, True)
    logger.warning("HEARTBEAT_SINGLE_SOURCE_RUNTIME_CONVERGENCE_PATCHED module=%s", module.__name__)


def _patch_execution_contract_authority(module: ModuleType) -> None:
    """Make execution-contract proof consume canonical heartbeat freshness."""
    if getattr(module, _PATCHED, False):
        return

    def authority_proof() -> tuple[bool, str]:
        generation = str(os.environ.get("NIJA_WRITER_LEASE_GENERATION", "") or "").strip()
        required = {
            "live_capital": bool(module.truthy("LIVE_CAPITAL_VERIFIED")),
            "runtime_authority": bool(module.truthy("NIJA_RUNTIME_EXECUTION_AUTHORITY")),
            "heartbeat_active": _truthy("NIJA_WRITER_HEARTBEAT_ACTIVE"),
            "fencing_token": bool(str(os.environ.get("NIJA_WRITER_FENCING_TOKEN", "")).strip()),
            "lease_generation": bool(generation and generation != "0"),
        }
        if module.truthy("DRY_RUN_MODE") or module.truthy("PAPER_MODE"):
            return False, "simulation_mode"
        missing = [name for name, ok in required.items() if not ok]
        if missing:
            return False, "missing:" + ",".join(missing)

        healthy, _now, _ts, age_s, authoritative = heartbeat_check(
            source="execution_contract.authority_proof"
        )
        max_age = heartbeat_max_age_s()
        if not authoritative:
            return False, "heartbeat_uninitialized"
        if not healthy:
            return False, f"heartbeat_stale:age_s={age_s:.1f}:max_age_s={max_age:.1f}"
        try:
            from bot.kill_switch import get_kill_switch
            if bool(get_kill_switch().is_active()):
                return False, "kill_switch_active"
        except Exception as exc:
            return False, f"kill_switch_probe_failed:{exc}"
        try:
            from bot.bootstrap_state_machine import get_bootstrap_fsm
            fsm = get_bootstrap_fsm()
            has_auth = fsm.has_execution_authority() if hasattr(fsm, "has_execution_authority") else bool(getattr(fsm, "execution_authority", False))
            if not has_auth:
                return False, "bootstrap_execution_authority_false"
        except Exception as exc:
            return False, f"bootstrap_authority_unavailable:{exc}"
        try:
            from bot.execution_authority_context import assert_distributed_writer_authority
            assert_distributed_writer_authority()
        except Exception as exc:
            return False, f"distributed_writer_not_ready:{exc}"
        return True, f"writer_lineage_verified:generation={generation}:heartbeat_age_s={age_s:.1f}"

    module.authority_proof = authority_proof
    setattr(module, _PATCHED, True)
    logger.warning("HEARTBEAT_SINGLE_SOURCE_EXECUTION_CONTRACT_PATCHED module=%s", module.__name__)


def _patch_three_venue_execution_readiness(module: ModuleType) -> None:
    """Make venue readiness report the same heartbeat decision as WriterAuthority."""
    if getattr(module, _PATCHED, False):
        return

    def writer_authority_snapshot(*, now: float | None = None) -> dict[str, Any]:
        try:
            from bot.writer_authority import WriterAuthority
        except ImportError:
            from writer_authority import WriterAuthority  # type: ignore[import]
        status = WriterAuthority.get_status(
            force_refresh=False,
            enforce_active_invariant=False,
        )
        checks = status.checks
        writer_state = status.state
        state_allows_execution = writer_state in {"ACTIVE", "REFRESHING"}
        core_loop_alive = bool(module._writer_core_loop_alive())
        heartbeat_active = bool(checks.get("heartbeat_active", _truthy("NIJA_WRITER_HEARTBEAT_ACTIVE")))
        healthy, _now, heartbeat_ts, age_s, authoritative = heartbeat_check(
            source="three_venue_execution_readiness"
        )
        heartbeat_healthy = bool(heartbeat_active and healthy and authoritative)
        heartbeat_effective = bool(heartbeat_healthy or writer_state == "REFRESHING")
        lease_effective = bool(checks.get("lease_acquired", _truthy("NIJA_WRITER_LEASE_ACQUIRED")))
        fencing_token = bool(
            checks.get(
                "fencing_token_active",
                bool(str(os.getenv("NIJA_WRITER_FENCING_TOKEN", "") or "").strip()),
            )
        )
        strict_ready = bool(
            status.ready
            and state_allows_execution
            and lease_effective
            and fencing_token
            and heartbeat_effective
            and core_loop_alive
        )
        return {
            "lease_acquired": lease_effective,
            "lease_acquired_raw": _truthy("NIJA_WRITER_LEASE_ACQUIRED"),
            "fencing_token": fencing_token,
            "writer_state": writer_state or "UNKNOWN",
            "state_allows_execution": state_allows_execution,
            "heartbeat_active": heartbeat_active,
            "heartbeat_alive_ts": heartbeat_ts,
            "heartbeat_age_s": age_s,
            "heartbeat_max_age_s": heartbeat_max_age_s(),
            "heartbeat_healthy": heartbeat_healthy,
            "heartbeat_effective": heartbeat_effective,
            "core_loop_alive": core_loop_alive,
            "authority_verified": bool(checks.get("authority_verified", False)),
            "redis_reachable": bool(checks.get("redis_reachable", False)),
            "checks": checks,
            "missing": list(status.missing),
            "source": status.source,
            "reason": status.reason,
            "ready": strict_ready,
        }

    module.writer_authority_snapshot = writer_authority_snapshot
    setattr(module, _PATCHED, True)
    logger.warning("HEARTBEAT_SINGLE_SOURCE_THREE_VENUE_PATCHED module=%s", module.__name__)


def _patch_loaded_modules() -> None:
    import sys

    targets = (
        ("bot.entrypoint_writer_authority", _patch_entrypoint_writer_authority),
        ("entrypoint_writer_authority", _patch_entrypoint_writer_authority),
        ("bot.authority_heartbeat", _patch_authority_heartbeat),
        ("authority_heartbeat", _patch_authority_heartbeat),
        ("bot.writer_authority", _patch_writer_authority),
        ("writer_authority", _patch_writer_authority),
        ("bot.trading_state_machine", _patch_trading_state_machine),
        ("trading_state_machine", _patch_trading_state_machine),
        ("bot.runtime_authority_convergence_repair_patch", _patch_runtime_authority_convergence),
        ("runtime_authority_convergence_repair_patch", _patch_runtime_authority_convergence),
        ("bot.execution_contract_authority", _patch_execution_contract_authority),
        ("execution_contract_authority", _patch_execution_contract_authority),
        ("three_venue_execution_readiness", _patch_three_venue_execution_readiness),
        ("bot.three_venue_execution_readiness", _patch_three_venue_execution_readiness),
    )
    for name, patcher in targets:
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            patcher(module)


def install_import_hook() -> None:
    """Patch loaded modules and future imports for the canonical heartbeat contract."""
    import builtins

    _patch_loaded_modules()
    hook_attr = "_NIJA_HEARTBEAT_SINGLE_SOURCE_IMPORT_HOOK_INSTALLED"
    if getattr(builtins, hook_attr, False):
        return
    original_import = builtins.__import__

    def guarded_import(name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        if any(
            name.endswith(target)
            for target in (
                "entrypoint_writer_authority",
                "authority_heartbeat",
                "writer_authority",
                "trading_state_machine",
                "runtime_authority_convergence_repair_patch",
                "execution_contract_authority",
                "three_venue_execution_readiness",
            )
        ):
            try:
                _patch_loaded_modules()
            except Exception:
                logger.exception("HEARTBEAT_SINGLE_SOURCE_IMPORT_PATCH_FAILED imported=%s", name)
        return module

    builtins.__import__ = guarded_import
    setattr(builtins, hook_attr, True)
    logger.warning("HEARTBEAT_SINGLE_SOURCE_INSTALL_COMPLETE max_age_s=%.1f", heartbeat_max_age_s())


def install() -> None:
    install_import_hook()
