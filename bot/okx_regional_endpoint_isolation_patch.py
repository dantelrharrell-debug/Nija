"""OKX regional endpoint and credential-scope isolation.

Selects exactly one OKX REST host before any private request. Region selection is
explicit and credential-safe: NIJA never infers the OKX account region from the
server/user location. When no region is configured, the historical global OKX
endpoint is retained.
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
_MARKER = "20260720-okx-regional-endpoint-v9"
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
    "INTERNATIONAL": "https://www.okx.com",
    "WWW": "https://www.okx.com",
}


def _clean(value: object) -> str:
    return str(value or "").strip().strip('"').strip("'")


def _validated_explicit_endpoint(value: str) -> str:
    explicit = _clean(value).rstrip("/")
    if not explicit:
        return ""
    parsed = urlparse(explicit)
    if parsed.scheme != "https" or parsed.hostname not in _ALLOWED or parsed.path not in ("", "/"):
        raise RuntimeError(
            "invalid OKX endpoint; use exactly https://us.okx.com, "
            "https://eea.okx.com, or https://www.okx.com"
        )
    return explicit


def resolve_okx_base_url() -> str:
    """Resolve the endpoint without guessing the account's legal region.

    Precedence:
      1. Explicit OKX_ACCOUNT_REGION / OKX_REGION.
      2. Explicit OKX_BASE_URL / OKX_API_BASE_URL / OKX_ENDPOINT.
      3. Historical NIJA default: global OKX (www.okx.com).

    A user's physical location is not evidence that an API key belongs to OKX US.
    """
    raw_region = _clean(os.getenv("OKX_ACCOUNT_REGION") or os.getenv("OKX_REGION"))
    region = raw_region.upper().replace("-", "_").replace(" ", "_")
    explicit = _validated_explicit_endpoint(
        os.getenv("OKX_BASE_URL") or os.getenv("OKX_API_BASE_URL") or os.getenv("OKX_ENDPOINT") or ""
    )

    if region:
        if region not in _REGION_DEFAULTS:
            raise RuntimeError(
                f"unsupported OKX account region {region!r}; use US, EEA, or GLOBAL"
            )
        selected = _REGION_DEFAULTS[region]
        if explicit and explicit != selected:
            logger.warning(
                "OKX_ENDPOINT_REGION_MISMATCH_REPAIRED marker=%s region=%s configured=%s selected=%s broker_scope=okx_only",
                _MARKER, region, explicit, selected,
            )
        source = "region"
    elif explicit:
        selected = explicit
        source = "explicit_endpoint"
    else:
        selected = "https://www.okx.com"
        source = "safe_global_default"
        logger.warning(
            "OKX_REGION_UNSET_GLOBAL_DEFAULT marker=%s selected=%s action=set_OKX_ACCOUNT_REGION_explicitly_if_key_is_us_or_eea",
            _MARKER, selected,
        )

    os.environ["NIJA_OKX_ENDPOINT_SOURCE"] = source
    return selected


def _patch_module(module: ModuleType) -> bool:
    cls = getattr(module, "_OKXRestClient", None)
    if not isinstance(cls, type):
        return False
    endpoint = resolve_okx_base_url()
    cls.BASE_URL = endpoint
    os.environ["OKX_BASE_URL"] = endpoint
    os.environ["NIJA_OKX_ENDPOINT_SELECTED"] = endpoint
    os.environ["NIJA_OKX_ENDPOINT_ISOLATED"] = "1"
    logger.critical(
        "OKX_REGIONAL_ENDPOINT_SELECTED marker=%s endpoint=%s source=%s broker_scope=okx_only fallback=false",
        _MARKER, endpoint, os.environ.get("NIJA_OKX_ENDPOINT_SOURCE", "unknown"),
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
    global _CONVERGENCE_INSTALLED
    if _CONVERGENCE_INSTALLED:
        return True
    installed: list[str] = []
    for name in (
        "bot.coinbase_balance_auth_convergence_patch",
        "bot.okx_order_wrapper_stability_patch",
        "bot.final_account_router_exit_convergence_patch",
        "bot.platform_recovery_and_coinbase_balance_convergence_patch",
        "bot.final_execution_state_router_convergence_patch",
        "bot.broker_local_minimum_coinbase_okx_convergence_patch",
        "bot.okx_router_connection_convergence_patch",
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
        "LATE_BROKER_CONVERGENCE_INSTALLED marker=%s coinbase_balance_auth=true okx_wrapper_stability=true final_account_router_exit=true platform_recovery_coinbase_balance=true final_execution_state_router=true broker_local_minimum_coinbase_okx=true okx_router_connection=true modules=%s",
        _MARKER, ",".join(installed),
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
