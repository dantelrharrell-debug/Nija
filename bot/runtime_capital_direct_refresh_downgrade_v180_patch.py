"""Prevent post-bootstrap direct fallback from downgrading canonical capital.

Production on 2026-08-21 proved a runtime-only capital split after the canonical
coordinator had already established complete three-broker state. During a
coordinator rollover/in-flight gap, ``MultiAccountBrokerManager`` may fall back
to ``CapitalAuthority.refresh(..., _bypass_startup_lock=True)``. Base
``CapitalAuthority.refresh`` replaces the complete internal balance map with the
results of that direct refresh and stamps ``last_updated`` to now. A slow or
failed Kraken read can therefore replace a complete 3/3 state with 2/3 before
v170 correctly rejects the partial publication.

v180 restores single-writer ownership after bootstrap:

* the call must use the private ``_bypass_startup_lock`` fallback flag;
* broker registration must already be finalized;
* CapitalAuthority must already hold at least ``expected_brokers`` entries;
* once that complete canonical state exists, any later private bypass refresh is
  suppressed and the canonical coordinator remains the only runtime writer.

The suppressed fallback does not merge balances, mutate ``last_updated``, extend
freshness/publication expiry, promote stale data, fabricate a broker balance,
change writer/nonce/risk/kill-switch authority, or force activation/trading.
Cold/bootstrap refreshes and ordinary non-bypass refreshes continue unchanged.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
from functools import wraps
from typing import Any, Mapping

LOGGER = logging.getLogger("nija.runtime_capital_direct_refresh_downgrade_v180")
MARKER = "20260821-runtime-capital-direct-refresh-downgrade-v180"
_READY_FLAG = "NIJA_RUNTIME_CAPITAL_DIRECT_REFRESH_DOWNGRADE_V180_READY"
_PATCH_ATTR = "_nija_runtime_capital_direct_refresh_downgrade_v180"
_LOCK = threading.RLock()


def _normalize_key(value: Any) -> str:
    raw = getattr(value, "value", value)
    return str(raw or "").strip().lower()


def _registration_complete(authority: Any) -> bool:
    gate = getattr(authority, "_broker_registration_complete", None)
    checker = getattr(gate, "is_set", None)
    try:
        return bool(checker()) if callable(checker) else False
    except Exception:
        return False


def _expected_brokers(authority: Any) -> int:
    for attr in ("_expected_brokers", "expected_brokers"):
        try:
            value = int(getattr(authority, attr, 0) or 0)
        except (TypeError, ValueError):
            value = 0
        if value > 0:
            return value
    return 1


def _existing_balance_keys(authority: Any) -> set[str]:
    lock = getattr(authority, "_lock", None)

    def _read() -> set[str]:
        balances = getattr(authority, "_broker_balances", None)
        if not isinstance(balances, Mapping):
            return set()
        return {_normalize_key(key) for key in balances if _normalize_key(key)}

    if lock is None:
        return _read()
    try:
        with lock:
            return _read()
    except Exception:
        return set()


def _incoming_keys(broker_map: Any) -> set[str]:
    if not isinstance(broker_map, Mapping):
        return set()
    return {
        _normalize_key(key)
        for key, broker in broker_map.items()
        if broker is not None and _normalize_key(key)
    }


def _should_suppress_direct_fallback(
    authority: Any,
    broker_map: Any,
    *,
    bypass_startup_lock: bool,
) -> tuple[bool, dict[str, Any]]:
    expected = max(1, _expected_brokers(authority))
    existing = _existing_balance_keys(authority)
    incoming = _incoming_keys(broker_map)
    covered = existing.intersection(incoming)
    missing = sorted(existing.difference(incoming))

    metadata = {
        "expected": expected,
        "existing": sorted(existing),
        "incoming": sorted(incoming),
        "covered": sorted(covered),
        "missing": missing,
        "registration_complete": _registration_complete(authority),
        "bypass_startup_lock": bool(bypass_startup_lock),
    }

    # The private bypass exists to build the initial bootstrap snapshot. Once a
    # complete canonical broker set already exists after registration, allowing
    # this fallback to run creates a second capital writer. Preserve the exact
    # prior state and let the coordinator refresh it; if it expires meanwhile,
    # normal freshness gates fail closed.
    suppress = bool(
        bypass_startup_lock
        and metadata["registration_complete"]
        and expected > 1
        and len(existing) >= expected
    )
    return suppress, metadata


def _patch_capital_authority() -> bool:
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
    def refresh_v180(
        self: Any,
        broker_map: Any,
        open_exposure_usd: float = 0.0,
        _bypass_startup_lock: bool = False,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        suppress, metadata = _should_suppress_direct_fallback(
            self,
            broker_map,
            bypass_startup_lock=bool(_bypass_startup_lock),
        )
        if suppress:
            last_updated = getattr(self, "last_updated", None)
            LOGGER.critical(
                "CAPITAL_V180_DIRECT_FALLBACK_SUPPRESSED marker=%s "
                "incoming=%s existing=%s missing=%s covered=%d expected=%d "
                "registration_complete=true bypass_startup_lock=true "
                "last_updated=%s balances_mutated=false last_updated_mutated=false "
                "freshness_extended=false publication_expiry_extended=false "
                "stale_promoted=false trading_fail_closed=true",
                MARKER,
                metadata["incoming"],
                metadata["existing"],
                metadata["missing"],
                len(metadata["covered"]),
                int(metadata["expected"]),
                last_updated,
            )
            return None

        return original(
            self,
            broker_map,
            open_exposure_usd=open_exposure_usd,
            _bypass_startup_lock=_bypass_startup_lock,
            *args,
            **kwargs,
        )

    setattr(refresh_v180, _PATCH_ATTR, True)
    setattr(refresh_v180, "__wrapped__", original)
    cls.refresh = refresh_v180
    return True


def _patch_release_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_capital_direct_refresh_downgrade_v180"] = _READY_FLAG
        return True
    except Exception:
        return False


def install() -> bool:
    with _LOCK:
        authority_ok = _patch_capital_authority()
        manifest_ok = _patch_release_manifest()
        ready = bool(authority_ok and manifest_ok)
        os.environ[_READY_FLAG] = "1" if ready else "0"
        if not ready:
            LOGGER.critical(
                "RUNTIME_CAPITAL_DIRECT_REFRESH_DOWNGRADE_V180_FAILED marker=%s "
                "authority_ok=%s manifest_ok=%s trading_fail_closed=true",
                MARKER,
                str(authority_ok).lower(),
                str(manifest_ok).lower(),
            )
            return False

        LOGGER.critical(
            "RUNTIME_CAPITAL_DIRECT_REFRESH_DOWNGRADE_V180 marker=%s ready=true "
            "private_fallback_only=true prior_complete_state_required=true "
            "post_bootstrap_direct_fallback_suppressed=true cold_bootstrap_unchanged=true "
            "canonical_coordinator_single_writer=true balances_mutated_on_reject=false "
            "last_updated_mutated_on_reject=false freshness_extended=false "
            "publication_expiry_extended=false stale_promoted=false forced_trade=false "
            "safety_gates_bypassed=false",
            MARKER,
        )
        return True


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_normalize_key",
    "_registration_complete",
    "_expected_brokers",
    "_existing_balance_keys",
    "_incoming_keys",
    "_should_suppress_direct_fallback",
    "_patch_capital_authority",
]
