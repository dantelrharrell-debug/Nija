"""Bridge genuine PLATFORM Kraken balance reads into CapitalAuthority v415.

Production can have a healthy authenticated Kraken Balance path while the
separate capital-refresh worker is stale.  In that state CapitalAuthority may
expire even though a newer canonical PLATFORM Balance request completed.

v415 observes the existing canonical private Balance request without starting
new broker I/O.  It marks a short-lived per-broker generation only after the
response is structurally valid and the existing v312 credential scope is
proven.  The outer get_account_balance result is then pushed through
CapitalAuthority.feed_broker_balance only when that exact invocation contained
a new authenticated PLATFORM Balance observation.

Cached get_account_balance calls that did not issue a new private Balance read
cannot refresh capital.  User-account balances are never fed into platform
capital.  Existing CapitalAuthority registration, monotonic timestamp,
freshness, completeness, writer, nonce, risk, kill-switch, position, protection,
order and fill gates remain authoritative.
"""
from __future__ import annotations

import importlib
import logging
import math
import os
import threading
import time
from collections.abc import Mapping
from datetime import datetime, timezone
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.runtime_kraken_platform_balance_capital_feed_v415")
MARKER = "20260914-kraken-platform-balance-capital-feed-v415"
_READY_FLAG = "NIJA_RUNTIME_KRAKEN_PLATFORM_BALANCE_CAPITAL_FEED_V415_READY"
_PRIVATE_ATTR = "_nija_kraken_platform_balance_capital_feed_v415_private"
_BALANCE_ATTR = "_nija_kraken_platform_balance_capital_feed_v415_balance"
_LOCK = threading.RLock()


def _chain_has(callable_obj: Any, attr: str) -> bool:
    seen: set[int] = set()
    current = callable_obj
    for _ in range(128):
        if not callable(current) or id(current) in seen:
            return False
        seen.add(id(current))
        if bool(getattr(current, attr, False)):
            return True
        current = getattr(current, "__wrapped__", None)
    return False


def _is_platform_account(broker: Any) -> bool:
    account = str(getattr(broker, "account_identifier", "") or "").strip().upper()
    if account == "PLATFORM" or account.startswith("PLATFORM:"):
        return True
    account_type = getattr(broker, "account_type", None)
    value = str(getattr(account_type, "value", account_type) or "").strip().upper()
    return value == "PLATFORM"


def _valid_credential_balance(broker: Any, response: Any) -> bool:
    if not isinstance(response, Mapping):
        return False
    if response.get("error"):
        return False
    if not isinstance(response.get("result"), Mapping):
        return False
    try:
        v312 = importlib.import_module("bot.runtime_kraken_balance_epoch_handoff_v312_patch")
        key_fn = getattr(v312, "_credential_key", None)
        if not callable(key_fn):
            return False
        key, proven = key_fn(broker)
        return bool(str(key or "") and proven)
    except Exception:
        return False


def _scalar(value: Any) -> float:
    try:
        parsed = float(value or 0.0)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    return parsed if math.isfinite(parsed) and parsed > 0.0 else 0.0


def _normalized_capital(value: Any) -> float:
    """Mirror CapitalAuthority.refresh's accepted normalized balance contract."""
    if isinstance(value, Mapping):
        trading = _scalar(value.get("trading_balance"))
        if trading > 0.0:
            return trading
        total = _scalar(value.get("total_funds"))
        if total > 0.0:
            return total
        usd = _scalar(value.get("usd"))
        usdc = _scalar(value.get("usdc"))
        combined = usd + usdc
        return combined if combined > 0.0 else 0.0
    return _scalar(value)


def _patch_kraken_class() -> bool:
    try:
        module = importlib.import_module("bot.broker_manager")
        cls = getattr(module, "KrakenBroker", None)
    except Exception:
        return False
    if not isinstance(cls, type):
        return False

    private_current = getattr(cls, "_kraken_private_call", None)
    balance_current = getattr(cls, "get_account_balance", None)
    if not callable(private_current) or not callable(balance_current):
        return False

    if not _chain_has(private_current, _PRIVATE_ATTR):
        original_private = private_current

        @wraps(original_private)
        def private_call_v415(self: Any, *args: Any, **kwargs: Any):
            method = str(args[0] if args else kwargs.get("method", "") or "")
            response = original_private(self, *args, **kwargs)
            if method != "Balance" or not _is_platform_account(self):
                return response
            if not _valid_credential_balance(self, response):
                return response
            try:
                seq = int(getattr(self, "_nija_v415_platform_balance_seq", 0) or 0) + 1
                setattr(self, "_nija_v415_platform_balance_seq", seq)
                setattr(self, "_nija_v415_platform_balance_observed_monotonic", time.monotonic())
                setattr(self, "_nija_v415_platform_balance_observed_wall", datetime.now(timezone.utc))
                LOGGER.critical(
                    "KRAKEN_PLATFORM_BALANCE_V415_OBSERVED marker=%s account=PLATFORM sequence=%d "
                    "authenticated_balance=true credential_proven=true new_broker_io=false "
                    "capital_freshness_granted=false safety_gates_bypassed=false",
                    MARKER,
                    seq,
                )
            except Exception:
                LOGGER.debug("v415 platform Balance observation marker deferred", exc_info=True)
            return response

        setattr(private_call_v415, _PRIVATE_ATTR, True)
        setattr(private_call_v415, "__wrapped__", original_private)
        cls._kraken_private_call = private_call_v415

    balance_current = getattr(cls, "get_account_balance", None)
    if not callable(balance_current):
        return False
    if not _chain_has(balance_current, _BALANCE_ATTR):
        original_balance = balance_current

        @wraps(original_balance)
        def get_account_balance_v415(self: Any, *args: Any, **kwargs: Any):
            before_seq = int(getattr(self, "_nija_v415_platform_balance_seq", 0) or 0)
            result = original_balance(self, *args, **kwargs)
            if not _is_platform_account(self):
                return result
            after_seq = int(getattr(self, "_nija_v415_platform_balance_seq", 0) or 0)
            if after_seq <= before_seq:
                return result

            observed_mono = _scalar(getattr(self, "_nija_v415_platform_balance_observed_monotonic", 0.0))
            observed_wall = getattr(self, "_nija_v415_platform_balance_observed_wall", None)
            age_s = max(0.0, time.monotonic() - observed_mono) if observed_mono > 0.0 else float("inf")
            # This bridge is only for the just-completed invocation.  A long-tail
            # valuation must not turn an old private observation into fresh capital.
            if not isinstance(observed_wall, datetime) or age_s > 30.0:
                LOGGER.warning(
                    "KRAKEN_PLATFORM_BALANCE_CA_FEED_V415_DEFERRED marker=%s reason=observation_not_current "
                    "age_s=%.2f max_age_s=30.0 freshness_extended=false trading_fail_closed=true",
                    MARKER,
                    age_s,
                )
                return result

            balance = _normalized_capital(result)
            if balance <= 0.0:
                LOGGER.warning(
                    "KRAKEN_PLATFORM_BALANCE_CA_FEED_V415_DEFERRED marker=%s reason=normalized_balance_unavailable "
                    "freshness_extended=false trading_fail_closed=true",
                    MARKER,
                )
                return result

            try:
                capital = importlib.import_module("bot.capital_authority")
                getter = getattr(capital, "get_capital_authority", None)
                authority = getter() if callable(getter) else None
                feeder = getattr(authority, "feed_broker_balance", None) if authority is not None else None
                if not callable(feeder):
                    raise RuntimeError("capital_authority_feed_unavailable")
                feeder("kraken", balance, timestamp=observed_wall)
                LOGGER.critical(
                    "KRAKEN_PLATFORM_BALANCE_CA_FEED_V415_ACCEPTED marker=%s broker=kraken balance=%.8f "
                    "source=canonical_authenticated_platform_balance observation_age_s=%.3f "
                    "observation_timestamp_preserved=true new_broker_io=false cached_call_cannot_refresh=true "
                    "capital_value_fabricated=false freshness_extended=false readiness_granted=false "
                    "execution_authority_granted=false safety_gates_bypassed=false",
                    MARKER,
                    balance,
                    age_s,
                )
            except Exception as exc:
                LOGGER.warning(
                    "KRAKEN_PLATFORM_BALANCE_CA_FEED_V415_DEFERRED marker=%s reason=capital_feed_rejected "
                    "error=%s:%s registration_gate_preserved=true freshness_extended=false "
                    "trading_fail_closed=true safety_gates_bypassed=false",
                    MARKER,
                    type(exc).__name__,
                    exc,
                )
            return result

        setattr(get_account_balance_v415, _BALANCE_ATTR, True)
        setattr(get_account_balance_v415, "__wrapped__", original_balance)
        cls.get_account_balance = get_account_balance_v415

    return bool(
        _chain_has(getattr(cls, "_kraken_private_call", None), _PRIVATE_ATTR)
        and _chain_has(getattr(cls, "get_account_balance", None), _BALANCE_ATTR)
    )


def install_import_hook() -> bool:
    with _LOCK:
        ready = bool(_patch_kraken_class())
        os.environ[_READY_FLAG] = "1" if ready else "0"
        if ready:
            LOGGER.critical(
                "RUNTIME_KRAKEN_PLATFORM_BALANCE_CAPITAL_FEED_V415_READY marker=%s ready=true "
                "platform_only=true authenticated_private_balance_required=true normalized_outer_result_required=true "
                "cached_call_cannot_refresh=true observation_timestamp_preserved=true new_broker_io=false "
                "capital_ttl_unchanged=true writer_nonce_risk_killswitch_position_protection_order_fill_gates_unchanged=true "
                "forced_activation=false safety_gates_bypassed=false",
                MARKER,
            )
        else:
            LOGGER.warning(
                "RUNTIME_KRAKEN_PLATFORM_BALANCE_CAPITAL_FEED_V415_NOT_READY marker=%s "
                "trading_fail_closed=true safety_gates_bypassed=false",
                MARKER,
            )
        return ready


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_normalized_capital",
    "_is_platform_account",
]
