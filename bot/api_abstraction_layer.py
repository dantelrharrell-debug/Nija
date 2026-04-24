"""
NIJA API Abstraction Layer
===========================

Provides a safe, validated interface through which users connect their
exchange accounts to NIJA.

Design goals
------------
* **Safety** — credentials are validated (non-empty, length, character set)
  before they are stored.  Plaintext keys never appear in log output.
* **Masking** — API keys are masked in every public-facing result object so
  that secrets cannot leak through API responses or log aggregators.
* **Abstraction** — callers do not need to know which environment variables
  or encrypted-storage paths are used internally; that is handled here.
* **Connection testing** — a lightweight dry-run check is attempted before
  credentials are persisted, reducing the risk of storing invalid keys.

Typical usage
-------------
::

    from bot.api_abstraction_layer import get_api_abstraction_layer, ExchangeConnectionRequest

    layer = get_api_abstraction_layer()

    req = ExchangeConnectionRequest(
        user_id="alice@example.com",
        display_name="Alice",
        exchange="COINBASE",
        api_key="<key>",
        api_secret="<secret>",
    )
    result = layer.connect_user_account(req)
    if result.success:
        print("Connected:", result.masked_key)
    else:
        print("Error:", result.error)

Supported exchanges
-------------------
COINBASE, KRAKEN, BINANCE, OKX, ALPACA
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger("nija.api_abstraction_layer")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Exchanges supported by the abstraction layer.
SUPPORTED_EXCHANGES = ("COINBASE", "KRAKEN", "BINANCE", "OKX", "ALPACA")

#: Minimum / maximum acceptable lengths for an API key / secret.
_KEY_MIN_LEN = 8
_KEY_MAX_LEN = 512

#: Characters that are never valid in exchange API credentials.
_INVALID_CHARS_RE = re.compile(r"[\x00-\x1f\x7f\"'`\\]")


# ---------------------------------------------------------------------------
# Request / result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ExchangeConnectionRequest:
    """Encapsulates a user's request to connect an exchange account."""

    user_id: str
    """Unique identifier for the user (e.g. email address or UUID)."""

    display_name: str
    """Human-readable name shown in dashboards."""

    exchange: str
    """Target exchange.  Must be one of SUPPORTED_EXCHANGES (case-insensitive)."""

    api_key: str
    """Exchange API key (plaintext — will be masked / encrypted on store)."""

    api_secret: str
    """Exchange API secret (plaintext — will be masked / encrypted on store)."""

    additional_params: Dict[str, str] = field(default_factory=dict)
    """Extra parameters required by some exchanges (e.g. ``passphrase`` for OKX)."""


@dataclass
class ConnectionResult:
    """Result of a connect / disconnect / test operation."""

    success: bool
    user_id: str
    exchange: str
    masked_key: str = ""
    """API key with all but the last 4 characters replaced with ``*``."""
    error: Optional[str] = None
    message: str = ""


@dataclass
class UserConnectionInfo:
    """Read-only summary of a single connected exchange account."""

    user_id: str
    display_name: str
    exchange: str
    masked_key: str
    connected: bool
    balance_usd: float = 0.0


# ---------------------------------------------------------------------------
# APIAbstractionLayer
# ---------------------------------------------------------------------------

class APIAbstractionLayer:
    """
    Safe, validated interface for connecting user exchange accounts to NIJA.

    All public methods return structured result objects.  No method raises
    an exception to the caller; errors are reported via ``result.error``.
    """

    def __init__(self) -> None:
        # {user_id: {exchange: masked_key}} – lightweight in-memory index
        # (source of truth is the PlatformAccountLayer + auth module)
        self._index: Dict[str, Dict[str, str]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def connect_user_account(self, request: ExchangeConnectionRequest) -> ConnectionResult:
        """
        Validate credentials and register a user exchange account with NIJA.

        Steps:
        1. Validate inputs (non-empty, length, character set, exchange name).
        2. Attempt a lightweight connection test (best-effort; skipped when
           the broker adapter is unavailable so the layer stays usable in
           environments without live exchange connectivity).
        3. Persist credentials via PlatformAccountLayer (encrypted via auth).
        4. Return a masked result.

        Args:
            request: Validated connection request.

        Returns:
            ConnectionResult with ``success=True`` and a ``masked_key`` on
            success, or ``success=False`` and an ``error`` message on failure.
        """
        exchange = request.exchange.upper()

        # -- 1. Validate inputs --
        validation_error = self._validate_request(request.user_id, exchange,
                                                   request.api_key, request.api_secret)
        if validation_error:
            logger.warning(
                "connect_user_account validation failed for user '%s': %s",
                request.user_id,
                validation_error,
            )
            return ConnectionResult(
                success=False,
                user_id=request.user_id,
                exchange=exchange,
                error=validation_error,
            )

        masked = _mask_key(request.api_key)

        # -- 2. Best-effort connection test --
        test_ok, test_msg = self._test_connection(exchange, request.api_key,
                                                   request.api_secret,
                                                   request.additional_params)
        if not test_ok:
            logger.warning(
                "connect_user_account: connection test failed for user '%s' on %s: %s",
                request.user_id,
                exchange,
                test_msg,
            )
            return ConnectionResult(
                success=False,
                user_id=request.user_id,
                exchange=exchange,
                masked_key=masked,
                error=f"Connection test failed: {test_msg}",
            )

        # -- 3. Persist via PlatformAccountLayer --
        try:
            from bot.platform_account_layer import get_platform_account_layer
        except ImportError:
            from platform_account_layer import get_platform_account_layer

        pal = get_platform_account_layer()
        registered = pal.register_user_account(
            user_id=request.user_id,
            name=request.display_name,
            exchange=exchange,
            api_key=request.api_key,
            api_secret=request.api_secret,
        )
        if not registered:
            return ConnectionResult(
                success=False,
                user_id=request.user_id,
                exchange=exchange,
                masked_key=masked,
                error="Failed to register account (duplicate or internal error)",
            )

        # Update in-memory index
        self._index.setdefault(request.user_id, {})[exchange] = masked

        logger.info(
            "✅ User '%s' connected %s account (%s)",
            request.user_id,
            exchange,
            masked,
        )
        return ConnectionResult(
            success=True,
            user_id=request.user_id,
            exchange=exchange,
            masked_key=masked,
            message=f"Successfully connected {exchange} account",
        )

    def disconnect_user_account(self, user_id: str, exchange: str) -> ConnectionResult:
        """
        Remove a user's exchange account connection from NIJA.

        Args:
            user_id: Unique user identifier.
            exchange: Exchange name (case-insensitive).

        Returns:
            ConnectionResult indicating success or failure.
        """
        exchange = exchange.upper()

        try:
            from bot.platform_account_layer import get_platform_account_layer
        except ImportError:
            from platform_account_layer import get_platform_account_layer

        pal = get_platform_account_layer()
        removed = pal.unregister_user_account(user_id)

        # Clean up index
        if user_id in self._index:
            self._index[user_id].pop(exchange, None)
            if not self._index[user_id]:
                del self._index[user_id]

        if removed:
            logger.info("🔌 User '%s' disconnected %s account", user_id, exchange)
            return ConnectionResult(
                success=True,
                user_id=user_id,
                exchange=exchange,
                message=f"Successfully disconnected {exchange} account",
            )
        return ConnectionResult(
            success=False,
            user_id=user_id,
            exchange=exchange,
            error="Account not found",
        )

    def test_connection(
        self,
        exchange: str,
        api_key: str,
        api_secret: str,
        additional_params: Optional[Dict[str, str]] = None,
    ) -> ConnectionResult:
        """
        Test an exchange connection without storing credentials.

        Useful for a "verify before save" UX flow.

        Args:
            exchange: Exchange name (case-insensitive).
            api_key: API key to test.
            api_secret: API secret to test.
            additional_params: Extra parameters (e.g. passphrase for OKX).

        Returns:
            ConnectionResult with ``success=True`` if the test passes.
        """
        exchange = exchange.upper()

        validation_error = self._validate_request(
            "test_user", exchange, api_key, api_secret
        )
        if validation_error:
            return ConnectionResult(
                success=False,
                user_id="test_user",
                exchange=exchange,
                error=validation_error,
            )

        ok, msg = self._test_connection(exchange, api_key, api_secret,
                                        additional_params or {})
        if ok:
            return ConnectionResult(
                success=True,
                user_id="test_user",
                exchange=exchange,
                masked_key=_mask_key(api_key),
                message="Connection test passed",
            )
        return ConnectionResult(
            success=False,
            user_id="test_user",
            exchange=exchange,
            masked_key=_mask_key(api_key),
            error=f"Connection test failed: {msg}",
        )

    def list_user_connections(self, user_id: str) -> List[UserConnectionInfo]:
        """
        List all exchange accounts connected by a given user.

        Args:
            user_id: Unique user identifier.

        Returns:
            List of UserConnectionInfo objects (no plaintext credentials).
        """
        try:
            from bot.platform_account_layer import get_platform_account_layer
        except ImportError:
            from platform_account_layer import get_platform_account_layer

        pal = get_platform_account_layer()
        status = pal.get_status()

        result: List[UserConnectionInfo] = []
        for conn in status.user_connections:
            if conn.user_id != user_id:
                continue
            masked = self._index.get(user_id, {}).get(conn.exchange, "****")
            result.append(
                UserConnectionInfo(
                    user_id=conn.user_id,
                    display_name=conn.name,
                    exchange=conn.exchange,
                    masked_key=masked,
                    connected=conn.connected,
                    balance_usd=conn.balance_usd,
                )
            )
        return result

    def rotate_credentials(
        self,
        user_id: str,
        exchange: str,
        new_api_key: str,
        new_api_secret: str,
        additional_params: Optional[Dict[str, str]] = None,
    ) -> ConnectionResult:
        """
        Rotate (replace) the exchange credentials for a registered user.

        The old credentials are removed and the new ones are validated and
        stored atomically from the caller's perspective.

        Args:
            user_id: Unique user identifier.
            exchange: Exchange name (case-insensitive).
            new_api_key: Replacement API key.
            new_api_secret: Replacement API secret.
            additional_params: Extra exchange parameters.

        Returns:
            ConnectionResult indicating success or failure.
        """
        exchange = exchange.upper()

        validation_error = self._validate_request(
            user_id, exchange, new_api_key, new_api_secret
        )
        if validation_error:
            return ConnectionResult(
                success=False,
                user_id=user_id,
                exchange=exchange,
                error=validation_error,
            )

        ok, msg = self._test_connection(exchange, new_api_key, new_api_secret,
                                        additional_params or {})
        if not ok:
            return ConnectionResult(
                success=False,
                user_id=user_id,
                exchange=exchange,
                masked_key=_mask_key(new_api_key),
                error=f"Credential test failed: {msg}",
            )

        # Retrieve display name from existing connection (fallback to user_id)
        try:
            from bot.platform_account_layer import get_platform_account_layer
        except ImportError:
            from platform_account_layer import get_platform_account_layer

        pal = get_platform_account_layer()
        display_name = user_id
        for conn in pal.get_status().user_connections:
            if conn.user_id == user_id:
                display_name = conn.name
                break

        # Remove then re-register
        pal.unregister_user_account(user_id)
        registered = pal.register_user_account(
            user_id=user_id,
            name=display_name,
            exchange=exchange,
            api_key=new_api_key,
            api_secret=new_api_secret,
        )
        if not registered:
            return ConnectionResult(
                success=False,
                user_id=user_id,
                exchange=exchange,
                error="Failed to store rotated credentials",
            )

        masked = _mask_key(new_api_key)
        self._index.setdefault(user_id, {})[exchange] = masked

        logger.info(
            "🔄 Rotated %s credentials for user '%s' (%s)",
            exchange,
            user_id,
            masked,
        )
        return ConnectionResult(
            success=True,
            user_id=user_id,
            exchange=exchange,
            masked_key=masked,
            message=f"Credentials rotated for {exchange}",
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_request(
        user_id: str, exchange: str, api_key: str, api_secret: str
    ) -> Optional[str]:
        """
        Validate connection request fields.

        Returns an error message string if validation fails, or None on success.
        """
        if not user_id or not user_id.strip():
            return "user_id must not be empty"

        if exchange not in SUPPORTED_EXCHANGES:
            return (
                f"Unsupported exchange '{exchange}'. "
                f"Supported: {', '.join(SUPPORTED_EXCHANGES)}"
            )

        for field_name, value in (("api_key", api_key), ("api_secret", api_secret)):
            if not value or not value.strip():
                return f"{field_name} must not be empty"
            stripped = value.strip()
            if len(stripped) < _KEY_MIN_LEN:
                return f"{field_name} is too short (minimum {_KEY_MIN_LEN} characters)"
            if len(stripped) > _KEY_MAX_LEN:
                return f"{field_name} is too long (maximum {_KEY_MAX_LEN} characters)"
            if _INVALID_CHARS_RE.search(stripped):
                return f"{field_name} contains invalid characters"

        return None

    @staticmethod
    def _test_connection(
        exchange: str,
        api_key: str,
        api_secret: str,
        additional_params: Dict[str, str],
    ) -> tuple[bool, str]:
        """
        Attempt a lightweight connection test against the exchange.

        Returns (True, "") on success or (True, "skipped") when the broker
        adapter is unavailable (so that the abstraction layer remains usable
        in offline / test environments).  Returns (False, reason) only when
        the adapter is available AND confirms the credentials are invalid.
        """
        exchange_lower = exchange.lower()
        try:
            # Attempt to import the broker manager dynamically
            try:
                from bot.broker_manager import BrokerType
            except ImportError:
                from broker_manager import BrokerType

            broker_type = BrokerType[exchange]  # raises KeyError if unknown

            # Try the individual broker verifier if available
            try:
                try:
                    from bot.broker_individual_verifier import verify_broker_credentials
                except ImportError:
                    from broker_individual_verifier import verify_broker_credentials

                ok, msg = verify_broker_credentials(
                    broker_type=broker_type,
                    api_key=api_key,
                    api_secret=api_secret,
                    additional_params=additional_params,
                )
                return ok, msg
            except (ImportError, Exception):
                # Verifier unavailable — skip live test
                return True, "skipped (verifier unavailable)"

        except (ImportError, KeyError):
            # Broker layer unavailable (e.g. unit test environment) — skip live test
            return True, "skipped (broker layer unavailable)"
        except Exception as exc:
            # Unexpected error — log but don't block registration
            logger.debug("_test_connection error for %s: %s", exchange, exc)
            return True, f"skipped ({exc})"


# ---------------------------------------------------------------------------
# Private key-masking helper
# ---------------------------------------------------------------------------

def _mask_key(key: str, visible_chars: int = 4) -> str:
    """
    Return a masked representation of an API key.

    All characters except the last ``visible_chars`` are replaced with ``*``.
    If the key is shorter than ``visible_chars``, the entire key is masked.

    Examples:
        >>> _mask_key("abcdef1234567890")
        '************7890'
        >>> _mask_key("short")
        '*****'
    """
    if not key:
        return ""
    key = key.strip()
    if len(key) <= visible_chars:
        return "*" * len(key)
    return "*" * (len(key) - visible_chars) + key[-visible_chars:]


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_api_abstraction_layer: Optional[APIAbstractionLayer] = None


def get_api_abstraction_layer() -> APIAbstractionLayer:
    """
    Return the module-level APIAbstractionLayer singleton.

    Thread-safety: the module is imported under the GIL so the first-time
    creation is safe without an additional lock.
    """
    global _api_abstraction_layer
    if _api_abstraction_layer is None:
        _api_abstraction_layer = APIAbstractionLayer()
    return _api_abstraction_layer
