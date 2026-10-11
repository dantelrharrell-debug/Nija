"""Staged legal-owner metadata, independent of legacy execution identifiers.

This module never creates broker clients, moves positions, or authorizes trades.
The legacy ``platform`` execution identity remains intact during preparation.
"""

from __future__ import annotations

import os
from typing import Dict, Mapping


BUSINESS_EXCHANGES = ("COINBASE", "KRAKEN", "OKX", "ALPACA")


def personal_ownership_mode() -> bool:
    """Return whether the operator has declared legacy platform accounts personal."""
    return os.getenv("NIJA_ACCOUNT_OWNERSHIP_MODE", "legacy").strip().lower() == "dante_personal"


def account_identity(user_id: str) -> Dict[str, object]:
    """Describe ownership without translating a ledger or broker-routing key."""
    if user_id == "platform" and personal_ownership_mode():
        return {
            "owner_id": "dante",
            "display_name": "Dante",
            "account_role": "master_user",
            "ownership_type": "personal",
            "execution_user_id": "platform",
            "migration_pending": True,
        }
    return {
        "owner_id": user_id,
        "display_name": "NIJA" if user_id == "platform" else user_id,
        "account_role": "ai_platform" if user_id == "platform" else "user",
        "ownership_type": "unverified",
        "execution_user_id": user_id,
        "migration_pending": False,
    }


def business_account_profiles() -> list[Dict[str, object]]:
    """Return disabled future LLC slots with no execution or ledger identity yet."""
    return [
        {
            "profile_id": f"nija_llc_{exchange.lower()}",
            "owner_id": "nija_llc",
            "display_name": "NIJA",
            "legal_owner": "NIJA AI Trading LLC",
            "account_role": "ai_platform",
            "ownership_type": "business",
            "exchange": exchange,
            "credential_prefix": f"{exchange}_NIJA_BUSINESS",
            "enabled": False,
            "status": "awaiting_business_account_verification_and_migration",
            "execution_user_id": None,
        }
        for exchange in BUSINESS_EXCHANGES
    ]


def business_credentials(exchange: str, env: Mapping[str, str] | None = None) -> Dict[str, str]:
    """Read staged business keys only; never fall back to personal credentials.

    Reading keys does not verify ownership or enable a staged account. Broker
    identity verification and a separately reviewed migration remain required.
    """
    exchange = exchange.upper()
    if exchange not in BUSINESS_EXCHANGES:
        raise ValueError("Unsupported business exchange")
    source = os.environ if env is None else env
    prefix = f"{exchange}_NIJA_BUSINESS"
    key = source.get(f"{prefix}_API_KEY", "").strip()
    secret = source.get(f"{prefix}_API_SECRET", "").strip()
    passphrase = source.get(f"{prefix}_PASSPHRASE", "").strip() if exchange == "OKX" else ""
    if not key or not secret or (exchange == "OKX" and not passphrase):
        return {}
    # Catch exact API-key reuse. Different keys can still refer to the same
    # brokerage account; authenticated account-ID verification must catch that.
    personal_keys = [
        value.strip()
        for name, value in source.items()
        if name.endswith("_API_KEY")
        and name.startswith(f"{exchange}_")
        and name != f"{prefix}_API_KEY"
    ]
    if key in personal_keys:
        raise ValueError("Business API key duplicates an existing account connection")
    result = {"api_key": key, "api_secret": secret}
    if exchange == "OKX":
        result["passphrase"] = passphrase
    return result
