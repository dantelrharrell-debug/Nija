"""Exact process-writer authority generation convergence v57.

Production after v55 proved the bounded recovery chain could acquire a fresh
writer epoch, but runtime authority could remain fail-closed on stale local
generation telemetry from the immediately preceding epoch.  The observed
sequence was a canonical v39 re-election from generation 3358 to 3359 followed
by exact writer acquisition while ``execution_authority_context`` still reported
``local=3358 redis=3359``.

v57 makes the distributed-authority assertion use the same v45 exact
process-writer proof already required by the trading-state generation gate.
That proof requires the canonical EntrypointWriterAuthority runtime to be
acquired and not lost, the exact Redis lock value and fencing token to match,
the lock TTL to be positive, and the Redis process-generation key to equal the
runtime generation.  Only after that proof succeeds may v45 repair mutable
process-local generation telemetry.

Safety contract:
* no Redis lock is created, renewed, extended, deleted, stolen, or fabricated;
* local generation is repaired only from an exact current distributed proof;
* live-mode distributed-lock bypass flags remain rejected;
* missing, stale, mismatched, or unavailable proof remains fail-closed;
* no capital, broker, nonce, SEAK, risk, strategy, or order gate is bypassed.
"""
from __future__ import annotations

import builtins
import importlib
import logging
import os
import sys
import threading
import time
from types import ModuleType
from typing import Any

LOGGER = logging.getLogger("nija.writer_authority_generation_convergence_v57")
MARKER = "20260808-writer-authority-generation-convergence-v57"

_LOCK = threading.RLock()
_PATCH_ATTR = "_nija_writer_authority_generation_convergence_v57"
_INSTALL_FLAG = "_NIJA_WRITER_AUTHORITY_GENERATION_CONVERGENCE_V57_IMPORT_HOOK"
_IMPORTLIB_FLAG = "_NIJA_WRITER_AUTHORITY_GENERATION_CONVERGENCE_V57_IMPORTLIB_HOOK"
_TARGETS = {"bot.execution_authority_context", "execution_authority_context"}
_V45_NAMES = (
    "nija_writer_generation_handoff_v45_prebot",
    "bot.writer_generation_handoff_v45_patch",
    "writer_generation_handoff_v45_patch",
)
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}


def _truthy(name: str) -> bool:
    return str(os.environ.get(name, "") or "").strip().lower() in _TRUE


def _live_mode() -> bool:
    return bool(
        _truthy("LIVE_CAPITAL_VERIFIED")
        and not _truthy("DRY_RUN_MODE")
        and not _truthy("PAPER_MODE")
    )


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


def _exact_process_writer(source: str) -> tuple[dict[str, Any] | None, str]:
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
    pttl_ms = int(proof.get("pttl_ms", -2) or -2)
    if generation <= 0:
        return None, "canonical_generation_invalid"
    if not token:
        return None, "canonical_fencing_token_missing"
    if pttl_ms <= 0:
        return None, f"canonical_writer_ttl_not_positive:{pttl_ms}"

    repair = getattr(v45, "repair_process_generation", None)
    if not callable(repair):
        return None, "v45_process_generation_repair_unavailable"
    try:
        ok, repaired_generation, repair_reason = repair(source)
    except Exception as exc:
        return None, f"v45_process_generation_repair_error:{type(exc).__name__}:{exc}"
    if not bool(ok):
        return None, f"v45_process_generation_repair_failed:{repair_reason}"
    if int(repaired_generation or 0) != generation:
        return None, (
            "v45_process_generation_repair_mismatch:"
            f"proof={generation}:repaired={repaired_generation}"
        )

    # A successful v45 proof means the canonical singleton is acquired and
    # owns the exact current Redis process-writer lock.  Re-publish only the
    # local acquisition telemetry that can legitimately lag a fresh epoch.
    os.environ["NIJA_WRITER_LEASE_ACQUIRED"] = "1"
    return dict(proof), ""


def _patch_execution_authority_context(module: ModuleType) -> bool:
    current = getattr(module, "assert_distributed_writer_authority", None)
    if not callable(current):
        return False
    if getattr(current, _PATCH_ATTR, False):
        return True

    original = current

    def assert_distributed_writer_authority() -> None:
        if _live_mode() and (
            _truthy("NIJA_UNSAFE_BYPASS_DISTRIBUTED_LOCK")
            or _truthy("NIJA_FORCE_LOCAL_WRITER_LOCK_FALLBACK")
            or _truthy("NIJA_WRITER_FENCING_TOKEN_FALLBACK")
        ):
            raise RuntimeError(
                "STRICT_SINGLE_WRITER_REQUIRED: live distributed-lock bypass refused"
            )

        before = str(
            os.environ.get("NIJA_WRITER_LEASE_GENERATION", "")
            or os.environ.get("NIJA_WRITER_GENERATION", "")
            or ""
        ).strip()
        proof, reason = _exact_process_writer("distributed_authority_v57")
        if proof is None:
            raise RuntimeError(
                "STRICT_SINGLE_WRITER_REQUIRED: exact process writer proof failed:"
                f"{reason}"
            )

        generation = int(proof["generation"])
        token = str(proof["token"])
        after = str(os.environ.get("NIJA_WRITER_LEASE_GENERATION", "") or "").strip()

        lock = getattr(module, "_FENCE_VERIFY_LOCK", None)
        try:
            if lock is not None:
                with lock:
                    module._FENCE_LAST_CHECK_TS = time.monotonic()
                    module._FENCE_LAST_OK = True
                    module._FENCE_LAST_ERR = ""
            else:
                module._FENCE_LAST_CHECK_TS = time.monotonic()
                module._FENCE_LAST_OK = True
                module._FENCE_LAST_ERR = ""
        except Exception:
            pass

        last_generation = int(
            getattr(module, "_NIJA_WRITER_AUTHORITY_V57_LAST_GENERATION", 0) or 0
        )
        if last_generation != generation or (before and before != after):
            module._NIJA_WRITER_AUTHORITY_V57_LAST_GENERATION = generation
            LOGGER.critical(
                "WRITER_AUTHORITY_V57_PROVEN marker=%s generation=%s "
                "token_prefix=%s local_before=%s local_after=%s "
                "proof=exact_redis_process_writer execution_grant=false",
                MARKER,
                generation,
                token[:8],
                before or "unset",
                after or "unset",
            )

    setattr(assert_distributed_writer_authority, _PATCH_ATTR, True)
    setattr(assert_distributed_writer_authority, "__wrapped__", original)
    module.assert_distributed_writer_authority = assert_distributed_writer_authority
    os.environ["NIJA_WRITER_AUTHORITY_GENERATION_CONVERGENCE_V57_PATCHED"] = "1"
    LOGGER.critical(
        "WRITER_AUTHORITY_GENERATION_CONVERGENCE_V57_PATCHED marker=%s module=%s "
        "exact_v45_proof=true local_generation_repair=proof_driven lock_mutation=false",
        MARKER,
        module.__name__,
    )
    return True


def _patch_loaded() -> bool:
    patched = False
    seen: set[int] = set()
    for name in _TARGETS:
        module = sys.modules.get(name)
        if not isinstance(module, ModuleType) or id(module) in seen:
            continue
        seen.add(id(module))
        try:
            patched = _patch_execution_authority_context(module) or patched
        except Exception as exc:
            LOGGER.warning(
                "WRITER_AUTHORITY_V57_PATCH_DEFERRED marker=%s module=%s err=%s:%s",
                MARKER,
                name,
                type(exc).__name__,
                exc,
            )
    return patched


def _interesting(name: str) -> bool:
    return str(name or "") in {*_TARGETS, *_V45_NAMES}


def install_import_hook() -> bool:
    with _LOCK:
        _patch_loaded()

        if not getattr(builtins, _INSTALL_FLAG, False):
            original_import = builtins.__import__

            def importing(
                name: str,
                globals: Any = None,
                locals: Any = None,
                fromlist: Any = (),
                level: int = 0,
            ):
                result = original_import(name, globals, locals, fromlist, level)
                if _interesting(str(name or "")):
                    _patch_loaded()
                return result

            setattr(importing, "__wrapped__", original_import)
            builtins.__import__ = importing
            setattr(builtins, _INSTALL_FLAG, True)

        if not getattr(importlib, _IMPORTLIB_FLAG, False):
            original_import_module = importlib.import_module

            def import_module(name: str, package: str | None = None):
                result = original_import_module(name, package)
                if _interesting(str(name or "")):
                    _patch_loaded()
                return result

            setattr(import_module, "__wrapped__", original_import_module)
            importlib.import_module = import_module  # type: ignore[assignment]
            setattr(importlib, _IMPORTLIB_FLAG, True)

        available = _v45_module() is not None
        os.environ["NIJA_WRITER_AUTHORITY_GENERATION_CONVERGENCE_V57_INSTALLED"] = (
            "1" if available else "0"
        )
        LOGGER.critical(
            "WRITER_AUTHORITY_GENERATION_CONVERGENCE_V57_INSTALLED marker=%s "
            "v45_available=%s future_import_hook=true fail_closed=true lock_mutation=false",
            MARKER,
            available,
        )
        return available


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_exact_process_writer",
    "_patch_execution_authority_context",
]
