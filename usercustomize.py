"""User-level startup defaults for NIJA runtime."""

from __future__ import annotations

import builtins
import json
import logging
import os
import sys
import threading
import time
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, Callable

logger = logging.getLogger("nija.usercustomize")

# US OKX accounts require the US regional API host. Keep an explicit Railway
# OKX_BASE_URL override if one is provided; otherwise default to us.okx.com.
os.environ.setdefault("OKX_BASE_URL", "https://us.okx.com")
os.environ.setdefault("OKX_US_REGION", "true")

# Conservative execution defaults: NIJA cannot guarantee profit, but it should
# require fee/slippage-aware positive expectancy before entry orders are allowed.
os.environ.setdefault("NIJA_PROFITABILITY_GUARD_ENABLED", "true")
os.environ.setdefault("NIJA_MIN_EXPECTANCY_THRESHOLD_PCT", "0.15")
os.environ.setdefault("MIN_EXPECTANCY_THRESHOLD_PCT", "0.15")
os.environ.setdefault("NIJA_MIN_EDGE_THRESHOLD", "0.0015")
os.environ.setdefault("MIN_EDGE_THRESHOLD", "0.0015")
os.environ.setdefault("NIJA_LOG_TRADE_DECISIONS", "true")

_STAGE_ORDER: dict[str, int] = {
    "AUTH_VERIFY": 1,
    "ORDER_VERIFY": 2,
    "FILL_VERIFY": 3,
}
_ORIGINAL_IMPORT: Callable[..., Any] | None = None


def _install_position_sync_hook() -> bool:
    for module_name in ("bot.multi_account_broker_manager", "multi_account_broker_manager"):
        module = sys.modules.get(module_name)
        cls = getattr(module, "MultiAccountBrokerManager", None) if module else None
        if cls is None:
            continue

        original = getattr(cls, "refresh_capital_authority", None)
        if original is None or getattr(original, "_position_sync_hooked", False):
            return bool(original)

        def wrapped_refresh(self, *args, **kwargs):
            result = original(self, *args, **kwargs)
            try:
                if getattr(self, "_startup_position_sync_done", False):
                    return result
                ready = isinstance(result, dict) and float(result.get("ready", 0.0) or 0.0) > 0.0
                capital = float(result.get("total_capital", 0.0) or 0.0) if isinstance(result, dict) else 0.0
                trigger = str(kwargs.get("trigger", "refresh_capital_authority"))
                if not ready or capital <= 0.0:
                    logger.info("EXCHANGE_POSITION_SYNC pending trigger=%s ready=%s capital=%.2f", trigger, ready, capital)
                    return result

                setattr(self, "_startup_position_sync_done", True)
                try:
                    from bot.startup_position_sync import sync_exchange_positions_on_startup
                except ImportError:
                    from startup_position_sync import sync_exchange_positions_on_startup  # type: ignore
                logger.warning("EXCHANGE_POSITION_SYNC invocation starting trigger=%s", trigger)
                adopted = sync_exchange_positions_on_startup(SimpleNamespace(multi_account_manager=self))
                logger.warning("EXCHANGE_POSITION_SYNC invocation complete adopted=%s trigger=%s", adopted, trigger)
            except Exception as exc:
                logger.exception("EXCHANGE_POSITION_SYNC invocation failed: %s", exc)
            return result

        wrapped_refresh._position_sync_hooked = True
        cls.refresh_capital_authority = wrapped_refresh
        logger.warning("EXCHANGE_POSITION_SYNC hook installed on %s", module_name)
        return True
    return False


def _position_sync_hook_watchdog() -> None:
    deadline = time.time() + float(os.getenv("NIJA_POSITION_SYNC_HOOK_TIMEOUT_S", "90"))
    while time.time() < deadline:
        if _install_position_sync_hook():
            return
        time.sleep(0.25)
    logger.warning("EXCHANGE_POSITION_SYNC hook not installed before timeout")


def _normalize_stage(stage: Any, default: str = "FILL_VERIFY") -> str:
    value = str(stage or default).strip().upper()
    return value if value in _STAGE_ORDER else default


def _required_stage_from_env(tsm: ModuleType | None = None) -> str:
    for key in (
        "NIJA_REQUIRED_HEARTBEAT_STAGE",
        "NIJA_HEARTBEAT_REQUIRED_STAGE",
        "HEARTBEAT_VERIFICATION_REQUIRED_STAGE",
        "REQUIRED_HEARTBEAT_STAGE",
    ):
        raw = str(os.environ.get(key, "")).strip()
        if raw:
            return _normalize_stage(raw)
    resolver = getattr(tsm, "_heartbeat_min_required_stage", None) if tsm is not None else None
    if callable(resolver):
        try:
            return _normalize_stage(resolver())
        except Exception:
            pass
    return "FILL_VERIFY"


def _read_heartbeat_marker(marker_path: str | None) -> tuple[bool, str, dict[str, Any]]:
    path = marker_path or os.environ.get("HEARTBEAT_MARKER_PATH", "./data/heartbeat_verified.flag")
    try:
        raw = Path(path).read_text(encoding="utf-8").strip()
        if not raw:
            return False, "marker_empty", {"path": path}
        if not raw.startswith("{"):
            return False, "legacy_marker_non_fresh", {"path": path, "legacy_marker": True}
        payload = json.loads(raw)
        return True, "", payload if isinstance(payload, dict) else {}
    except FileNotFoundError:
        return False, "marker_missing", {"path": path}
    except Exception as exc:
        return False, f"marker_read_failed:{exc}", {"path": path}


def _default_marker_path(tsm: ModuleType) -> str:
    resolver = getattr(tsm, "_heartbeat_marker_path", None)
    if callable(resolver):
        try:
            return str(resolver())
        except Exception:
            pass
    return os.environ.get("HEARTBEAT_MARKER_PATH", "./data/heartbeat_verified.flag")


def _default_max_age(tsm: ModuleType) -> float:
    resolver = getattr(tsm, "_heartbeat_verification_max_age_seconds", None)
    if callable(resolver):
        try:
            return max(0.0, float(resolver()))
        except Exception:
            pass
    try:
        return max(0.0, float(os.environ.get("HEARTBEAT_VERIFICATION_MAX_AGE_SECONDS", "1800") or 1800))
    except Exception:
        return 1800.0


def _patch_trading_state_machine(tsm: ModuleType) -> None:
    if getattr(tsm, "_nija_usercustomize_heartbeat_helpers", False):
        return

    def _required_heartbeat_stage(*_args: Any, **_kwargs: Any) -> str:
        return _required_stage_from_env(tsm)

    def required_heartbeat_stage(*_args: Any, **_kwargs: Any) -> str:
        return _required_stage_from_env(tsm)

    def heartbeat_marker_is_fresh(marker_path: str | None = None, max_age_s: float | None = None) -> bool:
        status_fn = getattr(tsm, "_heartbeat_verification_status", None)
        canonical_path = _default_marker_path(tsm)
        if callable(status_fn) and (not marker_path or str(marker_path) == canonical_path):
            try:
                ok, _reason, _detail = status_fn()
                return bool(ok)
            except Exception:
                pass

        ok, _reason, payload = _read_heartbeat_marker(marker_path or canonical_path)
        if not ok:
            return False
        try:
            verified_at = float(
                payload.get("verified_at_epoch")
                or payload.get("timestamp_epoch")
                or payload.get("verified_at")
                or 0.0
            )
        except Exception:
            verified_at = 0.0
        if verified_at <= 0:
            return False
        max_age = _default_max_age(tsm) if max_age_s is None else max(0.0, float(max_age_s))
        return max_age <= 0 or (time.time() - verified_at) <= max_age

    def heartbeat_marker_stage_is_sufficient(
        marker_path: str | None = None,
        required_stage: str | None = None,
    ) -> bool:
        required = _normalize_stage(required_stage or _required_stage_from_env(tsm))
        status_fn = getattr(tsm, "_heartbeat_verification_status", None)
        canonical_path = _default_marker_path(tsm)
        if callable(status_fn) and (not marker_path or str(marker_path) == canonical_path):
            try:
                ok, _reason, detail = status_fn()
                if not ok:
                    return False
                stage = _normalize_stage((detail or {}).get("stage"))
                return _STAGE_ORDER[stage] >= _STAGE_ORDER[required]
            except Exception:
                pass

        ok, _reason, payload = _read_heartbeat_marker(marker_path or canonical_path)
        if not ok:
            return False
        stage = _normalize_stage(payload.get("stage"), default="AUTH_VERIFY")
        return _STAGE_ORDER[stage] >= _STAGE_ORDER[required]

    # Export the helpers directly on the module so `from bot.trading_state_machine
    # import _required_heartbeat_stage` cannot fail closed during dispatch.
    if not callable(getattr(tsm, "_required_heartbeat_stage", None)):
        setattr(tsm, "_required_heartbeat_stage", _required_heartbeat_stage)
    if not callable(getattr(tsm, "required_heartbeat_stage", None)):
        setattr(tsm, "required_heartbeat_stage", required_heartbeat_stage)
    if not callable(getattr(tsm, "heartbeat_marker_is_fresh", None)):
        setattr(tsm, "heartbeat_marker_is_fresh", heartbeat_marker_is_fresh)
    if not callable(getattr(tsm, "heartbeat_marker_stage_is_sufficient", None)):
        setattr(tsm, "heartbeat_marker_stage_is_sufficient", heartbeat_marker_stage_is_sufficient)

    setattr(tsm, "_nija_usercustomize_heartbeat_helpers", True)
    logger.critical(
        "USERCUSTOMIZE_HEARTBEAT_HELPERS_PATCHED module=%s required_stage=%s",
        getattr(tsm, "__name__", "<unknown>"),
        _required_stage_from_env(tsm),
    )


def _sync_generation_env(redis_generation: Any) -> None:
    try:
        generation = int(redis_generation)
    except Exception:
        return
    if generation <= 0:
        return

    gen = str(generation)
    os.environ["NIJA_WRITER_LEASE_GENERATION"] = gen
    os.environ["NIJA_WRITER_LEASE_GENERATION_LAST"] = gen
    os.environ["NIJA_WRITER_GENERATION"] = gen
    os.environ["NIJA_AUTHORITY_GENERATION"] = gen
    os.environ["NIJA_WRITER_GENERATION_SYNCED_TS"] = f"{time.time():.6f}"
    expected = os.environ.get("NIJA_WRITER_LEASE_GENERATION_EXPECTED", "").strip()
    if expected and expected != gen:
        os.environ.pop("NIJA_WRITER_LEASE_GENERATION_EXPECTED", None)


def _patch_writer_generation_tracker(wgt: ModuleType) -> None:
    if getattr(wgt, "_nija_usercustomize_generation_env_sync", False):
        return

    original_sync = getattr(wgt, "attempt_generation_sync_recovery", None)
    if callable(original_sync):
        def wrapped_attempt_generation_sync_recovery(local: int, redis_gen: int):
            recovered, message = original_sync(local, redis_gen)
            if recovered:
                _sync_generation_env(redis_gen)
                logger.critical(
                    "USERCUSTOMIZE_GENERATION_SYNC_ENV_APPLIED local_before=%s redis=%s message=%s",
                    local,
                    redis_gen,
                    message,
                )
            return recovered, message

        setattr(wrapped_attempt_generation_sync_recovery, "_nija_usercustomize_wrapped", True)
        setattr(wgt, "attempt_generation_sync_recovery", wrapped_attempt_generation_sync_recovery)

    original_reset = getattr(wgt, "reset_generation_to_redis", None)
    if callable(original_reset):
        def wrapped_reset_generation_to_redis():
            success, message = original_reset()
            if success:
                redis_gen = 0
                redis_reader = getattr(wgt, "get_redis_generation", None)
                if callable(redis_reader):
                    try:
                        redis_gen, _err = redis_reader()
                    except Exception:
                        redis_gen = 0
                _sync_generation_env(redis_gen)
                logger.critical(
                    "USERCUSTOMIZE_GENERATION_RESET_ENV_APPLIED redis=%s message=%s",
                    redis_gen,
                    message,
                )
            return success, message

        setattr(wrapped_reset_generation_to_redis, "_nija_usercustomize_wrapped", True)
        setattr(wgt, "reset_generation_to_redis", wrapped_reset_generation_to_redis)

    setattr(wgt, "_nija_usercustomize_generation_env_sync", True)
    logger.critical("USERCUSTOMIZE_GENERATION_TRACKER_PATCHED module=%s", getattr(wgt, "__name__", "<unknown>"))


def _normalize_live_execution_env() -> None:
    # Keep operator-facing env aligned with exchange compiler reality. Kraken BTC
    # spot compiles at a $10 minimum; leaving runtime env at $2 causes false
    # sizing assumptions and noisy resize/shrink/re-clamp cycles.
    for key, value in (
        ("KRAKEN_MIN_NOTIONAL_USD", "10"),
        ("MIN_NOTIONAL_OVERRIDE", "10"),
    ):
        try:
            current = float(os.environ.get(key, "0") or 0)
        except Exception:
            current = 0.0
        if current < float(value):
            os.environ[key] = value


def _patch_loaded_runtime_modules() -> None:
    _normalize_live_execution_env()
    for name in ("bot.trading_state_machine", "trading_state_machine"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            _patch_trading_state_machine(module)
    for name in ("bot.writer_generation_tracker", "writer_generation_tracker"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            _patch_writer_generation_tracker(module)


def _install_runtime_import_hook() -> None:
    global _ORIGINAL_IMPORT
    if _ORIGINAL_IMPORT is not None:
        return

    _ORIGINAL_IMPORT = builtins.__import__

    # Thread-local re-entry guard: prevents recursive calls within the same
    # thread when _patch_loaded_runtime_modules() is running inside the hook.
    _hook_local = threading.local()

    def _nija_import_hook(name, globals=None, locals=None, fromlist=(), level=0):
        module = _ORIGINAL_IMPORT(name, globals, locals, fromlist, level)  # type: ignore[misc]
        # Skip patch work if we are already inside the hook on this thread.
        # This prevents a RecursionError when the patching code itself imports
        # additional modules that re-enter the hook.
        if getattr(_hook_local, "active", False):
            return module
        _hook_local.active = True
        try:
            _patch_loaded_runtime_modules()
        except Exception as exc:
            logger.warning("USERCUSTOMIZE_RUNTIME_IMPORT_PATCH_FAILED name=%s err=%s", name, exc)
        finally:
            _hook_local.active = False
        return module

    builtins.__import__ = _nija_import_hook  # type: ignore[assignment]

    # Compact the import hook chain so the recursion shield remains the
    # outermost guard and the usercustomize hook is treated as a delegate.
    # This prevents deep wrapper chains that could exceed the recursion limit.
    try:
        _shield = sys.modules.get("import_hook_recursion_shield_patch") or sys.modules.get(
            "nija_import_hook_recursion_shield_patch"
        )
        if _shield is None:
            import importlib as _il
            _shield = _il.util.find_spec("import_hook_recursion_shield_patch") and _il.import_module(
                "import_hook_recursion_shield_patch"
            )
        compact_fn = getattr(_shield, "compact_import_chain", None) if _shield else None
        if callable(compact_fn):
            compact_fn()
            logger.critical("USERCUSTOMIZE_IMPORT_CHAIN_COMPACTED_AFTER_HOOK")
    except Exception as _compact_exc:
        logger.warning("USERCUSTOMIZE_COMPACT_CHAIN_FAILED err=%s", _compact_exc)

    _patch_loaded_runtime_modules()
    logger.critical("USERCUSTOMIZE_RUNTIME_IMPORT_HOOK_INSTALLED")


threading.Thread(target=_position_sync_hook_watchdog, name="position-sync-hook", daemon=True).start()

try:
    from bot.strategy_publication_patch import install_import_hook as _install_strategy_publication
    _install_strategy_publication()
    logger.warning("STRATEGY_PUBLICATION_INSTALL_REQUESTED")
except Exception as exc:
    logger.warning("STRATEGY_PUBLICATION_INSTALL_FAILED err=%s", exc)

_install_runtime_import_hook()
_normalize_live_execution_env()
