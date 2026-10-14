"""Isolated PocketBase credential vault adapter; never imports trading runtime.

Callers must validate the member JWT through PocketBase and supply a server-side
Founding 100 entitlement verifier. This module never authorizes trading.
"""
from __future__ import annotations

import base64
import binascii
import json
import os
import secrets
from dataclasses import dataclass
from typing import Callable, Mapping

import requests
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

COLLECTION = "nija_broker_vault"
BROKERS = frozenset({"kraken", "alpaca"})
ENVIRONMENTS = frozenset({"paper", "live"})
MAX_CIPHERTEXT = 8192


class VaultError(Exception):
    """Generic fail-closed vault error; never include credentials in messages."""


@dataclass(frozen=True)
class Member:
    id: str
    verified: bool


def _bytes64(encoded: str) -> bytes:
    try:
        return base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError, TypeError) as exc:
        raise VaultError("Invalid encryption key encoding") from exc


class BrokerVault:
    def __init__(
        self,
        base_url: str,
        key_b64: str,
        entitlement_check: Callable[[str], bool],
        *,
        session: requests.Session | None = None,
        timeout: float = 8.0,
    ) -> None:
        if not base_url.startswith("https://"):
            raise VaultError("Vault requires HTTPS")
        key = _bytes64(key_b64)
        if len(key) != 32:
            raise VaultError("Vault requires a 256-bit encryption key")
        if not callable(entitlement_check):
            raise VaultError("Trusted entitlement verifier required")
        self._base = base_url.rstrip("/")
        self._cipher = AESGCM(key)
        self._entitlement = entitlement_check
        self._session = session or requests.Session()
        self._timeout = timeout

    @classmethod
    def from_environment(
        cls, entitlement_check: Callable[[str], bool], *, session: requests.Session | None = None
    ) -> "BrokerVault":
        return cls(
            os.environ["NIJA_POCKETBASE_URL"],
            os.environ["NIJA_BROKER_VAULT_KEY_B64"],
            entitlement_check,
            session=session,
        )

    def _request(self, method: str, path: str, token: str, **kwargs):
        if not token or any(c.isspace() for c in token):
            raise VaultError("Missing or malformed member token")
        try:
            response = self._session.request(
                method, self._base + path,
                headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
                timeout=self._timeout, allow_redirects=False, **kwargs,
            )
        except requests.RequestException as exc:
            raise VaultError("Vault backend unavailable") from exc
        if response.status_code >= 300:
            raise VaultError("Vault request denied or failed")
        try:
            payload = response.json()
        except (ValueError, TypeError) as exc:
            raise VaultError("Vault backend returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise VaultError("Vault backend returned invalid payload")
        return payload

    def _member(self, token: str) -> Member:
        # PocketBase verifies the signature and validity server-side.
        response = self._request("POST", "/.sfs-be/api/collections/users/auth-refresh", token)
        record = response.get("record") or {}
        member = Member(str(record.get("id") or ""), record.get("verified") is True)
        if not member.id or not member.verified:
            raise VaultError("Verified member required")
        if not self._entitlement(member.id):
            raise VaultError("Active Founding 100 entitlement required")
        return member

    @staticmethod
    def _scope(broker: str, environment: str) -> None:
        if broker not in BROKERS or environment not in ENVIRONMENTS:
            raise VaultError("Unsupported broker or environment")

    @staticmethod
    def _aad(user_id: str, broker: str, environment: str) -> bytes:
        return f"{user_id}:{broker}:{environment}".encode("utf-8")

    def encrypt(self, user_id: str, broker: str, environment: str, credentials: Mapping[str, str]) -> str:
        self._scope(broker, environment)
        if not user_id or not isinstance(credentials, Mapping) or not credentials:
            raise VaultError("Invalid credential payload")
        if any(not isinstance(k, str) or not isinstance(v, str) or not v for k, v in credentials.items()):
            raise VaultError("Credential fields must be nonempty strings")
        plaintext = json.dumps(dict(credentials), separators=(",", ":"), sort_keys=True).encode()
        nonce = secrets.token_bytes(12)
        ciphertext = self._cipher.encrypt(nonce, plaintext, self._aad(user_id, broker, environment))
        envelope = json.dumps({
            "v": 1,
            "n": base64.b64encode(nonce).decode("ascii"),
            "c": base64.b64encode(ciphertext).decode("ascii"),
        }, separators=(",", ":"))
        if len(envelope) > MAX_CIPHERTEXT:
            raise VaultError("Encrypted credential exceeds storage limit")
        return envelope

    def decrypt(self, user_id: str, broker: str, environment: str, envelope: str) -> dict[str, str]:
        self._scope(broker, environment)
        try:
            data = json.loads(envelope)
            if set(data) != {"v", "n", "c"} or type(data["v"]) is not int or data["v"] != 1:
                raise ValueError("Unsupported envelope")
            nonce = _bytes64(data["n"])
            if len(nonce) != 12:
                raise ValueError("Incorrect nonce length")
            plaintext = self._cipher.decrypt(
                nonce, _bytes64(data["c"]), self._aad(user_id, broker, environment)
            )
            result = json.loads(plaintext)
            if not isinstance(result, dict) or any(
                not isinstance(k, str) or not isinstance(v, str) for k, v in result.items()
            ):
                raise ValueError("Invalid payload")
            return result
        except Exception as exc:
            raise VaultError("Credential authentication failed") from exc

    def create(self, member_token: str, broker: str, environment: str, credentials: Mapping[str, str]) -> str:
        """Create only; never silently overwrite an existing credential record."""
        self._scope(broker, environment)
        member = self._member(member_token)
        envelope = self.encrypt(member.id, broker, environment, credentials)
        response = self._request(
            "POST", f"/.sfs-be/api/collections/{COLLECTION}/records", member_token,
            json={"user_id": member.id, "broker": broker,
                  "environment": environment, "ciphertext": envelope},
        )
        record_id = response.get("id")
        if not isinstance(record_id, str) or not record_id:
            raise VaultError("Vault did not confirm record creation")
        return record_id

    def list_metadata(self, member_token: str) -> list[dict[str, str]]:
        """Only return identifiers/labels; never return ciphertext to clients."""
        member = self._member(member_token)
        result = self._request(
            "GET", f"/.sfs-be/api/collections/{COLLECTION}/records",
            member_token, params={"filter": f'user_id="{member.id}"', "perPage": 100},
        )
        rows = result.get("items")
        total_pages = result.get("totalPages")
        if (not isinstance(rows, list) or not isinstance(total_pages, int)
                or isinstance(total_pages, bool) or total_pages not in (0, 1)
                or (total_pages == 0 and bool(rows))):
            raise VaultError("Vault metadata response incomplete or invalid")
        metadata: list[dict[str, str]] = []
        for row in rows:
            if not isinstance(row, dict) or row.get("user_id") != member.id:
                raise VaultError("Vault ownership mismatch")
            if (not isinstance(row.get("id"), str) or not row["id"]
                    or row.get("broker") not in BROKERS
                    or row.get("environment") not in ENVIRONMENTS):
                raise VaultError("Vault metadata invalid")
            metadata.append({
                "id": row["id"], "broker": row["broker"], "environment": row["environment"]
            })
        return metadata
