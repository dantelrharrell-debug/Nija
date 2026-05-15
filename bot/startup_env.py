"""Helpers for startup-time environment normalization."""

from __future__ import annotations

import os


def normalize_optional_env_value(raw_value: str) -> str | None:
    """Return a normalized value or ``None`` when effectively unset."""
    value = "".join(ch for ch in raw_value if ch.isprintable()).strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1].strip()
    return value or None


def normalized_optional_env(name: str) -> str | None:
    """Return normalized env value by name, or ``None`` when unset/blank."""
    return normalize_optional_env_value(os.environ.get(name, ""))


def first_normalized_env(names: tuple[str, ...]) -> tuple[str | None, str]:
    """Return first configured normalized env value and its source name."""
    for name in names:
        value = normalized_optional_env(name)
        if value:
            return name, value
    return None, ""


def _normalized_optional_env(name: str) -> str | None:
    """Backward-compatible alias for older imports."""
    return normalized_optional_env(name)


def resolve_coinbase_retail_portfolio_id() -> str | None:
    """Return the configured Coinbase retail portfolio override, if any."""
    return normalized_optional_env("COINBASE_RETAIL_PORTFOLIO_ID")
