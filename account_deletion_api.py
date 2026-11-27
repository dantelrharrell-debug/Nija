"""Authenticated NIJA account-deletion API.

Deletion covers the active stores explicitly called below: the current mobile
authentication database and its local verification, reset and 2FA records, encrypted broker vault, legacy in-memory broker
credentials, mobile push registrations, permission state, runtime user cache,
and per-user trading-rule files. A failure never returns a success response.

Other NIJA stores, connected providers and backups are outside this endpoint's
coverage. Successful active-store cleanup is not system-wide erasure or proof
of a retention schedule. Retention exceptions require separately reviewed
policy and implementation; this module does not add any exception or cleanup.
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

_NOT_COVERED = (
    "website submissions, consent history, lead queues, CRM and marketing records",
    "billing, purchase, course, education-progress and trading-history records",
    "the separate member broker vault and authentication-token or two-factor stores outside this service's authentication database",
    "support records, application/security logs, exports and uploaded files",
    "backups and records or copies held by connected service providers",
)


def _scope_disclosures() -> dict[str, object]:
    """Describe the fixed cleanup boundary without implying broader erasure."""
    return {
        "deletion_scope": "covered_active_stores_only",
        "not_covered": list(_NOT_COVERED),
        "retention_notice": (
            "Records outside the covered active stores may remain. This request does not confirm "
            "their deletion, a retention period, or a legal reason for retaining them."
        ),
        "privacy_follow_up": (
            "For other NIJA records and copies held by its service providers, contact support@nijaaitrading.com "
            "to request a separate review. No separate privacy request is submitted automatically. "
            "This action does not cancel a separately managed subscription."
        ),
    }


def _delete_auth_database_records(user_id: str) -> bool:
    user_db = get_user_database()
    conn = sqlite3.connect(user_db.db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        cursor.execute("DELETE FROM login_history WHERE user_id = ?", (user_id,))
        # These tables are created lazily in the same configured database.
        for table, statement in (
            ("email_verification_tokens", "DELETE FROM email_verification_tokens WHERE user_id = ?"),
            ("two_factor_backup_codes", "DELETE FROM two_factor_backup_codes WHERE user_id = ?"),
            ("two_factor_auth", "DELETE FROM two_factor_auth WHERE user_id = ?"),
        ):
            if cursor.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
            ).fetchone():
                cursor.execute(statement, (user_id,))
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
            "account records and sessions in this service's authentication store will be removed",
            "broker credentials in this service's covered vault and legacy credential cache will be removed",
            "registered mobile push tokens in this service's device store will be removed",
            "trading-rule files and permissions in this service's runtime cache will be removed",
            "login history and local verification, reset and two-factor records in this service's authentication database will be removed",
        ],
        "not_deleted": [
            "accounts held directly with brokerages or exchanges",
            "Apple or Google accounts",
            "third-party records those providers control",
        ],
        **_scope_disclosures(),
        "warning": (
            "Account deletion is permanent. Stop live trading and review open broker positions before proceeding."
        ),
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

    stage = "persistent_vault"
    try:
        vault_brokers = _delete_persistent_vault_data(user_id)
        stage = "legacy_credentials"
        legacy_brokers = _delete_legacy_broker_credentials(user_id)
        stage = "mobile_devices"
        devices_deleted = get_mobile_device_store().delete_user_devices(user_id)
        stage = "user_rules"
        rules_deleted = _delete_user_rules(user_id)
        stage = "runtime_state"
        _delete_runtime_state(user_id)
        stage = "authentication_store"
        auth_deleted = _delete_auth_database_records(user_id)
        if not auth_deleted:
            raise RuntimeError("Primary account record was not deleted")

        brokers_deleted = sorted(set(vault_brokers + legacy_brokers))
        logger.warning(
            "ACCOUNT_DELETED scope=covered_active_stores_only brokers=%s devices=%s rules=%s at=%s",
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
            **_scope_disclosures(),
            "message": (
                "Your account records, sessions, local verification, reset and two-factor records, broker "
                "credentials, mobile push registrations and trading-rule state were removed only from "
                "the active stores covered by this deletion service. "
                "Other NIJA records, the separate member broker vault, provider copies and backups are outside "
                "this request. Accounts held directly with brokerages, Apple or Google were not deleted."
            ),
        })
    except Exception as exc:
        # Stage and exception category support diagnosis without copying a user
        # identifier, credential, path or raw provider exception into this log.
        logger.error("ACCOUNT_DELETION_FAILED stage=%s error_type=%s", stage, type(exc).__name__)
        return jsonify({
            "error": "Account deletion could not be confirmed",
            "message": (
                "Complete cleanup could not be confirmed. Cleanup may be partial: some covered records "
                "may already have been removed. Contact NIJA support before retrying. "
                "This response does not confirm that account access has been revoked."
            ),
        }), 500


__all__ = ["account_deletion_api"]
