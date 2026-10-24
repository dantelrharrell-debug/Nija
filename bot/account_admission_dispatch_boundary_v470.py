"""Explicit pre-dispatch admission boundary; no implicit production installation.

The caller must provide a separately audited, account-scoped admission store
and immutable candidate. This module never builds evidence from request metadata.
Do not install until all entry transports use the same durable reservation store.
"""
from __future__ import annotations

from .account_order_admission import AccountOrderAdmission, AdmissionDenied
from .order_admission_policy import Candidate


def consume_verified_entry(
    admission: AccountOrderAdmission | None, candidate: Candidate | None
) -> None:
    """Durably consume one entry authorization before any broker transport call.

    A transport timeout or ambiguous broker ACK must not release this token.
    No success result is interpreted as execution authority: canonical runtime
    dispatch, kill switch, nonce ownership and broker guards still apply.
    """
    if type(admission) is not AccountOrderAdmission:
        raise AdmissionDenied("account_admission_not_installed")
    if type(candidate) is not Candidate:
        raise AdmissionDenied("candidate_identity_not_verified")
    reservation = admission.reserve(candidate)
    admission.consume(reservation)
