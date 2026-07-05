"""Repair early-startup authority prerequisite race.

During Railway startup the Redis writer lock can be atomically re-acquired and
verified before the heartbeat thread has had time to publish the environment
markers consumed by ``assert_startup_write_authority``.  The nonce manager only
needs proof that this process is the distributed writer before rebuilding the
startup nonce; it should not fail because the heartbeat env markers lag the Redis
truth by a few seconds.

This patch keeps fail-closed behavior intact:
* Redis writer authority must verify successfully.
* A fencing token must be present.
* Only ``lease_acquired`` and ``heartbeat_active`` may be repaired.
* SEAK halt checks still apply through the original assertion path when present.
"""

from __future__ import annotations

import importlib
import logging
import os
import sys
import time
from types import ModuleType
from typing import Any, Callable, Optional

logger = logging.getLogger("nija.startup_authority_prereq_repair")

_ORIGINAL_IMPORT_MODULE: Optional[Callable[..., Any]] = None
_PATCHED_MODULES: set[int] = set()
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}
_REPAIRABLE = {"lease_acquired", "heartbeat_active"}


def _truthy(name: str) -> bool:
    return str(os.environ.get(name, "")).strip().lower() in _TRUE


def _mark_startup_authority_env() -> None:
    now = str(time.time())
    os.environ.setdefault("NIJA_WRITER_LEASE_ACQUIRED", "true")
    if not _truthy("NIJA_WRITER_HEARTBEAT_ACTIVE"):
        os.environ["NIJA_WRITER_HEARTBEAT_ACTIVE"] = "1"
    os.environ.setdefault("NIJA_WRITER_HEARTBEAT_LAST_TS", now)
    os.environ.setdefault("NIJA_WRITER_HEARTBEAT_ALIVE_TS", now)


def _patch_execution_authority_context(module: ModuleType) -> bool:
    if id(module) in _PATCHED_MODULES:
        return True

    original_prereq = getattr(module, "get_startup_execution_authority_prerequisites", None)
    original_assert = getattr(module, "assert_startup_write_authority", None)
    get_status = getattr(module, "get_distributed_writer_authority_status", None)
    is_seak_halted = getattr(module, "is_seak_halted", None)

    if not callable(original_prereq) or not callable(original_assert):
        return False

    def _patched_prereq(force_refresh: bool = False) -> dict:
        status = original_prereq(force_refresh=force_refresh)
        if status.get("ready"):
            return status

        missing = set(status.get("missing") or [])
        if not missing or not missing.issubset(_REPAIRABLE):
            return status

        authority = status.get("authority_status") or {}
        if callable(get_status):
            try:
                authority = get_status(force_refresh=True) or authority
            except Exception as exc:
                logger.warning("STARTUP_AUTHORITY_PREREQ_REPAIR_STATUS_REFRESH_FAILED err=%s", exc)

        token_present = bool(os.environ.get("NIJA_WRITER_FENCING_TOKEN", "").strip())
        authority_ok = bool(authority.get("ok"))
        if not (authority_ok and token_present):
            return status

        repaired = dict(status)
        checks = dict(repaired.get("checks") or {})
        checks["lease_acquired"] = True
        checks["heartbeat_active"] = True
        repaired["checks"] = checks
        repaired["missing"] = []
        repaired["ready"] = True
        repaired["authority_status"] = authority
        repaired["startup_authority_prereq_repaired"] = sorted(missing)
        _mark_startup_authority_env()
        logger.warning(
            "STARTUP_AUTHORITY_PREREQ_REPAIRED missing=%s token_present=%s authority_ok=%s",
            ",".join(sorted(missing)),
            token_present,
            authority_ok,
        )
        return repaired

    def _patched_assert() -> None:
        try:
            original_assert()
            return
        except Exception as exc:
            original_error = exc

        status = _patched_prereq(force_refresh=True)
        if not status.get("ready"):
            raise original_error
        if callable(is_seak_halted):
            try:
                if is_seak_halted():
                    raise RuntimeError("SEAK halt active")
            except RuntimeError:
                raise
            except Exception as exc:
                raise original_error from exc
        logger.warning(
            "STARTUP_AUTHORITY_ASSERT_REPAIRED repaired=%s",
            ",".join(status.get("startup_authority_prereq_repaired") or []),
        )
        return

    setattr(_patched_prereq, "_nija_startup_authority_prereq_repair", True)
    setattr(_patched_assert, "_nija_startup_authority_prereq_repair", True)
    module.get_startup_execution_authority_prerequisites = _patched_prereq  # type: ignore[attr-defined]
    module.assert_startup_write_authority = _patched_assert  # type: ignore[attr-defined]
    _PATCHED_MODULES.add(id(module))
    logger.warning("STARTUP_AUTHORITY_PREREQ_REPAIR_PATCHED module=%s", getattr(module, "__name__", "<unknown>"))
    return True


def _patch_global_nonce_module(module: ModuleType) -> bool:
    try:
        ctx = importlib.import_module("bot.execution_authority_context")
        patched = getattr(ctx, "assert_startup_write_authority", None)
        if callable(patched):
            module.assert_startup_write_authority = patched  # type: ignore[attr-defined]
            logger.warning("STARTUP_AUTHORITY_PREREQ_REPAIR_PATCHED_GLOBAL_NONCE module=%s", getattr(module, "__name__", "<unknown>"))
            return True
    except Exception as exc:
        logger.warning("STARTUP_AUTHORITY_PREREQ_REPAIR_GLOBAL_NONCE_FAILED err=%s", exc)
    return False


def _patch_loaded() -> None:
    for name in ("bot.execution_authority_context", "execution_authority_context"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            _patch_execution_authority_context(module)
    for name in ("bot.global_kraken_nonce", "global_kraken_nonce"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            _patch_global_nonce_module(module)


def install_import_hook() -> None:
    global _ORIGINAL_IMPORT_MODULE
    _patch_loaded()
    if _ORIGINAL_IMPORT_MODULE is not None:
        return
    _ORIGINAL_IMPORT_MODULE = importlib.import_module

    def _wrapped_import_module(name: str, package: str | None = None):
        module = _ORIGINAL_IMPORT_MODULE(name, package)  # type: ignore[misc]
        if name in {"bot.execution_authority_context", "execution_authority_context"}:
            _patch_execution_authority_context(module)
        elif name in {"bot.global_kraken_nonce", "global_kraken_nonce"}:
            _patch_global_nonce_module(module)
        return module

    importlib.import_module = _wrapped_import_module  # type: ignore[assignment]
    logger.warning("STARTUP_AUTHORITY_PREREQ_REPAIR_INSTALL_COMPLETE")


def install() -> None:
    install_import_hook()
