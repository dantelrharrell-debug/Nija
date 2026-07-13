"""Canonical scan ownership and broker-auth convergence.

This patch is installed after all legacy runtime wrappers. It provides one
process-wide scan owner per account/broker, lets overlapping callers reuse the
owner's completed result, collapses recursive OKX connect wrappers, and keeps an
invalid Coinbase PEM isolated before SDK calls.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
import time
from dataclasses import dataclass, field
from types import ModuleType, SimpleNamespace
from typing import Any, Callable

logger = logging.getLogger("nija.scan_owner_okx_auth_convergence")
MARKER = "20260713b"
_LOCK = threading.RLock()
_WATCHDOG_STARTED = False


@dataclass
class _ScanState:
    lock: threading.Lock = field(default_factory=threading.Lock)
    complete: threading.Event = field(default_factory=threading.Event)
    result: Any = None
    owner_thread_id: int | None = None
    started_at: float = 0.0


_SCAN_STATES: dict[str, _ScanState] = {}
_SCAN_STATES_GUARD = threading.RLock()


def _empty_result(reason: str = "scan_owner_timeout") -> SimpleNamespace:
    return SimpleNamespace(
        symbols_scored=0,
        entries_taken=0,
        entries_blocked=1,
        exits_taken=0,
        next_interval=max(5, int(float(os.getenv("NIJA_DUPLICATE_SCAN_NEXT_INTERVAL_S", "15") or 15))),
        errors=[reason],
        metadata={reason: True},
    )


def _coerce_result(result: Any) -> Any:
    if result is None:
        return _empty_result("empty_scan_result")
    if isinstance(result, tuple):
        scored = int(result[0] or 0) if len(result) > 0 else 0
        blocked = int(result[1] or 0) if len(result) > 1 else 0
        entered = int(result[2] or 0) if len(result) > 2 else 0
        meta = result[3] if len(result) > 3 and isinstance(result[3], dict) else {}
        return SimpleNamespace(
            symbols_scored=scored,
            entries_taken=entered,
            entries_blocked=blocked,
            exits_taken=int(meta.get("exits_taken", 0) or 0),
            next_interval=int(meta.get("next_interval", 15) or 15),
            errors=list(meta.get("errors", [])),
            metadata=meta,
        )
    required = ("symbols_scored", "entries_taken", "entries_blocked", "exits_taken", "next_interval")
    return result if all(hasattr(result, name) for name in required) else _empty_result("invalid_scan_result")


def _clean(value: Any) -> str:
    raw = getattr(value, "value", value)
    return str(raw or "").strip().lower().replace(" ", "_")


def _resolve_broker(owner: Any, args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
    return (
        kwargs.get("broker")
        or getattr(owner, "broker", None)
        or getattr(owner, "broker_client", None)
        or getattr(owner, "_broker", None)
        or (args[0] if args else None)
    )


def _identity(broker: Any, owner: Any = None) -> str:
    account = ""
    for obj in (broker, owner):
        if obj is None:
            continue
        for attr in ("account_id", "user_id", "account_name", "owner_id"):
            try:
                value = getattr(obj, attr, None)
            except Exception:
                value = None
            if value:
                account = _clean(value)
                break
        if account:
            break
    if not account:
        for obj in (broker, owner):
            account_type = getattr(obj, "account_type", None) if obj is not None else None
            value = getattr(account_type, "value", account_type)
            if value:
                account = _clean(value)
                break
    account = account or "platform"

    text_parts: list[str] = []
    for obj in (broker, owner):
        if obj is None:
            continue
        for attr in ("broker_type", "broker_name", "name", "exchange", "exchange_name"):
            try:
                value = getattr(obj, attr, "")
                text_parts.append(_clean(value))
            except Exception:
                continue
        text_parts.append(type(obj).__name__.lower())
    text = " ".join(text_parts)
    venue = next((name for name in ("kraken", "coinbase", "okx", "alpaca", "binance") if name in text), "unknown")
    return f"{account}:{venue}"


def _unwrap_scan(func: Callable[..., Any]) -> Callable[..., Any]:
    current = func
    seen: set[int] = set()
    for _ in range(4096):
        if id(current) in seen:
            break
        seen.add(id(current))
        wrapped = getattr(current, "__wrapped__", None)
        if not callable(wrapped):
            break
        current = wrapped
    return current


def _patch_core(module: ModuleType) -> bool:
    cls = getattr(module, "NijaCoreLoop", None)
    if not isinstance(cls, type):
        return False
    current = getattr(cls, "run_scan_phase", None)
    if not callable(current):
        return False
    if getattr(current, "_nija_scan_owner_result_reuse_20260713b", False):
        return True
    base = _unwrap_scan(current)

    def run_scan_phase(self: Any, *args: Any, **kwargs: Any) -> Any:
        broker = _resolve_broker(self, args, kwargs)
        key = _identity(broker, self)
        with _SCAN_STATES_GUARD:
            state = _SCAN_STATES.setdefault(key, _ScanState())
        thread_id = threading.get_ident()
        if state.owner_thread_id == thread_id:
            logger.error("REENTRANT_SCAN_SUPPRESSED marker=%s identity=%s", MARKER, key)
            return _empty_result("reentrant_scan")

        acquire_timeout = max(0.1, float(os.getenv("NIJA_ACCOUNT_SCAN_LOCK_TIMEOUT_S", "1.0") or 1.0))
        if state.lock.acquire(timeout=acquire_timeout):
            try:
                state.owner_thread_id = thread_id
                state.started_at = time.monotonic()
                state.complete.clear()
                result = _coerce_result(base(self, *args, **kwargs))
                state.result = result
                return result
            finally:
                state.owner_thread_id = None
                state.complete.set()
                state.lock.release()

        wait_timeout = max(5.0, float(os.getenv("NIJA_DUPLICATE_SCAN_RESULT_WAIT_S", "45") or 45))
        if state.complete.wait(timeout=wait_timeout) and state.result is not None:
            logger.info("DUPLICATE_SCAN_RESULT_REUSED marker=%s identity=%s", MARKER, key)
            return state.result

        logger.error(
            "SCAN_OWNER_TIMEOUT marker=%s identity=%s owner_thread=%s age_s=%.2f",
            MARKER, key, state.owner_thread_id, max(0.0, time.monotonic() - state.started_at),
        )
        return _empty_result("scan_owner_timeout")

    for attr in (
        "_nija_scan_owner_result_reuse_20260713b",
        "_nija_scan_wrapper_canonical_h",
        "_nija_scan_identity_lock_v2",
        "_nija_account_scan_serialized_e",
        "_nija_final_result_contract_e",
        "_nija_account_scan_serialized",
        "_nija_final_result_contract",
    ):
        setattr(run_scan_phase, attr, True)
    run_scan_phase.__wrapped__ = base  # type: ignore[attr-defined]
    setattr(cls, "run_scan_phase", run_scan_phase)
    logger.critical("SCAN_OWNER_RESULT_REUSE_PATCHED marker=%s base=%s", MARKER, getattr(base, "__qualname__", "unknown"))
    return True


def _unwrap_connect(func: Callable[..., Any]) -> Callable[..., Any]:
    current = func
    seen: set[int] = set()
    for _ in range(256):
        if id(current) in seen:
            break
        seen.add(id(current))
        wrapped = getattr(current, "__wrapped__", None)
        if not callable(wrapped):
            break
        current = wrapped
    return current


def _apply_okx_url(instance: Any, url: str) -> None:
    os.environ["OKX_BASE_URL"] = url
    for attr in ("base_url", "api_base_url", "endpoint", "api_url", "rest_url"):
        try:
            if hasattr(instance, attr):
                setattr(instance, attr, url)
        except Exception:
            continue


def _patch_brokers(module: ModuleType) -> bool:
    changed = False
    auth = sys.modules.get("broker_auth_recovery_patch")
    coinbase_cls = getattr(module, "CoinbaseBroker", None)
    okx_cls = getattr(module, "OKXBroker", None)

    if isinstance(coinbase_cls, type):
        current = getattr(coinbase_cls, "connect", None)
        if callable(current) and not getattr(current, "_nija_coinbase_failfast_20260713b", False):
            base = _unwrap_connect(current)
            def coinbase_connect(self: Any, *args: Any, **kwargs: Any) -> Any:
                normalizer = getattr(auth, "normalize_coinbase_environment", None)
                valid = bool(normalizer()) if callable(normalizer) else False
                if not valid:
                    try:
                        self.connected = False
                    except Exception:
                        pass
                    logger.error("COINBASE_INVALID_PEM_ISOLATED marker=%s", MARKER)
                    return False
                return base(self, *args, **kwargs)
            coinbase_connect._nija_coinbase_failfast_20260713b = True  # type: ignore[attr-defined]
            coinbase_connect._nija_auth_recovery_20260711n = True  # type: ignore[attr-defined]
            coinbase_connect._nija_auth_v2 = True  # type: ignore[attr-defined]
            coinbase_connect.__wrapped__ = base  # type: ignore[attr-defined]
            setattr(coinbase_cls, "connect", coinbase_connect)
            changed = True

    if isinstance(okx_cls, type):
        current = getattr(okx_cls, "connect", None)
        if callable(current) and not getattr(current, "_nija_okx_connect_canonical_20260713b", False):
            base = _unwrap_connect(current)
            def okx_connect(self: Any, *args: Any, **kwargs: Any) -> Any:
                normalizer = getattr(auth, "normalize_okx_environment", None)
                if callable(normalizer) and not normalizer():
                    logger.error("OKX_CREDENTIALS_INCOMPLETE_ISOLATED marker=%s", MARKER)
                    return False
                primary = str(os.environ.get("OKX_BASE_URL", "https://www.okx.com") or "").rstrip("/")
                _apply_okx_url(self, primary)
                result = base(self, *args, **kwargs)
                if result or str(os.environ.get("OKX_DISABLE_ENDPOINT_FALLBACK", "")).lower() in {"1", "true", "yes", "on"}:
                    return result
                alternate_fn = getattr(auth, "_alternate_okx_url", None)
                alternate = alternate_fn(primary) if callable(alternate_fn) else ""
                if not alternate:
                    return result
                _apply_okx_url(self, alternate)
                for attr, value in (("connected", False), ("client", None), ("_auth_failed", False), ("_is_available", True)):
                    try:
                        setattr(self, attr, value)
                    except Exception:
                        continue
                second = base(self, *args, **kwargs)
                if second:
                    logger.warning("OKX_AUTH_ENDPOINT_RECOVERED marker=%s base_url=%s", MARKER, alternate)
                    return second
                _apply_okx_url(self, primary)
                return second
            okx_connect._nija_okx_connect_canonical_20260713b = True  # type: ignore[attr-defined]
            okx_connect._nija_auth_recovery_20260711n = True  # type: ignore[attr-defined]
            okx_connect._nija_auth_v2 = True  # type: ignore[attr-defined]
            okx_connect.__wrapped__ = base  # type: ignore[attr-defined]
            setattr(okx_cls, "connect", okx_connect)
            logger.critical("OKX_CONNECT_WRAPPER_CANONICALIZED marker=%s base=%s", MARKER, getattr(base, "__qualname__", "unknown"))
            changed = True
    return changed


def _patch_loaded() -> bool:
    changed = False
    for name in ("bot.nija_core_loop", "nija_core_loop"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            changed = _patch_core(module) or changed
    for name in ("bot.broker_manager", "broker_manager"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            changed = _patch_brokers(module) or changed
    return changed


def _watchdog() -> None:
    while True:
        try:
            _patch_loaded()
        except Exception as exc:
            logger.error("SCAN_OWNER_AUTH_CONVERGENCE_RETRY marker=%s error=%s", MARKER, exc)
        time.sleep(0.5)


def install() -> bool:
    global _WATCHDOG_STARTED
    with _LOCK:
        os.environ.setdefault("NIJA_ACCOUNT_SCAN_LOCK_TIMEOUT_S", "1.0")
        os.environ.setdefault("NIJA_DUPLICATE_SCAN_RESULT_WAIT_S", "45")
        _patch_loaded()
        if not _WATCHDOG_STARTED:
            _WATCHDOG_STARTED = True
            threading.Thread(target=_watchdog, name="ScanOwnerAuthConvergenceWatchdog", daemon=True).start()
        os.environ["NIJA_SCAN_OWNER_OKX_AUTH_CONVERGENCE_INSTALLED"] = "1"
        logger.critical("SCAN_OWNER_OKX_AUTH_CONVERGENCE_INSTALLED marker=%s", MARKER)
        return True


__all__ = ["install", "_patch_core", "_patch_brokers", "_identity", "_coerce_result"]
