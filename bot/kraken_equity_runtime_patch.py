"""Kraken total-equity hydration and dynamic asset valuation.

Balance reads remain idempotent and never mutate PositionTracker.  Non-cash
assets are valued through Kraken's public ``AssetPairs`` and ``Ticker`` endpoints
when the broker's convenience price methods do not support the asset's actual
quote pair.  This repairs assets such as AIR that were excluded after a single
hard-coded AIR-USDT lookup failed.
"""

from __future__ import annotations

import builtins
import logging
import time
from functools import wraps
from typing import Any, Dict, Mapping, Optional, Tuple

logger = logging.getLogger("nija.kraken_equity_patch")
_PATCHED_ATTR = "__nija_kraken_equity_patch_v2__"
_MARKER = "20260713-kraken-equity-v2"
_CASH_ASSETS = {"USD", "ZUSD", "USDT", "USDC", "ZEUR", "EUR", "USDG", "USAT"}
_ASSET_ALIASES = {
    "XXBT": "XBT",
    "BTC": "XBT",
    "XBT": "XBT",
    "XETH": "ETH",
    "ZUSD": "USD",
    "ZEUR": "EUR",
}
_NON_ASSET_BALANCE_KEYS = {
    "ERROR", "RESULT", "EB", "TB", "M", "UV", "N", "C", "V", "E", "MF", "MFO",
    "TOTAL_FUNDS", "TOTAL_BALANCE", "TOTAL_EQUITY", "EQUITY", "TRADING_BALANCE",
    "USD_HELD", "USDT_HELD", "USDC_HELD", "TOTAL_HELD", "NON_USD_USD", "CRYPTO_USD",
}
_PAIR_CACHE: Dict[Tuple[int, str], Tuple[float, Optional[Tuple[str, str]]]] = {}
_PRICE_CACHE: Dict[Tuple[int, str], Tuple[float, float, str]] = {}


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value or 0.0)
    except (TypeError, ValueError, OverflowError):
        return default
    return parsed if parsed == parsed else default


def _asset_name(asset: str) -> str:
    raw = str(asset or "").upper().strip()
    return _ASSET_ALIASES.get(raw, raw)


def _is_cash(asset: str) -> bool:
    return _asset_name(asset) in _CASH_ASSETS


def _extract_raw_balances(payload: Any) -> Dict[str, float]:
    if not isinstance(payload, dict):
        return {}
    candidates: list[dict] = []
    for key in ("crypto", "assets", "balances", "raw_balances", "result"):
        value = payload.get(key)
        if isinstance(value, dict):
            candidates.append(value)
    candidates.append(payload)
    out: Dict[str, float] = {}
    for data in candidates:
        for asset, value in data.items():
            name = _asset_name(str(asset))
            if not name or name in _NON_ASSET_BALANCE_KEYS or _is_cash(name):
                continue
            if isinstance(value, (dict, list, tuple, set)):
                continue
            qty = _safe_float(value)
            if qty > 0:
                out[name] = max(out.get(name, 0.0), qty)
    return out


def _call_balance_payload(instance: Any, *, allow_live_probe: bool = True) -> dict:
    for attr in (
        "_last_raw_balances", "last_raw_balances", "_raw_balances", "raw_balances",
        "_balance_payload", "balance_payload",
    ):
        cached = getattr(instance, attr, None)
        if isinstance(cached, dict):
            return cached
    methods = ["get_balance_snapshot", "get_portfolio_breakdown", "get_balances"]
    if allow_live_probe:
        methods.append("get_account_balance")
    for method_name in methods:
        method = getattr(instance, method_name, None)
        if not callable(method):
            continue
        try:
            try:
                result = method(verbose=False)
            except TypeError:
                result = method()
            if isinstance(result, dict):
                return result
            for attr in ("_last_raw_balances", "last_raw_balances", "_raw_balances", "raw_balances"):
                cached = getattr(instance, attr, None)
                if isinstance(cached, dict):
                    return cached
        except Exception as exc:
            logger.debug("Kraken balance payload probe skipped method=%s error=%s", method_name, exc)
    return {}


def _public_call(instance: Any, method: str, params: Optional[Dict[str, Any]] = None) -> dict:
    custom = getattr(instance, "_kraken_public_api_call", None)
    if callable(custom):
        result = custom(method, params or {})
        return result if isinstance(result, dict) else {}
    api = getattr(instance, "api", None)
    query_public = getattr(api, "query_public", None)
    if callable(query_public):
        result = query_public(method, params or {})
        return result if isinstance(result, dict) else {}
    query_public = getattr(instance, "query_public", None)
    if callable(query_public):
        result = query_public(method, params or {})
        return result if isinstance(result, dict) else {}
    return {}


def _quote_from_pair_row(row: Mapping[str, Any], fallback: str) -> str:
    quote = _asset_name(str(row.get("quote") or ""))
    if quote:
        return quote
    wsname = str(row.get("wsname") or "").upper()
    if "/" in wsname:
        return _asset_name(wsname.rsplit("/", 1)[1])
    for candidate in ("USDT", "USDC", "USD", "EUR"):
        if fallback.upper().endswith(candidate):
            return candidate
    return "USD"


def _resolve_asset_pair(instance: Any, asset: str) -> Optional[Tuple[str, str]]:
    base = _asset_name(asset)
    key = (id(instance), base)
    now = time.monotonic()
    cached = _PAIR_CACHE.get(key)
    if cached and now - cached[0] < 1800.0:
        return cached[1]
    candidates = [f"{base}{quote}" for quote in ("USD", "USDT", "USDC", "EUR")]
    for candidate in candidates:
        try:
            payload = _public_call(instance, "AssetPairs", {"pair": candidate})
            errors = payload.get("error") or [] if isinstance(payload, dict) else ["invalid"]
            result = payload.get("result", {}) if isinstance(payload, dict) else {}
            if errors or not isinstance(result, Mapping) or not result:
                continue
            row = next(iter(result.values()))
            if not isinstance(row, Mapping):
                continue
            pair = str(row.get("altname") or candidate)
            quote = _quote_from_pair_row(row, candidate)
            resolved = (pair, quote)
            _PAIR_CACHE[key] = (now, resolved)
            logger.info(
                "KRAKEN_ASSET_PAIR_RESOLVED marker=%s asset=%s pair=%s quote=%s",
                _MARKER, base, pair, quote,
            )
            return resolved
        except Exception:
            continue
    _PAIR_CACHE[key] = (now, None)
    logger.warning(
        "KRAKEN_ASSET_PAIR_UNRESOLVED marker=%s asset=%s candidates=%s",
        _MARKER, base, candidates,
    )
    return None


def _ticker_last(payload: Any) -> float:
    if not isinstance(payload, Mapping):
        return 0.0
    result = payload.get("result", payload)
    if not isinstance(result, Mapping) or not result:
        return 0.0
    row = next(iter(result.values()))
    if not isinstance(row, Mapping):
        return 0.0
    for key in ("c", "last", "price", "close"):
        value = row.get(key)
        if isinstance(value, (list, tuple)) and value:
            value = value[0]
        price = _safe_float(value)
        if price > 0:
            return price
    return 0.0


def _quote_to_usd(instance: Any, quote: str) -> float:
    quote = _asset_name(quote)
    if quote in {"USD", "USDT", "USDC"}:
        return 1.0
    if quote != "EUR":
        return 0.0
    for pair in ("EURUSD", "ZEURZUSD"):
        price = _ticker_last(_public_call(instance, "Ticker", {"pair": pair}))
        if price > 0:
            return price
    return 0.0


def _price_asset(instance: Any, asset: str) -> Tuple[float, str, str]:
    base = _asset_name(asset)
    cache_key = (id(instance), base)
    now = time.monotonic()
    cached = _PRICE_CACHE.get(cache_key)
    if cached and now - cached[0] < 30.0:
        return cached[1], cached[2], "cache"

    pairs = [
        f"{base}-USD", f"{base}/USD", f"{base}USD",
        f"{base}-USDT", f"{base}/USDT", f"{base}USDT",
        f"{base}-USDC", f"{base}/USDC", f"{base}USDC",
    ]
    for method_name in ("get_current_price", "get_price", "fetch_price", "get_ticker_price"):
        method = getattr(instance, method_name, None)
        if not callable(method):
            continue
        for pair in pairs:
            try:
                price = _safe_float(method(pair))
                if price > 0:
                    _PRICE_CACHE[cache_key] = (now, price, pair)
                    return price, pair, f"broker.{method_name}"
            except Exception:
                continue

    resolved = _resolve_asset_pair(instance, base)
    if resolved:
        pair, quote = resolved
        native = _ticker_last(_public_call(instance, "Ticker", {"pair": pair}))
        conversion = _quote_to_usd(instance, quote)
        usd_price = native * conversion if native > 0 and conversion > 0 else 0.0
        if usd_price > 0:
            _PRICE_CACHE[cache_key] = (now, usd_price, pair)
            logger.info(
                "KRAKEN_ASSET_USD_PRICE_RESOLVED marker=%s asset=%s pair=%s quote=%s native=%.12f usd=%.12f",
                _MARKER, base, pair, quote, native, usd_price,
            )
            return usd_price, pair, "kraken_public"

    logger.warning("KRAKEN_ASSET_USD_PRICE_MISSING marker=%s asset=%s", _MARKER, base)
    return 0.0, "", "unavailable"


def _build_positions(instance: Any, raw_assets: Dict[str, float]) -> list[Dict[str, Any]]:
    positions: list[Dict[str, Any]] = []
    for asset, qty in raw_assets.items():
        price, pair, source = _price_asset(instance, asset)
        size_usd = qty * price if price > 0 else 0.0
        positions.append({
            "symbol": f"{asset}-USD",
            "asset": asset,
            "currency": asset,
            "quantity": qty,
            "side": "long",
            "current_price": price,
            "size_usd": size_usd,
            "price_pair": pair,
            "price_source": source,
            "source": "kraken.crypto_balance",
            "status": "active_position",
        })
    return positions


def _cash_from_payload(payload: dict) -> float:
    candidates: list[dict] = []
    for key in ("result", "balances", "raw_balances", "assets"):
        value = payload.get(key)
        if isinstance(value, dict):
            candidates.append(value)
    candidates.append(payload)
    cash = 0.0
    for data in candidates:
        subtotal = 0.0
        for asset, value in data.items():
            if _is_cash(str(asset)) and not isinstance(value, (dict, list, tuple, set)):
                subtotal += max(0.0, _safe_float(value))
        cash = max(cash, subtotal)
    return cash


def _direct_total_from_payload(payload: dict) -> float:
    totals = []
    for key in (
        "total_funds", "total_balance", "total_equity", "equity", "portfolio_value",
        "account_equity", "eb", "e",
    ):
        if key in payload:
            totals.append(_safe_float(payload.get(key)))
    result = payload.get("result")
    if isinstance(result, dict):
        for key in ("total_funds", "total_balance", "total_equity", "equity", "eb", "e"):
            if key in result:
                totals.append(_safe_float(result.get(key)))
    return max([0.0] + totals)


def _payload_total_equity(payload: dict, positions: list[Dict[str, Any]]) -> float:
    if not isinstance(payload, dict):
        payload = {}
    direct = _direct_total_from_payload(payload)
    cash = _cash_from_payload(payload)
    held = max(_safe_float(payload.get("usd_held")), _safe_float(payload.get("total_held")), 0.0)
    crypto_usd = sum(_safe_float(position.get("size_usd")) for position in positions)
    declared_crypto = max(_safe_float(payload.get("crypto_usd")), _safe_float(payload.get("non_usd_usd")), 0.0)
    return max(direct, cash + held + max(crypto_usd, declared_crypto))


def _balance_total(value: Any) -> float:
    if isinstance(value, Mapping):
        for key in ("total_funds", "total_balance", "total_equity", "equity", "available_balance", "balance"):
            parsed = _safe_float(value.get(key))
            if parsed > 0:
                return parsed
        return 0.0
    return _safe_float(value)


def _cache_position_snapshot(instance: Any, positions: list[Dict[str, Any]]) -> None:
    try:
        setattr(instance, "_last_kraken_position_snapshot", tuple(dict(item) for item in positions))
        setattr(instance, "_last_kraken_position_snapshot_count", len(positions))
    except Exception:
        pass


def _patch_kraken_class(cls: type) -> bool:
    if getattr(cls, _PATCHED_ATTR, False):
        return True

    original_get_positions = getattr(cls, "get_positions", None)

    def get_positions(self: Any):
        existing: list[Dict[str, Any]] = []
        if callable(original_get_positions):
            try:
                result = original_get_positions(self)
                if isinstance(result, list):
                    existing.extend(item for item in result if isinstance(item, dict))
            except Exception as exc:
                logger.warning("KRAKEN_EQUITY_POSITION_CLASSIFICATION original get_positions failed: %s", exc)
        payload = _call_balance_payload(self, allow_live_probe=False)
        positions = _build_positions(self, _extract_raw_balances(payload))
        seen = {str(item.get("symbol", "")).upper() for item in existing}
        for position in positions:
            if str(position.get("symbol", "")).upper() not in seen:
                existing.append(position)
        _cache_position_snapshot(self, positions)
        if positions:
            logger.warning(
                "KRAKEN_CRYPTO_POSITIONS_CLASSIFIED marker=%s count=%d total_crypto_usd=%.2f symbols=%s tracker_mutation=false",
                _MARKER,
                len(positions),
                sum(_safe_float(item.get("size_usd")) for item in positions),
                ",".join(str(item.get("symbol")) for item in positions),
            )
        return existing

    setattr(cls, "get_positions", get_positions)

    original_get_account_balance = getattr(cls, "get_account_balance", None)
    if callable(original_get_account_balance):
        @wraps(original_get_account_balance)
        def get_account_balance(self: Any, *args: Any, **kwargs: Any):
            original_value = original_get_account_balance(self, *args, **kwargs)
            base_total = _balance_total(original_value)
            payload = _call_balance_payload(self, allow_live_probe=False)
            positions = _build_positions(self, _extract_raw_balances(payload))
            authoritative_total = _payload_total_equity(payload, positions)
            final_total = max(base_total, authoritative_total)
            _cache_position_snapshot(self, positions)
            if final_total > 0:
                setattr(self, "_last_known_balance", final_total)
                try:
                    enriched_payload = dict(payload)
                    enriched_payload["crypto_usd"] = sum(_safe_float(item.get("size_usd")) for item in positions)
                    enriched_payload["total_funds"] = final_total
                    enriched_payload["crypto_positions"] = positions
                    setattr(self, "_last_raw_balances", enriched_payload)
                except Exception:
                    pass
            logger.warning(
                "KRAKEN_EQUITY_CANONICAL marker=%s base_total=%.2f payload_total=%.2f final_total=%.2f "
                "crypto_usd=%.2f double_count_prevented=true tracker_mutation=false",
                _MARKER,
                base_total,
                authoritative_total,
                final_total,
                sum(_safe_float(item.get("size_usd")) for item in positions),
            )
            if isinstance(original_value, Mapping):
                updated = dict(original_value)
                updated["total_balance"] = max(_safe_float(updated.get("total_balance")), final_total)
                updated["total_funds"] = max(_safe_float(updated.get("total_funds")), final_total)
                return updated
            return final_total

        setattr(cls, "get_account_balance", get_account_balance)

    original_connect = getattr(cls, "connect", None)
    if callable(original_connect):
        @wraps(original_connect)
        def connect(self: Any, *args: Any, **kwargs: Any):
            result = original_connect(self, *args, **kwargs)
            if result:
                try:
                    positions = get_positions(self)
                    logger.warning(
                        "KRAKEN_STARTUP_POSITION_VISIBILITY marker=%s positions=%d symbols=%s tracker_mutation=false",
                        _MARKER,
                        len(positions),
                        ",".join(str(item.get("symbol")) for item in positions if isinstance(item, dict)),
                    )
                except Exception as exc:
                    logger.warning("KRAKEN_STARTUP_POSITION_VISIBILITY_ERROR marker=%s error=%s", _MARKER, exc)
            return result

        setattr(cls, "connect", connect)

    setattr(cls, _PATCHED_ATTR, True)
    logger.warning("KRAKEN_EQUITY_HYDRATION_PATCHED marker=%s class=%s canonical_total=true dynamic_pairs=true", _MARKER, cls.__name__)
    return True


def _patch_module(module: Any) -> bool:
    patched = False
    for name in dir(module):
        if "kraken" not in name.lower():
            continue
        obj = getattr(module, name, None)
        if isinstance(obj, type):
            patched = _patch_kraken_class(obj) or patched
    return patched


def install_import_hook() -> None:
    import sys
    for name, module in list(sys.modules.items()):
        if name.endswith(("broker_manager", "kraken_broker", "broker_integration", "execution_engine")):
            try:
                _patch_module(module)
            except Exception:
                continue
    if getattr(builtins, "_NIJA_KRAKEN_EQUITY_PATCH_HOOK_INSTALLED_V2", False):
        return
    original_import = builtins.__import__
    hook_local = __import__("threading").local()

    def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        if getattr(hook_local, "active", False):
            return module
        if name.endswith(("broker_manager", "kraken_broker", "broker_integration", "execution_engine")):
            hook_local.active = True
            try:
                _patch_module(module)
            except Exception as exc:
                logger.warning("Kraken equity runtime patch failed: %s", exc)
            finally:
                hook_local.active = False
        return module

    builtins.__import__ = guarded_import
    setattr(builtins, "_NIJA_KRAKEN_EQUITY_PATCH_HOOK_INSTALLED_V2", True)
    logger.critical("KRAKEN_EQUITY_RUNTIME_INSTALLED marker=%s dynamic_pairs=true", _MARKER)


__all__ = [
    "install_import_hook",
    "_extract_raw_balances",
    "_payload_total_equity",
    "_resolve_asset_pair",
    "_price_asset",
    "_patch_kraken_class",
]
