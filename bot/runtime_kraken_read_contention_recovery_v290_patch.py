"""Recover transient Kraken local read-lock contention for authoritative reads (v290).

The Kraken private-call lock remains authoritative. Production logs on
2026-08-30 showed platform and both user Balance enumerations repeatedly failing
closed after the existing 3-second lock-admission window while unrelated
read-only Kraken work held the process-local lock. A failed caller then retried
from the outer reconciliation loop, creating a thundering herd and preventing
all Kraken accounts from holding current position proof simultaneously.

v290 does not bypass or force-release that lock. It keeps the existing v286
single-flight worker alive and retries *only* the explicit local-contention
failure class with bounded, staggered backoff outside the broker lock. Genuine
exchange, auth, nonce, HTTP, payload and order errors are returned unchanged.
The same policy is applied to the v288 bulk read-only cost-basis worker so a
local lock collision does not permanently discard a valid history recovery.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
import time
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.runtime_kraken_read_contention_recovery_v290")
MARKER = "20260830-kraken-read-contention-recovery-v290"
RELEASE_ID = "20260830-runtime-convergence-v290"
_READY_FLAG = "NIJA_RUNTIME_KRAKEN_READ_CONTENTION_RECOVERY_V290_READY"
_PATCH_ATTR = "_nija_kraken_read_contention_recovery_v290"
_LOCK = threading.RLock()


def _float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        return default if number != number else number
    except Exception:
        return default


def _retry_budget_s() -> float:
    try:
        value = float(os.environ.get("NIJA_KRAKEN_LOCAL_CONTENTION_RETRY_BUDGET_S", "75") or 75.0)
    except (TypeError, ValueError):
        value = 75.0
    return max(10.0, min(150.0, value))


def _retry_sleep_s(attempt: int, identity: str) -> float:
    phase = (sum(ord(ch) for ch in identity) % 7) * 0.11
    return min(5.0, 0.75 + phase + max(0, attempt - 1) * 0.55)


def _local_contention(exc: BaseException) -> bool:
    name = type(exc).__name__.lower()
    text = str(exc or "").lower()
    return bool(
        "krakenreadlockbusy" in name
        or "kraken read lock busy" in text
        or "local_read_contention_during_authoritative_position_fetch" in text
    )


def _retry_read(call: Any, identity: str, operation: str) -> Any:
    started = time.monotonic()
    attempt = 0
    while True:
        attempt += 1
        try:
            result = call()
            if attempt > 1:
                LOGGER.critical(
                    "KRAKEN_READ_CONTENTION_V290_RECOVERED marker=%s account=%s operation=%s attempts=%d elapsed_s=%.1f lock_bypassed=false lock_force_released=false synthetic_success=false",
                    MARKER, identity, operation, attempt, max(0.0, time.monotonic() - started),
                )
            return result
        except BaseException as exc:
            if not _local_contention(exc):
                raise
            elapsed = max(0.0, time.monotonic() - started)
            sleep_s = _retry_sleep_s(attempt, identity)
            if elapsed + sleep_s >= _retry_budget_s():
                LOGGER.warning(
                    "KRAKEN_READ_CONTENTION_V290_EXHAUSTED marker=%s account=%s operation=%s attempts=%d elapsed_s=%.1f budget_s=%.1f error=%s:%s fail_closed=true lock_bypassed=false lock_force_released=false",
                    MARKER, identity, operation, attempt, elapsed, _retry_budget_s(), type(exc).__name__, exc,
                )
                raise
            LOGGER.info(
                "KRAKEN_READ_CONTENTION_V290_RETRY marker=%s account=%s operation=%s attempt=%d delay_s=%.2f elapsed_s=%.1f budget_s=%.1f sleep_outside_lock=true lock_bypassed=false mutating_calls_unchanged=true",
                MARKER, identity, operation, attempt, sleep_s, elapsed, _retry_budget_s(),
            )
            time.sleep(sleep_s)


def _patch_v286_authoritative_fetch() -> bool:
    try:
        v286 = importlib.import_module("bot.runtime_kraken_position_refresh_liveness_v286_patch")
    except Exception:
        return False
    current = getattr(v286, "_fetch_authoritative_rows_sync", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True
    original = current

    @wraps(original)
    def fetch_v290(broker: Any):
        identity = str(getattr(broker, "account_identifier", "unknown") or "unknown")
        return _retry_read(lambda: original(broker), identity, "Balance")

    setattr(fetch_v290, _PATCH_ATTR, True)
    setattr(fetch_v290, "__wrapped__", original)
    v286._fetch_authoritative_rows_sync = fetch_v290
    return True


def _patch_v288_bulk_worker() -> bool:
    try:
        v288 = importlib.import_module("bot.runtime_kraken_cost_basis_bulk_v288_patch")
    except Exception:
        return False
    current = getattr(v288, "_finish_bulk_flight", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    def finish_bulk_v290(flight: dict[str, Any], method: Any, symbols: tuple[str, ...]) -> None:
        try:
            owner = getattr(method, "__self__", None)
            identity = str(getattr(owner, "account_identifier", "unknown") or "unknown")
            result = _retry_read(lambda: method(list(symbols)), identity, "TradesHistoryBulk")
            from collections.abc import Mapping
            if not isinstance(result, Mapping):
                raise RuntimeError(f"invalid_bulk_entry_price_payload:{type(result).__name__}")
            flight["result"] = {
                str(key or "").strip().upper(): _float(value)
                for key, value in result.items()
                if str(key or "").strip() and _float(value) > 0.0
            }
        except BaseException as exc:
            flight["error"] = exc
        finally:
            flight["finished_at"] = time.monotonic()
            flight["event"].set()

    setattr(finish_bulk_v290, _PATCH_ATTR, True)
    setattr(finish_bulk_v290, "__wrapped__", current)
    v288._finish_bulk_flight = finish_bulk_v290
    return True


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_kraken_read_contention_recovery_v290"] = _READY_FLAG
        return True
    except Exception:
        return False


def reconcile_once() -> dict[str, Any]:
    fetch = _patch_v286_authoritative_fetch()
    bulk = _patch_v288_bulk_worker()
    downstream: dict[str, Any] = {}
    try:
        v287 = importlib.import_module("bot.runtime_kraken_position_flight_recovery_v287_patch")
        fn = getattr(v287, "reconcile_once", None)
        result = fn() if callable(fn) else {}
        downstream = dict(result) if isinstance(result, dict) else {}
    except Exception as exc:
        downstream = {"ready": False, "error": f"v287_reconcile_error:{type(exc).__name__}:{exc}"}
    return {"ready": bool(fetch and bulk and downstream.get("ready")), "fetch_retry": fetch, "bulk_retry": bulk, "downstream": downstream}


def install() -> bool:
    with _LOCK:
        fetch = _patch_v286_authoritative_fetch()
        bulk = _patch_v288_bulk_worker()
        manifest = _register_manifest()
        ready = bool(fetch and bulk and manifest)
        os.environ[_READY_FLAG] = "1" if ready else "0"
        LOGGER.critical(
            "RUNTIME_KRAKEN_READ_CONTENTION_RECOVERY_V290_%s marker=%s ready=%s retry_budget_s=%.1f position_balance_retry=true bulk_history_retry=true local_contention_only=true staggered_backoff_outside_lock=true lock_bypass=false lock_force_release=false rate_limits_unchanged=true mutating_calls_unchanged=true exchange_auth_nonce_http_errors_unchanged=true synthetic_position=false synthetic_cost_basis=false forced_trade=false forced_activation=false writer_nonce_capital_risk_killswitch_order_fill_gates_unchanged=true safety_gates_bypassed=false",
            "READY" if ready else "NOT_READY", MARKER, str(ready).lower(), _retry_budget_s(),
        )
        return ready


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER", "RELEASE_ID", "install", "install_import_hook", "reconcile_once",
    "_local_contention", "_retry_read", "_patch_v286_authoritative_fetch", "_patch_v288_bulk_worker",
]
