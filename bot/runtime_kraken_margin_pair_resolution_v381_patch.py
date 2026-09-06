"""Kraken synthetic margin-symbol pair-resolution bridge v381.

Kraken OpenPositions rows are intentionally carried through NIJA with an exact
synthetic identity such as ``ETHUSD:BTNL`` so the software protection stack can
bind to the authoritative margin exposure. Kraken public AssetPairs/Ticker,
however, accept the exchange pair (for example ``ETHUSD``) rather than NIJA's
``:<position-tag>`` suffix.

Before native backup starts, v381 now also installs v384. That repair stabilizes
exact-broker health scope across v367/v368 reassertions and resolves registered-
user Kraken proxies to their concrete adapters for authoritative private reads.
No global health state is promoted and no execution gate is bypassed.
"""
from __future__ import annotations

import importlib
import logging
import os
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.runtime_kraken_margin_pair_resolution_v381")
MARKER = "20260906-kraken-margin-pair-resolution-v381"
_READY_FLAG = "NIJA_RUNTIME_KRAKEN_MARGIN_PAIR_RESOLUTION_V381_READY"
_PATCH_ATTR = "_nija_kraken_margin_pair_resolution_v381"
_QUOTES = ("USDT", "USDC", "USD", "EUR")


def _lookup_symbol(value: Any) -> str:
    raw = str(value or "").strip()
    if ":" not in raw:
        return raw
    head, suffix = raw.split(":", 1)
    compact = head.upper().replace("/", "").replace("-", "").replace("_", "")
    if suffix and compact.endswith(_QUOTES):
        return head
    return raw


def _patch_pair_resolver() -> bool:
    module = importlib.import_module("bot.kraken_all_account_exit_runtime_patch")
    current = getattr(module, "_resolve_pair", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    @wraps(current)
    def resolve_pair_v381(broker: Any, symbol: str):
        lookup = _lookup_symbol(symbol)
        pair = current(broker, lookup)
        if lookup != str(symbol or "").strip():
            LOGGER.info(
                "KRAKEN_MARGIN_PAIR_V381_LOOKUP marker=%s synthetic_symbol=%s lookup_symbol=%s pair=%s "
                "position_identity_unchanged=true safety_gates_bypassed=false",
                MARKER,
                symbol,
                lookup,
                pair,
            )
        return pair

    setattr(resolve_pair_v381, _PATCH_ATTR, True)
    setattr(resolve_pair_v381, "__wrapped__", current)
    module._resolve_pair = resolve_pair_v381
    return True


def _install_liveness_v384() -> bool:
    try:
        module = importlib.import_module("bot.runtime_kraken_health_user_refresh_v384_patch")
        installer = getattr(module, "install_import_hook", None) or getattr(module, "install", None)
        return bool(callable(installer) and installer())
    except Exception as exc:
        LOGGER.exception(
            "KRAKEN_MARGIN_PAIR_V381_V384_INSTALL_FAILED marker=%s error=%s:%s "
            "native_backup_deferred=true software_four_way_protection_preserved=true "
            "trading_fail_closed=true safety_gates_bypassed=false",
            MARKER, type(exc).__name__, exc,
        )
        return False


def _reassert_v380() -> bool:
    try:
        v380 = importlib.import_module("bot.runtime_kraken_native_margin_backup_v380_patch")
        installer = getattr(v380, "install_import_hook", None)
        if not callable(installer):
            installer = getattr(v380, "install", None)
        return bool(callable(installer) and installer())
    except Exception as exc:
        LOGGER.exception(
            "KRAKEN_MARGIN_PAIR_V381_V380_REASSERT_FAILED marker=%s error=%s:%s "
            "new_entries_unchanged=true existing_software_protection_preserved=true",
            MARKER,
            type(exc).__name__,
            exc,
        )
        return False


def install_import_hook() -> bool:
    liveness_ready = _install_liveness_v384()
    pair_ready = _patch_pair_resolver() if liveness_ready else False
    native_worker_ready = _reassert_v380() if pair_ready else False
    ready = bool(liveness_ready and pair_ready and native_worker_ready)
    os.environ[_READY_FLAG] = "1" if ready else "0"
    LOGGER.critical(
        "RUNTIME_KRAKEN_MARGIN_PAIR_RESOLUTION_V381_%s marker=%s ready=%s "
        "v384_health_user_refresh=%s synthetic_suffix_lookup_only=true position_identity_unchanged=true "
        "v380_reasserted=%s reduce_only_unchanged=true openorders_proof_unchanged=true "
        "writer_nonce_risk_killswitch_unchanged=true safety_gates_bypassed=false",
        "READY" if ready else "NOT_READY",
        MARKER,
        str(ready).lower(),
        str(liveness_ready).lower(),
        str(native_worker_ready).lower(),
    )
    return ready


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER", "install", "install_import_hook", "_lookup_symbol",
    "_patch_pair_resolver", "_install_liveness_v384",
]
