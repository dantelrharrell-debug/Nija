"""Runtime hardening for NIJA's optional OKX broker.

This module deliberately avoids changing Kraken/Coinbase execution.  It patches
only the optional OKX direct REST client so authentication failures are diagnosable
but do not keep polluting startup/capital-refresh logs after OKX has already been
classified as unavailable.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
from typing import Any, Dict, Optional
from urllib.parse import urlencode

logger = logging.getLogger("nija.broker")
_TRUTHY = {"1", "true", "yes", "y", "on"}


def _env_truthy(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() in _TRUTHY


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
    """Patch bot.broker_manager OKX classes when available.

    Returns True when the broker_manager module was present and patching completed.
    Returns False when called before broker_manager has finished importing.
    """
    import sys

    bm = sys.modules.get("bot.broker_manager") or sys.modules.get("broker_manager")
    if bm is None or getattr(bm, "_NIJA_OKX_RUNTIME_PATCHED", False):
        return bool(getattr(bm, "_NIJA_OKX_RUNTIME_PATCHED", False)) if bm is not None else False

    rest_cls = getattr(bm, "_OKXRestClient", None)
    okx_cls = getattr(bm, "OKXBroker", None)
    if rest_cls is None or okx_cls is None:
        return False

    def _headers(self: Any, timestamp: str, method: str, request_path: str, body: str, *, private: bool) -> Dict[str, str]:
        if private:
            prehash = timestamp + method.upper() + request_path + body
            # OKX requires the method in its original case (e.g. "GET", "POST") — do NOT re-uppercase here.
            message = timestamp + method + request_path + body
            signature = base64.b64encode(
                hmac.new(self.api_secret.encode("utf-8"), prehash.encode("utf-8"), hashlib.sha256).digest()
            ).decode("utf-8")
            logger.warning(
                "OKX_AUTH_DETAIL timestamp=%s prehash=%r signing_algo=Base64-HMAC-SHA256 signature_len=%s",
                timestamp,
                prehash,
                len(signature),
            )
            headers: Dict[str, str] = {
                "OK-ACCESS-KEY": self.api_key,
                "OK-ACCESS-SIGN": signature,
                "OK-ACCESS-TIMESTAMP": timestamp,
                "OK-ACCESS-PASSPHRASE": self.passphrase,
                "Content-Type": "application/json",
            }
        else:
            headers = {"Content-Type": "application/json"}
        # Send x-simulated-trading:1 only when explicitly in simulated/testnet mode.
        # Live credentials must NOT include this header — OKX rejects live keys
        # that arrive with x-simulated-trading:1 (and vice versa).
        _sim_active = bool(getattr(self, "simulated", False)) or _env_truthy("OKX_SIMULATED_TRADING") or _env_truthy("OKX_USE_TESTNET")
        if _sim_active:
            headers["x-simulated-trading"] = "1"
        logger.warning(
            "OKX_HEADERS_DIAG simulated_instance=%s simulated_header_sent=%s headers_keys=%s",
            bool(getattr(self, "simulated", False)),
            _sim_active,
            list(headers.keys()),
        )
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
        clean_params = {k: v for k, v in (params or {}).items() if v is not None}
        query = "?" + urlencode(clean_params) if clean_params else ""
        request_path = f"{path}{query}"
        body = "" if method == "GET" or not payload else json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        ts = self._timestamp()
        simulated = bool(getattr(self, "simulated", False)) or _env_truthy("OKX_SIMULATED_TRADING") or _env_truthy("OKX_USE_TESTNET")

        logger.warning(
            "OKX_REQUEST_DIAG method=%s path=%s base_url=%s simulated_instance=%s simulated_active=%s "
            "key_present=%s passphrase_present=%s timestamp=%s body_empty=%s",
            method,
            request_path,
            self.BASE_URL,
            bool(getattr(self, "simulated", False)),
            simulated,
            bool(getattr(self, "api_key", "")),
            bool(getattr(self, "passphrase", "")),
            ts,
            body == "",
        )

        request_headers = self._headers(ts, method, request_path, body, private=private)
        response = self.session.request(
            method,
            f"{self.BASE_URL}{request_path}",
            data=body if body else None,
            headers=request_headers,
            timeout=self.timeout,
        )
        logger.warning(
            "OKX_RESPONSE_DIAG status=%s method=%s path=%s response_body=%s",
            response.status_code,
            method,
            request_path,
            response.text,
        )

        try:
            parsed = response.json()
        except ValueError:
            parsed = {"code": f"HTTP_{response.status_code}", "msg": response.text or "Non-JSON OKX response"}

        if not response.ok:
            okx_code = str(parsed.get("code", "unknown"))
            okx_msg = str(parsed.get("msg", ""))
            logger.error(
                "OKX_REQUEST_FAILED status=%s method=%s path=%s response_body=%s",
                response.status_code,
                method,
                request_path,
                response.text,
            )
            logger.error("OKX_ERROR_DETAIL okx_code=%s okx_msg=%s", okx_code, okx_msg)
            hint = _okx_auth_hint(okx_code, response.status_code)
            if hint:
                logger.error("OKX_AUTH_HINT %s", hint)
            parsed.setdefault("http_status", response.status_code)
            parsed.setdefault("request_path", request_path)
            return parsed

        return parsed

    original_get_account_balance = okx_cls.get_account_balance

    def get_account_balance(self: Any, verbose: bool = True) -> float:
        if not getattr(self, "account_api", None):
            last_known = getattr(self, "_last_known_balance", None)
            if last_known is not None:
                return float(last_known)
            setattr(self, "_is_available", False)
            if not getattr(self, "_okx_disconnected_balance_logged", False):
                logger.info("OKX balance skipped — optional OKX broker is not connected and has no last known balance")
                setattr(self, "_okx_disconnected_balance_logged", True)
            return 0.0
        return original_get_account_balance(self, verbose=verbose)

    rest_cls._headers = _headers
    rest_cls._request = _request
    okx_cls.get_account_balance = get_account_balance
    bm._NIJA_OKX_RUNTIME_PATCHED = True
    logger.info("✅ OKX runtime auth-failure patch applied")
    return True


def install_import_hook() -> None:
    """Install a one-shot import hook that patches broker_manager after import."""
    import builtins
    import sys

    if getattr(builtins, "_NIJA_OKX_IMPORT_HOOK_INSTALLED", False):
        apply_okx_runtime_patches()
        return

    original_import = builtins.__import__

    def guarded_import(name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0) -> Any:
        module = original_import(name, globals, locals, fromlist, level)
        target_loaded = (
            name in {"bot.broker_manager", "broker_manager"}
            or name.endswith(".broker_manager")
            or "bot.broker_manager" in sys.modules
            or "broker_manager" in sys.modules
        )
        if target_loaded:
            try:
                if apply_okx_runtime_patches():
                    builtins.__import__ = original_import
                    setattr(builtins, "_NIJA_OKX_IMPORT_HOOK_INSTALLED", False)
            except Exception as exc:  # pragma: no cover - defensive startup safety
                logging.getLogger("nija.broker").warning("OKX runtime patch hook failed: %s", exc)
        return module

    builtins.__import__ = guarded_import
    setattr(builtins, "_NIJA_OKX_IMPORT_HOOK_INSTALLED", True)
    apply_okx_runtime_patches()
