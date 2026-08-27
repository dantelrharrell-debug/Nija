"""Authenticated NIJA account-deletion API.

Deletion is fail-closed and covers the active NIJA stores currently used by the
mobile stack: authentication/session data, persistent encrypted broker vault,
legacy in-memory broker credentials, mobile push registrations, permission
state, runtime user cache, and per-user trading-rule files.

Third-party brokerage/Apple/Google accounts are never represented as deleted by
this endpoint. Any future legally-required retention must be defined by policy
and counsel before enabling a retention exception.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from api_server import require_auth
from auth import get_api_key_manager, get_user_manager
from auth.user_database import get_user_database
from execution import get_permission_validator
from mobile_device_store import get_mobile_device_store
from vault import get_vault
from bot.user_rules_engine import get_user_rules_engine

logger = logging.getLogger("nija.account_deletion")

account_deletion_api = Blueprint("account_deletion_api", __name__)


def _delete_auth_database_records(user_id: str) -> bool:
    user_db = get_user_database()
    conn = sqlite3.connect(user_db.db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        cursor.execute("DELETE FROM login_history WHERE user_id = ?", (user_id,))
        cursor.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
        deleted = cursor.rowcount > 0
        conn.commit()
        return deleted
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _delete_legacy_broker_credentials(user_id: str) -> list[str]:
    manager = get_api_key_manager()
    deleted: list[str] = []
    for broker in list(manager.list_user_brokers(user_id)):
        if manager.delete_user_api_key(user_id, broker):
            deleted.append(broker)
    manager.user_keys.pop(user_id, None)
    return deleted


def _delete_persistent_vault_data(user_id: str) -> list[str]:
    """Delete encrypted credentials and user-identifiable vault audit rows."""
    vault = get_vault()
    brokers = list(vault.list_user_brokers(user_id))
    conn = sqlite3.connect(vault.db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute("DELETE FROM credentials WHERE user_id = ?", (user_id,))
        cursor.execute("DELETE FROM audit_log WHERE user_id = ?", (user_id,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return brokers


def _delete_runtime_state(user_id: str) -> None:
    get_user_manager().users.pop(user_id, None)
    get_permission_validator().user_permissions.pop(user_id, None)


def _delete_user_rules(user_id: str) -> bool:
    """Remove the user's persisted rules file and cache entry."""
    engine = get_user_rules_engine()
    lock = engine._get_user_lock(user_id)
    with lock:
        path = engine._rules_file(user_id)
        engine._rules_cache.pop(user_id, None)
        if os.path.exists(path):
            os.remove(path)
            return True
    return False


@account_deletion_api.route("/api/account/deletion", methods=["GET"])
@require_auth
def deletion_requirements():
    return jsonify({
        "available": True,
        "user_id": request.user_id,
        "confirmation_phrase": "DELETE MY NIJA ACCOUNT",
        "effects": [
            "NIJA account access and active sessions will be removed",
            "NIJA-held broker API credentials will be removed",
            "registered mobile push tokens will be removed",
            "NIJA trading-rule and permission state will be removed",
            "known NIJA authentication/login records will be removed",
        ],
        "not_deleted": [
            "accounts held directly with brokerages or exchanges",
            "Apple or Google accounts",
            "third-party records those providers control",
        ],
        "retention_notice": (
            "NIJA does not retain an account-linked record by default after this deletion path. "
            "Any future legally required retention exception must be separately documented and implemented."
        ),
        "warning": "Account deletion is permanent. Stop live trading and review open broker positions before proceeding.",
    })


@account_deletion_api.route("/api/account/deletion", methods=["DELETE"])
@require_auth
def delete_account():
    payload = request.get_json(silent=True) or {}
    if str(payload.get("confirmation", "")).strip() != "DELETE MY NIJA ACCOUNT":
        return jsonify({
            "error": "Explicit confirmation required",
            "required_confirmation": "DELETE MY NIJA ACCOUNT",
        }), 400

    user_id = str(request.user_id)
    user_db = get_user_database()
    if not user_db.get_user(user_id):
        return jsonify({"error": "Account is no longer available"}), 404

    try:
        vault_brokers = _delete_persistent_vault_data(user_id)
        legacy_brokers = _delete_legacy_broker_credentials(user_id)
        devices_deleted = get_mobile_device_store().delete_user_devices(user_id)
        rules_deleted = _delete_user_rules(user_id)
        _delete_runtime_state(user_id)
        auth_deleted = _delete_auth_database_records(user_id)
        if not auth_deleted:
            raise RuntimeError("Primary account record was not deleted")

        brokers_deleted = sorted(set(vault_brokers + legacy_brokers))
        logger.warning(
            "ACCOUNT_DELETED user_id=%s brokers=%s devices=%s rules=%s at=%s",
            user_id,
            len(brokers_deleted),
            devices_deleted,
            rules_deleted,
            datetime.now(timezone.utc).isoformat(),
        )
        return jsonify({
            "success": True,
            "status": "deleted",
            "broker_credentials_removed": brokers_deleted,
            "mobile_devices_removed": devices_deleted,
            "trading_rules_removed": rules_deleted,
            "message": (
                "Your NIJA-controlled account data was removed from the active stores covered by this deletion service. "
                "Third-party brokerage, Apple, and Google accounts were not deleted."
            ),
        })
    except Exception:
        logger.exception("Account deletion failed for user %s", user_id)
        return jsonify({
            "error": "Account deletion failed safely",
            "message": (
                "A complete deletion could not be confirmed. Access remains fail-closed where data has already been removed; "
                "contact NIJA support before retrying."
            ),
        }), 500


__all__ = ["account_deletion_api"]
