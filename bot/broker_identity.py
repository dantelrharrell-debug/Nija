"""Canonical broker/account identity helpers for telemetry and cache keys."""

from __future__ import annotations

from typing import Any


def resolve_broker_label(broker: Any) -> str:
    """Return a stable lowercase broker label."""
    if broker is None:
        return "unknown"
    broker_type = getattr(broker, "broker_type", None)
    broker_value = getattr(broker_type, "value", None)
    if broker_value is not None:
        label = str(broker_value).strip().lower()
        if label:
            return label
    if isinstance(broker_type, str):
        label = broker_type.strip().lower()
        if label:
            return label
    return type(broker).__name__.replace("Broker", "").strip().lower() or "unknown"


def resolve_account_identifier(broker: Any) -> str:
    """Return normalized account identifier, or an empty string when unavailable."""
    raw = str(getattr(broker, "account_identifier", "") or "").strip().lower()
    if not raw or raw == "none":
        return ""
    return raw


def format_broker_identity(broker: Any) -> str:
    """Return canonical broker identity in broker[:account] form."""
    broker_label = resolve_broker_label(broker)
    account_identifier = resolve_account_identifier(broker)
    if not account_identifier or account_identifier in {"platform", broker_label}:
        return broker_label
    return f"{broker_label}:{account_identifier}"
