"""Runtime hardening for NIJA's optional OKX broker.

This module deliberately avoids changing Kraken/Coinbase execution. It patches
only the optional OKX direct REST client/broker so OKX can be enabled without
SDK/candlelite dependency issues and without invalid USD/USDT/USDC instrument
requests.

2026-07-03z: fixes the observed OKX Phase 3 blocker where merged-symbol scans
created malformed instruments such as ADA-USDTC and kept retrying OKX 51001
"instrument does not exist" responses. The patch now:
- repairs USDTT -> USDT and USDTC -> USDC deterministically,
- exposes OKX listed symbols to the Phase 3 broker-aware scanner,
- caches 51001 invalid instruments for the session, and
- bypasses legacy OKX market-data methods that blindly replace "-USD" inside
  "-USDC".
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import time
from typing import Any, Dict, Optional
from urllib.parse import urlencode

logger = logging.getLogger("nija.broker")

_TRUTHY = {"1", "true", "yes", "y", "on"}
_CASH_CURRENCIES = {"USD", "USDT", "USDC"}
_VALID_STABLE_QUOTES = ("USDT", "USDC", "USD")
_SYNTHETIC_CASH_PAIRS = {"USD-USDT", "USDT-USD", "USDC-USDT", "USDT-USDC", "USD-USDC", "USDC-USD"}
_INVALID_OKX_INST_IDS: set[str] = set()
_PRODUCT_CACHE: dict[str, Any] = {"loaded_at": 0.0, "symbols": set()}


def _env_truthy(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() in _TRUTHY


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return default


def _clean_symbol(symbol: Any) -> str:
    raw = str(symbol or "").upper().strip().replace("/", "-").replace("_", "-").replace(":", "-")
    raw = re.sub(r"[^A-Z0-9\-]", "", raw)
    while "--" in raw:
        raw = raw.replace("--", "-")
    return raw


def _normalize_okx_inst_id(symbol: Any) -> str:
    """Convert NIJA/Coinbase/Kraken-style symbols into valid OKX spot instIds."""
    raw = _clean_symbol(symbol)
    if not raw:
        return raw

    # Explicit repairs for prior bad normalizers.
    if raw.endswith("-USDTT"):
        raw = raw[:-6] + "-USDT"
    elif raw.endswith("-USDTC"):
        raw = raw[:-6] + "-USDC"
    elif raw.endswith("USDTT") and "-" not in raw:
        raw = raw[:-5] + "USDT"
    elif raw.endswith("USDTC") and "-" not in raw:
        raw = raw[:-5] + "USDC"

    if raw in _SYNTHETIC_CASH_PAIRS:
        return raw

    if "-" in raw:
        base, quote = raw.rsplit("-", 1)
        if not base:
            return raw
        if quote == "USD":
            return f"{base}-USDT"
        if quote in {"USDT", "USDC"}:
            return f"{base}-{quote}"
        return raw

    for quote in sorted(_VALID_STABLE_QUOTES, key=len, reverse=True):
        if raw.endswith(quote) and len(raw) > len(quote):
            base = raw[: -len(quote)]
            return f"{base}-USDT" if quote == "USD" else f"{base}-{quote}"
    return raw


def _extract_inst_ids(payload: Any) -> set[str]:
    products: set[str] = set()
    if payload is None:
        return products
    if isinstance(payload, dict):
        if "data" in payload:
            products.update(_extract_inst_ids(payload.get("data")))
        for key, value in payload.items():
            if str(key).lower() in {"instid", "symbol", "id", "name", "pair"}:
                inst = _normalize_okx_inst_id(value)
                if inst.endswith(("-USDT", "-USDC")):
                    products.add(inst)
            elif isinstance(value, (dict, list, tuple, set, frozenset)):
                products.update(_extract_inst_ids(value))
        return products
    if isinstance(payload, (list, tuple, set, frozenset)):
        for item in payload:
            if isinstance(item, str):
                inst = _normalize_okx_inst_id(item)
                if inst.endswith(("-USDT", "-USDC")):
                    products.add(inst)
            else:
                products.update(_extract_inst_ids(item))
    return products


def _load_okx_products_from_rest(rest_client: Any) -> set[str]:
    now = time.time()
    cached = _PRODUCT_CACHE.get("symbols")
    if isinstance(cached, set) and cached and now - float(_PRODUCT_CACHE.get("loaded_at", 0.0) or 0.0) < 1800:
        return set(cached)

    products: set[str] = set()
    try:
        result = rest_client._request("GET", "/api/v5/public/instruments", params={"instType": "SPOT"})
        if result and result.get("code") == "0":
            products.update(_extract_inst_ids(result.get("data", [])))
    except Exception as exc:
        logger.debug("OKX product cache load failed: %s", exc)

    if products:
        _PRODUCT_CACHE["loaded_at"] = now
        _PRODUCT_CACHE["symbols"] = set(products)
        logger.info("OKX_PRODUCT_CACHE_LOADED marker=20260703z count=%d", len(products))
    return products


def _is_invalid_or_synthetic(inst: str) -> bool:
    return inst in _SYNTHETIC_CASH_PAIRS or inst in _INVALID_OKX_INST_IDS


def _normalize_okx_params(path: str, params: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    clean = {k: v for k, v in (params or {}).items() if v is not None}
    if "instId" in clean:
        before = str(clean.get("instId") or "")
        after = _normalize_okx_inst_id(before)
        if after != before:
            logger.warning("OKX_INSTID_NORMALIZED marker=20260703z before=%s after=%s path=%s", before, after, path)
            print(f"[NIJA-PRINT] OKX_INSTID_NORMALIZED marker=20260703z before={before} after={after}", flush=True)
        clean["instId"] = after
    return clean


def _okx_auth_hint(code: str, status: int) -> Optional[str]:
    hints = {
        "50100": "API key invalid or unavailable — verify OKX_API_KEY is copied exactly and belongs to the selected OKX environment.",
        "50101": "API key missing — verify OKX_API_KEY is configured in the deployment environment.",
        "50102": "Request timestamp expired — check Railway/container clock and UTC timestamp generation.",
        "50110": "IP whitelist mismatch — add the deployment egress IP to the OKX API key whitelist or remove the whitelist.",
        "50111": "Invalid API key — key may be deleted, disabled, or from the wrong live/demo environment.",
        "50112": "Invalid passphrase — OKX_API_PASSPHRASE/OKX_PASSPHRASE does not match the API key passphrase.",
        "50113": "Invalid signature — check OKX_API_SECRET, request path, body, timestamp, and HMAC-SHA256 signing.",
        "50114": "Timestamp outside allowed window — ensure the system clock is accurate and timestamp is UTC milliseconds.",
        "50119": "API key does not exist in this OKX environment — verify the key exists on OKX API Management and matches live/demo mode.",
        "51001": "Invalid OKX instrument. NIJA caches this instrument and skips it for the rest of the process.",
    }
    if code in hints:
        return hints[code]
    if status in (401, 403):
        return "OKX auth rejected the request — likely wrong live/demo mode, invalid key/passphrase/secret, IP whitelist mismatch, expired/disabled key, or timestamp/signature mismatch."
    return None


def _candles_payload_to_rows(result: Any) -> list[dict[str, float]]:
    data = (result or {}).get("data") or []
    rows: list[dict[str, float]] = []
    for candle in reversed(list(data)):
        try:
            rows.append({
                "timestamp": int(float(candle[0])),
                "open": float(candle[1]),
                "high": float(candle[2]),
                "low": float(candle[3]),
                "close": float(candle[4]),
                "volume": float(candle[5]),
            })
        except Exception:
            continue
    return rows


def apply_okx_runtime_patches() -> bool:
    """Patch OKX REST and broker classes when available."""
    import sys

    bm = sys.modules.get("bot.broker_manager") or sys.modules.get("broker_manager")
    if bm is None:
        return False
    if getattr(bm, "_NIJA_OKX_RUNTIME_PATCHED_V20260703Z", False):
        return True

    rest_cls = getattr(bm, "_OKXRestClient", None)
    okx_cls = getattr(bm, "OKXBroker", None) or getattr(bm, "OKXBrokerAdapter", None)
    if rest_cls is None or okx_cls is None:
        return False

    def _headers(self: Any, timestamp: str, method: str, request_path: str, body: str, *, private: bool) -> Dict[str, str]:
        if private:
            prehash = timestamp + method.upper() + request_path + body
            signature = base64.b64encode(
                hmac.new(self.api_secret.encode("utf-8"), prehash.encode("utf-8"), hashlib.sha256).digest()
            ).decode("utf-8")
            logger.warning("OKX_AUTH_DETAIL timestamp=%s prehash=%r signing_algo=Base64-HMAC-SHA256 signature_len=%s", timestamp, prehash, len(signature))
            headers: Dict[str, str] = {
                "OK-ACCESS-KEY": self.api_key,
                "OK-ACCESS-SIGN": signature,
                "OK-ACCESS-TIMESTAMP": timestamp,
                "OK-ACCESS-PASSPHRASE": self.passphrase,
                "Content-Type": "application/json",
            }
        else:
            headers = {"Content-Type": "application/json"}
        _sim_active = bool(getattr(self, "simulated", False)) or _env_truthy("OKX_SIMULATED_TRADING") or _env_truthy("OKX_USE_TESTNET")
        if _sim_active:
            headers["x-simulated-trading"] = "1"
        logger.warning("OKX_HEADERS_DIAG simulated_instance=%s simulated_header_sent=%s headers_keys=%s", bool(getattr(self, "simulated", False)), _sim_active, list(headers.keys()))
        return headers

    def _request(self: Any, method: str, path: str, *, params: Optional[Dict[str, Any]] = None, payload: Optional[Dict[str, Any]] = None, private: bool = False) -> Dict[str, Any]:
        method = method.upper()
        clean_params = _normalize_okx_params(path, params)
        inst = str(clean_params.get("instId", "")).upper()
        is_market_data = path in {"/api/v5/market/candles", "/api/v5/market/ticker"}

        if is_market_data and _is_invalid_or_synthetic(inst):
            logger.warning("OKX_INVALID_INSTRUMENT_CACHE_SKIP marker=20260703z instId=%s path=%s", inst, path)
            return {"code": "0", "msg": "invalid_or_synthetic_instrument_cached_skip", "data": []}

        query = "?" + urlencode(clean_params) if clean_params else ""
        request_path = f"{path}{query}"
        body = "" if method == "GET" or not payload else json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        ts = self._timestamp()
        simulated = bool(getattr(self, "simulated", False)) or _env_truthy("OKX_SIMULATED_TRADING") or _env_truthy("OKX_USE_TESTNET")

        logger.warning("OKX_REQUEST_DIAG method=%s path=%s base_url=%s simulated_instance=%s simulated_active=%s key_present=%s passphrase_present=%s timestamp=%s body_empty=%s", method, request_path, self.BASE_URL, bool(getattr(self, "simulated", False)), simulated, bool(getattr(self, "api_key", "")), bool(getattr(self, "passphrase", "")), ts, body == "")

        request_headers = self._headers(ts, method, request_path, body, private=private)
        response = self.session.request(method, f"{self.BASE_URL}{request_path}", data=body if body else None, headers=request_headers, timeout=self.timeout)
        logger.warning("OKX_RESPONSE_DIAG status=%s method=%s path=%s response_body=%s", response.status_code, method, request_path, response.text)

        try:
            parsed = response.json()
        except ValueError:
            parsed = {"code": f"HTTP_{response.status_code}", "msg": response.text or "Non-JSON OKX response"}

        okx_code = str(parsed.get("code", "0"))
        if (not response.ok) or okx_code not in {"0", ""}:
            okx_msg = str(parsed.get("msg", ""))
            if is_market_data and okx_code == "51001" and inst:
                _INVALID_OKX_INST_IDS.add(inst)
                logger.warning("OKX_INVALID_INSTRUMENT_CACHED marker=20260703z instId=%s path=%s cache_size=%d", inst, path, len(_INVALID_OKX_INST_IDS))
            log_fn = logger.error if not response.ok else logger.warning
            log_fn("OKX_REQUEST_FAILED status=%s method=%s path=%s okx_code=%s okx_msg=%s response_body=%s", response.status_code, method, request_path, okx_code, okx_msg, response.text)
            hint = _okx_auth_hint(okx_code, response.status_code)
            if hint:
                log_fn("OKX_HINT %s", hint)
            parsed.setdefault("http_status", response.status_code)
            parsed.setdefault("request_path", request_path)
        return parsed

    def get_ticker(self: Any, instId: str) -> Dict[str, Any]:
        normalized = _normalize_okx_inst_id(instId)
        if _is_invalid_or_synthetic(normalized):
            logger.warning("OKX_CASH_OR_INVALID_TICKER_SKIPPED marker=20260703z instId=%s", normalized)
            return {"code": "0", "msg": "cash_or_invalid_ticker_skipped", "data": []}
        return self._request("GET", "/api/v5/market/ticker", params={"instId": normalized})

    original_get_account_balance = getattr(okx_cls, "get_account_balance")
    original_get_positions = getattr(okx_cls, "get_positions")
    original_get_current_price = getattr(okx_cls, "get_current_price", None)

    def get_positions(self: Any) -> list[Dict[str, Any]]:
        try:
            if not getattr(self, "account_api", None):
                return []
            result = self.account_api.get_balance()
            if not (result and result.get("code") == "0"):
                return []
            data = result.get("data", [])
            if not data:
                return []
            details = data[0].get("details", [])
            raw_holdings: list[tuple[str, float, str]] = []
            for detail in details:
                ccy = str(detail.get("ccy") or "").upper().strip()
                amount = max(_safe_float(detail.get("availBal", 0)), _safe_float(detail.get("cashBal", 0)))
                if not ccy or ccy in _CASH_CURRENCIES or amount <= 0:
                    continue
                raw_holdings.append((ccy, amount, f"{ccy}-USDT"))
            positions = []
            for ccy, amount, okx_symbol in raw_holdings:
                current_price = self.get_current_price(okx_symbol) or 0.0
                positions.append({"symbol": okx_symbol, "quantity": amount, "currency": ccy, "current_price": current_price, "size_usd": amount * current_price if current_price > 0 else 0.0})
            return positions
        except Exception as exc:
            logger.error("Error fetching OKX positions: %s", exc)
            try:
                return original_get_positions(self)
            except Exception:
                return []

    def get_account_balance(self: Any, verbose: bool = True) -> float:
        if not getattr(self, "account_api", None):
            last_known = getattr(self, "_last_known_balance", None)
            if last_known is not None:
                return float(last_known)
            setattr(self, "_is_available", False)
            return 0.0
        try:
            result = self.account_api.get_balance()
            if result and result.get("code") == "0":
                data = result.get("data", [])
                if not data:
                    return 0.0
                root = data[0]
                details = root.get("details", [])
                usd_available = usdt_available = usdc_available = noncash_position_value = 0.0
                for detail in details:
                    ccy = str(detail.get("ccy") or "").upper().strip()
                    amount = max(_safe_float(detail.get("availBal", 0)), _safe_float(detail.get("cashBal", 0)), _safe_float(detail.get("eqUsd", 0)))
                    eq_usd = _safe_float(detail.get("eqUsd", 0))
                    if ccy == "USD":
                        usd_available += amount
                    elif ccy == "USDT":
                        usdt_available += amount
                    elif ccy == "USDC":
                        usdc_available += amount
                    elif amount > 0:
                        noncash_position_value += eq_usd if eq_usd > 0 else 0.0
                total_eq = _safe_float(root.get("totalEq", 0))
                total_equity = total_eq if total_eq > 0 else (usd_available + usdt_available + usdc_available + noncash_position_value)
                setattr(self, "_last_known_balance", total_equity)
                setattr(self, "_balance_fetch_errors", 0)
                setattr(self, "_is_available", True)
                return total_equity
            return original_get_account_balance(self, verbose=verbose)
        except TypeError:
            return original_get_account_balance(self)
        except Exception as exc:
            logger.error("OKX patched balance fetch failed: %s", exc)
            try:
                return original_get_account_balance(self, verbose=verbose)
            except TypeError:
                return original_get_account_balance(self)

    def get_tradeable_pairs(self: Any) -> list[str]:
        rest = getattr(self, "market_api", None) or getattr(self, "account_api", None)
        products = _load_okx_products_from_rest(rest) if rest is not None else set()
        return sorted(products)

    def get_available_markets(self: Any) -> list[str]:
        return get_tradeable_pairs(self)

    def is_listed_symbol(self: Any, symbol: Any) -> bool:
        inst = _normalize_okx_inst_id(symbol)
        products = set(get_tradeable_pairs(self))
        return bool(inst and (not products or inst in products) and inst not in _INVALID_OKX_INST_IDS)

    def _direct_get_candles(self: Any, symbol: Any, *args: Any, **kwargs: Any):
        normalized = _normalize_okx_inst_id(symbol)
        if normalized != str(symbol):
            logger.warning("OKX_CANDLE_SYMBOL_NORMALIZED marker=20260703z before=%s after=%s", symbol, normalized)
        if _is_invalid_or_synthetic(normalized):
            logger.warning("OKX_CANDLE_SYMBOL_SKIPPED marker=20260703z instId=%s reason=invalid_or_synthetic", normalized)
            return None

        rest = getattr(self, "market_api", None) or getattr(self, "account_api", None)
        if rest is None:
            return None

        products = _load_okx_products_from_rest(rest)
        if products and normalized not in products:
            _INVALID_OKX_INST_IDS.add(normalized)
            logger.warning("OKX_CANDLE_SYMBOL_SKIPPED marker=20260703z instId=%s reason=not_listed products=%d", normalized, len(products))
            return None

        timeframe = kwargs.get("timeframe") or kwargs.get("bar") or (args[0] if args else "1m")
        if isinstance(timeframe, (int, float)):
            timeframe = "1m"
        tf = str(timeframe or "1m").lower()
        timeframe_map = {"1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m", "30m": "30m", "1h": "1H", "4h": "4H", "1d": "1D"}
        bar = timeframe_map.get(tf, str(timeframe or "1m"))
        limit_raw = kwargs.get("limit") or (args[1] if len(args) > 1 else 100)
        try:
            limit = max(1, min(int(float(limit_raw)), 300))
        except Exception:
            limit = 100

        result = rest.get_candles(instId=normalized, bar=bar, limit=str(limit))
        if not result or result.get("code") != "0":
            if str((result or {}).get("code", "")) == "51001":
                _INVALID_OKX_INST_IDS.add(normalized)
            return None
        rows = _candles_payload_to_rows(result)
        if not rows:
            return None
        return rows

    def get_candles(self: Any, symbol: Any, *args: Any, **kwargs: Any):
        return _direct_get_candles(self, symbol, *args, **kwargs)

    def get_market_data(self: Any, symbol: Any, *args: Any, **kwargs: Any):
        rows = _direct_get_candles(self, symbol, *args, **kwargs)
        normalized = _normalize_okx_inst_id(symbol)
        if rows is None:
            return None
        return {"symbol": normalized, "timeframe": str(kwargs.get("timeframe") or (args[0] if args else "1m")), "candles": rows}

    def get_current_price(self: Any, symbol: Any, *args: Any, **kwargs: Any):
        normalized = _normalize_okx_inst_id(symbol)
        if _is_invalid_or_synthetic(normalized):
            return 0.0
        if callable(original_get_current_price):
            try:
                price = original_get_current_price(self, normalized, *args, **kwargs)
                if _safe_float(price, 0.0) > 0:
                    return price
            except Exception:
                pass
        try:
            ticker = self.market_api.get_ticker(normalized) if getattr(self, "market_api", None) else None
            data = (ticker or {}).get("data") or []
            if data:
                return _safe_float(data[0].get("last"), 0.0)
        except Exception:
            pass
        return 0.0

    rest_cls._headers = _headers
    rest_cls._request = _request
    rest_cls.get_ticker = get_ticker
    okx_cls.get_positions = get_positions
    okx_cls.get_account_balance = get_account_balance
    okx_cls.get_candles = get_candles
    okx_cls.get_market_data = get_market_data
    okx_cls.get_current_price = get_current_price
    okx_cls.get_tradeable_pairs = get_tradeable_pairs
    okx_cls.get_available_markets = get_available_markets
    okx_cls.is_listed_symbol = is_listed_symbol
    okx_cls.normalize_symbol = staticmethod(_normalize_okx_inst_id)
    bm._NIJA_OKX_RUNTIME_PATCHED = True
    bm._NIJA_OKX_RUNTIME_PATCHED_V20260703E = True
    bm._NIJA_OKX_RUNTIME_PATCHED_V20260703Z = True
    logger.warning("✅ OKX runtime patch applied marker=20260703z: USDTC repair, listed-symbol cache, 51001 invalid-instrument quarantine")
    print("[NIJA-PRINT] OKX_RUNTIME_PATCHED marker=20260703z", flush=True)
    return True


def install_import_hook() -> None:
    """Install a one-shot import hook that patches broker_manager after import."""
    import builtins
    import sys

    bm = sys.modules.get("bot.broker_manager") or sys.modules.get("broker_manager")
    if bm is not None and getattr(bm, "_NIJA_OKX_RUNTIME_PATCHED_V20260703Z", False):
        return

    if getattr(builtins, "_NIJA_OKX_IMPORT_HOOK_INSTALLED", False):
        apply_okx_runtime_patches()
        return

    original_import = builtins.__import__

    def guarded_import(name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0) -> Any:
        module = original_import(name, globals, locals, fromlist, level)
        target_loaded = name in {"bot.broker_manager", "broker_manager"} or name.endswith(".broker_manager")
        if target_loaded:
            try:
                if apply_okx_runtime_patches():
                    builtins.__import__ = original_import
                    setattr(builtins, "_NIJA_OKX_IMPORT_HOOK_INSTALLED", False)
            except Exception as exc:
                logging.getLogger("nija.broker").warning("OKX runtime patch hook failed: %s", exc)
        return module

    builtins.__import__ = guarded_import
    setattr(builtins, "_NIJA_OKX_IMPORT_HOOK_INSTALLED", True)
    apply_okx_runtime_patches()
