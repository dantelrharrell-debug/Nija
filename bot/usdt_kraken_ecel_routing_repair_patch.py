"""Compatibility shim for the retired USDT→Kraken routing repair.

This module used to patch ECEL and ExecutionPipeline so unset/auto/coinbase
``*-USDT`` orders were force-routed to Kraken.  That behavior is unsafe for the
current venue-selection model because OKX-selected USDT orders must remain on OKX
and Coinbase/auto candidates must be handled by the venue route guard.

The module is intentionally kept importable because old startup hooks and stack
allowlists still reference its name.  Importing it must not mutate ECEL,
ExecutionPipeline, importlib, builtins, or any order route.
"""

from __future__ import annotations

import logging
from types import ModuleType
from typing import Any

logger = logging.getLogger("nija.usdt_kraken_ecel_routing_repair")

_DISABLED_REASON = "legacy_blind_reroute_disabled"


def _is_usdt_spot(symbol: str) -> bool:
    return str(symbol or "").strip().upper().replace("/", "-").endswith("-USDT")


def _install_on_ecel(module: ModuleType) -> bool:
    logger.warning(
        "USDT_KRAKEN_ECEL_REPAIR_SKIPPED reason=%s module=%s",
        _DISABLED_REASON,
        getattr(module, "__name__", "<unknown>"),
    )
    return False


def _install_on_pipeline(module: ModuleType) -> bool:
    logger.warning(
        "USDT_KRAKEN_PIPELINE_ROUTING_REPAIR_SKIPPED reason=%s module=%s",
        _DISABLED_REASON,
        getattr(module, "__name__", "<unknown>"),
    )
    return False


def _install_on_core_loop(module: ModuleType) -> bool:
    logger.warning(
        "LOOP_RUNTIME_REPAIR_SKIPPED source=retired_usdt_kraken_patch reason=%s module=%s",
        _DISABLED_REASON,
        getattr(module, "__name__", "<unknown>"),
    )
    return False


def _try_patch_loaded() -> bool:
    return False


def install_import_hook() -> None:
    logger.warning("USDT_KRAKEN_ECEL_ROUTING_REPAIR_INSTALL_SKIPPED reason=%s", _DISABLED_REASON)


def install() -> None:
    install_import_hook()


def __getattr__(name: str) -> Any:
    if name.startswith("_PATCHED") or name in {"_MONITOR_STARTED", "_ORIGINAL_IMPORT_MODULE"}:
        return False if name != "_ORIGINAL_IMPORT_MODULE" else None
    raise AttributeError(name)
