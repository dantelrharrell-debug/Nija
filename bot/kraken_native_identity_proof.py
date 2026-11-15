"""Native request credential binding for independently reviewed identity readers.

No network calls, nonce generation, credential storage, or order authority.
The caller must bind the receipt to its one fresh canonical transport call.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from typing import Any
from urllib.parse import parse_qsl

ENDPOINT = "https://api.kraken.com/0/private/GetApiKeyInfo"


def native_identity_key_digest(
    api: Any, previous: Any, parsed: Any, key_before: str, secret_before: str,
) -> str | None:
    """Return only the authenticated request key digest, or deny with None.

Recompute the signature on the exact prepared form body. Require native TLS,
unchanged client credentials, one new successful nonredirected response, and
unambiguous wire JSON identical to the parsed result. A configured key alone
and boolean field-presence diagnostics can never establish this proof.
"""
    try:
        from requests import PreparedRequest, Response, Session

        response = getattr(api, "response", None)
        session = getattr(api, "session", None)
        if (type(session) is not Session or session.verify is not True
                or not isinstance(key_before, str) or not 0 < len(key_before) <= 512
                or not isinstance(secret_before, str) or not 0 < len(secret_before) <= 1024
                or not hmac.compare_digest(api.key, key_before)
                or not hmac.compare_digest(api.secret, secret_before)
                or type(response) is not Response or response is previous
                or response.status_code != 200 or response.url != ENDPOINT or response.history
                or type(response.request) is not PreparedRequest
                or response.request.method != "POST" or response.request.url != ENDPOINT
                or response._content_consumed is not True):
            return None
        request = response.request
        header_key = request.headers.get("API-Key")
        signature = request.headers.get("API-Sign")
        if (not isinstance(header_key, str) or not hmac.compare_digest(header_key, key_before)
                or not isinstance(signature, str) or len(signature) > 256
                or request.headers.get("Content-Type") != "application/x-www-form-urlencoded"):
            return None
        body = request.body
        if isinstance(body, bytes):
            body = body.decode("ascii")
        if not isinstance(body, str) or not 0 < len(body) <= 8192:
            return None
        pairs = parse_qsl(body, keep_blank_values=True, strict_parsing=True)
        fields = dict(pairs)
        if (len(fields) != len(pairs) or set(fields) - {"nonce", "otp"}
                or "nonce" not in fields or not fields["nonce"].isascii()
                or not fields["nonce"].isdigit() or not 0 < int(fields["nonce"]) < 2**64):
            return None
        message = b"/0/private/GetApiKeyInfo" + hashlib.sha256(
            (fields["nonce"] + body).encode("ascii"),
        ).digest()
        expected = base64.b64encode(hmac.new(
            base64.b64decode(secret_before, validate=True), message, hashlib.sha512,
        ).digest()).decode("ascii")
        if not hmac.compare_digest(signature, expected):
            return None
        wire = response._content
        if type(wire) is not bytes or not 0 < len(wire) <= 65536:
            return None

        def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for name, value in pairs:
                if name in result:
                    raise ValueError("ambiguous_native_identity")
                result[name] = value
            return result

        def reject_constant(_: str) -> None:
            raise ValueError("nonfinite_native_identity")

        payload = json.loads(wire, object_pairs_hook=unique, parse_constant=reject_constant)
        if (type(payload) is not dict or payload.get("error") != []
                or type(payload.get("result")) is not dict or payload != parsed):
            return None
        return hashlib.sha256(header_key.encode("utf-8")).hexdigest()
    except Exception:
        return None  # Never expose request/credential/provider exception values.
