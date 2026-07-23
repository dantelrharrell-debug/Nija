"""Execution venue environment helpers for broker initialization and routing.

The production live-crypto contract is intentionally limited to Kraken,
Coinbase, and OKX. Alpaca remains available to user/paper workflows elsewhere
in the repository, and Binance is a legacy/future label without a canonical
live broker adapter in the active MultiAccountBrokerManager.
"""

from __future__ import annotations

import os
from typing import List, Mapping, Optional

_FALSEY = {"0", "false", "no", "off"}
_LIVE_EXECUTION_VENUES = {"kraken", "coinbase", "okx"}
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
    if not _parse_bool_flag(source.get("ENABLE_COINBASE_TRADING", ""), default=True):
        reasons.append("ENABLE_COINBASE_TRADING!=true")
    return reasons


def should_initialize_coinbase_platform(env: Optional[Mapping[str, str]] = None) -> bool:
    """Return True when Coinbase is explicitly opted in for execution routing."""
    return not get_coinbase_platform_skip_reasons(env)


def get_okx_platform_skip_reasons(
    env: Optional[Mapping[str, str]] = None,
    *,
    credentials_configured: bool,
) -> List[str]:
    """Explain why OKX platform initialization is blocked."""
    source = _env(env)
    reasons: List[str] = []
    if _is_disabled(source.get("NIJA_DISABLE_OKX", "")):
        reasons.append("NIJA_DISABLE_OKX=true")
    if not credentials_configured:
        reasons.append("credentials not configured")
    return reasons


def should_initialize_okx_platform(
    env: Optional[Mapping[str, str]] = None,
    *,
    credentials_configured: bool,
) -> bool:
    """Return True when OKX credentials are present and the venue is not disabled."""
    return not get_okx_platform_skip_reasons(
        env,
        credentials_configured=credentials_configured,
    )


def get_preferred_execution_venue(env: Optional[Mapping[str, str]] = None) -> Optional[str]:
    """Return a forced live venue, or ``None`` for automatic multi-venue routing.

    Only venues with a canonical production connection, entry, and broker-native
    exit path may be forced here. Unsupported/legacy labels fail closed to the
    normal multi-venue selector instead of steering an order toward an adapter
    that the active runtime cannot initialize.
    """
    source = _env(env)
    raw = str(source.get("PRIMARY_EXECUTION_VENUE", "") or "").strip().lower()
    if raw in _MULTI_VENUE_MARKERS:
        return None
    if raw in _LIVE_EXECUTION_VENUES:
        return raw
    return None
