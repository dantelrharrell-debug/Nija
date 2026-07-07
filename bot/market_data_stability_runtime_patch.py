"""Runtime market-data stability patch for live scans.

This patch addresses the current live blocker seen in Railway logs:

* repeated ``get_ohlc_data ... timed out`` warnings,
* hundreds of daemon ``_fetch_ohlc`` threads accumulating,
* invalid/low-value pairs consuming scan budget, and
* ``ENTRY_BLOCKED reason=data_insufficient`` after good candidates are found.

The patch replaces Kraken candle reads with Kraken's lightweight public OHLC
REST endpoint, adds a small TTL cache, bounds concurrent market-data calls,
normalizes USDC quote pairs to USD for candle reads, and fast-skips fiat/stable
base pairs that should not be selected as live crypto entries.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("nija.market_data_stability")

_INSTALLED = False
_ORIGINALS: Dict[str, Any] = {}
_CACHE: Dict[Tuple[str, str, int], Tuple[float, Optional[Dict[str, Any]]]] = {}
_CACHE_LOCK = threading.Lock()
_INFLIGHT = threading.BoundedSemaphore(value=int(os.getenv("NIJA_MARKET_DATA_MAX_CONCURRENCY", "3")))

_TRUE = {"1", "true", "yes", "on", "y", "enabled"}
_STABLE_OR_FIAT_BASES = {
    "AUSD", "AUD", "DAI", "EUR", "EURC", "EURQ", "USD", "USDC", "USDG", "USDT", "USAT"
}
_ALLOWED_QUOTES = {"USD", "USDT", "USDC"}


def _truthy(name: str, default: str = "true") -> bool:
    return str(os.getenv(name, default)).strip().lower() in _TRUE


def _split_symbol(symbol: str) -> Tuple[str, str]:
    raw = str(symbol or "").strip().upper().replace("/", "-").replace("_", "-")
    if "-" in raw:
        base, quote = raw.rsplit("-", 1)
        return base, quote
    for quote in ("USDT", "USDC", "USD", "EUR"):
        if raw.endswith(quote) and len(raw) > len(quote):
            return raw[: -len(quote)], quote
    return raw, ""


def _should_skip_symbol(symbol: str) -> Tuple[bool, str]:
    base, quote = _split_symbol(symbol)
    if not base or not quote:
        return True, "malformed_symbol"
    if quote not in _ALLOWED_QUOTES:
        return True, "unsupported_quote"
    if base in _STABLE_OR_FIAT_BASES:
        return True, "fiat_or_stable_base"
    explicit = {
        s.strip().upper().replace("/", "-").replace("_", "-")
        for s in os.getenv("NIJA_MARKET_DATA_SKIP_SYMBOLS", "AUSD-USD,AUSD-EUR,AUD-USD,ETH-USDC").split(",")
        if s.strip()
    }
    if str(symbol).strip().upper().replace("/", "-").replace("_", "-") in explicit:
        return True, "configured_skip_symbol"
    return False, "ok"


def _normalize_for_kraken_candles(symbol: str) -> str:
    base, quote = _split_symbol(symbol)
    # Kraken public OHLC is more reliable on USD than USDC for the current scan set.
    # This is market-data-only normalization; execution routing is left untouched.
    if quote == "USDC" and _truthy("NIJA_MARKET_DATA_MAP_USDC_TO_USD", "true"):
        quote = "USD"
    if base == "BTC":
        base = "XBT"
    return f"{base}{quote}"


def _parse_kraken_ohlc(result: Any, pair: str, timeframe: str, limit: int) -> Optional[Dict[str, Any]]:
    if not isinstance(result, dict):
        return None
    errors = result.get("error") or []
    if errors:
        logger.warning("MARKET_DATA_STABILITY_KRAKEN_PUBLIC_ERROR pair=%s errors=%s", pair, errors)
        return None
    payload = result.get("result") or {}
    if not isinstance(payload, dict):
        return None
    rows = None
    for key, value in payload.items():
        if key != "last" and isinstance(value, list):
            rows = value
            break
    if not rows:
        return None
    rows = rows[-int(limit):]
    candles: List[Dict[str, float]] = []
    for row in rows:
        try:
            candles.append(
                {
                    "timestamp": int(float(row[0])),
                    "open": float(row[1]),
                    "high": float(row[2]),
                    "low": float(row[3]),
                    "close": float(row[4]),
                    "volume": float(row[6] if len(row) > 6 else row[5]),
                }
            )
        except Exception:
            continue
    if len(candles) < max(20, min(50, int(limit) // 4)):
        logger.debug(
            "MARKET_DATA_STABILITY_SHORT_CANDLES pair=%s candles=%d limit=%s",
            pair,
            len(candles),
            limit,
        )
    if not candles:
        return None
    return {"symbol": pair, "timeframe": timeframe, "candles": candles}


def _install_kraken_market_data_patch() -> None:
    try:
        from bot import broker_integration as bi  # type: ignore
    except Exception:
        import broker_integration as bi  # type: ignore

    KrakenBrokerAdapter = getattr(bi, "KrakenBrokerAdapter", None)
    if KrakenBrokerAdapter is None:
        raise RuntimeError("KrakenBrokerAdapter not found")

    if getattr(KrakenBrokerAdapter, "_NIJA_MARKET_DATA_STABILITY_PATCHED", False):
        return

    original = getattr(KrakenBrokerAdapter, "get_market_data", None)
    _ORIGINALS["KrakenBrokerAdapter.get_market_data"] = original

    def stable_get_market_data(self: Any, symbol: str, timeframe: str = "5m", limit: int = 100) -> Optional[Dict[str, Any]]:
        skip, reason = _should_skip_symbol(symbol)
        if skip:
            logger.info("MARKET_DATA_STABILITY_SKIP symbol=%s reason=%s", symbol, reason)
            return None

        try:
            limit_i = max(50, min(int(limit or 100), int(os.getenv("NIJA_MARKET_DATA_MAX_CANDLES", "200"))))
        except Exception:
            limit_i = 100
        cache_ttl = float(os.getenv("NIJA_MARKET_DATA_CACHE_TTL_S", "20"))
        cache_key = (str(symbol).upper(), str(timeframe).lower(), limit_i)
        now = time.time()
        with _CACHE_LOCK:
            cached = _CACHE.get(cache_key)
            if cached and now - cached[0] <= cache_ttl:
                logger.debug("MARKET_DATA_STABILITY_CACHE_HIT symbol=%s timeframe=%s", symbol, timeframe)
                return cached[1]

        if not _INFLIGHT.acquire(blocking=False):
            logger.warning("MARKET_DATA_STABILITY_BACKPRESSURE symbol=%s timeframe=%s", symbol, timeframe)
            return None

        try:
            api = getattr(self, "api", None)
            if api is not None and hasattr(api, "query_public"):
                interval_map = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240, "1d": 1440}
                interval = interval_map.get(str(timeframe).lower(), 5)
                pair = _normalize_for_kraken_candles(symbol)
                try:
                    result = api.query_public("OHLC", {"pair": pair, "interval": interval})
                    parsed = _parse_kraken_ohlc(result, pair, timeframe, limit_i)
                    if parsed:
                        with _CACHE_LOCK:
                            _CACHE[cache_key] = (time.time(), parsed)
                        logger.info(
                            "MARKET_DATA_STABILITY_PUBLIC_OHLC_OK symbol=%s pair=%s candles=%d",
                            symbol,
                            pair,
                            len(parsed.get("candles", [])),
                        )
                        return parsed
                except Exception as exc:
                    logger.warning("MARKET_DATA_STABILITY_PUBLIC_OHLC_FAILED symbol=%s err=%s", symbol, exc)

            # Fallback to original method only if explicitly allowed.  Default is off
            # because the original pykrakenapi path creates lingering timeout threads.
            if original is not None and _truthy("NIJA_MARKET_DATA_ALLOW_PYKRAKEN_FALLBACK", "false"):
                return original(self, symbol, timeframe, limit_i)
            return None
        finally:
            try:
                _INFLIGHT.release()
            except Exception:
                pass

    setattr(KrakenBrokerAdapter, "get_market_data", stable_get_market_data)
    setattr(KrakenBrokerAdapter, "_NIJA_MARKET_DATA_STABILITY_PATCHED", True)
    logger.warning("MARKET_DATA_STABILITY_KRAKEN_PATCHED")


def install_import_hook() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    os.environ.setdefault("NIJA_MARKET_DATA_STABILITY_PATCH", "true")
    os.environ.setdefault("NIJA_MARKET_DATA_MAX_CONCURRENCY", "3")
    os.environ.setdefault("NIJA_MARKET_DATA_CACHE_TTL_S", "20")
    os.environ.setdefault("NIJA_MARKET_DATA_MAP_USDC_TO_USD", "true")
    os.environ.setdefault("NIJA_MARKET_DATA_ALLOW_PYKRAKEN_FALLBACK", "false")
    os.environ.setdefault("NIJA_KRAKEN_OHLC_TIMEOUT", "6")
    os.environ.setdefault("NIJA_CANDLE_FETCH_TIMEOUT", "6")

    try:
        _install_kraken_market_data_patch()
    except Exception as exc:
        logger.warning("MARKET_DATA_STABILITY_INSTALL_DEFERRED err=%s", exc)

    logger.warning("MARKET_DATA_STABILITY_IMPORT_HOOK_INSTALLED")


try:
    install_import_hook()
except Exception as exc:  # pragma: no cover
    logger.warning("MARKET_DATA_STABILITY_IMPORT_FAILED err=%s", exc)
