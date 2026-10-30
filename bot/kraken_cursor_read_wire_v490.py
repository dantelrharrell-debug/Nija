"""Read-only Kraken cursor parameter serialization for the direct krakenex client.

Only the inspected KrakenBroker direct branch sends a form-encoded POST via
krakenex. A gateway JSON request must keep actual Python bools. Unrecognized
broker objects are unchanged, never silently assumed to use direct mode.

This does not authorize a request, allocate nonces or communicate with Kraken.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

_CURSOR_READ_ENDPOINTS = frozenset((
    "TradesHistory", "ClosedOrders", "Ledgers", "OpenOrders",
))


def cursor_read_params(broker: Any, endpoint: str, params: Mapping[str, Any]) -> dict[str, Any]:
    """Return a new dict, lowering only supported direct-mode boolean flags."""
    output = dict(params)
    if (endpoint not in _CURSOR_READ_ENDPOINTS
            or output.get("with_cursor") is not True
            or getattr(broker, "_gateway_url", None) != ""
            or getattr(broker, "_gateway_only_mode", False) is True):
        return output

    output["with_cursor"] = "true"
    if endpoint == "OpenOrders" and type(output.get("trades")) is bool:
        output["trades"] = "true" if output["trades"] else "false"
    return output


__all__ = ["cursor_read_params"]
