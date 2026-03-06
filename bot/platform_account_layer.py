"""
NIJA Platform Account Layer
============================

Implements the "Smart Structure" for running NIJA as a real SaaS platform:

    ┌────────────────────────────────────────────────┐
    │           SMART STRUCTURE (Recommended)         │
    │                                                 │
    │  Kraken Account 1                               │
    │    Owner  : You                                 │
    │    Purpose: Personal investing                  │
    │                                                 │
    │  Kraken Account 2                               │
    │    Owner  : NIJA                                │
    │    Purpose: AI trading engine                   │
    │                                                 │
    │  User connections:                              │
    │    User Kraken ──► API ──► NIJA                 │
    └────────────────────────────────────────────────┘

How it works:
  - Account 2 (NIJA's own Kraken) is the PLATFORM account.
    It is the AI engine that drives all trading logic.
  - Account 1 (owner's personal Kraken) is a USER account.
    It connects to NIJA via API keys just like any other user.
  - Additional users connect their own Kraken accounts to NIJA
    using the same User Kraken → API → NIJA pattern.

Environment variables:
  # NIJA Platform account (Account 2 – NIJA AI engine)
  KRAKEN_PLATFORM_API_KEY=<nija-kraken-api-key>
  KRAKEN_PLATFORM_API_SECRET=<nija-kraken-api-secret>

  # Connected user accounts (Account 1 = personal, or any user)
  # Pattern: KRAKEN_USER_{FIRSTNAME}_API_KEY
  KRAKEN_USER_YOURNAME_API_KEY=<personal-kraken-api-key>
  KRAKEN_USER_YOURNAME_API_SECRET=<personal-kraken-api-secret>
"""

import logging
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger("nija.platform_account_layer")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class UserConnection:
    """Represents a user's Kraken account connected to NIJA."""
    user_id: str
    name: str
    env_prefix: str          # e.g. "KRAKEN_USER_YOURNAME"
    connected: bool = False
    error: Optional[str] = None
    balance_usd: float = 0.0

    @property
    def label(self) -> str:
        return f"{self.name} ({self.user_id})"


@dataclass
class PlatformStatus:
    """Current status of the NIJA Platform Account Layer."""
    platform_configured: bool = False
    platform_connected: bool = False
    platform_account_label: str = "NIJA AI Trading Engine (Kraken Account 2)"
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
        """Platform layer is ready when at least the NIJA platform account is configured."""
        return self.platform_configured


# ---------------------------------------------------------------------------
# PlatformAccountLayer
# ---------------------------------------------------------------------------

class PlatformAccountLayer:
    """
    Manages the NIJA SaaS platform account hierarchy.

    Smart Structure
    ───────────────
    Kraken Account 2  →  NIJA (AI trading engine)      [PLATFORM]
    Kraken Account 1  →  You  (personal investing)     [USER]
    Kraken Account N  →  Any user                      [USER]

    Users connect their Kraken accounts to NIJA by providing
    their Kraken API key/secret, which NIJA stores as
    KRAKEN_USER_{FIRSTNAME}_API_KEY / _SECRET env vars.
    """

    # Env var names for NIJA's own Kraken account (Account 2)
    PLATFORM_KEY_ENV = "KRAKEN_PLATFORM_API_KEY"
    PLATFORM_SECRET_ENV = "KRAKEN_PLATFORM_API_SECRET"

    # Legacy fallback (backward compatibility)
    LEGACY_KEY_ENV = "KRAKEN_API_KEY"
    LEGACY_SECRET_ENV = "KRAKEN_API_SECRET"

    def __init__(self) -> None:
        self._status = PlatformStatus()
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

        # NIJA platform account (Account 2)
        if s.platform_configured:
            icon = "✅"
            note = "CONNECTED" if s.platform_connected else "ready — will connect on startup"
        else:
            icon = "❌"
            note = "NOT CONFIGURED — set KRAKEN_PLATFORM_API_KEY / SECRET"

        logger.info(f"  {icon}  Kraken Account 2  │  Owner: NIJA  │  Purpose: AI trading engine")
        logger.info(f"          Status: {note}")
        logger.info("")

        # Connected user accounts
        if s.user_connections:
            logger.info(f"  👥  Connected user accounts  ({s.connected_user_count}/{s.user_count})")
            for u in s.user_connections:
                u_icon = "✅" if u.connected else "⚠️ "
                if u.connected:
                    u_note = "CONNECTED"
                elif u.error:
                    u_note = u.error
                else:
                    u_note = "ready — will connect on startup"
                logger.info(f"      {u_icon}  {u.label:30s}  │  {u.env_prefix}_API_KEY  │  {u_note}")
        else:
            logger.info("  ℹ️   No user accounts configured yet.")
            logger.info("       To connect Account 1 (your personal Kraken), add:")
            logger.info("         KRAKEN_USER_YOURNAME_API_KEY=<key>")
            logger.info("         KRAKEN_USER_YOURNAME_API_SECRET=<secret>")
            logger.info("       Then add your user to  config/users/retail_kraken.json")

        logger.info("")
        logger.info("  User connection pattern:  User Kraken ──► API ──► NIJA")
        logger.info("=" * 64)

    def validate(self) -> bool:
        """
        Validate that the platform layer is properly configured.

        Returns True if the NIJA platform account (Account 2) credentials
        are present.  Logs actionable guidance when they are missing.
        """
        if self._status.platform_configured:
            logger.info("✅ Platform Account Layer: NIJA platform account configured")
            return True

        logger.warning("⚠️  Platform Account Layer: NIJA platform account NOT configured")
        logger.warning("   To run NIJA as a SaaS platform you need TWO Kraken accounts:")
        logger.warning("")
        logger.warning("   Kraken Account 1 (yours — personal investing)")
        logger.warning("     → Connect as a user:  KRAKEN_USER_YOURNAME_API_KEY")
        logger.warning("")
        logger.warning("   Kraken Account 2 (NIJA — AI trading engine)   ← required here")
        logger.warning("     → Set as platform:    KRAKEN_PLATFORM_API_KEY")
        logger.warning("                            KRAKEN_PLATFORM_API_SECRET")
        logger.warning("")
        logger.warning("   See SMART_STRUCTURE_GUIDE.md for step-by-step setup.")
        return False

    def get_platform_credentials(self) -> Dict[str, str]:
        """
        Return the NIJA platform account credentials.

        Returns a dict with 'api_key' and 'api_secret', or empty strings
        if not configured.  Credentials are read from environment variables
        and are never stored in memory beyond this call.
        """
        api_key = (
            os.getenv(self.PLATFORM_KEY_ENV, "").strip()
            or os.getenv(self.LEGACY_KEY_ENV, "").strip()
        )
        api_secret = (
            os.getenv(self.PLATFORM_SECRET_ENV, "").strip()
            or os.getenv(self.LEGACY_SECRET_ENV, "").strip()
        )
        return {"api_key": api_key, "api_secret": api_secret}

    def list_user_env_prefixes(self) -> List[str]:
        """
        Return the list of KRAKEN_USER_* env prefixes that have credentials set.

        Useful for dynamically discovering which users have connected their
        Kraken accounts to NIJA.
        """
        return [u.env_prefix for u in self._status.user_connections]

    def mark_platform_connected(self, connected: bool = True) -> None:
        """Called by the broker manager once NIJA's Kraken account connects."""
        self._status.platform_connected = connected

    def mark_user_connected(self, user_id: str, connected: bool = True,
                            error: Optional[str] = None,
                            balance_usd: float = 0.0) -> None:
        """Called by the broker manager once a user's Kraken account connects."""
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
        """Check whether NIJA's own Kraken credentials (Account 2) are set."""
        key = (
            os.getenv(self.PLATFORM_KEY_ENV, "").strip()
            or os.getenv(self.LEGACY_KEY_ENV, "").strip()
        )
        secret = (
            os.getenv(self.PLATFORM_SECRET_ENV, "").strip()
            or os.getenv(self.LEGACY_SECRET_ENV, "").strip()
        )
        self._status.platform_configured = bool(key and secret)

        if self._status.platform_configured:
            source = (
                self.PLATFORM_KEY_ENV
                if os.getenv(self.PLATFORM_KEY_ENV, "").strip()
                else f"{self.LEGACY_KEY_ENV} (legacy)"
            )
            logger.debug(f"Platform credentials found via {source}")
        else:
            logger.debug("Platform credentials not set")

    def _discover_user_connections(self) -> None:
        """
        Scan environment variables for KRAKEN_USER_*_API_KEY entries.

        Each matching key represents a user who has connected their personal
        Kraken account to NIJA via the pattern:
            User Kraken → API → NIJA
        """
        env = os.environ
        seen: Dict[str, UserConnection] = {}

        for var_name in env:
            if not var_name.startswith("KRAKEN_USER_"):
                continue
            if not var_name.endswith("_API_KEY"):
                continue

            # Extract FIRSTNAME from KRAKEN_USER_{FIRSTNAME}_API_KEY
            # e.g. "KRAKEN_USER_YOURNAME_API_KEY" → inner = "YOURNAME"
            inner = var_name[len("KRAKEN_USER_"):-len("_API_KEY")]
            if not inner:
                continue

            prefix = f"KRAKEN_USER_{inner}"  # e.g. "KRAKEN_USER_YOURNAME"
            api_key = env.get(f"{prefix}_API_KEY", "").strip()
            api_secret = env.get(f"{prefix}_API_SECRET", "").strip()

            if not api_key or not api_secret:
                continue

            # Build a user_id from the firstname token (lowercase)
            # e.g. "YOURNAME" → user_id = "yourname"
            user_id = inner.lower()
            if user_id not in seen:
                seen[user_id] = UserConnection(
                    user_id=user_id,
                    name=inner.capitalize(),
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


def get_platform_account_layer() -> PlatformAccountLayer:
    """
    Return the module-level PlatformAccountLayer singleton.

    Call this once during startup, then use display_hierarchy() and validate()
    to log the Smart Structure and confirm configuration.
    """
    global _platform_account_layer
    if _platform_account_layer is None:
        _platform_account_layer = PlatformAccountLayer()
    return _platform_account_layer
