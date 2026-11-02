"""Call-scoped timing at the existing Kraken identity transport boundary.

Queue/rate-limit waits precede observation, but transport and post-read delays
consume the unchanged evidence lifetime. No response cache, nonce owner, client,
approval, or collector is created here. Gateway and uninstrumented calls retain
the provider's conservative whole-call freshness check.
"""
from __future__ import annotations

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
def capture_identity_read(api: Any, clock: Callable[[], float]) -> Iterator[IdentityReadTiming]:
    """Scope timing to this thread, exact API object and provider invocation."""
    previous = getattr(_LOCAL, "capture", None)
    capture = IdentityReadTiming(api, clock)
    _LOCAL.capture = capture
    try:
        yield capture
    finally:
        _LOCAL.capture = previous


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
    result = api.query_private("GetApiKeyInfo", params)
    capture.elapsed = time.monotonic() - started_monotonic
    capture.finished = capture.clock()
    capture.response = result
    return result
