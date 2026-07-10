"""Render-specific runtime normalization before NIJA imports the bot package.

This module does not grant execution authority or bypass the distributed writer
lock. It only restores the private Render Key Value endpoint when an existing
Render web service was created outside the current Blueprint and therefore did
not receive its ``fromService`` environment variables.
"""

from __future__ import annotations

import os
from collections.abc import MutableMapping
from urllib.parse import urlparse

_RENDER_METADATA_KEYS = (
    "RENDER_SERVICE_ID",
    "RENDER_SERVICE_NAME",
    "RENDER_INSTANCE_ID",
    "RENDER_GIT_BRANCH",
    "RENDER_GIT_COMMIT",
)
_REDIS_URL_KEYS = (
    "NIJA_REDIS_URL",
    "REDIS_PRIVATE_URL",
    "REDIS_PUBLIC_URL",
    "REDIS_URL",
    "REDIS_TLS_URL",
)
_TRUTHY = {"1", "true", "yes", "on", "enabled"}

# Private, credential-free Render Key Value address supplied by the operator.
# It is reachable only from services in the same Render private network/region.
_DEFAULT_RENDER_PRIVATE_REDIS_URL = "redis://red-d98dsl5aeets73fpb0hg:6379"


def _truthy(value: object) -> bool:
    return str(value or "").strip().lower() in _TRUTHY


def _is_render_runtime(env: MutableMapping[str, str]) -> bool:
    if _truthy(env.get("RENDER", "")):
        return True
    return any(str(env.get(key, "") or "").strip() for key in _RENDER_METADATA_KEYS)


def _valid_render_private_url(raw: str) -> bool:
    try:
        parsed = urlparse(str(raw or "").strip())
        host = (parsed.hostname or "").lower()
        return bool(
            parsed.scheme == "redis"
            and host.startswith("red-")
            and "." not in host
            and parsed.port == 6379
        )
    except (TypeError, ValueError):
        return False


def apply_render_private_redis_fallback(
    env: MutableMapping[str, str] | None = None,
) -> str:
    """Publish the Render-private Redis URL only when no valid URL is configured.

    Existing valid Redis configuration always wins. Outside a positively detected
    Render runtime this function is a no-op. The fallback never sets writer
    authority, fencing tokens, heartbeat state, or any trading-state variable.
    """

    target = env if env is not None else os.environ
    if not _is_render_runtime(target):
        return ""

    for key in _REDIS_URL_KEYS:
        value = str(target.get(key, "") or "").strip().strip("\"'")
        if value.startswith(("redis://", "rediss://")):
            return ""

    candidate = str(
        target.get("NIJA_RENDER_REDIS_FALLBACK_URL", "")
        or _DEFAULT_RENDER_PRIVATE_REDIS_URL
    ).strip().strip("\"'")
    if not _valid_render_private_url(candidate):
        return ""

    target["NIJA_REDIS_URL"] = candidate
    target["REDIS_URL"] = candidate
    target["NIJA_RENDER_REDIS_FALLBACK_APPLIED"] = "1"
    return candidate
