"""
Owner/account isolation guards for Strategy Engine V2.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional

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
class ExecutionOwnershipEnvelope:
    context: TradingContext
    symbol: str
    side: str
    quantity: float
    idempotency_key: str
    sizing_decision: PositionSizingDecision
    risk_context: TradingContext


def context_cache_key(context: TradingContext, *parts: str) -> str:
    suffix = ":".join(str(part or "").strip().lower() for part in parts if str(part or "").strip())
    if suffix:
        return f"ctx:{context.scope_key}:{suffix}"
    return f"ctx:{context.scope_key}"


def validate_owner_account_authorization(
    context: TradingContext,
    *,
    authorized_accounts: Mapping[str, str],
) -> None:
    owner = str(authorized_accounts.get(context.trading_account_id) or "").strip()
    if not owner or owner != context.user_id:
        raise ValueError("ownership_mismatch:user_not_authorized_for_account")


def verify_execution_ownership(envelope: ExecutionOwnershipEnvelope) -> None:
    if envelope.sizing_decision.context.scope_key != envelope.context.scope_key:
        raise ValueError("ownership_mismatch:sizing_context_mismatch")
    if envelope.risk_context.scope_key != envelope.context.scope_key:
        raise ValueError("ownership_mismatch:risk_context_mismatch")
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
    broker_account = str(position.get("broker_account_id") or "").strip()
    position_id = str(position.get("position_id") or "").strip()
    if not position_id:
        raise ValueError("position_missing_authoritative_id")
    if (owner, account, broker_account) != (
        context.user_id,
        context.trading_account_id,
        context.broker_account_id,
    ):
        raise ValueError("position_owner_mismatch")


def validate_queue_event_context(
    payload: Mapping[str, Any],
    *,
    expected_context: Optional[TradingContext] = None,
) -> TradingContext:
    raw_ctx = payload.get("trading_context")
    if isinstance(raw_ctx, TradingContext):
        ctx = raw_ctx
    elif isinstance(raw_ctx, dict):
        ctx = TradingContext.from_mapping(raw_ctx)
    else:
        raise ValueError("queue_event_missing_context")
    if expected_context and ctx.scope_key != expected_context.scope_key:
        raise ValueError("queue_event_context_mismatch")
    return ctx

