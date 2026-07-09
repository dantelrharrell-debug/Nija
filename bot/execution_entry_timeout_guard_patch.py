from __future__ import annotations

import builtins
import logging
import os
import queue
import threading
import time
from functools import wraps
from types import ModuleType
from typing import Any

logger = logging.getLogger("nija.execution_entry_timeout_guard")

_MARKER = "EXECUTION_ENTRY_TIMEOUT_GUARD_PATCHED marker=20260709ac"
_IMPORT_FLAG = "_NIJA_EXECUTION_ENTRY_TIMEOUT_GUARD_IMPORT_HOOK_20260709AC"
_WRAP_ATTR = "_nija_execution_entry_timeout_guard_20260709ac"
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}


def _truthy(name: str, default: str = "true") -> bool:
    return str(os.environ.get(name, default)).strip().lower() in _TRUE


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)) or default)
    except Exception:
        return default


def _derived_timeout_s() -> float:
    ack_timeout = max(1.0, _float_env("NIJA_ACK_TIMEOUT_S", 30.0))
    return max(40.0, ack_timeout + 10.0)


def _timeout_s() -> float:
    try:
        raw = os.environ.get("NIJA_EXECUTION_ENTRY_TIMEOUT_SECONDS")
        if raw not in (None, ""):
            return max(5.0, float(raw or "0"))
        return _derived_timeout_s()
    except Exception:
        return _derived_timeout_s()


def _symbol_from(args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
    return str(kwargs.get("symbol") or (args[0] if len(args) > 0 else "") or "").upper().replace("/", "-")


def _side_from(args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
    return str(kwargs.get("side") or (args[1] if len(args) > 1 else "") or "")


def _size_from(args: tuple[Any, ...], kwargs: dict[str, Any]) -> float:
    for value in (
        kwargs.get("position_size"),
        kwargs.get("size_usd"),
        kwargs.get("notional_usd"),
        args[2] if len(args) > 2 else None,
    ):
        try:
            amount = float(value)
            if amount > 0:
                return amount
        except Exception:
            continue
    return 0.0


def _patch_module(module: ModuleType) -> bool:
    cls = getattr(module, "ExecutionEngine", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "execute_entry", None)
    if not callable(original) or getattr(original, _WRAP_ATTR, False):
        return bool(getattr(original, _WRAP_ATTR, False))

    @wraps(original)
    def execute_entry(self: Any, *args: Any, **kwargs: Any):
        if not _truthy("NIJA_EXECUTION_ENTRY_TIMEOUT_GUARD_ENABLED", "true"):
            return original(self, *args, **kwargs)

        timeout = _timeout_s()
        symbol = _symbol_from(args, kwargs)
        side = _side_from(args, kwargs)
        size = _size_from(args, kwargs)
        result_queue: "queue.Queue[tuple[str, Any]]" = queue.Queue(maxsize=1)

        def _runner() -> None:
            try:
                result_queue.put(("result", original(self, *args, **kwargs)), block=False)
            except BaseException as exc:  # noqa: BLE001 - must return exceptions across thread boundary
                try:
                    result_queue.put(("error", exc), block=False)
                except Exception:
                    pass

        worker = threading.Thread(
            target=_runner,
            name=f"nija-execute-entry-timeout-{symbol or 'unknown'}",
            daemon=True,
        )
        started = time.time()
        worker.start()
        worker.join(timeout)

        if worker.is_alive():
            logger.critical(
                "EXECUTION_ENTRY_TIMEOUT_GUARD_TIMEOUT marker=20260709ac symbol=%s side=%s size_usd=%.2f timeout_s=%.1f ack_timeout_s=%.1f action=return_false_loop_continue",
                symbol,
                side,
                size,
                timeout,
                _float_env("NIJA_ACK_TIMEOUT_S", 30.0),
            )
            print(
                f"[NIJA-PRINT] EXECUTION_ENTRY_TIMEOUT_GUARD_TIMEOUT marker=20260709ac symbol={symbol} side={side} size=${size:.2f} timeout_s={timeout:.1f}",
                flush=True,
            )
            return None

        try:
            kind, payload = result_queue.get_nowait()
        except queue.Empty:
            logger.warning(
                "EXECUTION_ENTRY_TIMEOUT_GUARD_EMPTY_RESULT marker=20260709ac symbol=%s side=%s elapsed_ms=%.0f",
                symbol,
                side,
                (time.time() - started) * 1000,
            )
            return None

        if kind == "error":
            raise payload
        return payload

    setattr(execute_entry, _WRAP_ATTR, True)
    setattr(cls, "execute_entry", execute_entry)
    logger.warning("%s class=ExecutionEngine timeout_s=%.1f ack_timeout_s=%.1f", _MARKER, _timeout_s(), _float_env("NIJA_ACK_TIMEOUT_S", 30.0))
    print("[NIJA-PRINT] EXECUTION_ENTRY_TIMEOUT_GUARD_PATCHED marker=20260709ac", flush=True)
    return True


def _try_patch_loaded() -> bool:
    patched = False
    for name in ("bot.execution_engine", "execution_engine"):
        try:
            import sys
            module = sys.modules.get(name)
            if isinstance(module, ModuleType):
                patched = _patch_module(module) or patched
        except Exception:
            continue
    return patched


def install_import_hook() -> None:
    os.environ.setdefault("NIJA_EXECUTION_ENTRY_TIMEOUT_GUARD_ENABLED", "true")
    os.environ.setdefault("NIJA_EXECUTION_ENTRY_TIMEOUT_SECONDS", str(int(_derived_timeout_s())))
    _try_patch_loaded()
    if getattr(builtins, _IMPORT_FLAG, False):
        return
    original_import = builtins.__import__

    def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        try:
            if name.endswith("execution_engine") or "execution_engine" in str(name):
                _try_patch_loaded()
        except Exception as exc:
            logger.warning("EXECUTION_ENTRY_TIMEOUT_GUARD_IMPORT_FAILED marker=20260709ac name=%s err=%s", name, exc)
        return module

    builtins.__import__ = guarded_import
    setattr(builtins, _IMPORT_FLAG, True)
    logger.warning("EXECUTION_ENTRY_TIMEOUT_GUARD_IMPORT_HOOK marker=20260709ac installed=true timeout_s=%s", os.environ.get("NIJA_EXECUTION_ENTRY_TIMEOUT_SECONDS"))


def install() -> None:
    install_import_hook()
