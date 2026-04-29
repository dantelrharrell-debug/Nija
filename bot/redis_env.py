"""Redis environment variable resolution helpers."""

from __future__ import annotations

import os
from urllib.parse import quote


_REDIS_URL_ENV_NAMES = (
    "NIJA_REDIS_URL",
    "REDIS_URL",
    "REDIS_PRIVATE_URL",
    "REDIS_PUBLIC_URL",
)


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
            return value
    _source, _component_url = _build_component_redis_url()
    if _component_url:
        return _component_url
    return ""


def get_redis_url_source() -> str:
    """Return the environment variable name supplying the current Redis URL."""
    for name in _REDIS_URL_ENV_NAMES:
        value = os.getenv(name, "").strip()
        if value:
            return name
    _source, _component_url = _build_component_redis_url()
    if _component_url:
        return _source
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
            seen_urls.add(value)
            result.append((name, value))
    component_source, component_url = _build_component_redis_url()
    if component_url and component_url not in seen_urls:
        result.append((component_source, component_url))
    return result