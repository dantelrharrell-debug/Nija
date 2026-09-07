"""Read-only Coinbase capital rehydration after authenticated startup.

Production evidence on 2026-09-07 showed Coinbase authenticating successfully while
its first capital surface remained 0.0 for roughly two minutes before the genuine
$136.09 balance hydrated.  This patch does not create execution authority and does
not submit orders.  It only retries the existing authenticated balance reader for
a bounded window after a successful connection that has not hydrated capital yet.
The existing Coinbase capital-consistency guard remains authoritative for publishing
funds and for authentication fail-closed behavior.
"""
from __future__ import annotations

import builtins
import logging
import os
import sys
import threading
import time
from functools import wraps
from types import ModuleType
from typing import Any, Iterator, Mapping

logger = logging.getLogger("nija.coinbase_capital_readonly_rehydrate_v388")
MARKER = "20260907-coinbase-capital-readonly-rehydrate-v388"
_PATCH_ATTR = "_nija_coinbase_capital_readonly_rehydrate_v388"
_STATE_KEY = "_NIJA_COINBASE_CAPITAL_READONLY_REHYDRATE_V388"

if not hasattr(builtins, _STATE_KEY):
    setattr(
        builtins,
        _STATE_KEY,
        {
            "lock": threading.RLock(),
            "monitor_started": False,
            "install_attested": False,
            "rehydrating_ids": set(),
        },
    )
_STATE: dict[str, Any] = getattr(builtins, _STATE_KEY)
_LOCK: threading.RLock = _STATE["lock"]


def _targets(broker: Any) -> Iterator[Any]:
    current = broker
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        nested = getattr(current, "_broker", None)
        if nested is None or nested is current:
            return
        current = nested


def _connected(broker: Any) -> bool:
    return any(bool(getattr(target, "connected", False)) for target in _targets(broker))


def _auth_failed(broker: Any) -> bool:
    for target in _targets(broker):
        for attr in (
            "_auth_failed",
            "auth_failed",
            "_permanent_auth_failure",
            "permanent_auth_failure",
        ):
            try:
                if bool(getattr(target, attr, False)):
                    return True
            except Exception:
                continue
    return False


def _consistency_module() -> Any:
    for name in (
        "nija_coinbase_capital_consistency_patch",
        "bot.coinbase_capital_consistency_patch",
        "coinbase_capital_consistency_patch",
    ):
        module = sys.modules.get(name)
        if module is not None and hasattr(module, "_known_balance"):
            return module
    return None


def _amount(value: Any) -> float:
    module = _consistency_module()
    parser = getattr(module, "_payload_total", None) if module is not None else None
    if callable(parser):
        try:
            return max(0.0, float(parser(value) or 0.0))
        except Exception:
            pass
    try:
        if isinstance(value, Mapping):
            for key in ("total_funds", "trading_balance", "total_available", "available_balance"):
                child = value.get(key)
                if isinstance(child, Mapping):
                    child = child.get("value") or child.get("amount") or child.get("balance")
                parsed = float(child or 0.0)
                if parsed > 0:
                    return parsed
            return 0.0
        return max(0.0, float(value or 0.0))
    except Exception:
        return 0.0


def _known_balance(broker: Any) -> float:
    module = _consistency_module()
    reader = getattr(module, "_known_balance", None) if module is not None else None
    if callable(reader):
        try:
            return max(0.0, float(reader(broker) or 0.0))
        except Exception:
            pass
    for target in _targets(broker):
        for attr in ("_last_known_balance", "last_known_balance"):
            value = _amount(getattr(target, attr, 0.0))
            if value > 0:
                return value
    return 0.0


def _publish_authenticated_balance(broker: Any, amount: float) -> None:
    """Delegate publication to the existing fail-closed consistency guard."""
    if amount <= 0 or _auth_failed(broker):
        return
    module = _consistency_module()
    publisher = getattr(module, "_publish", None) if module is not None else None
    if callable(publisher):
        publisher(broker, amount)


def _balance_reader(broker: Any) -> Any:
    for target in _targets(broker):
        reader = getattr(target, "get_account_balance", None)
        if callable(reader):
            return reader
    return None


def _rehydrate_once(broker: Any) -> float:
    """Perform one authenticated balance read and publish only genuine nonzero funds."""
    if _auth_failed(broker) or not _connected(broker):
        return 0.0
    amount = _known_balance(broker)
    if amount > 0:
        _publish_authenticated_balance(broker, amount)
        return amount
    reader = _balance_reader(broker)
    if reader is None:
        return 0.0
    result = reader()
    amount = _amount(result)
    if amount <= 0:
        amount = _known_balance(broker)
    if amount > 0:
        _publish_authenticated_balance(broker, amount)
    return amount


def _worker(broker: Any) -> None:
    broker_id = id(broker)
    timeout_s = max(15.0, float(os.environ.get("NIJA_COINBASE_REHYDRATE_TIMEOUT_SECONDS", "120") or 120))
    interval_s = max(2.0, float(os.environ.get("NIJA_COINBASE_REHYDRATE_INTERVAL_SECONDS", "5") or 5))
    deadline = time.monotonic() + timeout_s
    try:
        while time.monotonic() < deadline:
            if _auth_failed(broker) or not _connected(broker):
                return
            try:
                amount = _rehydrate_once(broker)
            except Exception as exc:
                logger.warning(
                    "COINBASE_CAPITAL_REHYDRATE_V388_RETRY marker=%s error=%s "
                    "read_only=true orders_submitted=false",
                    MARKER,
                    type(exc).__name__,
                )
                amount = 0.0
            if amount > 0:
                logger.critical(
                    "COINBASE_CAPITAL_REHYDRATE_V388_READY marker=%s amount=$%.2f "
                    "authenticated_read=true read_only=true orders_submitted=false "
                    "execution_proof_fabricated=false safety_gates_bypassed=false",
                    MARKER,
                    amount,
                )
                return
            time.sleep(interval_s)
        logger.warning(
            "COINBASE_CAPITAL_REHYDRATE_V388_PENDING marker=%s timeout_s=%.1f "
            "funds_fabricated=false orders_submitted=false trading_fail_closed=true",
            MARKER,
            timeout_s,
        )
    finally:
        with _LOCK:
            _STATE["rehydrating_ids"].discard(broker_id)


def _start_worker(broker: Any) -> bool:
    if _auth_failed(broker) or not _connected(broker) or _known_balance(broker) > 0:
        return False
    broker_id = id(broker)
    with _LOCK:
        if broker_id in _STATE["rehydrating_ids"]:
            return False
        _STATE["rehydrating_ids"].add(broker_id)
    threading.Thread(
        target=_worker,
        args=(broker,),
        name=f"CoinbaseCapitalRehydrateV388-{broker_id}",
        daemon=True,
    ).start()
    logger.critical(
        "COINBASE_CAPITAL_REHYDRATE_V388_STARTED marker=%s authenticated_only=true "
        "read_only=true orders_submitted=false execution_authority_unchanged=true",
        MARKER,
    )
    return True


def _wrap_connect(current: Any) -> Any:
    @wraps(current)
    def wrapped(self: Any, *args: Any, **kwargs: Any):
        result = current(self, *args, **kwargs)
        if not _auth_failed(self) and (bool(result) or _connected(self)):
            _start_worker(self)
        return result

    setattr(wrapped, _PATCH_ATTR, True)
    wrapped.__wrapped__ = current  # type: ignore[attr-defined]
    return wrapped


def _chain_has_patch(current: Any) -> bool:
    seen: set[int] = set()
    node = current
    for _ in range(64):
        if not callable(node) or id(node) in seen:
            return False
        seen.add(id(node))
        if bool(getattr(node, _PATCH_ATTR, False)):
            return True
        node = getattr(node, "__wrapped__", None)
    return False


def _patch_class(cls: type) -> bool:
    current = getattr(cls, "connect", None)
    if not callable(current) or _chain_has_patch(current):
        return False
    cls.connect = _wrap_connect(current)
    return True


def _patch_loaded() -> bool:
    changed = False
    for module_name in (
        "bot.broker_manager",
        "broker_manager",
        "bot.broker_integration",
        "broker_integration",
    ):
        module = sys.modules.get(module_name)
        if not isinstance(module, ModuleType):
            continue
        for class_name in ("CoinbaseBroker", "CoinbaseBrokerAdapter", "_CoinbaseInvalidProductFilter"):
            cls = getattr(module, class_name, None)
            if isinstance(cls, type):
                changed = _patch_class(cls) or changed
    return changed


def _monitor() -> None:
    deadline = time.monotonic() + max(120.0, float(os.environ.get("NIJA_PATCH_MONITOR_SECONDS", "600") or 600))
    while time.monotonic() < deadline:
        try:
            _patch_loaded()
        except Exception:
            logger.exception("COINBASE_CAPITAL_REHYDRATE_V388_MONITOR_ERROR marker=%s", MARKER)
        time.sleep(0.25)


def install() -> bool:
    with _LOCK:
        _patch_loaded()
        if not bool(_STATE["monitor_started"]):
            _STATE["monitor_started"] = True
            threading.Thread(target=_monitor, name="CoinbaseCapitalRehydrateV388", daemon=True).start()
        if not bool(_STATE["install_attested"]):
            _STATE["install_attested"] = True
            logger.critical(
                "COINBASE_CAPITAL_REHYDRATE_V388_INSTALLED marker=%s read_only=true "
                "orders_submitted=false execution_authority_unchanged=true",
                MARKER,
            )
        return True


install()

__all__ = ["install", "_rehydrate_once", "_start_worker", "_patch_loaded"]
