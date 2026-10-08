"""NIJA v428 — isolated, public-only multi-venue market coverage observer.

This module intentionally imports no NIJA trading module or authenticated SDK.
It runs inside Render's -S early liveness server, not the trading worker.
Its only network operation is bounded HTTPS GET to fixed exchange public hosts.
No account balances, credentials, orders, stop controls, or trade authority are read
or modified. Results describe QUOTE COVERAGE only, NOT profitable trade signals.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from typing import Any
from urllib.parse import quote
from urllib.request import Request, urlopen

MARKER = "20261008-public-market-observer-v428"
VENUES = ("kraken", "coinbase", "okx")
HOSTS = {
    "kraken": "https://api.kraken.com",
    "coinbase": "https://api.exchange.coinbase.com",
    "okx": "https://www.okx.com",
}
_SYMBOL = re.compile(r"^[A-Z0-9][A-Z0-9._-]{1,39}$")
_QUOTES = frozenset({"USD", "USDT", "USDC"})
_MAX_PAYLOAD_BYTES = 5_000_000
_COVERAGE_TTL_SECONDS = 86400.0


def _positive(value: Any) -> float:
    try:
        result = float(value or 0)
        return result if result > 0 and result < float("inf") else 0.0
    except (TypeError, ValueError, OverflowError):
        return 0.0


def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        return min(maximum, max(minimum, int(value)))
    except (TypeError, ValueError, OverflowError):
        return default


def _safe_symbol(value: Any) -> str:
    result = str(value or "").strip().upper()
    return result if _SYMBOL.fullmatch(result) else ""


def _http_json(url: str, timeout: float = 4.0) -> Any:
    """GET-only network boundary. Callers construct URLs from fixed hosts."""
    if not any(url.startswith(host + "/") for host in HOSTS.values()):
        raise ValueError("public_market_url_host_not_allowed")
    request = Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "NIJA-PublicMarketObserver/1.0"},
        method="GET",
    )
    with urlopen(request, timeout=min(5.0, max(1.0, timeout))) as response:
        payload = response.read(_MAX_PAYLOAD_BYTES + 1)
    if len(payload) > _MAX_PAYLOAD_BYTES:
        raise ValueError("public_market_payload_too_large")
    return json.loads(payload.decode("utf-8"))


def _catalog(venue: str, timeout: float) -> list[dict[str, str]]:
    """Retrieve eligible spot instruments; never consult trading account state."""
    if venue == "okx":
        data = _http_json(HOSTS[venue] + "/api/v5/public/instruments?instType=SPOT", timeout)
        if not isinstance(data, dict) or str(data.get("code", "")) != "0" or not isinstance(data.get("data"), list):
            raise ValueError("okx_public_catalog_unavailable")
        rows = []
        for item in data["data"]:
            if not isinstance(item, dict) or item.get("state") != "live":
                continue
            pair = _safe_symbol(item.get("instId"))
            quoted = str(item.get("quoteCcy") or "").upper()
            if pair and quoted in _QUOTES and pair.endswith("-" + quoted):
                rows.append({"symbol": pair, "pair": pair})
    elif venue == "coinbase":
        data = _http_json(HOSTS[venue] + "/products", timeout)
        if not isinstance(data, list):
            raise ValueError("coinbase_public_catalog_unavailable")
        rows = []
        for item in data:
            if not isinstance(item, dict) or item.get("status", "online") != "online":
                continue
            if any(item.get(flag) is True for flag in ("trading_disabled", "cancel_only", "limit_only", "post_only")):
                continue
            pair = _safe_symbol(item.get("id"))
            quoted = str(item.get("quote_currency") or "").upper()
            if pair and quoted in _QUOTES and pair.endswith("-" + quoted):
                rows.append({"symbol": pair, "pair": pair})
    elif venue == "kraken":
        data = _http_json(HOSTS[venue] + "/0/public/AssetPairs", timeout)
        if not isinstance(data, dict) or data.get("error") or not isinstance(data.get("result"), dict):
            raise ValueError("kraken_public_catalog_unavailable")
        rows = []
        for native, item in data["result"].items():
            if not isinstance(item, dict) or item.get("status", "online") != "online":
                continue
            pair = _safe_symbol(native)
            wsname = str(item.get("wsname") or "").upper()
            parts = wsname.split("/")
            if len(parts) != 2 or parts[1] not in _QUOTES or not pair or pair.endswith(".D"):
                continue
            base = _safe_symbol(parts[0])
            if base:
                rows.append({"symbol": base + "-" + parts[1], "pair": pair})
    else:
        raise ValueError("unsupported_public_market")
    by_symbol: dict[str, dict[str, str]] = {}
    for row in rows:
        by_symbol.setdefault(row["symbol"], row)
    return [by_symbol[key] for key in sorted(by_symbol)]


def _valid_quote(bid: Any, ask: Any, last: Any) -> dict[str, Any] | None:
    buy = _positive(ask)
    sell = _positive(bid)
    price = _positive(last)
    if not sell or not buy or buy < sell or not price:
        return None
    return {
        "last": price,
        "spread_bps": round((buy - sell) * 10000.0 / ((buy + sell) / 2.0), 3),
    }


def _check_window(venue: str, rows: list[dict[str, str]], timeout: float) -> dict[str, dict[str, Any]]:
    """Retrieve public quote quality; failure never counts as evaluated."""
    found: dict[str, dict[str, Any]] = {}
    if not rows:
        return found
    if venue == "okx":
        result = _http_json(HOSTS[venue] + "/api/v5/market/tickers?instType=SPOT", timeout)
        if not isinstance(result, dict) or str(result.get("code", "")) != "0" or not isinstance(result.get("data"), list):
            raise ValueError("okx_public_tickers_unavailable")
        selected = {row["pair"]: row["symbol"] for row in rows}
        for item in result["data"]:
            if not isinstance(item, dict):
                continue
            symbol = selected.get(str(item.get("instId") or "").upper())
            if symbol:
                validated = _valid_quote(item.get("bidPx"), item.get("askPx"), item.get("last"))
                if validated:
                    found[symbol] = validated
    elif venue == "kraken":
        selected = {row["pair"]: row["symbol"] for row in rows}
        pairs = ",".join(selected)
        result = _http_json(HOSTS[venue] + "/0/public/Ticker?pair=" + quote(pairs, safe=","), timeout)
        if not isinstance(result, dict) or result.get("error") or not isinstance(result.get("result"), dict):
            raise ValueError("kraken_public_tickers_unavailable")
        for native, item in result["result"].items():
            symbol = selected.get(str(native).upper())
            if not symbol or not isinstance(item, dict):
                continue
            bid, ask, last = item.get("b"), item.get("a"), item.get("c")
            validated = _valid_quote(
                bid[0] if isinstance(bid, list) and bid else bid,
                ask[0] if isinstance(ask, list) and ask else ask,
                last[0] if isinstance(last, list) and last else last,
            )
            if validated:
                found[symbol] = validated
    elif venue == "coinbase":
        for row in rows:
            # A failed public quote is recorded as unavailable, not a fabricated price.
            pair = row["pair"]
            try:
                result = _http_json(HOSTS[venue] + "/products/" + quote(pair, safe="-") + "/ticker", timeout)
                if not isinstance(result, dict):
                    continue
                validated = _valid_quote(result.get("bid"), result.get("ask"), result.get("price"))
                if validated:
                    found[row["symbol"]] = validated
            except (OSError, ValueError, TimeoutError):
                continue
    return found


class PublicMarketObserver:
    """Rotate public-only quote checks independently of trading readiness."""

    def __init__(self, *, max_symbols: int = 20, interval_s: int = 150, catalog_ttl_s: int = 900):
        self.max_symbols = _bounded_int(max_symbols, 20, 1, 20)
        self.interval_s = _bounded_int(interval_s, 150, 60, 900)
        self.catalog_ttl_s = _bounded_int(catalog_ttl_s, 900, 120, 3600)
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._catalogs: dict[str, list[dict[str, str]]] = {v: [] for v in VENUES}
        self._catalog_time: dict[str, float] = {v: 0.0 for v in VENUES}
        self._cursors: dict[str, int] = {v: 0 for v in VENUES}
        self._covered: dict[str, dict[str, float]] = {v: {} for v in VENUES}
        self._attempted: dict[str, dict[str, float]] = {v: {} for v in VENUES}
        self._summary: dict[str, Any] = {
            "status": "starting",
            "mode": "public_quote_quality_only_not_strategy",
            "orders_submitted": False,
            "broker_credentials_used": False,
            "trading_authority_unchanged": True,
            "interval_seconds": self.interval_s,
            "max_symbols_per_venue_per_cycle": self.max_symbols,
            "last_cycle_epoch": None,
            "venues": {},
        }

    def stop(self) -> None:
        self._stop.set()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return json.loads(json.dumps(self._summary))

    def poll_once(self) -> dict[str, Any]:
        """One bounded pass. Can be called from deterministic test fixtures."""
        now = time.time()
        snapshot: dict[str, Any] = {}
        for venue in VENUES:
            errors: list[str] = []
            rows = self._catalogs[venue]
            if not rows or now - self._catalog_time[venue] >= self.catalog_ttl_s:
                try:
                    latest = _catalog(venue, timeout=4.0)
                    if not latest:
                        raise ValueError("no_eligible_spot_symbols")
                    self._catalogs[venue] = latest
                    self._catalog_time[venue] = now
                    rows = latest
                    available_symbols = {row["symbol"] for row in latest}
                    self._covered[venue] = {
                        symbol: ts for symbol, ts in self._covered[venue].items()
                        if symbol in available_symbols and now - ts < _COVERAGE_TTL_SECONDS
                    }
                except (OSError, ValueError, TimeoutError) as exc:
                    errors.append("catalog:" + type(exc).__name__)
                    if now - self._catalog_time[venue] > 3600.0:
                        rows = []
            selected: list[dict[str, str]] = []
            if rows:
                cursor = self._cursors[venue] % len(rows)
                selected = [rows[(cursor + offset) % len(rows)] for offset in range(min(self.max_symbols, len(rows)))]
                self._cursors[venue] = (cursor + len(selected)) % len(rows)
            verified: dict[str, dict[str, Any]] = {}
            if selected:
                for row in selected:
                    self._attempted[venue][row["symbol"]] = now
                try:
                    verified = _check_window(venue, selected, timeout=4.0)
                except (OSError, ValueError, TimeoutError) as exc:
                    errors.append("quote:" + type(exc).__name__)
                for symbol in verified:
                    self._covered[venue][symbol] = now
            self._covered[venue] = {
                symbol: ts for symbol, ts in self._covered[venue].items()
                if now - ts < _COVERAGE_TTL_SECONDS
            }
            self._attempted[venue] = {
                symbol: ts for symbol, ts in self._attempted[venue].items()
                if now - ts < _COVERAGE_TTL_SECONDS
            }
            total = len(rows)
            coverage = len(self._covered[venue])
            snapshot[venue] = {
                "catalog_count": total,
                "catalog_fresh": bool(total and now - self._catalog_time[venue] <= self.catalog_ttl_s),
                "window_attempted": len(selected),
                "quotes_verified_this_cycle": len(verified),
                "unique_quotes_verified_24h": coverage,
                "unique_attempted_24h": len(self._attempted[venue]),
                "coverage_pct_24h": round(100.0 * coverage / total, 2) if total else 0.0,
                "next_cursor": self._cursors[venue],
                "errors": errors,
            }
            print(
                f"PUBLIC_MARKET_OBSERVER_V428_CYCLE marker={MARKER} venue={venue} "
                f"catalog={total} attempted={len(selected)} quotes_verified={len(verified)} "
                f"covered_24h={coverage} coverage_pct={snapshot[venue]['coverage_pct_24h']} "
                f"errors={','.join(errors) or 'none'} "
                "orders_submitted=false broker_credentials_used=false trading_authority_unchanged=true",
                flush=True,
            )
        summary = {
            "status": "running" if any(v["quotes_verified_this_cycle"] for v in snapshot.values()) else "degraded",
            "mode": "public_quote_quality_only_not_strategy",
            "orders_submitted": False,
            "broker_credentials_used": False,
            "trading_authority_unchanged": True,
            "interval_seconds": self.interval_s,
            "max_symbols_per_venue_per_cycle": self.max_symbols,
            "last_cycle_epoch": now,
            "venues": snapshot,
        }
        with self._lock:
            self._summary = summary
        return self.snapshot()

    def run(self) -> None:
        while not self._stop.is_set():
            try:
                self.poll_once()
            except Exception as exc:
                print(
                    f"PUBLIC_MARKET_OBSERVER_V428_ERROR type={type(exc).__name__} "
                    "orders_submitted=false trading_authority_unchanged=true",
                    flush=True,
                )
            self._stop.wait(self.interval_s)


def start_from_liveness() -> PublicMarketObserver | None:
    """Explicit opt-in; caller holds reference for /market-observerz metrics."""
    if str(os.environ.get("NIJA_PUBLIC_MARKET_OBSERVER_ENABLED", "false")).strip().lower() not in {
        "1", "true", "yes", "on"
    }:
        return None
    observer = PublicMarketObserver(
        max_symbols=_bounded_int(os.environ.get("NIJA_PUBLIC_MARKET_SCAN_WINDOW"), 20, 1, 20),
        interval_s=_bounded_int(os.environ.get("NIJA_PUBLIC_MARKET_SCAN_INTERVAL_S"), 150, 60, 900),
    )
    threading.Thread(target=observer.run, name="nija-public-market-observer", daemon=True).start()
    return observer
