"""OKX regional endpoint and credential-scope isolation.

Selects exactly one OKX REST host before any private request. The patch is
strictly OKX-local: it never mutates Coinbase, Kraken, global writer authority,
or global trading state.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
from types import ModuleType
from urllib.parse import urlparse

logger = logging.getLogger("nija.okx_regional_endpoint")
_MARKER = "20260718-okx-regional-endpoint-v2"
_LOCK = threading.RLock()
_STARTED = False
_ALLOWED = {
    "www.okx.com",
    "us.okx.com",
    "eea.okx.com",
}
_REGION_DEFAULTS = {
    "US": "https://us.okx.com",
    "USA": "https://us.okx.com",
    "UNITED_STATES": "https://us.okx.com",
    "EEA": "https://eea.okx.com",
    "EU": "https://eea.okx.com",
    "GLOBAL": "https://www.okx.com",
    "INTL": "https://www.okx.com",
}


def _clean(value: object) -> str:
    return str(value or "").strip().strip('"').strip("'")


def resolve_okx_base_url() -> str:
    """Resolve the OKX host with account region taking precedence.

    NIJA's production account is U.S.-scoped, so an omitted region defaults to
    the U.S. endpoint. A stale OKX_BASE_URL cannot override an explicit region.
    """
    region = _clean(
        os.getenv("OKX_ACCOUNT_REGION") or os.getenv("OKX_REGION") or "US"
    ).upper().replace("-", "_").replace(" ", "_")
    explicit = _clean(os.getenv("OKX_BASE_URL"))

    if region not in _REGION_DEFAULTS:
        raise RuntimeError(
            f"unsupported OKX account region {region!r}; use US, EEA, or GLOBAL"
        )

    regional_endpoint = _REGION_DEFAULTS[region]
    selected = regional_endpoint

    if explicit:
        parsed_explicit = urlparse(explicit.rstrip("/"))
        if (
            parsed_explicit.scheme != "https"
            or parsed_explicit.hostname not in _ALLOWED
            or parsed_explicit.path not in ("", "/")
        ):
            raise RuntimeError(
                "invalid OKX endpoint; use exactly https://us.okx.com, "
                "https://eea.okx.com, or https://www.okx.com"
            )
        if explicit.rstrip("/") != regional_endpoint:
            logger.warning(
                "OKX_ENDPOINT_REGION_MISMATCH_REPAIRED marker=%s region=%s "
                "configured=%s selected=%s broker_scope=okx_only",
                _MARKER,
                region,
                explicit.rstrip("/"),
                regional_endpoint,
            )

    return selected


def _patch_module(module: ModuleType) -> bool:
    cls = getattr(module, "_OKXRestClient", None)
    if not isinstance(cls, type):
        return False
    endpoint = resolve_okx_base_url()
    cls.BASE_URL = endpoint
    os.environ["OKX_ACCOUNT_REGION"] = "US" if endpoint == "https://us.okx.com" else os.environ.get("OKX_ACCOUNT_REGION", "")
    os.environ["OKX_BASE_URL"] = endpoint
    os.environ["NIJA_OKX_ENDPOINT_SELECTED"] = endpoint
    os.environ["NIJA_OKX_ENDPOINT_ISOLATED"] = "1"
    logger.critical(
        "OKX_REGIONAL_ENDPOINT_SELECTED marker=%s endpoint=%s broker_scope=okx_only fallback=false",
        _MARKER,
        endpoint,
    )
    return True


def _patch_loaded() -> bool:
    ready = False
    for name in ("bot.broker_manager", "broker_manager"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            ready = _patch_module(module) or ready
    return ready


def _watchdog() -> None:
    for _ in range(300):
        try:
            if _patch_loaded():
                os.environ["NIJA_OKX_REGIONAL_ENDPOINT_READY"] = "1"
                return
        except Exception:
            logger.exception("OKX_REGIONAL_ENDPOINT_RETRY marker=%s", _MARKER)
        threading.Event().wait(0.2)


def install() -> None:
    global _STARTED
    with _LOCK:
        endpoint = resolve_okx_base_url()
        if endpoint == "https://us.okx.com":
            os.environ["OKX_ACCOUNT_REGION"] = "US"
        os.environ["OKX_BASE_URL"] = endpoint
        os.environ["NIJA_OKX_ENDPOINT_ISOLATED"] = "1"
        _patch_loaded()
        if not _STARTED:
            _STARTED = True
            threading.Thread(
                target=_watchdog,
                name="OKXRegionalEndpoint",
                daemon=True,
            ).start()
        os.environ["NIJA_OKX_REGIONAL_ENDPOINT_INSTALLED"] = "1"


def installed_marker() -> str:
    return _MARKER


__all__ = ["install", "installed_marker", "resolve_okx_base_url"]
