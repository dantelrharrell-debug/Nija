"""Runtime hardening for NIJA's optional OKX broker.

This module deliberately avoids changing Kraken/Coinbase execution. It patches
only the optional OKX direct REST client/broker so OKX can be enabled without
SDK/candlelite dependency issues and without invalid USD-USDT startup probes.

2026-07-03d: also normalizes NIJA's USD-style merged symbol universe into valid
OKX spot instrument IDs before candle/ticker/order requests. This prevents bad
runtime requests like BTC-USDTT and keeps OKX scans on real OKX instruments.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import re
from typing import Any, Dict, Optional
from urllib.parse import urlencode

logger = logging.getLogger("nija.broker")
_TRUTHY = {"1", "true", "yes", "y", "on"}
_CASH_CURRENCIES = {"USD", "USDT", "USDC"}
_VALID_STABLE_QUOTES = ("USDT", "USDC", "USD")


def _env_truthy(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() in _TRUTHY


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return default


def _normalize_okx_inst_id(symbol: Any) -> str:
    """Convert NIJA/Coinbase/Kraken-style symbols into valid OKX spot instIds.

    OKX spot markets are mostly BASE-USDT. NIJA's merged universe contains
    Coinbase/Kraken forms such as BTC-USD and BTC-USDT. Some legacy OKX code
    appended a trailing T to USD pairs, creating invalid values like BTC-USDTT.
    This normalizer is idempotent and explicitly repairs that malformed suffix.
    """
    raw = str(symbol or "").upper().strip().replace("/", "-").replace("_", "-").replace(":", "-")
    raw = re.sub(r"[^A-Z0-9\-]", "", raw)
    if not raw:
        return raw
    while "--" in raw:
        raw = raw.replace("--", "-")
    if raw.endswith("-USDTT"):
        raw = raw[:-6] + "-USDT"
    elif raw.endswith("USDTT") and "-" not in raw:
        raw = raw[:-5] + "USDT"
    if raw in {"USD-USDT", "USDT-USD", "USDC-USDT", "USDT-USDC", "USD-USDC", "USDC-USD"}:
        return raw
    if "-" in raw:
        base, quote = raw.rsplit("-", 1)
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


def _normalize_okx_params(path: str, params: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    clean = {k: v for k, v in (params or {}).items() if v is not None}
    if "instId" in clean:
        before = str(clean.get("instId") or "")
        after = _normalize_okx_inst_id(before)
        if after != before:
            logger.warning("OKX_INSTID_NORMALIZED marker=20260703e before=%s after=%s path=%s", before, after, path)
            print(f"[NIJA-PRINT] OKX_INSTID_NORMALIZED marker=20260703e before={before} after={after}", flush=True)
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
        "50119": (
            "API key does not exist in this OKX environment (error 50119) — "
            "the key is not found on the OKX account. Possible causes: "
            "(1) OKX_API_KEY value is wrong or was never created, "
            "(2) key belongs to a different OKX account or sub-account, "
            "(3) live key used with x-simulated-trading:1 header (or vice versa), "
            "(4) key was deleted from the OKX dashboard. "
            "Action: log into OKX → API Management and verify the key exists and matches OKX_API_KEY exactly."
        ),
        "51001": "Invalid OKX instrument. The runtime now normalizes NIJA USD symbols to OKX spot instIds; if this repeats, the instrument is not listed on OKX.",
    }
    if code in hints:
        return hints[code]
    if status in (401, 403):
        return (
            "OKX auth rejected the request — likely wrong live/demo mode, invalid key/passphrase/secret, "
            "IP whitelist mismatch, expired/disabled key, or timestamp/signature mismatch."
        )
    return None


def apply_okx_runtime_patches() -> bool:
    """Patch bot.broker_manager OKX classes when available."""
    import sys

    bm = sys.modules.get("bot.broker_manager") or sys.modules.get("broker_manager")
    if bm is None:
        return False
    if getattr(bm, "_NIJA_OKX_RUNTIME_PATCHED_V20260703E", False):
        return True

    rest_cls = getattr(bm, "_OKXRestClient", None)
    okx_cls = getattr(bm, "OKXBroker", None)
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

    def _request(
        self: Any,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        payload: Optional[Dict[str, Any]] = None,
        private: bool = False,
    ) -> Dict[str, Any]:
        method = method.upper()
        clean_params = _normalize_okx_params(path, params)
        if path in {"/api/v5/market/candles", "/api/v5/market/ticker"}:
            inst = str(clean_params.get("instId", "")).upper()
            if inst in {"USD-USDT", "USDT-USD", "USDC-USDT", "USDT-USDC", "USD-USDC", "USDC-USD"}:
                logger.warning("OKX_SYNTHETIC_INSTRUMENT_SKIPPED marker=20260703e instId=%s path=%s", inst, path)
                return {"code": "0", "msg": "synthetic_cash_pair_skipped", "data": []}
        query = "?" + urlencode(clean_params) if clean_params else ""
        request_path = f"{path}{query}"
        body = "" if method == "GET" or not payload else json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        ts = self._timestamp()
        simulated = bool(getattr(self, "simulated", False)) or _env_truthy("OKX_SIMULATED_TRADING") or _env_truthy("OKX_USE_TESTNET")

        logger.warning(
            "OKX_REQUEST_DIAG method=%s path=%s base_url=%s simulated_instance=%s simulated_active=%s key_present=%s passphrase_present=%s timestamp=%s body_empty=%s",
            method, request_path, self.BASE_URL, bool(getattr(self, "simulated", False)), simulated,
            bool(getattr(self, "api_key", "")), bool(getattr(self, "passphrase", "")), ts, body == "",
        )

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
        if normalized in {"USD-USDT", "USDT-USD", "USDC-USDT", "USDT-USDC", "USD-USDC", "USDC-USD"}:
            logger.warning("OKX_CASH_PAIR_TICKER_SKIPPED instId=%s reason=synthetic_cash_pair", normalized)
            return {"code": "0", "msg": "synthetic_cash_pair_skipped", "data": []}
        return self._request("GET", "/api/v5/market/ticker", params={"instId": normalized})

    original_get_account_balance = getattr(okx_cls, "get_account_balance")
    original_get_positions = getattr(okx_cls, "get_positions")
    original_get_candles = getattr(okx_cls, "get_candles", None)
    original_get_market_data = getattr(okx_cls, "get_market_data", None)
    original_get_current_price = getattr(okx_cls, "get_current_price", None)

    def get_positions(self: Any) -> list[Dict[str, Any]]:
        """Return only real crypto positions; treat USD/USDT/USDC as cash."""
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
                available = _safe_float(detail.get("availBal", 0))
                cash_bal = _safe_float(detail.get("cashBal", 0))
                amount = max(available, cash_bal)
                if not ccy or ccy in _CASH_CURRENCIES or amount <= 0:
                    continue
                raw_holdings.append((ccy, amount, f"{ccy}-USDT"))
            if not raw_holdings:
                return []
            batch_prices: Dict[str, float] = {}
            if getattr(self, "market_api", None):
                try:
                    tickers_result = self.market_api.get_tickers(instType="SPOT")
                    if tickers_result and tickers_result.get("code") == "0":
                        for ticker in tickers_result.get("data", []):
                            inst_id = str(ticker.get("instId", ""))
                            batch_prices[inst_id] = _safe_float(ticker.get("last", 0))
                except Exception as ticker_err:
                    logger.warning("OKX batch ticker fetch failed: %s", ticker_err)
            positions = []
            for ccy, amount, okx_symbol in raw_holdings:
                current_price = batch_prices.get(okx_symbol, 0.0)
                if current_price <= 0.0:
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
        """Use OKX authenticated balance as source of truth and count USD cash."""
        if not getattr(self, "account_api", None):
            last_known = getattr(self, "_last_known_balance", None)
            if last_known is not None:
                return float(last_known)
            setattr(self, "_is_available", False)
            if not getattr(self, "_okx_disconnected_balance_logged", False):
                logger.info("OKX balance skipped — optional OKX broker is not connected and has no last known balance")
                setattr(self, "_okx_disconnected_balance_logged", True)
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
                    avail = _safe_float(detail.get("availBal", 0))
                    cash = _safe_float(detail.get("cashBal", 0))
                    eq_usd = _safe_float(detail.get("eqUsd", 0))
                    amount = max(avail, cash, eq_usd)
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
                if verbose:
                    raw = {"usd": usd_available, "usdt": usdt_available, "usdc": usdc_available, "trading_balance": usd_available + usdt_available + usdc_available, "usd_held": 0.0, "usdt_held": 0.0, "total_held": noncash_position_value, "total_funds": total_equity}
                    try:
                        _log_balance_snapshot = getattr(bm, "_log_balance_snapshot")
                        _log_balance_snapshot(account_label=f"okx:{getattr(self, 'account_identifier', 'PLATFORM')}", source="okx.account.balance", usd_available=usd_available, secondary_available=usdt_available + usdc_available, secondary_label="USDT/USDC", usd_held=0.0, secondary_held=noncash_position_value, raw_balances=raw, emit_info=True, emit_critical=True)
                    except Exception:
                        logger.info("OKX balance: total=$%.2f usd=$%.2f usdt=$%.2f usdc=$%.2f", total_equity, usd_available, usdt_available, usdc_available)
                setattr(self, "_last_known_balance", total_equity)
                setattr(self, "_balance_fetch_errors", 0)
                setattr(self, "_is_available", True)
                return total_equity
            return original_get_account_balance(self, verbose=verbose)
        except Exception as exc:
            logger.error("OKX patched balance fetch failed: %s", exc)
            return original_get_account_balance(self, verbose=verbose)

    def get_candles(self: Any, symbol: Any, *args: Any, **kwargs: Any):
        normalized = _normalize_okx_inst_id(symbol)
        if normalized != str(symbol):
            logger.warning("OKX_CANDLE_SYMBOL_NORMALIZED marker=20260703e before=%s after=%s", symbol, normalized)
        if callable(original_get_candles):
            return original_get_candles(self, normalized, *args, **kwargs)
        if callable(original_get_market_data):
            return original_get_market_data(self, normalized, *args, **kwargs)
        return None

    def get_market_data(self: Any, symbol: Any, *args: Any, **kwargs: Any):
        normalized = _normalize_okx_inst_id(symbol)
        if normalized != str(symbol):
            logger.warning("OKX_MARKETDATA_SYMBOL_NORMALIZED marker=20260703e before=%s after=%s", symbol, normalized)
        if callable(original_get_market_data):
            return original_get_market_data(self, normalized, *args, **kwargs)
        if callable(original_get_candles):
            return original_get_candles(self, normalized, *args, **kwargs)
        return None

    def get_current_price(self: Any, symbol: Any, *args: Any, **kwargs: Any):
        normalized = _normalize_okx_inst_id(symbol)
        if callable(original_get_current_price):
            return original_get_current_price(self, normalized, *args, **kwargs)
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
    bm._NIJA_OKX_RUNTIME_PATCHED = True
    bm._NIJA_OKX_RUNTIME_PATCHED_V20260703E = True
    logger.warning("✅ OKX runtime patch applied marker=20260703e: auth diagnostics, cash-aware balance, valid instId normalization")
    print("[NIJA-PRINT] OKX_RUNTIME_PATCHED marker=20260703e", flush=True)
    return True


def install_import_hook() -> None:
    """Install a one-shot import hook that patches broker_manager after import."""
    import builtins
    import sys

    bm = sys.modules.get("bot.broker_manager") or sys.modules.get("broker_manager")
    if bm is not None and getattr(bm, "_NIJA_OKX_RUNTIME_PATCHED_V20260703E", False):
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
