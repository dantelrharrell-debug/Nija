"""
Simple rate limiter + TTL cache for NIJA bot.

- RateLimiter: per-endpoint minimum interval (derived from requests/min)
  usage: rate_limiter.call(key, lambda: client.get_accounts(...))
- TTLCache: in-memory time-based cache for short lived values (balances)

This is intentionally lightweight (no external deps) and safe for single-process use.
If you run multiple processes/workers, switch TTLCache to Redis (hooks included).
"""
from threading import Lock
import time
from typing import Any, Callable, Optional, Dict


class TTLCache:
    def __init__(self, ttl_seconds: int = 45):
        self.ttl = int(ttl_seconds)
        self._store: Dict[str, tuple[float, Any]] = {}
        self._lock = Lock()

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            v = self._store.get(key)
            if not v:
                return None
            ts, value = v
            if time.time() - ts > self.ttl:
                del self._store[key]
                return None
            return value

    def set(self, key: str, value: Any):
        with self._lock:
            self._store[key] = (time.time(), value)

    def invalidate(self, key: str):
        with self._lock:
            if key in self._store:
                del self._store[key]

    def clear(self):
        with self._lock:
            self._store.clear()


class RateLimiter:
    """
    Very small per-key rate limiter based on minimum interval between calls.

    - default_per_min: default requests per minute -> converted to min_interval_seconds
    - per_key_overrides: optional dict mapping keys to req_per_min values

    Usage:
        rl = RateLimiter(default_per_min=12)
        result = rl.call("get_accounts", lambda: client.get_accounts())

    The call() method will block (sleep) if the last call for the key was too recent.
    It returns the wrapped function's return value (or raises exceptions from the function).
    """
    def __init__(self, default_per_min: int = 12, per_key_overrides: Optional[Dict[str, int]] = None):
        self.default_per_min = int(default_per_min) if default_per_min > 0 else 12
        self.per_key_overrides = per_key_overrides or {}
        self._last_called: Dict[str, float] = {}
        self._locks: Dict[str, Lock] = {}
        self._global_lock = Lock()

    @staticmethod
    def _per_min_to_interval(per_min: int) -> float:
        # requests per minute -> seconds per request
        per_min = max(1, int(per_min))
        return 60.0 / per_min

    def _get_interval(self, key: str) -> float:
        per_min = self.per_key_overrides.get(key, self.default_per_min)
        return self._per_min_to_interval(per_min)

    def _get_lock(self, key: str) -> Lock:
        with self._global_lock:
            if key not in self._locks:
                self._locks[key] = Lock()
            return self._locks[key]

    def call(self, key: str, fn: Callable[[], Any]) -> Any:
        """
        Execute fn() while enforcing inter-call delay for `key`.
        This blocks the current thread until the request may proceed.
        """
        lock = self._get_lock(key)
        with lock:
            now = time.time()
            last = self._last_called.get(key, 0)
            interval = self._get_interval(key)
            delta = now - last
            if delta < interval:
                to_sleep = interval - delta
                # small jitter to help multi-process cases (not perfect without central store)
                jitter = min(0.2, to_sleep * 0.1)
                time.sleep(to_sleep + jitter)
            # Execute the function (propagate exceptions)
            result = fn()
            self._last_called[key] = time.time()
            return result
