"""Persistent Redis state for paid NIJA customer live-trading access.

This module deliberately owns a separate Redis namespace and never writes
writer/nonce/risk/order keys. Broker secrets remain Fernet-encrypted at rest.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
import os
from typing import Any, Iterable, Optional

from cryptography.fernet import Fernet

from bot.redis_runtime import create_redis

logger = logging.getLogger("nija.paid_user_state")

PREFIX = "nija:paid_user:v1"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class RedisBillingRecord:
    user_id: str
    provider: str
    customer_id: Optional[str]
    subscription_id: Optional[str]
    checkout_session_id: Optional[str]
    status: str
    offer_code: Optional[str]
    current_period_end: Optional[int]
    updated_at: str


class RedisPaidUserStore:
    def __init__(self, client: Any):
        self.client = client

    def _key(self, user_id: str) -> str:
        return f"{PREFIX}:user:{user_id}"

    def upsert_user(self, user_id: str, **fields: Any) -> dict[str, Any]:
        uid = str(user_id or "").strip()
        if not uid:
            raise ValueError("user_id is required")
        payload: dict[str, str] = {"user_id": uid, "updated_at": _now()}
        for key, value in fields.items():
            if value is None:
                continue
            if isinstance(value, bool):
                payload[key] = "1" if value else "0"
            else:
                payload[key] = str(value)
        self.client.hset(self._key(uid), mapping=payload)
        self.client.sadd(f"{PREFIX}:users", uid)
        return self.get_user(uid) or {}

    def get_user(self, user_id: str) -> Optional[dict[str, Any]]:
        uid = str(user_id or "").strip()
        if not uid:
            return None
        raw = self.client.hgetall(self._key(uid)) or {}
        if not raw:
            return None
        return {
            **raw,
            "user_id": uid,
            "enabled": _as_bool(raw.get("enabled"), True),
            "email_verified": _as_bool(raw.get("email_verified"), False),
            "education_mode": _as_bool(raw.get("education_mode"), True),
            "consented_to_live_trading": _as_bool(
                raw.get("consented_to_live_trading"), False
            ),
        }

    def record_live_trading_consent(self, user_id: str) -> bool:
        uid = str(user_id or "").strip()
        if not self.get_user(uid):
            return False
        now = _now()
        self.client.hset(
            self._key(uid),
            mapping={
                "consented_to_live_trading": "1",
                "live_trading_consent_at": now,
                "risk_acknowledged_at": now,
                "updated_at": now,
            },
        )
        return True

    def set_education_mode(self, user_id: str, enabled: bool) -> bool:
        uid = str(user_id or "").strip()
        if not self.get_user(uid):
            return False
        self.client.hset(
            self._key(uid),
            mapping={
                "education_mode": "1" if enabled else "0",
                "updated_at": _now(),
            },
        )
        return True

    def update_subscription_tier(self, user_id: str, tier: str) -> bool:
        uid = str(user_id or "").strip()
        if not self.get_user(uid):
            return False
        self.client.hset(
            self._key(uid),
            mapping={"subscription_tier": str(tier), "updated_at": _now()},
        )
        return True


class RedisBillingStore:
    def __init__(self, client: Any):
        self.client = client

    def _key(self, user_id: str) -> str:
        return f"{PREFIX}:billing:{user_id}"

    def upsert(
        self,
        *,
        user_id: str,
        status: str,
        customer_id: Optional[str] = None,
        subscription_id: Optional[str] = None,
        checkout_session_id: Optional[str] = None,
        offer_code: Optional[str] = None,
        current_period_end: Optional[int] = None,
    ) -> RedisBillingRecord:
        uid = str(user_id or "").strip()
        normalized = str(status or "").strip().lower()
        if not uid or not normalized:
            raise ValueError("user_id and status are required")

        existing = self.client.hgetall(self._key(uid)) or {}
        old_status = str(existing.get("status") or "").strip().lower()
        if old_status:
            self.client.srem(f"{PREFIX}:billing_status:{old_status}", uid)

        payload = {
            "user_id": uid,
            "provider": "stripe",
            "status": normalized,
            "updated_at": _now(),
        }
        optional = {
            "customer_id": customer_id,
            "subscription_id": subscription_id,
            "checkout_session_id": checkout_session_id,
            "offer_code": offer_code,
            "current_period_end": current_period_end,
        }
        for key, value in optional.items():
            if value is not None:
                payload[key] = str(value)
            elif key in existing:
                payload[key] = str(existing[key])

        self.client.hset(self._key(uid), mapping=payload)
        self.client.sadd(f"{PREFIX}:billing_status:{normalized}", uid)
        self.client.sadd(f"{PREFIX}:billing_users", uid)
        if subscription_id:
            self.client.set(
                f"{PREFIX}:subscription_user:{subscription_id}",
                uid,
            )
        return self.get(uid)  # type: ignore[return-value]

    def get(self, user_id: str) -> Optional[RedisBillingRecord]:
        uid = str(user_id or "").strip()
        raw = self.client.hgetall(self._key(uid)) or {}
        if not raw:
            return None
        period = raw.get("current_period_end")
        return RedisBillingRecord(
            user_id=uid,
            provider=str(raw.get("provider") or "stripe"),
            customer_id=raw.get("customer_id"),
            subscription_id=raw.get("subscription_id"),
            checkout_session_id=raw.get("checkout_session_id"),
            status=str(raw.get("status") or ""),
            offer_code=raw.get("offer_code"),
            current_period_end=int(period) if period not in (None, "") else None,
            updated_at=str(raw.get("updated_at") or ""),
        )

    def list_by_status(self, statuses: Iterable[str]) -> list[RedisBillingRecord]:
        user_ids: set[str] = set()
        for status in statuses or []:
            normalized = str(status or "").strip().lower()
            if normalized:
                user_ids.update(
                    str(v) for v in (
                        self.client.smembers(
                            f"{PREFIX}:billing_status:{normalized}"
                        ) or set()
                    )
                )
        records = [self.get(uid) for uid in sorted(user_ids)]
        return [record for record in records if record is not None]

    def find_user_by_subscription(self, subscription_id: str) -> Optional[str]:
        value = self.client.get(
            f"{PREFIX}:subscription_user:{str(subscription_id or '').strip()}"
        )
        return str(value) if value else None


class RedisCredentialVault:
    def __init__(self, client: Any, encryption_key: Optional[bytes] = None):
        self.client = client
        raw_key = encryption_key
        if raw_key is None:
            env_key = os.getenv("VAULT_ENCRYPTION_KEY", "").strip()
            if not env_key:
                raise RuntimeError(
                    "VAULT_ENCRYPTION_KEY is required for paid-user credentials"
                )
            raw_key = env_key.encode()
        self.cipher = Fernet(raw_key)

    def _key(self, user_id: str, broker: str) -> str:
        return f"{PREFIX}:vault:{user_id}:{broker}"

    def _brokers_key(self, user_id: str) -> str:
        return f"{PREFIX}:vault_brokers:{user_id}"

    def _audit(
        self,
        user_id: str,
        broker: str,
        action: str,
        success: bool,
        ip_address: Optional[str] = None,
    ) -> None:
        record = json.dumps(
            {
                "user_id": user_id,
                "broker": broker,
                "action": action,
                "success": bool(success),
                "ip_address": ip_address,
                "timestamp": _now(),
            },
            separators=(",", ":"),
        )
        pipe = self.client.pipeline()
        pipe.lpush(f"{PREFIX}:vault_audit", record)
        pipe.ltrim(f"{PREFIX}:vault_audit", 0, 9999)
        pipe.execute()

    def store_credentials(
        self,
        user_id: str,
        broker: str,
        api_key: str,
        api_secret: str,
        additional_params: Optional[dict[str, Any]] = None,
        ip_address: Optional[str] = None,
    ) -> bool:
        uid = str(user_id or "").strip()
        br = str(broker or "").strip().lower()
        try:
            if not uid or not br or not api_key or not api_secret:
                raise ValueError("incomplete credentials")
            payload = {
                "api_key_encrypted": self.cipher.encrypt(
                    str(api_key).encode()
                ).decode(),
                "api_secret_encrypted": self.cipher.encrypt(
                    str(api_secret).encode()
                ).decode(),
                "updated_at": _now(),
            }
            if additional_params:
                payload["additional_params_encrypted"] = self.cipher.encrypt(
                    json.dumps(additional_params, separators=(",", ":")).encode()
                ).decode()
            pipe = self.client.pipeline()
            pipe.hset(self._key(uid, br), mapping=payload)
            pipe.sadd(self._brokers_key(uid), br)
            pipe.execute()
            self._audit(uid, br, "STORE_CREDENTIALS", True, ip_address)
            logger.info(
                "PAID_USER_VAULT_STORED user=%s broker=%s backend=redis",
                uid,
                br,
            )
            return True
        except Exception:
            logger.exception(
                "PAID_USER_VAULT_STORE_FAILED user=%s broker=%s",
                uid,
                br,
            )
            try:
                self._audit(uid, br, "STORE_CREDENTIALS", False, ip_address)
            except Exception:
                pass
            return False

    def get_credentials(
        self,
        user_id: str,
        broker: str,
        ip_address: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        uid = str(user_id or "").strip()
        br = str(broker or "").strip().lower()
        try:
            raw = self.client.hgetall(self._key(uid, br)) or {}
            if not raw:
                return None
            result: dict[str, Any] = {
                "api_key": self.cipher.decrypt(
                    str(raw["api_key_encrypted"]).encode()
                ).decode(),
                "api_secret": self.cipher.decrypt(
                    str(raw["api_secret_encrypted"]).encode()
                ).decode(),
                "broker": br,
            }
            additional = raw.get("additional_params_encrypted")
            if additional:
                result["additional_params"] = json.loads(
                    self.cipher.decrypt(str(additional).encode()).decode()
                )
            self._audit(uid, br, "GET_CREDENTIALS", True, ip_address)
            return result
        except Exception:
            logger.exception(
                "PAID_USER_VAULT_GET_FAILED user=%s broker=%s",
                uid,
                br,
            )
            try:
                self._audit(uid, br, "GET_CREDENTIALS", False, ip_address)
            except Exception:
                pass
            return None

    def list_user_brokers(self, user_id: str) -> list[str]:
        values = self.client.smembers(self._brokers_key(str(user_id))) or set()
        return sorted(str(value).strip().lower() for value in values if value)

    def delete_credentials(
        self,
        user_id: str,
        broker: str,
        ip_address: Optional[str] = None,
    ) -> bool:
        uid = str(user_id or "").strip()
        br = str(broker or "").strip().lower()
        pipe = self.client.pipeline()
        pipe.delete(self._key(uid, br))
        pipe.srem(self._brokers_key(uid), br)
        results = pipe.execute()
        deleted = bool(results and int(results[0] or 0) > 0)
        self._audit(uid, br, "DELETE_CREDENTIALS", deleted, ip_address)
        return deleted


@dataclass(frozen=True)
class PaidUserState:
    users: RedisPaidUserStore
    billing: RedisBillingStore
    vault: RedisCredentialVault


_state: Optional[PaidUserState] = None


def get_paid_user_state() -> PaidUserState:
    global _state
    if _state is None:
        client = create_redis(
            decode_responses=True,
            socket_timeout=5,
            socket_connect_timeout=5,
        )
        client.ping()
        _state = PaidUserState(
            users=RedisPaidUserStore(client),
            billing=RedisBillingStore(client),
            vault=RedisCredentialVault(client),
        )
        logger.info(
            "PAID_USER_STATE_READY backend=redis namespace=%s encrypted_vault=true",
            PREFIX,
        )
    return _state


__all__ = [
    "PREFIX",
    "PaidUserState",
    "RedisBillingRecord",
    "RedisBillingStore",
    "RedisCredentialVault",
    "RedisPaidUserStore",
    "get_paid_user_state",
]
