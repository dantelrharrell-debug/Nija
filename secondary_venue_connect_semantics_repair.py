"""Repair Coinbase/OKX adapter connection-result semantics.

Some NIJA broker adapters establish and verify a connection by setting
``connected``/``is_connected`` but return ``None`` (or a non-authoritative
boolean) from ``connect()``.  The secondary venue activator previously required
both a truthy return value and the connected flag, which could permanently
exclude an authenticated venue from capital and execution routing.

This repair keeps the contract fail-closed: only the adapter's post-call
connection state is authoritative.  A truthy return value without a verified
connected state is still rejected.
"""

from __future__ import annotations

import logging
from typing import Any

import secondary_venue_activation_patch as activation

logger = logging.getLogger("nija.secondary_venue_connect_semantics_repair")
_MARKER = "20260713a"


def _connect(venue: Any, broker: Any, fingerprint: str) -> bool:
    if activation._connected(broker):
        return True

    previous = activation._SECRET_FP.get(venue.name)
    if previous and previous != fingerprint:
        for attr in ("_auth_failed", "auth_failed", "_is_available"):
            if hasattr(broker, attr):
                try:
                    setattr(broker, attr, False if "auth_failed" in attr else True)
                except Exception:
                    pass
    activation._SECRET_FP[venue.name] = fingerprint

    connect = getattr(broker, "connect", None)
    if not callable(connect):
        logger.warning(
            "SECONDARY_VENUE_CONNECT_METHOD_MISSING marker=%s venue=%s broker=%s",
            _MARKER,
            venue.name,
            type(broker).__name__,
        )
        return False

    try:
        raw_result = connect()
    except Exception as exc:
        logger.warning(
            "SECONDARY_VENUE_CONNECT_FAILED marker=%s venue=%s type=%s error=%s",
            _MARKER,
            venue.name,
            type(exc).__name__,
            str(exc)[:240],
        )
        return False

    connected = activation._connected(broker)
    logger.warning(
        "SECONDARY_VENUE_CONNECT_RESULT marker=%s venue=%s return_type=%s return_value=%r connected=%s",
        _MARKER,
        venue.name,
        type(raw_result).__name__,
        raw_result,
        connected,
    )
    return connected


def install() -> None:
    activation._connect = _connect
    activation._NIJA_CONNECT_SEMANTICS_REPAIR_MARKER = _MARKER
    logger.warning(
        "SECONDARY_VENUE_CONNECT_SEMANTICS_REPAIRED marker=%s venues=coinbase,okx",
        _MARKER,
    )


install()

__all__ = ["install", "_connect"]
