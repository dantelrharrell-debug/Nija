"""
NIJA Platform Account Layer
============================

Implements the "Smart Structure" for running NIJA as a real SaaS platform:

    ┌────────────────────────────────────────────────────────────────┐
    │                 SMART STRUCTURE (Recommended)                  │
    │                                                                │
    │  Platform Account (NIJA)                                       │
    │    Owner  : NIJA AI Engine                                     │
    │    Purpose: AI trading engine / SaaS backbone                  │
    │    Exchanges: Coinbase, Kraken, OKX, Alpaca, Binance           │
    │                                                                │
    │  User Accounts                                                 │
    │    Owner  : Individual subscribers                             │
    │    Purpose: Personal investing (managed by NIJA AI)            │
    │    Connection: User Exchange ──► API ──► NIJA                  │
    └────────────────────────────────────────────────────────────────┘

How it works:
  - The PLATFORM account belongs to NIJA.  It is the AI engine that
    drives all trading logic.  Its credentials are stored as env vars
    prefixed with {EXCHANGE}_PLATFORM_*.
  - USER accounts are individual subscribers who connect their own
    exchange accounts to NIJA by supplying API keys.
  - Credentials are encrypted at rest using Fernet symmetric encryption
    via the ``auth`` module.  Plaintext keys are never persisted.
  - Runtime user registration is supported in addition to the legacy
    env-var discovery path, enabling database-backed onboarding.

Environment variables (legacy / single-exchange path):
  # NIJA Platform account — Kraken
  KRAKEN_PLATFORM_API_KEY=<nija-kraken-api-key>
  KRAKEN_PLATFORM_API_SECRET=<nija-kraken-api-secret>

  # Connected user accounts
  # Pattern: KRAKEN_USER_{FIRSTNAME}_API_KEY
  KRAKEN_USER_YOURNAME_API_KEY=<personal-kraken-api-key>
  KRAKEN_USER_YOURNAME_API_SECRET=<personal-kraken-api-secret>

Supported exchanges (EXCHANGE prefix):
  COINBASE, KRAKEN, BINANCE, OKX, ALPACA
"""

import logging
import os
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger("nija.platform_account_layer")

# ---------------------------------------------------------------------------
# Supported exchanges
# ---------------------------------------------------------------------------

SUPPORTED_EXCHANGES = ("COINBASE", "KRAKEN", "BINANCE", "OKX", "ALPACA")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class UserConnection:
    """Represents a user's exchange account connected to NIJA."""
    user_id: str
    name: str
    exchange: str            # e.g. "KRAKEN", "COINBASE"
    env_prefix: str          # e.g. "KRAKEN_USER_YOURNAME"
    connected: bool = False
    error: Optional[str] = None
    balance_usd: float = 0.0

    @property
    def label(self) -> str:
        return f"{self.name} ({self.user_id}) [{self.exchange}]"


@dataclass
class PlatformStatus:
    """Current status of the NIJA Platform Account Layer."""
    platform_configured: bool = False
    platform_connected: bool = False
    platform_account_label: str = "NIJA AI Trading Engine (Platform Account)"
    # Exchanges for which NIJA has platform credentials
    platform_exchanges: List[str] = field(default_factory=list)
    user_connections: List[UserConnection] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    @property
    def user_count(self) -> int:
        return len(self.user_connections)

    @property
    def connected_user_count(self) -> int:
        return sum(1 for u in self.user_connections if u.connected)

    @property
    def is_ready(self) -> bool:
        """Platform layer is ready when at least one NIJA platform account is configured."""
        return self.platform_configured


# ---------------------------------------------------------------------------
# PlatformAccountLayer
# ---------------------------------------------------------------------------

class PlatformAccountLayer:
    """
    Manages the NIJA SaaS platform account hierarchy.

    Smart Structure
    ───────────────
    Platform Account  →  NIJA (AI trading engine)      [PLATFORM]
    User Account 1    →  Personal investing             [USER]
    User Account N    →  Any subscriber                 [USER]

    Multiple exchanges are supported: Coinbase, Kraken, Binance, OKX, Alpaca.

    Users connect their exchange accounts to NIJA by supplying their API
    credentials, which are encrypted and stored via the ``auth`` module.
    The legacy env-var path (KRAKEN_USER_{NAME}_*) is still supported for
    backward compatibility.
    """

    # Legacy Kraken-only env var names (backward compatibility)
    LEGACY_KEY_ENV = "KRAKEN_API_KEY"
    LEGACY_SECRET_ENV = "KRAKEN_API_SECRET"

    def __init__(self) -> None:
        self._status = PlatformStatus()
        # {user_id: UserConnection} — runtime-registered users (encrypted store)
        self._runtime_users: Dict[str, UserConnection] = {}
        self._validate_platform_credentials()
        self._discover_user_connections()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_status(self) -> PlatformStatus:
        """Return the current platform layer status."""
        return self._status

    def display_hierarchy(self) -> None:
        """Log the Smart Structure hierarchy to the console."""
        s = self._status
        logger.info("=" * 64)
        logger.info("🏦  NIJA PLATFORM ACCOUNT LAYER — Smart Structure")
        logger.info("=" * 64)

        # NIJA platform accounts
        if s.platform_configured:
            exchanges = ", ".join(s.platform_exchanges) if s.platform_exchanges else "unknown"
            icon = "✅"
            note = f"CONNECTED ({exchanges})" if s.platform_connected else f"ready — will connect on startup ({exchanges})"
        else:
            icon = "❌"
            note = "NOT CONFIGURED — set {EXCHANGE}_PLATFORM_API_KEY / SECRET"

        logger.info(f"  {icon}  Platform Account  │  Owner: NIJA  │  Purpose: AI trading engine")
        logger.info(f"          Status: {note}")
        logger.info("")

        # Connected user accounts
        all_users = list(self._status.user_connections)
        if all_users:
            logger.info(f"  👥  Connected user accounts  ({s.connected_user_count}/{s.user_count})")
            for u in all_users:
                u_icon = "✅" if u.connected else "⚠️ "
                if u.connected:
                    u_note = "CONNECTED"
                elif u.error:
                    u_note = u.error
                else:
                    u_note = "ready — will connect on startup"
                logger.info(
                    f"      {u_icon}  {u.label:40s}  │  {u.env_prefix}_API_KEY  │  {u_note}"
                )
        else:
            logger.info("  ℹ️   No user accounts configured yet.")
            logger.info("       To connect a user account, call register_user_account() or add:")
            logger.info("         {EXCHANGE}_USER_YOURNAME_API_KEY=<key>")
            logger.info("         {EXCHANGE}_USER_YOURNAME_API_SECRET=<secret>")
            logger.info("       Then add the user to config/users/retail_{exchange}.json")

        logger.info("")
        logger.info("  User connection pattern:  User Exchange ──► API ──► NIJA")
        logger.info("=" * 64)

    def validate(self) -> bool:
        """
        Validate that the platform layer is properly configured.

        Returns True if at least one NIJA platform account credential
        is present.  Logs actionable guidance when they are missing.
        """
        if self._status.platform_configured:
            exchanges = ", ".join(self._status.platform_exchanges)
            logger.info(
                f"✅ Platform Account Layer: NIJA platform account configured ({exchanges})"
            )
            return True

        logger.warning("⚠️  Platform Account Layer: NIJA platform account NOT configured")
        logger.warning("   To run NIJA as a SaaS platform, set platform credentials for at")
        logger.warning("   least one exchange:")
        logger.warning("")
        for ex in SUPPORTED_EXCHANGES:
            logger.warning(f"   {ex}_PLATFORM_API_KEY=<key>")
            logger.warning(f"   {ex}_PLATFORM_API_SECRET=<secret>")
        logger.warning("")
        logger.warning("   See SMART_STRUCTURE_GUIDE.md for step-by-step setup.")
        return False

    def get_platform_credentials(self, exchange: str = "KRAKEN") -> Dict[str, str]:
        """
        Return the NIJA platform account credentials for a given exchange.

        Args:
            exchange: Exchange name (COINBASE, KRAKEN, BINANCE, OKX, ALPACA).
                      Defaults to KRAKEN for backward compatibility.

        Returns:
            dict with 'api_key' and 'api_secret', or empty strings if not
            configured.  Credentials are read from environment variables and
            are never stored in memory beyond this call.
        """
        exchange = exchange.upper()
        key_env = f"{exchange}_PLATFORM_API_KEY"
        secret_env = f"{exchange}_PLATFORM_API_SECRET"

        api_key = os.getenv(key_env, "").strip()
        api_secret = os.getenv(secret_env, "").strip()

        # Legacy Kraken fallback
        if exchange == "KRAKEN" and not (api_key and api_secret):
            api_key = api_key or os.getenv(self.LEGACY_KEY_ENV, "").strip()
            api_secret = api_secret or os.getenv(self.LEGACY_SECRET_ENV, "").strip()

        return {"api_key": api_key, "api_secret": api_secret}

    def has_platform_account(self, exchange: str = "KRAKEN") -> bool:
        """
        Return True when NIJA has platform credentials configured for *exchange*.

        This is the canonical check used before connecting user accounts so that
        standalone-fallback trading can be blocked when no platform account exists.

        Args:
            exchange: Exchange name (case-insensitive, e.g. "KRAKEN", "COINBASE").

        Returns:
            True if platform credentials for the exchange are present, False otherwise.
        """
        return exchange.upper() in self._status.platform_exchanges

    def list_user_env_prefixes(self) -> List[str]:
        """
        Return the list of {EXCHANGE}_USER_* env prefixes that have credentials set.

        Useful for dynamically discovering which users have connected their
        exchange accounts to NIJA.
        """
        return [u.env_prefix for u in self._status.user_connections]

    def register_user_account(
        self,
        user_id: str,
        name: str,
        exchange: str,
        api_key: str,
        api_secret: str,
    ) -> bool:
        """
        Register a user account at runtime (database-backed onboarding path).

        Credentials are stored encrypted via the ``auth`` module.  The env-var
        representation is set for the current process so that broker managers
        that read env vars will pick up the new user immediately.

        Args:
            user_id: Unique user identifier (e.g. email or UUID).
            name: Display name for the user.
            exchange: Exchange name (COINBASE, KRAKEN, BINANCE, OKX, ALPACA).
            api_key: Exchange API key.
            api_secret: Exchange API secret.

        Returns:
            True on success, False if the user is already registered or
            credentials are empty.
        """
        exchange = exchange.upper()
        if exchange not in SUPPORTED_EXCHANGES:
            logger.warning(f"register_user_account: unsupported exchange '{exchange}'")
            return False

        if not api_key or not api_secret:
            logger.warning(f"register_user_account: empty credentials for user '{user_id}'")
            return False

        # Store encrypted via auth module (best-effort; falls back to env-only)
        try:
            from auth import get_api_key_manager
            mgr = get_api_key_manager()
            mgr.store_user_api_key(user_id, exchange.lower(), api_key, api_secret)
            logger.debug(f"Encrypted credentials stored for user '{user_id}' on {exchange}")
        except ImportError:
            # auth module not on path in some deployment configurations — env-only is fine
            logger.debug("auth module not importable, using env-only credential path")
        except Exception as exc:
            logger.debug(f"auth module unavailable, using env-only path: {exc}")

        # Expose via env vars for broker managers that read os.environ.
        # Sanitize user_id so the env-var name is always valid: keep only
        # alphanumeric characters, replacing everything else with underscore.
        import re as _re
        token = _re.sub(r"[^A-Z0-9]", "_", user_id.upper())
        prefix = f"{exchange}_USER_{token}"
        os.environ[f"{prefix}_API_KEY"] = api_key
        os.environ[f"{prefix}_API_SECRET"] = api_secret

        conn = UserConnection(
            user_id=user_id,
            name=name,
            exchange=exchange,
            env_prefix=prefix,
        )
        self._runtime_users[user_id] = conn

        # Merge into status list (replace if same user_id already present)
        existing = [u for u in self._status.user_connections if u.user_id != user_id]
        self._status.user_connections = existing + [conn]

        logger.info(f"Registered user account: {conn.label}")
        return True

    def unregister_user_account(self, user_id: str) -> bool:
        """
        Remove a user account from the platform layer.

        Removes the runtime entry and clears the env vars set during
        registration.  Does not delete persisted encrypted keys from the
        auth module's durable store (call ``auth.get_api_key_manager()``
        directly for that).

        Args:
            user_id: Unique user identifier.

        Returns:
            True if the user was found and removed, False otherwise.
        """
        conn = self._runtime_users.pop(user_id, None)
        if conn is None:
            # Try env-var discovered users
            conn_list = [u for u in self._status.user_connections if u.user_id == user_id]
            if not conn_list:
                return False
            conn = conn_list[0]

        # Clear env vars
        os.environ.pop(f"{conn.env_prefix}_API_KEY", None)
        os.environ.pop(f"{conn.env_prefix}_API_SECRET", None)

        self._status.user_connections = [
            u for u in self._status.user_connections if u.user_id != user_id
        ]
        logger.info(f"Unregistered user account: {conn.label}")
        return True

    def mark_platform_connected(self, connected: bool = True) -> None:
        """Called by the broker manager once NIJA's platform account connects."""
        self._status.platform_connected = connected

    def mark_user_connected(
        self,
        user_id: str,
        connected: bool = True,
        error: Optional[str] = None,
        balance_usd: float = 0.0,
    ) -> None:
        """Called by the broker manager once a user's account connects."""
        for u in self._status.user_connections:
            if u.user_id == user_id:
                u.connected = connected
                u.error = error
                u.balance_usd = balance_usd
                return

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _validate_platform_credentials(self) -> None:
        """Check which exchanges NIJA has platform credentials for."""
        configured_exchanges: List[str] = []

        for exchange in SUPPORTED_EXCHANGES:
            key = os.getenv(f"{exchange}_PLATFORM_API_KEY", "").strip()
            secret = os.getenv(f"{exchange}_PLATFORM_API_SECRET", "").strip()
            if key and secret:
                configured_exchanges.append(exchange)

        # Legacy Kraken fallback
        if "KRAKEN" not in configured_exchanges:
            legacy_key = os.getenv(self.LEGACY_KEY_ENV, "").strip()
            legacy_secret = os.getenv(self.LEGACY_SECRET_ENV, "").strip()
            if legacy_key and legacy_secret:
                configured_exchanges.append("KRAKEN")
                logger.debug("Platform credentials found via legacy KRAKEN_API_KEY env vars")

        self._status.platform_exchanges = configured_exchanges
        self._status.platform_configured = bool(configured_exchanges)

        if configured_exchanges:
            logger.debug(f"Platform credentials found for: {', '.join(configured_exchanges)}")
        else:
            logger.debug("No platform credentials set")

    def _discover_user_connections(self) -> None:
        """
        Scan environment variables for {EXCHANGE}_USER_*_API_KEY entries
        across all supported exchanges.

        Each matching key represents a user who has connected their personal
        exchange account to NIJA via the pattern:
            User Exchange → API → NIJA
        """
        env = os.environ
        seen: Dict[str, UserConnection] = {}

        for exchange in SUPPORTED_EXCHANGES:
            prefix_search = f"{exchange}_USER_"
            for var_name in env:
                if not var_name.startswith(prefix_search):
                    continue
                if not var_name.endswith("_API_KEY"):
                    continue

                # Extract token between {EXCHANGE}_USER_ and _API_KEY
                inner = var_name[len(prefix_search):-len("_API_KEY")]
                if not inner:
                    continue

                prefix = f"{exchange}_USER_{inner}"
                api_key = env.get(f"{prefix}_API_KEY", "").strip()
                api_secret = env.get(f"{prefix}_API_SECRET", "").strip()
                if not api_key or not api_secret:
                    continue

                user_id = f"{exchange.lower()}_{inner.lower()}"
                if user_id not in seen:
                    seen[user_id] = UserConnection(
                        user_id=user_id,
                        name=inner.capitalize(),
                        exchange=exchange,
                        env_prefix=prefix,
                    )

        self._status.user_connections = list(seen.values())
        if seen:
            logger.debug(
                f"Discovered {len(seen)} user connection(s): "
                + ", ".join(seen.keys())
            )


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_platform_account_layer: Optional[PlatformAccountLayer] = None
_platform_layer_lock = threading.Lock()


def get_platform_account_layer() -> PlatformAccountLayer:
    """
    Return the module-level PlatformAccountLayer singleton.

    Thread-safe: uses a module-level lock to guard first-time creation.
    Call this once during startup, then use display_hierarchy() and validate()
    to log the Smart Structure and confirm configuration.
    """
    global _platform_account_layer
    if _platform_account_layer is None:
        with _platform_layer_lock:
            if _platform_account_layer is None:
                _platform_account_layer = PlatformAccountLayer()
    return _platform_account_layer


def get_platform_layer() -> PlatformAccountLayer:
    """
    Convenience alias for :func:`get_platform_account_layer`.

    Preferred name for new call sites introduced after the singleton
    enforcement refactor (March 2026).  Both functions return the same
    module-level singleton instance.

    Example::

        from bot.platform_account_layer import get_platform_layer

        pal = get_platform_layer()
        if not pal.has_platform_account("KRAKEN"):
            raise RuntimeError("Platform account not configured")
    """
    return get_platform_account_layer()
