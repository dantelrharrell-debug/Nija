"""Safe application boundary for member broker onboarding.

Framework-neutral. Never imports trading execution or exposes credential contents.
An authenticated PocketBase session and authoritative subscription verifier are
required by BrokerVault. This adapter does not grant trading authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from bot.member_broker_vault import BrokerVault, VaultError

_ALLOWED_FIELDS = {
    "kraken": frozenset({"api_key", "api_secret"}),
    "alpaca": frozenset({"api_key", "api_secret"}),
}


@dataclass(frozen=True)
class ConnectionStatus:
    broker: str
    environment: str
    connected: bool


class MemberBrokerOnboarding:
    def __init__(self, vault: BrokerVault):
        self._vault = vault

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
            statuses.append(ConnectionStatus(*scope, connected=True))
        return statuses

    def connect(
        self, member_token: str, broker: str, environment: str,
        credentials: Mapping[str, str],
    ) -> ConnectionStatus:
        if broker not in _ALLOWED_FIELDS or environment not in ("paper", "live"):
            raise VaultError("Unsupported broker or environment")
        if not isinstance(credentials, Mapping) or set(credentials) != _ALLOWED_FIELDS[broker]:
            raise VaultError("Invalid broker credential fields")
        if any(not isinstance(value, str) or not value.strip() or
               len(value) > 4096 for value in credentials.values()):
            raise VaultError("Invalid broker credential values")
        # Never echo, return or log API keys; create() must enforce member ownership.
        self._vault.create(member_token, broker, environment, credentials)
        return ConnectionStatus(broker, environment, connected=True)
