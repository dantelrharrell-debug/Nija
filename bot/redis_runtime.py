"""Shared Redis runtime helpers for startup-safe, bounded operations."""

from __future__ import annotations

import os
import signal
import socket
import ssl
import threading
import time
from types import FrameType
from typing import Any, Callable, Iterable, Optional
from urllib.parse import urlparse

import redis  # type: ignore[import]

from bot.redis_env import get_all_redis_urls, get_redis_url


def _is_tlsish_connection_error(exc: Exception) -> bool:
    """Return True when exception text suggests TLS/scheme mismatch."""
    msg = str(exc).lower()
    return (
        "timeout" in msg
        or "handshake" in msg
        or "ssl" in msg
        or "record layer" in msg
        or "wrong version number" in msg
    )


def _redact_url_for_log(url: str) -> str:
    """Redact auth details for safe logs."""
    parsed = urlparse((url or "").strip())
    host = parsed.hostname or "<unknown-host>"
    try:
        port = parsed.port
    except ValueError:
        port = None
    return f"{parsed.scheme}://***@{host}:{port or '<unknown-port>'}"


def get_redis_tls_kwargs(url: str) -> dict[str, Any]:
    """Return TLS keyword args for ``redis.Redis.from_url``.

    Parameters
    ----------
    url:
        Redis connection URL. TLS kwargs are returned only for ``rediss://`` URLs.

    Returns
    -------
    dict[str, Any]
        SSL/TLS keyword arguments suitable for redis-py connection creation.
        Policy is strict: ssl=True, ssl_cert_reqs='required',
        ssl_check_hostname=True for all rediss:// connections.
        Optional CA pinning via NIJA_REDIS_TLS_CA_CERT.

    SECURITY NOTE
    -------------
    NIJA_REDIS_TLS_INSECURE and NIJA_REDIS_FORCE_TLS are intentionally
    ignored.  All rediss:// connections use strict TLS validation.
    """
    raw_url = (url or "").strip()
    parsed = urlparse(raw_url)
    if (parsed.scheme or "").lower() != "rediss":
        return {}

    tls_ca_certs = os.getenv("NIJA_REDIS_TLS_CA_CERT", "").strip()

    if tls_ca_certs:
        return {
            "ssl": True,
            "ssl_cert_reqs": ssl.CERT_REQUIRED,
            "ssl_check_hostname": True,
            "ssl_ca_certs": tls_ca_certs,
        }

    return {
        "ssl": True,
        "ssl_cert_reqs": ssl.CERT_REQUIRED,
        "ssl_check_hostname": True,
    }


def _prioritized_alt_urls(primary_url: str) -> list[str]:
    """Return non-primary configured Redis URLs, preferring non-proxy endpoints."""
    primary = (primary_url or "").strip()
    configured_urls = [url for _, url in get_all_redis_urls() if url]

    unique: list[str] = []
    seen: set[str] = set()
    for candidate in configured_urls:
        raw = candidate.strip()
        if not raw or raw == primary or raw in seen:
            continue
        seen.add(raw)
        unique.append(raw)

    def _priority(url: str) -> tuple[int, str]:
        host = (urlparse(url).hostname or "").lower()
        if host.endswith(".railway.internal"):
            return (0, host)
        if host.endswith(".proxy.rlwy.net"):
            return (3, host)
        if ".rlwy.net" in host:
            return (2, host)
        return (1, host)

    return sorted(unique, key=_priority)


def _detect_non_redis_http_endpoint(url: str) -> str:
    """Return error hint when endpoint looks like HTTP instead of Redis."""
    try:
        parsed = urlparse((url or "").strip())
        scheme = (parsed.scheme or "").lower()
        # Avoid plaintext probing TLS endpoints; rediss:// can reject the probe
        # and mimic an HTTP response even when Redis is healthy.
        if scheme == "rediss":
            return ""
        host = parsed.hostname
        port = parsed.port
        if not host or port is None:
            return ""
        # Railway public proxy endpoints can emit HTTP-like errors when a plain
        # redis:// probe is sent to a TLS-only listener; that is a scheme/TLS
        # mismatch, not proof that the endpoint is non-Redis.
        if ".proxy.rlwy.net" in host.lower():
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
    """Create Redis client from URL with strict TLS enforcement.

    Uses the provided URL (or NIJA_REDIS_URL from environment) and applies
    strict TLS kwargs for rediss:// connections.  The Railway public proxy
    endpoint requires rediss:// with ssl=True and ssl_cert_reqs='required'.
    """
    import redis as _redis
    resolved_url = (url or "").strip() or os.environ.get("NIJA_REDIS_URL", "").strip()
    if not resolved_url:
        raise RuntimeError(
            "Redis URL is not configured. Set NIJA_REDIS_URL to a valid "
            "rediss://default:<PASSWORD>@viaduct.proxy.rlwy.net:<PORT> endpoint."
        )
    tls_kwargs = get_redis_tls_kwargs(resolved_url)
    r = _redis.Redis.from_url(
        resolved_url,
        decode_responses=decode_responses,
        socket_timeout=socket_timeout,
        socket_connect_timeout=socket_connect_timeout,
        health_check_interval=30,
        retry_on_timeout=True,
        **tls_kwargs,
    )
    return r


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
    """Connect to Redis with strict TLS enforcement.

    Uses the provided URL (or NIJA_REDIS_URL) with strict TLS for rediss://
    endpoints.  Plain redis:// downgrade and TLS-insecure fallbacks are
    permanently disabled.  Railway proxy endpoints (.proxy.rlwy.net) are
    automatically promoted to rediss:// if configured as redis://.

    SECURITY NOTE
    -------------
    NIJA_REDIS_ALLOW_PLAIN_FALLBACK and NIJA_REDIS_FORCE_TLS are ignored.
    TLS downgrade from rediss:// to redis:// is never permitted.
    """
    primary_url = (url or get_redis_url()).strip()
    if not primary_url:
        raise RuntimeError(
            "Redis URL is missing. Set NIJA_REDIS_URL to a valid "
            "rediss://default:<PASSWORD>@viaduct.proxy.rlwy.net:<PORT> endpoint."
        )

    non_redis_hint = _detect_non_redis_http_endpoint(primary_url)
    if non_redis_hint:
        raise RuntimeError(non_redis_hint)

    # Promote Railway proxy redis:// to rediss:// — TLS is required.
    primary_hostname = (urlparse(primary_url).hostname or "").lower()
    is_railway_proxy = ".proxy.rlwy.net" in primary_hostname
    if not primary_url.startswith("rediss://") and is_railway_proxy:
        primary_url = primary_url.replace("redis://", "rediss://", 1)
        log(f"Railway proxy endpoint promoted to rediss:// for TLS enforcement")

    # Only try the primary URL and alternate configured URLs.
    # No TLS downgrade candidates, no plain fallback.
    candidates: list[tuple[str, bool]] = [(primary_url, False)]

    # Add alternate configured URLs (internal/private first, then other endpoints).
    for alt_url in _prioritized_alt_urls(primary_url):
        candidates.append((alt_url, False))

    last_error: Optional[Exception] = None
    for idx, (candidate_url, _) in enumerate(candidates):
        try:
            client = create_redis(
                candidate_url,
                decode_responses=decode_responses,
                socket_timeout=socket_timeout,
                socket_connect_timeout=socket_connect_timeout,
            )
            wait_for_redis_ready(client, retries=retries, delay_s=delay_s, log=log)
            if idx > 0:
                log(f"Redis connected using fallback candidate: {_redact_url_for_log(candidate_url)}")
            return client, candidate_url
        except Exception as exc:
            last_error = exc
            has_more_candidates = idx < len(candidates) - 1
            if not has_more_candidates:
                break
            log(
                "Redis candidate failed; trying next configured endpoint: "
                f"{_redact_url_for_log(candidate_url)}"
            )
            continue

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
