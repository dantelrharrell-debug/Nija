"""Kraken total-equity hydration patch.

This layer classifies non-cash Kraken holdings for visibility while keeping
balance reads idempotent. It never mutates PositionTracker during a balance read,
never recursively calls the wrapped get_account_balance method, and never adds
crypto value twice when the broker already returned total account equity.
"""

from __future__ import annotations

import builtins
import logging
from functools import wraps
from typing import Any, Dict

logger = logging.getLogger("nija.kraken_equity_patch")
_PATCHED_ATTR = "__nija_kraken_equity_patch__"
_CASH_ASSETS = {"USD", "ZUSD", "USDT", "USDC", "ZEUR", "EUR", "USDG", "USAT"}
_ASSET_ALIASES = {
    "XXBT": "BTC",
    "XBT": "BTC",
    "XETH": "ETH",
    "ZUSD": "USD",
    "ZEUR": "EUR",
}
_NON_ASSET_BALANCE_KEYS = {
    "ERROR",
    "RESULT",
    "EB",
    "TB",
    "M",
    "UV",
    "N",
    "C",
    "V",
    "E",
    "MF",
    "MFO",
    "TOTAL_FUNDS",
    "TOTAL_BALANCE",
    "TOTAL_EQUITY",
    "EQUITY",
    "TRADING_BALANCE",
    "USD_HELD",
    "USDT_HELD",
    "USDC_HELD",
    "TOTAL_HELD",
    "NON_USD_USD",
    "CRYPTO_USD",
}


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
    """Extract positive non-cash asset quantities from Kraken balance payloads."""
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
    """Return cached balance metadata, optionally probing non-recursive helpers."""
    for attr in (
        "_last_raw_balances",
        "last_raw_balances",
        "_raw_balances",
        "raw_balances",
        "_balance_payload",
        "balance_payload",
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


def _price_asset(instance: Any, asset: str) -> float:
    base = _asset_name(asset)
    pairs = [
        f"{base}-USD",
        f"{base}/USD",
        f"{base}USD",
        f"{base}-USDT",
        f"{base}/USDT",
        f"{base}USDT",
    ]
    for method_name in ("get_current_price", "get_price", "fetch_price", "get_ticker_price"):
        method = getattr(instance, method_name, None)
        if not callable(method):
            continue
        for pair in pairs:
            try:
                price = _safe_float(method(pair))
                if price > 0:
                    return price
            except Exception:
                continue
    for method_name in ("get_ticker", "fetch_ticker", "ticker"):
        method = getattr(instance, method_name, None)
        if not callable(method):
            continue
        for pair in pairs:
            try:
                ticker = method(pair)
                if not isinstance(ticker, dict):
                    continue
                for key in ("last", "price", "c", "close"):
                    value = ticker.get(key)
                    if isinstance(value, (list, tuple)) and value:
                        value = value[0]
                    price = _safe_float(value)
                    if price > 0:
                        return price
            except Exception:
                continue
    return 0.0


def _build_positions(instance: Any, raw_assets: Dict[str, float]) -> list[Dict[str, Any]]:
    positions: list[Dict[str, Any]] = []
    for asset, qty in raw_assets.items():
        price = _price_asset(instance, asset)
        size_usd = qty * price if price > 0 else 0.0
        positions.append(
            {
                "symbol": f"{asset}-USD",
                "asset": asset,
                "currency": asset,
                "quantity": qty,
                "side": "long",
                "current_price": price,
                "size_usd": size_usd,
                "source": "kraken.crypto_balance",
                "status": "active_position",
            }
        )
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
        "total_funds",
        "total_balance",
        "total_equity",
        "equity",
        "portfolio_value",
        "account_equity",
        "eb",
        "e",
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
    held = max(
        _safe_float(payload.get("usd_held")),
        _safe_float(payload.get("total_held")),
        0.0,
    )
    crypto_usd = sum(_safe_float(position.get("size_usd")) for position in positions)
    declared_crypto = max(
        _safe_float(payload.get("crypto_usd")),
        _safe_float(payload.get("non_usd_usd")),
        0.0,
    )
    computed = cash + held + max(crypto_usd, declared_crypto)
    return max(direct, computed)


def _cache_position_snapshot(instance: Any, positions: list[Dict[str, Any]]) -> None:
    """Cache visibility only; PositionTracker reconciliation happens elsewhere."""
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
        raw_assets = _extract_raw_balances(payload)
        positions = _build_positions(self, raw_assets)
        seen = {str(item.get("symbol", "")).upper() for item in existing}
        for position in positions:
            if str(position.get("symbol", "")).upper() not in seen:
                existing.append(position)
        _cache_position_snapshot(self, positions)
        if positions:
            logger.warning(
                "KRAKEN_CRYPTO_POSITIONS_CLASSIFIED count=%d total_crypto_usd=%.2f symbols=%s tracker_mutation=false",
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
            base_total = _safe_float(original_get_account_balance(self, *args, **kwargs))
            # Do not call get_account_balance again from payload discovery.
            payload = _call_balance_payload(self, allow_live_probe=False)
            raw_assets = _extract_raw_balances(payload)
            positions = _build_positions(self, raw_assets)
            authoritative_total = _payload_total_equity(payload, positions)
            final_total = max(base_total, authoritative_total)
            _cache_position_snapshot(self, positions)
            if final_total > 0:
                setattr(self, "_last_known_balance", final_total)
                try:
                    enriched_payload = dict(payload)
                    enriched_payload["crypto_usd"] = sum(
                        _safe_float(item.get("size_usd")) for item in positions
                    )
                    enriched_payload["total_funds"] = final_total
                    setattr(self, "_last_raw_balances", enriched_payload)
                except Exception:
                    pass
            logger.warning(
                "KRAKEN_EQUITY_CANONICAL base_total=%.2f payload_total=%.2f final_total=%.2f "
                "crypto_usd=%.2f double_count_prevented=true tracker_mutation=false",
                base_total,
                authoritative_total,
                final_total,
                sum(_safe_float(item.get("size_usd")) for item in positions),
            )
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
                        "KRAKEN_STARTUP_POSITION_VISIBILITY positions=%d symbols=%s tracker_mutation=false",
                        len(positions),
                        ",".join(str(item.get("symbol")) for item in positions if isinstance(item, dict)),
                    )
                except Exception as exc:
                    logger.warning("KRAKEN_STARTUP_POSITION_VISIBILITY_ERROR error=%s", exc)
            return result

        setattr(cls, "connect", connect)

    setattr(cls, _PATCHED_ATTR, True)
    logger.warning("KRAKEN_EQUITY_HYDRATION_PATCHED class=%s canonical_total=true", cls.__name__)
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

    if getattr(builtins, "_NIJA_KRAKEN_EQUITY_PATCH_HOOK_INSTALLED", False):
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
    setattr(builtins, "_NIJA_KRAKEN_EQUITY_PATCH_HOOK_INSTALLED", True)


__all__ = [
    "install_import_hook",
    "_extract_raw_balances",
    "_payload_total_equity",
    "_patch_kraken_class",
]
