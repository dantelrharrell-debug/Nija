from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from datetime import datetime, timezone
import threading
import time
from typing import Any, Dict, List, Optional, Tuple


PLATFORM_IDENTITY = "PLATFORM"
PROTECTION_PENDING = "PROTECTION_PENDING"
PROTECTION_CONFIRMED = "PROTECTION_CONFIRMED"
PROTECTION_UNVERIFIED = "PROTECTION_UNVERIFIED"
PROTECTION_FAILED = "PROTECTION_FAILED"
EXIT_TRIGGERED = "EXIT_TRIGGERED"
EXIT_SUBMITTED = "EXIT_SUBMITTED"
EXIT_ACCEPTED = "EXIT_ACCEPTED"
EXIT_STATE_UNKNOWN = "EXIT_STATE_UNKNOWN"
EXIT_REJECTED = "EXIT_REJECTED"
EXIT_FILLED = "EXIT_FILLED"
POSITION_CLOSED = "POSITION_CLOSED"


def _clean_identity(value: Any) -> str:
    return str(value or "").strip()


@dataclass(frozen=True)
class UserDecisionContext:
    """Immutable identity context for one account-scoped trading decision."""

    user_id: str
    account_id: str
    broker: str
    portfolio_id: str
    strategy_signal_id: str
    trade_id: str
    risk_profile_id: Optional[str] = None
    execution_mode: Optional[str] = None
    asset_class: Optional[str] = None
    session_id: Optional[str] = None
    correlation_id: Optional[str] = None
    identity_scope: str = "user"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @classmethod
    def platform(
        cls,
        *,
        broker: str,
        portfolio_id: str,
        strategy_signal_id: str,
        trade_id: str,
        execution_mode: Optional[str] = None,
        asset_class: Optional[str] = None,
        session_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> "UserDecisionContext":
        return cls(
            user_id=PLATFORM_IDENTITY,
            account_id=PLATFORM_IDENTITY,
            broker=broker,
            portfolio_id=portfolio_id,
            strategy_signal_id=strategy_signal_id,
            trade_id=trade_id,
            execution_mode=execution_mode,
            asset_class=asset_class,
            session_id=session_id,
            correlation_id=correlation_id,
            identity_scope="platform",
        )

    @property
    def canonical_account_key(self) -> str:
        return f"{self.broker}:{self.account_id}"

    @property
    def canonical_user_key(self) -> str:
        return f"{self.broker}:{self.account_id}:{self.user_id}"

    def validate_for_entry(self) -> List[str]:
        notes: List[str] = []
        required = {
            "broker": self.broker,
            "portfolio_id": self.portfolio_id,
            "strategy_signal_id": self.strategy_signal_id,
            "trade_id": self.trade_id,
        }
        for name, value in required.items():
            if not _clean_identity(value):
                notes.append(f"USER_CONTEXT_UNPROVEN:{name}")

        if self.identity_scope == "platform":
            if _clean_identity(self.user_id).upper() != PLATFORM_IDENTITY:
                notes.append("USER_CONTEXT_UNPROVEN:user_id")
            if _clean_identity(self.account_id).upper() != PLATFORM_IDENTITY:
                notes.append("USER_CONTEXT_UNPROVEN:account_id")
            return notes

        user_id = _clean_identity(self.user_id)
        account_id = _clean_identity(self.account_id)
        if not user_id:
            notes.append("USER_CONTEXT_UNPROVEN:user_id")
        if not account_id:
            notes.append("USER_CONTEXT_UNPROVEN:account_id")
        if user_id.upper() == PLATFORM_IDENTITY or account_id.upper() == PLATFORM_IDENTITY:
            notes.append("USER_CONTEXT_UNPROVEN:platform_fallback_forbidden")
        return notes


@dataclass(frozen=True)
class UserPortfolioSnapshot:
    """Authoritative account snapshot for one user/account/broker tuple."""

    user_id: str
    account_id: str
    broker: str
    balance: Optional[float]
    equity: Optional[float]
    available_buying_power: Optional[float]
    open_positions: Tuple[Dict[str, Any], ...] = ()
    pending_orders: Tuple[Dict[str, Any], ...] = ()
    symbol_exposure: Dict[str, float] = field(default_factory=dict)
    asset_class_exposure: Dict[str, float] = field(default_factory=dict)
    portfolio_exposure: float = 0.0
    daily_realized_pnl: float = 0.0
    daily_unrealized_pnl: float = 0.0
    peak_equity: Optional[float] = None
    risk_limits: Dict[str, Any] = field(default_factory=dict)
    kill_switch_active: bool = False
    platform_kill_switch_active: bool = False
    broker_healthy: bool = True
    positions_fresh: bool = True
    orders_fresh: bool = True
    protection_state: str = PROTECTION_CONFIRMED
    authoritative_positions_proven: bool = True
    margin_enabled: bool = False
    position_sources: Tuple[str, ...] = ()
    metadata: Dict[str, Any] = field(default_factory=dict)

    def validate_for_context(self, context: UserDecisionContext) -> List[str]:
        notes: List[str] = []
        if _clean_identity(self.account_id) != _clean_identity(context.account_id):
            notes.append("USER_CONTEXT_UNPROVEN:account_mismatch")
        if _clean_identity(self.broker).lower() != _clean_identity(context.broker).lower():
            notes.append("USER_CONTEXT_UNPROVEN:broker_mismatch")
        if context.identity_scope != "platform" and _clean_identity(self.user_id) != _clean_identity(context.user_id):
            notes.append("USER_CONTEXT_UNPROVEN:user_mismatch")
        return notes

    def readiness_notes(self, *, symbol: str, direction: str) -> List[str]:
        notes: List[str] = []
        if not self.authoritative_positions_proven:
            notes.append("AUTHORITATIVE_POSITION_UNPROVEN")
        if self.platform_kill_switch_active:
            notes.append("PLATFORM_KILL_SWITCH_ACTIVE")
        if self.kill_switch_active:
            notes.append("USER_KILL_SWITCH_ACTIVE")
        if not self.broker_healthy:
            notes.append("BROKER_UNAVAILABLE")
        if not self.positions_fresh:
            notes.append("POSITION_DATA_STALE")
        if not self.orders_fresh:
            notes.append("ORDER_DATA_STALE")
        has_open_positions = bool(self.open_positions)
        if has_open_positions and self.protection_state in {PROTECTION_UNVERIFIED, PROTECTION_FAILED}:
            notes.append(self.protection_state)
        if self.broker.lower() == "kraken" and not bool(self.metadata.get("kraken_margin_visibility_proven")):
            notes.append("AUTHORITATIVE_POSITION_UNPROVEN")
        for order in self.pending_orders:
            if str(order.get("symbol") or "").upper() != symbol.upper():
                continue
            pending_side = str(order.get("side") or order.get("direction") or "").lower()
            normalized_direction = (
                "buy" if direction.lower() in {"long", "buy"} else "sell" if direction.lower() in {"short", "sell"} else direction.lower()
            )
            if pending_side == normalized_direction:
                notes.append("PENDING_ORDER_EXISTS")
                break
        return notes


class UserScopedIdempotencyRegistry:
    """In-memory duplicate guard scoped by user/account/broker/signal/direction."""

    def __init__(self, ttl_seconds: float = 300.0) -> None:
        self._lock = threading.Lock()
        self._ttl_seconds = max(1.0, float(ttl_seconds))
        self._states: Dict[str, Dict[str, Any]] = {}

    @staticmethod
    def build_key(context: UserDecisionContext, *, symbol: str, direction: str) -> str:
        """Return a collision-safe, opaque key for one account-scoped intent.

        Length-prefixed/canonical JSON semantics avoid delimiter collisions in
        caller-controlled identities.  The digest also prevents raw user/account
        identifiers from leaking into shared-state keys or logs.
        """
        payload = json.dumps(
            {
                "user_id": _clean_identity(context.user_id),
                "account_id": _clean_identity(context.account_id),
                "broker": _clean_identity(context.broker).lower(),
                "symbol": _clean_identity(symbol).upper(),
                "strategy_signal_id": _clean_identity(context.strategy_signal_id),
                "trade_id": _clean_identity(context.trade_id),
                "direction": _clean_identity(direction).lower(),
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return "v2:" + hashlib.sha256(payload).hexdigest()

    def reserve(self, context: UserDecisionContext, *, symbol: str, direction: str) -> Tuple[bool, str]:
        key = self.build_key(context, symbol=symbol, direction=direction)
        with self._lock:
            entry = self._states.get(key)
            if entry is not None and self._is_expired(entry):
                self._states.pop(key, None)
                entry = None
            state = str((entry or {}).get("state") or "")
            if state and state not in {"reconciled_rejected", "released"}:
                return False, key
            self._states[key] = {
                "state": "submitted",
                "expires_at": time.monotonic() + self._ttl_seconds,
            }
        return True, key

    def mark_state(self, key: str, state: str) -> None:
        if not key:
            return
        with self._lock:
            self._states[key] = {
                "state": state,
                "expires_at": None if state == "released" else time.monotonic() + self._ttl_seconds,
            }

    def release(self, key: str) -> None:
        self.mark_state(key, "released")

    def get_state(self, key: str) -> Optional[str]:
        with self._lock:
            entry = self._states.get(key)
            if entry is not None and self._is_expired(entry):
                self._states.pop(key, None)
                return None
            return None if entry is None else str(entry.get("state") or "")

    @staticmethod
    def _is_expired(entry: Dict[str, Any]) -> bool:
        expires_at = entry.get("expires_at")
        return expires_at is not None and time.monotonic() >= float(expires_at)


@dataclass(frozen=True)
class ProtectionVerificationResult:
    state: str
    notes: Tuple[str, ...]


@dataclass(frozen=True)
class ExitVerificationResult:
    state: str
    events: Tuple[str, ...]
    notes: Tuple[str, ...]


def verify_protection_after_fill(
    context: UserDecisionContext,
    *,
    filled_quantity: float,
    stop_loss_order_id: Optional[str],
    take_profit_order_id: Optional[str],
    broker_confirmation: Optional[Dict[str, Any]],
) -> ProtectionVerificationResult:
    notes: List[str] = [f"trade_id:{context.trade_id}"]
    if filled_quantity <= 0:
        return ProtectionVerificationResult(PROTECTION_FAILED, tuple(notes + ["fill_missing"]))
    if not stop_loss_order_id:
        return ProtectionVerificationResult(PROTECTION_FAILED, tuple(notes + ["stop_loss_missing"]))
    if not broker_confirmation:
        return ProtectionVerificationResult(PROTECTION_UNVERIFIED, tuple(notes + ["broker_confirmation_missing"]))
    if not broker_confirmation.get("orders_submitted", True):
        return ProtectionVerificationResult(PROTECTION_FAILED, tuple(notes + ["protection_submission_failed"]))
    stop_ok = bool(stop_loss_order_id) and bool(broker_confirmation.get("stop_loss_verified"))
    tp_required = bool(take_profit_order_id)
    tp_ok = (not tp_required) or bool(broker_confirmation.get("take_profit_verified"))
    if stop_ok and tp_ok:
        return ProtectionVerificationResult(PROTECTION_CONFIRMED, tuple(notes + ["broker_verified"]))
    if bool(broker_confirmation.get("verification_pending")):
        return ProtectionVerificationResult(PROTECTION_PENDING, tuple(notes + ["verification_pending"]))
    return ProtectionVerificationResult(PROTECTION_UNVERIFIED, tuple(notes + ["verification_incomplete"]))


def verify_exit_lifecycle(
    context: UserDecisionContext,
    *,
    exit_reason: str,
    submission_status: str,
    broker_fill_state: str,
    remaining_position_quantity: Optional[float],
) -> ExitVerificationResult:
    events: List[str] = [EXIT_TRIGGERED, EXIT_SUBMITTED]
    notes: List[str] = [f"trade_id:{context.trade_id}", f"exit_reason:{exit_reason}"]

    status = submission_status.upper().strip()
    if status == "REJECTED":
        events.append(EXIT_REJECTED)
        return ExitVerificationResult(EXIT_REJECTED, tuple(events), tuple(notes))
    if status == "STATE_UNKNOWN":
        events.append(EXIT_STATE_UNKNOWN)
        return ExitVerificationResult(EXIT_STATE_UNKNOWN, tuple(events), tuple(notes))

    events.append(EXIT_ACCEPTED)
    fill_state = broker_fill_state.upper().strip()
    if fill_state in {"FILLED", "PARTIAL_FILL", "PARTIAL_FILLED"}:
        events.append(EXIT_FILLED)
    if fill_state in {"FILLED", "PARTIAL_FILL", "PARTIAL_FILLED"} and remaining_position_quantity is not None and remaining_position_quantity <= 0:
        events.append(POSITION_CLOSED)
        return ExitVerificationResult(POSITION_CLOSED, tuple(events), tuple(notes))
    if fill_state in {"FILLED", "PARTIAL_FILL", "PARTIAL_FILLED"}:
        return ExitVerificationResult(EXIT_FILLED, tuple(events), tuple(notes))
    return ExitVerificationResult(EXIT_ACCEPTED, tuple(events), tuple(notes))


__all__ = [
    "EXIT_ACCEPTED",
    "EXIT_FILLED",
    "EXIT_REJECTED",
    "EXIT_STATE_UNKNOWN",
    "EXIT_SUBMITTED",
    "EXIT_TRIGGERED",
    "PLATFORM_IDENTITY",
    "POSITION_CLOSED",
    "PROTECTION_CONFIRMED",
    "PROTECTION_FAILED",
    "PROTECTION_PENDING",
    "PROTECTION_UNVERIFIED",
    "ExitVerificationResult",
    "ProtectionVerificationResult",
    "UserDecisionContext",
    "UserPortfolioSnapshot",
    "UserScopedIdempotencyRegistry",
    "verify_exit_lifecycle",
    "verify_protection_after_fill",
]
