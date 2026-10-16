"""Isolated, read-only Kraken authentication probe; never authorizes trading."""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import time
from urllib.parse import urlencode

import requests


class KrakenVerificationError(Exception):
    """Generic error; never expose credentials or account balances."""


def verify_kraken_readonly(api_key: str, api_secret: str, *, session=None, nonce=None) -> bool:
    """Verify an owner-authorized credential with Kraken's private Balance endpoint.

    Only call after owner-scoped vault retrieval and entitlement validation.
    This helper does not read vault records, store credentials, or submit orders.
    """
    if not isinstance(api_key, str) or not api_key.strip() or not isinstance(api_secret, str):
        raise KrakenVerificationError("Kraken verification unavailable")
    path = "/0/private/Balance"
    n = str(time.time_ns() // 1000 if nonce is None else nonce)
    if not n.isdecimal():
        raise KrakenVerificationError("Kraken verification unavailable")
    encoded = urlencode({"nonce": n})
    try:
        secret = base64.b64decode(api_secret, validate=True)
        if not secret:
            raise KrakenVerificationError("Kraken verification unavailable")
        digest = hashlib.sha256((n + encoded).encode("utf-8")).digest()
        signature = base64.b64encode(hmac.new(
            secret, path.encode("ascii") + digest, hashlib.sha512
        ).digest()).decode("ascii")
        response = (session or requests).post(
            "https://api.kraken.com" + path,
            data={"nonce": n},
            headers={"API-Key": api_key, "API-Sign": signature},
            timeout=10,
            allow_redirects=False,
        )
        if response.status_code != 200:
            raise KrakenVerificationError("Kraken verification unavailable")
        result = response.json()
        if not isinstance(result, dict) or result.get("error") != [] or not isinstance(result.get("result"), dict):
            raise KrakenVerificationError("Kraken verification unavailable")
        return True
    except (binascii.Error, ValueError, TypeError, requests.RequestException) as exc:
        raise KrakenVerificationError("Kraken verification unavailable") from exc
