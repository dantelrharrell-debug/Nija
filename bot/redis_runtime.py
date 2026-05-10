"""Shared Redis runtime helpers for startup-safe, bounded operations."""

from __future__ import annotations

import os
import signal
import socket
import threading
import time
from types import FrameType
from typing import Any, Callable, Iterable, Optional
from urllib.parse import urlparse

import redis  # type: ignore[import]

from bot.redis_env import get_redis_url


def _detect_non_redis_http_endpoint(url: str) -> str:
    """Return error hint when endpoint looks like HTTP instead of Redis."""
    try:
        parsed = urlparse((url or "").strip())
        # Avoid plaintext probing TLS endpoints; rediss:// can reject the probe
        # and mimic an HTTP response even when Redis is healthy.
        if (parsed.scheme or "").lower() == "rediss":
            return ""
        host = parsed.hostname
        port = parsed.port
        if not host or port is None:
            return ""
        with socket.create_connection((host, int(port)), timeout=2.5) as sock:
            sock.sendall(b"*1\r\n$4\r\nPING\r\n")
            data = sock.recv(128)
        if not data:
            return ""
        head = data[:80].decode("latin-1", errors="ignore")
        if data.startswith(b"HTTP/") or b"<!DOCTYPE HTML" in data or "Bad request syntax" in head:
            return (
                "Redis URL endpoint responded as HTTP/non-Redis. "
                "Verify NIJA_REDIS_URL points to Railway Redis Connect URL."
            )
    except Exception:
        return ""
    return ""


def create_redis(
    url: Optional[str] = None,
    *,
    decode_responses: bool = True,
    socket_timeout: int = 5,
    socket_connect_timeout: int = 5,
) -> redis.Redis:
    """Create Redis client from URL without host/port reconstruction."""
    raw_url = (url or get_redis_url()).strip()
    if not raw_url:
        raise RuntimeError("Redis URL is missing")

    assert raw_url.startswith("redis://") or raw_url.startswith("rediss://")

    kwargs: dict[str, Any] = {
        "decode_responses": decode_responses,
        "socket_timeout": socket_timeout,
        "socket_connect_timeout": socket_connect_timeout,
    }
    parsed = urlparse(raw_url)
    tls_insecure_raw = os.getenv("NIJA_REDIS_TLS_INSECURE", "auto").strip().lower()
    tls_insecure = tls_insecure_raw in {"1", "true", "yes", "on", "enabled"}
    tls_auto = tls_insecure_raw in {"", "auto"}
    is_railway_host = ".rlwy.net" in (parsed.hostname or "").lower()
    if (parsed.scheme or "").lower() == "rediss" and (
        tls_insecure or (tls_auto and is_railway_host)
    ):
        # Railway viaduct proxy uses a self-signed / mismatched certificate.
        # Disable both cert chain and hostname verification so TLS still
        # encrypts the channel without failing the handshake.
        kwargs["ssl_cert_reqs"] = "none"
        kwargs["ssl_check_hostname"] = False

    return redis.Redis.from_url(raw_url, **kwargs)


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
    """Connect to Redis with scheme fallback for Railway proxy endpoints."""
    primary_url = (url or get_redis_url()).strip()
    if not primary_url:
        raise RuntimeError("Redis URL is missing")

    non_redis_hint = _detect_non_redis_http_endpoint(primary_url)
    if non_redis_hint:
        raise RuntimeError(non_redis_hint)

    candidates = [primary_url]
    allow_plain_fallback_raw = os.getenv("NIJA_REDIS_ALLOW_PLAIN_FALLBACK", "auto").strip().lower()
    allow_plain_fallback = allow_plain_fallback_raw in {"1", "true", "yes", "on", "enabled"}
    allow_plain_fallback_auto = allow_plain_fallback_raw in {"", "auto"}
    primary_is_tls = primary_url.startswith("rediss://")
    primary_hostname = (urlparse(primary_url).hostname or "").lower()
    is_railway_host = ".rlwy.net" in primary_hostname
    is_railway_proxy = ".proxy.rlwy.net" in primary_hostname
    force_tls_env = os.getenv("NIJA_REDIS_FORCE_TLS", "true").strip().lower() in {
        "1", "true", "yes", "on", "enabled"
    }
    # For Railway-managed Redis hosts (*.rlwy.net), allow a controlled rediss://
    # -> redis:// downgrade when fallback is explicitly enabled or left at auto.
    # For Railway viaduct proxy endpoints (*.proxy.rlwy.net), also try rediss://
    # when the primary URL is plain redis:// and TLS is forced.
    allow_tls_downgrade = is_railway_host and (allow_plain_fallback or allow_plain_fallback_auto)
    if primary_is_tls and allow_tls_downgrade:
        candidates.append(primary_url.replace("rediss://", "redis://", 1))
    elif not primary_is_tls and is_railway_proxy and force_tls_env:
        candidates.append(primary_url.replace("redis://", "rediss://", 1))

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
                if "timeout" in msg or "handshake" in msg or "ssl" in msg or "record layer" in msg:
                    log(
                        "Redis TLS/scheme mismatch suspected against Railway proxy; "
                        "trying alternative redis URL scheme for the same endpoint..."
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
