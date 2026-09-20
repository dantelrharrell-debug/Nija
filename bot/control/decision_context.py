from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import logging
import os
from datetime import datetime, timezone
import threading
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple


logger = logging.getLogger("nija.control.decision_context")
_REDIS_CAS_FALLBACK_LOCK = threading.Lock()


def _default_redis_client():
    """Return the canonical Redis client when configured, otherwise None."""
    try:
        from bot.redis_env import get_redis_url
        redis_url = str(get_redis_url() or "").strip()
        if not redis_url:
            return None
        from bot.redis_runtime import connect_redis_with_fallback
        connected = connect_redis_with_fallback(
            url=redis_url,
            decode_responses=True,
            socket_timeout=2,
            socket_connect_timeout=2,
            retries=1,
            delay_s=0.0,
            log=lambda msg: logger.debug("V2 idempotency redis: %s", msg),
        )
        if isinstance(connected, tuple):
            return connected[0] if connected else None
        return connected
    except Exception as exc:
        logger.warning("V2 idempotency Redis unavailable: %s", exc)
        return None


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
    environment: Optional[str] = None
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
        environment: Optional[str] = None,
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
            environment=environment,
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


@dataclass(frozen=True)
class IdempotencyReservationHandle:
    """Ownership-bearing handle required to mutate one idempotency reservation."""

    key: str
    token: str
    shared_required: bool = False

    def __bool__(self) -> bool:
        return bool(self.key and self.token)

    def to_metadata(self) -> Dict[str, Any]:
        return {
            "duplicate_key": self.key,
            "duplicate_token": self.token,
            "duplicate_shared_required": bool(self.shared_required),
        }

    @classmethod
    def from_metadata(cls, metadata: Dict[str, Any]) -> "IdempotencyReservationHandle":
        data = metadata or {}
        raw_shared = data.get("duplicate_shared_required", False)
        shared_required = (
            raw_shared
            if isinstance(raw_shared, bool)
            else str(raw_shared or "").strip().lower() in {"1", "true", "yes", "on"}
        )
        return cls(
            str(data.get("duplicate_key") or "").strip(),
            str(data.get("duplicate_token") or "").strip(),
            bool(shared_required),
        )


class UserScopedIdempotencyRegistry:
    """Distributed duplicate guard scoped by user/account/broker/signal/direction.

    Redis is the authoritative backend whenever it is configured.  A local
    in-process fallback is retained for paper/backtest development only.
    Production LIVE admission fails closed when shared Redis authority is
    unavailable; it never silently downgrades to process-local protection.
    """

    _KEY_PREFIX = "nija:control:v2:idempotency:"

    def __init__(
        self,
        ttl_seconds: float = 300.0,
        *,
        redis_client=None,
        uncertain_ttl_seconds: Optional[float] = None,
    ) -> None:
        self._lock = threading.Lock()
        self._ttl_seconds = max(1.0, float(ttl_seconds))
        default_uncertain = float(os.getenv("NIJA_V2_UNCERTAIN_IDEMPOTENCY_TTL_S", "86400") or 86400)
        self._uncertain_ttl_seconds = max(
            self._ttl_seconds,
            float(uncertain_ttl_seconds if uncertain_ttl_seconds is not None else default_uncertain),
        )
        self._redis = redis_client
        self._redis_checked = redis_client is not None
        self._states: Dict[str, Dict[str, Any]] = {}
        self._reservation_tokens: Dict[str, str] = {}
        self._reservation_shared_required: Dict[str, bool] = {}

    @staticmethod
    def build_key(context: UserDecisionContext, *, symbol: str, direction: str) -> str:
        """Return a collision-safe, opaque key for one account-scoped intent."""
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

    @classmethod
    def _redis_key(cls, key: str) -> str:
        digest = key[3:] if key.startswith("v2:") else hashlib.sha256(key.encode("utf-8")).hexdigest()
        return cls._KEY_PREFIX + digest

    @staticmethod
    def _requires_shared_authority(context: UserDecisionContext) -> bool:
        mode = str(context.execution_mode or "").strip().lower()
        environment = str(context.environment or "").strip().lower()
        # LIVE with an omitted environment is treated as production. A caller
        # must explicitly name a non-production environment to use local state.
        return mode in {"live", "limited_live"} and environment in {"", "production", "prod"}

    def _get_redis(self):
        if not self._redis_checked:
            with self._lock:
                if not self._redis_checked:
                    self._redis = _default_redis_client()
                    self._redis_checked = True
        return self._redis

    @staticmethod
    def _encode_redis_state(token: str, state: str) -> str:
        return f"{token}|{state}"

    @staticmethod
    def _decode_redis_state(value: Any) -> Tuple[str, str]:
        if isinstance(value, bytes):
            value = value.decode("utf-8", errors="replace")
        raw = str(value or "")
        token, sep, state = raw.partition("|")
        if not sep:
            return "", raw
        return token, state

    def _redis_reserve(self, key: str, token: str, ttl_seconds: float) -> Optional[bool]:
        client = self._get_redis()
        if client is None:
            return None
        try:
            result = client.set(
                self._redis_key(key),
                self._encode_redis_state(token, "submitted"),
                nx=True,
                px=max(1, int(ttl_seconds * 1000)),
            )
            return bool(result)
        except Exception as exc:
            logger.error("V2 idempotency Redis reserve failed error=%s", type(exc).__name__)
            return None

    def _redis_compare_set(
        self,
        key: str,
        token: str,
        state: str,
        ttl_seconds: float,
    ) -> Optional[bool]:
        client = self._get_redis()
        if client is None:
            return None
        redis_key = self._redis_key(key)
        ttl_ms = max(1, int(ttl_seconds * 1000))
        try:
            if hasattr(client, "compare_set"):
                return bool(client.compare_set(
                    redis_key,
                    token,
                    self._encode_redis_state(token, state),
                    px=ttl_ms,
                ))
            if not hasattr(client, "eval"):
                # Minimal/mock Redis clients used in tests may not implement
                # EVAL. A process-global lock preserves CAS semantics for
                # those in-process backends; production Redis uses Lua below.
                with _REDIS_CAS_FALLBACK_LOCK:
                    current = client.get(redis_key)
                    current_token, _current_state = self._decode_redis_state(current)
                    if current_token != token:
                        return False
                    result = client.set(
                        redis_key,
                        self._encode_redis_state(token, state),
                        px=ttl_ms,
                    )
                    return result is not False
            script = (
                "local v=redis.call('GET',KEYS[1]); "
                "if not v then return 0 end; "
                "local p=ARGV[1]..'|'; "
                "if string.sub(v,1,string.len(p)) ~= p then return 0 end; "
                "redis.call('PSETEX',KEYS[1],ARGV[3],ARGV[1]..'|'..ARGV[2]); "
                "return 1"
            )
            return bool(client.eval(script, 1, redis_key, token, state, ttl_ms))
        except Exception as exc:
            logger.error("V2 idempotency Redis compare-set failed state=%s error=%s", state, type(exc).__name__)
            return None

    def _redis_compare_delete(self, key: str, token: str) -> Optional[bool]:
        client = self._get_redis()
        if client is None:
            return None
        redis_key = self._redis_key(key)
        try:
            if hasattr(client, "compare_delete"):
                return bool(client.compare_delete(redis_key, token))
            if not hasattr(client, "eval"):
                with _REDIS_CAS_FALLBACK_LOCK:
                    current = client.get(redis_key)
                    current_token, _current_state = self._decode_redis_state(current)
                    if current_token != token:
                        return False
                    return bool(client.delete(redis_key))
            script = (
                "local v=redis.call('GET',KEYS[1]); "
                "if not v then return 0 end; "
                "local p=ARGV[1]..'|'; "
                "if string.sub(v,1,string.len(p)) ~= p then return 0 end; "
                "return redis.call('DEL',KEYS[1])"
            )
            return bool(client.eval(script, 1, redis_key, token))
        except Exception as exc:
            logger.error("V2 idempotency Redis compare-delete failed error=%s", type(exc).__name__)
            return None

    def reserve(self, context: UserDecisionContext, *, symbol: str, direction: str) -> Tuple[bool, IdempotencyReservationHandle]:
        key = self.build_key(context, symbol=symbol, direction=direction)
        token = uuid.uuid4().hex
        redis_result = self._redis_reserve(key, token, self._ttl_seconds)
        if redis_result is True:
            shared_required = self._requires_shared_authority(context)
            with self._lock:
                self._reservation_tokens[key] = token
                self._reservation_shared_required[key] = shared_required
                self._states[key] = {
                    "state": "submitted",
                    "token": token,
                    "expires_at": time.monotonic() + self._ttl_seconds,
                }
            return True, IdempotencyReservationHandle(key, token, shared_required)
        if redis_result is False:
            return False, IdempotencyReservationHandle(key, "", self._requires_shared_authority(context))
        if self._requires_shared_authority(context):
            logger.critical(
                "V2_IDEMPOTENCY_SHARED_AUTHORITY_UNAVAILABLE broker=%s account=%s fail_closed=true",
                context.broker,
                hashlib.sha256(_clean_identity(context.account_id).encode("utf-8")).hexdigest()[:12],
            )
            return False, IdempotencyReservationHandle(
                key,
                "",
                self._requires_shared_authority(context),
            )

        # Non-live fallback for local paper/backtest use.
        with self._lock:
            entry = self._states.get(key)
            if entry is not None and self._is_expired(entry):
                self._states.pop(key, None)
                self._reservation_tokens.pop(key, None)
                self._reservation_shared_required.pop(key, None)
                entry = None
            state = str((entry or {}).get("state") or "")
            if state and state not in {"reconciled_rejected", "released"}:
                return False, IdempotencyReservationHandle(key, "")
            self._reservation_tokens[key] = token
            self._reservation_shared_required[key] = False
            self._states[key] = {
                "state": "submitted",
                "token": token,
                "expires_at": time.monotonic() + self._ttl_seconds,
            }
        return True, IdempotencyReservationHandle(key, token, False)

    @staticmethod
    def _coerce_handle(handle: Any) -> IdempotencyReservationHandle:
        if isinstance(handle, IdempotencyReservationHandle):
            return handle
        return IdempotencyReservationHandle(str(handle or "").strip(), "", False)

    def _forget_local_if_owned(self, key: str, token: str) -> None:
        """Clear local bookkeeping only when no newer token is present."""
        with self._lock:
            entry = self._states.get(key)
            entry_token = str((entry or {}).get("token") or "")
            reservation_token = str(self._reservation_tokens.get(key, "") or "")
            if reservation_token and reservation_token != token:
                return
            if entry_token and entry_token != token:
                return
            if entry_token == token or reservation_token == token:
                self._states.pop(key, None)
                self._reservation_tokens.pop(key, None)
                self._reservation_shared_required.pop(key, None)

    def mark_state(self, handle: IdempotencyReservationHandle, state: str) -> bool:
        handle = self._coerce_handle(handle)
        key = handle.key
        token = handle.token
        if not key or not token:
            logger.error("V2 idempotency state transition refused: ownership handle unavailable state=%s", state)
            return False
        normalized = str(state or "").strip()
        if normalized in {"released", "reconciled_rejected"}:
            return self.release(handle)
        ttl = (
            self._uncertain_ttl_seconds
            if normalized in {"state_unknown", "submitted_pending", "pending"}
            else self._ttl_seconds
        )
        redis_result = self._redis_compare_set(key, token, normalized, ttl)
        if redis_result is False:
            logger.warning("V2 idempotency stale finalizer refused state=%s", normalized)
            self._forget_local_if_owned(key, token)
            return False

        if redis_result is None:
            # Redis is unavailable. Shared-required reservations must never
            # downgrade to local authority.
            with self._lock:
                shared_required = bool(
                    handle.shared_required
                    or self._reservation_shared_required.get(key, False)
                )
            if shared_required:
                logger.critical(
                    "V2 idempotency shared state transition unavailable state=%s fail_closed=true",
                    normalized,
                )
                return False

            # Local fallback ownership + expiry + mutation are one atomic
            # critical section. This prevents an expired/stale finalizer from
            # racing a replacement reservation and overwriting the new token.
            now = time.monotonic()
            with self._lock:
                entry = self._states.get(key)
                current_token = str(
                    (entry or {}).get("token")
                    or self._reservation_tokens.get(key, "")
                )
                if entry is None or current_token != token:
                    logger.warning(
                        "V2 idempotency local owner mismatch state=%s fail_closed=true",
                        normalized,
                    )
                    return False
                if self._is_expired(entry):
                    self._states.pop(key, None)
                    self._reservation_tokens.pop(key, None)
                    self._reservation_shared_required.pop(key, None)
                    logger.warning(
                        "V2 idempotency expired local finalizer refused state=%s",
                        normalized,
                    )
                    return False
                self._states[key] = {
                    "state": normalized,
                    "token": token,
                    "expires_at": now + ttl,
                }
                self._reservation_tokens[key] = token
                self._reservation_shared_required[key] = False
            logger.warning(
                "V2 idempotency state mirrored locally state=%s",
                normalized,
            )
            return True

        # Shared authority accepted the CAS. Keep a local mirror only for
        # observability; Redis remains authoritative.
        with self._lock:
            self._states[key] = {
                "state": normalized,
                "token": token,
                "expires_at": time.monotonic() + ttl,
            }
            self._reservation_tokens[key] = token
            self._reservation_shared_required[key] = bool(
                handle.shared_required
                or self._reservation_shared_required.get(key, False)
            )
        return True

    def release(self, handle: IdempotencyReservationHandle) -> bool:
        """Remove only the reservation owned by the supplied reservation handle."""
        handle = self._coerce_handle(handle)
        key = handle.key
        token = handle.token
        if not key or not token:
            logger.warning("V2 idempotency release refused: ownership handle unavailable")
            return False
        redis_result = self._redis_compare_delete(key, token)
        if redis_result is False:
            logger.warning("V2 idempotency stale release refused")
            self._forget_local_if_owned(key, token)
            return False

        if redis_result is None:
            with self._lock:
                shared_required = bool(
                    handle.shared_required
                    or self._reservation_shared_required.get(key, False)
                )
            if shared_required:
                logger.critical(
                    "V2 idempotency release not durable; shared authority unchanged"
                )
                return False

            # Validate ownership, expiry and removal atomically for local
            # fallback so a stale handle cannot delete a replacement token.
            with self._lock:
                entry = self._states.get(key)
                current_token = str(
                    (entry or {}).get("token")
                    or self._reservation_tokens.get(key, "")
                )
                if entry is None or current_token != token:
                    logger.warning(
                        "V2 idempotency local release owner mismatch fail_closed=true"
                    )
                    return False
                if self._is_expired(entry):
                    self._states.pop(key, None)
                    self._reservation_tokens.pop(key, None)
                    self._reservation_shared_required.pop(key, None)
                    logger.warning("V2 idempotency expired local release refused")
                    return False
                self._states.pop(key, None)
                self._reservation_tokens.pop(key, None)
                self._reservation_shared_required.pop(key, None)
                return True

        self._forget_local_if_owned(key, token)
        return True

    def get_state(self, key: Any) -> Optional[str]:
        if isinstance(key, IdempotencyReservationHandle):
            key = key.key
        key = str(key or "").strip()
        if not key:
            return None
        client = self._get_redis()
        if client is not None:
            try:
                value = client.get(self._redis_key(key))
                if value is not None:
                    _token, state = self._decode_redis_state(value)
                    return state
            except Exception as exc:
                logger.error("V2 idempotency Redis read failed error=%s", type(exc).__name__)
        with self._lock:
            entry = self._states.get(key)
            if entry is not None and self._is_expired(entry):
                expired_token = str((entry or {}).get("token") or "")
                self._states.pop(key, None)
                if not expired_token or self._reservation_tokens.get(key) == expired_token:
                    self._reservation_tokens.pop(key, None)
                    self._reservation_shared_required.pop(key, None)
                return None
            return None if entry is None else str(entry.get("state") or "")

    @staticmethod
    def _is_expired(entry: Dict[str, Any]) -> bool:
        expires_at = entry.get("expires_at")
        return expires_at is not None and time.monotonic() >= float(expires_at)


_IDEMPOTENCY_REGISTRY_SINGLETON: Optional["UserScopedIdempotencyRegistry"] = None
_IDEMPOTENCY_REGISTRY_LOCK = threading.Lock()


def get_user_scoped_idempotency_registry(redis_client=None) -> "UserScopedIdempotencyRegistry":
    """Return the process-wide V2 registry backed by shared Redis when available."""
    global _IDEMPOTENCY_REGISTRY_SINGLETON
    with _IDEMPOTENCY_REGISTRY_LOCK:
        if _IDEMPOTENCY_REGISTRY_SINGLETON is None:
            _IDEMPOTENCY_REGISTRY_SINGLETON = UserScopedIdempotencyRegistry(redis_client=redis_client)
        elif redis_client is not None and _IDEMPOTENCY_REGISTRY_SINGLETON._redis is None:
            _IDEMPOTENCY_REGISTRY_SINGLETON._redis = redis_client
            _IDEMPOTENCY_REGISTRY_SINGLETON._redis_checked = True
        return _IDEMPOTENCY_REGISTRY_SINGLETON


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
    "IdempotencyReservationHandle",
    "get_user_scoped_idempotency_registry",
    "verify_exit_lifecycle",
    "verify_protection_after_fill",
]
