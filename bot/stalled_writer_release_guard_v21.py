"""Release a fail-closed writer lease when startup cannot become execution-ready.

A Render process can acquire the distributed writer lease and then remain stuck in
``LIVE_PENDING_CONFIRMATION`` with no execution authority, no initialized canonical
broker manager, no hydrated capital, and zero scan cycles.  Keeping that failed
process alive indefinitely blocks a corrected deployment from becoming the writer.

This guard is deliberately narrow:

* it applies only to verified live mode;
* it requires a real writer token and lease generation;
* it never runs after ``LIVE_ACTIVE`` or execution authority is granted;
* it waits a bounded startup timeout before acting;
* it requests shutdown, releases the current process's own lease through bot_main,
  and exits the failed process so Render can replace it.

It does not delete Redis keys directly, take over another process's lease, grant
trading authority, initialize brokers from a background thread, or submit orders.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
import time
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger("nija.stalled_writer_release_guard")

_MARKER = "20260723-stalled-writer-release-v21"
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}
_LOCK = threading.RLock()
_INSTALLED = False
_THREAD: Optional[threading.Thread] = None
_STOP = threading.Event()


def _truthy_value(value: Any) -> bool:
    return str(value or "").strip().lower() in _TRUE


def _truthy_env(name: str, default: str = "false") -> bool:
    return _truthy_value(os.environ.get(name, default))


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)) or default)
    except (TypeError, ValueError):
        return default


def _int_env(name: str, default: int) -> int:
    try:
        return int(float(os.environ.get(name, str(default)) or default))
    except (TypeError, ValueError):
        return default


def _live_mode() -> bool:
    return (
        _truthy_env("LIVE_CAPITAL_VERIFIED")
        and not _truthy_env("DRY_RUN_MODE")
        and not _truthy_env("PAPER_MODE")
    )


def _manager_snapshot() -> tuple[bool, bool, bool]:
    """Return ``(fsm_initialized, sources_registered, attempts_finalized)``.

    The watchdog never imports the manager module merely to inspect it.  It only
    observes an already-loaded canonical module, preserving bootstrap ownership.
    """

    module = sys.modules.get("bot.multi_account_broker_manager") or sys.modules.get(
        "multi_account_broker_manager"
    )
    if module is None:
        return False, False, False

    manager = getattr(module, "multi_account_broker_manager", None)
    if manager is None:
        getter = getattr(module, "get_broker_manager", None)
        if callable(getter):
            try:
                manager = getter()
            except Exception:
                manager = None
    if manager is None:
        return False, False, False

    fsm_initialized = bool(getattr(manager, "_fsm_initialized", False))

    has_sources = getattr(manager, "has_registered_sources", None)
    try:
        sources_registered = bool(has_sources()) if callable(has_sources) else False
    except Exception:
        sources_registered = False

    attempted = getattr(manager, "has_attempted_connections", None)
    try:
        attempts_finalized = bool(attempted()) if callable(attempted) else False
    except Exception:
        attempts_finalized = False

    return fsm_initialized, sources_registered, attempts_finalized


def _capital_snapshot() -> tuple[bool, float, bool, int]:
    """Return ``(hydrated, capital, stale, valid_brokers)`` without creating CA."""

    module = sys.modules.get("bot.capital_authority") or sys.modules.get("capital_authority")
    if module is None:
        return False, 0.0, True, 0

    getter = getattr(module, "get_capital_authority", None)
    if not callable(getter):
        return False, 0.0, True, 0

    try:
        authority = getter()
    except Exception:
        return False, 0.0, True, 0
    if authority is None:
        return False, 0.0, True, 0

    hydrated_raw = getattr(authority, "is_hydrated", False)
    try:
        hydrated = bool(hydrated_raw() if callable(hydrated_raw) else hydrated_raw)
    except Exception:
        hydrated = False

    try:
        capital = float(authority.get_real_capital() or 0.0)
    except Exception:
        try:
            capital = float(getattr(authority, "total_capital", 0.0) or 0.0)
        except Exception:
            capital = 0.0

    try:
        stale = bool(authority.is_stale())
    except Exception:
        stale = True

    valid = 0
    for attr in ("valid_brokers", "broker_count", "_valid_broker_count"):
        try:
            candidate = int(getattr(authority, attr, 0) or 0)
        except Exception:
            candidate = 0
        if candidate > 0:
            valid = candidate
            break

    return hydrated, capital, stale, valid


@dataclass(frozen=True)
class RuntimeSnapshot:
    live_mode: bool
    writer_acquired: bool
    token: str
    generation: str
    state: str
    authority: bool
    startup_complete: bool
    shutdown_requested: bool
    fsm_initialized: bool
    sources_registered: bool
    attempts_finalized: bool
    hydrated: bool
    capital: float
    stale: bool
    valid_brokers: int

    @property
    def manager_ready(self) -> bool:
        return self.fsm_initialized and self.sources_registered and self.attempts_finalized

    @property
    def capital_ready(self) -> bool:
        return self.hydrated and not self.stale and self.capital > 0.0 and self.valid_brokers >= 1


def _runtime_snapshot(bot_main: Any) -> RuntimeSnapshot:
    token = str(os.environ.get("NIJA_WRITER_FENCING_TOKEN", "") or "").strip()
    generation = str(os.environ.get("NIJA_WRITER_LEASE_GENERATION", "") or "").strip()
    writer_acquired = (
        _truthy_env("NIJA_WRITER_LEASE_ACQUIRED") and bool(token) and bool(generation)
    )
    fsm_initialized, sources_registered, attempts_finalized = _manager_snapshot()
    hydrated, capital, stale, valid_brokers = _capital_snapshot()

    shutdown_event = getattr(bot_main, "_shutdown_event", None)
    shutdown_requested = bool(
        shutdown_event is not None
        and callable(getattr(shutdown_event, "is_set", None))
        and shutdown_event.is_set()
    )

    return RuntimeSnapshot(
        live_mode=_live_mode(),
        writer_acquired=writer_acquired,
        token=token,
        generation=generation,
        state=str(os.environ.get("NIJA_RUNTIME_TRADING_STATE", "OFF") or "OFF")
        .strip()
        .upper(),
        authority=_truthy_env("NIJA_RUNTIME_EXECUTION_AUTHORITY"),
        startup_complete=bool(getattr(bot_main, "_startup_complete", False)),
        shutdown_requested=shutdown_requested,
        fsm_initialized=fsm_initialized,
        sources_registered=sources_registered,
        attempts_finalized=attempts_finalized,
        hydrated=hydrated,
        capital=capital,
        stale=stale,
        valid_brokers=valid_brokers,
    )


def _release_reason(snapshot: RuntimeSnapshot) -> str:
    reasons: list[str] = []
    if not snapshot.manager_ready:
        reasons.append("broker_manager_not_initialized")
    if not snapshot.capital_ready:
        reasons.append(
            "capital_not_ready"
            f":hydrated={snapshot.hydrated}"
            f":capital={snapshot.capital:.8f}"
            f":stale={snapshot.stale}"
            f":brokers={snapshot.valid_brokers}"
        )
    if snapshot.state != "LIVE_ACTIVE":
        reasons.append(f"state={snapshot.state}")
    if not snapshot.authority:
        reasons.append("execution_authority=0")
    return ",".join(reasons) or "startup_not_ready"


def _should_release(snapshot: RuntimeSnapshot, elapsed_s: float, timeout_s: float) -> bool:
    if elapsed_s < timeout_s:
        return False
    if not snapshot.live_mode or not snapshot.writer_acquired:
        return False
    if snapshot.shutdown_requested or snapshot.startup_complete:
        return False
    if snapshot.authority or snapshot.state == "LIVE_ACTIVE":
        return False
    return not snapshot.manager_ready or not snapshot.capital_ready


def _terminate_process(exit_code: int) -> None:
    """Hard-exit only after this process has released its own writer lease."""

    logging.shutdown()
    os._exit(exit_code)


def _trigger_release(bot_main: Any, snapshot: RuntimeSnapshot, reason: str) -> None:
    """Request shutdown and release this process's own writer lease."""

    os.environ["NIJA_STALLED_WRITER_RELEASE_TRIGGERED"] = "1"
    os.environ["NIJA_STALLED_WRITER_RELEASE_REASON"] = reason
    os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] = "0"
    os.environ["NIJA_RUNTIME_TRADING_STATE"] = "OFF"

    logger.critical(
        "STALLED_WRITER_RELEASE_GUARD_TRIGGERED marker=%s token_prefix=%s "
        "generation=%s reason=%s trading_remains_fail_closed=true",
        _MARKER,
        snapshot.token[:8],
        snapshot.generation,
        reason,
    )

    shutdown_event = getattr(bot_main, "_shutdown_event", None)
    if shutdown_event is not None and callable(getattr(shutdown_event, "set", None)):
        shutdown_event.set()

    release = getattr(bot_main, "_release_writer_authority", None)
    release_error = ""
    try:
        if callable(release):
            release()
        else:
            release_error = "release_function_missing"
    except Exception as exc:  # final defensive boundary before process exit
        release_error = f"{type(exc).__name__}:{exc}"
        logger.critical(
            "STALLED_WRITER_RELEASE_CALL_FAILED marker=%s err=%s",
            _MARKER,
            release_error,
            exc_info=True,
        )

    token_after = str(os.environ.get("NIJA_WRITER_FENCING_TOKEN", "") or "").strip()
    lease_after = _truthy_env("NIJA_WRITER_LEASE_ACQUIRED")
    release_verified = not token_after and not lease_after
    logger.critical(
        "STALLED_WRITER_RELEASE_GUARD_RELEASED marker=%s verified=%s "
        "release_error=%s exit_enabled=%s",
        _MARKER,
        release_verified,
        release_error or "none",
        _truthy_env("NIJA_STALLED_WRITER_EXIT_PROCESS", "true"),
    )

    if _truthy_env("NIJA_STALLED_WRITER_EXIT_PROCESS", "true"):
        _terminate_process(_int_env("NIJA_STALLED_WRITER_EXIT_CODE", 78))


def _ensure_canonical_guard() -> None:
    """Re-assert the v20 startup guard without taking broker ownership."""

    try:
        from bot.canonical_broker_main_entry_guard_v20 import install_import_hook

        install_import_hook()
    except Exception as exc:
        logger.critical(
            "STALLED_WRITER_CANONICAL_GUARD_REINSTALL_FAILED marker=%s err=%s",
            _MARKER,
            exc,
            exc_info=True,
        )


def _monitor() -> None:
    try:
        import bot.bot_main as bot_main
    except Exception as exc:
        logger.critical(
            "STALLED_WRITER_RELEASE_GUARD_IMPORT_FAILED marker=%s err=%s",
            _MARKER,
            exc,
            exc_info=True,
        )
        return

    timeout_s = max(30.0, _float_env("NIJA_STALLED_WRITER_RELEASE_TIMEOUT_S", 360.0))
    poll_s = max(1.0, _float_env("NIJA_STALLED_WRITER_RELEASE_POLL_S", 5.0))
    lease_seen_at: Optional[float] = None
    observed_token = ""
    observed_generation = ""

    while not _STOP.is_set():
        snapshot = _runtime_snapshot(bot_main)
        now = time.monotonic()

        if snapshot.writer_acquired:
            if (
                lease_seen_at is None
                or snapshot.token != observed_token
                or snapshot.generation != observed_generation
            ):
                lease_seen_at = now
                observed_token = snapshot.token
                observed_generation = snapshot.generation
                logger.warning(
                    "STALLED_WRITER_RELEASE_GUARD_LEASE_OBSERVED marker=%s "
                    "token_prefix=%s generation=%s timeout_s=%.1f",
                    _MARKER,
                    snapshot.token[:8],
                    snapshot.generation,
                    timeout_s,
                )
        else:
            lease_seen_at = None
            observed_token = ""
            observed_generation = ""

        if lease_seen_at is not None:
            elapsed_s = now - lease_seen_at
            if _should_release(snapshot, elapsed_s, timeout_s):
                # Re-read immediately so a last-moment LIVE_ACTIVE transition or
                # fencing-token handoff cannot be mistaken for the stalled process.
                confirm = _runtime_snapshot(bot_main)
                if (
                    confirm.token == snapshot.token
                    and confirm.generation == snapshot.generation
                    and _should_release(confirm, elapsed_s, timeout_s)
                ):
                    _trigger_release(bot_main, confirm, _release_reason(confirm))
                    return

        _STOP.wait(poll_s)


def install_import_hook() -> bool:
    global _INSTALLED, _THREAD
    with _LOCK:
        if _INSTALLED and _THREAD is not None and _THREAD.is_alive():
            return True

        _ensure_canonical_guard()
        _STOP.clear()
        _THREAD = threading.Thread(
            target=_monitor,
            name="stalled-writer-release-guard-v21",
            daemon=True,
        )
        _THREAD.start()
        _INSTALLED = bool(_THREAD.is_alive())
        os.environ["NIJA_STALLED_WRITER_RELEASE_GUARD_INSTALLED"] = (
            "1" if _INSTALLED else "0"
        )
        logger.critical(
            "STALLED_WRITER_RELEASE_GUARD_INSTALLED marker=%s thread_alive=%s "
            "timeout_s=%s",
            _MARKER,
            _THREAD.is_alive(),
            os.environ.get("NIJA_STALLED_WRITER_RELEASE_TIMEOUT_S", "360"),
        )
        return _INSTALLED


def install() -> bool:
    return install_import_hook()


__all__ = [
    "RuntimeSnapshot",
    "install",
    "install_import_hook",
    "_runtime_snapshot",
    "_should_release",
    "_release_reason",
    "_trigger_release",
]
