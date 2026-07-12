"""Final process-wide runtime repair for NIJA.

Prevents duplicate NIJA worker threads across multiple manager instances, normalizes
Kraken position fields at the broker boundary, and repairs/validates Coinbase PEM
material before SDK construction. Exchange authentication remains authoritative.
"""
from __future__ import annotations

import base64
import logging
import os
import re
import sys
import threading
import time
import weakref
from typing import Any

logger = logging.getLogger("nija.final_worker_position_coinbase_repair")
_MARKER = "20260712g"
_LOCK = threading.RLock()
_INSTALLED = False
_ORIGINAL_THREAD_START = threading.Thread.start
_ACTIVE_THREADS: dict[str, weakref.ReferenceType[threading.Thread]] = {}
_GUARDED_PREFIXES = (
    "Trader-",
    "AccountExitRecoverySupervisor",
    "csm-watchdog-",
)


def _guarded_name(name: str) -> bool:
    return any(name == prefix or name.startswith(prefix) for prefix in _GUARDED_PREFIXES)


def _thread_start(self: threading.Thread, *args: Any, **kwargs: Any):
    name = str(getattr(self, "name", "") or "")
    if not _guarded_name(name):
        return _ORIGINAL_THREAD_START(self, *args, **kwargs)
    with _LOCK:
        ref = _ACTIVE_THREADS.get(name)
        active = ref() if ref is not None else None
        if active is not None and active is not self and active.is_alive():
            logger.critical(
                "PROCESS_WIDE_DUPLICATE_THREAD_SUPPRESSED marker=%s name=%s existing_ident=%s",
                _MARKER,
                name,
                getattr(active, "ident", None),
            )
            return None
        _ACTIVE_THREADS[name] = weakref.ref(self)
    try:
        return _ORIGINAL_THREAD_START(self, *args, **kwargs)
    except Exception:
        with _LOCK:
            ref = _ACTIVE_THREADS.get(name)
            if ref is not None and ref() is self:
                _ACTIVE_THREADS.pop(name, None)
        raise


def _float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _first_value(position: Any, names: tuple[str, ...]) -> float:
    if isinstance(position, dict):
        for name in names:
            if name in position and position[name] not in (None, ""):
                value = _float(position[name])
                if value != 0.0:
                    return value
        return 0.0
    for name in names:
        if hasattr(position, name):
            value = _float(getattr(position, name, 0.0))
            if value != 0.0:
                return value
    return 0.0


def _set_value(position: Any, name: str, value: float) -> None:
    if isinstance(position, dict):
        position.setdefault(name, value)
        return
    try:
        current = getattr(position, name, None)
        if current in (None, "", 0, 0.0):
            setattr(position, name, value)
    except Exception:
        return


def normalize_position(position: Any) -> Any:
    quantity = _first_value(position, (
        "quantity", "qty", "size", "position_size", "volume", "vol", "amount", "balance", "units",
    ))
    entry_price = _first_value(position, (
        "entry_price", "average_entry_price", "avg_entry_price", "avg_price", "average_price", "cost_basis_price", "price",
    ))
    if entry_price <= 0.0:
        cost = _first_value(position, ("cost", "cost_basis", "total_cost", "notional"))
        if cost > 0.0 and abs(quantity) > 0.0:
            entry_price = cost / abs(quantity)
    _set_value(position, "quantity", quantity)
    _set_value(position, "size", quantity)
    _set_value(position, "entry_price", entry_price)
    _set_value(position, "average_entry_price", entry_price)
    return position


def _wrap_positions_method(cls: type, method_name: str) -> None:
    original = getattr(cls, method_name, None)
    if not callable(original) or getattr(original, "_nija_position_normalized", False):
        return

    def wrapped(self: Any, *args: Any, **kwargs: Any):
        result = original(self, *args, **kwargs)
        if isinstance(result, list):
            return [normalize_position(item) for item in result]
        if isinstance(result, tuple):
            return tuple(normalize_position(item) for item in result)
        if isinstance(result, dict):
            for key, value in list(result.items()):
                if isinstance(value, (dict, object)) and not isinstance(value, (str, bytes, int, float, bool, type(None))):
                    result[key] = normalize_position(value)
            return result
        return result

    wrapped._nija_position_normalized = True
    setattr(cls, method_name, wrapped)
    logger.warning("KRAKEN_POSITION_NORMALIZER_PATCHED marker=%s class=%s method=%s", _MARKER, cls.__name__, method_name)


def _repair_pem(raw: str) -> str:
    value = str(raw or "").strip().strip('"').strip("'")
    value = value.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\r\n", "\n").replace("\r", "\n")
    if "BEGIN" not in value:
        try:
            decoded = base64.b64decode(value, validate=True).decode("utf-8").strip()
            if "BEGIN" in decoded and "PRIVATE KEY" in decoded:
                value = decoded
        except Exception:
            pass
    match = re.search(r"-----BEGIN ([A-Z0-9 ]*PRIVATE KEY)-----(.*?)-----END \1-----", value, re.S)
    if match:
        label = match.group(1)
        body = re.sub(r"\s+", "", match.group(2))
        if body:
            lines = [body[i:i + 64] for i in range(0, len(body), 64)]
            value = f"-----BEGIN {label}-----\n" + "\n".join(lines) + f"\n-----END {label}-----\n"
    return value


def _validate_coinbase_pem() -> bool:
    names = ("COINBASE_API_SECRET", "COINBASE_API_PRIVATE_KEY", "COINBASE_PRIVATE_KEY")
    source = next((name for name in names if str(os.environ.get(name, "") or "").strip()), "")
    if not source:
        return False
    repaired = _repair_pem(os.environ[source])
    for name in names:
        if name == source or name in os.environ:
            os.environ[name] = repaired
    try:
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
        load_pem_private_key(repaired.encode("utf-8"), password=None)
        os.environ["NIJA_COINBASE_PEM_VALID"] = "1"
        logger.warning("COINBASE_PEM_VALIDATED marker=%s source=%s lines=%d", _MARKER, source, len(repaired.splitlines()))
        return True
    except Exception as exc:
        os.environ["NIJA_COINBASE_PEM_VALID"] = "0"
        os.environ["NIJA_COINBASE_AUTH_ISOLATED"] = "1"
        logger.error("COINBASE_PEM_INVALID_ISOLATED marker=%s source=%s lines=%d error=%s", _MARKER, source, len(repaired.splitlines()), type(exc).__name__)
        return False


def _patch_loaded_brokers() -> None:
    for module_name in ("bot.broker_manager", "bot.broker_integration", "bot.multi_account_broker_manager"):
        module = sys.modules.get(module_name)
        if module is None:
            continue
        for class_name in ("KrakenBroker", "KrakenBrokerAdapter"):
            cls = getattr(module, class_name, None)
            if isinstance(cls, type):
                for method_name in ("get_positions", "fetch_positions", "get_open_positions"):
                    _wrap_positions_method(cls, method_name)


def _watchdog() -> None:
    deadline = time.monotonic() + 180.0
    while time.monotonic() < deadline:
        _patch_loaded_brokers()
        time.sleep(0.25)


def install() -> bool:
    global _INSTALLED
    with _LOCK:
        if _INSTALLED:
            return True
        threading.Thread.start = _thread_start
        _validate_coinbase_pem()
        _patch_loaded_brokers()
        threading.Thread(target=_watchdog, name="final-worker-position-watchdog", daemon=True).start()
        os.environ["NIJA_FINAL_WORKER_POSITION_COINBASE_REPAIR_INSTALLED"] = "1"
        _INSTALLED = True
        logger.warning(
            "FINAL_WORKER_POSITION_COINBASE_REPAIR_INSTALLED marker=%s process_thread_guard=true kraken_position_normalizer=true coinbase_preflight=true",
            _MARKER,
        )
        return True


__all__ = ["install", "normalize_position"]
