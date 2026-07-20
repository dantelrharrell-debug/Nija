"""Thread-safe independent-account capital isolation for NIJA trading cycles.

This patch replaces process-wide balance overrides with an account-local CapitalAuthority
proxy.  User cycles always retain their broker balance, positions and mode even while
platform and other user threads run concurrently.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
import time
from functools import wraps
from types import ModuleType
from typing import Any

logger = logging.getLogger("nija.account_capital_isolation_v4")
_MARKER = "20260720-account-capital-isolation-v4"
_PATCH_ATTR = "_nija_account_capital_isolation_v4"
_LOCK = threading.RLock()
_STARTED = False


def _f(value: Any, default: float = 0.0) -> float:
    try:
        value = float(value or 0.0)
    except (TypeError, ValueError, OverflowError):
        return default
    return value if value == value and value >= 0.0 else default


def _account_name(broker: Any) -> str:
    for name in ("account_id", "_account_id", "user_id", "account_name", "label", "owner_id"):
        try:
            value = getattr(broker, name, None)
        except Exception:
            value = None
        if value:
            return str(value).strip().lower().replace(" ", "_")
    account_type = getattr(broker, "account_type", None)
    value = getattr(account_type, "value", account_type)
    return str(value or "platform").strip().lower().replace(" ", "_")


def _is_user_account(broker: Any) -> bool:
    account = _account_name(broker)
    return account not in {"", "platform", "platform_account", "master", "primary", "none", "unknown"}


def _broker_balance(broker: Any) -> float:
    for name in (
        "_nija_last_account_balance_usd", "_nija_cycle_balance_usd", "last_account_balance",
        "_last_known_balance", "available_balance", "usd_balance", "cash_balance", "balance",
    ):
        try:
            value = _f(getattr(broker, name, 0.0))
        except Exception:
            value = 0.0
        if value > 0:
            return value
    getter = getattr(broker, "get_account_balance", None)
    if callable(getter):
        try:
            raw = getter()
            if isinstance(raw, dict):
                for key in ("total_balance", "balance", "equity", "total_funds", "available_balance", "cash"):
                    value = _f(raw.get(key))
                    if value > 0:
                        return value
            value = _f(raw)
            if value > 0:
                return value
        except Exception as exc:
            logger.warning("ACCOUNT_LOCAL_BALANCE_REFRESH_FAILED marker=%s account=%s error=%s", _MARKER, _account_name(broker), exc)
    return 0.0


class _ScopedCapitalAuthority:
    def __init__(self, delegate: Any, balance: float, broker: Any) -> None:
        object.__setattr__(self, "_delegate", delegate)
        object.__setattr__(self, "_balance", float(balance))
        object.__setattr__(self, "_broker", broker)

    @property
    def total_capital(self) -> float:
        return object.__getattribute__(self, "_balance")

    @property
    def real_capital(self) -> float:
        return object.__getattribute__(self, "_balance")

    @property
    def usable_capital(self) -> float:
        reserve = max(0.0, min(0.50, _f(os.getenv("NIJA_CAPITAL_RESERVE_PCT", "0.02"), 0.02)))
        return object.__getattribute__(self, "_balance") * (1.0 - reserve)

    @property
    def risk_capital(self) -> float:
        return self.usable_capital

    @property
    def hydrated(self) -> bool:
        return self.total_capital > 0

    @property
    def valid_brokers(self) -> int:
        return 1 if self.total_capital > 0 else 0

    @property
    def broker_balances(self) -> dict[str, float]:
        broker = object.__getattribute__(self, "_broker")
        venue = type(broker).__name__.replace("Broker", "").lower() or "broker"
        return {venue: self.total_capital}

    def __getattr__(self, name: str) -> Any:
        delegate = object.__getattribute__(self, "_delegate")
        if delegate is None:
            raise AttributeError(name)
        return getattr(delegate, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name in {"_delegate", "_balance", "_broker"}:
            object.__setattr__(self, name, value)
            return
        delegate = object.__getattribute__(self, "_delegate")
        if delegate is None:
            object.__setattr__(self, name, value)
        else:
            setattr(delegate, name, value)


def _patch_class(cls: type) -> bool:
    current = getattr(cls, "run_cycle", None)
    if not callable(current) or getattr(current, _PATCH_ATTR, False):
        return bool(callable(current) and getattr(current, _PATCH_ATTR, False))

    @wraps(current)
    def run_cycle(self: Any, broker: Any = None, user_mode: bool = False, *args: Any, **kwargs: Any):
        selected = broker or getattr(self, "broker", None)
        if selected is None:
            return current(self, broker=broker, user_mode=user_mode, *args, **kwargs)

        balance = _broker_balance(selected)
        account = _account_name(selected)
        user_account = _is_user_account(selected)
        effective_user_mode = bool(user_mode or user_account)
        if balance <= 0:
            logger.critical("ACCOUNT_CAPITAL_ISOLATION_FAIL_CLOSED marker=%s account=%s reason=no_broker_balance", _MARKER, account)
            return max(5, int(_f(os.getenv("NIJA_ACCOUNT_SCOPE_RETRY_S", "10"), 10.0)))

        core = getattr(self, "nija_core_loop", None)
        targets = [self]
        if core is not None:
            targets.append(core)
        apex = getattr(self, "apex", None)
        if apex is not None:
            targets.append(apex)

        saved: list[tuple[Any, str, bool, Any]] = []
        for target in targets:
            for attr in ("capital_authority", "_capital_authority"):
                existed = hasattr(target, attr)
                old = getattr(target, attr, None)
                if existed or old is not None:
                    saved.append((target, attr, existed, old))
                    try:
                        setattr(target, attr, _ScopedCapitalAuthority(old, balance, selected))
                    except Exception:
                        pass
            for attr, value in (
                ("_nija_account_scoped_balance", balance),
                ("_nija_account_scope_active", True),
                ("_nija_effective_user_mode", effective_user_mode),
                ("balance", balance),
            ):
                existed = hasattr(target, attr)
                old = getattr(target, attr, None)
                saved.append((target, attr, existed, old))
                try:
                    setattr(target, attr, value)
                except Exception:
                    pass

        old_broker_balance = getattr(selected, "_nija_cycle_balance_usd", None)
        old_broker_user = getattr(selected, "_nija_effective_user_mode", None)
        setattr(selected, "_nija_cycle_balance_usd", balance)
        setattr(selected, "_nija_effective_user_mode", effective_user_mode)

        # Never use the process-wide force-balance bridge for concurrent account cycles.
        old_force = os.environ.pop("NIJA_FORCE_TRADE_BALANCE", None)
        logger.critical(
            "ACCOUNT_CAPITAL_ISOLATION_ACTIVE marker=%s account=%s balance=$%.2f user_mode_requested=%s user_mode_effective=%s process_env_override=false",
            _MARKER, account, balance, bool(user_mode), effective_user_mode,
        )
        try:
            return current(self, broker=selected, user_mode=effective_user_mode, *args, **kwargs)
        finally:
            if old_force is not None and not user_account:
                os.environ["NIJA_FORCE_TRADE_BALANCE"] = old_force
            for target, attr, existed, old in reversed(saved):
                try:
                    if existed:
                        setattr(target, attr, old)
                    else:
                        delattr(target, attr)
                except Exception:
                    pass
            if old_broker_balance is None:
                try:
                    delattr(selected, "_nija_cycle_balance_usd")
                except Exception:
                    pass
            else:
                setattr(selected, "_nija_cycle_balance_usd", old_broker_balance)
            if old_broker_user is None:
                try:
                    delattr(selected, "_nija_effective_user_mode")
                except Exception:
                    pass
            else:
                setattr(selected, "_nija_effective_user_mode", old_broker_user)

    setattr(run_cycle, _PATCH_ATTR, True)
    setattr(run_cycle, "__wrapped__", current)
    cls.run_cycle = run_cycle
    logger.critical("ACCOUNT_CAPITAL_ISOLATION_SURFACE_PATCHED marker=%s module=%s class=%s", _MARKER, cls.__module__, cls.__name__)
    return True


def _patch_loaded() -> bool:
    changed = False
    for name in ("bot.trading_strategy", "trading_strategy"):
        module = sys.modules.get(name)
        cls = getattr(module, "TradingStrategy", None) if isinstance(module, ModuleType) else None
        if isinstance(cls, type):
            changed = _patch_class(cls) or changed
    return changed


def _watchdog() -> None:
    deadline = time.monotonic() + 600.0
    while time.monotonic() < deadline:
        try:
            _patch_loaded()
        except Exception as exc:
            logger.debug("ACCOUNT_CAPITAL_ISOLATION_RETRY marker=%s error=%s", _MARKER, exc)
        time.sleep(0.5)


def install() -> bool:
    global _STARTED
    with _LOCK:
        _patch_loaded()
        if not _STARTED:
            _STARTED = True
            threading.Thread(target=_watchdog, name="AccountCapitalIsolationV4", daemon=True).start()
        os.environ["NIJA_ACCOUNT_CAPITAL_ISOLATION_V4_INSTALLED"] = "1"
        logger.critical("ACCOUNT_CAPITAL_ISOLATION_V4_INSTALLED marker=%s", _MARKER)
        return True


install()

__all__ = ["install", "_ScopedCapitalAuthority", "_is_user_account"]
