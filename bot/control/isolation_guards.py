"""
Owner/account isolation guards for Strategy Engine V2.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from types import MappingProxyType
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from bot.control.trading_context import TradingContext


@dataclass(frozen=True)
class PositionSizingDecision:
    context: TradingContext
    symbol: str
    side: str
    quantity: float
    size_usd: float
    stop_distance: float

    def ownership_key(self) -> str:
        return self.context.scope_key


@dataclass(frozen=True)
class ScopedRiskSnapshot:
    """Owner-bound balances, P&L, and positions consumed by one decision."""

    context: TradingContext
    portfolio_value_usd: float
    daily_pnl: float = 0.0
    peak_portfolio_value: Optional[float] = None
    available_balance_usd: Optional[float] = None
    positions: Tuple[Mapping[str, Any], ...] = ()

    def __post_init__(self) -> None:
        numeric_values = {
            "portfolio_value_usd": self.portfolio_value_usd,
            "daily_pnl": self.daily_pnl,
        }
        if self.peak_portfolio_value is not None:
            numeric_values["peak_portfolio_value"] = self.peak_portfolio_value
        if self.available_balance_usd is not None:
            numeric_values["available_balance_usd"] = self.available_balance_usd
        for name, value in numeric_values.items():
            try:
                parsed = float(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"risk_snapshot_invalid:{name}") from exc
            if not math.isfinite(parsed):
                raise ValueError(f"risk_snapshot_invalid:{name}")
        if float(self.portfolio_value_usd) < 0:
            raise ValueError("risk_snapshot_invalid:negative_portfolio_value")
        if self.available_balance_usd is not None and float(self.available_balance_usd) < 0:
            raise ValueError("risk_snapshot_invalid:negative_available_balance")
        object.__setattr__(
            self,
            "positions",
            tuple(MappingProxyType(dict(position)) for position in self.positions),
        )

    @classmethod
    def from_values(
        cls,
        *,
        context: TradingContext,
        portfolio_value_usd: float,
        current_positions: Sequence[Mapping[str, Any]],
        daily_pnl: float = 0.0,
        peak_portfolio_value: Optional[float] = None,
        available_balance_usd: Optional[float] = None,
    ) -> "ScopedRiskSnapshot":
        """Build an immutable snapshot without retaining a mutable list."""
        return cls(
            context=context,
            portfolio_value_usd=portfolio_value_usd,
            daily_pnl=daily_pnl,
            peak_portfolio_value=peak_portfolio_value,
            available_balance_usd=available_balance_usd,
            positions=tuple(dict(position) for position in current_positions),
        )

    def positions_for_owner(self) -> Tuple[Dict[str, Any], ...]:
        """Return owned records, ignore foreign records, reject unscoped data."""
        owned = []
        for index, position in enumerate(self.positions):
            owner = _position_owner_key(position)
            if owner is None:
                raise ValueError(f"position_missing_owner_metadata:index={index}")
            if owner == self.context.owner_key:
                owned.append(dict(position))
        return tuple(owned)


def _position_owner_key(position: Mapping[str, Any]) -> Optional[Tuple[str, str, str, str]]:
    raw_context = position.get("trading_context")
    if isinstance(raw_context, TradingContext):
        return raw_context.owner_key
    if isinstance(raw_context, Mapping):
        try:
            return TradingContext.from_mapping(raw_context).owner_key
        except ValueError:
            return None
    values = (
        str(position.get("user_id") or "").strip(),
        str(position.get("trading_account_id") or "").strip(),
        str(position.get("broker") or "").strip().lower(),
        str(position.get("broker_account_id") or "").strip(),
    )
    return values if all(values) else None


@dataclass(frozen=True)
class ExecutionOwnershipEnvelope:
    context: TradingContext
    symbol: str
    side: str
    quantity: float
    idempotency_key: str
    sizing_decision: PositionSizingDecision
    risk_context: TradingContext


def context_cache_key(context: TradingContext, *parts: str) -> str:
    normalized = [str(part or "").strip().lower() for part in parts if str(part or "").strip()]
    if normalized:
        encoded = json.dumps(normalized, separators=(",", ":")).encode("utf-8")
        suffix = hashlib.sha256(encoded).hexdigest()
        return f"ctx:{context.scope_key}:{suffix}"
    return f"ctx:{context.scope_key}"


def verify_snapshot_ownership(context: TradingContext, snapshot: ScopedRiskSnapshot) -> None:
    """Reject financial state that was captured for a different owner scope."""
    if snapshot.context.scope_key != context.scope_key:
        raise ValueError("ownership_mismatch:risk_snapshot_context_mismatch")


def validate_owner_account_authorization(
    context: TradingContext,
    *,
    authorized_accounts: Mapping[str, str],
) -> None:
    owner = str(
        authorized_accounts.get(f"{context.broker}:{context.broker_account_id}")
        or authorized_accounts.get(context.broker_account_id)
        or authorized_accounts.get(context.trading_account_id)
        or ""
    ).strip()
    if not owner or owner != context.user_id:
        raise ValueError("ownership_mismatch:user_not_authorized_for_account")


def verify_execution_ownership(envelope: ExecutionOwnershipEnvelope) -> None:
    if envelope.sizing_decision.context.scope_key != envelope.context.scope_key:
        raise ValueError("ownership_mismatch:sizing_context_mismatch")
    if envelope.risk_context.scope_key != envelope.context.scope_key:
        raise ValueError("ownership_mismatch:risk_context_mismatch")
    if envelope.sizing_decision.symbol.strip().upper() != envelope.symbol.strip().upper():
        raise ValueError("ownership_mismatch:sizing_symbol_mismatch")
    if envelope.sizing_decision.side.strip().lower() != envelope.side.strip().lower():
        raise ValueError("ownership_mismatch:sizing_side_mismatch")
    if not math.isclose(envelope.sizing_decision.quantity, envelope.quantity, rel_tol=0.0, abs_tol=1e-12):
        raise ValueError("ownership_mismatch:sizing_quantity_mismatch")
    expected_idempotency = envelope.context.make_idempotency_key(
        symbol=envelope.symbol,
        side=envelope.side,
        action="submit_order",
    )
    if expected_idempotency != envelope.idempotency_key:
        raise ValueError("ownership_mismatch:idempotency_scope_mismatch")


def verify_position_ownership(
    *,
    context: TradingContext,
    position: Mapping[str, Any],
) -> None:
    if not position:
        raise ValueError("position_missing")
    owner = str(position.get("user_id") or "").strip()
    account = str(position.get("trading_account_id") or "").strip()
    broker = str(position.get("broker") or "").strip().lower()
    broker_account = str(position.get("broker_account_id") or "").strip()
    position_id = str(position.get("position_id") or "").strip()
    if not position_id:
        raise ValueError("position_missing_authoritative_id")
    if (owner, account, broker, broker_account) != (
        context.user_id,
        context.trading_account_id,
        context.broker,
        context.broker_account_id,
    ):
        raise ValueError("position_owner_mismatch")


def validate_queue_event_context(
    payload: Mapping[str, Any],
    *,
    expected_context: Optional[TradingContext] = None,
    require_same_decision: bool = False,
) -> TradingContext:
    raw_ctx = payload.get("trading_context")
    if isinstance(raw_ctx, TradingContext):
        ctx = raw_ctx
    elif isinstance(raw_ctx, dict):
        ctx = TradingContext.from_mapping(raw_ctx)
    else:
        raise ValueError("queue_event_missing_context")
    if expected_context:
        if ctx.scope_key != expected_context.scope_key:
            raise ValueError("queue_event_context_mismatch")
        if require_same_decision and ctx.decision_id != expected_context.decision_id:
            raise ValueError("queue_event_context_mismatch")
    return ctx
