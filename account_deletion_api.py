"""Authenticated NIJA account-deletion API.

This module implements the mobile/store account-deletion contract without
claiming to erase third-party brokerage accounts or records NIJA must retain
under applicable law. The current implementation removes the account from
NIJA's known authentication database, active sessions, login history,
in-memory user cache, broker credential manager, runtime broker env aliases,
and mobile push-token registry.

Production release owners MUST reconcile this list against every production
data store and processor before representing deletion as complete.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from api_server import require_auth
from auth import get_api_key_manager, get_user_manager
from auth.user_database import get_user_database
from mobile_api import push_tokens

logger = logging.getLogger("nija.account_deletion")

account_deletion_api = Blueprint("account_deletion_api", __name__)


def _delete_auth_database_records(user_id: str) -> bool:
    """Delete known user-linked authentication records in one transaction."""
    user_db = get_user_database()
    conn = sqlite3.connect(user_db.db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("BEGIN")
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


def _delete_broker_credentials(user_id: str) -> list[str]:
    """Remove all NIJA-held broker credentials for a user."""
    manager = get_api_key_manager()
    deleted: list[str] = []
    for broker in list(manager.list_user_brokers(user_id)):
        if manager.delete_user_api_key(user_id, broker):
            deleted.append(broker)
    # Avoid leaving an empty per-user credential bucket in memory.
    manager.user_keys.pop(user_id, None)
    return deleted


def _delete_runtime_user_cache(user_id: str) -> None:
    manager = get_user_manager()
    manager.users.pop(user_id, None)


@account_deletion_api.route("/api/account/deletion", methods=["GET"])
@require_auth
def deletion_requirements():
    """Return deletion semantics for the authenticated user."""
    return jsonify(
        {
            "available": True,
            "user_id": request.user_id,
            "confirmation_phrase": "DELETE MY NIJA ACCOUNT",
            "effects": [
                "NIJA account access will be removed",
                "active NIJA sessions will be removed",
                "NIJA-held broker API credentials will be removed",
                "registered mobile push tokens will be removed",
                "known NIJA authentication/login records will be removed",
            ],
            "not_deleted": [
                "accounts held directly with brokerages or exchanges",
                "Apple or Google accounts",
                "third-party records those providers control",
                "records NIJA is legally required to retain",
            ],
            "warning": "Account deletion is permanent. Stop live trading and review open broker positions before proceeding.",
        }
    )


@account_deletion_api.route("/api/account/deletion", methods=["DELETE"])
@require_auth
def delete_account():
    """Permanently delete the authenticated NIJA account from known stores."""
    payload = request.get_json(silent=True) or {}
    confirmation = str(payload.get("confirmation", "")).strip()
    if confirmation != "DELETE MY NIJA ACCOUNT":
        return jsonify(
            {
                "error": "Explicit confirmation required",
                "required_confirmation": "DELETE MY NIJA ACCOUNT",
            }
        ), 400

    user_id = request.user_id
    user_db = get_user_database()
    if not user_db.get_user(user_id):
        # Do not disclose more detail than necessary; a valid token may outlive
        # an already-deleted database row until JWT expiry.
        return jsonify({"error": "Account is no longer available"}), 404

    try:
        brokers_deleted = _delete_broker_credentials(user_id)
        push_tokens.pop(user_id, None)
        _delete_runtime_user_cache(user_id)
        deleted = _delete_auth_database_records(user_id)
        if not deleted:
            return jsonify({"error": "Account deletion could not be confirmed"}), 500

        logger.warning(
            "ACCOUNT_DELETED user_id=%s broker_credentials_removed=%s at=%s",
            user_id,
            len(brokers_deleted),
            datetime.now(timezone.utc).isoformat(),
        )

        return jsonify(
            {
                "success": True,
                "status": "deleted",
                "broker_credentials_removed": brokers_deleted,
                "message": "Your NIJA account has been deleted from the known active account stores. Third-party brokerage accounts were not deleted.",
                "retention_notice": "Limited records may be retained only where required for legal, tax, accounting, security, fraud-prevention, dispute-resolution, or regulatory obligations.",
            }
        )
    except Exception as exc:
        logger.exception("Account deletion failed for user %s", user_id)
        return jsonify(
            {
                "error": "Account deletion failed safely",
                "message": "The request did not receive a confirmed completion response. Contact NIJA support before retrying if access remains available.",
            }
        ), 500


__all__ = ["account_deletion_api"]
