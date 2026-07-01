"""Runtime compatibility fixes for live execution authority blockers.

This module repairs the blockers seen in the 2026-07-01 Railway log without
weakening execution safety:

* Re-exposes heartbeat marker helpers expected by ``execution_authority_context``.
* Keeps writer lease generation env state synchronized after lightweight recovery.
* Installs import hooks so late imports receive the same repairs.

The patch is intentionally conservative: it does not bypass live-capital,
distributed-writer, nonce, ECEL, notional, risk, or broker health gates.
"""

from __future__ import annotations

import importlib
import json
import logging
import os
import sys
import time
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Optional

logger = logging.getLogger("nija.live_execution_authority_blocker_patch")

_PATCHED_TSM: set[str] = set()
_PATCHED_WGT: set[str] = set()
_ORIGINAL_IMPORT_MODULE: Optional[Callable[..., Any]] = None

_STAGE_ORDER = {
    "AUTH_VERIFY": 1,
    "ORDER_VERIFY": 2,
    "FILL_VERIFY": 3,
}


def _normalize_stage(stage: Any, default: str = "FILL_VERIFY") -> str:
    value = str(stage or default).strip().upper()
    return value if value in _STAGE_ORDER else default


def _read_marker_payload(marker_path: str | None) -> tuple[bool, str, dict[str, Any]]:
    path = marker_path or os.environ.get("HEARTBEAT_MARKER_PATH", "./data/heartbeat_verified.flag")
    try:
        marker = Path(path)
        if not marker.exists():
            return False, "marker_missing", {"path": path}
        raw = marker.read_text(encoding="utf-8").strip()
        if not raw:
            return False, "marker_empty", {"path": path}
        if not raw.startswith("{"):
            return False, "legacy_marker_non_fresh", {"path": path, "legacy_marker": True}
        payload = json.loads(raw)
        return True, "", payload if isinstance(payload, dict) else {}
    except Exception as exc:
        return False, f"marker_read_failed:{exc}", {"path": path}


def _required_stage_from_env(tsm: ModuleType | None = None) -> str:
    for key in (
        "NIJA_REQUIRED_HEARTBEAT_STAGE",
        "HEARTBEAT_VERIFICATION_REQUIRED_STAGE",
        "REQUIRED_HEARTBEAT_STAGE",
    ):
        raw = os.environ.get(key, "").strip()
        if raw:
            return _normalize_stage(raw)
    if tsm is not None:
        resolver = getattr(tsm, "_heartbeat_min_required_stage", None)
        if callable(resolver):
            try:
                return _normalize_stage(resolver())
            except Exception:
                pass
    # Live dispatch should require the strongest marker written by AuthorityHeartbeatMonitor.
    return "FILL_VERIFY"


def _patch_trading_state_machine(tsm: ModuleType) -> bool:
    name = getattr(tsm, "__name__", "<unknown>")
    changed = False

    if not callable(getattr(tsm, "_required_heartbeat_stage", None)):
        def _required_heartbeat_stage(*_args: Any, **_kwargs: Any) -> str:
            return _required_stage_from_env(tsm)

        setattr(tsm, "_required_heartbeat_stage", _required_heartbeat_stage)
        changed = True

    if not callable(getattr(tsm, "heartbeat_marker_is_fresh", None)):
        def heartbeat_marker_is_fresh(marker_path: str | None = None, max_age_s: float | None = None) -> bool:
            status_fn = getattr(tsm, "_heartbeat_verification_status", None)
            default_path_fn = getattr(tsm, "_heartbeat_marker_path", None)
            try:
                default_path = default_path_fn() if callable(default_path_fn) else None
            except Exception:
                default_path = None
            # Prefer the native status function when the caller is checking the canonical marker.
            if callable(status_fn) and (not marker_path or not default_path or str(marker_path) == str(default_path)):
                try:
                    ok, _reason, _detail = status_fn()
                    return bool(ok)
                except Exception:
                    pass
            ok, _reason, payload = _read_marker_payload(marker_path)
            if not ok:
                return False
            try:
                ts = float(
                    payload.get("verified_at_epoch")
                    or payload.get("timestamp_epoch")
                    or payload.get("verified_at")
                    or 0.0
                )
            except Exception:
                ts = 0.0
            if ts <= 0:
                return False
            if max_age_s is None:
                try:
                    age_fn = getattr(tsm, "_heartbeat_verification_max_age_seconds", None)
                    max_age_s = float(age_fn()) if callable(age_fn) else float(os.environ.get("HEARTBEAT_VERIFICATION_MAX_AGE_SECONDS", "1800") or 1800)
                except Exception:
                    max_age_s = 1800.0
            return max_age_s <= 0 or (time.time() - ts) <= max_age_s

        setattr(tsm, "heartbeat_marker_is_fresh", heartbeat_marker_is_fresh)
        changed = True

    if not callable(getattr(tsm, "heartbeat_marker_stage_is_sufficient", None)):
        def heartbeat_marker_stage_is_sufficient(marker_path: str | None = None, required_stage: str | None = None) -> bool:
            required = _normalize_stage(required_stage or _required_stage_from_env(tsm))
            status_fn = getattr(tsm, "_heartbeat_verification_status", None)
            default_path_fn = getattr(tsm, "_heartbeat_marker_path", None)
            try:
                default_path = default_path_fn() if callable(default_path_fn) else None
            except Exception:
                default_path = None
            if callable(status_fn) and (not marker_path or not default_path or str(marker_path) == str(default_path)):
                try:
                    ok, _reason, detail = status_fn()
                    if not ok:
                        return False
                    stage = _normalize_stage((detail or {}).get("stage"))
                    return _STAGE_ORDER[stage] >= _STAGE_ORDER[required]
                except Exception:
                    pass
            ok, _reason, payload = _read_marker_payload(marker_path)
            if not ok:
                return False
            stage = _normalize_stage(payload.get("stage"), default="AUTH_VERIFY")
            return _STAGE_ORDER[stage] >= _STAGE_ORDER[required]

        setattr(tsm, "heartbeat_marker_stage_is_sufficient", heartbeat_marker_stage_is_sufficient)
        changed = True

    if changed or name not in _PATCHED_TSM:
        _PATCHED_TSM.add(name)
        logger.warning(
            "LIVE_EXECUTION_AUTHORITY_BLOCKER_PATCHED module=%s helpers=%s",
            name,
            ",".join(
                helper for helper in (
                    "_required_heartbeat_stage",
                    "heartbeat_marker_is_fresh",
                    "heartbeat_marker_stage_is_sufficient",
                )
                if callable(getattr(tsm, helper, None))
            ),
        )
    return True


def _sync_generation_env(redis_generation: Any) -> None:
    try:
        redis_gen = int(redis_generation)
    except Exception:
        return
    if redis_gen <= 0:
        return
    os.environ["NIJA_WRITER_LEASE_GENERATION"] = str(redis_gen)
    os.environ["NIJA_WRITER_LEASE_GENERATION_LAST"] = str(redis_gen)
    os.environ["NIJA_WRITER_GENERATION_SYNCED_TS"] = f"{time.time():.6f}"
    expected = os.environ.get("NIJA_WRITER_LEASE_GENERATION_EXPECTED", "").strip()
    if expected and expected != str(redis_gen):
        os.environ.pop("NIJA_WRITER_LEASE_GENERATION_EXPECTED", None)


def _patch_writer_generation_tracker(wgt: ModuleType) -> bool:
    name = getattr(wgt, "__name__", "<unknown>")
    changed = False

    original_sync = getattr(wgt, "attempt_generation_sync_recovery", None)
    if callable(original_sync) and not getattr(original_sync, "_nija_env_sync_wrapped", False):
        def _wrapped_attempt_generation_sync_recovery(local: int, redis_gen: int):
            recovered, message = original_sync(local, redis_gen)
            if recovered:
                _sync_generation_env(redis_gen)
                logger.critical(
                    "GENERATION_SYNC_ENV_REPAIR_APPLIED local_before=%s redis=%s message=%s",
                    local,
                    redis_gen,
                    message,
                )
            return recovered, message

        setattr(_wrapped_attempt_generation_sync_recovery, "_nija_env_sync_wrapped", True)
        setattr(wgt, "attempt_generation_sync_recovery", _wrapped_attempt_generation_sync_recovery)
        changed = True

    original_reset = getattr(wgt, "reset_generation_to_redis", None)
    if callable(original_reset) and not getattr(original_reset, "_nija_env_sync_wrapped", False):
        def _wrapped_reset_generation_to_redis():
            success, message = original_reset()
            if success:
                redis_reader = getattr(wgt, "get_redis_generation", None)
                redis_gen = 0
                if callable(redis_reader):
                    try:
                        redis_gen, _err = redis_reader()
                    except Exception:
                        redis_gen = 0
                _sync_generation_env(redis_gen)
                logger.critical(
                    "GENERATION_RESET_ENV_REPAIR_APPLIED redis=%s message=%s",
                    redis_gen,
                    message,
                )
            return success, message

        setattr(_wrapped_reset_generation_to_redis, "_nija_env_sync_wrapped", True)
        setattr(wgt, "reset_generation_to_redis", _wrapped_reset_generation_to_redis)
        changed = True

    if changed or name not in _PATCHED_WGT:
        _PATCHED_WGT.add(name)
        logger.warning("LIVE_EXECUTION_GENERATION_SYNC_PATCHED module=%s", name)
    return True


def _try_patch_module(name: str) -> None:
    module = sys.modules.get(name)
    if not isinstance(module, ModuleType):
        return
    if name in {"bot.trading_state_machine", "trading_state_machine"}:
        _patch_trading_state_machine(module)
    elif name in {"bot.writer_generation_tracker", "writer_generation_tracker"}:
        _patch_writer_generation_tracker(module)


def _patch_loaded_modules() -> None:
    for name in (
        "bot.trading_state_machine",
        "trading_state_machine",
        "bot.writer_generation_tracker",
        "writer_generation_tracker",
    ):
        _try_patch_module(name)


def install_import_hook() -> None:
    """Install the compatibility patch once."""
    global _ORIGINAL_IMPORT_MODULE

    # Import and patch the trading state machine eagerly so attribute imports from
    # execution_authority_context cannot fail at dispatch time.
    for name in ("bot.trading_state_machine", "trading_state_machine"):
        try:
            module = importlib.import_module(name)
            if isinstance(module, ModuleType):
                _patch_trading_state_machine(module)
        except Exception as exc:
            logger.debug("deferred trading_state_machine compatibility patch for %s: %s", name, exc)

    for name in ("bot.writer_generation_tracker", "writer_generation_tracker"):
        try:
            module = importlib.import_module(name)
            if isinstance(module, ModuleType):
                _patch_writer_generation_tracker(module)
        except Exception as exc:
            logger.debug("deferred writer_generation_tracker compatibility patch for %s: %s", name, exc)

    _patch_loaded_modules()

    if _ORIGINAL_IMPORT_MODULE is not None:
        logger.warning("LIVE_EXECUTION_AUTHORITY_BLOCKER_INSTALL_COMPLETE already_installed=True")
        return

    _ORIGINAL_IMPORT_MODULE = importlib.import_module

    def _wrapped_import_module(name: str, package: str | None = None):
        module = _ORIGINAL_IMPORT_MODULE(name, package)  # type: ignore[misc]
        if isinstance(module, ModuleType):
            if name in {"bot.trading_state_machine", "trading_state_machine"}:
                _patch_trading_state_machine(module)
            elif name in {"bot.writer_generation_tracker", "writer_generation_tracker"}:
                _patch_writer_generation_tracker(module)
        return module

    importlib.import_module = _wrapped_import_module  # type: ignore[assignment]
    logger.warning(
        "LIVE_EXECUTION_AUTHORITY_BLOCKER_INSTALL_COMPLETE tsm_patched=%s writer_generation_patched=%s",
        sorted(_PATCHED_TSM),
        sorted(_PATCHED_WGT),
    )
