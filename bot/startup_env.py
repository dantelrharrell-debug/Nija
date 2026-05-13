"""Helpers for startup-time environment normalization."""

from __future__ import annotations

import os


def _normalized_optional_env(name: str) -> str | None:
    """Return a stripped env value or `None` when effectively unset."""
    raw_value = os.environ.get(name, "")
    value = "".join(ch for ch in raw_value if ch.isprintable()).strip()
    return value or None


def resolve_coinbase_retail_portfolio_id() -> str | None:
    """Return the configured Coinbase retail portfolio override, if any."""
    return _normalized_optional_env("COINBASE_RETAIL_PORTFOLIO_ID")
