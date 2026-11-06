"""Read-only inventory of required production commissioning bindings.

This module deliberately does not install collectors, mutate the pipeline,
read secrets, create a broker, or authorize orders. The trusted composition
root must supply real independently reviewed objects before installation.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from bot.pretrade_attestation_validation_v452 import REQUIRED

REQUIRED_BINDINGS = (
    "canonical_nonce_owning_broker",
    "approved_api_key_sha256",
    "approved_iban_sha256",
    "reviewed_provider_ids",
    "providers",
    "account_scope",
    "maximum_cash_debit_usd",
    "independent_open_intents",
    "independent_positions",
    "independent_remaining",
    "monitoring_category",
    "ledger",
    "collector",
    "fence",
    "execution_reader",
    "candidate_for_request",
    "first_order_plan",
    "release_id",
    "account_fingerprint",
    "credential_fingerprint",
    "general_approval_binding",
    "operator_public_key_path",
    "status_public_key_path",
    "general_status_public_key_path",
    "approval_records_path",
    "general_approval_records_path",
    "signed_first_order_approval",
    "backup_restore_receipt",
    "broker_ledger_exits_receipt",
)


def inspect_commissioning_bindings(bindings: Mapping[str, Any] | None) -> dict[str, Any]:
    """Report only missing binding names; never echo values or assert readiness.

    A supplied binding is not proof of authenticity, freshness or review.
    """
    supplied = bindings if isinstance(bindings, Mapping) else {}
    missing = tuple(name for name in REQUIRED_BINDINGS if supplied.get(name) is None)
    provider_ids = supplied.get("reviewed_provider_ids")
    missing_providers = tuple(
        field for field in REQUIRED
        if not isinstance(provider_ids, Mapping) or not provider_ids.get(field)
    )
    return {
        "complete_binding_inventory": not missing and not missing_providers,
        "missing_bindings": missing,
        "missing_provider_id_fields": missing_providers,
        "authenticated_evidence_verified": False,
        "collector_installed": False,
        "authorizes_orders": False,
        "activation_allowed": False,
    }
