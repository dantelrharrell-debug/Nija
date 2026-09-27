"""Broker-local capital floor guard for NIJA live execution.

This guard protects broker accounts from new-entry orders that could leave the
account too close to a broker capability threshold or NIJA's own operating
reserve. Risk-reducing exits are never blocked by this guard.

Important:
- Alpaca's hard floor defaults to $2,000 because margin/short access requires
  at least that much account equity.
- Kraken, Coinbase, and OKX static floors below are NIJA internal operating
  reserves, not representations of broker-wide account minimums.
- Futures/derivatives reserve requirements are dynamic. When maintenance margin
  or margin-ratio data is supplied, the dynamic requirement can only make the
  guard stricter.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from typing import Any, Optional


_TRUE = {"1", "true", "yes", "on", "enabled", "y"}


def _truthy(name: str, default: bool = True) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in _TRUE


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def _env_float(name: str, default: float) -> float:
    return _safe_float(os.getenv(name, default), default)


def _normalize_broker(value: Any) -> str:
    text = str(value or "").strip().lower()
    compact = text.replace("-", "").replace("_", "").replace(" ", "")
    aliases = {
        "alpacabrokeradapter": "alpaca",
        "alpaca": "alpaca",
        "krakenbrokeradapter": "kraken",
        "kraken": "kraken",
        "coinbasebrokeradapter": "coinbase",
        "coinbase": "coinbase",
        "okxbrokeradapter": "okx",
        "okx": "okx",
    }
    return aliases.get(compact, text)


@dataclass(frozen=True)
class BrokerCapitalFloorPolicy:
    broker: str
    hard_floor_usd: float
    protected_floor_usd: float
    maintenance_margin_multiplier: float
    max_margin_ratio: Optional[float]
    default_stress_loss_pct: float
    fee_slippage_buffer_pct: float


@dataclass(frozen=True)
class CapitalFloorDecision:
    allowed: bool
    broker: str
    state: str
    reason: str
    equity_usd: float
    hard_floor_usd: float
    required_floor_usd: float
    projected_equity_usd: float
    estimated_stress_loss_usd: float
    margin_ratio: Optional[float]

    def to_metadata(self) -> dict[str, Any]:
        return {
            "capital_floor_guard_allowed": self.allowed,
            "capital_floor_guard_state": self.state,
            "capital_floor_guard_reason": self.reason,
            "capital_floor_equity_usd": self.equity_usd,
            "capital_floor_hard_usd": self.hard_floor_usd,
            "capital_floor_required_usd": self.required_floor_usd,
            "capital_floor_projected_equity_usd": self.projected_equity_usd,
            "capital_floor_estimated_stress_loss_usd": self.estimated_stress_loss_usd,
            "capital_floor_margin_ratio": self.margin_ratio,
        }


_DEFAULTS = {
    "alpaca": (2000.0, 2250.0),
    "kraken": (0.0, 800.0),
    "coinbase": (0.0, 400.0),
    "okx": (0.0, 400.0),
}


def get_broker_capital_floor_policy(broker_name: str) -> BrokerCapitalFloorPolicy:
    broker = _normalize_broker(broker_name)
    hard_default, protected_default = _DEFAULTS.get(broker, (0.0, 0.0))
    env_prefix = "NIJA_" + (broker.upper() if broker else "UNKNOWN")
    hard = max(0.0, _env_float(f"{env_prefix}_HARD_FLOOR_USD", hard_default))
    protected = max(
        hard,
        _env_float(f"{env_prefix}_PROTECTED_FLOOR_USD", protected_default),
    )
    maintenance_multiplier = max(
        1.0,
        _env_float(
            f"{env_prefix}_MAINTENANCE_MARGIN_MULTIPLIER",
            _env_float("NIJA_MAINTENANCE_MARGIN_MULTIPLIER", 2.0),
        ),
    )
    max_margin_ratio_raw = _env_float(
        f"{env_prefix}_MAX_MARGIN_RATIO",
        _env_float("NIJA_MAX_MARGIN_RATIO", 0.50),
    )
    max_margin_ratio = min(0.99, max(0.01, max_margin_ratio_raw))
    stress = min(
        1.0,
        max(
            0.0,
            _env_float(
                f"{env_prefix}_DEFAULT_STRESS_LOSS_PCT",
                _env_float("NIJA_CAPITAL_FLOOR_DEFAULT_STRESS_PCT", 0.05),
            ),
        ),
    )
    fee_slippage = min(
        0.25,
        max(
            0.0,
            _env_float(
                f"{env_prefix}_FEE_SLIPPAGE_BUFFER_PCT",
                _env_float("NIJA_CAPITAL_FLOOR_FEE_SLIPPAGE_BUFFER_PCT", 0.01),
            ),
        ),
    )
    return BrokerCapitalFloorPolicy(
        broker=broker,
        hard_floor_usd=hard,
        protected_floor_usd=protected,
        maintenance_margin_multiplier=maintenance_multiplier,
        max_margin_ratio=max_margin_ratio,
        default_stress_loss_pct=stress,
        fee_slippage_buffer_pct=fee_slippage,
    )


def _normalize_margin_ratio(value: Any) -> Optional[float]:
    if value is None:
        return None
    ratio = _safe_float(value, -1.0)
    if ratio < 0.0:
        return None
    if ratio > 1.0:
        ratio /= 100.0
    return ratio


def evaluate_broker_capital_floor(
    *,
    broker_name: str,
    equity_usd: Any,
    order_size_usd: Any,
    side: str,
    intent_type: str = "entry",
    reduce_only: bool = False,
    stop_loss_pct: Any = None,
    maintenance_margin_usd: Any = None,
    margin_ratio: Any = None,
    existing_risk_usd: Any = 0.0,
    explicit_stress_loss_usd: Any = None,
) -> CapitalFloorDecision:
    """Return a fail-closed decision for broker-local capital preservation."""

    policy = get_broker_capital_floor_policy(broker_name)
    broker = policy.broker
    equity = _safe_float(equity_usd, -1.0)
    size = max(0.0, _safe_float(order_size_usd, 0.0))
    intent = str(intent_type or "entry").strip().lower()
    side_norm = str(side or "").strip().lower()
    reducing = bool(reduce_only) or intent in {"exit", "reduce", "close"}

    if not _truthy("NIJA_BROKER_CAPITAL_FLOOR_GUARD_ENABLED", True):
        return CapitalFloorDecision(
            allowed=True,
            broker=broker,
            state="DISABLED",
            reason="capital_floor_guard_disabled",
            equity_usd=max(0.0, equity),
            hard_floor_usd=policy.hard_floor_usd,
            required_floor_usd=policy.protected_floor_usd,
            projected_equity_usd=max(0.0, equity),
            estimated_stress_loss_usd=0.0,
            margin_ratio=_normalize_margin_ratio(margin_ratio),
        )

    if reducing:
        return CapitalFloorDecision(
            allowed=True,
            broker=broker,
            state="EXIT_ONLY",
            reason="risk_reducing_order_allowed",
            equity_usd=max(0.0, equity),
            hard_floor_usd=policy.hard_floor_usd,
            required_floor_usd=policy.protected_floor_usd,
            projected_equity_usd=max(0.0, equity),
            estimated_stress_loss_usd=0.0,
            margin_ratio=_normalize_margin_ratio(margin_ratio),
        )

    if equity < 0.0:
        return CapitalFloorDecision(
            allowed=False,
            broker=broker,
            state="HALT",
            reason="account_equity_unavailable",
            equity_usd=0.0,
            hard_floor_usd=policy.hard_floor_usd,
            required_floor_usd=policy.protected_floor_usd,
            projected_equity_usd=0.0,
            estimated_stress_loss_usd=0.0,
            margin_ratio=_normalize_margin_ratio(margin_ratio),
        )

    maintenance = max(0.0, _safe_float(maintenance_margin_usd, 0.0))
    required_floor = max(
        policy.protected_floor_usd,
        maintenance * policy.maintenance_margin_multiplier,
    )

    ratio = _normalize_margin_ratio(margin_ratio)
    if (
        ratio is not None
        and policy.max_margin_ratio is not None
        and ratio >= policy.max_margin_ratio
    ):
        return CapitalFloorDecision(
            allowed=False,
            broker=broker,
            state="RED",
            reason=(
                f"margin_ratio_too_high:{ratio:.4f}>="
                f"{policy.max_margin_ratio:.4f}"
            ),
            equity_usd=equity,
            hard_floor_usd=policy.hard_floor_usd,
            required_floor_usd=required_floor,
            projected_equity_usd=equity,
            estimated_stress_loss_usd=0.0,
            margin_ratio=ratio,
        )

    if equity <= policy.hard_floor_usd and policy.hard_floor_usd > 0.0:
        return CapitalFloorDecision(
            allowed=False,
            broker=broker,
            state="HALT",
            reason="hard_floor_reached",
            equity_usd=equity,
            hard_floor_usd=policy.hard_floor_usd,
            required_floor_usd=required_floor,
            projected_equity_usd=equity,
            estimated_stress_loss_usd=0.0,
            margin_ratio=ratio,
        )

    explicit_loss = _safe_float(explicit_stress_loss_usd, -1.0)
    if explicit_loss >= 0.0:
        stress_loss = explicit_loss
    else:
        requested_stop = _safe_float(stop_loss_pct, 0.0)
        stress_pct = max(policy.default_stress_loss_pct, requested_stop)
        stress_loss = size * (stress_pct + policy.fee_slippage_buffer_pct)

    stress_loss += max(0.0, _safe_float(existing_risk_usd, 0.0))
    projected_equity = equity - stress_loss

    if projected_equity < required_floor:
        return CapitalFloorDecision(
            allowed=False,
            broker=broker,
            state="RED",
            reason="projected_equity_below_protected_floor",
            equity_usd=equity,
            hard_floor_usd=policy.hard_floor_usd,
            required_floor_usd=required_floor,
            projected_equity_usd=projected_equity,
            estimated_stress_loss_usd=stress_loss,
            margin_ratio=ratio,
        )

    cushion = projected_equity - required_floor
    warning_band = max(25.0, required_floor * 0.05)
    state = "YELLOW" if cushion <= warning_band else "GREEN"
    reason = "capital_floor_buffer_thin" if state == "YELLOW" else "capital_floor_ok"

    return CapitalFloorDecision(
        allowed=True,
        broker=broker,
        state=state,
        reason=reason,
        equity_usd=equity,
        hard_floor_usd=policy.hard_floor_usd,
        required_floor_usd=required_floor,
        projected_equity_usd=projected_equity,
        estimated_stress_loss_usd=stress_loss,
        margin_ratio=ratio,
    )


__all__ = [
    "BrokerCapitalFloorPolicy",
    "CapitalFloorDecision",
    "evaluate_broker_capital_floor",
    "get_broker_capital_floor_policy",
]
