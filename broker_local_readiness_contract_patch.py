"""Make NIJA broker-local readiness telemetry internally consistent.

The secondary venue guard intentionally applies strict activation checks only to
orders routed to the affected broker.  Its legacy global telemetry flag,
``NIJA_REQUIRED_VENUES_READY``, was always set to ``1`` to avoid blocking Kraken.
That produced contradictory Render output when Coinbase and OKX were both missing.

This repair separates the two concepts:

* ``NIJA_REQUIRED_VENUES_READY`` truthfully reports whether every configured
  required secondary venue is ready.
* ``NIJA_MULTI_BROKER_TRADING_READY`` and ``NIJA_GLOBAL_TRADING_READY`` report
  whether at least one live venue is available for independent execution.
* ``NIJA_SECONDARY_VENUE_POLICY=broker_local`` tells readiness consumers that
  unavailable secondary venues must not globally block a healthy Kraken venue.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
from functools import wraps
from types import ModuleType
from typing import Any

logger = logging.getLogger("nija.broker_local_readiness_contract")
_MARKER = "20260714-broker-local-readiness-v1"
_PATCH_ATTR = "_nija_broker_local_readiness_contract_v1"
_LOCK = threading.RLock()
_INSTALLED = False


def _policy(strict: bool) -> str:
    return "broker_local" if strict else "optional"


def _active_venues(statuses: dict[str, dict[str, Any]]) -> list[str]:
    return sorted(
        name for name, status in statuses.items()
        if bool(status.get("ready"))
    )


def _publish_contract(
    module: ModuleType,
    missing: list[str],
    statuses: dict[str, dict[str, Any]],
) -> bool:
    active = _active_venues(statuses)
    strict_fn = getattr(module, "strict_mode_enabled", None)
    strict = bool(strict_fn()) if callable(strict_fn) else False
    all_required_ready = not missing
    any_live_ready = bool(active)

    os.environ["NIJA_SECONDARY_VENUE_POLICY"] = _policy(strict)
    os.environ["NIJA_REQUIRED_VENUES_READY"] = "1" if all_required_ready else "0"
    os.environ["NIJA_MULTI_BROKER_TRADING_READY"] = "1" if any_live_ready else "0"
    os.environ["NIJA_GLOBAL_TRADING_READY"] = "1" if any_live_ready else "0"
    os.environ["NIJA_ACTIVE_LIVE_VENUES"] = ",".join(active)
    os.environ["NIJA_REQUIRED_VENUES_MISSING"] = ",".join(missing)
    os.environ["NIJA_BROKER_LOCAL_READINESS_CONTRACT_INSTALLED"] = "1"

    logger.warning(
        "BROKER_LOCAL_READINESS_CONTRACT marker=%s policy=%s active=%s "
        "required_ready=%s missing=%s global_ready=%s",
        _MARKER,
        _policy(strict),
        ",".join(active) or "none",
        str(all_required_ready).lower(),
        ",".join(missing) or "none",
        str(any_live_ready).lower(),
    )
    return any_live_ready


def _patch_module(module: ModuleType) -> bool:
    current = getattr(module, "refresh_readiness", None)
    if not callable(current):
        return False
    if getattr(current, _PATCH_ATTR, False):
        return True

    @wraps(current)
    def refresh_readiness(*args: Any, **kwargs: Any):
        _legacy_ready, missing, statuses = current(*args, **kwargs)
        missing_list = list(missing or [])
        status_map = dict(statuses or {})
        global_ready = _publish_contract(module, missing_list, status_map)
        return global_ready, missing_list, status_map

    setattr(refresh_readiness, _PATCH_ATTR, True)
    setattr(refresh_readiness, "__wrapped__", current)
    module.refresh_readiness = refresh_readiness

    def required_venues_ready() -> bool:
        return bool(refresh_readiness()[0])

    module.required_venues_ready = required_venues_ready
    # Publish immediately so the readiness bridge cannot emit one contradictory
    # snapshot between guard installation and the first monitor refresh.
    try:
        refresh_readiness(force_log=True)
    except Exception as exc:
        logger.warning(
            "BROKER_LOCAL_READINESS_INITIAL_REFRESH_FAILED marker=%s error=%s",
            _MARKER,
            exc,
        )
    logger.critical("BROKER_LOCAL_READINESS_CONTRACT_INSTALLED marker=%s", _MARKER)
    return True


def install() -> None:
    global _INSTALLED
    with _LOCK:
        module = importlib.import_module("secondary_venue_strict_readiness_patch")
        if not _patch_module(module):
            raise RuntimeError("secondary_venue_readiness_not_patchable")
        _INSTALLED = True


def install_import_hook() -> None:
    install()


__all__ = [
    "install",
    "install_import_hook",
    "_policy",
    "_active_venues",
    "_publish_contract",
    "_patch_module",
]
