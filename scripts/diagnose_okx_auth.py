#!/usr/bin/env python3
"""OKX V5 authentication diagnostic for NIJA.

Logs request shape and OKX response body without printing secret values.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from urllib.parse import urlencode

import requests

logger = logging.getLogger("nija.okx_auth_diag")
RFC3339_MILLIS_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
TRUTHY = {"1", "true", "yes", "y", "on"}


def env_truthy(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() in TRUTHY


def timestamp_ms_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def sign(secret_value: str, ts: str, method: str, request_path: str, body: str) -> str:
    prehash = ts + method.upper() + request_path + body
    digest = hmac.new(secret_value.encode("utf-8"), prehash.encode("utf-8"), hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


def main() -> int:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(), format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")

    api_key = os.getenv("OKX_API_KEY", "").strip()
    api_secret = os.getenv("OKX_API_SECRET", "").strip()
    passphrase = (os.getenv("OKX_API_PASSPHRASE") or os.getenv("OKX_PASSPHRASE") or "").strip()
    base_url = os.getenv("OKX_BASE_URL", "https://www.okx.com").strip().rstrip("/")
    use_testnet = env_truthy("OKX_USE_TESTNET")
    simulated = env_truthy("OKX_SIMULATED_TRADING") or use_testnet

    method = "GET"
    path = "/api/v5/account/balance"
    params = {}
    query = "?" + urlencode(params) if params else ""
    request_path = f"{path}{query}"
    body = ""
    ts = timestamp_ms_utc()

    logger.info(
        "OKX auth diag: base_url=%s path=%s key=%s secret=%s passphrase=%s use_testnet=%s simulated=%s",
        base_url,
        request_path,
        bool(api_key),
        bool(api_secret),
        bool(passphrase),
        use_testnet,
        simulated,
    )
    logger.info(
        "OKX signature diag: method=%s request_path=%s body_empty=%s timestamp=%s timestamp_valid=%s",
        method,
        request_path,
        body == "",
        ts,
        bool(RFC3339_MILLIS_UTC_RE.match(ts)),
    )

    if not api_key or not api_secret or not passphrase:
        logger.error("OKX credentials incomplete")
        return 2

    headers = {
        "OK-ACCESS-KEY": api_key,
        "OK-ACCESS-SIGN": sign(api_secret, ts, method, request_path, body),
        "OK-ACCESS-TIMESTAMP": ts,
        "OK-ACCESS-PASSPHRASE": passphrase,
        "Content-Type": "application/json",
    }
    if simulated:
        headers["x-simulated-trading"] = "1"

    logger.info(
        "OKX header diag: key=%s sign=%s timestamp=%s passphrase=%s content_type=%s simulated_header=%s",
        bool(headers.get("OK-ACCESS-KEY")),
        bool(headers.get("OK-ACCESS-SIGN")),
        headers.get("OK-ACCESS-TIMESTAMP"),
        bool(headers.get("OK-ACCESS-PASSPHRASE")),
        headers.get("Content-Type"),
        headers.get("x-simulated-trading", "absent"),
    )

    response = requests.request(method, f"{base_url}{request_path}", headers=headers, data=None, timeout=15)
    logger.info("OKX HTTP status: %s", response.status_code)
    logger.info("OKX response body: %s", response.text)

    try:
        payload = response.json()
    except ValueError:
        logger.error("OKX returned non-JSON response")
        return 1

    if response.status_code == 200 and str(payload.get("code")) == "0":
        logger.info("OKX auth diagnostic passed")
        return 0

    logger.error("OKX auth diagnostic failed: http=%s code=%s msg=%s", response.status_code, payload.get("code"), payload.get("msg"))
    return 1


if __name__ == "__main__":
    sys.exit(main())
