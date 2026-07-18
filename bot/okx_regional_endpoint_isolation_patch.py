"""OKX regional endpoint and credential-scope isolation.

Selects exactly one OKX REST host before any private request. The patch is
strictly OKX-local: it never mutates Coinbase, Kraken, global writer authority,
or global trading state. Once broker classes are available it also installs the
late broker convergence repairs that require those concrete classes.
"""
from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
from types import ModuleType
from urllib.parse import urlparse

logger = logging.getLogger("nija.okx_regional_endpoint")
_MARKER = "20260718-okx-regional-endpoint-v4"
_LOCK = threading.RLock()
_STARTED = False
_CONVERGENCE_INSTALLED = False
_ALLOWED = {"www.okx.com", "us.okx.com", "eea.okx.com"}
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
    """Resolve the OKX host with account region taking precedence."""
    region = _clean(os.getenv("OKX_ACCOUNT_REGION") or os.getenv("OKX_REGION") or "US").upper().replace("-", "_").replace(" ", "_")
    explicit = _clean(os.getenv("OKX_BASE_URL"))
    if region not in _REGION_DEFAULTS:
        raise RuntimeError(f"unsupported OKX account region {region!r}; use US, EEA, or GLOBAL")
    regional_endpoint = _REGION_DEFAULTS[region]
    if explicit:
        parsed_explicit = urlparse(explicit.rstrip("/"))
        if parsed_explicit.scheme != "https" or parsed_explicit.hostname not in _ALLOWED or parsed_explicit.path not in ("", "/"):
            raise RuntimeError("invalid OKX endpoint; use exactly https://us.okx.com, https://eea.okx.com, or https://www.okx.com")
        if explicit.rstrip("/") != regional_endpoint:
            logger.warning(
                "OKX_ENDPOINT_REGION_MISMATCH_REPAIRED marker=%s region=%s configured=%s selected=%s broker_scope=okx_only",
                _MARKER, region, explicit.rstrip("/"), regional_endpoint,
            )
    return regional_endpoint


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
        _MARKER, endpoint,
    )
    return True


def _patch_loaded() -> bool:
    ready = False
    for name in ("bot.broker_manager", "broker_manager"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            ready = _patch_module(module) or ready
    return ready


def _install_convergence_repairs() -> bool:
    """Install repairs that need concrete broker/router classes, exactly once."""
    global _CONVERGENCE_INSTALLED
    if _CONVERGENCE_INSTALLED:
        return True
    installed: list[str] = []
    for name in (
        "bot.coinbase_balance_auth_convergence_patch",
        "bot.okx_order_wrapper_stability_patch",
        "bot.final_account_router_exit_convergence_patch",
    ):
        module = importlib.import_module(name)
        installer = getattr(module, "install", None) or getattr(module, "install_import_hook", None)
        if not callable(installer):
            raise RuntimeError(f"{name} installer missing")
        installer()
        installed.append(name)
    _CONVERGENCE_INSTALLED = True
    os.environ["NIJA_LATE_BROKER_CONVERGENCE_INSTALLED"] = "1"
    logger.critical(
        "LATE_BROKER_CONVERGENCE_INSTALLED marker=%s coinbase_balance_auth=true okx_wrapper_stability=true final_account_router_exit=true modules=%s",
        _MARKER,
        ",".join(installed),
    )
    return True


def _watchdog() -> None:
    for _ in range(600):
        try:
            if _patch_loaded():
                _install_convergence_repairs()
                os.environ["NIJA_OKX_REGIONAL_ENDPOINT_READY"] = "1"
                return
        except Exception:
            logger.exception("OKX_REGIONAL_ENDPOINT_RETRY marker=%s", _MARKER)
        threading.Event().wait(0.2)
    logger.critical("OKX_REGIONAL_ENDPOINT_WATCHDOG_EXHAUSTED marker=%s", _MARKER)


def install() -> None:
    global _STARTED
    with _LOCK:
        endpoint = resolve_okx_base_url()
        if endpoint == "https://us.okx.com":
            os.environ["OKX_ACCOUNT_REGION"] = "US"
        os.environ["OKX_BASE_URL"] = endpoint
        os.environ["NIJA_OKX_ENDPOINT_ISOLATED"] = "1"
        loaded = _patch_loaded()
        if loaded:
            _install_convergence_repairs()
        if not _STARTED:
            _STARTED = True
            threading.Thread(target=_watchdog, name="OKXRegionalEndpoint", daemon=True).start()
        os.environ["NIJA_OKX_REGIONAL_ENDPOINT_INSTALLED"] = "1"


def installed_marker() -> str:
    return _MARKER


__all__ = ["install", "installed_marker", "resolve_okx_base_url"]
