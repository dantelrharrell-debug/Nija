"""NIJA production readiness corrective set v39.

Repairs two production defects exposed after v38:

1. A recoverable writer-epoch loss (missing Redis lock with stale fencing epoch)
   currently invokes bot_main's lease-lost callback, which immediately sets the
   process shutdown event. That prevents the canonical authority object from
   acquiring a fresh token/generation even though acquire_once already supports
   safe re-election. v39 keeps execution fail-closed, performs bounded
   re-election only for this specific missing-lock/fencing-mismatch condition,
   re-verifies distributed authority, re-registers the live core thread, then
   restarts the existing Kraken recovery coordinator. All other authority-loss
   reasons retain the original shutdown behavior.

2. OKX market-data calls can still reach a REST client as ``*-USDTT`` because
   older payload repair wrappers normalize order payloads but not all request
   params. v39 wraps every loaded OKX REST ``_request`` boundary and normalizes
   ``params['instId']`` and ``payload['instId']`` immediately before dispatch.

The patch never fabricates balances, clears terminal-risk files, bypasses SEAK,
or grants execution authority without a fresh writer lease and synchronous
writer-authority verification.
"""
from __future__ import annotations

import builtins
import importlib
import logging
import os
from pathlib import Path
import re
import sys
import threading
import time
from functools import wraps
from types import ModuleType
from typing import Any, Optional

LOGGER = logging.getLogger("nija.production_readiness_v39")
MARKER = "20260807-production-readiness-v39"

_PATCH_LOCK = threading.RLock()
_RECOVERY_LOCK = threading.Lock()
_RECOVERY_ACTIVE = False
_INSTALL_FLAG = "_NIJA_PRODUCTION_READINESS_V39_IMPORT_HOOK"
_IMPORTLIB_FLAG = "_NIJA_PRODUCTION_READINESS_V39_IMPORTLIB_HOOK"
_OKX_WRAP_ATTR = "_nija_okx_marketdata_boundary_v39"
_BOT_MAIN_PATCH_ATTR = "_nija_writer_reelection_v39"
_VALID_QUOTES = ("USDT", "USDC", "USD")


def _cfg_float(name: str, default: float, minimum: float) -> float:
    try:
        return max(minimum, float(os.environ.get(name, str(default)) or default))
    except (TypeError, ValueError):
        return max(minimum, default)


def _clean_symbol(symbol: Any) -> str:
    raw = str(symbol or "").upper().strip().replace("/", "-").replace("_", "-").replace(":", "-")
    raw = re.sub(r"[^A-Z0-9\-]", "", raw)
    while "--" in raw:
        raw = raw.replace("--", "-")
    return raw


def _normalize_okx_inst_id(symbol: Any) -> str:
    raw = _clean_symbol(symbol)
    if not raw:
        return raw
    if raw.endswith("-USDTT"):
        raw = raw[:-6] + "-USDT"
    elif raw.endswith("-USDTC"):
        raw = raw[:-6] + "-USDC"
    elif raw.endswith("USDTT") and "-" not in raw:
        raw = raw[:-5] + "USDT"
    elif raw.endswith("USDTC") and "-" not in raw:
        raw = raw[:-5] + "USDC"

    if "-" in raw:
        base, quote = raw.rsplit("-", 1)
        if not base:
            return raw
        if quote == "USD":
            return f"{base}-USDT"
        if quote in {"USDT", "USDC"}:
            return f"{base}-{quote}"
        return raw

    for quote in sorted(_VALID_QUOTES, key=len, reverse=True):
        if raw.endswith(quote) and len(raw) > len(quote):
            base = raw[:-len(quote)]
            return f"{base}-USDT" if quote == "USD" else f"{base}-{quote}"
    return raw


def _malformed_okx_inst_id(inst: str) -> bool:
    text = str(inst or "").upper()
    return text.endswith("USDTT") or text.endswith("USDTC")


def _looks_like_okx_rest_class(cls: type) -> bool:
    name = str(getattr(cls, "__name__", "")).lower()
    module = str(getattr(cls, "__module__", "")).lower()
    base_url = str(getattr(cls, "BASE_URL", "")).lower()
    return "okx" in name or "okx" in module or "okx.com" in base_url


def _candidate_okx_rest_classes(module: ModuleType) -> list[type]:
    found: list[type] = []
    for obj in vars(module).values():
        if not isinstance(obj, type):
            continue
        if not callable(getattr(obj, "_request", None)):
            continue
        if _looks_like_okx_rest_class(obj) and obj not in found:
            found.append(obj)
    return found


def _wrap_okx_rest_class(rest_cls: type, module_name: str) -> bool:
    original = getattr(rest_cls, "_request", None)
    if not callable(original) or getattr(original, _OKX_WRAP_ATTR, False):
        return False

    @wraps(original)
    def _request(
        self: Any,
        method: str,
        path: str,
        *,
        params: Optional[dict[str, Any]] = None,
        payload: Optional[dict[str, Any]] = None,
        private: bool = False,
    ) -> Any:
        clean_params = dict(params or {}) if isinstance(params, dict) else params
        clean_payload = dict(payload or {}) if isinstance(payload, dict) else payload

        for container_name, container in (("params", clean_params), ("payload", clean_payload)):
            if not isinstance(container, dict) or "instId" not in container:
                continue
            before = str(container.get("instId") or "")
            after = _normalize_okx_inst_id(before)
            if after != before:
                LOGGER.warning(
                    "OKX_INSTID_BOUNDARY_V39_NORMALIZED marker=%s path=%s container=%s before=%s after=%s",
                    MARKER,
                    path,
                    container_name,
                    before,
                    after,
                )
            container["instId"] = after
            if _malformed_okx_inst_id(after):
                LOGGER.critical(
                    "OKX_INSTID_BOUNDARY_V39_REJECTED marker=%s path=%s container=%s instId=%s",
                    MARKER,
                    path,
                    container_name,
                    after,
                )
                if str(path or "") in {"/api/v5/market/candles", "/api/v5/market/ticker"}:
                    return {
                        "code": "51001",
                        "msg": "v39_rejected_malformed_instId_before_dispatch",
                        "data": [],
                    }

        return original(
            self,
            method,
            path,
            params=clean_params,
            payload=clean_payload,
            private=private,
        )

    setattr(_request, _OKX_WRAP_ATTR, True)
    setattr(_request, "__wrapped__", original)
    setattr(rest_cls, "_request", _request)
    LOGGER.critical(
        "OKX_INSTID_BOUNDARY_V39_PATCHED marker=%s module=%s class=%s",
        MARKER,
        module_name,
        getattr(rest_cls, "__name__", "<unknown>"),
    )
    return True


def _patch_okx_module(module: ModuleType) -> bool:
    changed = False
    for cls in _candidate_okx_rest_classes(module):
        changed = _wrap_okx_rest_class(cls, getattr(module, "__name__", "<unknown>")) or changed
    return changed


def _recoverable_writer_loss(reason: str) -> bool:
    return "lock_missing_and_fencing_token_mismatch" in str(reason or "")


def _configured_paths(env_name: str, defaults: tuple[str, ...]) -> list[Path]:
    raw = str(os.environ.get(env_name, "") or "").strip()
    values = [piece.strip() for piece in raw.split(",") if piece.strip()] if raw else list(defaults)
    return [Path(value).expanduser() for value in values]


def _terminal_stop_files_present() -> bool:
    candidates = _configured_paths(
        "NIJA_EMERGENCY_STOP_FILES",
        ("/app/EMERGENCY_STOP", "./EMERGENCY_STOP", "./data/EMERGENCY_STOP"),
    )
    candidates += _configured_paths(
        "NIJA_EMERGENCY_STOP_STATE_FILES",
        ("/app/.nija_kill_switch_state.json", "./.nija_kill_switch_state.json", "./data/.nija_kill_switch_state.json"),
    )
    for path in candidates:
        try:
            if path.exists() and path.is_file():
                return True
        except Exception:
            continue
    return False


def _restart_authority_monitor(bot_main_module: ModuleType) -> bool:
    old = getattr(bot_main_module, "_authority_heartbeat_monitor", None)
    if old is not None and callable(getattr(old, "stop", None)):
        try:
            old.stop()
        except Exception:
            pass
    try:
        heartbeat = importlib.import_module("bot.authority_heartbeat")
        starter = getattr(heartbeat, "start_authority_heartbeat", None)
        if not callable(starter):
            return False
        monitor = starter()
        setattr(bot_main_module, "_authority_heartbeat_monitor", monitor)
        return monitor is not None
    except Exception as exc:
        LOGGER.error("WRITER_REELECTION_V39_MONITOR_RESTART_FAILED marker=%s err=%s", MARKER, exc)
        return False


def _assert_writer_authority() -> bool:
    try:
        context = importlib.import_module("bot.execution_authority_context")
        verifier = getattr(context, "assert_distributed_writer_authority", None)
        if not callable(verifier):
            return False
        verifier()
        return True
    except Exception as exc:
        LOGGER.warning("WRITER_REELECTION_V39_VERIFY_FAILED marker=%s err=%s", MARKER, exc)
        return False


def _kick_kraken_recovery() -> None:
    try:
        module = importlib.import_module("bot.canonical_broker_startup_convergence_v24")
        coordinator = getattr(module, "_start_kraken_recovery_coordinator", None)
        if callable(coordinator):
            coordinator()
            LOGGER.info("KRAKEN_RECOVERY_V39_RETRIGGERED marker=%s", MARKER)
    except Exception as exc:
        LOGGER.warning("KRAKEN_RECOVERY_V39_RETRIGGER_FAILED marker=%s err=%s", MARKER, exc)


def _resume_seak_if_writer_halt() -> bool:
    if _terminal_stop_files_present():
        LOGGER.critical(
            "WRITER_REELECTION_V39_SEAK_REMAINS_HALTED marker=%s reason=emergency_stop_file_present",
            MARKER,
        )
        return False
    try:
        seak_module = importlib.import_module("bot.single_execution_authority_kernel")
        getter = getattr(seak_module, "get_seak", None)
        if not callable(getter):
            return False
        seak = getter()
        if not bool(getattr(seak, "is_halted", False)):
            return True
        halt_reason = str(getattr(seak, "_halt_reason", "") or "")
        if not halt_reason.startswith("entrypoint_writer_authority_lost:"):
            LOGGER.critical(
                "WRITER_REELECTION_V39_SEAK_REMAINS_HALTED marker=%s reason=non_writer_halt halt_reason=%s",
                MARKER,
                halt_reason,
            )
            return False
        if not _recoverable_writer_loss(halt_reason):
            return False
        resume = getattr(seak, "resume", None)
        if not callable(resume):
            return False
        resume(caller="writer_reelection_v39")
        return True
    except Exception as exc:
        LOGGER.warning("WRITER_REELECTION_V39_SEAK_RESUME_FAILED marker=%s err=%s", MARKER, exc)
        return False


def _run_writer_recovery(
    bot_main_module: ModuleType,
    runtime: Any,
    reason: str,
    fallback_shutdown_callback: Any,
) -> None:
    global _RECOVERY_ACTIVE
    try:
        time.sleep(0.20)
        heartbeat = getattr(runtime, "_heartbeat_thread", None)
        if heartbeat is not None and heartbeat is not threading.current_thread():
            try:
                if heartbeat.is_alive():
                    heartbeat.join(timeout=3.0)
            except Exception:
                pass

        max_s = _cfg_float("NIJA_WRITER_REELECTION_MAX_S", 120.0, 5.0)
        retry_s = _cfg_float("NIJA_WRITER_REELECTION_RETRY_S", 2.0, 0.25)
        deadline = time.monotonic() + max_s
        attempt = 0
        last_error = "not_attempted"

        LOGGER.critical(
            "WRITER_REELECTION_V39_STARTED marker=%s reason=%s max_s=%.1f retry_s=%.1f",
            MARKER,
            reason,
            max_s,
            retry_s,
        )

        while time.monotonic() < deadline:
            attempt += 1
            try:
                result = runtime.acquire_once()
            except Exception as exc:
                result = None
                last_error = f"acquire_exception:{type(exc).__name__}:{exc}"
            if result is not None and bool(getattr(result, "acquired", False)):
                core = getattr(bot_main_module, "_core_loop_thread", None)
                if core is not None and callable(getattr(core, "is_alive", None)) and core.is_alive():
                    register = getattr(runtime, "register_core_thread", None)
                    if callable(register):
                        register(core)
                    record_scan = getattr(runtime, "record_scan_started", None)
                    if callable(record_scan):
                        record_scan()

                monitor_ok = _restart_authority_monitor(bot_main_module)
                authority_ok = monitor_ok and _assert_writer_authority()
                if authority_ok:
                    _kick_kraken_recovery()
                    seak_resumed = _resume_seak_if_writer_halt()
                    reconcile = getattr(runtime, "_notify_runtime_reconciliation", None)
                    if callable(reconcile):
                        try:
                            reconcile("writer_reelected_v39")
                        except Exception:
                            pass
                    LOGGER.critical(
                        "WRITER_REELECTION_V39_RECOVERED marker=%s attempts=%d generation=%s token_prefix=%s seak_resumed=%s",
                        MARKER,
                        attempt,
                        getattr(result, "generation", 0),
                        str(getattr(result, "token", "") or "")[:8],
                        seak_resumed,
                    )
                    return
                last_error = "post_acquire_authority_verify_failed"
                try:
                    runtime.release()
                except Exception:
                    pass
            else:
                last_error = str(getattr(result, "error", "") or last_error)

            remaining = deadline - time.monotonic()
            if remaining > 0:
                time.sleep(min(retry_s, remaining))

        LOGGER.critical(
            "WRITER_REELECTION_V39_EXHAUSTED marker=%s attempts=%d last_error=%s action=original_shutdown",
            MARKER,
            attempt,
            last_error,
        )
        if callable(fallback_shutdown_callback):
            fallback_shutdown_callback(f"v39_reelection_exhausted:{reason}:{last_error}")
    finally:
        with _RECOVERY_LOCK:
            _RECOVERY_ACTIVE = False


def _start_writer_recovery(
    bot_main_module: ModuleType,
    runtime: Any,
    reason: str,
    fallback_shutdown_callback: Any,
) -> bool:
    global _RECOVERY_ACTIVE
    if not _recoverable_writer_loss(reason):
        return False
    with _RECOVERY_LOCK:
        if _RECOVERY_ACTIVE:
            LOGGER.warning("WRITER_REELECTION_V39_ALREADY_ACTIVE marker=%s reason=%s", MARKER, reason)
            return True
        _RECOVERY_ACTIVE = True
    thread = threading.Thread(
        target=_run_writer_recovery,
        args=(bot_main_module, runtime, reason, fallback_shutdown_callback),
        name="writer-reelection-v39",
        daemon=True,
    )
    thread.start()
    return True


def _patch_bot_main(module: ModuleType) -> bool:
    original = getattr(module, "_acquire_writer_authority_before_nonce", None)
    if not callable(original) or getattr(original, _BOT_MAIN_PATCH_ATTR, False):
        return False

    original_keepalive = getattr(module, "_keep_process_alive_after_loop_return", None)

    @wraps(original)
    def _acquire_writer_authority_before_nonce(*args: Any, **kwargs: Any) -> bool:
        ok = bool(original(*args, **kwargs))
        if not ok:
            return False
        runtime = getattr(module, "_writer_authority_runtime", None)
        if runtime is None or not callable(getattr(runtime, "set_on_lost_callback", None)):
            return True

        fallback_shutdown_callback = getattr(runtime, "_on_lost_callback", None)

        def _on_lost(reason: str) -> None:
            if not _recoverable_writer_loss(reason):
                if callable(fallback_shutdown_callback):
                    fallback_shutdown_callback(reason)
                return

            monitor = getattr(module, "_authority_heartbeat_monitor", None)
            if monitor is not None and callable(getattr(monitor, "stop", None)):
                try:
                    monitor.stop()
                except Exception:
                    pass
            os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] = "0"
            os.environ["NIJA_EXECUTION_ACTIVE"] = "false"
            LOGGER.critical(
                "WRITER_REELECTION_V39_INTERCEPTED marker=%s reason=%s trading_fail_closed=true",
                MARKER,
                reason,
            )
            if not _start_writer_recovery(module, runtime, reason, fallback_shutdown_callback):
                if callable(fallback_shutdown_callback):
                    fallback_shutdown_callback(reason)

        runtime.set_on_lost_callback(_on_lost)
        LOGGER.critical("WRITER_REELECTION_V39_CALLBACK_ARMED marker=%s", MARKER)
        return True

    setattr(_acquire_writer_authority_before_nonce, _BOT_MAIN_PATCH_ATTR, True)
    setattr(_acquire_writer_authority_before_nonce, "__wrapped__", original)
    setattr(module, "_acquire_writer_authority_before_nonce", _acquire_writer_authority_before_nonce)

    if callable(original_keepalive):
        @wraps(original_keepalive)
        def _keep_process_alive_after_loop_return() -> None:
            log = getattr(module, "logger", LOGGER)
            shutdown = getattr(module, "_shutdown_event", None)
            if shutdown is None:
                return original_keepalive()
            log.critical(
                "BOT_MAIN_KEEPALIVE_V39_ENTERED marker=%s startup_complete=%s",
                MARKER,
                bool(getattr(module, "_startup_complete", False)),
            )
            last_heartbeat = 0.0
            while not shutdown.is_set():
                runtime = getattr(module, "_writer_authority_runtime", None)
                core_thread = getattr(module, "_core_loop_thread", None)
                if runtime is not None and bool(getattr(runtime, "lost", False)):
                    with _RECOVERY_LOCK:
                        recovering = bool(_RECOVERY_ACTIVE)
                    if recovering:
                        log.warning(
                            "BOT_MAIN_KEEPALIVE_V39_REELECTION_WAIT marker=%s trading_fail_closed=true",
                            MARKER,
                        )
                    else:
                        log.critical(
                            "BOT_MAIN_KEEPALIVE_V39_EXIT marker=%s reason=writer_authority_lost_no_recovery",
                            MARKER,
                        )
                        shutdown.set()
                        break
                elif core_thread is not None and not core_thread.is_alive():
                    log.critical(
                        "CORE_LOOP_EXITED thread_name=%s ident=%s",
                        getattr(core_thread, "name", "unknown"),
                        getattr(core_thread, "ident", None),
                    )
                    shutdown.set()
                    break

                now = time.monotonic()
                if now - last_heartbeat >= 60.0:
                    active_threads = [t.name for t in threading.enumerate() if t.is_alive()]
                    log.info(
                        "BOT_MAIN_KEEPALIVE_HEARTBEAT startup_complete=%s writer_authority=%s writer_recovery=%s active_threads=%s",
                        bool(getattr(module, "_startup_complete", False)),
                        bool(runtime and getattr(runtime, "acquired", False)),
                        recovering if runtime is not None and bool(getattr(runtime, "lost", False)) else False,
                        active_threads,
                    )
                    last_heartbeat = now
                poll = max(0.25, float(getattr(module, "SUPERVISOR_POLL_INTERVAL_S", 10.0) or 10.0))
                shutdown.wait(timeout=poll)
            log.info("BOT_MAIN_KEEPALIVE_EXIT reason=shutdown_event_set")

        setattr(_keep_process_alive_after_loop_return, _BOT_MAIN_PATCH_ATTR, True)
        setattr(_keep_process_alive_after_loop_return, "__wrapped__", original_keepalive)
        setattr(module, "_keep_process_alive_after_loop_return", _keep_process_alive_after_loop_return)

    LOGGER.critical("WRITER_REELECTION_V39_BOT_MAIN_PATCHED marker=%s keepalive_guard=true", MARKER)
    return True


def _interesting_module(name: str) -> bool:
    text = str(name or "").lower()
    return (
        text in {
            "bot.bot_main",
            "bot.broker_manager",
            "broker_manager",
            "bot.multi_account_broker_manager",
            "multi_account_broker_manager",
            "bot.broker_integration",
            "broker_integration",
        }
        or "okx" in text
    )


def _patch_loaded() -> bool:
    changed = False
    for name, module in list(sys.modules.items()):
        if not isinstance(module, ModuleType) or not _interesting_module(name):
            continue
        try:
            if name == "bot.bot_main":
                changed = _patch_bot_main(module) or changed
            changed = _patch_okx_module(module) or changed
        except Exception as exc:
            LOGGER.warning("PRODUCTION_READINESS_V39_PATCH_FAILED marker=%s module=%s err=%s", MARKER, name, exc)
    return changed


def install_import_hook() -> bool:
    with _PATCH_LOCK:
        _patch_loaded()
        if not getattr(builtins, _INSTALL_FLAG, False):
            original_import = builtins.__import__

            @wraps(original_import)
            def importing(name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0):
                result = original_import(name, globals, locals, fromlist, level)
                if _interesting_module(str(name)):
                    _patch_loaded()
                return result

            builtins.__import__ = importing
            setattr(builtins, _INSTALL_FLAG, True)

        if not getattr(importlib, _IMPORTLIB_FLAG, False):
            original_import_module = importlib.import_module

            @wraps(original_import_module)
            def import_module(name: str, package: Optional[str] = None):
                result = original_import_module(name, package)
                if _interesting_module(str(name)):
                    _patch_loaded()
                return result

            importlib.import_module = import_module  # type: ignore[assignment]
            setattr(importlib, _IMPORTLIB_FLAG, True)

        os.environ["NIJA_PRODUCTION_READINESS_V39_INSTALLED"] = "1"
        LOGGER.critical(
            "PRODUCTION_READINESS_V39_INSTALLED marker=%s fail_closed=true writer_reelection=bounded okx_instid_boundary=true kraken_retrigger=true",
            MARKER,
        )
        return True


def install() -> bool:
    return install_import_hook()
