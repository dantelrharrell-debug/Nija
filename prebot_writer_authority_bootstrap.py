"""Acquire NIJA's canonical Redis writer authority before the bot import graph.

This module is loaded from an alphabetically-first ``.pth`` file in the
production image. It executes only for NIJA's live entrypoint process, never
for health checks, tests, build helpers, or arbitrary ``python -c`` commands.

The canonical ``bot/entrypoint_writer_authority.py`` module is loaded directly
from disk without importing ``bot.__init__``. Its Redis connector and instance
identity helpers are replaced with pre-package-safe implementations, then its
normal fail-closed lease acquisition and heartbeat logic are used unchanged.
The loaded module is registered under its canonical import name so ``bot_main``
reuses the exact same singleton, lock value, and heartbeat.
"""

from __future__ import annotations

import builtins
import importlib.util
import logging
import os
import ssl
import sys
import threading
from pathlib import Path
from types import ModuleType
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger("nija.prebot_writer_authority")
_MARKER = "20260710aa"
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}
_LOCK = threading.RLock()
_INSTALLED = False
_RUNTIME: Any = None
_CANONICAL_NAME = "bot.entrypoint_writer_authority"
_ALIAS_NAME = "entrypoint_writer_authority"


def _truthy(name: str, default: str = "false") -> bool:
    return str(os.environ.get(name, default) or "").strip().lower() in _TRUE


def _live_mode() -> bool:
    return (
        _truthy("LIVE_CAPITAL_VERIFIED")
        and not _truthy("DRY_RUN_MODE")
        and not _truthy("PAPER_MODE")
    )


def _target_process() -> bool:
    if _truthy("NIJA_PREBOT_WRITER_AUTHORITY_DISABLE"):
        return False
    if not _live_mode() and not _truthy("NIJA_PREBOT_WRITER_AUTHORITY_FORCE"):
        return False

    argv0 = os.path.basename(str(sys.argv[0] or "")).strip().lower()
    configured = os.environ.get(
        "NIJA_PREBOT_WRITER_PROCESS_NAMES",
        "main.py,bot.py,bot_main.py",
    )
    allowed = {
        os.path.basename(item.strip()).lower()
        for item in configured.split(",")
        if item.strip()
    }
    return _truthy("NIJA_PREBOT_WRITER_AUTHORITY_FORCE") or argv0 in allowed


def _strip_wrapping_quotes(value: str) -> str:
    text = str(value or "").strip()
    while len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        text = text[1:-1].strip()
    return text


def _is_render_runtime() -> bool:
    if _truthy("RENDER"):
        return True
    return any(
        _strip_wrapping_quotes(os.environ.get(name, ""))
        for name in (
            "RENDER_SERVICE_ID",
            "RENDER_SERVICE_NAME",
            "RENDER_INSTANCE_ID",
            "RENDER_GIT_BRANCH",
            "RENDER_GIT_COMMIT",
        )
    )


def _is_render_private(url: str) -> bool:
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        return (
            (parsed.scheme or "").lower() == "redis"
            and host.startswith("red-")
            and "." not in host
            and parsed.port == 6379
        )
    except (TypeError, ValueError):
        return False


def _is_railway_proxy(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except (TypeError, ValueError):
        return False
    return ".proxy.rlwy.net" in host or host.endswith(".up.railway.app")


def _normalize_url(url: str) -> str:
    value = _strip_wrapping_quotes(url)
    if value.startswith("redis://") and _is_railway_proxy(value):
        value = "rediss://" + value[len("redis://") :]
    return value


def _candidate_urls() -> list[str]:
    configured: list[str] = []
    for name in (
        "NIJA_REDIS_URL",
        "REDIS_PRIVATE_URL",
        "REDIS_PUBLIC_URL",
        "REDIS_URL",
        "REDIS_TLS_URL",
    ):
        value = _normalize_url(os.environ.get(name, ""))
        if value.startswith(("redis://", "rediss://")):
            configured.append(value)

    if _is_render_runtime():
        configured.sort(key=lambda value: 0 if _is_render_private(value) else 1)

    result: list[str] = []
    seen: set[str] = set()
    for value in configured:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _safe_endpoint(url: str) -> str:
    try:
        parsed = urlparse(url)
        return f"{parsed.scheme}://***@{parsed.hostname or 'unknown'}:{parsed.port or 'unknown'}"
    except Exception:
        return "<invalid-redis-url>"


def _connect_redis_prebot(timeout_s: float = 3.0):
    """Return the canonical connector tuple without importing the bot package."""

    try:
        import redis  # type: ignore[import]
    except Exception as exc:
        return None, "", f"redis_import_failed:{type(exc).__name__}:{exc}"

    candidates = _candidate_urls()
    if not candidates:
        return None, "", "redis_url_missing"

    errors: list[str] = []
    for url in candidates:
        kwargs: dict[str, Any] = {}
        if url.startswith("rediss://"):
            kwargs.update(
                {
                    "ssl_cert_reqs": ssl.CERT_REQUIRED,
                    "ssl_check_hostname": True,
                }
            )
            ca_cert = os.environ.get("NIJA_REDIS_TLS_CA_CERT", "").strip()
            if ca_cert:
                kwargs["ssl_ca_certs"] = ca_cert

        try:
            client = redis.Redis.from_url(
                url,
                decode_responses=True,
                socket_timeout=timeout_s,
                socket_connect_timeout=timeout_s,
                health_check_interval=30,
                retry_on_timeout=True,
                **kwargs,
            )
            client.ping()
            logger.warning(
                "PREBOT_WRITER_REDIS_READY marker=%s endpoint=%s",
                _MARKER,
                _safe_endpoint(url),
            )
            return client, url, ""
        except Exception as exc:
            errors.append(
                f"{_safe_endpoint(url)}:{type(exc).__name__}:{str(exc)[:180]}"
            )

    return (
        None,
        candidates[0],
        "redis_unavailable:" + " | ".join(errors),
    )


def _instance_identity_prebot() -> tuple[dict[str, str], str, str]:
    instance_id = (
        os.environ.get("RENDER_INSTANCE_ID", "").strip()
        or os.environ.get("HOSTNAME", "").strip()
        or f"pid-{os.getpid()}"
    )
    provider = "render" if _is_render_runtime() else "unknown"
    identity = {
        "provider": provider,
        "service_id": os.environ.get("RENDER_SERVICE_ID", "").strip(),
        "service_name": os.environ.get("RENDER_SERVICE_NAME", "").strip(),
        "deployment_id": os.environ.get("RENDER_DEPLOY_ID", "").strip(),
        "instance_id": instance_id,
        "pid": str(os.getpid()),
    }
    owner = "|".join(
        f"{key}={value}"
        for key, value in identity.items()
        if value
    )
    return identity, owner, instance_id


def _load_canonical_module() -> ModuleType:
    existing = sys.modules.get(_CANONICAL_NAME)
    if isinstance(existing, ModuleType):
        existing.__dict__["_connect_redis"] = _connect_redis_prebot
        existing.__dict__["_instance_identity"] = _instance_identity_prebot
        return existing

    path = Path(__file__).resolve().parent / "bot" / "entrypoint_writer_authority.py"
    if not path.is_file():
        raise RuntimeError(f"canonical writer authority module missing: {path}")

    spec = importlib.util.spec_from_file_location(_CANONICAL_NAME, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load canonical writer authority: {path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[_CANONICAL_NAME] = module
    sys.modules.setdefault(_ALIAS_NAME, module)
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(_CANONICAL_NAME, None)
        if sys.modules.get(_ALIAS_NAME) is module:
            sys.modules.pop(_ALIAS_NAME, None)
        raise

    module.__dict__["_connect_redis"] = _connect_redis_prebot
    module.__dict__["_instance_identity"] = _instance_identity_prebot
    module.__dict__["_NIJA_PREBOT_WRITER_PATCH_MARKER"] = _MARKER
    return module


def install() -> Any:
    """Acquire the canonical writer lease before any ``bot`` package import."""

    global _INSTALLED, _RUNTIME
    if not _target_process():
        return None

    with _LOCK:
        if _INSTALLED:
            return _RUNTIME

        module = _load_canonical_module()
        getter = getattr(module, "get_entrypoint_writer_authority", None)
        if not callable(getter):
            raise RuntimeError("canonical writer authority getter missing")

        runtime = getter()
        result = runtime.acquire_with_standby()
        if not bool(getattr(result, "acquired", False)):
            raise RuntimeError(
                "prebot writer authority unavailable: "
                f"{getattr(result, 'error', 'unknown')}"
            )

        _RUNTIME = runtime
        _INSTALLED = True
        setattr(builtins, "_NIJA_PREBOT_WRITER_AUTHORITY_RUNTIME", runtime)
        os.environ["NIJA_PREBOT_WRITER_AUTHORITY_READY"] = "1"
        os.environ["NIJA_PREBOT_WRITER_AUTHORITY_MARKER"] = _MARKER

        logger.critical(
            "PREBOT_WRITER_AUTHORITY_READY marker=%s token_prefix=%s generation=%s "
            "instance=%s canonical_singleton=true",
            _MARKER,
            str(getattr(result, "token", ""))[:8],
            getattr(result, "generation", 0),
            getattr(result, "instance_id", ""),
        )
        print(
            f"[NIJA-PRINT] PREBOT_WRITER_AUTHORITY_READY marker={_MARKER} "
            f"generation={getattr(result, 'generation', 0)} canonical_singleton=true",
            flush=True,
        )
        return runtime


__all__ = ["install"]
