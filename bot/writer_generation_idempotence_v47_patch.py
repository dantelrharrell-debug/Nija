"""NIJA v47 convergence guard for v45 heartbeat-generation patching.

v45 correctly moved process-writer generation back under EntrypointWriterAuthority,
but the legacy authority-heartbeat generation-scope watchdog can repeatedly
reinstall its writer. v45 then immediately replaces it again, producing a
high-frequency patch ping-pong and CRITICAL log storm.

v47 makes that boundary idempotent. Once the v45 heartbeat writer owns the
AuthorityHeartbeatMonitor method, subsequent legacy scope-patch attempts become
no-ops. It also replaces v45's scope patch helper with a stable implementation
that does not recreate wrapper functions on every watchdog pass.

No writer authority is granted here. No Redis lock is created, extended,
deleted, or stolen. No Kraken, capital, SEAK, readiness, risk, or dispatch gate
is changed.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
import time
from functools import wraps
from types import ModuleType
from typing import Any

LOGGER = logging.getLogger("nija.writer_generation_idempotence_v47")
MARKER = "20260808-writer-generation-idempotence-v47"

_LOCK = threading.RLock()
_INSTALLED = False
_WATCHDOG_STARTED = False
_SCOPE_WRAPPER_MARK = "_nija_writer_generation_idempotence_v47_scope_wrapper"
_SCOPE_GENERATION_MARK = "_nija_writer_generation_idempotence_v47_generation"
_V45_PATCHER_MARK = "_nija_writer_generation_idempotence_v47_v45_patcher"
_MODULE_MARK = "_nija_writer_generation_idempotence_v47_converged"

_V45_NAMES = (
    "nija_writer_generation_handoff_v45_prebot",
    "bot.writer_generation_handoff_v45_patch",
    "writer_generation_handoff_v45_patch",
)
_SCOPE_NAMES = ("authority_heartbeat_generation_scope_patch",)


def _modules(names: tuple[str, ...]) -> list[ModuleType]:
    found: list[ModuleType] = []
    seen: set[int] = set()
    for name in names:
        module = sys.modules.get(name)
        if isinstance(module, ModuleType) and id(module) not in seen:
            seen.add(id(module))
            found.append(module)
    return found


def _heartbeat_writer(target: ModuleType) -> Any:
    cls = getattr(target, "AuthorityHeartbeatMonitor", None)
    return getattr(cls, "_write_heartbeat_to_redis", None) if isinstance(cls, type) else None


def _is_v45_heartbeat(target: ModuleType, v45: ModuleType) -> bool:
    marker = str(
        getattr(v45, "_HEARTBEAT_PATCH", "_nija_writer_generation_handoff_v45_heartbeat")
        or "_nija_writer_generation_handoff_v45_heartbeat"
    )
    return bool(getattr(_heartbeat_writer(target), marker, False))


def _process_generation(v45: ModuleType) -> tuple[int, str]:
    proof_fn = getattr(v45, "_prove_process_writer", None)
    if not callable(proof_fn):
        return 0, "v45_process_writer_proof_unavailable"
    try:
        proof, reason = proof_fn()
    except Exception as exc:
        return 0, f"v45_process_writer_proof_error:{type(exc).__name__}:{exc}"
    if proof is None:
        return 0, str(reason or "process_writer_proof_failed")
    try:
        generation = int(proof.get("generation", 0) or 0)
    except Exception:
        generation = 0
    if generation <= 0:
        return 0, "process_writer_generation_invalid"
    return generation, ""


def _converge_scope_module(v45: ModuleType, scope: ModuleType) -> bool:
    changed = False

    generation_fn = getattr(scope, "_platform_generation", None)
    if not getattr(generation_fn, _SCOPE_GENERATION_MARK, False):
        def process_generation() -> tuple[int, str]:
            return _process_generation(v45)

        setattr(process_generation, _SCOPE_GENERATION_MARK, True)
        scope._platform_generation = process_generation
        changed = True

    current = getattr(scope, "_patch_module", None)
    if not getattr(current, _SCOPE_WRAPPER_MARK, False):
        legacy = current

        @wraps(legacy if callable(legacy) else (lambda _target: False))
        def patch_module(target: ModuleType) -> bool:
            # Once v45 owns the heartbeat method, do not call the legacy scope
            # patcher again. It would overwrite v45 and restart the ping-pong.
            if _is_v45_heartbeat(target, v45):
                return True
            result = False
            if callable(legacy):
                result = bool(legacy(target))
            patch_v45 = getattr(v45, "_patch_heartbeat_module", None)
            if callable(patch_v45):
                result = bool(patch_v45(target)) or result
            return result

        setattr(patch_module, _SCOPE_WRAPPER_MARK, True)
        if callable(legacy):
            setattr(patch_module, "__wrapped__", legacy)
        scope._patch_module = patch_module
        changed = True

    if not bool(getattr(scope, _MODULE_MARK, False)):
        setattr(scope, _MODULE_MARK, True)
        changed = True

    if changed:
        LOGGER.critical(
            "WRITER_GENERATION_V47_SCOPE_CONVERGED marker=%s module=%s legacy_repatch_suppressed=true",
            MARKER,
            scope.__name__,
        )
    return True


def _patch_v45_module(v45: ModuleType) -> bool:
    current = getattr(v45, "_patch_scope_module", None)
    if getattr(current, _V45_PATCHER_MARK, False):
        return True

    def stable_scope_patcher(scope: ModuleType) -> bool:
        return _converge_scope_module(v45, scope)

    setattr(stable_scope_patcher, _V45_PATCHER_MARK, True)
    if callable(current):
        setattr(stable_scope_patcher, "__wrapped__", current)
    v45._patch_scope_module = stable_scope_patcher
    LOGGER.critical(
        "WRITER_GENERATION_V47_V45_PATCHER_CONVERGED marker=%s module=%s stable=true",
        MARKER,
        v45.__name__,
    )
    return True


def reconcile_once() -> dict[str, Any]:
    v45_modules = _modules(_V45_NAMES)
    scope_modules = _modules(_SCOPE_NAMES)
    patched_v45 = 0
    patched_scope = 0

    for v45 in v45_modules:
        if _patch_v45_module(v45):
            patched_v45 += 1
        for scope in scope_modules:
            if _converge_scope_module(v45, scope):
                patched_scope += 1

    return {
        "v45_modules": len(v45_modules),
        "scope_modules": len(scope_modules),
        "patched_v45": patched_v45,
        "patched_scope": patched_scope,
        "ready": bool(v45_modules),
    }


def _watchdog() -> None:
    # v45 already owns the import hooks. This quiet watchdog only catches a
    # later alias/module load and never emits per-pass success logs.
    deadline = time.monotonic() + max(
        120.0,
        float(os.environ.get("NIJA_WRITER_GENERATION_V47_WATCHDOG_S", "900") or 900),
    )
    while time.monotonic() < deadline:
        try:
            reconcile_once()
        except Exception:
            LOGGER.debug("WRITER_GENERATION_V47_RECONCILE_DEFERRED", exc_info=True)
        time.sleep(1.0)


def install() -> bool:
    global _INSTALLED, _WATCHDOG_STARTED
    with _LOCK:
        reconcile_once()
        if not _WATCHDOG_STARTED:
            _WATCHDOG_STARTED = True
            threading.Thread(
                target=_watchdog,
                name="WriterGenerationIdempotenceV47",
                daemon=True,
            ).start()
        _INSTALLED = True
        os.environ["NIJA_WRITER_GENERATION_IDEMPOTENCE_V47_INSTALLED"] = "1"
        LOGGER.critical(
            "WRITER_GENERATION_IDEMPOTENCE_V47_INSTALLED marker=%s legacy_repatch_suppressed=true fail_closed=true",
            MARKER,
        )
        return True


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "reconcile_once",
    "_converge_scope_module",
    "_patch_v45_module",
    "_process_generation",
]
