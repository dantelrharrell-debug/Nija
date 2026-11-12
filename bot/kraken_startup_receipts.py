"""Authenticate externally issued startup receipts; never issue approvals.

The trusted composition root supplies independently approved public keys and
exact runtime/account pins. No key discovery, environment loader, signing,
broker construction, network call or order authority is provided here.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from bot.kraken_operator_authorization import _canonical, _digest, _identifier, _verified_payload
from bot.kraken_startup_evidence_binding import (
    RECEIPTS, ReviewedStartupBinding, register_reviewed_startup_binding,
)
from bot.pretrade_attestation_validation_v452 import REQUIRED

CONTRACT = "nija.kraken-startup-certification.v1"
FIELDS = frozenset({
    "contract", "kind", "evidence_id", "artifact_sha256", "status",
    "service_id", "release_id", "image_sha256", "account",
    "account_iiban_sha256", "api_key_sha256", "provider_registry_sha256",
    "approved_at_epoch", "expires_at_epoch",
})


@dataclass(frozen=True)
class StartupReceiptTrust:
    """Externally approved deployment, account, registry and signer pins.

    Construct only after independent review of actual runtime metadata and the
    factory/source objects. This data structure is not proof of that review.
    Public keys are raw Ed25519 public bytes; private keys are never accepted.
    """

    service_id: str
    release_id: str
    image_sha256: str
    account_iiban_sha256: str
    api_key_sha256: str
    reviewed_provider_ids: Mapping[str, str]
    public_keys: Mapping[str, bytes]
    maximum_receipt_age_s: float

    def __post_init__(self) -> None:
        if (not isinstance(self.reviewed_provider_ids, Mapping)
                or not isinstance(self.public_keys, Mapping)):
            raise ValueError("reviewed_startup_trust_pins_required")
        ids = dict(self.reviewed_provider_ids)
        keys = dict(self.public_keys)
        if (self.service_id != "srv-d98dsr5aeets73fpbaqg"
                or not isinstance(self.release_id, str) or len(self.release_id) != 40
                or any(c not in "0123456789abcdef" for c in self.release_id)
                or any(not _digest(value) for value in (
                    self.image_sha256, self.account_iiban_sha256, self.api_key_sha256,
                ))
                or set(ids) != set(REQUIRED)
                or any(not _identifier(value) for value in ids.values())
                or len(set(ids.values())) != len(REQUIRED)
                or set(keys) != RECEIPTS
                or any(type(value) is not bytes or len(value) != 32 for value in keys.values())
                or not _positive_number(self.maximum_receipt_age_s)):
            raise ValueError("reviewed_startup_trust_pins_required")
        object.__setattr__(self, "reviewed_provider_ids", MappingProxyType(ids))
        object.__setattr__(self, "public_keys", MappingProxyType(keys))


def _positive_number(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def _runtime_matches(trust: StartupReceiptTrust) -> bool:
    return (os.environ.get("RENDER_SERVICE_ID") == trust.service_id
            and os.environ.get("RENDER_GIT_COMMIT") == trust.release_id)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_receipt_field")
        result[key] = value
    return result


def _receipt(raw: Any) -> dict[str, Any]:
    # Immutable serialized envelopes prevent a mutable receipt being swapped
    # while signatures are checked. Duplicate keys and excessive data deny.
    if (type(raw) is not str or not 0 < len(raw) <= 16384
            or len(raw.encode("utf-8")) > 16384):
        raise ValueError("bounded_serialized_receipt_required")
    envelope = json.loads(raw, object_pairs_hook=_unique_object)
    if type(envelope) is not dict:
        raise ValueError("signed_receipt_required")
    return envelope


def make_startup_receipt_verifier(
    trust: StartupReceiptTrust, *, clock: Callable[[], float] = time.time,
) -> Callable[[ReviewedStartupBinding], bool]:
    """Return the literal-True verifier expected by the existing startup hook.

    Signatures authenticate external attestations, not the underlying event by
    themselves. Signer custody, artifacts, runtime pins and source separation
    still require independent review. No receipt can authorize an order.
    """
    if type(trust) is not StartupReceiptTrust or not callable(clock):
        raise ValueError("reviewed_startup_trust_required")
    expected = {
        "contract": CONTRACT, "status": "certified", "service_id": trust.service_id,
        "release_id": trust.release_id, "image_sha256": trust.image_sha256,
        "account": "platform:kraken", "account_iiban_sha256": trust.account_iiban_sha256,
        "api_key_sha256": trust.api_key_sha256,
        "provider_registry_sha256": hashlib.sha256(_canonical(dict(trust.reviewed_provider_ids))).hexdigest(),
    }

    def verify(binding: ReviewedStartupBinding) -> bool:
        try:
            if (type(binding) is not ReviewedStartupBinding
                    or not _runtime_matches(trust)
                    or dict(binding.reviewed_provider_ids) != dict(trust.reviewed_provider_ids)
                    or set(binding.providers) != set(REQUIRED)
                    or any(not callable(value) for value in binding.providers.values())
                    or len({id(value) for value in binding.providers.values()}) != len(REQUIRED)
                    or set(binding.receipts) != RECEIPTS):
                return False
            now = clock()
            if not _positive_number(now):
                return False
            evidence_ids = set()
            expiries = []
            issued = []
            for kind in sorted(RECEIPTS):
                payload = _verified_payload(_receipt(binding.receipts[kind]), trust.public_keys[kind], FIELDS)
                if (any(payload.get(key) != value for key, value in expected.items())
                        or payload["kind"] != kind or not _identifier(payload["evidence_id"])
                        or not _digest(payload["artifact_sha256"])
                        or payload["evidence_id"] in evidence_ids
                        or not _positive_number(payload["approved_at_epoch"])
                        or not _positive_number(payload["expires_at_epoch"])
                        or not payload["approved_at_epoch"] <= now < payload["expires_at_epoch"]
                        or now - payload["approved_at_epoch"] > trust.maximum_receipt_age_s):
                    return False
                evidence_ids.add(payload["evidence_id"])
                expiries.append(payload["expires_at_epoch"])
                issued.append(payload["approved_at_epoch"])
            # Expiry must still hold after all three signature checks. Clock
            # rollback, nonfinite clocks and validation-time expiry deny.
            finished = clock()
            return bool(_runtime_matches(trust) and _positive_number(finished) and now <= finished < min(expiries)
                        and finished - min(issued) <= trust.maximum_receipt_age_s)
        except Exception:
            # Receipt errors may contain private material. Export no exception.
            return False

    return verify


def register_signed_kraken_startup(
    factory: Callable, trust: StartupReceiptTrust, *, clock: Callable[[], float] = time.time,
) -> None:
    """Register an externally reviewed factory with authenticated receipts.

    Call explicitly in the real production interpreter before canonical main,
    after validating the supplied trust against that runtime. This creates no
    sources, receipts, approvals or providers, and never submits an order.
    """
    if not callable(factory):
        raise TypeError("reviewed_startup_factory_required")
    verifier = make_startup_receipt_verifier(trust, clock=clock)
    register_reviewed_startup_binding(factory, verify_receipts=verifier)
