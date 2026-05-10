"""Execution venue environment helpers for broker initialization and routing."""

from __future__ import annotations

import os
from typing import Mapping, Optional

_FALSEY = {"0", "false", "no", "off"}
_SUPPORTED_VENUES = {"kraken", "coinbase", "okx", "binance", "alpaca"}
_MULTI_VENUE_MARKERS = {"", "auto", "best", "multi", "multi-venue", "multi_venue", "all"}


def _env(source: Optional[Mapping[str, str]] = None) -> Mapping[str, str]:
    return source if source is not None else os.environ


def _is_enabled(value: str, *, default: bool = True) -> bool:
    raw = str(value or "").strip().lower()
    if not raw:
        return default
    return raw not in _FALSEY


def should_initialize_coinbase_platform(env: Optional[Mapping[str, str]] = None) -> bool:
    """Return True when Coinbase should be connected as an execution venue."""
    source = _env(env)
    return (
        _is_enabled(source.get("NIJA_DISABLE_COINBASE", ""), default=False) is False
        and _is_enabled(source.get("ENABLE_COINBASE", ""), default=True)
        and _is_enabled(source.get("ENABLE_COINBASE_TRADING", ""), default=True)
    )


def get_preferred_execution_venue(env: Optional[Mapping[str, str]] = None) -> Optional[str]:
    """Return a forced single venue, or None when multi-venue routing should decide."""
    source = _env(env)
    raw = str(source.get("PRIMARY_EXECUTION_VENUE", "") or "").strip().lower()
    if raw in _MULTI_VENUE_MARKERS:
        return None
    if raw in _SUPPORTED_VENUES:
        return raw
    return None
