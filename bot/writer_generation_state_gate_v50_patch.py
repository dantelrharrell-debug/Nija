"""Canonical process-writer generation gate convergence v50.

Production showed a process-writer generation regression such as ``prev=3344
current=18`` immediately before writer identity disappeared.  The process writer
and Kraken nonce lease use separate Redis generation domains, but the legacy
TradingStateMachine generation gate still called ``DistributedNonceManager`` and
interpreted its lease token/version as the process-writer generation.  A legacy
dispatch-latch repair could then copy that nonce-derived value into process-writer
environment state.

v50 removes that cross-domain authority path.  A process-writer generation is
accepted only when writer_generation_handoff_v45 can prove the canonical
EntrypointWriterAuthority runtime against its exact Redis lock value, fencing
token, positive TTL, and process-generation key.  The proven generation may
repair local process-writer telemetry, including a contaminated local high-water
mark, because the repair is backed by exact current distributed ownership.
Missing or mismatched proof remains fail-closed.

This patch never creates, renews, deletes, steals, or fabricates a writer lease.
It never grants execution authority, resumes SEAK, connects a broker, or bypasses
capital, nonce, heartbeat, kill-switch, risk, or dispatch gates.
"""
from __future__ import annotations

import builtins
import importlib
import logging
import os
import sys
import threading
from functools import wraps
from types import ModuleType
from typing import Any

LOGGER = logging.getLogger("nija.writer_generation_state_gate_v50")
MARKER = "20260808-writer-generation-state-gate-v50"

_LOCK = threading.RLock()
_INSTALLED = False
_HOOK_FLAG = "_NIJA_WRITER_GENERATION_STATE_GATE_V50_IMPORT_HOOK"
_IMPORTLIB_FLAG = "_NIJA_WRITER_GENERATION_STATE_GATE_V50_IMPORTLIB_HOOK"
_GATE_PATCH = "_nija_writer_generation_state_gate_v50"
_DISPATCH_PATCH = "_nija_writer_generation_state_gate_v50_dispatch"

_TSM_NAMES = ("bot.trading_state_machine", "trading_state_machine")
_V45_NAMES = (
    "nija_writer_generation_handoff_v45_prebot",
    "bot.writer_generation_handoff_v45_patch",
    "writer_generation_handoff_v45_patch",
)
_DISPATCH_NAMES = (
    "bot.trading_state_dispatch_latch_repair_patch",
    "trading_state_dispatch_latch_repair_patch",
)


def _truthy(name: str, default: str = "true") -> bool:
    return str(os.environ.get(name, default) or "").strip().lower() in {
        "1", "true", "yes", "on", "enabled", "y"
    }


def _v45_module() -> ModuleType | None:
    seen: set[int] = set()
    for name in _V45_NAMES:
        module = sys.modules.get(name)
        if isinstance(module, ModuleType) and id(module) not in seen:
            seen.add(id(module))
            if callable(getattr(module, "_prove_process_writer", None)):
                return module
    for name in _V45_NAMES:
        try:
            module = importlib.import_module(name)
        except Exception:
            continue
        if isinstance(module, ModuleType) and callable(
            getattr(module, "_prove_process_writer", None)
        ):
            return module
    return None


def _canonical_process_writer_proof(source: str) -> tuple[dict[str, Any] | None, str]:
    v45 = _v45_module()
    if v45 is None:
        return None, "v45_process_writer_proof_unavailable"
    prove = getattr(v45, "_prove_process_writer", None)
    if not callable(prove):
        return None, "v45_process_writer_proof_unavailable"
    try:
        proof, reason = prove()
    except Exception as exc:
        return None, f"v45_process_writer_proof_error:{type(exc).__name__}:{exc}"
    if proof is None:
        return None, str(reason or "process_writer_proof_failed")
    try:
        generation = int(proof.get("generation", 0) or 0)
    except Exception:
        generation = 0
    token = str(proof.get("token", "") or "").strip()
    if generation <= 0:
        return None, "canonical_generation_invalid"
    if not token:
        return None, "canonical_fencing_token_missing"

    repair = getattr(v45, "repair_process_generation", None)
    if callable(repair):
        try:
            ok, repaired_generation, repair_reason = repair(source)
        except Exception as exc:
            return None, f"canonical_generation_repair_error:{type(exc).__name__}:{exc}"
        if not bool(ok) or int(repaired_generation or 0) != generation:
            return None, f"canonical_generation_repair_failed:{repair_reason}"
    else:
        value = str(generation)
        os.environ["NIJA_WRITER_LEASE_GENERATION"] = value
        os.environ["NIJA_WRITER_GENERATION"] = value
        os.environ["NIJA_WRITER_LEASE_GENERATION_LAST"] = value

    # Exact current distributed proof supersedes local-only high-water telemetry.
    # This is not a generation rollback: v45 already proved Redis's process
    # generation key equals EntrypointWriterAuthority._generation for the exact
    # current lock owner and fencing token.
    before_last = str(os.environ.get("NIJA_WRITER_LEASE_GENERATION_LAST", "") or "")
    value = str(generation)
    os.environ["NIJA_WRITER_LEASE_GENERATION"] = value
    os.environ["NIJA_WRITER_GENERATION"] = value
    os.environ["NIJA_WRITER_LEASE_GENERATION_LAST"] = value
    expected = str(os.environ.get("NIJA_WRITER_LEASE_GENERATION_EXPECTED", "") or "").strip()
    if expected and expected != value:
        os.environ["NIJA_WRITER_LEASE_GENERATION_EXPECTED"] = value
    if before_last and before_last != value:
        LOGGER.critical(
            "WRITER_GENERATION_V50_CANONICALIZED marker=%s source=%s before_last=%s "
            "canonical=%s token_prefix=%s proof=exact_redis_process_writer",
            MARKER,
            source,
            before_last,
            value,
            token[:8],
        )
    return dict(proof), ""


def canonical_writer_generation_gate() -> tuple[bool, str]:
    """Validate process generation without consulting the Kraken nonce lease."""
    if not _truthy("NIJA_ENFORCE_WRITER_LEASE_GENERATION", "true"):
        return True, ""
    proof, reason = _canonical_process_writer_proof("trading_state_generation_gate_v50")
    if proof is None:
        return False, f"process_writer_generation:{reason}"
    generation = int(proof["generation"])
    return True, f"process_writer_generation_proven generation={generation}"


setattr(canonical_writer_generation_gate, _GATE_PATCH, True)


def _patch_trading_state_module(module: ModuleType) -> bool:
    current = getattr(module, "_writer_lease_generation_gate", None)
    if not callable(current):
        return False
    if getattr(current, _GATE_PATCH, False):
        return True
    replacement = canonical_writer_generation_gate
    try:
        setattr(replacement, "__wrapped__", current)
    except Exception:
        pass
    module._writer_lease_generation_gate = replacement
    os.environ["NIJA_WRITER_GENERATION_STATE_GATE_V50_PATCHED"] = "1"
    LOGGER.critical(
        "WRITER_GENERATION_STATE_GATE_V50_PATCHED marker=%s module=%s "
        "nonce_generation_as_process_writer=false fail_closed=true",
        MARKER,
        module.__name__,
    )
    return True


def _patch_dispatch_module(module: ModuleType) -> bool:
    """Prevent the legacy regression repair from restoring nonce-derived state."""
    current = getattr(module, "_install_lease_generation_patch_on_module", None)
    if not callable(current):
        return False
    if getattr(current, _DISPATCH_PATCH, False):
        return True
    legacy = current

    @wraps(legacy)
    def install_lease_generation_patch_on_module(target: ModuleType) -> bool:
        # The v50 gate is already the complete process-generation policy.  Do
        # not wrap it with the legacy regex repair that copies a nonce token into
        # NIJA_WRITER_LEASE_GENERATION[_LAST].
        gate = getattr(target, "_writer_lease_generation_gate", None)
        if getattr(gate, _GATE_PATCH, False):
            try:
                setattr(module, "_LEASE_GENERATION_PATCHED", True)
            except Exception:
                pass
            return True
        result = bool(legacy(target))
        # If the legacy installer ran first, immediately replace its wrapper
        # with the canonical proof gate.
        if target.__name__ in _TSM_NAMES:
            return _patch_trading_state_module(target) or result
        return result

    setattr(install_lease_generation_patch_on_module, _DISPATCH_PATCH, True)
    setattr(install_lease_generation_patch_on_module, "__wrapped__", legacy)
    module._install_lease_generation_patch_on_module = install_lease_generation_patch_on_module
    LOGGER.critical(
        "WRITER_GENERATION_STATE_GATE_V50_DISPATCH_PATCHED marker=%s module=%s "
        "legacy_nonce_regression_repair_suppressed=true",
        MARKER,
        module.__name__,
    )
    return True


def _patch_loaded() -> tuple[bool, bool]:
    tsm_ok = False
    dispatch_ok = False
    seen: set[int] = set()
    for name, module in list(sys.modules.items()):
        if not isinstance(module, ModuleType) or id(module) in seen:
            continue
        seen.add(id(module))
        try:
            if name in _TSM_NAMES:
                tsm_ok = _patch_trading_state_module(module) or tsm_ok
            if name in _DISPATCH_NAMES:
                dispatch_ok = _patch_dispatch_module(module) or dispatch_ok
        except Exception as exc:
            LOGGER.warning(
                "WRITER_GENERATION_STATE_GATE_V50_PATCH_DEFERRED marker=%s module=%s err=%s:%s",
                MARKER,
                name,
                type(exc).__name__,
                exc,
            )
    return tsm_ok, dispatch_ok


def _interesting(name: str) -> bool:
    text = str(name or "")
    return text in {*_TSM_NAMES, *_DISPATCH_NAMES, *_V45_NAMES}


def install_import_hook() -> bool:
    global _INSTALLED
    with _LOCK:
        _patch_loaded()
        if not getattr(builtins, _HOOK_FLAG, False):
            original_import = builtins.__import__

            @wraps(original_import)
            def importing(name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0):
                result = original_import(name, globals, locals, fromlist, level)
                if _interesting(str(name or "")):
                    _patch_loaded()
                return result

            builtins.__import__ = importing
            setattr(builtins, _HOOK_FLAG, True)

        if not getattr(importlib, _IMPORTLIB_FLAG, False):
            original_import_module = importlib.import_module

            @wraps(original_import_module)
            def import_module(name: str, package: str | None = None):
                result = original_import_module(name, package)
                if _interesting(str(name or "")):
                    _patch_loaded()
                return result

            importlib.import_module = import_module  # type: ignore[assignment]
            setattr(importlib, _IMPORTLIB_FLAG, True)

        # v45 must be available because v50 never invents an alternative writer
        # proof. TradingStateMachine may legitimately load later.
        _INSTALLED = _v45_module() is not None
        os.environ["NIJA_WRITER_GENERATION_STATE_GATE_V50_INSTALLED"] = "1" if _INSTALLED else "0"
        LOGGER.critical(
            "WRITER_GENERATION_STATE_GATE_V50_INSTALLED marker=%s v45_available=%s "
            "future_import_hook=true installed=%s",
            MARKER,
            _v45_module() is not None,
            _INSTALLED,
        )
        return _INSTALLED


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "canonical_writer_generation_gate",
    "_canonical_process_writer_proof",
    "_patch_trading_state_module",
    "_patch_dispatch_module",
]
