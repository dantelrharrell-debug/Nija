"""Pinned Kraken IIBAN evidence for a reviewed, read-only pretrade collector.

A producer for the *account_identity* field only, not legal ownership proof.
The independently approved API-key and account-IIBAN digests must be pinned
before constructing this provider. The existing nonce-owning Kraken client
performs one authenticated GetApiKeyInfo read. Nothing auto-installs or trades.
"""
from __future__ import annotations

import hashlib
import hmac
import math
import time
from collections.abc import Callable, Mapping
from typing import Any

from scripts.nija_kraken_readonly_history_collector_v441 import _broker_account_scope

_MAX_SECONDS = 60.0
_HEX = frozenset("0123456789abcdefABCDEF")


class AccountIdentityEvidenceDenied(ValueError):
    """A fixed denial code; never include broker responses or credentials."""


def _pin(value: Any, kind: str) -> str:
    if (not isinstance(value, str) or len(value) != 64
            or any(char not in _HEX for char in value)):
        raise AccountIdentityEvidenceDenied(kind + "_reviewed_sha256_required")
    return value.lower()


def _scope_valid(scope: Any) -> bool:
    if (not isinstance(scope, str) or not scope or scope != scope.strip()
            or any(char.isspace() for char in scope)):
        return False
    parts = scope.split(":")
    return scope == "platform:kraken" or (
        len(parts) == 3 and parts[0] == "user" and bool(parts[1])
        and parts[2] == "kraken"
    )


def _iiban_digest(raw: Any) -> str:
    # Format normalization is exactly the existing startup identity convention.
    # The digest must have been approved outside this live process.
    if not isinstance(raw, str):
        raise AccountIdentityEvidenceDenied("authenticated_account_iiban_missing")
    canonical = raw.strip().upper()
    if not 6 <= len(canonical) <= 128 or not all(
        char.isascii() and (char.isalnum() or char in " -") for char in canonical
    ):
        raise AccountIdentityEvidenceDenied("authenticated_account_iiban_missing")
    return hashlib.sha256(("kraken\0" + canonical).encode("utf-8")).hexdigest()


def make_kraken_account_identity_provider(
    broker: Any, *, account_scope: str,
    approved_api_key_sha256: str,
    approved_account_iiban_sha256: str,
    reviewed_provider_id: str,
    monitoring_category: Any,
    clock: Callable[[], float] = time.time,
) -> Callable[[], Mapping[str, Any]]:
    """Bind the authenticated IIBAN to external pins before any broker I/O.

    The IIBAN identifies the Kraken account, not the legal beneficial owner.
    Only independently approved account+key pins and provider ID are accepted.
    The v452 certificate must still validate the other twelve evidence fields.
    """
    key_digest = _pin(approved_api_key_sha256, "api_key")
    account_digest = _pin(approved_account_iiban_sha256, "account_iiban")
    if not _scope_valid(account_scope):
        raise AccountIdentityEvidenceDenied("account_scope_invalid")
    if (not isinstance(reviewed_provider_id, str) or not reviewed_provider_id
            or reviewed_provider_id != reviewed_provider_id.strip()
            or any(char.isspace() for char in reviewed_provider_id)):
        raise AccountIdentityEvidenceDenied("reviewed_provider_id_required")
    if monitoring_category is None or not callable(clock):
        raise AccountIdentityEvidenceDenied("monitoring_boundary_missing")

    def observe() -> Mapping[str, Any]:
        try:
            if (getattr(broker, "connected", False) is not True
                    or _broker_account_scope(broker) != account_scope):
                raise AccountIdentityEvidenceDenied("authenticated_broker_scope_unavailable")
        except (ValueError, AttributeError):
            raise AccountIdentityEvidenceDenied("authenticated_broker_scope_unavailable") from None
        caller = getattr(broker, "_kraken_private_call", None)
        if not callable(caller):
            raise AccountIdentityEvidenceDenied("authenticated_client_missing")
        try:
            began = clock()
            if (isinstance(began, bool) or not isinstance(began, (float, int))
                    or not math.isfinite(began) or began <= 0):
                raise AccountIdentityEvidenceDenied("observation_clock_invalid")
            reply = caller("GetApiKeyInfo", {}, category=monitoring_category)
            finished = clock()
        except AccountIdentityEvidenceDenied:
            raise
        except Exception:
            raise AccountIdentityEvidenceDenied("authenticated_identity_read_failed") from None
        if (isinstance(finished, bool) or not isinstance(finished, (float, int))
                or not math.isfinite(finished) or finished < began
                or finished - began > _MAX_SECONDS):
            raise AccountIdentityEvidenceDenied("observation_clock_invalid_or_stale")
        try:
            if (getattr(broker, "connected", False) is not True
                    or _broker_account_scope(broker) != account_scope):
                raise AccountIdentityEvidenceDenied("broker_scope_changed")
        except (ValueError, AttributeError):
            raise AccountIdentityEvidenceDenied("broker_scope_changed") from None
        if (not isinstance(reply, Mapping) or reply.get("error") != []
                or not isinstance(reply.get("result"), Mapping)):
            raise AccountIdentityEvidenceDenied("authenticated_identity_response_invalid")
        data = reply["result"]
        key = data.get("apiKey")
        if not isinstance(key, str) or not key:
            raise AccountIdentityEvidenceDenied("authenticated_api_key_missing")
        observed_key = hashlib.sha256(key.encode("utf-8")).hexdigest()
        if not hmac.compare_digest(observed_key, key_digest):
            raise AccountIdentityEvidenceDenied("reviewed_api_key_mismatch")
        observed_account = _iiban_digest(data.get("iban"))
        if not hmac.compare_digest(observed_account, account_digest):
            raise AccountIdentityEvidenceDenied("reviewed_account_iiban_mismatch")
        # A digest of a time-bound, pinned observation is only a correlation ID.
        # It does not represent execution/fill or proof of legal ownership.
        evidence_id = hashlib.sha256(
            ("kraken-identity-v478:" + account_scope + ":" +
             account_digest + ":" + repr(began)).encode("utf-8")
        ).hexdigest()
        return {
            "account": account_scope,
            "source": "authenticated_broker",
            "provider_id": reviewed_provider_id,
            "evidence_id": evidence_id,
            "verified": True,
            "read_only": True,
            "scope_verified": True,
            "observed_at_epoch": began,
            "provenance": {
                "account_scope_verified": True,
                "collector_identity_verified": True,
                "snapshot_complete": True,
                "authenticated_broker_read_verified": True,
                "complete_pagination_verified": True,
            },
        }

    return observe


__all__ = ["make_kraken_account_identity_provider", "AccountIdentityEvidenceDenied"]
