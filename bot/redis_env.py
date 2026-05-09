"""Redis environment variable resolution helpers."""

from __future__ import annotations

import os



_REDIS_URL_ENV_NAMES = (
    "NIJA_REDIS_URL",
    "REDIS_TLS_URL",
    "REDIS_URL",
    "REDIS_PRIVATE_URL",
    "REDIS_PUBLIC_URL",
)


def _strip_wrapping_quotes(value: str) -> str:
    """Trim matching single or double quotes from environment values."""
    value = (value or "").strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1].strip()
    return value


def get_redis_url() -> str:
    """Return NIJA_REDIS_URL directly without reconstruction or host/port parsing."""
    redis_url = os.getenv("NIJA_REDIS_URL")
    if not redis_url:
        return ""
    assert redis_url.startswith("redis://") or redis_url.startswith("rediss://")
    return redis_url


def _get_redis_url_validated() -> str:
    """Best-effort validated Redis URL without raising AssertionError in production paths."""
    redis_url = os.getenv("NIJA_REDIS_URL")
    if not redis_url:
        return ""
    if not (redis_url.startswith("redis://") or redis_url.startswith("rediss://")):
        return ""
    return redis_url


def _normalize_source_name(name: str) -> str:
    """Return canonical source name for diagnostics."""
    return "NIJA_REDIS_URL" if name == "NIJA_REDIS_URL" else name


def _iter_configured_redis_urls() -> list[tuple[str, str]]:
    """Return configured URL env vars in priority order without rewriting values."""
    configured: list[tuple[str, str]] = []
    for name in _REDIS_URL_ENV_NAMES:
        value = _strip_wrapping_quotes(os.getenv(name, ""))
        if value and (value.startswith("redis://") or value.startswith("rediss://")):
            configured.append((_normalize_source_name(name), value))
    return configured


def get_redis_url_source() -> str:
    """Return the environment variable name supplying the current Redis URL."""
    redis_url = _get_redis_url_validated()
    if redis_url:
        return "NIJA_REDIS_URL"
    return ""


def get_redis_env_presence() -> dict[str, bool]:
    """Return whether each supported Redis URL environment variable is set."""
    return {name: bool(_strip_wrapping_quotes(os.getenv(name, ""))) for name in _REDIS_URL_ENV_NAMES}


def get_redis_resolution_diagnostics() -> dict[str, object]:
    """Return Redis resolution diagnostics for startup logs."""
    return {
        "url_env_presence": get_redis_env_presence(),
        "component_host_present": False,
        "component_port_present": False,
        "component_port_valid": False,
        "component_source": None,
        "component_endpoint": None,
        "resolved_url_present": bool(_get_redis_url_validated()),
        "resolved_source": get_redis_url_source() or None,
    }


def get_all_redis_urls() -> list[tuple[str, str]]:
    """Return configured Redis URLs in priority order without rewriting values."""
    return _iter_configured_redis_urls()
