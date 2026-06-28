"""Runtime compatibility patches loaded automatically by Python.

This module keeps NIJA's OKX optional-broker behavior fail-soft while preserving
full OKX authentication diagnostics.  It patches broker_manager after import so
existing startup code does not need to import another helper explicitly.
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
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "y", "on"}


def _json_body(payload: Optional[Dict[str, Any]]) -> str:
    if not payload:
        return ""
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def _patch_broker_manager(module: Any) -> None:
    marker = f"{getattr(module, '__name__', '')}:{id(module)}"
    if marker in _PATCHED:
        return

    okx_client_cls = getattr(module, "_OKXRestClient", None)
    okx_broker_cls = getattr(module, "OKXBroker", None)
    if okx_client_cls is None or okx_broker_cls is None:
        return

    logger = getattr(module, "logger", logging.getLogger("nija.broker"))
    requests_available = bool(getattr(module, "_REQUESTS_AVAILABLE", False))
    requests_lib = getattr(module, "_requests_lib", None)

    def _headers(self, timestamp: str, method: str, request_path: str, body: str, *, private: bool) -> Dict[str, str]:
        if private:
            message = timestamp + method.upper() + request_path + body
            signature = base64.b64encode(
                hmac.new(self.api_secret.encode(), message.encode(), hashlib.sha256).digest()
            ).decode()
            headers: Dict[str, str] = {
                "OK-ACCESS-KEY": self.api_key,
                "OK-ACCESS-SIGN": signature,
                "OK-ACCESS-TIMESTAMP": timestamp,
                "OK-ACCESS-PASSPHRASE": self.passphrase,
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

        logger.info(
            "OKX_REQUEST_DIAG method=%s path=%s base_url=%s simulated=%s key_present=%s passphrase_present=%s body_empty=%s",
            method,
            request_path,
            self.BASE_URL,
            simulated,
            bool(getattr(self, "api_key", "")),
            bool(getattr(self, "passphrase", "")),
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

            # OKX is registered as a non-critical optional broker.  Once connect()
            # has failed, capital hydration must skip it quietly instead of
            # producing repeated ERROR logs and artificial zero-balance signals.
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

    okx_client_cls._headers = _headers
    okx_client_cls._request = _request
    okx_broker_cls.get_account_balance = get_account_balance
    _PATCHED.add(marker)
    _LOG.info("OKX runtime patch applied to %s", getattr(module, "__name__", "broker_manager"))


class _BrokerManagerPatchLoader(importlib.abc.Loader):
    def __init__(self, wrapped: importlib.abc.Loader):
        self._wrapped = wrapped

    def create_module(self, spec):
        create_module = getattr(self._wrapped, "create_module", None)
        if create_module is not None:
            return create_module(spec)
        return None

    def exec_module(self, module):
        self._wrapped.exec_module(module)
        if getattr(module, "__name__", "") in {"bot.broker_manager", "broker_manager"}:
            try:
                _patch_broker_manager(module)
            except Exception as exc:
                _LOG.warning("OKX runtime patch failed for %s: %s", getattr(module, "__name__", "broker_manager"), exc)


class _BrokerManagerPatchFinder(importlib.abc.MetaPathFinder):
    TARGETS = {"bot.broker_manager", "broker_manager"}

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
                spec.loader = _BrokerManagerPatchLoader(spec.loader)
                return spec
        return None


# Install the hook once.  If broker_manager was already imported, patch it now.
if not any(isinstance(finder, _BrokerManagerPatchFinder) for finder in sys.meta_path):
    sys.meta_path.insert(0, _BrokerManagerPatchFinder())

for _name in ("bot.broker_manager", "broker_manager"):
    _module = sys.modules.get(_name)
    if _module is not None:
        try:
            _patch_broker_manager(_module)
        except Exception as _exc:
            _LOG.warning("OKX runtime patch failed for preloaded %s: %s", _name, _exc)
