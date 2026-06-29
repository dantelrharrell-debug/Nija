"""Runtime compatibility patches loaded automatically by Python.

This module keeps NIJA's OKX optional-broker behavior fail-soft while preserving
full OKX authentication diagnostics. It also wires startup exchange-position
adoption into the real TradingStrategy startup path so pre-existing exchange
positions are visible to the internal PositionTracker after Railway restarts.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import importlib
import importlib.abc
import importlib.machinery
import json
import logging
import os
import sys
import time
from typing import Any, Dict, Optional
from urllib.parse import urlencode

_LOG = logging.getLogger("nija.okx_runtime_patch")
_PATCHED = set()

_OKX_AUTH_HINTS = {
    "50100": "API key does not exist — verify OKX_API_KEY belongs to this OKX environment/account.",
    "50102": "Request timestamp expired — check UTC clock sync and timestamp format.",
    "50110": "IP whitelist rejection — add the Railway/public egress IP to the OKX key whitelist or remove the whitelist.",
    "50111": "Invalid API key — key may be deleted, disabled, expired, or for a different environment.",
    "50112": "Invalid passphrase — OKX_API_PASSPHRASE/OKX_PASSPHRASE does not match the key passphrase.",
    "50113": "Invalid signature — check OKX_API_SECRET, request path, timestamp, and body prehash.",
    "50114": "Timestamp out of sync — server time differs too much from request timestamp.",
    "50119": "API key does not exist in this environment — verify live vs demo mode, account/subaccount, copied key value, and whether the key was deleted/disabled.",
}


def _truthy_env(name: str, default: str = "false") -> bool:
    return _clean_secret(os.getenv(name, default)).strip().lower() in {"1", "true", "yes", "y", "on"}


def _clean_secret(value: Any) -> str:
    """Normalize Railway/raw-env values without exposing their content."""
    if value is None:
        return ""
    text = str(value).strip().lstrip("\ufeff")
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
        text = text[1:-1].strip()
    text = text.strip().strip('"').strip("'").strip()
    return text


def _clean_base_url(value: Any) -> str:
    url = _clean_secret(value or "https://us.okx.com").rstrip("/")
    if not url:
        return "https://us.okx.com"
    if url in {"https://www.okx.com", "https://openapi.okx.com"} and _truthy_env("OKX_US_REGION", "true"):
        return "https://us.okx.com"
    return url


def _json_body(payload: Optional[Dict[str, Any]]) -> str:
    if not payload:
        return ""
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def _invoke_startup_position_sync(strategy: Any, *, source: str) -> None:
    if getattr(strategy, "_startup_position_sync_done", False):
        return
    setattr(strategy, "_startup_position_sync_done", True)
    if not _truthy_env("NIJA_STARTUP_POSITION_SYNC_ENABLED", "true"):
        _LOG.warning("EXCHANGE_POSITION_SYNC disabled by NIJA_STARTUP_POSITION_SYNC_ENABLED=false")
        return
    try:
        try:
            from bot.startup_position_sync import sync_exchange_positions_on_startup
        except ImportError:
            from startup_position_sync import sync_exchange_positions_on_startup  # type: ignore[import]
        _LOG.warning("EXCHANGE_POSITION_SYNC invocation starting source=%s", source)
        adopted = sync_exchange_positions_on_startup(strategy)
        _LOG.warning("EXCHANGE_POSITION_SYNC invocation complete adopted=%s source=%s", adopted, source)
    except Exception as exc:
        _LOG.exception("EXCHANGE_POSITION_SYNC invocation failed source=%s error=%s", source, exc)


def _patch_trading_strategy(module: Any) -> None:
    marker = f"trading_strategy:{getattr(module, '__name__', '')}:{id(module)}"
    if marker in _PATCHED:
        return
    cls = getattr(module, "TradingStrategy", None)
    if cls is None:
        return
    original_init = getattr(cls, "__init__", None)
    if original_init is None or getattr(original_init, "_nija_position_sync_wrapped", False):
        return

    def _init_with_position_sync(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        _invoke_startup_position_sync(self, source="TradingStrategy.__init__")

    _init_with_position_sync._nija_position_sync_wrapped = True
    cls.__init__ = _init_with_position_sync
    _PATCHED.add(marker)
    _LOG.warning("EXCHANGE_POSITION_SYNC TradingStrategy hook installed on %s", getattr(module, "__name__", "trading_strategy"))


def _patch_broker_manager(module: Any) -> None:
    marker = f"broker_manager:{getattr(module, '__name__', '')}:{id(module)}"
    if marker in _PATCHED:
        return

    okx_client_cls = getattr(module, "_OKXRestClient", None)
    okx_broker_cls = getattr(module, "OKXBroker", None)
    if okx_client_cls is None or okx_broker_cls is None:
        return

    logger = getattr(module, "logger", logging.getLogger("nija.broker"))
    requests_available = bool(getattr(module, "_REQUESTS_AVAILABLE", False))
    requests_lib = getattr(module, "_requests_lib", None)
    original_client_init = okx_client_cls.__init__
    okx_client_cls.BASE_URL = _clean_base_url(os.getenv("OKX_BASE_URL", "https://us.okx.com"))

    def _init(self, api_key: str, api_secret: str, passphrase: str, *, simulated: bool = False, timeout: float = 10.0):
        raw_key = str(api_key or "")
        raw_secret = str(api_secret or "")
        raw_passphrase = str(passphrase or "")
        cleaned_key = _clean_secret(api_key)
        cleaned_secret = _clean_secret(api_secret)
        cleaned_passphrase = _clean_secret(passphrase)
        original_client_init(self, cleaned_key, cleaned_secret, cleaned_passphrase, simulated=simulated, timeout=timeout)
        self.BASE_URL = _clean_base_url(getattr(self, "BASE_URL", None) or os.getenv("OKX_BASE_URL", "https://us.okx.com"))
        if raw_key != cleaned_key or raw_secret != cleaned_secret or raw_passphrase != cleaned_passphrase:
            logger.warning(
                "OKX_ENV_SANITIZED stripped quote/whitespace wrappers from one or more OKX credential variables "
                "(key_len=%s secret_len=%s passphrase_len=%s)",
                len(cleaned_key),
                len(cleaned_secret),
                len(cleaned_passphrase),
            )
        logger.info(
            "OKX_ENV_SHAPE key_len=%s secret_len=%s passphrase_len=%s base_url=%s simulated=%s",
            len(cleaned_key),
            len(cleaned_secret),
            len(cleaned_passphrase),
            self.BASE_URL,
            bool(simulated),
        )

    def _headers(self, timestamp: str, method: str, request_path: str, body: str, *, private: bool) -> Dict[str, str]:
        if private:
            api_key = _clean_secret(getattr(self, "api_key", ""))
            api_secret = _clean_secret(getattr(self, "api_secret", ""))
            passphrase = _clean_secret(getattr(self, "passphrase", ""))
            self.api_key = api_key
            self.api_secret = api_secret
            self.passphrase = passphrase
            message = timestamp + method.upper() + request_path + body
            signature = base64.b64encode(
                hmac.new(api_secret.encode(), message.encode(), hashlib.sha256).digest()
            ).decode()
            headers: Dict[str, str] = {
                "OK-ACCESS-KEY": api_key,
                "OK-ACCESS-SIGN": signature,
                "OK-ACCESS-TIMESTAMP": timestamp,
                "OK-ACCESS-PASSPHRASE": passphrase,
                "Content-Type": "application/json",
            }
        else:
            headers = {"Content-Type": "application/json"}
        if bool(getattr(self, "simulated", False)) or _truthy_env("OKX_SIMULATED_TRADING"):
            headers["x-simulated-trading"] = "1"
        return headers

    def _request(self, method: str, path: str, *, params: Optional[Dict[str, Any]] = None, payload: Optional[Dict[str, Any]] = None, private: bool = False) -> Dict[str, Any]:
        if not requests_available or requests_lib is None:
            raise RuntimeError("requests is required for OKX REST trading")

        method = method.upper()
        clean_params = {k: v for k, v in (params or {}).items() if v is not None}
        query = "?" + urlencode(clean_params) if clean_params else ""
        request_path = f"{path}{query}"
        body = _json_body(payload) if method != "GET" else ""
        timestamp = self._timestamp()
        simulated = bool(getattr(self, "simulated", False)) or _truthy_env("OKX_SIMULATED_TRADING")
        self.BASE_URL = _clean_base_url(getattr(self, "BASE_URL", None) or os.getenv("OKX_BASE_URL", "https://us.okx.com"))

        logger.info(
            "OKX_REQUEST_DIAG method=%s path=%s base_url=%s simulated=%s key_present=%s key_len=%s passphrase_present=%s body_empty=%s",
            method,
            request_path,
            self.BASE_URL,
            simulated,
            bool(_clean_secret(getattr(self, "api_key", ""))),
            len(_clean_secret(getattr(self, "api_key", ""))),
            bool(_clean_secret(getattr(self, "passphrase", ""))),
            body == "",
        )

        response = self.session.request(
            method,
            f"{self.BASE_URL}{request_path}",
            data=body if body else None,
            headers=self._headers(timestamp, method, request_path, body, private=private),
            timeout=self.timeout,
        )

        response_text = getattr(response, "text", "")
        try:
            parsed = response.json()
        except Exception:
            parsed = None

        if not response.ok:
            logger.error(
                "OKX_REQUEST_FAILED status=%s method=%s path=%s response_body=%s",
                response.status_code,
                method,
                request_path,
                response_text,
            )
            if isinstance(parsed, dict):
                code = str(parsed.get("code", "unknown"))
                msg = parsed.get("msg", "")
                logger.error("OKX_ERROR_DETAIL okx_code=%s okx_msg=%s", code, msg)
                hint = _OKX_AUTH_HINTS.get(code)
                if hint:
                    logger.error("OKX_AUTH_HINT %s", hint)
            response.raise_for_status()

        if isinstance(parsed, dict):
            return parsed
        raise RuntimeError(f"OKX returned non-JSON response status={response.status_code} body={response_text[:300]}")

    original_get_account_balance = okx_broker_cls.get_account_balance

    def get_account_balance(self, verbose: bool = True):
        if not getattr(self, "account_api", None):
            last_known = getattr(self, "_last_known_balance", None)
            if last_known is not None:
                return last_known
            setattr(self, "_is_available", False)
            now = time.monotonic()
            last_log = float(getattr(self, "_last_disconnected_balance_log_ts", 0.0) or 0.0)
            if verbose and now - last_log >= 300.0:
                logger.warning(
                    "OKX optional broker unavailable; skipping balance contribution until credentials/connectivity recover"
                )
                setattr(self, "_last_disconnected_balance_log_ts", now)
            return None
        return original_get_account_balance(self, verbose=verbose)

    okx_client_cls.__init__ = _init
    okx_client_cls._headers = _headers
    okx_client_cls._request = _request
    okx_broker_cls.get_account_balance = get_account_balance
    _PATCHED.add(marker)
    _LOG.info("OKX runtime patch applied to %s", getattr(module, "__name__", "broker_manager"))


class _NijaPatchLoader(importlib.abc.Loader):
    def __init__(self, wrapped: importlib.abc.Loader):
        self._wrapped = wrapped

    def create_module(self, spec):
        create_module = getattr(self._wrapped, "create_module", None)
        if create_module is not None:
            return create_module(spec)
        return None

    def exec_module(self, module):
        self._wrapped.exec_module(module)
        name = getattr(module, "__name__", "")
        try:
            if name in {"bot.broker_manager", "broker_manager"}:
                _patch_broker_manager(module)
            elif name in {"bot.trading_strategy", "trading_strategy"}:
                _patch_trading_strategy(module)
        except Exception as exc:
            _LOG.warning("NIJA runtime patch failed for %s: %s", name, exc)


class _NijaPatchFinder(importlib.abc.MetaPathFinder):
    TARGETS = {"bot.broker_manager", "broker_manager", "bot.trading_strategy", "trading_strategy"}

    def find_spec(self, fullname, path=None, target=None):
        if fullname not in self.TARGETS:
            return None
        for finder in sys.meta_path:
            if finder is self:
                continue
            find_spec = getattr(finder, "find_spec", None)
            if find_spec is None:
                continue
            spec = find_spec(fullname, path, target)
            if spec is not None and spec.loader is not None:
                spec.loader = _NijaPatchLoader(spec.loader)
                return spec
        return None


if not any(isinstance(finder, _NijaPatchFinder) for finder in sys.meta_path):
    sys.meta_path.insert(0, _NijaPatchFinder())

for _name in ("bot.broker_manager", "broker_manager", "bot.trading_strategy", "trading_strategy"):
    _module = sys.modules.get(_name)
    if _module is not None:
        try:
            if _name in {"bot.broker_manager", "broker_manager"}:
                _patch_broker_manager(_module)
            else:
                _patch_trading_strategy(_module)
        except Exception as _exc:
            _LOG.warning("NIJA runtime patch failed for preloaded %s: %s", _name, _exc)
