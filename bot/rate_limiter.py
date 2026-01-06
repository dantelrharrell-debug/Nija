"""
Simple thread-safe rate limiter for protecting rate-limited calls (e.g. balance cache).
Provides a blocking acquire() and a context manager .limit() to be used around critical calls.
This implementation is intentionally conservative and keeps logging and safety guards.
"""
import time
import threading
import collections
import logging
from contextlib import contextmanager

logger = logging.getLogger(__name__)

class RateLimiter:
    """A simple token-bucket-like limiter based on timestamps.

    Usage:
        limiter = RateLimiter(max_calls=5, period=1.0)
        with limiter.limit():
            do_rate_limited_work()

    Methods:
        acquire(): block until a slot is available
        try_acquire(): attempt to take a slot without blocking, return bool
        limit(): context manager wrapper for acquire
    """

    def __init__(self, max_calls=5, period=1.0):
        self.max_calls = int(max_calls)
        self.period = float(period)
        self._lock = threading.Lock()
        self._calls = collections.deque()

    def _cleanup(self, now):
        # Drop timestamps that are outside the window
        while self._calls and (now - self._calls[0]) >= self.period:
            self._calls.popleft()

    def acquire(self):
        """Block until a call slot is available. Returns when a slot is reserved."""
        while True:
            with self._lock:
                now = time.monotonic()
                self._cleanup(now)
                if len(self._calls) < self.max_calls:
                    self._calls.append(now)
                    logger.debug("RateLimiter: acquired slot (calls=%d/%d)", len(self._calls), self.max_calls)
                    return
                # need to wait until the earliest timestamp expires
                earliest = self._calls[0]
                wait = self.period - (now - earliest)
                # Safety: don't sleep negative
                if wait <= 0:
                    continue
                logger.debug("RateLimiter: rate limit reached, sleeping for %.3f seconds", wait)
            # Sleep outside the lock to allow other threads to progress
            time.sleep(wait)

    def try_acquire(self):
        """Attempt to acquire without blocking. Returns True if acquired, False otherwise."""
        with self._lock:
            now = time.monotonic()
            self._cleanup(now)
            if len(self._calls) < self.max_calls:
                self._calls.append(now)
                logger.debug("RateLimiter: try_acquire succeeded")
                return True
            logger.debug("RateLimiter: try_acquire failed")
            return False

    @contextmanager
    def limit(self):
        """Context manager to wrap a rate-limited call."""
        self.acquire()
        try:
            yield
        finally:
            # No explicit release necessary because we rely on time window
            pass


# Provide a no-op fallback for environments that don't want rate limiting
class _NoOpRateLimiter:
    def __init__(self, *_, **__):
        pass
    def acquire(self):
        return
    def try_acquire(self):
        return True
    @contextmanager
    def limit(self):
        yield

# Helper factory that will produce a real limiter; callers can swap parameters as needed
def make_rate_limiter(max_calls=5, period=1.0):
    try:
        return RateLimiter(max_calls=max_calls, period=period)
    except Exception:
        logger.exception("Failed to instantiate RateLimiter, falling back to no-op limiter")
        return _NoOpRateLimiter()
