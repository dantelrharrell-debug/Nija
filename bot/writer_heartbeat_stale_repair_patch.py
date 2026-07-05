from __future__ import annotations

import builtins
import logging
import os
import sys
import threading
import time
from types import ModuleType
from typing import Any

logger = logging.getLogger("nija.writer_heartbeat_stale_repair")
_PATCHED_ATTR = "_NIJA_WRITER_HEARTBEAT_STALE_REPAIR_PATCHED"
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}


def _truthy(name: str, default: str = "false") -> bool:
    return str(os.getenv(name, default)).strip().lower() in _TRUE


def _live_capital_mode() -> bool:
    return bool(
        _truthy("LIVE_CAPITAL_VERIFIED")
        and not _truthy("DRY_RUN_MODE")
        and not _truthy("PAPER_MODE")
    )


def _redis_nonce_heartbeat_alive() -> bool:
    try:
        for thread in threading.enumerate():
            name = str(getattr(thread, "name", "") or "")
            if thread.is_alive() and "RedisNonceLeaseHeartbeat" in name:
                return True
    except Exception:
        pass
    return False


def _authority_env_present() -> bool:
    return bool(
        os.getenv("NIJA_WRITER_FENCING_TOKEN", "").strip()
        and os.getenv("NIJA_WRITER_LEASE_GENERATION", "").strip()
        and os.getenv("NIJA_WRITER_HEARTBEAT_ACTIVE", "").strip() == "1"
    )


def _strict_writer_checks_pass(tsm: ModuleType) -> tuple[bool, str]:
    # Do not treat the stale heartbeat timestamp itself as authority.  Require
    # the independent distributed-writer and nonce-lease checks to pass first.
    lease_gate = getattr(tsm, "_distributed_writer_authority_gate", None)
    if callable(lease_gate):
        ok, detail = lease_gate()
        if not bool(ok):
            return False, f"lease_gate:{detail}"

    nonce_gate = getattr(tsm, "_nonce_writer_lease_gate", None)
    if callable(nonce_gate):
        ok, detail = nonce_gate()
        if not bool(ok):
            return False, f"nonce_lease_gate:{detail}"

    nonce_sync_gate = getattr(tsm, "_nonce_sync_gate", None)
    if callable(nonce_sync_gate):
        ok, detail = nonce_sync_gate()
        if not bool(ok):
            return False, f"nonce_sync_gate:{detail}"

    return True, "strict_writer_checks_passed"


def _refresh_writer_heartbeat_timestamp(reason: str) -> None:
    now = time.time()
    os.environ["NIJA_WRITER_HEARTBEAT_ACTIVE"] = "1"
    os.environ["NIJA_WRITER_HEARTBEAT_ALIVE_TS"] = f"{now:.6f}"
    os.environ["NIJA_WRITER_HEARTBEAT_REPAIRED_TS"] = f"{now:.6f}"
    logger.critical(
        "WRITER_HEARTBEAT_STALE_REPAIRED reason=%s token_prefix=%s generation=%s alive_ts=%.6f redis_nonce_thread=%s",
        reason,
        os.getenv("NIJA_WRITER_FENCING_TOKEN", "")[:8],
        os.getenv("NIJA_WRITER_LEASE_GENERATION", ""),
        now,
        _redis_nonce_heartbeat_alive(),
    )
    print(
        f"[NIJA-PRINT] WRITER_HEARTBEAT_STALE_REPAIRED | reason={reason} "
        f"token_prefix={os.getenv('NIJA_WRITER_FENCING_TOKEN', '')[:8]} "
        f"generation={os.getenv('NIJA_WRITER_LEASE_GENERATION', '')}",
        flush=True,
    )


def _patch_module(tsm: ModuleType) -> bool:
    if getattr(tsm, _PATCHED_ATTR, False):
        return True

    original_gate = getattr(tsm, "_writer_heartbeat_gate", None)
    if not callable(original_gate):
        return False

    def _patched_writer_heartbeat_gate() -> tuple[bool, str]:
        ok, detail = original_gate()
        if bool(ok):
            return True, detail

        detail_text = str(detail or "")
        if "writer_heartbeat_stale" not in detail_text:
            return ok, detail

        if not _live_capital_mode():
            return ok, detail
        if not _authority_env_present():
            return ok, detail
        if not _redis_nonce_heartbeat_alive():
            return ok, detail

        strict_ok, strict_detail = _strict_writer_checks_pass(tsm)
        if not strict_ok:
            logger.critical(
                "WRITER_HEARTBEAT_STALE_REPAIR_WAITING detail=%s original=%s",
                strict_detail,
                detail_text,
            )
            return ok, detail

        _refresh_writer_heartbeat_timestamp(f"{detail_text}; {strict_detail}")
        return True, "writer_heartbeat_timestamp_repaired"

    setattr(_patched_writer_heartbeat_gate, "_nija_writer_heartbeat_stale_repair_wrapped", True)
    setattr(tsm, "_writer_heartbeat_gate", _patched_writer_heartbeat_gate)
    setattr(tsm, _PATCHED_ATTR, True)
    logger.warning("WRITER_HEARTBEAT_STALE_REPAIR_PATCHED module=%s", tsm.__name__)
    return True


def _patch_loaded() -> None:
    for name in ("bot.trading_state_machine", "trading_state_machine"):
        mod = sys.modules.get(name)
        if isinstance(mod, ModuleType):
            try:
                _patch_module(mod)
            except Exception as exc:  # noqa: BLE001
                logger.warning("WRITER_HEARTBEAT_STALE_REPAIR_PATCH_FAILED module=%s err=%s", name, exc)


def install_import_hook() -> None:
    _patch_loaded()
    if getattr(builtins, "_NIJA_WRITER_HEARTBEAT_STALE_REPAIR_IMPORT_HOOK_INSTALLED", False):
        return

    original_import = builtins.__import__

    def guarded_import(name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0) -> Any:
        module = original_import(name, globals, locals, fromlist, level)
        if name in {"bot.trading_state_machine", "trading_state_machine"} or str(name).endswith("trading_state_machine"):
            _patch_loaded()
        return module

    builtins.__import__ = guarded_import
    setattr(builtins, "_NIJA_WRITER_HEARTBEAT_STALE_REPAIR_IMPORT_HOOK_INSTALLED", True)
    logger.warning("WRITER_HEARTBEAT_STALE_REPAIR_INSTALL_COMPLETE")


def install() -> None:
    install_import_hook()
