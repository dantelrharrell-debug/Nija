"""Bounded position-fetch generation and supervised-pending startup repair v117.

Production 24eb31c showed two remaining liveness races:

* a v95 broker ``get_positions`` worker can outlive its 12s caller timeout and
  remain the single-flight forever, so every later reconciliation reuses the
  same stuck request;
* post-core convergence may return ``can_execute=False`` while bootstrap is
  still THREADS_STARTING even though exact Redis writer proof and the canonical
  core thread are already healthy, causing bot_main to unwind that healthy
  runtime before RUNNING_SUPERVISED is published.

v117 preserves fail-closed execution.  Timed-out position workers are rotated
by generation after a bounded stale interval; late superseded generations are
never allowed to return authoritative data.  Healthy writer/core runtimes may
remain alive while THREADS_STARTING/RUNNING_SUPERVISED readiness converges, but
only with runtime execution authority explicitly disabled.
"""
from __future__ import annotations

import builtins
import logging
import os
import sys
import threading
import time
from functools import wraps
from types import ModuleType
from typing import Any, Callable

LOGGER = logging.getLogger("nija.position_fetch_generation_v117")
MARKER = "20260816-position-fetch-generation-v117"
_LOCK = threading.RLock()
_IMPORT_LOCAL = threading.local()
_HOOK_FLAG = "_NIJA_POSITION_FETCH_GENERATION_V117_IMPORT_HOOK"
_PATCH_ATTR = "_nija_position_fetch_generation_v117"
_FLIGHTS: dict[int, dict[str, Any]] = {}
_GENERATIONS: dict[int, int] = {}


def _loaded(*names: str) -> ModuleType | None:
    for name in names:
        mod = sys.modules.get(name)
        if isinstance(mod, ModuleType):
            return mod
    return None


def _timeout_s() -> float:
    try:
        return max(0.1, float(os.environ.get("NIJA_POSITION_FETCH_TIMEOUT_S", "12") or 12.0))
    except (TypeError, ValueError):
        return 12.0


def _stale_after_s() -> float:
    timeout = _timeout_s()
    try:
        configured = float(os.environ.get("NIJA_POSITION_FETCH_STALE_GENERATION_S", "0") or 0.0)
    except (TypeError, ValueError):
        configured = 0.0
    if configured > 0:
        return max(timeout + 0.5, min(120.0, configured))
    return max(timeout * 1.5, timeout + 3.0)


def _finish_flight(
    flight: dict[str, Any],
    method: Callable[..., Any],
    self: Any,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> None:
    try:
        flight["result"] = method(self, *args, **kwargs)
    except BaseException as exc:
        flight["error"] = exc
    finally:
        flight["finished_at"] = time.monotonic()
        flight["event"].set()


def _raw_under_v95(method: Callable[..., Any]) -> Callable[..., Any]:
    current = method
    seen: set[int] = set()
    while callable(current) and id(current) not in seen:
        seen.add(id(current))
        if getattr(current, "_nija_position_sync_core_handoff_v95", False):
            wrapped = getattr(current, "__wrapped__", None)
            if callable(wrapped):
                current = wrapped
                continue
        break
    return current


def _bounded_generation(method: Callable[..., Any], broker_name: str) -> Callable[..., Any]:
    raw = _raw_under_v95(method)

    @wraps(method)
    def get_positions_v117(self: Any, *args: Any, **kwargs: Any):
        key = id(self)
        now = time.monotonic()
        stale_after = _stale_after_s()
        with _LOCK:
            flight = _FLIGHTS.get(key)
            started_new = False
            if flight is not None and not flight["event"].is_set():
                age = max(0.0, now - float(flight.get("started_at", now)))
                if age >= stale_after:
                    flight["superseded"] = True
                    LOGGER.critical(
                        "POSITION_FETCH_V117_GENERATION_SUPERSEDED marker=%s broker=%s generation=%s age_s=%.2f stale_after_s=%.2f late_result_discarded=true",
                        MARKER,
                        broker_name,
                        flight.get("generation"),
                        age,
                        stale_after,
                    )
                    flight = None
            elif flight is not None and flight["event"].is_set():
                _FLIGHTS.pop(key, None)
                flight = None

            if flight is None:
                generation = int(_GENERATIONS.get(key, 0)) + 1
                _GENERATIONS[key] = generation
                flight = {
                    "event": threading.Event(),
                    "result": None,
                    "error": None,
                    "started_at": time.monotonic(),
                    "finished_at": 0.0,
                    "generation": generation,
                    "superseded": False,
                    "broker_name": broker_name,
                }
                _FLIGHTS[key] = flight
                thread = threading.Thread(
                    target=_finish_flight,
                    args=(flight, raw, self, args, dict(kwargs)),
                    name=f"position-fetch-v117-{broker_name}-g{generation}",
                    daemon=True,
                )
                flight["thread"] = thread
                thread.start()
                started_new = True

        timeout = _timeout_s()
        if not flight["event"].wait(timeout=timeout):
            age = max(0.0, time.monotonic() - float(flight.get("started_at", 0.0) or 0.0))
            LOGGER.critical(
                "POSITION_FETCH_V117_TIMEOUT marker=%s broker=%s generation=%s timeout_s=%.2f age_s=%.2f single_flight_reused=%s synthetic_empty_snapshot=false",
                MARKER,
                broker_name,
                flight.get("generation"),
                timeout,
                age,
                str(not started_new).lower(),
            )
            raise TimeoutError(
                f"position snapshot timed out for {broker_name} after {timeout:.2f}s generation={flight.get('generation')}"
            )

        with _LOCK:
            current = _FLIGHTS.get(key)
            authoritative_generation = current is flight and not bool(flight.get("superseded"))
            if authoritative_generation:
                _FLIGHTS.pop(key, None)

        if not authoritative_generation:
            LOGGER.warning(
                "POSITION_FETCH_V117_STALE_RESULT_DISCARDED marker=%s broker=%s generation=%s current_generation=%s",
                MARKER,
                broker_name,
                flight.get("generation"),
                current.get("generation") if isinstance(current, dict) else "none",
            )
            raise TimeoutError(
                f"stale position snapshot generation discarded for {broker_name} generation={flight.get('generation')}"
            )

        error = flight.get("error")
        if error is not None:
            raise error
        return flight.get("result")

    setattr(get_positions_v117, _PATCH_ATTR, True)
    setattr(get_positions_v117, "__wrapped__", method)
    return get_positions_v117


def _patch_broker_manager() -> bool:
    mod = _loaded("bot.broker_manager", "broker_manager")
    if mod is None:
        return True
    patched = False
    for class_name in ("CoinbaseBroker", "KrakenBroker", "OKXBroker", "AlpacaBroker"):
        cls = getattr(mod, class_name, None)
        if not isinstance(cls, type):
            continue
        current = getattr(cls, "get_positions", None)
        if not callable(current):
            continue
        if getattr(current, _PATCH_ATTR, False):
            patched = True
            continue
        cls.get_positions = _bounded_generation(current, class_name.replace("Broker", "").lower())
        patched = True
        LOGGER.critical(
            "POSITION_FETCH_V117_BROKER_PATCHED marker=%s broker_class=%s timeout_s=%.2f stale_after_s=%.2f",
            MARKER,
            class_name,
            _timeout_s(),
            _stale_after_s(),
        )
    return patched or mod is not None


def _bootstrap_state() -> str:
    for name in ("bot.bootstrap_state_machine", "bootstrap_state_machine"):
        mod = _loaded(name)
        if mod is None:
            continue
        try:
            fsm = mod.get_bootstrap_fsm()
            state = getattr(fsm, "state", getattr(fsm, "current_state", ""))
            return str(getattr(state, "value", state) or "")
        except Exception:
            continue
    return ""


def _writer_core_healthy(runtime: Any, trading_thread: Any) -> bool:
    if runtime is None or bool(getattr(runtime, "lost", True)) or not bool(getattr(runtime, "acquired", False)):
        return False
    if bool(getattr(runtime, "_local_fallback", False)):
        return False
    try:
        if trading_thread is None or not trading_thread.is_alive():
            return False
    except Exception:
        return False
    registered = getattr(runtime, "_core_thread", None)
    if registered is not trading_thread:
        return False
    if os.environ.get("NIJA_PROCESS_EXIT_REQUESTED", "").strip().lower() in {"1", "true", "yes"}:
        return False
    try:
        from bot.writer_generation_handoff_v45_patch import _prove_process_writer
        proof = _prove_process_writer()
        if isinstance(proof, tuple):
            if not bool(proof[0]):
                return False
        elif not bool(proof):
            return False
    except Exception:
        return False
    return True


def _patch_bot_main() -> bool:
    mod = _loaded("bot.bot_main", "bot_main")
    if mod is None:
        return True
    current = getattr(mod, "_perform_post_core_activation_convergence", None)
    if not callable(current) or getattr(current, _PATCH_ATTR, False):
        return callable(current)

    @wraps(current)
    def supervised_pending(runtime: Any, trading_thread: Any, *args: Any, **kwargs: Any) -> bool:
        result = bool(current(runtime, trading_thread, *args, **kwargs))
        if result:
            return True
        state = _bootstrap_state()
        if state in {"THREADS_STARTING", "RUNNING_SUPERVISED"} and _writer_core_healthy(runtime, trading_thread):
            os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] = "0"
            os.environ["NIJA_EXECUTION_ACTIVE"] = "false"
            LOGGER.critical(
                "POST_CORE_V117_SUPERVISED_PENDING marker=%s bootstrap=%s exact_writer=true core_alive=true execution_fail_closed=true",
                MARKER,
                state,
            )
            return True
        return False

    setattr(supervised_pending, _PATCH_ATTR, True)
    mod._perform_post_core_activation_convergence = supervised_pending
    return True


def _patch_loaded() -> bool:
    return bool(_patch_broker_manager() and _patch_bot_main())


def install_import_hook() -> bool:
    with _LOCK:
        ready = _patch_loaded()
        if not getattr(builtins, _HOOK_FLAG, False):
            original_import = builtins.__import__

            @wraps(original_import)
            def importing(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
                result = original_import(name, globals, locals, fromlist, level)
                if getattr(_IMPORT_LOCAL, "active", False):
                    return result
                text = str(name or "")
                if "broker_manager" in text or "bot_main" in text:
                    _IMPORT_LOCAL.active = True
                    try:
                        _patch_loaded()
                    finally:
                        _IMPORT_LOCAL.active = False
                return result

            builtins.__import__ = importing
            setattr(builtins, _HOOK_FLAG, True)

        os.environ["NIJA_POSITION_FETCH_GENERATION_V117_INSTALLED"] = "1"
        LOGGER.critical(
            "POSITION_FETCH_GENERATION_V117_INSTALLED marker=%s timeout_s=%.2f stale_after_s=%.2f supervised_threads_starting=true late_generation_discard=true initial_patch_ready=%s",
            MARKER,
            _timeout_s(),
            _stale_after_s(),
            ready,
        )
        return True


def install() -> bool:
    return install_import_hook()


__all__ = ["MARKER", "install", "install_import_hook"]
