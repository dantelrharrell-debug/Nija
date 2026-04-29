"""Redis environment variable resolution helpers."""

from __future__ import annotations

import os
from urllib.parse import quote, urlsplit, urlunsplit


_REDIS_URL_ENV_NAMES = (
    "NIJA_REDIS_URL",
    "REDIS_URL",
    "REDIS_PRIVATE_URL",
    "REDIS_PUBLIC_URL",
)


def _is_railway_proxy_host(hostname: str) -> bool:
    """Return True when the hostname matches Railway's public TCP proxy."""
    return bool(hostname) and hostname.endswith(".proxy.rlwy.net")


def _normalize_redis_url(source: str, url: str) -> tuple[str, str]:
    """Normalize operator-provided Redis URLs when provider quirks are known.

    Railway's public TCP proxy speaks plain Redis behind the proxy endpoint.
    Operators sometimes paste the proxy URL as ``rediss://`` which makes redis-py
    attempt a TLS handshake and fail with EOF / connection-reset errors.
    """
    try:
        parsed = urlsplit(url)
    except ValueError:
        return source, url

    if parsed.scheme != "rediss" or not _is_railway_proxy_host(parsed.hostname or ""):
        return source, url

    normalized_url = urlunsplit(("redis", parsed.netloc, parsed.path, parsed.query, parsed.fragment))
    return f"{source} [normalized Railway proxy scheme]", normalized_url


def _alternate_railway_proxy_scheme(source: str, url: str) -> tuple[str, str] | None:
    """Return a synthetic fallback URL using the opposite Redis URL scheme.

    Some Railway proxy setups behave differently across environments; probing both
    redis:// and rediss:// improves startup resilience while still preserving
    fail-closed semantics when neither endpoint responds.
    """
    try:
        parsed = urlsplit(url)
    except ValueError:
        return None

    host = parsed.hostname or ""
    if not _is_railway_proxy_host(host):
        return None
    if parsed.scheme not in {"redis", "rediss"}:
        return None

    alt_scheme = "rediss" if parsed.scheme == "redis" else "redis"
    alt_url = urlunsplit((alt_scheme, parsed.netloc, parsed.path, parsed.query, parsed.fragment))
    return f"{source} [alternate Railway proxy scheme]", alt_url


def _first_nonempty(*names: str) -> str:
    """Return first non-empty environment variable value from names."""
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


def _build_component_redis_url() -> tuple[str, str]:
    """Build Redis URL from Railway/component-style env vars when possible."""
    # Prefer Railway TCP proxy settings when present.
    host = _first_nonempty("RAILWAY_TCP_PROXY_DOMAIN", "REDIS_HOST", "REDISHOST")
    port = _first_nonempty("RAILWAY_TCP_PROXY_PORT", "REDIS_PORT", "REDISPORT")

    # Common provider aliases: REDIS_PASSWORD, REDISPASSWORD, REDIS_TOKEN.
    password = _first_nonempty("REDIS_PASSWORD", "REDISPASSWORD", "REDIS_TOKEN")
    username = _first_nonempty("REDIS_USERNAME", "REDIS_USER", "REDISUSER") or "default"
    db = _first_nonempty("REDIS_DB", "REDIS_DATABASE") or "0"

    if not host or not port:
        return "", ""

    # Accept integer-ish ports only; malformed values should not generate URLs.
    try:
        int(port)
    except (TypeError, ValueError):
        return "", ""

    auth = ""
    if password:
        auth = f"{quote(username, safe='')}:{quote(password, safe='')}@"

    # The source label is diagnostic text used in startup logging.
    if os.getenv("RAILWAY_TCP_PROXY_DOMAIN", "").strip() and os.getenv("RAILWAY_TCP_PROXY_PORT", "").strip():
        source = "RAILWAY_TCP_PROXY_DOMAIN+RAILWAY_TCP_PROXY_PORT"
    else:
        source = "REDIS_HOST+REDIS_PORT"

    return source, f"redis://{auth}{host}:{port}/{db}"


def get_redis_url() -> str:
    """Return the first configured Redis URL from supported environment vars."""
    for name in _REDIS_URL_ENV_NAMES:
        value = os.getenv(name, "").strip()
        if value:
            _normalized_source, _normalized_value = _normalize_redis_url(name, value)
            return _normalized_value
    _source, _component_url = _build_component_redis_url()
    if _component_url:
        _normalized_source, _normalized_value = _normalize_redis_url(_source, _component_url)
        return _normalized_value
    return ""


def get_redis_url_source() -> str:
    """Return the environment variable name supplying the current Redis URL."""
    for name in _REDIS_URL_ENV_NAMES:
        value = os.getenv(name, "").strip()
        if value:
            _normalized_source, _normalized_value = _normalize_redis_url(name, value)
            return _normalized_source
    _source, _component_url = _build_component_redis_url()
    if _component_url:
        _normalized_source, _normalized_value = _normalize_redis_url(_source, _component_url)
        return _normalized_source
    return ""


def get_redis_env_presence() -> dict[str, bool]:
    """Return whether each supported Redis URL environment variable is set."""
    return {name: bool(os.getenv(name, "").strip()) for name in _REDIS_URL_ENV_NAMES}


def get_all_redis_urls() -> list[tuple[str, str]]:
    """Return all configured Redis URLs as (source_env_name, url) in priority order."""
    result = []
    seen_urls = set()
    for name in _REDIS_URL_ENV_NAMES:
        value = os.getenv(name, "").strip()
        if value:
            normalized_source, normalized_value = _normalize_redis_url(name, value)
            if normalized_value not in seen_urls:
                seen_urls.add(normalized_value)
                result.append((normalized_source, normalized_value))
            alternate = _alternate_railway_proxy_scheme(normalized_source, normalized_value)
            if alternate:
                alt_source, alt_value = alternate
                if alt_value not in seen_urls:
                    seen_urls.add(alt_value)
                    result.append((alt_source, alt_value))
    component_source, component_url = _build_component_redis_url()
    if component_url:
        normalized_source, normalized_value = _normalize_redis_url(component_source, component_url)
        if normalized_value not in seen_urls:
            result.append((normalized_source, normalized_value))
            seen_urls.add(normalized_value)
        alternate = _alternate_railway_proxy_scheme(normalized_source, normalized_value)
        if alternate:
            alt_source, alt_value = alternate
            if alt_value not in seen_urls:
                result.append((alt_source, alt_value))
    return result
