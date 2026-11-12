"""Call-scoped timing at the existing Kraken identity transport boundary.

Queue/rate-limit waits precede observation, but transport and post-read delays
consume the unchanged evidence lifetime. No response cache, nonce owner, client,
approval, or collector is created here. Gateway and uninstrumented calls retain
the provider's conservative whole-call freshness check.
"""
from __future__ import annotations

import json
import math
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator

_LOCAL = threading.local()


def _finite(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


@dataclass
class IdentityReadTiming:
    """Private, single-call receipt; never serializable production evidence."""

    api: Any = field(repr=False)
    clock: Callable[[], float] = field(repr=False)
    attempts: int = 0
    started: float | None = None
    finished: float | None = None
    elapsed: float | None = None
    monotonic_started: float | None = None
    response: Any = field(default=None, repr=False)
    api_matched: bool = False
    inspect_http_fields: bool = field(default=False, repr=False)
    http_field_presence: dict[str, bool] | None = None

    def observation_start(self, response: Any, queued: float, now: float, maximum: float) -> float:
        """Accept exactly one matching transport and its original start time."""
        total_elapsed = (time.monotonic() - self.monotonic_started
                         if _finite(self.monotonic_started) else float("nan"))
        if (self.attempts != 1 or not self.api_matched or self.response is not response
                or not all(_finite(v) for v in (self.started, self.finished, self.elapsed, queued, now))
                or not 0 < queued <= self.started <= self.finished <= now
                or not 0 <= self.elapsed <= maximum
                or not _finite(total_elapsed) or not 0 <= total_elapsed <= maximum
                or now - self.started > maximum):
            raise ValueError("identity_transport_timing_unverified")
        return self.started


@contextmanager
def capture_identity_read(
    api: Any, clock: Callable[[], float], *, inspect_http_fields: bool = False,
) -> Iterator[IdentityReadTiming]:
    """Scope timing to this thread, exact API object and provider invocation."""
    previous = getattr(_LOCAL, "capture", None)
    capture = IdentityReadTiming(api, clock, inspect_http_fields=inspect_http_fields)
    _LOCAL.capture = capture
    try:
        yield capture
    finally:
        _LOCAL.capture = previous


def _http_field_presence(api: Any, previous: Any) -> dict[str, bool] | None:
    """Inspect only field presence on a new native identity HTTP response.

    This diagnostic is not identity evidence. Never export headers, body values,
    request data, URLs or exceptions. Stale, redirected, foreign, oversized and
    ambiguous responses have no diagnostic result. No network call is made.
    """
    try:
        from requests import PreparedRequest, Response

        response = getattr(api, "response", None)
        endpoint = "https://api.kraken.com/0/private/GetApiKeyInfo"
        if (type(response) is not Response or response is previous
                or response.status_code != 200 or response.url != endpoint
                or response.history or type(response.request) is not PreparedRequest
                or response.request.method != "POST" or response.request.url != endpoint):
            return None
        body = response.content
        if type(body) is not bytes or not 0 < len(body) <= 65536:
            return None

        def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("ambiguous_http_diagnostic")
                result[key] = value
            return result

        payload = json.loads(body, object_pairs_hook=unique)
        if (type(payload) is not dict or payload.get("error") != []
                or type(payload.get("result")) is not dict):
            return None
        return {field: field in payload["result"] for field in ("apiKey", "validUntil")}
    except Exception:
        return None


def query_identity_with_timing(api: Any, params: Any) -> Any:
    """Call the existing API once, after canonical lock/rate admission.

    Called only by KrakenBroker's GetApiKeyInfo branch. The broker's existing
    API wrapper still owns authentication, nonce sequencing and HTTP timeouts.
    No cached/API-supplied timestamp can populate this receipt.
    """
    capture = getattr(_LOCAL, "capture", None)
    if capture is None:
        return api.query_private("GetApiKeyInfo", params)
    capture.attempts += 1
    capture.api_matched = api is capture.api and api is not None
    capture.started = capture.clock()
    started_monotonic = time.monotonic()
    capture.monotonic_started = started_monotonic
    previous = getattr(api, "response", None) if capture.inspect_http_fields else None
    result = api.query_private("GetApiKeyInfo", params)
    capture.elapsed = time.monotonic() - started_monotonic
    capture.finished = capture.clock()
    capture.response = result
    if capture.inspect_http_fields and capture.api_matched and capture.attempts == 1:
        capture.http_field_presence = _http_field_presence(api, previous)
    return result
