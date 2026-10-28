"""Read-only validation of an independently sourced NIJA risk-governor snapshot.

Diagnostic only: never generates an attestation, clears a halt, or authorizes
orders. An observed green snapshot is NOT independent risk certification.
"""
from __future__ import annotations

import math
from collections.abc import Mapping


def inspect_risk_snapshot(snapshot: Mapping) -> dict:
    """Fail closed on missing, malformed, stale-context or unsafe risk data."""
    failures = []
    if not isinstance(snapshot, Mapping):
        return {"ready": False, "failures": ["snapshot_missing"], "authorizes_orders": False}
    if snapshot.get("halt_active") is not False:
        failures.append("halt_active_or_unknown")
    if snapshot.get("halt_reason") != "none":
        failures.append("halt_reason_not_none")
    config = snapshot.get("config")
    if not isinstance(config, Mapping):
        config = {}
    for field in ("max_daily_loss_pct", "max_total_risk_pct"):
        value = config.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            failures.append("invalid_" + field)
    for field in ("max_open_positions", "max_consecutive_losses"):
        value = config.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            failures.append("invalid_" + field)
    for field in ("open_positions", "total_risk_usd"):
        value = snapshot.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            failures.append("invalid_" + field)
    if not failures and snapshot["open_positions"] > config["max_open_positions"]:
        failures.append("position_limit_exceeded")
    return {"ready": not failures, "failures": failures, "authorizes_orders": False,
            "independent_certification": False}
