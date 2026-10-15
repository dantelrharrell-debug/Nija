"""Safe application boundary for member broker onboarding.

Framework-neutral. Never imports trading execution or exposes credential contents.
An authenticated PocketBase session and authoritative subscription verifier are
required by BrokerVault. This adapter does not grant trading authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from member_broker_vault import BrokerVault, VaultError

_ALLOWED_FIELDS = {
    "kraken": frozenset({"api_key", "api_secret"}),
    "alpaca": frozenset({"api_key", "api_secret"}),
    "coinbase": frozenset({"api_key", "api_secret"}),  # CDP key name + PEM private key
    "okx": frozenset({"api_key", "api_secret", "passphrase"}),
}


@dataclass(frozen=True)
class ConnectionStatus:
    broker: str
    environment: str
    credentials_stored: bool
    broker_verified: bool = False
    live_trading_authorized: bool = False

    @property
    def connected(self) -> bool:
        """True only with independent authenticated broker verification.

        Storing API credentials cannot prove a healthy broker connection.
        """
        return self.broker_verified


class MemberBrokerOnboarding:
    def __init__(self, vault: BrokerVault, *, secret_intake_enabled: bool = False):
        self._vault = vault
        # Set only by trusted deployment configuration after independent review
        # of PocketBase ACL, subscription checks, and key custody.
        self._secret_intake_enabled = secret_intake_enabled is True

    def connections(self, member_token: str) -> list[ConnectionStatus]:
        # Vault checks server-authenticated identity and subscription on each call.
        rows = self._vault.list_metadata(member_token)
        seen = set()
        statuses = []
        for row in rows:
            scope = (row["broker"], row["environment"])
            if scope in seen:
                raise VaultError("Duplicate broker connection detected")
            seen.add(scope)
            statuses.append(ConnectionStatus(*scope, credentials_stored=True))
        return statuses

    def connect(
        self, member_token: str, broker: str, environment: str,
        credentials: Mapping[str, str],
    ) -> ConnectionStatus:
        if not self._secret_intake_enabled:
            raise VaultError("Secure credential intake is not enabled")
        if broker not in _ALLOWED_FIELDS or environment not in ("paper", "live"):
            raise VaultError("Unsupported broker or environment")
        if not isinstance(credentials, Mapping) or set(credentials) != _ALLOWED_FIELDS[broker]:
            raise VaultError("Invalid broker credential fields")
        if any(not isinstance(value, str) or not value.strip() or
               len(value) > 4096 for value in credentials.values()):
            raise VaultError("Invalid broker credential values")
        # Detect existing owned scopes before write. A server-side unique index is
        # still mandatory to prevent concurrent duplicate creation.
        if any(item.broker == broker and item.environment == environment
               for item in self.connections(member_token)):
            raise VaultError("Broker credential record already exists")
        # Never echo, return or log API keys; create() rechecks auth and entitlement.
        self._vault.create(member_token, broker, environment, credentials)
        return ConnectionStatus(broker, environment, credentials_stored=True)
