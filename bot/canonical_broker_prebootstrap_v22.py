"""Initialize the canonical broker manager before SelfHealingStartup.

The production startup path previously waited for SelfHealingStartup to return a
connected broker before initializing the canonical MultiAccountBrokerManager.
SelfHealingStartup itself delegates broker connection to that manager, creating a
circular dependency that can leave the writer process in LIVE_PENDING_CONFIRMATION
with no manager, no capital snapshot, and no scan cycles.

This module patches the canonical bot_main writer-acquisition function. After
Redis writer authority is acquired and synchronously verified, the existing
canonical manager singleton is initialized before SelfHealingStartup runs. In
live mode initialization may continue in a daemon worker after a strict liveness
handoff proof is satisfied, allowing bot_main to start and register the real core
thread without granting execution authority. A failed prebootstrap releases only
this process's own lease and returns startup failure; no order, authority, nonce,
kill-switch, risk, or state gate is bypassed.

Wrapper-order safety
--------------------
The writer-acquisition function is also wrapped by authority/recovery convergence
layers (notably production_readiness_v39 and runtime_execution_convergence_v32).
This module must preserve those wrappers. Repatching therefore detects an existing
v22 layer anywhere in the __wrapped__ chain instead of unwrapping the chain to the
base function. Stripping those layers disables bounded fresh-epoch writer recovery
when a Redis writer lock disappears.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
import time
from functools import wraps
from types import ModuleType
from typing import Any, Callable

logger = logging.getLogger("nija.canonical_broker_prebootstrap")

_MARKER = "20260723-canonical-broker-prebootstrap-v22"
_HANDOFF_MARKER = "20260814-prebootstrap-core-handoff-v94"
_WRAPPER_PRESERVATION_MARKER = "20260808-v22-writer-wrapper-preservation-v1"
_LOCK = threading.RLock()
_READY = False
_INSTALLED = False
_ACQUIRE_WRAP_ATTR = "_nija_canonical_broker_prebootstrap_acquire_v22"
_MAIN_WRAP_ATTR = "_nija_canonical_broker_prebootstrap_main_v22"
_TRUTHY = {"1", "true", "yes", "enabled"}
_HANDOFF_READINESS_KEYS = (
    "broker_connected",
    "balance_hydrated",
    "capital_ready",
    "risk_ready",
)


def _canonical_manager() -> Any:
    module = importlib.import_module("bot.multi_account_broker_manager")
    manager = getattr(module, "multi_account_broker_manager", None)
    if manager is None:
        getter = getattr(module, "get_broker_manager", None)
        manager = getter() if callable(getter) else None
    if manager is None:
        raise RuntimeError("canonical MultiAccountBrokerManager singleton unavailable")
    return manager


def _manager_contract(manager: Any) -> tuple[bool, str]:
    if not bool(getattr(manager, "_fsm_initialized", False)):
        return False, "fsm_not_initialized"

    has_sources = getattr(manager, "has_registered_sources", None)
    if callable(has_sources):
        try:
            if not bool(has_sources()):
                return False, "no_registered_platform_source"
        except Exception as exc:
            return False, f"source_contract_error:{type(exc).__name__}:{exc}"

    attempted = getattr(manager, "has_attempted_connections", None)
    if callable(attempted):
        try:
            if not bool(attempted()):
                return False, "broker_registration_not_finalized"
        except Exception as exc:
            return False, f"attempt_contract_error:{type(exc).__name__}:{exc}"

    return True, "manager_ready"


def _repair_capital_fsm_latch(manager: Any, cause: BaseException) -> bool:
    if bool(getattr(manager, "_fsm_initialized", False)):
        return True

    repair = getattr(manager, "_init_capital_fsm", None)
    if not callable(repair):
        return False

    logger.critical(
        "CANONICAL_BROKER_PREBOOTSTRAP_V22_LATCH_REPAIR_BEGIN marker=%s cause=%s:%s",
        _MARKER,
        type(cause).__name__,
        cause,
    )
    repair()
    repaired = bool(getattr(manager, "_fsm_initialized", False))
    logger.critical(
        "CANONICAL_BROKER_PREBOOTSTRAP_V22_LATCH_REPAIR_RESULT marker=%s repaired=%s",
        _MARKER,
        repaired,
    )
    return repaired


def _initialize_manager(manager: Any) -> None:
    initialize = getattr(manager, "initialize", None)
    if not callable(initialize):
        raise RuntimeError("MultiAccountBrokerManager.initialize is unavailable")

    try:
        initialize()
    except Exception as first_exc:
        # Retry only the confirmed stale InitRegistry/FSM-latch case. Broker,
        # credential, balance, and network failures must remain fail-closed.
        if bool(getattr(manager, "_fsm_initialized", False)):
            raise
        if not _repair_capital_fsm_latch(manager, first_exc):
            raise
        logger.warning(
            "CANONICAL_BROKER_PREBOOTSTRAP_V22_INITIALIZE_RETRY marker=%s first_error=%s:%s",
            _MARKER,
            type(first_exc).__name__,
            first_exc,
        )
        initialize()

    # Some legacy initialize paths return successfully after an InitRegistry
    # short-circuit without setting the capital-FSM latch. Treat that exact
    # silent state as recoverable, while keeping all broker/auth/balance
    # failures fail-closed.
    if not bool(getattr(manager, "_fsm_initialized", False)):
        silent_latch = RuntimeError(
            "initialize returned without setting _fsm_initialized"
        )
        if not _repair_capital_fsm_latch(manager, silent_latch):
            raise RuntimeError(
                "MultiAccountBrokerManager.initialize completed without "
                "initializing the capital FSM"
            )
        logger.critical(
            "CANONICAL_BROKER_PREBOOTSTRAP_V22_SILENT_LATCH_REPAIRED marker=%s",
            _MARKER,
        )


def _platform_counts(manager: Any) -> tuple[int, int, list[str]]:
    brokers = getattr(manager, "platform_brokers", None)
    if callable(brokers):
        brokers = brokers()
    if brokers is None:
        brokers = getattr(manager, "_platform_brokers", {})

    try:
        items = list(dict(brokers or {}).items())
    except Exception:
        items = []

    connected_names: list[str] = []
    for broker_type, broker in items:
        if broker is None or not bool(getattr(broker, "connected", False)):
            continue
        name = getattr(broker_type, "value", None) or str(broker_type)
        connected_names.append(str(name).lower())

    return len(items), len(connected_names), sorted(set(connected_names))


def _is_live_mode() -> bool:
    try:
        runtime_mode = importlib.import_module("bot.runtime_mode")
        resolve = getattr(runtime_mode, "resolve_runtime_mode", None)
        if not callable(resolve):
            return False
        return bool(resolve().is_live)
    except Exception:
        logger.debug("v94 runtime-mode resolution failed; using synchronous path", exc_info=True)
        return False


def _writer_handoff_proof() -> tuple[bool, str]:
    acquired = os.getenv("NIJA_WRITER_LEASE_ACQUIRED", "").strip().lower() in _TRUTHY
    if not acquired:
        return False, "writer_lease_not_acquired"

    token = os.getenv("NIJA_WRITER_FENCING_TOKEN", "").strip()
    if not token:
        return False, "writer_fencing_token_missing"

    raw_generation = os.getenv("NIJA_WRITER_LEASE_GENERATION", "").strip()
    try:
        generation = int(raw_generation)
    except (TypeError, ValueError):
        return False, "writer_generation_invalid"
    if generation <= 0:
        return False, "writer_generation_not_positive"

    return True, "writer_fenced"


def _readiness_handoff_proof() -> tuple[bool, str, dict[str, bool]]:
    try:
        readiness = importlib.import_module("bot.readiness_table")
        snapshot_fn = getattr(readiness, "snapshot", None)
        if not callable(snapshot_fn):
            return False, "readiness_snapshot_unavailable", {}
        snapshot = dict(snapshot_fn() or {})
    except Exception as exc:
        return False, f"readiness_snapshot_error:{type(exc).__name__}:{exc}", {}

    missing = [key for key in _HANDOFF_READINESS_KEYS if not bool(snapshot.get(key, False))]
    if missing:
        return False, "readiness_false:" + ",".join(missing), snapshot
    return True, "readiness_ready", snapshot


def _prebootstrap_handoff_proof(manager: Any) -> tuple[bool, str, dict[str, Any]]:
    writer_ok, writer_reason = _writer_handoff_proof()
    if not writer_ok:
        return False, writer_reason, {}

    contract_ok, contract_reason = _manager_contract(manager)
    if not contract_ok:
        return False, contract_reason, {}

    registered, connected, names = _platform_counts(manager)
    if connected < 1:
        return False, "no_connected_platform_broker", {
            "registered": registered,
            "connected": connected,
            "brokers": names,
        }

    readiness_ok, readiness_reason, snapshot = _readiness_handoff_proof()
    if not readiness_ok:
        return False, readiness_reason, {
            "registered": registered,
            "connected": connected,
            "brokers": names,
            "readiness": snapshot,
        }

    return True, "handoff_ready", {
        "registered": registered,
        "connected": connected,
        "brokers": names,
        "readiness": snapshot,
    }


def _live_initialize_with_handoff(manager: Any) -> bool:
    """Initialize in a daemon worker and return True only for an early v94 handoff."""

    try:
        timeout_s = float(os.getenv("NIJA_PREBOOTSTRAP_HANDOFF_TIMEOUT_S", "45"))
    except (TypeError, ValueError):
        timeout_s = 45.0
    timeout_s = max(1.0, timeout_s)

    done = threading.Event()
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            _initialize_manager(manager)
        except BaseException as exc:
            errors.append(exc)
        finally:
            done.set()

    thread = threading.Thread(
        target=worker,
        name="nija-canonical-broker-init-v94",
        daemon=True,
    )
    thread.start()

    deadline = time.monotonic() + timeout_s
    last_reason = "initializing"
    while True:
        if done.is_set():
            if errors:
                raise errors[0]
            return False

        proof_ok, proof_reason, detail = _prebootstrap_handoff_proof(manager)
        last_reason = proof_reason
        if proof_ok:
            logger.critical(
                "CANONICAL_BROKER_PREBOOTSTRAP_V94_EARLY_HANDOFF marker=%s registered=%d connected=%d brokers=%s writer_generation=%s readiness=%s initializer_alive=%s execution_authority_granted=false",
                _HANDOFF_MARKER,
                int(detail.get("registered", 0)),
                int(detail.get("connected", 0)),
                ",".join(detail.get("brokers", [])),
                os.getenv("NIJA_WRITER_LEASE_GENERATION", ""),
                detail.get("readiness", {}),
                thread.is_alive(),
            )
            return True

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError(
                "canonical broker prebootstrap live handoff timed out "
                f"after {timeout_s:.1f}s (last_blocker={last_reason})"
            )
        done.wait(timeout=min(0.05, remaining))


def prepare_canonical_broker_runtime() -> Any:
    """Prepare the canonical manager after writer verification.

    Non-live modes retain the original synchronous behavior. In live mode the
    manager initializer may continue in one daemon worker only after the strict
    v94 liveness proof succeeds. This function never marks authority, nonce,
    strategy, execution, or bootstrap readiness.
    """

    global _READY
    with _LOCK:
        manager = _canonical_manager()
        contract_ok, _ = _manager_contract(manager)
        registered, connected, names = _platform_counts(manager)
        if _READY and contract_ok and connected >= 1:
            logger.info(
                "CANONICAL_BROKER_PREBOOTSTRAP_V22_ALREADY_READY marker=%s registered=%d connected=%d brokers=%s",
                _MARKER,
                registered,
                connected,
                ",".join(names),
            )
            return manager

        live_mode = _is_live_mode()
        logger.critical(
            "CANONICAL_BROKER_PREBOOTSTRAP_V22_BEGIN marker=%s thread=%s live_mode=%s",
            _MARKER,
            threading.current_thread().name,
            live_mode,
        )

        early_handoff = False
        if live_mode:
            early_handoff = _live_initialize_with_handoff(manager)
        else:
            _initialize_manager(manager)

        contract_ok, contract_reason = _manager_contract(manager)
        registered, connected, names = _platform_counts(manager)
        if not contract_ok:
            raise RuntimeError(
                f"canonical broker prebootstrap contract failed: {contract_reason}"
            )
        if connected < 1:
            raise RuntimeError(
                "canonical broker prebootstrap has no connected platform broker "
                f"(registered={registered}, connected={connected})"
            )

        if early_handoff:
            proof_ok, proof_reason, _ = _prebootstrap_handoff_proof(manager)
            if not proof_ok:
                raise RuntimeError(
                    "canonical broker prebootstrap handoff proof regressed before return: "
                    f"{proof_reason}"
                )

        _READY = True
        os.environ["NIJA_CANONICAL_BROKER_PREBOOTSTRAP_V22_READY"] = "1"
        logger.critical(
            "CANONICAL_BROKER_PREBOOTSTRAP_V22_READY marker=%s fsm_initialized=true registered=%d connected=%d brokers=%s early_handoff=%s",
            _MARKER,
            registered,
            connected,
            ",".join(names),
            early_handoff,
        )
        return manager


def _wrapper_chain_has_marker(current: Callable[..., Any], marker_attr: str) -> bool:
    """Return True when any callable in ``current``'s wrapper chain has marker_attr."""
    seen: set[int] = set()
    candidate: Any = current
    while callable(candidate) and id(candidate) not in seen:
        seen.add(id(candidate))
        if bool(getattr(candidate, marker_attr, False)):
            return True
        wrapped = getattr(candidate, "__wrapped__", None)
        if not callable(wrapped):
            break
        candidate = wrapped
    return False


def _patch_writer_acquire(module: ModuleType) -> bool:
    current = getattr(module, "_acquire_writer_authority_before_nonce", None)
    if not callable(current):
        return False

    if _wrapper_chain_has_marker(current, _ACQUIRE_WRAP_ATTR):
        return True

    preserved_existing_layers = callable(getattr(current, "__wrapped__", None))

    @wraps(current)
    def guarded_acquire(*args: Any, **kwargs: Any) -> bool:
        acquired = bool(current(*args, **kwargs))
        if not acquired:
            return False
        try:
            prepare_canonical_broker_runtime()
            return True
        except Exception as exc:
            os.environ["NIJA_CANONICAL_BROKER_PREBOOTSTRAP_V22_READY"] = "0"
            logger.critical(
                "CANONICAL_BROKER_PREBOOTSTRAP_V22_FAILED marker=%s err=%s:%s trading_remains_fail_closed=true",
                _MARKER,
                type(exc).__name__,
                exc,
                exc_info=True,
            )
            release = getattr(module, "_release_writer_authority", None)
            if callable(release):
                try:
                    release()
                except Exception as release_exc:
                    logger.critical(
                        "CANONICAL_BROKER_PREBOOTSTRAP_V22_RELEASE_FAILED marker=%s err=%s:%s",
                        _MARKER,
                        type(release_exc).__name__,
                        release_exc,
                        exc_info=True,
                    )
            return False

    setattr(guarded_acquire, _ACQUIRE_WRAP_ATTR, True)
    setattr(guarded_acquire, "__wrapped__", current)
    setattr(module, "_acquire_writer_authority_before_nonce", guarded_acquire)
    os.environ["NIJA_CANONICAL_BROKER_PREBOOTSTRAP_WRAPPER_PRESERVATION"] = "1"
    logger.critical(
        "CANONICAL_BROKER_PREBOOTSTRAP_V22_ACQUIRE_PATCHED marker=%s wrapper_preservation_marker=%s module=%s existing_layers_preserved=%s",
        _MARKER,
        _WRAPPER_PRESERVATION_MARKER,
        module.__name__,
        preserved_existing_layers,
    )
    return True


def _patch_main(module: ModuleType) -> bool:
    current = getattr(module, "main", None)
    if not callable(current):
        return False
    if _wrapper_chain_has_marker(current, _MAIN_WRAP_ATTR):
        return True

    @wraps(current)
    def guarded_main(*args: Any, **kwargs: Any):
        if not _patch_writer_acquire(module):
            logger.critical(
                "CANONICAL_BROKER_PREBOOTSTRAP_V22_REPATCH_FAILED marker=%s trading_remains_fail_closed=true",
                _MARKER,
            )
            return 1
        return current(*args, **kwargs)

    setattr(guarded_main, _MAIN_WRAP_ATTR, True)
    setattr(guarded_main, "__wrapped__", current)
    setattr(module, "main", guarded_main)
    logger.critical(
        "CANONICAL_BROKER_PREBOOTSTRAP_V22_MAIN_PATCHED marker=%s module=%s",
        _MARKER,
        module.__name__,
    )
    return True


def install_import_hook() -> bool:
    global _INSTALLED
    with _LOCK:
        module = importlib.import_module("bot.bot_main")
        acquire_patched = _patch_writer_acquire(module)
        main_patched = _patch_main(module)
        _INSTALLED = bool(acquire_patched and main_patched)
        os.environ["NIJA_CANONICAL_BROKER_PREBOOTSTRAP_V22_INSTALLED"] = (
            "1" if _INSTALLED else "0"
        )
        if _INSTALLED:
            os.environ["NIJA_CANONICAL_BROKER_PREBOOTSTRAP_WRAPPER_PRESERVATION"] = "1"
        logger.critical(
            "CANONICAL_BROKER_PREBOOTSTRAP_V22_INSTALLED marker=%s wrapper_preservation_marker=%s acquire_patched=%s main_patched=%s",
            _MARKER,
            _WRAPPER_PRESERVATION_MARKER,
            acquire_patched,
            main_patched,
        )
        return _INSTALLED


def install() -> bool:
    return install_import_hook()


__all__ = [
    "install",
    "install_import_hook",
    "prepare_canonical_broker_runtime",
    "_canonical_manager",
    "_manager_contract",
    "_initialize_manager",
    "_platform_counts",
    "_is_live_mode",
    "_writer_handoff_proof",
    "_readiness_handoff_proof",
    "_prebootstrap_handoff_proof",
    "_live_initialize_with_handoff",
    "_wrapper_chain_has_marker",
    "_patch_writer_acquire",
    "_patch_main",
]
