"""Supervised Coinbase and OKX activation for NIJA.

Reconnects secondary platform venues only after canonical writer authority exists.
It never creates credentials, fabricates balances, borrows capital between venues,
places probe orders, or bypasses risk/order-admission controls.
"""

from __future__ import annotations

import hashlib
import importlib
import logging
import os
import sys
import threading
import time
from dataclasses import dataclass
from typing import Any, Mapping, Optional

logger = logging.getLogger("nija.secondary_venue_activation")
_MARKER = "20260710ag"
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}
_FALSE = {"0", "false", "no", "off", "disabled", "n"}
_LOCK = threading.RLock()
_INSTALLED = False
_THREADS: dict[str, threading.Thread] = {}
_LAST_STATE: dict[str, str] = {}
_SECRET_FP: dict[str, str] = {}


@dataclass(frozen=True)
class Venue:
    name: str
    enum_name: str
    class_name: str
    credentials: tuple[tuple[str, ...], ...]
    enable_flags: tuple[str, ...]
    disable_flag: str
    min_env: str
    min_default: float


VENUES = (
    Venue(
        "coinbase", "COINBASE", "CoinbaseBroker",
        (
            ("COINBASE_API_KEY", "COINBASE_PLATFORM_API_KEY", "COINBASE_ADVANCED_API_KEY"),
            ("COINBASE_API_SECRET", "COINBASE_PLATFORM_API_SECRET", "COINBASE_ADVANCED_API_SECRET"),
        ),
        ("ENABLE_COINBASE", "ENABLE_COINBASE_TRADING", "COINBASE_LIVE_TRADING_ENABLED"),
        "NIJA_DISABLE_COINBASE", "COINBASE_VENUE_THRESHOLD_USD", 12.0,
    ),
    Venue(
        "okx", "OKX", "OKXBroker",
        (
            ("OKX_API_KEY", "OKX_PLATFORM_API_KEY"),
            ("OKX_API_SECRET", "OKX_PLATFORM_API_SECRET"),
            ("OKX_PASSPHRASE", "OKX_API_PASSPHRASE", "OKX_PLATFORM_PASSPHRASE"),
        ),
        ("ENABLE_OKX_TRADING", "OKX_LIVE_TRADING_ENABLED", "NIJA_OKX_EXECUTION_ENABLED", "NIJA_OKX_LIVE_TRADING_ENABLED"),
        "NIJA_DISABLE_OKX", "OKX_MIN_ORDER_USD", 10.0,
    ),
)


def _flag(name: str, default: bool = True) -> bool:
    raw = str(os.environ.get(name, "") or "").strip().lower()
    if not raw:
        return default
    if raw in _FALSE:
        return False
    return raw in _TRUE


def _live() -> bool:
    return _flag("LIVE_CAPITAL_VERIFIED", False) and not _flag("DRY_RUN_MODE", False) and not _flag("PAPER_MODE", False)


def _writer_ready() -> bool:
    if not _live():
        return True
    return (
        _flag("NIJA_WRITER_LEASE_ACQUIRED", False)
        and bool(os.environ.get("NIJA_WRITER_FENCING_TOKEN", "").strip())
        and bool(os.environ.get("NIJA_WRITER_LEASE_GENERATION", "").strip())
    )


def _state(venue: Venue, state: str, **details: Any) -> None:
    previous = _LAST_STATE.get(venue.name)
    _LAST_STATE[venue.name] = state
    os.environ[f"NIJA_{venue.name.upper()}_ACTIVATION_STATE"] = state
    if previous == state and not details.pop("force", False):
        return
    tail = " ".join(f"{key}={value}" for key, value in details.items())
    logger.warning(
        "SECONDARY_VENUE_ACTIVATION_STATE marker=%s venue=%s state=%s%s",
        _MARKER, venue.name, state, f" {tail}" if tail else "",
    )


def _enabled(venue: Venue) -> tuple[bool, str]:
    if _flag(venue.disable_flag, False):
        return False, f"{venue.disable_flag}=true"
    disabled = [name for name in venue.enable_flags if not _flag(name, True)]
    return (not disabled, "disabled_flags=" + ",".join(disabled) if disabled else "")


def _credentials(venue: Venue) -> tuple[bool, list[str], str]:
    values: list[str] = []
    missing: list[str] = []
    for names in venue.credentials:
        canonical = names[0]
        value = os.environ.get(canonical, "").strip()
        if not value:
            for alias in names[1:]:
                alias_value = os.environ.get(alias, "").strip()
                if alias_value:
                    os.environ[canonical] = alias_value
                    value = alias_value
                    logger.warning(
                        "SECONDARY_VENUE_CREDENTIAL_ALIAS_PROMOTED marker=%s venue=%s canonical=%s alias=%s",
                        _MARKER, venue.name, canonical, alias,
                    )
                    break
        if not value:
            missing.append(canonical)
        values.append(value)
    fingerprint = hashlib.sha256("\0".join(values).encode()).hexdigest()[:16]
    return not missing, missing, fingerprint


def _runtime() -> tuple[Optional[Any], Optional[Any]]:
    try:
        broker_module = sys.modules.get("bot.broker_manager") or importlib.import_module("bot.broker_manager")
        mabm_module = sys.modules.get("bot.multi_account_broker_manager") or importlib.import_module("bot.multi_account_broker_manager")
        manager = getattr(mabm_module, "multi_account_broker_manager", None)
        if manager is None:
            getter = getattr(mabm_module, "get_broker_manager", None)
            manager = getter() if callable(getter) else None
        return broker_module, manager
    except Exception:
        return None, None


def _enum(broker_module: Any, venue: Venue) -> Any:
    return getattr(getattr(broker_module, "BrokerType", None), venue.enum_name, None)


def _lookup(manager: Any, broker_module: Any, venue: Venue) -> Optional[Any]:
    enum_value = _enum(broker_module, venue)
    for attr in ("_platform_brokers", "platform_brokers"):
        try:
            mapping = getattr(manager, attr, None)
            if isinstance(mapping, Mapping):
                broker = mapping.get(enum_value) or mapping.get(venue.name)
                if broker is not None:
                    return broker
        except Exception:
            pass
    getter = getattr(broker_module, "get_platform_broker", None)
    if callable(getter):
        try:
            return getter(venue.name)
        except Exception:
            pass
    return None


def _construct_and_register(manager: Any, broker_module: Any, venue: Venue) -> Optional[Any]:
    if bool(getattr(manager, "_platform_brokers_locked", False)):
        return None
    broker_cls = getattr(broker_module, venue.class_name, None)
    if not isinstance(broker_cls, type):
        return None
    account_type = getattr(getattr(broker_module, "AccountType", None), "PLATFORM", None)
    try:
        broker = broker_cls(account_type=account_type) if account_type is not None else broker_cls()
    except TypeError:
        broker = broker_cls()
    enum_value = _enum(broker_module, venue)
    register = getattr(manager, "register_platform_broker_instance", None)
    if callable(register) and enum_value is not None:
        try:
            register(enum_value, broker, mark_connected_state=False)
        except TypeError:
            register(enum_value, broker)
    else:
        return None
    return broker


def _connected(broker: Any) -> bool:
    for attr in ("connected", "is_connected"):
        if hasattr(broker, attr):
            try:
                value = getattr(broker, attr)
                return bool(value() if callable(value) else value)
            except Exception:
                return False
    return False


def _connect(venue: Venue, broker: Any, fingerprint: str) -> bool:
    if _connected(broker):
        return True
    previous = _SECRET_FP.get(venue.name)
    if previous and previous != fingerprint:
        for attr in ("_auth_failed", "auth_failed", "_is_available"):
            if hasattr(broker, attr):
                try:
                    setattr(broker, attr, False if "auth_failed" in attr else True)
                except Exception:
                    pass
    _SECRET_FP[venue.name] = fingerprint
    connect = getattr(broker, "connect", None)
    if not callable(connect):
        return False
    try:
        result = bool(connect())
    except Exception as exc:
        logger.warning(
            "SECONDARY_VENUE_CONNECT_FAILED marker=%s venue=%s type=%s error=%s",
            _MARKER, venue.name, type(exc).__name__, str(exc)[:240],
        )
        return False
    return result and _connected(broker)


def _mark_connected(manager: Any, broker_module: Any, venue: Venue) -> None:
    enum_value = _enum(broker_module, venue)
    marker = getattr(manager, "_mark_platform_connected", None)
    if callable(marker) and enum_value is not None:
        try:
            marker(enum_value)
        except Exception:
            pass
    refresh_registry = getattr(manager, "refresh_registry", None)
    if callable(refresh_registry):
        try:
            refresh_registry()
        except Exception:
            pass


def _spendable(venue: Venue, broker: Any) -> tuple[float, str]:
    try:
        module = importlib.import_module("bot.spendable_quote_routing_patch")
        resolver = getattr(module, "_spendable_usd", None)
        if callable(resolver):
            value, _available, source = resolver(broker, venue.name)
            return max(0.0, float(value or 0.0)), str(source)
    except Exception:
        pass
    for method_name in ("get_account_balance_detailed", "get_account_balance"):
        method = getattr(broker, method_name, None)
        if not callable(method):
            continue
        try:
            try:
                payload = method(verbose=False)
            except TypeError:
                payload = method()
            if isinstance(payload, (int, float)):
                return max(0.0, float(payload)), method_name
            if isinstance(payload, Mapping):
                for key in ("trading_balance", "available_balance", "available_usd", "usd", "usdt", "usdc"):
                    if key in payload:
                        return max(0.0, float(payload.get(key) or 0.0)), method_name
        except Exception:
            pass
    return 0.0, "unavailable"


def _markets(broker: Any) -> Optional[int]:
    for method_name in ("get_available_markets", "get_all_products", "get_tradable_symbols", "get_tradable_universe"):
        method = getattr(broker, method_name, None)
        if callable(method):
            try:
                payload = method()
                if isinstance(payload, Mapping):
                    return len(payload)
                if isinstance(payload, (list, tuple, set)):
                    return len(payload)
                return 0
            except Exception:
                return 0
    return None


def _refresh(manager: Any, venue: Venue) -> None:
    refresh = getattr(manager, "refresh_capital_authority", None)
    if callable(refresh):
        try:
            refresh(trigger=f"secondary_venue_activation:{venue.name}")
        except Exception:
            pass


def activate_once(venue: Venue, broker_module: Any = None, manager: Any = None) -> str:
    enabled, reason = _enabled(venue)
    if not enabled:
        _state(venue, "disabled", reason=reason)
        return "disabled"
    ok, missing, fingerprint = _credentials(venue)
    if not ok:
        _state(venue, "missing_credentials", missing=",".join(missing))
        return "missing_credentials"
    if broker_module is None or manager is None:
        broker_module, manager = _runtime()
    if broker_module is None or manager is None:
        _state(venue, "runtime_modules_pending")
        return "runtime_modules_pending"
    broker = _lookup(manager, broker_module, venue)
    if broker is None:
        broker = _construct_and_register(manager, broker_module, venue)
    if broker is None:
        _state(venue, "registration_pending")
        return "registration_pending"
    if not _connect(venue, broker, fingerprint):
        auth_failed = bool(getattr(broker, "_auth_failed", False) or getattr(broker, "auth_failed", False))
        state = "authentication_failed" if auth_failed else "connect_failed"
        _state(venue, state)
        return state
    _mark_connected(manager, broker_module, venue)
    os.environ[f"NIJA_{venue.name.upper()}_CONNECTED"] = "1"
    spendable, source = _spendable(venue, broker)
    minimum = max(venue.min_default, float(os.environ.get(venue.min_env, venue.min_default) or venue.min_default))
    os.environ[f"NIJA_{venue.name.upper()}_SPENDABLE_QUOTE"] = f"{spendable:.8f}"
    if spendable < minimum:
        os.environ[f"NIJA_{venue.name.upper()}_TRADING_READY"] = "0"
        _state(venue, "connected_unfunded", spendable=f"{spendable:.2f}", required=f"{minimum:.2f}", source=source)
        _refresh(manager, venue)
        return "connected_unfunded"
    markets = _markets(broker)
    if markets is not None and markets <= 0:
        os.environ[f"NIJA_{venue.name.upper()}_TRADING_READY"] = "0"
        _state(venue, "market_discovery_pending", spendable=f"{spendable:.2f}")
        return "market_discovery_pending"
    os.environ[f"NIJA_{venue.name.upper()}_TRADING_READY"] = "1"
    os.environ[f"NIJA_{venue.name.upper()}_ACTIVATED"] = "1"
    _state(venue, "ready", spendable=f"{spendable:.2f}", markets=markets if markets is not None else "adapter_managed")
    _refresh(manager, venue)
    return "ready"


def _delay(state: str, failures: int) -> float:
    if state == "ready":
        return 60.0
    if state in {"missing_credentials", "disabled", "authentication_failed"}:
        return 300.0
    if state == "connected_unfunded":
        return 120.0
    return min(300.0, 10.0 * (2 ** min(failures, 5)))


def _loop(venue: Venue) -> None:
    failures = 0
    while True:
        if not _writer_ready():
            _state(venue, "writer_authority_pending")
            time.sleep(2.0)
            continue
        try:
            state = activate_once(venue)
            failures = 0 if state == "ready" else failures + 1
        except Exception as exc:
            failures += 1
            state = "loop_error"
            logger.exception(
                "SECONDARY_VENUE_ACTIVATION_LOOP_ERROR marker=%s venue=%s type=%s error=%s",
                _MARKER, venue.name, type(exc).__name__, str(exc)[:240],
            )
        time.sleep(_delay(state, failures))


def install() -> None:
    global _INSTALLED
    with _LOCK:
        if _INSTALLED:
            return
        _INSTALLED = True
        for venue in VENUES:
            thread = threading.Thread(target=_loop, args=(venue,), name=f"secondary-venue-activation-{venue.name}", daemon=True)
            _THREADS[venue.name] = thread
            thread.start()
        logger.warning("SECONDARY_VENUE_ACTIVATION_INSTALLED marker=%s venues=coinbase,okx", _MARKER)
        print(f"[NIJA-PRINT] SECONDARY_VENUE_ACTIVATION_INSTALLED marker={_MARKER} venues=coinbase,okx", flush=True)


__all__ = ["Venue", "VENUES", "install", "activate_once", "_credentials", "_spendable"]
