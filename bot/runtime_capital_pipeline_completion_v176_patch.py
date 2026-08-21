"""Runtime capital pipeline completion convergence v176.

Production after v175 proved LIVE_ACTIVE, writer authority, three-broker
connectivity, and three-broker position readiness, but the proactive v137
capital refresh path still exposed two liveness contradictions:

* v166 correctly reduced proactive broker collection to a 30 second synchronous
  budget and intended a 50 second total coordinator deadline, while v142 still
  observed an 80 second deadline on the caller thread.  The worker thread had
  the proactive trigger context, but the caller thread that evaluates the v142
  total deadline did not reliably retain it through the accumulated wrapper
  chain; and
* CapitalAuthority performs best-effort warm-start persistence synchronously at
  the end of an accepted publication.  Slow filesystem/fsync work can therefore
  hold the coordinator open after capital has already been atomically accepted,
  causing v142 to retire an otherwise successful generation.

v176 closes those liveness gaps without changing capital truth.  It reasserts
proactive trigger context around the effective coordinator entrypoint, caps the
proactive v142 total deadline to v166's existing bounded deadline, and moves
non-authoritative warm-start persistence off the live publication critical path
with a single coalescing daemon worker.

The patch does not extend freshness/publication expiry, accept partial capital,
fabricate balances, promote stale data, force activation/trading, mutate writer
or nonce authority, or bypass risk/execution/order gates.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
import time
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.runtime_capital_pipeline_completion_v176")
MARKER = "20260821-runtime-capital-pipeline-completion-v176"
RELEASE_ID = "20260821-runtime-convergence-v176"
_READY_FLAG = "NIJA_RUNTIME_CAPITAL_PIPELINE_COMPLETION_V176_READY"
_PATCH_ATTR = "_nija_runtime_capital_pipeline_completion_v176"
_LOCK = threading.RLock()
_PERSIST_LOCK = threading.RLock()
_PERSIST_RUNNING = False
_PERSIST_PENDING = False
_PERSIST_WORKER: threading.Thread | None = None
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in _TRUE


def _live_runtime() -> bool:
    return bool(
        _truthy(os.environ.get("LIVE_CAPITAL_VERIFIED"))
        and not _truthy(os.environ.get("DRY_RUN_MODE"))
        and not _truthy(os.environ.get("PAPER_MODE"))
    )


def _flow() -> Any:
    return importlib.import_module("bot.capital_flow_state_machine")


def _v142() -> Any:
    return importlib.import_module("bot.capital_publication_liveness_v142_patch")


def _v166() -> Any:
    return importlib.import_module("bot.runtime_capital_refresh_ownership_v166_patch")


def _patch_proactive_deadline_context() -> bool:
    """Keep proactive v137 work inside v166's existing total runtime budget."""
    try:
        v142 = _v142()
        current = getattr(v142, "_runtime_pipeline_deadline_seconds", None)
    except Exception:
        return False
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True
    original = current

    @wraps(original)
    def runtime_pipeline_deadline_v176() -> float:
        base = max(10.0, float(original()))
        try:
            v166 = _v166()
            proactive = bool(v166._is_proactive_trigger())
            if not proactive:
                return base
            bounded = max(10.0, float(v166._proactive_pipeline_deadline_seconds()))
            # Only shorten proactive work to the deadline v166 already owns.
            # Never lengthen any stricter deadline installed elsewhere.
            return min(base, bounded)
        except Exception:
            return base

    setattr(runtime_pipeline_deadline_v176, _PATCH_ATTR, True)
    setattr(runtime_pipeline_deadline_v176, "__wrapped__", original)
    v142._runtime_pipeline_deadline_seconds = runtime_pipeline_deadline_v176
    return True


def _patch_execute_trigger_context() -> bool:
    """Reassert v166 trigger context on the thread that owns v142's deadline wait."""
    try:
        flow = _flow()
        cls = getattr(flow, "CapitalRefreshCoordinator", None)
    except Exception:
        return False
    if not isinstance(cls, type):
        return False
    current = getattr(cls, "execute_refresh", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True
    original = current

    @wraps(original)
    def execute_refresh_v176(
        self: Any,
        broker_map: dict[str, Any],
        trigger: str = "coordinator",
        open_exposure_usd: float = 0.0,
    ) -> Any:
        try:
            v166 = _v166()
            setter = getattr(v166, "_set_trigger", None)
            restorer = getattr(v166, "_restore_trigger", None)
        except Exception:
            setter = None
            restorer = None
            v166 = None
        if not callable(setter) or not callable(restorer):
            return original(
                self,
                broker_map=broker_map,
                trigger=trigger,
                open_exposure_usd=open_exposure_usd,
            )

        previous = setter(trigger)
        try:
            proactive = bool(v166._is_proactive_trigger(trigger))
            if proactive:
                try:
                    effective = float(_v142()._runtime_pipeline_deadline_seconds())
                except Exception:
                    effective = -1.0
                LOGGER.info(
                    "CAPITAL_V176_PROACTIVE_CALLER_CONTEXT marker=%s trigger=%s "
                    "caller_context=true deadline_s=%.1f freshness_extended=false",
                    MARKER,
                    trigger,
                    effective,
                )
            return original(
                self,
                broker_map=broker_map,
                trigger=trigger,
                open_exposure_usd=open_exposure_usd,
            )
        finally:
            restorer(previous)

    setattr(execute_refresh_v176, _PATCH_ATTR, True)
    setattr(execute_refresh_v176, "__wrapped__", original)
    cls.execute_refresh = execute_refresh_v176
    return True


def _patch_async_best_effort_persistence() -> bool:
    """Keep warm-start disk persistence out of the live publication critical path."""
    try:
        ca = importlib.import_module("bot.capital_authority")
        cls = getattr(ca, "CapitalAuthority", None)
    except Exception:
        return False
    if not isinstance(cls, type):
        return False
    current = getattr(cls, "_save_cached_state", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True
    original = current

    @wraps(original)
    def save_cached_state_v176(self: Any) -> None:
        global _PERSIST_RUNNING, _PERSIST_PENDING, _PERSIST_WORKER

        # Preserve deterministic synchronous behavior outside the real live
        # runtime (including unit tests and paper/dry-run environments).
        if not _live_runtime():
            original(self)
            return

        with _PERSIST_LOCK:
            if _PERSIST_RUNNING:
                _PERSIST_PENDING = True
                LOGGER.debug(
                    "CAPITAL_V176_PERSISTENCE_COALESCED marker=%s running=true",
                    MARKER,
                )
                return
            _PERSIST_RUNNING = True
            _PERSIST_PENDING = False

        def _worker() -> None:
            global _PERSIST_RUNNING, _PERSIST_PENDING, _PERSIST_WORKER
            while True:
                started = time.monotonic()
                try:
                    original(self)
                except BaseException as exc:
                    # Persistence is explicitly best-effort in CapitalAuthority;
                    # a disk failure must not mutate publication truth.
                    LOGGER.warning(
                        "CAPITAL_V176_PERSISTENCE_ERROR marker=%s error=%s:%s "
                        "capital_publication_unchanged=true",
                        MARKER,
                        type(exc).__name__,
                        exc,
                    )
                elapsed = max(0.0, time.monotonic() - started)
                if elapsed >= 5.0:
                    LOGGER.warning(
                        "CAPITAL_V176_PERSISTENCE_SLOW marker=%s elapsed_s=%.2f "
                        "publication_path_blocked=false",
                        MARKER,
                        elapsed,
                    )
                with _PERSIST_LOCK:
                    if _PERSIST_PENDING:
                        _PERSIST_PENDING = False
                        continue
                    _PERSIST_RUNNING = False
                    _PERSIST_WORKER = None
                    return

        worker = threading.Thread(
            target=_worker,
            name="capital-state-persist-v176",
            daemon=True,
        )
        with _PERSIST_LOCK:
            _PERSIST_WORKER = worker
        try:
            worker.start()
        except BaseException:
            with _PERSIST_LOCK:
                _PERSIST_RUNNING = False
                _PERSIST_PENDING = False
                _PERSIST_WORKER = None
            raise
        LOGGER.debug(
            "CAPITAL_V176_PERSISTENCE_ASYNC marker=%s single_worker=true "
            "publication_path_blocked=false",
            MARKER,
        )

    setattr(save_cached_state_v176, _PATCH_ATTR, True)
    setattr(save_cached_state_v176, "__wrapped__", original)
    cls._save_cached_state = save_cached_state_v176
    return True


def _patch_release_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_capital_pipeline_completion_v176"] = _READY_FLAG
        return True
    except Exception:
        return False


def install() -> bool:
    with _LOCK:
        deadline_ok = _patch_proactive_deadline_context()
        context_ok = _patch_execute_trigger_context()
        persistence_ok = _patch_async_best_effort_persistence()
        manifest_ok = _patch_release_manifest()
        ready = bool(deadline_ok and context_ok and persistence_ok and manifest_ok)
        os.environ[_READY_FLAG] = "1" if ready else "0"
        if not ready:
            LOGGER.critical(
                "RUNTIME_CAPITAL_PIPELINE_COMPLETION_V176_FAILED marker=%s "
                "deadline_ok=%s context_ok=%s persistence_ok=%s manifest_ok=%s "
                "trading_fail_closed=true",
                MARKER,
                str(deadline_ok).lower(),
                str(context_ok).lower(),
                str(persistence_ok).lower(),
                str(manifest_ok).lower(),
            )
            return False

        try:
            proactive_deadline = float(_v166()._proactive_pipeline_deadline_seconds())
        except Exception:
            proactive_deadline = -1.0
        LOGGER.critical(
            "RUNTIME_CAPITAL_PIPELINE_COMPLETION_V176 marker=%s ready=true "
            "proactive_caller_context=true proactive_pipeline_deadline_s=%.1f "
            "best_effort_persistence_async=true persistence_single_worker=true "
            "freshness_extended=false publication_expiry_extended=false "
            "partial_aggregation_gate_unchanged=true stale_promoted=false forced_trade=false "
            "safety_gates_bypassed=false",
            MARKER,
            proactive_deadline,
        )
        return True


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "RELEASE_ID",
    "install",
    "install_import_hook",
    "_patch_proactive_deadline_context",
    "_patch_execute_trigger_context",
    "_patch_async_best_effort_persistence",
    "_live_runtime",
]
