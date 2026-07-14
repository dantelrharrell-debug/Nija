"""Exclude synthetic balance metadata from Kraken position classification.

The dynamic equity layer reads cached balance dictionaries that are enriched by
later guards. Fields such as ``canonical_equity`` and
``held_excluded_from_equity_sum`` are accounting metadata, not Kraken assets.
Without this guard they can be re-read as fake coins, producing symbols such as
``CANONICAL_EQUITY-USD`` and unnecessary public pair lookups.

This patch also corrects the underlying total-equity helper so held telemetry is
never added on top of the same crypto holdings. The final double-count guard
remains in place as an independent defense.
"""

from __future__ import annotations

import importlib
import logging
import os
import threading
from functools import wraps
from types import ModuleType
from typing import Any, Dict, Mapping

logger = logging.getLogger("nija.kraken_equity_metadata_guard")
_MARKER = "20260714-kraken-equity-metadata-v1"
_PATCH_ATTR = "_nija_kraken_equity_metadata_guard_v1"
_LOCK = threading.RLock()
_INSTALLED = False

_EXPLICIT_METADATA_KEYS = {
    "CANONICAL_EQUITY",
    "CANONICAL_TOTAL",
    "HELD_EXCLUDED_FROM_EQUITY_SUM",
    "PORTFOLIO_VALUE",
    "ACCOUNT_EQUITY",
    "AVAILABLE_BALANCE",
    "AVAILABLE_FUNDS",
    "BROKER_COUNT",
    "EXPECTED_BROKERS",
    "CAPITAL_COMPLETENESS",
    "UPDATED_TOTAL_CAPITAL",
    "REAL_CAPITAL",
    "USABLE_CAPITAL",
    "RISK_CAPITAL",
    "OPEN_EXPOSURE_USD",
    "RESERVE_PCT",
    "LAST_UPDATED",
}
_METADATA_PREFIXES = (
    "CANONICAL_",
    "TOTAL_",
    "AVAILABLE_",
    "BROKER_",
    "CAPITAL_",
    "UPDATED_",
    "OPEN_EXPOSURE_",
    "RESERVE_",
    "HELD_EXCLUDED_",
    "LAST_",
)
_METADATA_SUFFIXES = (
    "_EQUITY",
    "_BALANCE",
    "_FUNDS",
    "_CAPITAL",
    "_EXPOSURE",
    "_VALUE",
    "_COUNT",
    "_COMPLETENESS",
    "_UPDATED",
)


def _f(value: Any) -> float:
    try:
        parsed = float(value or 0.0)
        return parsed if parsed == parsed else 0.0
    except Exception:
        return 0.0


def _is_metadata_key(asset: Any) -> bool:
    name = str(asset or "").strip().upper()
    if not name:
        return True
    if name in _EXPLICIT_METADATA_KEYS:
        return True
    # Kraken asset identifiers do not use underscore-delimited accounting words.
    # Restrict the broad rule to underscore names so legitimate symbols remain.
    if "_" not in name:
        return False
    return name.startswith(_METADATA_PREFIXES) or name.endswith(_METADATA_SUFFIXES)


def _filter_assets(raw_assets: Mapping[str, Any]) -> Dict[str, float]:
    filtered: Dict[str, float] = {}
    removed: list[str] = []
    for asset, value in (raw_assets or {}).items():
        if _is_metadata_key(asset):
            removed.append(str(asset))
            continue
        qty = _f(value)
        if qty > 0:
            filtered[str(asset)] = qty
    if removed:
        logger.warning(
            "KRAKEN_EQUITY_METADATA_EXCLUDED marker=%s fields=%s fake_positions_prevented=true",
            _MARKER,
            sorted(set(removed)),
        )
    return filtered


def _canonical_total(equity: ModuleType, payload: Any, positions: list[Mapping[str, Any]]) -> float:
    source = payload if isinstance(payload, dict) else {}
    direct = _f(equity._direct_total_from_payload(source))
    cash = _f(equity._cash_from_payload(source))
    crypto_usd = sum(_f(position.get("size_usd")) for position in positions)
    declared_crypto = max(_f(source.get("crypto_usd")), _f(source.get("non_usd_usd")), 0.0)
    # Held balances describe the locked subset of the same cash/assets and must
    # never be added again.
    return max(direct, cash + max(crypto_usd, declared_crypto))


def _patch_equity_module(equity: ModuleType) -> bool:
    original_extract = getattr(equity, "_extract_raw_balances", None)
    original_build = getattr(equity, "_build_positions", None)
    original_total = getattr(equity, "_payload_total_equity", None)
    if not all(callable(item) for item in (original_extract, original_build, original_total)):
        return False
    if getattr(original_extract, _PATCH_ATTR, False):
        return True

    non_asset_keys = getattr(equity, "_NON_ASSET_BALANCE_KEYS", None)
    if isinstance(non_asset_keys, set):
        non_asset_keys.update(_EXPLICIT_METADATA_KEYS)

    @wraps(original_extract)
    def extract_raw_balances(payload: Any) -> Dict[str, float]:
        return _filter_assets(original_extract(payload))

    @wraps(original_build)
    def build_positions(instance: Any, raw_assets: Mapping[str, Any]):
        return original_build(instance, _filter_assets(raw_assets))

    @wraps(original_total)
    def payload_total_equity(payload: Any, positions: list[Mapping[str, Any]]) -> float:
        return _canonical_total(equity, payload, positions)

    setattr(extract_raw_balances, _PATCH_ATTR, True)
    setattr(build_positions, _PATCH_ATTR, True)
    setattr(payload_total_equity, _PATCH_ATTR, True)
    equity._extract_raw_balances = extract_raw_balances
    equity._build_positions = build_positions
    equity._payload_total_equity = payload_total_equity
    logger.critical(
        "KRAKEN_EQUITY_METADATA_GUARD_PATCHED marker=%s synthetic_assets_blocked=true held_double_count_blocked=true",
        _MARKER,
    )
    return True


def install_import_hook() -> None:
    global _INSTALLED
    with _LOCK:
        modules: list[ModuleType] = []
        for name in ("bot.kraken_equity_runtime_patch", "kraken_equity_runtime_patch"):
            try:
                module = importlib.import_module(name)
            except Exception:
                continue
            if isinstance(module, ModuleType) and module not in modules:
                modules.append(module)
        if not modules or not all(_patch_equity_module(module) for module in modules):
            raise RuntimeError("kraken_equity_runtime_patch_not_patchable")
        _INSTALLED = True
        os.environ["NIJA_KRAKEN_EQUITY_METADATA_GUARD_INSTALLED"] = "1"
    logger.critical("KRAKEN_EQUITY_METADATA_GUARD_INSTALLED marker=%s", _MARKER)


def install() -> None:
    install_import_hook()


__all__ = [
    "install",
    "install_import_hook",
    "_is_metadata_key",
    "_filter_assets",
    "_canonical_total",
    "_patch_equity_module",
]
