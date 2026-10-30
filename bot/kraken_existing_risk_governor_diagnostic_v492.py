"""Read-only diagnostic adapter for NIJA's existing global risk governor.

Never instantiates the governor, approves entries, clears halts, or emits
v452 independent risk attestations. The caller must supply the existing
production governor object; its get_status() holds the governor's lock.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def inspect_existing_risk_governor(governor: Any) -> dict[str, Any]:
    """Fail closed when a complete, consistent governor snapshot is absent."""
    result = {
        "ready": False, "authorizes_orders": False,
        "independent_certification": False, "failures": [],
    }
    if governor is None or not callable(getattr(governor, "get_status", None)):
        result["failures"].append("existing_governor_missing")
        return result
    try:
        snapshot = governor.get_status()
    except Exception:
        result["failures"].append("governor_snapshot_failed")
        return result
    if not isinstance(snapshot, Mapping):
        result["failures"].append("invalid_governor_snapshot")
        return result
    if snapshot.get("halt_active") is not False or snapshot.get("halt_reason") != "none":
        result["failures"].append("halt_not_independently_cleared")
    config = snapshot.get("config")
    if not isinstance(config, Mapping):
        result["failures"].append("risk_config_missing")
    else:
        for key in ("max_daily_loss_pct", "max_consecutive_losses", "max_open_positions", "max_total_risk_pct"):
            value = config.get(key)
            if type(value) not in (int, float) or not (0 < value < float("inf")):
                result["failures"].append("invalid_" + key)
    for key in ("open_positions", "consecutive_losses"):
        value = snapshot.get(key)
        if type(value) is not int or value < 0:
            result["failures"].append("invalid_" + key)
    result["ready"] = not result["failures"]
    return result
