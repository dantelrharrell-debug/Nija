"""
Runtime contract invariants and deterministic intent lineage helpers.
"""

from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass
from typing import Dict, Optional


def _env_truthy(name: str, default: str = "false") -> bool:
    return str(os.getenv(name, default)).strip().lower() in {"1", "true", "yes", "enabled", "on"}


@dataclass(frozen=True)
class RuntimeContractStatus:
    quiet_runtime: bool
    deterministic_runtime: bool
    idempotent_runtime: bool
    correlation_safe_runtime: bool
    release_ready: bool

    def as_dict(self) -> Dict[str, bool]:
        return {
            "quiet_runtime": self.quiet_runtime,
            "deterministic_runtime": self.deterministic_runtime,
            "idempotent_runtime": self.idempotent_runtime,
            "correlation_safe_runtime": self.correlation_safe_runtime,
            "release_ready": self.release_ready,
        }


def build_canonical_intent_id(
    *,
    symbol: str,
    side: str,
    size_usd: float,
    strategy: str = "",
    account_id: str = "",
    cycle_id: str = "",
    trace_id: str = "",
    broker_identity: str = "",
    dedup_window_seconds: Optional[float] = None,
    now_ts: Optional[float] = None,
) -> str:
    """Build deterministic canonical intent id for execution lineage."""
    if dedup_window_seconds is None:
        try:
            dedup_window_seconds = float(os.getenv("NIJA_TRADE_DEDUP_WINDOW_S", "180") or "180")
        except (TypeError, ValueError):
            dedup_window_seconds = 180.0
    dedup_window_seconds = max(30.0, float(dedup_window_seconds))

    symbol_n = str(symbol or "").upper().strip()
    side_n = str(side or "").lower().strip()
    size_cents = int(round(float(size_usd or 0.0) * 100))
    strategy_n = str(strategy or "").strip()
    account_n = str(account_id or "").strip()
    cycle_n = str(cycle_id or "").strip()
    trace_n = str(trace_id or "").strip()
    broker_n = str(broker_identity or "").strip()
    now = float(now_ts if now_ts is not None else time.time())
    bucket = int(now / dedup_window_seconds)

    material = "|".join(
        [
            symbol_n,
            side_n,
            str(size_cents),
            strategy_n,
            account_n,
            cycle_n,
            trace_n,
            broker_n,
            str(bucket),
        ]
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


def evaluate_runtime_contract() -> RuntimeContractStatus:
    """Evaluate process runtime contract invariants."""
    quiet_runtime = _env_truthy("NIJA_RUNTIME_QUIET_MODE", "true")
    deterministic_runtime = not _env_truthy("NIJA_FORCE_LIVE_BYPASS", "false")
    try:
        dedup_window = float(os.getenv("NIJA_TRADE_DEDUP_WINDOW_S", "180") or "180")
    except (TypeError, ValueError):
        dedup_window = 0.0
    idempotent_runtime = dedup_window >= 30.0
    correlation_safe_runtime = _env_truthy("NIJA_RUNTIME_CORRELATION_REQUIRED", "true")
    release_ready = all(
        [
            quiet_runtime,
            deterministic_runtime,
            idempotent_runtime,
            correlation_safe_runtime,
        ]
    )
    return RuntimeContractStatus(
        quiet_runtime=quiet_runtime,
        deterministic_runtime=deterministic_runtime,
        idempotent_runtime=idempotent_runtime,
        correlation_safe_runtime=correlation_safe_runtime,
        release_ready=release_ready,
    )


def assert_runtime_contract_release_ready(*, context: str) -> RuntimeContractStatus:
    """Assert runtime contract if enforcement is enabled."""
    status = evaluate_runtime_contract()
    if not _env_truthy("NIJA_RUNTIME_CONTRACT_ENFORCED", "false"):
        return status
    if status.release_ready:
        return status
    raise RuntimeError(
        "RUNTIME_CONTRACT_VIOLATION "
        f"context={context} checks={status.as_dict()}"
    )
