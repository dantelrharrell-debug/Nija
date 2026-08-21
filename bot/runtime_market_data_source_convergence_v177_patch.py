"""Runtime market-data source convergence v177.

Production evidence showed the live core loop receiving a ``KrakenBroker`` while
Phase 3 still produced Coinbase candle timeouts and 0/30 usable frames.  v171
bounded the work, but the stability patch targeted ``KrakenBrokerAdapter`` while
the multi-account runtime uses ``broker_manager.KrakenBroker``.

v177 patches the canonical core-loop fetch surface instead of changing execution
routing.  For a live Kraken broker it tries Kraken's public OHLC endpoint first,
returns a normalized pandas DataFrame when at least the shared 50-candle minimum
is available, and otherwise falls back to the already-installed fetch chain.
The direct read is public, bounded, cached, and has no nonce/order side effects.
Unknown Kraken pairs fail back to the existing broker logic; no signal, risk,
capital, or order gate is relaxed.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
import time
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.runtime_market_data_source_convergence_v177")
MARKER = "20260821-runtime-market-data-source-convergence-v177"
RELEASE_ID = "20260821-runtime-convergence-v177"
_READY_FLAG = "NIJA_RUNTIME_MARKET_DATA_SOURCE_CONVERGENCE_V177_READY"
_PATCH_ATTR = "_nija_runtime_market_data_source_convergence_v177"
_LOCK = threading.RLock()
_CACHE_LOCK = threading.RLock()
_CACHE: dict[tuple[str, str], tuple[float, Any]] = {}
_MIN_CANDLES = 50


def _broker_name(broker: Any) -> str:
    for attr in ("broker_type", "name", "broker_name", "exchange", "exchange_name"):
        try:
            value = getattr(broker, attr, None)
            raw = getattr(value, "value", value)
            text = str(raw or "").strip().lower()
            if "kraken" in text:
                return "kraken"
        except Exception:
            pass
    return "kraken" if "kraken" in type(broker).__name__.lower() else "unknown"


def _normalize_symbol(symbol: Any) -> str:
    raw = str(symbol or "").strip().upper().replace("/", "-").replace("_", "-")
    if "-" in raw:
        base, quote = raw.rsplit("-", 1)
    else:
        quote = ""
        for candidate in ("USDT", "USDC", "USD", "EUR"):
            if raw.endswith(candidate) and len(raw) > len(candidate):
                base, quote = raw[: -len(candidate)], candidate
                break
        else:
            return ""
    if quote == "USDC" and str(os.environ.get("NIJA_MARKET_DATA_MAP_USDC_TO_USD", "true")).lower() in {"1", "true", "yes", "on"}:
        quote = "USD"
    if base == "BTC":
        base = "XBT"
    if quote not in {"USD", "USDT", "EUR"}:
        return ""
    return f"{base}{quote}"


def _public_kraken_frame(symbol: Any, timeframe: str = "5m") -> Any:
    pair = _normalize_symbol(symbol)
    if not pair:
        return None
    cache_ttl = max(1.0, float(os.environ.get("NIJA_V177_OHLC_CACHE_TTL_S", "20") or 20))
    key = (pair, str(timeframe or "5m").lower())
    now = time.time()
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
        if cached and now - cached[0] <= cache_ttl:
            return cached[1]

    try:
        requests = importlib.import_module("requests")
        pd = importlib.import_module("pandas")
    except Exception:
        return None

    interval_map = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240, "1d": 1440}
    interval = interval_map.get(key[1], 5)
    timeout_s = max(1.0, min(8.0, float(os.environ.get("NIJA_V177_KRAKEN_PUBLIC_TIMEOUT_S", "4") or 4)))
    try:
        response = requests.get(
            "https://api.kraken.com/0/public/OHLC",
            params={"pair": pair, "interval": interval},
            timeout=timeout_s,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or payload.get("error"):
            return None
        result = payload.get("result") or {}
        rows = next((value for name, value in result.items() if name != "last" and isinstance(value, list)), None)
        if not rows:
            return None
        rows = rows[-200:]
        normalized = []
        for row in rows:
            try:
                normalized.append(
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
        if len(normalized) < _MIN_CANDLES:
            return None
        frame = pd.DataFrame(normalized)
        if len(frame) < _MIN_CANDLES or "volume" not in frame.columns:
            return None
        with _CACHE_LOCK:
            _CACHE[key] = (time.time(), frame)
        LOGGER.info(
            "MARKET_DATA_V177_KRAKEN_PUBLIC_OK marker=%s symbol=%s pair=%s rows=%d timeout_s=%.1f",
            MARKER,
            symbol,
            pair,
            len(frame),
            timeout_s,
        )
        return frame
    except Exception as exc:
        LOGGER.debug(
            "MARKET_DATA_V177_KRAKEN_PUBLIC_MISS marker=%s symbol=%s pair=%s error=%s:%s",
            MARKER,
            symbol,
            pair,
            type(exc).__name__,
            exc,
        )
        return None


def _patch_core_loop() -> bool:
    try:
        core = importlib.import_module("bot.nija_core_loop")
        cls = getattr(core, "NijaCoreLoop", None)
        if not isinstance(cls, type):
            return False
        current = getattr(cls, "_fetch_df", None)
        if not callable(current):
            return False
        if bool(getattr(current, _PATCH_ATTR, False)):
            return True
        original = current

        @wraps(original)
        def fetch_df_v177(self: Any, broker: Any, symbol: Any, *args: Any, **kwargs: Any):
            if _broker_name(broker) == "kraken":
                timeframe = str(kwargs.get("timeframe") or "5m")
                frame = _public_kraken_frame(symbol, timeframe)
                if frame is not None:
                    try:
                        if len(frame) >= _MIN_CANDLES:
                            return frame
                    except Exception:
                        pass
            return original(self, broker, symbol, *args, **kwargs)

        setattr(fetch_df_v177, _PATCH_ATTR, True)
        setattr(fetch_df_v177, "__wrapped__", original)
        cls._fetch_df = fetch_df_v177
        return True
    except Exception:
        return False


def _patch_release_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_market_data_source_convergence_v177"] = _READY_FLAG
        return True
    except Exception:
        return False


def install() -> bool:
    with _LOCK:
        os.environ.setdefault("NIJA_V177_KRAKEN_PUBLIC_TIMEOUT_S", "4")
        os.environ.setdefault("NIJA_V177_OHLC_CACHE_TTL_S", "20")
        core_ok = _patch_core_loop()
        manifest_ok = _patch_release_manifest()
        ready = bool(core_ok and manifest_ok)
        os.environ[_READY_FLAG] = "1" if ready else "0"
        if not ready:
            LOGGER.critical(
                "RUNTIME_MARKET_DATA_SOURCE_CONVERGENCE_V177_FAILED marker=%s core_ok=%s "
                "manifest_ok=%s trading_fail_closed=true",
                MARKER,
                str(core_ok).lower(),
                str(manifest_ok).lower(),
            )
            return False
        LOGGER.critical(
            "RUNTIME_MARKET_DATA_SOURCE_CONVERGENCE_V177 marker=%s ready=true "
            "live_kraken_public_ohlc_first=true min_candles=%d bounded_timeout=true cache=true "
            "execution_routing_unchanged=true signal_thresholds_unchanged=true forced_trade=false "
            "safety_gates_bypassed=false",
            MARKER,
            _MIN_CANDLES,
        )
        return True


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "RELEASE_ID",
    "install",
    "install_import_hook",
    "_broker_name",
    "_normalize_symbol",
    "_public_kraken_frame",
    "_patch_core_loop",
]
