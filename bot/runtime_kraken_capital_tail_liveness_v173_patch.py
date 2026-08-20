"""Keep Kraken capital refreshes from self-amplifying slow balance tails.

Production on 2026-08-20 showed the canonical proactive capital batch correctly
rejecting a 2/3 snapshot after Kraken exceeded the 30 second synchronous v78
budget.  A few seconds later the authenticated Kraken ``Balance`` request had
succeeded, but ``KrakenBroker.get_account_balance`` was still completing its
post-Balance valuation/TradeBalance tail.  Meanwhile v161 had already classified
the still-live Kraken flight as stale at 25 seconds, creating orphaned private
requests.  Production reached two live orphan requests plus one reused current
flight, which can increase Kraken serialization/rate-limit pressure and delay the
very observation needed to recover 3/3 publication.

v173 repairs only that liveness feedback loop:

* Kraken balance valuation checks a recent broker price cache before live ticker
  I/O and never invokes the same ``_get_asset_usd_price`` resolver twice for one
  asset.  Existing valuation semantics and pricing-coverage accounting remain.
* Kraken stale-flight rotation gets a 50 second default floor, still strictly
  below the existing 75 second broker timeout and 90 second capital freshness
  TTL.  Non-Kraken rotation behavior is unchanged.  A genuinely stuck Kraken
  worker can still be superseded before freshness expires.

This patch does not extend capital/publication freshness, accept partial broker
aggregation, fabricate balances or prices, bypass v162 late-result fencing,
force LIVE_ACTIVE, clear kill switches, grant writer/nonce authority, or alter
risk/order/execution gates.
"""
from __future__ import annotations

import importlib
import logging
import math
import os
import threading
import time
from functools import wraps
from typing import Any, Optional

LOGGER = logging.getLogger("nija.runtime_kraken_capital_tail_liveness_v173")
MARKER = "20260820-runtime-kraken-capital-tail-liveness-v173"
_READY_FLAG = "NIJA_RUNTIME_KRAKEN_CAPITAL_TAIL_LIVENESS_V173_READY"
_PATCH_ATTR = "_nija_runtime_kraken_capital_tail_liveness_v173"
_LOCK = threading.RLock()

_DEFAULT_PRICE_CACHE_MAX_AGE_S = 15.0
_DEFAULT_KRAKEN_STALE_FLIGHT_AFTER_S = 50.0


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)) or default)
    except (TypeError, ValueError):
        return float(default)


def _price_cache_max_age_seconds() -> float:
    return max(
        1.0,
        min(
            30.0,
            _float_env(
                "NIJA_KRAKEN_CAPITAL_PRICE_CACHE_MAX_AGE_S",
                _DEFAULT_PRICE_CACHE_MAX_AGE_S,
            ),
        ),
    )


def _positive_float(value: Any) -> Optional[float]:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(parsed) or parsed <= 0.0:
        return None
    return parsed


def _cached_pair_price(instance: Any, symbol_code: str) -> Optional[float]:
    """Return only a recent broker-owned cached USD/USDT price."""
    cache = getattr(instance, "_price_cache", None)
    if not isinstance(cache, dict):
        return None
    lock = getattr(instance, "_price_cache_lock", None)
    max_age_s = _price_cache_max_age_seconds()
    now = time.monotonic()

    def read() -> Optional[float]:
        for pair in (f"{symbol_code}-USD", f"{symbol_code}-USDT"):
            record = cache.get(pair)
            if not isinstance(record, dict):
                continue
            price = _positive_float(record.get("price"))
            try:
                ts = float(record.get("ts", 0.0) or 0.0)
            except (TypeError, ValueError):
                ts = 0.0
            if price is None or ts <= 0.0:
                continue
            age_s = max(0.0, now - ts)
            if age_s <= max_age_s:
                return price
        return None

    if lock is not None and callable(getattr(lock, "__enter__", None)):
        with lock:
            return read()
    return read()


def _is_same_bound_method(candidate: Any, instance: Any, method_name: str) -> bool:
    method = getattr(type(instance), method_name, None)
    return bool(
        getattr(candidate, "__self__", None) is instance
        and getattr(candidate, "__func__", None) is method
    )


def _compute_total_usd_balance_v173(
    instance: Any,
    balance: dict,
    price_lookup: Any,
) -> float:
    """Preserve Kraken valuation semantics while eliminating duplicate live I/O."""
    total = 0.0
    non_usd_count = 0
    priced_count = 0

    for asset, amount in (balance or {}).items():
        try:
            qty = float(amount)
        except (TypeError, ValueError, OverflowError):
            continue
        if not math.isfinite(qty) or qty <= 0.0:
            continue

        symbol = instance._normalize_kraken_asset_code(asset)
        if symbol == "USD":
            total += qty
            continue

        if symbol in {"USDT", "USDC"}:
            price = _cached_pair_price(instance, symbol)
            if price is None and callable(price_lookup):
                try:
                    price = _positive_float(price_lookup(symbol))
                except Exception:
                    price = None
            if price is not None:
                total += qty * price
            else:
                # Preserve the existing stablecoin fallback. This is not a new
                # valuation rule; v173 merely avoids unnecessary network I/O.
                LOGGER.warning(
                    "KRAKEN_CAPITAL_V173_STABLECOIN_FALLBACK marker=%s account=%s "
                    "asset=%s qty=%.8f assumed_price=1.0",
                    MARKER,
                    getattr(instance, "account_identifier", "unknown"),
                    symbol,
                    qty,
                )
                total += qty
            continue

        non_usd_count += 1
        price = _cached_pair_price(instance, symbol)
        source = "recent_price_cache" if price is not None else "live_resolver"

        if price is None and callable(price_lookup):
            try:
                price = _positive_float(price_lookup(symbol))
            except Exception:
                price = None

        # The legacy implementation invoked ``price_lookup(symbol)`` and then,
        # when it returned no price, called ``instance._get_asset_usd_price``
        # again. In the canonical call site price_lookup already IS that bound
        # method, so one asset could perform the same USD/USDT network resolver
        # twice. Keep the secondary path only for genuinely different injected
        # lookup functions.
        if (
            price is None
            and not _is_same_bound_method(price_lookup, instance, "_get_asset_usd_price")
        ):
            resolver = getattr(instance, "_get_asset_usd_price", None)
            if callable(resolver):
                try:
                    price = _positive_float(resolver(symbol))
                    source = "broker_resolver_fallback"
                except Exception:
                    price = None

        if price is not None:
            total += qty * price
            priced_count += 1
            if source == "recent_price_cache":
                LOGGER.debug(
                    "KRAKEN_CAPITAL_V173_PRICE_CACHE_HIT marker=%s account=%s asset=%s "
                    "max_age_s=%.1f network_lookup=false",
                    MARKER,
                    getattr(instance, "account_identifier", "unknown"),
                    symbol,
                    _price_cache_max_age_seconds(),
                )
        else:
            LOGGER.warning(
                "KRAKEN_CAPITAL_V173_PRICE_MISSING marker=%s account=%s asset=%s qty=%.8f "
                "duplicate_live_lookup=false excluded_from_usd_total=true",
                MARKER,
                getattr(instance, "account_identifier", "unknown"),
                symbol,
                qty,
            )

    instance._last_pricing_coverage_pct = (
        priced_count / non_usd_count if non_usd_count > 0 else 1.0
    )
    return total


def _patch_kraken_valuation() -> bool:
    broker_module = importlib.import_module("bot.broker_manager")
    broker_cls = getattr(broker_module, "KrakenBroker", None)
    if not isinstance(broker_cls, type):
        return False
    current = getattr(broker_cls, "compute_total_usd_balance", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    @wraps(current)
    def compute_v173(self: Any, balance: dict, price_lookup: Any) -> float:
        return _compute_total_usd_balance_v173(self, balance, price_lookup)

    setattr(compute_v173, _PATCH_ATTR, True)
    setattr(compute_v173, "__wrapped__", current)
    broker_cls.compute_total_usd_balance = compute_v173
    return True


def _kraken_rotation_threshold(
    base_s: float,
    broker_timeout_s: float,
    freshness_ttl_s: float,
    requested_s: float | None = None,
) -> float:
    """Return a Kraken-only stale-flight threshold inside timeout/freshness bounds."""
    base = max(2.0, float(base_s))
    timeout = max(2.0, float(broker_timeout_s))
    ttl = max(10.0, float(freshness_ttl_s))
    requested = (
        _DEFAULT_KRAKEN_STALE_FLIGHT_AFTER_S
        if requested_s is None
        else max(2.0, float(requested_s))
    )
    # Keep at least five seconds before the broker hard timeout and twenty
    # seconds before capital freshness expiry. This only delays *rotation* of a
    # still-running worker; it does not lengthen either timeout or freshness.
    ceiling = max(2.0, min(timeout - 5.0, ttl - 20.0))
    return max(base, min(requested, ceiling))


def _patch_kraken_flight_rotation() -> bool:
    v161 = importlib.import_module("bot.runtime_capital_position_convergence_v161_patch")
    current = getattr(v161, "_stale_flight_after_seconds", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    @wraps(current)
    def stale_v173(broker_id: str) -> float:
        base = max(2.0, float(current(broker_id)))
        bid = str(broker_id or "").strip().lower()
        if bid != "kraken":
            return base

        guard = importlib.import_module("bot.capital_refresh_stall_guard_v35")
        try:
            broker_timeout = float(guard._broker_timeout_seconds("kraken"))
        except Exception:
            broker_timeout = 75.0
        try:
            ttl_s = float(guard._freshness_ttl_seconds())
        except Exception:
            ttl_s = 90.0

        raw = str(os.environ.get("NIJA_CAPITAL_KRAKEN_STALE_FLIGHT_AFTER_S", "") or "").strip()
        requested: float | None = None
        if raw:
            try:
                requested = float(raw)
            except (TypeError, ValueError):
                requested = None
        return _kraken_rotation_threshold(base, broker_timeout, ttl_s, requested)

    setattr(stale_v173, _PATCH_ATTR, True)
    setattr(stale_v173, "__wrapped__", current)
    v161._stale_flight_after_seconds = stale_v173
    return True


def _patch_release_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_kraken_capital_tail_liveness_v173"] = _READY_FLAG
        return True
    except Exception:
        return False


def install() -> bool:
    with _LOCK:
        valuation_ok = _patch_kraken_valuation()
        rotation_ok = _patch_kraken_flight_rotation()
        manifest_ok = _patch_release_manifest()
        ready = bool(valuation_ok and rotation_ok and manifest_ok)
        os.environ[_READY_FLAG] = "1" if ready else "0"
        if not ready:
            LOGGER.critical(
                "RUNTIME_KRAKEN_CAPITAL_TAIL_LIVENESS_V173_FAILED marker=%s valuation=%s "
                "rotation=%s manifest=%s trading_fail_closed=true",
                MARKER,
                str(valuation_ok).lower(),
                str(rotation_ok).lower(),
                str(manifest_ok).lower(),
            )
            return False

        LOGGER.critical(
            "RUNTIME_KRAKEN_CAPITAL_TAIL_LIVENESS_V173 marker=%s ready=true "
            "cache_first_valuation=true duplicate_live_price_lookup=false "
            "kraken_stale_flight_floor_s=%.1f broker_timeout_unchanged=true "
            "freshness_ttl_unchanged=true partial_aggregation_gate_unchanged=true "
            "late_observation_fence_unchanged=true forced_trade=false safety_gates_bypassed=false",
            MARKER,
            _DEFAULT_KRAKEN_STALE_FLIGHT_AFTER_S,
        )
        return True


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_cached_pair_price",
    "_compute_total_usd_balance_v173",
    "_kraken_rotation_threshold",
    "_patch_kraken_valuation",
    "_patch_kraken_flight_rotation",
]
