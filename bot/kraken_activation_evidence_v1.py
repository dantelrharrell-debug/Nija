"""Offline, read-only verification boundary. No network, secrets or trading authority."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Mapping
from .kraken_activation_status_v1 import REQUIRED_OBSERVATIONS

@dataclass(frozen=True)
class Evidence:
    provider: str
    account_scope: str
    release_sha: str
    image_digest: str
    deployment_epoch: str
    observed_at: datetime
    expires_at: datetime
    payload: bytes
    signature: bytes
    signer_role: str

@dataclass(frozen=True)
class TrustContext:
    account_scope: str
    release_sha: str
    image_digest: str
    deployment_epoch: str
    required_roles: Mapping[str, str]
    max_age_seconds: int = 300

def verify_evidence(records: Mapping[str, Evidence], trust: TrustContext,
                    now: datetime, verify_signature: Callable[[Evidence], bool]
                    ) -> tuple[frozenset[str], tuple[str, ...]]:
    """Only a caller-provided, independently pinned verifier can authenticate signatures.

    This function cannot establish production trust by itself. Fail closed if
    verifier is missing, scope differs, or evidence is stale/replayed.
    """
    if verify_signature is None or now.tzinfo is None:
        raise ValueError("trusted_verifier_and_aware_clock_required")
    valid = set()
    errors = []
    for provider in REQUIRED_OBSERVATIONS:
        item = records.get(provider)
        if item is None:
            errors.append("missing:" + provider)
            continue
        try:
            fresh = (item.observed_at.tzinfo is not None
                     and item.expires_at.tzinfo is not None
                     and item.observed_at <= now < item.expires_at
                     and 0 <= (now - item.observed_at).total_seconds() <= trust.max_age_seconds)
            scoped = (item.provider == provider
                      and item.account_scope == trust.account_scope
                      and item.release_sha == trust.release_sha
                      and item.image_digest == trust.image_digest
                      and item.deployment_epoch == trust.deployment_epoch
                      and item.signer_role == trust.required_roles.get(provider)
                      and bool(item.payload) and bool(item.signature))
            authenticated = bool(verify_signature(item)) if fresh and scoped else False
        except Exception:
            authenticated = False
        if authenticated:
            valid.add(provider)
        else:
            errors.append("invalid_or_stale:" + provider)
    for name in records:
        if name not in REQUIRED_OBSERVATIONS:
            errors.append("unknown:" + name)
    return frozenset(valid), tuple(errors)
