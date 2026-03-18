"""
NIJA Secrets Manager

Unified secrets provider that supports multiple backends for production-grade
secrets management:

  - ``env``   (default) – reads from environment variables / .env file
  - ``aws``              – AWS Secrets Manager (boto3)
  - ``vault``            – HashiCorp Vault (hvac) via AppRole or token auth

Backend selection
-----------------
Set ``SECRETS_BACKEND`` environment variable to one of ``env``, ``aws``, or
``vault``.  When the variable is absent the ``env`` backend is used so that
local development continues to work without any changes.

AWS configuration (SECRETS_BACKEND=aws)
-----------------------------------------
Required env vars:
  AWS_REGION                – e.g. "us-east-1"
  AWS_SECRET_NAME_PREFIX    – optional prefix for secret names (default: "nija/")

Authentication is handled by boto3's standard credential chain (IAM role,
~/.aws/credentials, environment variables AWS_ACCESS_KEY_ID /
AWS_SECRET_ACCESS_KEY, etc.).

HashiCorp Vault configuration (SECRETS_BACKEND=vault)
------------------------------------------------------
Required env vars:
  VAULT_ADDR                – e.g. "https://vault.example.com:8200"

One of:
  VAULT_TOKEN               – root/service token (dev / CI only)
  VAULT_ROLE_ID +
  VAULT_SECRET_ID           – AppRole (recommended for production)

Optional:
  VAULT_SECRET_PATH_PREFIX  – KV v2 mount/path prefix (default: "secret/nija/")
  VAULT_NAMESPACE           – Vault namespace (Vault Enterprise only)
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger("nija.secrets_manager")

# ---------------------------------------------------------------------------
# Backend constant
# ---------------------------------------------------------------------------
BACKEND_ENV = "env"
BACKEND_AWS = "aws"
BACKEND_VAULT = "vault"

# ---------------------------------------------------------------------------
# Lazy-loaded backend clients (only imported when actually needed)
# ---------------------------------------------------------------------------
_boto3_client: Optional[Any] = None
_hvac_client: Optional[Any] = None


def _get_aws_client():
    """Return a cached boto3 secretsmanager client."""
    global _boto3_client
    if _boto3_client is None:
        try:
            import boto3  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "boto3 is required for the 'aws' secrets backend. "
                "Install it with: pip install boto3"
            ) from exc
        region = os.environ.get("AWS_REGION", "us-east-1")
        _boto3_client = boto3.client("secretsmanager", region_name=region)
        logger.info("AWS Secrets Manager client initialised (region=%s)", region)
    return _boto3_client


def _get_vault_client():
    """Return a cached hvac Vault client, authenticating if necessary."""
    global _hvac_client
    if _hvac_client is None:
        try:
            import hvac  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "hvac is required for the 'vault' secrets backend. "
                "Install it with: pip install hvac"
            ) from exc

        vault_addr = os.environ.get("VAULT_ADDR", "http://localhost:8200")
        namespace = os.environ.get("VAULT_NAMESPACE")

        client = hvac.Client(url=vault_addr, namespace=namespace)

        token = os.environ.get("VAULT_TOKEN")
        role_id = os.environ.get("VAULT_ROLE_ID")
        secret_id = os.environ.get("VAULT_SECRET_ID")

        if token:
            client.token = token
            logger.info("Vault client initialised with static token (addr=%s)", vault_addr)
        elif role_id and secret_id:
            result = client.auth.approle.login(role_id=role_id, secret_id=secret_id)
            client.token = result["auth"]["client_token"]
            logger.info("Vault client authenticated via AppRole (addr=%s)", vault_addr)
        else:
            raise RuntimeError(
                "Vault backend requires either VAULT_TOKEN or "
                "VAULT_ROLE_ID + VAULT_SECRET_ID to be set."
            )

        if not client.is_authenticated():
            raise RuntimeError("Vault authentication failed – check credentials.")

        _hvac_client = client

    return _hvac_client


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def get_secret(name: str, default: Optional[str] = None) -> Optional[str]:
    """
    Retrieve a secret value by *name*.

    The look-up strategy depends on ``SECRETS_BACKEND``:

    * ``env``   – ``os.environ[name]``
    * ``aws``   – AWS Secrets Manager secret identified by
                  ``{AWS_SECRET_NAME_PREFIX}{name}``
    * ``vault`` – Vault KV v2 secret at
                  ``{VAULT_SECRET_PATH_PREFIX}{name}``; the *value* field
                  inside the secret JSON is used when the JSON contains a
                  single ``value`` key, otherwise the raw string is returned.

    Returns *default* when the secret is not found or on non-fatal errors.
    """
    backend = os.environ.get("SECRETS_BACKEND", BACKEND_ENV).lower()

    if backend == BACKEND_ENV:
        return os.environ.get(name, default)

    if backend == BACKEND_AWS:
        return _get_aws_secret(name, default)

    if backend == BACKEND_VAULT:
        return _get_vault_secret(name, default)

    logger.warning("Unknown SECRETS_BACKEND=%r; falling back to env", backend)
    return os.environ.get(name, default)


def get_secret_dict(name: str) -> Dict[str, str]:
    """
    Retrieve a secrets bundle as a dictionary.

    For the ``aws`` backend the secret must be a JSON object stored in AWS
    Secrets Manager.  For the ``vault`` backend the secret's ``data`` dict is
    returned.  For the ``env`` backend a single key/value pair
    ``{name: os.environ[name]}`` is returned.
    """
    backend = os.environ.get("SECRETS_BACKEND", BACKEND_ENV).lower()

    if backend == BACKEND_ENV:
        value = os.environ.get(name, "")
        return {name: value} if value else {}

    if backend == BACKEND_AWS:
        return _get_aws_secret_dict(name)

    if backend == BACKEND_VAULT:
        return _get_vault_secret_dict(name)

    logger.warning("Unknown SECRETS_BACKEND=%r; falling back to env", backend)
    return {name: os.environ.get(name, "")}


# ---------------------------------------------------------------------------
# AWS Secrets Manager helpers
# ---------------------------------------------------------------------------

def _aws_secret_id(name: str) -> str:
    prefix = os.environ.get("AWS_SECRET_NAME_PREFIX", "nija/")
    return f"{prefix}{name}"


def _get_aws_secret(name: str, default: Optional[str]) -> Optional[str]:
    try:
        client = _get_aws_client()
        response = client.get_secret_value(SecretId=_aws_secret_id(name))
        raw = response.get("SecretString") or ""
        # If it's a JSON object with a "value" key, extract it
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict) and "value" in parsed:
                return str(parsed["value"])
            # Multi-key JSON: return as-is for callers that want a string blob
            return raw
        except (json.JSONDecodeError, TypeError):
            return raw or default
    except Exception as exc:
        logger.warning("AWS Secrets Manager lookup failed for %r: %s", name, exc)
        return default


def _get_aws_secret_dict(name: str) -> Dict[str, str]:
    try:
        client = _get_aws_client()
        response = client.get_secret_value(SecretId=_aws_secret_id(name))
        raw = response.get("SecretString") or "{}"
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return {k: str(v) for k, v in parsed.items()}
        return {}
    except Exception as exc:
        logger.warning("AWS Secrets Manager dict lookup failed for %r: %s", name, exc)
        return {}


# ---------------------------------------------------------------------------
# HashiCorp Vault helpers
# ---------------------------------------------------------------------------

def _vault_path(name: str) -> str:
    prefix = os.environ.get("VAULT_SECRET_PATH_PREFIX", "secret/nija/")
    return f"{prefix}{name}"


def _get_vault_secret(name: str, default: Optional[str]) -> Optional[str]:
    try:
        client = _get_vault_client()
        path = _vault_path(name)
        # KV v2: mount path is the first segment; the rest is the secret path
        parts = path.split("/", 2)
        mount_point = parts[0]
        secret_path = "/".join(parts[1:]) if len(parts) > 1 else name
        response = client.secrets.kv.v2.read_secret_version(
            path=secret_path,
            mount_point=mount_point,
        )
        data = response["data"]["data"]
        if isinstance(data, dict) and "value" in data:
            return str(data["value"])
        # Serialise the whole dict as a JSON string for single-string callers
        return json.dumps(data)
    except Exception as exc:
        logger.warning("Vault secret lookup failed for %r: %s", name, exc)
        return default


def _get_vault_secret_dict(name: str) -> Dict[str, str]:
    try:
        client = _get_vault_client()
        path = _vault_path(name)
        parts = path.split("/", 2)
        mount_point = parts[0]
        secret_path = "/".join(parts[1:]) if len(parts) > 1 else name
        response = client.secrets.kv.v2.read_secret_version(
            path=secret_path,
            mount_point=mount_point,
        )
        data = response["data"]["data"]
        if isinstance(data, dict):
            return {k: str(v) for k, v in data.items()}
        return {}
    except Exception as exc:
        logger.warning("Vault secret dict lookup failed for %r: %s", name, exc)
        return {}


# ---------------------------------------------------------------------------
# Convenience accessor for well-known NIJA application secrets
# ---------------------------------------------------------------------------

def get_jwt_secret() -> str:
    """
    Return the JWT signing secret.

    Fetches ``JWT_SECRET_KEY`` via the configured secrets backend.
    Raises ``RuntimeError`` if the secret is not set in production
    (i.e. when ``SECRETS_BACKEND != 'env'``), because auto-generating
    a secret at runtime would invalidate all issued tokens on restart.
    """
    secret = get_secret("JWT_SECRET_KEY")
    backend = os.environ.get("SECRETS_BACKEND", BACKEND_ENV).lower()
    if not secret:
        if backend != BACKEND_ENV:
            raise RuntimeError(
                "JWT_SECRET_KEY must be set in your secrets backend "
                "(SECRETS_BACKEND=%r). " % backend
                + "Generate one with: openssl rand -hex 32"
            )
        import secrets as _secrets
        secret = _secrets.token_hex(32)
        logger.warning(
            "JWT_SECRET_KEY not set – generated ephemeral key. "
            "Set JWT_SECRET_KEY in .env for persistence across restarts."
        )
    return secret


def get_vault_encryption_key() -> Optional[str]:
    """Return the VAULT_ENCRYPTION_KEY via the configured backend."""
    return get_secret("VAULT_ENCRYPTION_KEY")
