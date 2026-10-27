"""Account-bound Kraken identity evidence, read-only and non-authorizing.

The trusted composition root supplies the existing nonce-owning Kraken broker,
an independently approved IIBAN fingerprint and API-key fingerprint, and a
separately audited provider ID. Never derive these pins from the API response.
This provider covers ONLY v452's account_identity field; it cannot attest to
account balances, ledger lots, protective exits or execution authority.
"""
from __future__ import annotations

import hashlib
import hmac
import math
import time
from collections.abc import Callable, Mapping
from typing import Any

from bot.kraken_authenticated_key_info_v477 import _sha256_fingerprint
from scripts.nija_kraken_readonly_history_collector_v441 import _broker_account_scope

MAX_READ_SECONDS = 60.0


class KrakenIdentityDenied(ValueError):
    """Fixed, non-sensitive refusal; never attach raw API data."""


def _canonical_scope(scope: Any) -> bool:
    if not isinstance(scope, str) or not scope or scope != scope.strip():
        return False
    if any(ch.isspace() for ch in scope):
        return False
    if scope == "platform:kraken":
        return True
    parts = scope.split(":")
    return len(parts) == 3 and parts[0] == "user" and bool(parts[1]) and parts[2] == "kraken"


def _canonical_iban(iban: Any) -> str:
    # Keep the same IIBAN normalization and hash domain used by NIJA's
    # startup_verification_evidence.read_startup_broker_identity.
    if (not isinstance(iban, str) or not iban or len(iban) > 128
            or any(ord(char) < 32 or ord(char) == 127 for char in iban)):
        raise KrakenIdentityDenied("authenticated_account_identifier_invalid")
    value = iban.strip().upper()
    if not value:
        raise KrakenIdentityDenied("authenticated_account_identifier_invalid")
    return value


def _fingerprint_iban(iban: Any) -> str:
    return hashlib.sha256(("kraken\0" + _canonical_iban(iban)).encode("utf-8")).hexdigest()


def make_kraken_account_identity_provider(
    broker: Any,
    *,
    account_scope: str,
    approved_iban_sha256: str,
    approved_api_key_sha256: str,
    reviewed_provider_id: str,
    monitoring_category: Any,
    clock: Callable[[], float] = time.time,
) -> Callable[[], Mapping[str, Any]]:
    """Return a single-field v452 producer using an existing authenticated client.

    The approved pins MUST originate in an independently reviewed account
    registry, not in the first GetApiKeyInfo response or a runtime ready flag.
    The observation never contains IIBAN, API key, or broker response rows.
    """
    try:
        account_pin = _sha256_fingerprint(approved_iban_sha256)
        key_pin = _sha256_fingerprint(approved_api_key_sha256)
    except Exception:
        raise KrakenIdentityDenied("independently_reviewed_pins_required") from None
    if not _canonical_scope(account_scope):
        raise KrakenIdentityDenied("account_scope_invalid")
    if (not isinstance(reviewed_provider_id, str) or not reviewed_provider_id
            or reviewed_provider_id != reviewed_provider_id.strip()
            or any(c.isspace() for c in reviewed_provider_id)):
        raise KrakenIdentityDenied("trusted_provider_id_required")
    if monitoring_category is None or not callable(clock):
        raise KrakenIdentityDenied("monitoring_boundary_missing")

    def observe() -> Mapping[str, Any]:
        if getattr(broker, "connected", False) is not True:
            raise KrakenIdentityDenied("authenticated_client_unavailable")
        try:
            if _broker_account_scope(broker) != account_scope:
                raise KrakenIdentityDenied("broker_scope_mismatch")
        except (ValueError, AttributeError):
            raise KrakenIdentityDenied("broker_scope_mismatch") from None
        read = getattr(broker, "_kraken_private_call", None)
        if not callable(read):
            raise KrakenIdentityDenied("authenticated_client_unavailable")
        started = clock()
        if (isinstance(started, bool) or not isinstance(started, (int, float))
                or not math.isfinite(started) or started <= 0):
            raise KrakenIdentityDenied("observation_clock_invalid")
        try:
            response = read("GetApiKeyInfo", {}, category=monitoring_category)
        except Exception:
            raise KrakenIdentityDenied("authenticated_identity_read_failed") from None
        finished = clock()
        if (isinstance(finished, bool) or not isinstance(finished, (int, float))
                or not math.isfinite(finished) or finished < started
                or finished - started > MAX_READ_SECONDS):
            raise KrakenIdentityDenied("observation_clock_invalid_or_stale")
        try:
            if (_broker_account_scope(broker) != account_scope
                    or getattr(broker, "connected", False) is not True):
                raise KrakenIdentityDenied("broker_scope_changed")
        except (ValueError, AttributeError):
            raise KrakenIdentityDenied("broker_scope_changed") from None
        if (not isinstance(response, Mapping) or response.get("error") != []
                or not isinstance(response.get("result"), Mapping)):
            raise KrakenIdentityDenied("authenticated_identity_read_unverified")
        row = response["result"]
        api_key = row.get("apiKey")
        if not isinstance(api_key, str) or not api_key or len(api_key) > 512:
            raise KrakenIdentityDenied("authenticated_api_key_identity_missing")
        if not hmac.compare_digest(hashlib.sha256(api_key.encode("utf-8")).hexdigest(), key_pin):
            raise KrakenIdentityDenied("approved_api_key_identity_mismatch")
        if not hmac.compare_digest(_fingerprint_iban(row.get("iban")), account_pin):
            raise KrakenIdentityDenied("approved_broker_account_mismatch")
        # An expired key cannot certify a presently authenticated account.
        expiry = row.get("validUntil")
        if (isinstance(expiry, bool) or not isinstance(expiry, (str, int))
                or not str(expiry).isdigit()):
            raise KrakenIdentityDenied("key_expiry_unverified")
        expires_at = int(expiry)
        if expires_at != 0 and expires_at <= finished:
            raise KrakenIdentityDenied("key_expired")

        evidence_id = hashlib.sha256(
            ("kraken-account-identity-v480:" + account_pin + ":" +
             key_pin + ":" + account_scope + ":" + repr(started)).encode("utf-8")
        ).hexdigest()
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


__all__ = ["KrakenIdentityDenied", "make_kraken_account_identity_provider"]
