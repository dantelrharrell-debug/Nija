"""Execution venue environment helpers for broker initialization and routing."""

from __future__ import annotations

import os
from typing import List, Mapping, Optional

_FALSEY = {"0", "false", "no", "off"}
_SUPPORTED_VENUES = {"kraken", "coinbase", "okx", "binance", "alpaca"}
_MULTI_VENUE_MARKERS = {"", "auto", "best", "multi", "multi-venue", "multi_venue", "all"}


def _env(source: Optional[Mapping[str, str]] = None) -> Mapping[str, str]:
    return source if source is not None else os.environ


def _parse_bool_flag(value: Optional[str], *, default: bool = True) -> bool:
    raw = str(value or "").strip().lower()
    if not raw:
        return default
    return raw not in _FALSEY


def _is_disabled(value: Optional[str]) -> bool:
    return _parse_bool_flag(value, default=False)


def get_coinbase_platform_skip_reasons(env: Optional[Mapping[str, str]] = None) -> List[str]:
    """Explain why Coinbase platform initialization is blocked."""
    source = _env(env)
    reasons: List[str] = []
    if _is_disabled(source.get("NIJA_DISABLE_COINBASE", "")):
        reasons.append("NIJA_DISABLE_COINBASE=true")
    if not _parse_bool_flag(source.get("ENABLE_COINBASE", ""), default=True):
        reasons.append("ENABLE_COINBASE=false")
    if not _parse_bool_flag(source.get("ENABLE_COINBASE_TRADING", ""), default=False):
        reasons.append("ENABLE_COINBASE_TRADING!=true")
    return reasons


def should_initialize_coinbase_platform(env: Optional[Mapping[str, str]] = None) -> bool:
    """Return True when Coinbase is explicitly opted in for execution routing."""
    return not get_coinbase_platform_skip_reasons(env)


def get_preferred_execution_venue(env: Optional[Mapping[str, str]] = None) -> Optional[str]:
    """Return a forced single venue, or None when multi-venue routing should decide."""
    source = _env(env)
    raw = str(source.get("PRIMARY_EXECUTION_VENUE", "") or "").strip().lower()
    if raw in _MULTI_VENUE_MARKERS:
        return None
    if raw in _SUPPORTED_VENUES:
        return raw
    return None
