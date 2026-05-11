"""Redis environment variable resolution helpers."""

from __future__ import annotations

import os
from urllib.parse import quote
from urllib.parse import urlparse



_REDIS_URL_ENV_NAMES = (
    "NIJA_REDIS_URL",
    "REDIS_URL",
    "REDIS_TLS_URL",
    "REDIS_PRIVATE_URL",
    "REDIS_PUBLIC_URL",
)

_REDIS_COMPONENT_HOST_ENV_NAMES = (
    "RAILWAY_TCP_PROXY_DOMAIN",
    "REDISHOST",
    "REDIS_HOST",
)

_REDIS_COMPONENT_PORT_ENV_NAMES = (
    "RAILWAY_TCP_PROXY_PORT",
    "REDISPORT",
    "REDIS_PORT",
)

_REDIS_COMPONENT_PASSWORD_ENV_NAMES = (
    "REDIS_PASSWORD",
    "REDISPASSWORD",
)

_REDIS_COMPONENT_USER_ENV_NAMES = (
    "REDISUSER",
    "REDIS_USER",
)

_REDIS_COMPONENT_DB_ENV_NAMES = (
    "REDIS_DB",
    "REDISDB",
)


def _first_nonempty_env(names: tuple[str, ...]) -> tuple[str | None, str]:
    """Return first configured env value and the env name it came from."""
    for name in names:
        value = _strip_wrapping_quotes(os.getenv(name, ""))
        if value:
            return name, value
    return None, ""


def _is_truthy(value: str) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _build_component_redis_url() -> tuple[str, dict[str, object]]:
    """Build Redis URL from host/port/password style env vars when available."""
    host_source, host = _first_nonempty_env(_REDIS_COMPONENT_HOST_ENV_NAMES)
    port_source, port_raw = _first_nonempty_env(_REDIS_COMPONENT_PORT_ENV_NAMES)
    password_source, password = _first_nonempty_env(_REDIS_COMPONENT_PASSWORD_ENV_NAMES)
    user_source, user = _first_nonempty_env(_REDIS_COMPONENT_USER_ENV_NAMES)
    _, db_raw = _first_nonempty_env(_REDIS_COMPONENT_DB_ENV_NAMES)

    component_host_present = bool(host)
    component_port_present = bool(port_raw)
    component_port_valid = False
    endpoint = None
    built_url = ""

    port = 0
    if port_raw:
        try:
            port = int(port_raw)
            component_port_valid = 1 <= port <= 65535
        except (TypeError, ValueError):
            component_port_valid = False

    if component_host_present and component_port_valid:
        # Default to TLS only for Railway TCP proxy domain (public endpoint); private
        # internal Railway hosts (REDISHOST/REDIS_HOST) do not support TLS and must use
        # plain redis://.  NIJA_REDIS_FORCE_TLS can override in either direction.
        _host_needs_tls = host_source == "RAILWAY_TCP_PROXY_DOMAIN" or ".proxy.rlwy.net" in host.lower()
        _default_tls = "true" if _host_needs_tls else "false"
        scheme = "rediss" if _is_truthy(os.getenv("NIJA_REDIS_FORCE_TLS", _default_tls)) else "redis"
        endpoint = f"{host}:{port}"
        username = user or "default"
        db_value = db_raw or "0"
        if password:
            built_url = f"{scheme}://{quote(username, safe='')}:{quote(password, safe='')}@{host}:{port}/{db_value}"
        else:
            built_url = f"{scheme}://{quote(username, safe='')}@{host}:{port}/{db_value}"

    source_parts = [part for part in (host_source, port_source, password_source, user_source) if part]
    component_source = "+".join(source_parts) if source_parts else None
    if component_source is None and built_url:
        component_source = "components"

    return built_url, {
        "component_host_present": component_host_present,
        "component_port_present": component_port_present,
        "component_port_valid": component_port_valid,
        "component_source": component_source,
        "component_endpoint": endpoint,
    }


def _strip_wrapping_quotes(value: str) -> str:
    """Trim matching single or double quotes from environment values."""
    value = (value or "").strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1].strip()
    return value


def _maybe_strip_tls(url: str) -> str:
    """Downgrade rediss:// → redis:// when NIJA_REDIS_STRIP_TLS=true.

    Railway's internal (private) Redis endpoint does not support TLS, but
    some env vars (REDIS_TLS_URL) ship with the rediss:// scheme.  Setting
    NIJA_REDIS_STRIP_TLS=true converts the scheme so the bot can connect
    without a TLS handshake while keeping all other URL parts intact.
    """
    if _is_truthy(os.getenv("NIJA_REDIS_STRIP_TLS", "false")) and url.startswith("rediss://"):
        url = "redis://" + url[len("rediss://"):]
    return url


def get_redis_url() -> str:
    """Return the highest-priority configured Redis URL."""
    configured = _iter_configured_redis_urls()
    if configured:
        return _maybe_strip_tls(configured[0][1])
    return ""


def _get_redis_url_validated() -> str:
    """Best-effort validated Redis URL without raising AssertionError in production paths."""
    redis_url = get_redis_url()
    if not redis_url:
        return ""
    if not (redis_url.startswith("redis://") or redis_url.startswith("rediss://")):
        return ""
    return redis_url


def _normalize_source_name(name: str) -> str:
    """Return canonical source name for diagnostics."""
    return "NIJA_REDIS_URL" if name == "NIJA_REDIS_URL" else name


def _iter_configured_redis_urls() -> list[tuple[str, str]]:
    """Return configured URL env vars (and component-derived URL) in priority order."""
    configured: list[tuple[str, str]] = []
    for name in _REDIS_URL_ENV_NAMES:
        value = _strip_wrapping_quotes(os.getenv(name, ""))
        if value and (value.startswith("redis://") or value.startswith("rediss://")):
            configured.append((_normalize_source_name(name), value))
    component_url, component_diag = _build_component_redis_url()
    if component_url:
        component_source = str(component_diag.get("component_source") or "components")
        configured.append((f"COMPONENTS[{component_source}]", component_url))
    return configured


def get_redis_url_source() -> str:
    """Return the environment variable name supplying the current Redis URL."""
    configured = _iter_configured_redis_urls()
    if configured:
        return configured[0][0]
    return ""


def get_redis_env_presence() -> dict[str, bool]:
    """Return whether each supported Redis URL environment variable is set."""
    return {name: bool(_strip_wrapping_quotes(os.getenv(name, ""))) for name in _REDIS_URL_ENV_NAMES}


def get_redis_resolution_diagnostics() -> dict[str, object]:
    """Return Redis resolution diagnostics for startup logs."""
    component_url, component_diag = _build_component_redis_url()
    resolved_source = get_redis_url_source() or None
    resolved_url = _get_redis_url_validated()
    parsed = urlparse(resolved_url) if resolved_url else None
    hostname = (parsed.hostname or "").lower() if parsed else ""
    scheme = (parsed.scheme or "").lower() if parsed else ""
    is_railway_proxy = ".proxy.rlwy.net" in hostname
    is_railway_internal = ".railway.internal" in hostname
    tls_required_hint = bool(is_railway_proxy)
    tls_configured = scheme == "rediss"
    tls_mismatch = bool(resolved_url) and tls_required_hint and not tls_configured
    nija_url_format_error = get_nija_url_format_error()
    return {
        "url_env_presence": get_redis_env_presence(),
        "component_host_present": component_diag["component_host_present"],
        "component_port_present": component_diag["component_port_present"],
        "component_port_valid": component_diag["component_port_valid"],
        "component_source": component_diag["component_source"],
        "component_endpoint": component_diag["component_endpoint"],
        "component_url_present": bool(component_url),
        "resolved_url_present": bool(resolved_url),
        "resolved_source": resolved_source,
        "resolved_scheme": scheme or None,
        "resolved_host": hostname or None,
        "is_railway_proxy": is_railway_proxy,
        "is_railway_internal": is_railway_internal,
        "tls_required_hint": tls_required_hint,
        "tls_configured": tls_configured,
        "tls_mismatch": tls_mismatch,
        "nija_url_invalid_format": bool(nija_url_format_error),
        "nija_url_format_error": nija_url_format_error or None,
    }


def get_all_redis_urls() -> list[tuple[str, str]]:
    """Return configured Redis URLs in priority order without rewriting values."""
    return _iter_configured_redis_urls()


def get_nija_url_format_error() -> str:
    """Return a non-empty error string when NIJA_REDIS_URL is set but not a valid Redis URL.

    Returns ``""`` when the variable is unset, empty, or already a valid ``redis://``
    / ``rediss://`` URL so that callers can do a simple truthiness check.
    """
    raw = _strip_wrapping_quotes(os.getenv("NIJA_REDIS_URL", ""))
    if not raw:
        return ""
    if raw.startswith("redis://") or raw.startswith("rediss://"):
        return ""
    return (
        f"NIJA_REDIS_URL is set to {raw!r}, which is not a valid Redis connection URL. "
        "In Railway, copy the full Connect URL from the Redis service Connect tab "
        "(format: rediss://default:PASSWORD@<host>.proxy.rlwy.net:PORT) "
        "and set that exact value as NIJA_REDIS_URL."
    )
