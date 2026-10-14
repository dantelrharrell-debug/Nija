"""Pure broker-cell order routing checks; does not execute or authorize trades.

The production router must supply authenticated broker account identity and a
durable transactionally consumed idempotency key before placing real orders.
"""
from __future__ import annotations

from dataclasses import dataclass

from bot.member_broker_cells import CellKey, CellState


class RouteDenied(ValueError):
    pass


@dataclass(frozen=True)
class OrderIntent:
    cell: CellKey
    authenticated_member_id: str
    authenticated_broker_account_id: str
    idempotency_key: str


def validate_order_route(
    intent: OrderIntent,
    *,
    cell_status: CellState,
    global_emergency_stop: bool,
    durable_nonce_reserved: bool,
    broker_identity_attested: bool = False,
    account_lease_fenced: bool = False,
) -> str:
    """Reject cross-member/cross-account routes and unreserved duplicate attempts.

    Readiness is a necessary check, not sufficient authorization: caller still
    must enforce broker-side protective orders, exposure limits, entitlement,
    single-use approvals, reconciliation, and live execution evidence.
    """
    if global_emergency_stop or cell_status is not CellState.READY:
        raise RouteDenied("Trading cell not ready")
    if (intent.authenticated_member_id != intent.cell.member_id
            or intent.authenticated_broker_account_id != intent.cell.brokerage_account_id):
        raise RouteDenied("Authenticated owner or brokerage account mismatch")
    if not isinstance(intent.idempotency_key, str) or not (
        8 <= len(intent.idempotency_key) <= 128
    ) or not intent.idempotency_key.isascii() or any(
        not (c.isalnum() or c in "-_") for c in intent.idempotency_key
    ):
        raise RouteDenied("Invalid idempotency key")
    if not broker_identity_attested:
        raise RouteDenied("Broker account identity not attested")
    if not account_lease_fenced:
        raise RouteDenied("Missing account-scoped execution lease")
    if not durable_nonce_reserved:
        raise RouteDenied("Missing durable single-use reservation")
    return intent.cell.isolation_id
