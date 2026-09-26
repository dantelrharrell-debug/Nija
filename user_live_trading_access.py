"""Authoritative paid-user live-trading access bridge for NIJA.

This module deliberately sits between billing, user consent, the encrypted
credential vault, and the live multi-account runtime.  It is fail-closed:
missing or contradictory state never grants live execution.
"""
from __future__ import annotations

from dataclasses import dataclass
import logging
import time
from typing import Any, Optional, Sequence, Tuple

from auth import get_api_key_manager
from auth.user_database import get_user_database
from billing_store import get_billing_store
from vault import get_vault
from paid_user_state import get_paid_user_state

logger = logging.getLogger("nija.live_trading_access")

PAID_ACTIVE_STATUSES = frozenset({"active"})
SUPPORTED_USER_BROKERS = frozenset({"kraken", "coinbase", "okx", "alpaca"})


@dataclass(frozen=True)
class LiveTradingAccessDecision:
    user_id: str
    allowed: bool
    blocker: str
    billing_status: str
    consented: bool
    education_mode: bool
    brokers: Tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "allowed": self.allowed,
            "blocker": self.blocker,
            "billing_status": self.billing_status,
            "consented": self.consented,
            "education_mode": self.education_mode,
            "brokers": list(self.brokers),
        }


def _resolve_stores(
    user_db: Any = None,
    billing_store: Any = None,
    vault: Any = None,
) -> tuple[Any, Any, Any]:
    """Resolve authoritative stores.

    Explicitly injected stores remain supported for tests. In production/default
    execution, Redis-paid-user state is authoritative and failures are surfaced
    so live access remains fail-closed instead of falling back to ephemeral
    container SQLite.
    """
    if user_db is not None or billing_store is not None or vault is not None:
        return (
            user_db or get_user_database(),
            billing_store or get_billing_store(),
            vault or get_vault(),
        )
    state = get_paid_user_state()
    return state.users, state.billing, state.vault


def _safe_user(user_id: str, user_db: Any = None) -> Optional[dict[str, Any]]:
    db = user_db or get_user_database()
    try:
        user = db.get_user(user_id)
    except Exception as exc:
        logger.error("LIVE_ACCESS user lookup failed user=%s error=%s", user_id, exc)
        return None
    return user if isinstance(user, dict) else None


def _safe_billing(user_id: str, billing_store: Any = None) -> Any:
    store = billing_store or get_billing_store()
    try:
        return store.get(user_id)
    except Exception as exc:
        logger.error("LIVE_ACCESS billing lookup failed user=%s error=%s", user_id, exc)
        return None


def _safe_brokers(user_id: str, vault: Any = None) -> Tuple[str, ...]:
    store = vault or get_vault()
    try:
        brokers = store.list_user_brokers(user_id)
    except Exception as exc:
        logger.error("LIVE_ACCESS vault broker lookup failed user=%s error=%s", user_id, exc)
        return ()
    normalized = {
        str(broker or "").strip().lower()
        for broker in (brokers or [])
        if str(broker or "").strip().lower() in SUPPORTED_USER_BROKERS
    }
    return tuple(sorted(normalized))


def evaluate_live_trading_access(
    user_id: str,
    *,
    require_live_mode: bool = True,
    require_credentials: bool = True,
    user_db: Any = None,
    billing_store: Any = None,
    vault: Any = None,
) -> LiveTradingAccessDecision:
    """Return the authoritative fail-closed live-trading decision for one user."""
    uid = str(user_id or "").strip()
    if not uid:
        return LiveTradingAccessDecision("", False, "user_id_missing", "", False, True, ())

    try:
        users, billing, secure_vault = _resolve_stores(
            user_db=user_db,
            billing_store=billing_store,
            vault=vault,
        )
    except Exception as exc:
        logger.error(
            "LIVE_ACCESS persistent state unavailable user=%s error=%s",
            uid,
            exc,
        )
        return LiveTradingAccessDecision(
            uid,
            False,
            "persistent_state_unavailable",
            "",
            False,
            True,
            (),
        )

    user = _safe_user(uid, user_db=users)
    if not user:
        return LiveTradingAccessDecision(uid, False, "user_not_found", "", False, True, ())

    if not bool(user.get("enabled", False)):
        return LiveTradingAccessDecision(uid, False, "user_disabled", "", False, True, ())

    billing_record = _safe_billing(uid, billing_store=billing)
    billing_status = str(getattr(billing_record, "status", "") or "").strip().lower()
    if billing_status not in PAID_ACTIVE_STATUSES:
        return LiveTradingAccessDecision(
            uid,
            False,
            "paid_entitlement_inactive",
            billing_status,
            bool(user.get("consented_to_live_trading", False)),
            bool(user.get("education_mode", True)),
            (),
        )

    current_period_end = getattr(billing_record, "current_period_end", None)
    if current_period_end is not None:
        try:
            if int(current_period_end) <= int(time.time()):
                return LiveTradingAccessDecision(
                    uid,
                    False,
                    "paid_entitlement_expired",
                    billing_status,
                    bool(user.get("consented_to_live_trading", False)),
                    bool(user.get("education_mode", True)),
                    (),
                )
        except (TypeError, ValueError, OverflowError):
            return LiveTradingAccessDecision(
                uid,
                False,
                "paid_entitlement_period_invalid",
                billing_status,
                bool(user.get("consented_to_live_trading", False)),
                bool(user.get("education_mode", True)),
                (),
            )

    consented = bool(user.get("consented_to_live_trading", False))
    if not consented:
        return LiveTradingAccessDecision(
            uid, False, "live_trading_consent_missing", billing_status, False,
            bool(user.get("education_mode", True)), ()
        )

    education_mode = bool(user.get("education_mode", True))
    if require_live_mode and education_mode:
        return LiveTradingAccessDecision(
            uid, False, "education_mode_active", billing_status, True, True, ()
        )

    brokers = _safe_brokers(uid, vault=secure_vault)
    if require_credentials and not brokers:
        return LiveTradingAccessDecision(
            uid, False, "broker_credentials_missing", billing_status, True,
            education_mode, ()
        )

    return LiveTradingAccessDecision(
        uid, True, "none", billing_status, consented, education_mode, brokers
    )


def entitlement_allows_new_entries(
    user_id: str,
    user_config: Any = None,
) -> tuple[bool, str]:
    """Continuously gate new entries for dynamically entitled customer accounts.

    Static/operator-managed accounts keep their existing behavior. Dynamic paid
    customer accounts are rechecked every entry cycle so cancellation, expiry,
    payment failure, consent revocation, or education-mode reversion blocks new
    positions without disconnecting the broker or interfering with exits.
    """
    if user_config is None or not bool(
        getattr(user_config, "entitlement_required", False)
    ):
        return True, "not_required"

    decision = evaluate_live_trading_access(
        user_id,
        require_live_mode=True,
        require_credentials=True,
    )
    return decision.allowed, decision.blocker


def hydrate_runtime_credentials(
    user_id: str,
    *,
    brokers: Optional[Sequence[str]] = None,
    user_db: Any = None,
    billing_store: Any = None,
    vault: Any = None,
    api_key_manager: Any = None,
) -> Tuple[str, ...]:
    """Load entitled user's encrypted vault credentials into this process runtime.

    The persistent vault remains authoritative.  This compatibility bridge feeds
    the existing broker constructors that consume per-user environment variables
    and the APIKeyManager cache.  If any configured broker cannot be decrypted,
    the entire user hydration fails closed.
    """
    decision = evaluate_live_trading_access(
        user_id,
        require_live_mode=True,
        require_credentials=True,
        user_db=user_db,
        billing_store=billing_store,
        vault=vault,
    )
    if not decision.allowed:
        raise PermissionError(f"live_trading_blocked:{decision.blocker}")

    selected = tuple(
        str(b or "").strip().lower() for b in (brokers or decision.brokers)
        if str(b or "").strip().lower() in SUPPORTED_USER_BROKERS
    )
    if not selected:
        raise PermissionError("live_trading_blocked:broker_credentials_missing")

    try:
        _, _, secure_vault = _resolve_stores(
            user_db=user_db,
            billing_store=billing_store,
            vault=vault,
        )
    except Exception as exc:
        raise PermissionError(
            "live_trading_blocked:persistent_state_unavailable"
        ) from exc
    manager = api_key_manager or get_api_key_manager()

    pending: list[tuple[str, dict[str, Any]]] = []
    for broker in selected:
        credentials = secure_vault.get_credentials(user_id, broker)
        if not credentials:
            raise PermissionError(f"live_trading_blocked:credential_decrypt_failed:{broker}")
        api_key = str(credentials.get("api_key") or "").strip()
        api_secret = str(credentials.get("api_secret") or "").strip()
        if not api_key or not api_secret:
            raise PermissionError(f"live_trading_blocked:credential_incomplete:{broker}")
        pending.append((broker, credentials))

    hydrated: list[str] = []
    for broker, credentials in pending:
        manager.store_user_api_key(
            user_id=user_id,
            broker=broker,
            api_key=str(credentials["api_key"]),
            api_secret=str(credentials["api_secret"]),
            additional_params=credentials.get("additional_params") or {},
        )
        hydrated.append(broker)

    logger.info(
        "LIVE_ACCESS_RUNTIME_HYDRATED user=%s brokers=%s paid=true consent=true",
        user_id,
        ",".join(hydrated),
    )
    return tuple(hydrated)


def discover_runtime_paid_users(
    *,
    user_db: Any = None,
    billing_store: Any = None,
    vault: Any = None,
    api_key_manager: Any = None,
) -> list[dict[str, Any]]:
    """Discover and hydrate paid users eligible for canonical multi-account runtime."""
    try:
        users, billing, secure_vault = _resolve_stores(
            user_db=user_db,
            billing_store=billing_store,
            vault=vault,
        )
        active_records = billing.list_by_status(PAID_ACTIVE_STATUSES)
    except Exception as exc:
        logger.error(
            "LIVE_ACCESS persistent paid-user discovery unavailable error=%s",
            exc,
        )
        return []

    discovered: list[dict[str, Any]] = []
    for record in active_records:
        user_id = str(getattr(record, "user_id", "") or "").strip()
        if not user_id:
            continue
        decision = evaluate_live_trading_access(
            user_id,
            require_live_mode=True,
            require_credentials=True,
            user_db=users,
            billing_store=billing,
            vault=secure_vault,
        )
        if not decision.allowed:
            logger.info(
                "LIVE_ACCESS_DISCOVERY_SKIPPED user=%s blocker=%s billing_status=%s",
                user_id,
                decision.blocker,
                decision.billing_status,
            )
            continue

        try:
            hydrated = hydrate_runtime_credentials(
                user_id,
                brokers=decision.brokers,
                user_db=users,
                billing_store=billing,
                vault=secure_vault,
                api_key_manager=api_key_manager,
            )
        except Exception as exc:
            logger.warning(
                "LIVE_ACCESS_DISCOVERY_SKIPPED user=%s blocker=credential_hydration_failed error=%s",
                user_id,
                exc,
            )
            continue

        user = users.get_user(user_id) or {}
        display_name = str(user.get("email") or user_id)
        for broker in hydrated:
            discovered.append(
                {
                    "user_id": user_id,
                    "name": display_name,
                    "account_type": "retail",
                    "broker_type": broker,
                    "enabled": True,
                    "description": "Dynamic paid live-trading customer",
                    "copy_from_platform": False,
                    "disabled_symbols": [],
                    "independent_trading": True,
                    "active_trading": True,
                    "source": "paid_entitlement_vault",
                    "entitlement_required": True,
                }
            )

    return discovered


__all__ = [
    "LiveTradingAccessDecision",
    "PAID_ACTIVE_STATUSES",
    "SUPPORTED_USER_BROKERS",
    "evaluate_live_trading_access",
    "entitlement_allows_new_entries",
    "hydrate_runtime_credentials",
    "discover_runtime_paid_users",
]
