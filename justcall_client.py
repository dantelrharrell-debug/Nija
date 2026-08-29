"""JustCall API client for NIJA outreach workflows.

Credentials are loaded exclusively from environment variables so they are never
committed to the repository. The client deliberately fails closed for outbound
AI calls unless the caller explicitly attests that the contact has the consent
required by JustCall's outbound Voice Agent API.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

import requests

JUSTCALL_API_BASE = "https://api.justcall.io/v2.1"
_E164_RE = re.compile(r"^\+[1-9]\d{7,14}$")


class JustCallError(RuntimeError):
    """Base error for JustCall integration failures."""


class JustCallConfigurationError(JustCallError):
    """Raised when required JustCall configuration is missing or invalid."""


class JustCallAPIError(JustCallError):
    """Raised when JustCall rejects or cannot complete an API request."""

    def __init__(self, message: str, *, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class JustCallConfig:
    api_key: str
    api_secret: str
    ai_agent_id: str = ""
    expected_outbound_number: str = ""
    timeout_seconds: float = 15.0

    @classmethod
    def from_env(cls) -> "JustCallConfig":
        api_key = os.getenv("JUSTCALL_API_KEY", "").strip()
        api_secret = os.getenv("JUSTCALL_API_SECRET", "").strip()
        ai_agent_id = os.getenv("JUSTCALL_AI_AGENT_ID", "").strip()
        expected_number = os.getenv("JUSTCALL_OUTBOUND_NUMBER", "").strip()
        timeout_raw = os.getenv("JUSTCALL_API_TIMEOUT_SECONDS", "15").strip()

        try:
            timeout_seconds = max(1.0, min(float(timeout_raw), 60.0))
        except ValueError:
            timeout_seconds = 15.0

        return cls(
            api_key=api_key,
            api_secret=api_secret,
            ai_agent_id=ai_agent_id,
            expected_outbound_number=expected_number,
            timeout_seconds=timeout_seconds,
        )

    @property
    def credentials_configured(self) -> bool:
        return bool(self.api_key and self.api_secret)


def normalize_e164(value: str) -> str:
    """Return a validated E.164 phone number without guessing a country code."""
    number = (value or "").strip()
    if not _E164_RE.fullmatch(number):
        raise ValueError("Phone number must be in E.164 format, for example +15551234567")
    return number


class JustCallClient:
    """Small, fail-closed client for the JustCall v2.1 API."""

    def __init__(
        self,
        config: Optional[JustCallConfig] = None,
        session: Optional[requests.Session] = None,
    ) -> None:
        self.config = config or JustCallConfig.from_env()
        self.session = session or requests.Session()

    def _require_credentials(self) -> None:
        if not self.config.credentials_configured:
            raise JustCallConfigurationError(
                "JUSTCALL_API_KEY and JUSTCALL_API_SECRET must be configured as deployment secrets"
            )

    def _headers(self) -> Dict[str, str]:
        self._require_credentials()
        return {
            "Authorization": f"{self.config.api_key}:{self.config.api_secret}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "NIJA-Outreach/1.0",
        }

    def _request(self, method: str, path: str, **kwargs: Any) -> Dict[str, Any]:
        url = f"{JUSTCALL_API_BASE}{path}"
        try:
            response = self.session.request(
                method,
                url,
                headers=self._headers(),
                timeout=self.config.timeout_seconds,
                **kwargs,
            )
        except requests.RequestException as exc:
            raise JustCallAPIError("Unable to reach JustCall API") from exc

        if not 200 <= response.status_code < 300:
            # Provider errors can contain phone numbers/contact data, so do not
            # echo response bodies into NIJA logs or client-facing errors.
            raise JustCallAPIError(
                f"JustCall API request failed with HTTP {response.status_code}",
                status_code=response.status_code,
            )

        if response.status_code == 204 or not response.content:
            return {}
        try:
            payload = response.json()
        except ValueError as exc:
            raise JustCallAPIError(
                "JustCall returned an invalid JSON response",
                status_code=response.status_code,
            ) from exc
        if not isinstance(payload, dict):
            raise JustCallAPIError("JustCall returned an unexpected response format")
        return payload

    def list_voice_agents(self, *, page: int = 0, per_page: int = 50) -> Dict[str, Any]:
        page = max(0, int(page))
        per_page = max(1, min(int(per_page), 100))
        return self._request(
            "GET",
            "/voice-agents/list",
            params={"page": page, "per_page": per_page, "order": "desc"},
        )

    def initiate_ai_call(
        self,
        *,
        contact_number: str,
        has_consent: bool,
        dynamic_variables: Optional[Iterable[Dict[str, Any]]] = None,
        ai_agent_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Initiate a consented JustCall AI Voice Agent call.

        NIJA refuses to coerce/default ``has_consent`` to true. The calling
        workflow must have a stored consent record before reaching this method.
        """
        if has_consent is not True:
            raise ValueError(
                "Outbound AI call blocked: a verified consent record is required"
            )

        agent_id = (ai_agent_id or self.config.ai_agent_id).strip()
        if not agent_id:
            raise JustCallConfigurationError(
                "JUSTCALL_AI_AGENT_ID is not configured and no ai_agent_id was supplied"
            )

        normalized_contact = normalize_e164(contact_number)
        variables: List[Dict[str, Any]] = list(dynamic_variables or [])
        if len(variables) > 50:
            raise ValueError("Too many dynamic variables")

        return self._request(
            "POST",
            "/voice-agents/calls",
            json={
                "ai_agent_id": agent_id,
                "contact_number": normalized_contact,
                "dynamic_variables": variables,
                "has_consent": True,
            },
        )

    def connection_status(self) -> Dict[str, Any]:
        """Check whether NIJA is configured and can authenticate to JustCall."""
        status: Dict[str, Any] = {
            "configured": self.config.credentials_configured,
            "authenticated": False,
            "ai_agent_configured": bool(self.config.ai_agent_id),
            "outbound_number_configured": bool(self.config.expected_outbound_number),
        }
        if not self.config.credentials_configured:
            status["state"] = "credentials_missing"
            return status

        try:
            agents = self.list_voice_agents(page=0, per_page=1)
        except JustCallAPIError as exc:
            status["state"] = "authentication_or_api_failed"
            status["http_status"] = exc.status_code
            return status

        status["authenticated"] = True
        status["state"] = "connected"
        status["voice_agents_response_received"] = bool(agents)
        return status
