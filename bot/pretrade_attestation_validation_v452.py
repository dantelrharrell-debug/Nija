"""Fail-closed, non-authorizing pre-trade attestation evidence validator.

This module performs no broker requests, writes or startup-state mutations.
The supplying producers must independently authenticate live broker/ledger
observations. A reported success never grants execution authority.
"""
from __future__ import annotations

import math
import time
from collections.abc import Mapping
from typing import Any

REQUIRED = (
    "account_permissions", "account_identity", "broker_balances",
    "position_ledger_reconciliation", "protective_exit_readback",
    "open_order_reconciliation", "duplicate_order_fence",
    "writer_lease", "nonce_sequence", "operator_authorization",
    "kill_switch_clear", "risk_limits", "position_sync",
)


def evaluate_pretrade_certificate(
    observations: Mapping[str, Any],
    *,
    now_epoch: float | None = None,
    max_age_s: float = 90.0,
) -> dict[str, Any]:
    """Validate independently sourced, timestamped attestations without authorizing."""
    now = time.time() if now_epoch is None else float(now_epoch)
    missing: list[str] = []
    if not isinstance(observations, Mapping) or not math.isfinite(now):
        return {"certified": False, "missing": list(REQUIRED), "authorizes_orders": False}
    for name in REQUIRED:
        row = observations.get(name)
        if not isinstance(row, Mapping) or row.get("verified") is not True:
            missing.append(name)
            continue
        if row.get("source") not in ("authenticated_broker", "independent_ledger",
                                     "writer_authority", "operator_authority",
                                     "risk_governor"):
            missing.append(name)
            continue
        try:
            epoch = float(row["observed_at_epoch"])
        except (KeyError, TypeError, ValueError, OverflowError):
            missing.append(name)
            continue
        if not math.isfinite(epoch) or epoch <= 0 or not (-5 <= now - epoch <= max_age_s):
            missing.append(name)
    return {
        "certified": not missing,
        "missing": missing,
        "authorizes_orders": False,
        "execution_proof_required_for_this_certificate": False,
        "post_trade_confirmation_required": True,
    }
