"""Canonical platform capital source-graph completion v189.

Production on 2026-08-23 showed CapitalAuthority.refresh() receiving a non-empty
but incomplete platform broker map containing Coinbase and OKX while the
canonical broker manager still had Kraken connected.  The base refresh path
only hydrates from the canonical registry when the incoming map is completely
empty, so a 2/3 input can omit a healthy platform broker and produce a partial
capital snapshot.

v189 repairs only the source graph before the existing refresh logic runs.  It
adds a missing broker object only when that broker already exists in the
canonical platform-broker registry and is currently connected (or the broker
adapter does not expose a connected attribute).  It never supplies a balance,
never reuses a stale balance, never changes expected-broker thresholds, never
extends freshness/publication expiry, and never promotes a partial snapshot.
The original CapitalAuthority refresh path still performs the authenticated
balance read and all existing 3/3 completeness/freshness gates remain intact.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
from functools import wraps
from typing import Any, Mapping

LOGGER = logging.getLogger("nija.runtime_capital_platform_source_graph_v189")
MARKER = "20260822-runtime-capital-platform-source-graph-v189"
RELEASE_ID = "20260822-runtime-convergence-v189"
_READY_FLAG = "NIJA_RUNTIME_CAPITAL_PLATFORM_SOURCE_GRAPH_V189_READY"
_PATCH_ATTR = "_nija_runtime_capital_platform_source_graph_v189"
_LOCK = threading.RLock()


def _normalise_broker_key(value: Any) -> str:
    return str(getattr(value, "value", value) or "").strip().lower()


def _platform_brokers(manager: Any) -> dict[str, Any]:
    """Return canonical platform brokers keyed by normalized broker id."""
    raw = getattr(manager, "platform_brokers", None)
    if not isinstance(raw, Mapping):
        raw = getattr(manager, "_platform_brokers", None)
    if not isinstance(raw, Mapping):
        return {}

    result: dict[str, Any] = {}
    for key, broker in raw.items():
        name = _normalise_broker_key(key)
        if not name or broker is None:
            continue
        result[name] = broker
    return result


def _broker_is_connected(broker: Any) -> bool:
    """Use explicit connectivity when exposed; otherwise leave truth to fetch."""
    if hasattr(broker, "connected"):
        try:
            return bool(getattr(broker, "connected"))
        except Exception:
            return False
    return True


def _supplement_platform_sources(authority: Any, broker_map: Any) -> tuple[dict[Any, Any], list[str]]:
    """Add only missing connected canonical platform broker objects.

    No balance or readiness value is synthesized here.  The returned broker
    objects are passed to the original CapitalAuthority.refresh(), which must
    still authenticate/fetch them normally.
    """
    incoming = dict(broker_map or {})
    normalized_present = {
        _normalise_broker_key(key)
        for key in incoming
        if _normalise_broker_key(key)
    }

    try:
        mabm = importlib.import_module("bot.multi_account_broker_manager")
        getter = getattr(mabm, "get_broker_manager", None)
        manager = getter() if callable(getter) else None
    except Exception:
        manager = None
    if manager is None:
        return incoming, []

    canonical = _platform_brokers(manager)
    if not canonical:
        return incoming, []

    added: list[str] = []
    for name, broker in canonical.items():
        if name in normalized_present:
            continue
        if not _broker_is_connected(broker):
            continue
        incoming[name] = broker
        normalized_present.add(name)
        added.append(name)

    if added:
        expected = 0
        for candidate in (
            getattr(authority, "expected_brokers", None),
            getattr(authority, "_expected_brokers", None),
        ):
            try:
                parsed = int(candidate or 0)
            except (TypeError, ValueError):
                parsed = 0
            if parsed > 0:
                expected = parsed
                break
        LOGGER.critical(
            "CAPITAL_PLATFORM_SOURCE_GRAPH_V189_SUPPLEMENTED marker=%s added=%s "
            "final_platform_sources=%s expected_brokers=%d canonical_registry_only=true "
            "connected_only=true balances_fabricated=false stale_balance_reused=false "
            "completeness_threshold_unchanged=true freshness_extended=false "
            "publication_expiry_extended=false forced_activation=false safety_gates_bypassed=false",
            MARKER,
            sorted(added),
            sorted(name for name in normalized_present if name in canonical),
            expected,
        )
    return incoming, sorted(added)


def _patch_capital_authority_refresh() -> bool:
    try:
        module = importlib.import_module("bot.capital_authority")
        cls = getattr(module, "CapitalAuthority", None)
    except Exception:
        return False
    if not isinstance(cls, type):
        return False

    current = getattr(cls, "refresh", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True
    original = current

    @wraps(original)
    def refresh_v189(
        self: Any,
        broker_map: Any,
        open_exposure_usd: float = 0.0,
        _bypass_startup_lock: bool = False,
    ) -> Any:
        supplemented, _added = _supplement_platform_sources(self, broker_map)
        return original(
            self,
            supplemented,
            open_exposure_usd=open_exposure_usd,
            _bypass_startup_lock=_bypass_startup_lock,
        )

    setattr(refresh_v189, _PATCH_ATTR, True)
    setattr(refresh_v189, "__wrapped__", original)
    cls.refresh = refresh_v189
    return True


def _patch_release_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        installers = getattr(manifest, "_INSTALLERS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_capital_platform_source_graph_v189"] = _READY_FLAG
        own = ("bot.runtime_capital_platform_source_graph_v189_patch", "install_import_hook")
        if isinstance(installers, tuple) and own not in installers:
            manifest._INSTALLERS = tuple(installers) + (own,)
        return True
    except Exception:
        return False


def install() -> bool:
    with _LOCK:
        authority_ok = _patch_capital_authority_refresh()
        manifest_ok = _patch_release_manifest()
        ready = bool(authority_ok and manifest_ok)
        os.environ[_READY_FLAG] = "1" if ready else "0"
        if not ready:
            LOGGER.critical(
                "RUNTIME_CAPITAL_PLATFORM_SOURCE_GRAPH_V189_FAILED marker=%s authority=%s "
                "manifest=%s trading_fail_closed=true",
                MARKER,
                str(authority_ok).lower(),
                str(manifest_ok).lower(),
            )
            return False
        LOGGER.critical(
            "RUNTIME_CAPITAL_PLATFORM_SOURCE_GRAPH_V189 marker=%s ready=true "
            "canonical_registry_only=true connected_platform_sources_only=true "
            "balances_fabricated=false stale_balance_reused=false "
            "completeness_threshold_unchanged=true freshness_ttl_unchanged=true "
            "publication_expiry_extended=false forced_activation=false safety_gates_bypassed=false",
            MARKER,
        )
        return True


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "RELEASE_ID",
    "install",
    "install_import_hook",
    "_normalise_broker_key",
    "_platform_brokers",
    "_broker_is_connected",
    "_supplement_platform_sources",
    "_patch_capital_authority_refresh",
    "_patch_release_manifest",
]
