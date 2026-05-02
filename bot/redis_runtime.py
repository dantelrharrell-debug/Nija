"""Shared Redis runtime helpers for startup-safe, bounded operations."""

from __future__ import annotations

import os
import signal
import threading
import time
from types import FrameType
from typing import Any, Callable, Iterable, Optional
from urllib.parse import urlparse

import redis  # type: ignore[import]


def create_redis(
    url: Optional[str] = None,
    *,
    decode_responses: bool = True,
    socket_timeout: int = 5,
    socket_connect_timeout: int = 5,
) -> redis.Redis:
    """Create Redis client from URL with explicit parsed configuration."""
    raw_url = (url or os.getenv("NIJA_REDIS_URL", "")).strip()
    if not raw_url:
        raise RuntimeError("NIJA_REDIS_URL is missing")

    parsed = urlparse(raw_url)
    if parsed.scheme not in {"redis", "rediss"}:
        raise RuntimeError("NIJA_REDIS_URL must start with redis:// or rediss://")
    if not parsed.hostname or not parsed.port:
        raise RuntimeError("NIJA_REDIS_URL must include host and port")

    db = 0
    try:
        db = int((parsed.path or "/0").lstrip("/") or "0")
    except (TypeError, ValueError):
        db = 0

    return redis.Redis(
        host=parsed.hostname,
        port=parsed.port,
        username=parsed.username or "default",
        password=parsed.password,
        db=db,
        ssl=parsed.scheme == "rediss",
        ssl_cert_reqs=None,
        socket_timeout=socket_timeout,
        socket_connect_timeout=socket_connect_timeout,
        decode_responses=decode_responses,
    )


def wait_for_redis_ready(
    client: redis.Redis,
    *,
    retries: int = 5,
    delay_s: float = 2.0,
    log: Callable[[str], None] = print,
) -> None:
    """Block until Redis ping succeeds, else raise after bounded retries."""
    log("PINGING REDIS FIRST")
    for i in range(max(1, retries)):
        try:
            client.ping()
            log("REDIS OK - CONTINUING")
            return
        except Exception as exc:
            if i < retries - 1:
                log(f"Redis not ready ({i + 1}/{retries}): {exc}")
                time.sleep(delay_s)
            else:
                raise RuntimeError("Redis never became available") from exc


def connect_redis_with_fallback(
    *,
    url: Optional[str] = None,
    decode_responses: bool = True,
    socket_timeout: int = 5,
    socket_connect_timeout: int = 5,
    retries: int = 5,
    delay_s: float = 2.0,
    log: Callable[[str], None] = print,
) -> tuple[redis.Redis, str]:
    """Connect to Redis and fallback to plain Railway proxy URL on TLS timeout."""
    primary_url = (url or os.getenv("NIJA_REDIS_URL", "")).strip()
    if not primary_url:
        raise RuntimeError("NIJA_REDIS_URL is missing")

    candidates = [primary_url]
    parsed = urlparse(primary_url)
    if (
        parsed.scheme == "rediss"
        and (parsed.hostname or "").lower().endswith(".proxy.rlwy.net")
    ):
        candidates.append(primary_url.replace("rediss://", "redis://", 1))

    last_error: Optional[Exception] = None
    for idx, candidate_url in enumerate(candidates):
        try:
            client = create_redis(
                candidate_url,
                decode_responses=decode_responses,
                socket_timeout=socket_timeout,
                socket_connect_timeout=socket_connect_timeout,
            )
            wait_for_redis_ready(client, retries=retries, delay_s=delay_s, log=log)
            if idx > 0:
                log("Redis Railway proxy reachable via plain redis:// fallback")
            return client, candidate_url
        except Exception as exc:
            last_error = exc
            if idx == 0 and len(candidates) > 1:
                msg = str(exc).lower()
                if "timeout" in msg or "handshake" in msg or "ssl" in msg:
                    log(
                        "Redis TLS handshake timed out against Railway proxy; "
                        "trying plain redis:// fallback for the same endpoint..."
                    )
                    continue
                break

    raise RuntimeError("Redis never became available") from last_error


def safe_redis(fn: Callable[[], Any], *, default: Any = None, log: Callable[[str], None] = print) -> Any:
    """Execute Redis operation safely and return default on failure."""
    try:
        return fn()
    except Exception as exc:
        log(f"Redis error: {exc}")
        return default


def _timeout_handler(signum: int, frame: Optional[FrameType]) -> None:
    raise TimeoutError("Operation timed out")


def install_timeout_handler() -> None:
    """Install SIGALRM timeout handler (main thread only)."""
    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGALRM, _timeout_handler)


def run_with_timeout(timeout_s: int, fn: Callable[[], Any]) -> Any:
    """Run callable with signal-alarm timeout on main thread where possible."""
    if timeout_s <= 0:
        return fn()
    if threading.current_thread() is not threading.main_thread():
        return fn()

    install_timeout_handler()
    signal.alarm(timeout_s)
    try:
        return fn()
    finally:
        signal.alarm(0)


def safe_scan(
    redis_client: redis.Redis,
    *,
    match: Optional[str] = None,
    count: int = 100,
    max_iters: int = 10,
) -> Iterable[str]:
    """Bounded cursor scan generator."""
    cursor = 0
    for _ in range(max(1, max_iters)):
        cursor, keys = redis_client.scan(cursor=cursor, match=match, count=count)
        for key in keys:
            yield key
        if cursor == 0:
            break


def clear_nonce_state_safe(
    redis_client: redis.Redis,
    *,
    patterns: list[str],
    explicit_keys: Optional[set[str]] = None,
    timeout_s: int = 5,
    log: Callable[[str], None] = print,
) -> int:
    """Bounded nonce-key cleanup with timeout-safe scan/delete."""
    log("CLEAR NONCE START")
    start = time.time()
    keys = set(explicit_keys or set())

    for pattern in patterns:
        prefix = pattern.rstrip("*")
        for key in safe_scan(redis_client, match=pattern):
            if time.time() - start > timeout_s:
                log("Nonce reset timeout - aborting")
                log("CLEAR NONCE DONE")
                return 0
            if prefix and not str(key).startswith(prefix):
                continue
            keys.add(key)

    deleted = 0
    for key in sorted(keys):
        if time.time() - start > timeout_s:
            log("Nonce reset timeout - aborting")
            break
        try:
            if redis_client.delete(key):
                deleted += 1
        except Exception as exc:
            log(f"Delete failed: {exc}")

    log("CLEAR NONCE DONE")
    return deleted
