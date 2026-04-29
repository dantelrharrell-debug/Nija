"""Redis environment variable resolution helpers."""

from __future__ import annotations

import os


_REDIS_URL_ENV_NAMES = (
    "NIJA_REDIS_URL",
    "REDIS_URL",
    "REDIS_PRIVATE_URL",
    "REDIS_PUBLIC_URL",
)


def get_redis_url() -> str:
    """Return the first configured Redis URL from supported environment vars."""
    for name in _REDIS_URL_ENV_NAMES:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


def get_redis_url_source() -> str:
    """Return the environment variable name supplying the current Redis URL."""
    for name in _REDIS_URL_ENV_NAMES:
        value = os.getenv(name, "").strip()
        if value:
            return name
    return ""


def get_redis_env_presence() -> dict[str, bool]:
    """Return whether each supported Redis URL environment variable is set."""
    return {name: bool(os.getenv(name, "").strip()) for name in _REDIS_URL_ENV_NAMES}


def get_all_redis_urls() -> list[tuple[str, str]]:
    """Return all configured Redis URLs as (source_env_name, url) in priority order."""
    result = []
    for name in _REDIS_URL_ENV_NAMES:
        value = os.getenv(name, "").strip()
        if value:
            result.append((name, value))
    return result