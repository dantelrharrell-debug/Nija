"""Authenticated Kraken key-permission evidence for audited NIJA collectors.

This is a single, read-only, non-authorizing v452 provider. A trusted runtime
composition root must inject the existing Kraken client, a separately approved
SHA-256 fingerprint for its API key, the exact account scope, a vetted provider
identity, and the client's canonical monitoring category. Nothing auto-installs.

GetApiKeyInfo proves the responding API key's permissions, not the legal owner,
current positions, complete historical trade/ledger reconciliation, protective
exits, or order-entry authority. Never log or return the API key or broker rows.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
import hashlib
import hmac
import math
import time
from typing import Any

from scripts.nija_kraken_readonly_history_collector_v441 import _broker_account_scope

# Exact permissions needed for read-only account, order and ledger provenance.
# Live order authority is a separate verified prerequisite and is not inferred.
REQUIRED_READ_PERMISSIONS = frozenset({
    "query-funds", "query-open-trades", "query-closed-trades", "query-ledger",
})
MAX_OBSERVATION_AGE_S = 60.0


class KeyInfoEvidenceDenied(ValueError):
    """Fixed, non-secret denial reason (no raw provider exceptions)."""


def _identifier(value: Any) -> bool:
    return (isinstance(value, str) and bool(value)
            and value == value.strip()
            and not any(c.isspace() for c in value))


def _sha256_fingerprint(value: Any) -> str:
    if (not isinstance(value, str) or len(value) != 64
            or any(c not in "0123456789abcdefABCDEF" for c in value)):
        raise KeyInfoEvidenceDenied("reviewed_key_fingerprint_required")
    return value.lower()


def _unrestricted_time(value: Any, *, now_epoch: float,
                       kind: str) -> None:
    # A history query window may omit old entries, even when the key works.
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise KeyInfoEvidenceDenied(kind + "_invalid")
    try:
        stamp = int(value)
    except (ValueError, OverflowError):
        raise KeyInfoEvidenceDenied(kind + "_invalid") from None
    if str(value) != str(stamp) or stamp < 0:
        raise KeyInfoEvidenceDenied(kind + "_invalid")
    if kind in {"query_from", "query_to"} and stamp != 0:
        raise KeyInfoEvidenceDenied("historical_query_window_restricted")
    if kind == "valid_until" and stamp and stamp <= now_epoch:
        raise KeyInfoEvidenceDenied("key_expired")


def make_kraken_key_permission_provider(
    broker: Any, *, account_scope: str,
    approved_api_key_sha256: str,
    reviewed_provider_id: str,
    monitoring_category: Any,
    clock: Callable[[], float] = time.time,
) -> Callable[[], Mapping[str, Any]]:
    """Produce v452 account_permissions only from an authenticated key read.

    The binding values must come from an *independent* operator-reviewed account
    registry; never copy them from response rows or self-reported runtime flags.
    This builder does not authenticate the legal account owner or register the
    resulting callable. The v452 validator still enforces all other providers.
    """
    fingerprint = _sha256_fingerprint(approved_api_key_sha256)
    if (not _identifier(account_scope)
            or not (account_scope == "platform:kraken" or
                    (account_scope.startswith("user:")
                     and account_scope.endswith(":kraken")
                     and len(account_scope.split(":")) == 3
                     and bool(account_scope.split(":")[1])))):
        raise KeyInfoEvidenceDenied("account_scope_invalid")
    if not _identifier(reviewed_provider_id):
        raise KeyInfoEvidenceDenied("trusted_provider_id_required")
    if monitoring_category is None or not callable(clock):
        raise KeyInfoEvidenceDenied("monitoring_boundary_missing")

    def observe() -> Mapping[str, Any]:
        if getattr(broker, "connected", False) is not True:
            raise KeyInfoEvidenceDenied("authenticated_client_unavailable")
        try:
            if _broker_account_scope(broker) != account_scope:
                raise KeyInfoEvidenceDenied("broker_scope_mismatch")
        except (ValueError, AttributeError):
            raise KeyInfoEvidenceDenied("broker_scope_mismatch") from None
        caller = getattr(broker, "_kraken_private_call", None)
        if not callable(caller):
            raise KeyInfoEvidenceDenied("authenticated_client_unavailable")
        started = clock()
        if isinstance(started, bool) or not isinstance(started, (int, float)) or not math.isfinite(started) or started <= 0:
            raise KeyInfoEvidenceDenied("observation_clock_invalid")
        try:
            # Never instantiate credentials or a second nonce writer. The
            # existing Kraken client signs this one private read.
            reply = caller("GetApiKeyInfo", {}, category=monitoring_category)
        except Exception:
            raise KeyInfoEvidenceDenied("authenticated_key_read_failed") from None
        finished = clock()
        if (isinstance(finished, bool) or not isinstance(finished, (int, float))
                or not math.isfinite(finished) or finished < started
                or finished - started > MAX_OBSERVATION_AGE_S):
            raise KeyInfoEvidenceDenied("observation_clock_invalid_or_stale")
        try:
            if (_broker_account_scope(broker) != account_scope
                    or getattr(broker, "connected", False) is not True):
                raise KeyInfoEvidenceDenied("broker_scope_changed")
        except (ValueError, AttributeError):
            raise KeyInfoEvidenceDenied("broker_scope_changed") from None
        if (not isinstance(reply, Mapping) or reply.get("error") != []
                or not isinstance(reply.get("result"), Mapping)):
            raise KeyInfoEvidenceDenied("authenticated_key_read_unverified")
        result = reply["result"]
        actual_key = result.get("apiKey")
        if not isinstance(actual_key, str) or not actual_key:
            raise KeyInfoEvidenceDenied("broker_key_identity_missing")
        actual_fingerprint = hashlib.sha256(actual_key.encode("utf-8")).hexdigest()
        if not hmac.compare_digest(actual_fingerprint, fingerprint):
            raise KeyInfoEvidenceDenied("reviewed_key_fingerprint_mismatch")
        perms = result.get("permissions")
        if (not isinstance(perms, list) or not perms
                or any(not isinstance(p, str) or not p for p in perms)
                or not REQUIRED_READ_PERMISSIONS.issubset(set(perms))):
            raise KeyInfoEvidenceDenied("required_read_permissions_missing")
        for field, kind in (("validUntil", "valid_until"),
                            ("queryFrom", "query_from"),
                            ("queryTo", "query_to")):
            _unrestricted_time(result.get(field), now_epoch=finished, kind=kind)
        # An evidence ID is a correlation ID, not a signature or a fill marker.
        evidence_id = hashlib.sha256(
            ("kraken-key-info-v477:" + fingerprint + ":" +
             account_scope + ":" + repr(started)).encode("utf-8")
        ).hexdigest()
        # GetApiKeyInfo is one nonpaginated read. Do not use its success as a
        # certificate for any historical orders, fills, ledger or positions.
        return {
            "account": account_scope,
            "source": "authenticated_broker",
            "provider_id": reviewed_provider_id,
            "evidence_id": evidence_id,
            "verified": True,
            "read_only": True,
            "scope_verified": True,
            "observed_at_epoch": started,
            "provenance": {
                "account_scope_verified": True,
                "collector_identity_verified": True,
                "snapshot_complete": True,
                "authenticated_broker_read_verified": True,
                "complete_pagination_verified": True,
            },
        }

    return observe


__all__ = ["make_kraken_key_permission_provider", "KeyInfoEvidenceDenied",
           "REQUIRED_READ_PERMISSIONS"]
