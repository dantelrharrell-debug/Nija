"""Verify independently signed general approval; never grant execution authority.

Public keys and deployment/account pins belong to a separately reviewed
composition root. This module has no signing, approval-creation, installation,
environment fallback, or order-submission path.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import math
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from bot.kraken_authenticated_account_identity_v478 import _scope_valid

logger = logging.getLogger(__name__)
_APPROVAL_FIELDS = frozenset({
    "contract", "approval_id", "broker", "account", "account_iiban_sha256",
    "api_key_sha256", "mode", "scope", "operator_id", "approved_at_epoch",
    "expires_at_epoch", "release_id",
})
_STATUS_FIELDS = frozenset({
    "contract", "approval_id", "approval_sha256", "status", "generation",
    "observed_at_epoch", "expires_at_epoch",
})


class OperatorAuthorizationDenied(ValueError):
    """A fixed denial reason containing no approval contents or identities."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _identifier(value: Any) -> bool:
    return isinstance(value, str) and 0 < len(value) <= 256 and not any(c.isspace() for c in value)


def _digest(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _timestamp(value: Any) -> bool:
    return (
        not isinstance(value, bool) and isinstance(value, (int, float))
        and math.isfinite(value) and value > 0
    )


def _verified_payload(envelope: Any, public_key: bytes, fields: frozenset[str]) -> dict[str, Any]:
    if not isinstance(envelope, dict) or set(envelope) != {"payload", "signature"}:
        raise OperatorAuthorizationDenied("signed_record_required")
    payload = envelope["payload"]
    if not isinstance(payload, dict) or set(payload) != fields:
        raise OperatorAuthorizationDenied("signed_record_schema_invalid")
    signature = envelope["signature"]
    if not isinstance(signature, str) or len(signature) > 128:
        raise OperatorAuthorizationDenied("signature_invalid")
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(
            base64.b64decode(signature, validate=True), _canonical(payload),
        )
    except (ValueError, TypeError, InvalidSignature):
        raise OperatorAuthorizationDenied("signature_invalid") from None
    return payload


@dataclass(frozen=True)
class GeneralApprovalBinding:
    """Externally approved pins; SHA-256 conventions match the v478 identity."""

    account: str
    account_iiban_sha256: str
    api_key_sha256: str
    mode: str
    scope: tuple[str, ...]
    release_id: str
    provider_id: str

    def validate(self) -> None:
        """Require exact, unambiguous immutable account and permission pins."""
        if (not _scope_valid(self.account) or not _digest(self.account_iiban_sha256)
                or not _digest(self.api_key_sha256) or not _identifier(self.release_id)
                or not _identifier(self.provider_id) or self.mode not in {"spot", "margin"}
                or not isinstance(self.scope, tuple) or not self.scope
                or not all(_identifier(item) for item in self.scope)
                or tuple(sorted(set(self.scope))) != self.scope):
            raise OperatorAuthorizationDenied("reviewed_binding_invalid")


def make_general_operator_authorization_provider(
    *,
    binding: GeneralApprovalBinding,
    operator_public_keys: Mapping[str, bytes],
    revocation_public_key: bytes,
    read_records: Callable[[], Mapping[str, Any]],
    independently_reviewed: bool = False,
    clock: Callable[[], float] = time.time,
) -> Callable[[], Mapping[str, Any]]:
    """Verify approval and current signed revocation membership on every read.

    ``read_records`` returns ``approval`` and ``status`` signed envelopes.
    The status signer must positively attest that this exact approval digest
    is active; absence from an optional revocation list is not sufficient.
    Key custody, identity vetting and approval issuance are external dependencies.
    No general approval is inferred from startup-plan approval or Redis health.
    """
    if independently_reviewed is not True:
        raise OperatorAuthorizationDenied("independent_review_required")
    binding.validate()
    keys = dict(operator_public_keys)
    if (not keys or any(not _identifier(operator) or not isinstance(key, bytes) or len(key) != 32
                        for operator, key in keys.items())
            or not isinstance(revocation_public_key, bytes) or len(revocation_public_key) != 32
            or revocation_public_key in keys.values()
            or not callable(read_records) or not callable(clock)):
        raise OperatorAuthorizationDenied("independent_trust_roots_required")

    def observe() -> Mapping[str, Any]:
        row: dict[str, Any] = {
            "account": binding.account, "source": "operator_authority",
            "provider_id": binding.provider_id, "evidence_id": uuid.uuid4().hex,
            "observed_at_epoch": None, "verified": False, "read_only": True,
            "scope_verified": False, "authorizes_orders": False,
            "provenance": {
                "account_scope_verified": False, "collector_identity_verified": True,
                "snapshot_complete": False, "operator_approval_verified": False,
            },
        }
        try:
            stamp = clock()
            row["observed_at_epoch"] = stamp
            if not _timestamp(stamp):
                raise OperatorAuthorizationDenied("observation_clock_invalid")
            # Freeze provider-owned objects before a second read detects replacement.
            records = json.loads(_canonical(read_records()))
            if not isinstance(records, dict) or set(records) != {"approval", "status"}:
                raise OperatorAuthorizationDenied("approval_and_status_required")
            envelope = records["approval"]
            if not isinstance(envelope, dict) or not isinstance(envelope.get("payload"), dict):
                raise OperatorAuthorizationDenied("signed_record_required")
            operator_id = envelope["payload"].get("operator_id")
            if not isinstance(operator_id, str) or operator_id not in keys:
                raise OperatorAuthorizationDenied("operator_identity_untrusted")
            approval = _verified_payload(envelope, keys[operator_id], _APPROVAL_FIELDS)
            expected = {
                "contract": "nija.general-live-approval.v1", "broker": "kraken",
                "account": binding.account, "account_iiban_sha256": binding.account_iiban_sha256,
                "api_key_sha256": binding.api_key_sha256, "mode": binding.mode,
                "scope": list(binding.scope), "release_id": binding.release_id,
            }
            if any(approval[key] != value for key, value in expected.items()):
                raise OperatorAuthorizationDenied("approval_binding_mismatch")
            if not _identifier(approval["approval_id"]):
                raise OperatorAuthorizationDenied("approval_identity_invalid")
            approved = approval["approved_at_epoch"]
            expires = approval["expires_at_epoch"]
            if (not _timestamp(approved) or not _timestamp(expires)
                    or not approved <= stamp < expires):
                raise OperatorAuthorizationDenied("approval_expired_or_future")
            status = _verified_payload(records["status"], revocation_public_key, _STATUS_FIELDS)
            approval_digest = hashlib.sha256(_canonical(approval)).hexdigest()
            if (status["contract"] != "nija.general-live-approval-status.v1"
                    or status["approval_id"] != approval["approval_id"]
                    or status["approval_sha256"] != approval_digest):
                raise OperatorAuthorizationDenied("revocation_record_binding_mismatch")
            if status["status"] != "active":
                raise OperatorAuthorizationDenied("approval_revoked_or_unknown")
            if (isinstance(status["generation"], bool) or not isinstance(status["generation"], int)
                    or status["generation"] <= 0):
                raise OperatorAuthorizationDenied("revocation_generation_invalid")
            observed = status["observed_at_epoch"]
            status_expires = status["expires_at_epoch"]
            if (not _timestamp(observed) or not _timestamp(status_expires)
                    or not 0 <= stamp - observed <= 60 or not observed <= stamp < status_expires):
                raise OperatorAuthorizationDenied("revocation_status_stale_or_expired")
            if _canonical(read_records()) != _canonical(records):
                raise OperatorAuthorizationDenied("authorization_changed_during_read")
            finished = clock()
            if (not _timestamp(finished) or not 0 <= finished - stamp <= 60
                    or finished >= min(expires, status_expires) or finished - observed > 60):
                raise OperatorAuthorizationDenied("authorization_expired_during_read")
            row.update(verified=True, scope_verified=True, approval_sha256=approval_digest,
                       approval_id=approval["approval_id"], status_generation=status["generation"],
                       expires_at_epoch=min(expires, status_expires))
            row["provenance"].update(
                account_scope_verified=True, snapshot_complete=True, operator_approval_verified=True,
                signature_algorithm="Ed25519", approval_contract="nija.general-live-approval.v1",
                revocation_contract="nija.general-live-approval-status.v1",
            )
        except OperatorAuthorizationDenied as exc:
            row["failure_reason"] = str(exc)
            logger.warning("KRAKEN_OPERATOR_EVIDENCE_DENIED reason=%s", exc)
        except Exception:
            row["failure_reason"] = "authorization_provider_unavailable_or_invalid"
            logger.warning("KRAKEN_OPERATOR_EVIDENCE_DENIED reason=authorization_provider_unavailable_or_invalid")
        return row

    return observe
