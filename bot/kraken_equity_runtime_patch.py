"""Kraken total-equity hydration patch.

Kraken balances can include USD cash, held USD/open-order funds, and separate
crypto holdings.  Earlier snapshots only counted USD available + USD held, which
undercounted accounts where crypto holdings remain open on Kraken.

This patch is conservative:
- it does not place, cancel, or modify orders;
- it does not change risk rules;
- it only enriches balance snapshots/position visibility when crypto balances
  can be priced from Kraken market data.
"""

from __future__ import annotations

import builtins
import logging
from functools import wraps
from typing import Any, Dict, Iterable

logger = logging.getLogger("nija.kraken_equity_patch")
_PATCHED_ATTR = "__nija_kraken_equity_patch__"
_CASH_ASSETS = {"USD", "ZUSD", "USDT", "USDC", "ZEUR", "EUR"}
_ASSET_ALIASES = {
    "XXBT": "BTC",
    "XBT": "BTC",
    "XETH": "ETH",
    "ZUSD": "USD",
    "ZEUR": "EUR",
}


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return default


def _asset_name(asset: str) -> str:
    raw = str(asset or "").upper().strip()
    return _ASSET_ALIASES.get(raw, raw)


def _is_cash(asset: str) -> bool:
    return _asset_name(asset) in _CASH_ASSETS


def _extract_raw_balances(payload: Any) -> Dict[str, float]:
    """Extract Kraken raw asset quantities from common response shapes."""
    if not isinstance(payload, dict):
        return {}
    candidates = []
    for key in ("crypto", "assets", "balances", "raw_balances", "result"):
        value = payload.get(key)
        if isinstance(value, dict):
            candidates.append(value)
    # Some code stores raw balances directly at the top level.
    candidates.append(payload)
    out: Dict[str, float] = {}
    for data in candidates:
        for asset, value in data.items():
            name = _asset_name(str(asset))
            if not name or name in {"USD_HELD", "USDT_HELD", "TOTAL_HELD", "TOTAL_FUNDS", "TRADING_BALANCE"}:
                continue
            qty = _safe_float(value)
            if qty > 0 and not _is_cash(name):
                out[name] = max(out.get(name, 0.0), qty)
    return out


def _call_balance_payload(instance: Any) -> dict:
    for attr in ("_last_raw_balances", "last_raw_balances", "_raw_balances", "raw_balances", "_balance_payload", "balance_payload"):
        cached = getattr(instance, attr, None)
        if isinstance(cached, dict):
            return cached
    for method_name in ("get_balance_snapshot", "get_portfolio_breakdown", "get_balances", "get_account_balance"):
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
    pairs = [f"{base}-USD", f"{base}/USD", f"{base}USD", f"{base}-USDT", f"{base}/USDT", f"{base}USDT"]
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
    ticker_methods = ("get_ticker", "fetch_ticker", "ticker")
    for method_name in ticker_methods:
        method = getattr(instance, method_name, None)
        if not callable(method):
            continue
        for pair in pairs:
            try:
                ticker = method(pair)
                if isinstance(ticker, dict):
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
        positions.append({
            "symbol": f"{asset}-USD",
            "asset": asset,
            "currency": asset,
            "quantity": qty,
            "side": "long",
            "current_price": price,
            "size_usd": size_usd,
            "source": "kraken.crypto_balance",
            "status": "active_position",
        })
    return positions


def _sync_tracker(instance: Any, positions: list[Dict[str, Any]]) -> None:
    if not positions:
        return
    for tracker_attr in ("position_tracker", "_position_tracker", "tracker"):
        tracker = getattr(instance, tracker_attr, None)
        if tracker is None:
            continue
        for pos in positions:
            for method_name in ("add_position", "record_position", "sync_position", "update_position"):
                method = getattr(tracker, method_name, None)
                if not callable(method):
                    continue
                try:
                    method(pos)
                    break
                except TypeError:
                    try:
                        method(pos.get("symbol"), pos.get("quantity"), pos.get("current_price", 0.0))
                        break
                    except Exception:
                        continue
                except Exception:
                    continue


def _patch_kraken_class(cls: type) -> bool:
    if getattr(cls, _PATCHED_ATTR, False):
        return True

    original_get_positions = getattr(cls, "get_positions", None)

    def get_positions(self: Any):
        existing = []
        if callable(original_get_positions):
            try:
                result = original_get_positions(self)
                if isinstance(result, list):
                    existing.extend(result)
            except Exception as exc:
                logger.warning("KRAKEN_EQUITY_POSITION_CLASSIFICATION original get_positions failed: %s", exc)
        payload = _call_balance_payload(self)
        raw_assets = _extract_raw_balances(payload)
        positions = _build_positions(self, raw_assets)
        seen = {str(p.get("symbol", "")).upper() for p in existing if isinstance(p, dict)}
        for pos in positions:
            if str(pos.get("symbol", "")).upper() not in seen:
                existing.append(pos)
        if positions:
            _sync_tracker(self, positions)
            logger.warning(
                "KRAKEN_CRYPTO_POSITIONS_CLASSIFIED count=%d total_crypto_usd=%.2f symbols=%s",
                len(positions),
                sum(_safe_float(p.get("size_usd")) for p in positions),
                ",".join(str(p.get("symbol")) for p in positions),
            )
        return existing

    setattr(cls, "get_positions", get_positions)

    original_get_account_balance = getattr(cls, "get_account_balance", None)
    if callable(original_get_account_balance):
        @wraps(original_get_account_balance)
        def get_account_balance(self: Any, *args: Any, **kwargs: Any):
            base_total = _safe_float(original_get_account_balance(self, *args, **kwargs))
            payload = _call_balance_payload(self)
            raw_assets = _extract_raw_balances(payload)
            positions = _build_positions(self, raw_assets)
            crypto_usd = sum(_safe_float(p.get("size_usd")) for p in positions)
            enriched_total = base_total + crypto_usd
            if crypto_usd > 0:
                setattr(self, "_last_known_balance", enriched_total)
                try:
                    payload["crypto_usd"] = crypto_usd
                    payload["total_funds"] = max(_safe_float(payload.get("total_funds")), enriched_total)
                    setattr(self, "_last_raw_balances", payload)
                except Exception:
                    pass
                _sync_tracker(self, positions)
                logger.warning(
                    "KRAKEN_EQUITY_ENRICHED base_total=%.2f crypto_usd=%.2f enriched_total=%.2f symbols=%s",
                    base_total,
                    crypto_usd,
                    enriched_total,
                    ",".join(str(p.get("symbol")) for p in positions),
                )
            return enriched_total if enriched_total > base_total else base_total
        setattr(cls, "get_account_balance", get_account_balance)

    original_connect = getattr(cls, "connect", None)
    if callable(original_connect):
        @wraps(original_connect)
        def connect(self: Any, *args: Any, **kwargs: Any):
            result = original_connect(self, *args, **kwargs)
            try:
                positions = get_positions(self)
                crypto_usd = sum(_safe_float(p.get("size_usd")) for p in positions if isinstance(p, dict) and p.get("source") == "kraken.crypto_balance")
                if crypto_usd > 0:
                    base = _safe_float(getattr(self, "_last_known_balance", 0.0))
                    setattr(self, "_last_known_balance", max(base, base + crypto_usd if base else crypto_usd))
                    logger.warning(
                        "KRAKEN_STARTUP_EQUITY_SYNC positions=%d crypto_usd=%.2f symbols=%s",
                        len(positions),
                        crypto_usd,
                        ",".join(str(p.get("symbol")) for p in positions if isinstance(p, dict)),
                    )
            except Exception as exc:
                logger.warning("KRAKEN_STARTUP_EQUITY_SYNC_ERROR error=%s", exc)
            return result
        setattr(cls, "connect", connect)

    setattr(cls, _PATCHED_ATTR, True)
    logger.warning("KRAKEN_EQUITY_HYDRATION_PATCHED class=%s", cls.__name__)
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
        if name.endswith(("broker_manager", "kraken_broker", "execution_engine")):
            try:
                if _patch_module(module):
                    return
            except Exception:
                continue

    if getattr(builtins, "_NIJA_KRAKEN_EQUITY_PATCH_HOOK_INSTALLED", False):
        return

    original_import = builtins.__import__

    def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        if name.endswith(("broker_manager", "kraken_broker", "execution_engine")):
            try:
                if _patch_module(module):
                    builtins.__import__ = original_import
                    setattr(builtins, "_NIJA_KRAKEN_EQUITY_PATCH_HOOK_INSTALLED", False)
            except Exception as exc:
                logger.warning("Kraken equity runtime patch failed: %s", exc)
        return module

    builtins.__import__ = guarded_import
    setattr(builtins, "_NIJA_KRAKEN_EQUITY_PATCH_HOOK_INSTALLED", True)
