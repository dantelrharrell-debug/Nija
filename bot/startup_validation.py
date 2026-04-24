"""
NIJA Startup Validation - Critical Pre-Flight Checks
Addresses subtle risks: branch/commit unknown, disabled exchanges, testing vs. live mode

This module provides validation for:
1. Git metadata (branch/commit must be known)
2. Exchange configuration (clear warnings for disabled exchanges)
3. Trading mode intentionality (testing vs. live must be explicit)
4. Account hierarchy (platform credentials must be configured before user credentials)
"""

import os
import re
import logging
from typing import Dict, List, Optional, Tuple
from enum import Enum

logger = logging.getLogger("nija")


class StartupRisk(Enum):
    """Categories of startup risks"""
    GIT_METADATA_UNKNOWN = "git_metadata_unknown"
    DISABLED_EXCHANGE_WARNING = "disabled_exchange_warning"
    MODE_AMBIGUOUS = "mode_ambiguous"
    NO_EXCHANGES_ENABLED = "no_exchanges_enabled"
    NO_VIABLE_BROKER = "no_viable_broker"
    PLATFORM_NOT_CONFIGURED_FIRST = "platform_not_configured_first"
    NTP_CLOCK_DRIFT = "ntp_clock_drift"
    DATA_DIR_UNAVAILABLE = "data_dir_unavailable"


class StartupValidationResult:
    """Result of startup validation checks"""
    
    def __init__(self):
        self.risks: List[Tuple[StartupRisk, str]] = []
        self.warnings: List[str] = []
        self.info: List[str] = []
        self.critical_failure: bool = False
        self.failure_reason: str = ""
    
    def add_risk(self, risk_type: StartupRisk, message: str):
        """Add a risk item"""
        self.risks.append((risk_type, message))
        
    def add_warning(self, message: str):
        """Add a warning"""
        self.warnings.append(message)
        
    def add_info(self, message: str):
        """Add informational message"""
        self.info.append(message)
        
    def mark_critical_failure(self, reason: str):
        """Mark as critical failure (bot should not start)"""
        self.critical_failure = True
        self.failure_reason = reason
        
    def has_risks(self) -> bool:
        """Check if any risks were detected"""
        return len(self.risks) > 0
    
    def get_summary(self) -> Dict:
        """Get summary of validation results"""
        return {
            'risks': [{'type': r[0].value, 'message': r[1]} for r in self.risks],
            'warnings': self.warnings,
            'info': self.info,
            'critical_failure': self.critical_failure,
            'failure_reason': self.failure_reason,
        }


def _is_git_metadata_unknown(value: str) -> bool:
    """
    Helper function to check if git metadata value is unknown.
    
    Args:
        value: Git metadata value (branch or commit)
        
    Returns:
        True if value is unknown or missing, False otherwise
    """
    return not value or value == "unknown"


def validate_git_metadata(git_branch: str, git_commit: str) -> StartupValidationResult:
    """
    Validate that git branch and commit are known.
    
    Risk: Running with unknown branch/commit makes it impossible to verify
    which code version is executing, especially dangerous in production.
    
    Args:
        git_branch: Git branch name from environment or git command
        git_commit: Git commit hash from environment or git command
        
    Returns:
        StartupValidationResult with validation findings
    """
    result = StartupValidationResult()
    
    # Check if branch is unknown
    if _is_git_metadata_unknown(git_branch):
        result.add_risk(
            StartupRisk.GIT_METADATA_UNKNOWN,
            "Git branch is UNKNOWN - cannot verify code version"
        )
        result.add_warning(
            "RISK: Running code with unknown branch. "
            "Set GIT_BRANCH environment variable or ensure .git directory exists."
        )
    else:
        result.add_info(f"Git branch verified: {git_branch}")
    
    # Check if commit is unknown
    if _is_git_metadata_unknown(git_commit):
        result.add_risk(
            StartupRisk.GIT_METADATA_UNKNOWN,
            "Git commit is UNKNOWN - cannot verify code version"
        )
        result.add_warning(
            "RISK: Running code with unknown commit hash. "
            "Set GIT_COMMIT environment variable or ensure .git directory exists."
        )
    else:
        result.add_info(f"Git commit verified: {git_commit}")
    
    # If both are unknown, this is a critical configuration issue
    if _is_git_metadata_unknown(git_branch) and _is_git_metadata_unknown(git_commit):
        result.add_warning(
            "CRITICAL: Both branch and commit are unknown. "
            "This bot instance cannot be traced to any specific code version."
        )
    
    return result


# ---------------------------------------------------------------------------
# Credential format / placeholder helpers
# ---------------------------------------------------------------------------

# Placeholder patterns that indicate a credential was never filled in.
# Patterns are anchored (^...$) and only match the *entire* value, so a real
# credential that merely *starts with* a common word (e.g. "testnet-key-abc")
# will NOT be flagged.  The word-boundary approach handles variants like
# "test", "testkey", "test_key", "test123" while leaving longer real keys alone.
# Bracketed groups use negated char classes (e.g. [^>]+) to prevent backtracking.
# "none" / "null" only match when the entire credential is that exact word.
_PLACEHOLDER_PATTERNS = re.compile(
    r"^(your[_\-]?.*|replace[_\-]?.*|change[_\-]?me?|insert[_\-]?.*|fill[_\-]?.*|"
    r"xxx+|placeholder.*|example.*|sample.*|testkey|test[_\-]api|test[_\-]secret|"
    r"dummy.*|fake.*|todo.*|none|null|n/?a|"
    r"<[^>]+>|\[[^\]]+\]|\{[^}]+\}|api[_\-]?key|api[_\-]?secret|key[_\-]?here|"
    r"secret[_\-]?here|\*+)$",
    re.IGNORECASE,
)

# Minimum sensible lengths for each credential type
_MIN_LENGTHS: Dict[str, int] = {
    "kraken_key": 10,
    "kraken_secret": 32,
    "coinbase_key": 10,
    "coinbase_secret": 20,
    "alpaca_key": 10,
    "alpaca_secret": 20,
    "binance_key": 16,
    "binance_secret": 16,
    "okx_key": 8,
    "okx_secret": 8,
    "okx_passphrase": 4,
}


def _is_placeholder(value: str) -> bool:
    """Return True if the value looks like an unfilled placeholder."""
    stripped = value.strip()
    return bool(_PLACEHOLDER_PATTERNS.match(stripped))


def _credential_looks_valid(value: Optional[str], min_len: int = 8) -> bool:
    """
    Return True if *value* is set, non-empty, not a placeholder, and meets
    the minimum length requirement.
    """
    if not value or not value.strip():
        return False
    v = value.strip()
    if len(v) < min_len:
        return False
    if _is_placeholder(v):
        return False
    return True


def _kraken_credentials_viable() -> Tuple[bool, str]:
    """
    Check whether Kraken credentials look viable.

    Accepts the new KRAKEN_PLATFORM_API_KEY / KRAKEN_PLATFORM_API_SECRET pair
    **or** the legacy KRAKEN_API_KEY / KRAKEN_API_SECRET pair (broker_manager.py
    uses both with the legacy keys as a fallback).

    Returns (viable: bool, which_pair: str)
    """
    # Use explicit strip() checks so an empty KRAKEN_PLATFORM_API_KEY=""
    # does not silently fall through to the legacy key via the `or` short-circuit.
    platform_key = os.getenv("KRAKEN_PLATFORM_API_KEY", "").strip()
    platform_secret = os.getenv("KRAKEN_PLATFORM_API_SECRET", "").strip()
    legacy_key = os.getenv("KRAKEN_API_KEY", "").strip()
    legacy_secret = os.getenv("KRAKEN_API_SECRET", "").strip()

    # Prefer platform credentials; fall back to legacy only when platform is absent.
    key = platform_key if platform_key else legacy_key
    secret = platform_secret if platform_secret else legacy_secret

    if (_credential_looks_valid(key, _MIN_LENGTHS["kraken_key"]) and
            _credential_looks_valid(secret, _MIN_LENGTHS["kraken_secret"])):
        if platform_key:
            return True, "KRAKEN_PLATFORM_API_KEY / KRAKEN_PLATFORM_API_SECRET"
        return True, "KRAKEN_API_KEY / KRAKEN_API_SECRET (legacy)"
    return False, ""


def _coinbase_credentials_viable() -> Tuple[bool, str]:
    """
    Check whether Coinbase credentials look viable.

    Accepts both the new Cloud API key format
    (``organizations/{org_id}/apiKeys/{key_id}``) and the shorter legacy key
    format.  The secret must contain PEM markers **or** be a sufficiently long
    non-placeholder string (some integrations store only the raw EC key body).
    """
    key = os.getenv("COINBASE_API_KEY", "").strip()
    secret = os.getenv("COINBASE_API_SECRET", "").strip()

    if not _credential_looks_valid(key, _MIN_LENGTHS["coinbase_key"]):
        return False, ""
    if not _credential_looks_valid(secret, _MIN_LENGTHS["coinbase_secret"]):
        return False, ""
    # If the secret looks like a PEM key (recommended) that's a strong signal
    if "-----BEGIN" in secret or "-----END" in secret:
        return True, "COINBASE_API_KEY / COINBASE_API_SECRET (PEM format)"
    return True, "COINBASE_API_KEY / COINBASE_API_SECRET"


def _alpaca_credentials_viable() -> Tuple[bool, str]:
    """Check whether Alpaca credentials look viable."""
    key = os.getenv("ALPACA_API_KEY", "").strip()
    secret = os.getenv("ALPACA_API_SECRET", "").strip()
    if (_credential_looks_valid(key, _MIN_LENGTHS["alpaca_key"]) and
            _credential_looks_valid(secret, _MIN_LENGTHS["alpaca_secret"])):
        return True, "ALPACA_API_KEY / ALPACA_API_SECRET"
    return False, ""


def _binance_credentials_viable() -> Tuple[bool, str]:
    """Check whether Binance credentials look viable."""
    key = os.getenv("BINANCE_API_KEY", "").strip()
    secret = os.getenv("BINANCE_API_SECRET", "").strip()
    if (_credential_looks_valid(key, _MIN_LENGTHS["binance_key"]) and
            _credential_looks_valid(secret, _MIN_LENGTHS["binance_secret"])):
        return True, "BINANCE_API_KEY / BINANCE_API_SECRET"
    return False, ""


def _okx_credentials_viable() -> Tuple[bool, str]:
    """Check whether OKX credentials look viable."""
    key = os.getenv("OKX_API_KEY", "").strip()
    secret = os.getenv("OKX_API_SECRET", "").strip()
    passphrase = os.getenv("OKX_PASSPHRASE", "").strip()
    if (_credential_looks_valid(key, _MIN_LENGTHS["okx_key"]) and
            _credential_looks_valid(secret, _MIN_LENGTHS["okx_secret"]) and
            _credential_looks_valid(passphrase, _MIN_LENGTHS["okx_passphrase"])):
        return True, "OKX_API_KEY / OKX_API_SECRET / OKX_PASSPHRASE"
    return False, ""


def validate_exchange_configuration() -> StartupValidationResult:
    """
    Validate exchange configuration and check that at least one broker is viable.

    A broker is *viable* when its required credentials are:
      - Present (not empty / not set)
      - Not placeholder values (e.g. "your_api_key_here")
      - Long enough to be real credentials

    This check does **not** make live API calls; it only inspects environment
    variables.  The bot will refuse to start when zero viable brokers are found.

    Returns:
        StartupValidationResult with validation findings
    """
    result = StartupValidationResult()

    viable_brokers: List[str] = []

    # ------------------------------------------------------------------
    # Kraken (Primary / Platform broker)
    # Accepts KRAKEN_PLATFORM_API_KEY or legacy KRAKEN_API_KEY as fallback.
    # ------------------------------------------------------------------
    kraken_key_set = bool(
        os.getenv("KRAKEN_PLATFORM_API_KEY") or os.getenv("KRAKEN_API_KEY")
    )
    kraken_secret_set = bool(
        os.getenv("KRAKEN_PLATFORM_API_SECRET") or os.getenv("KRAKEN_API_SECRET")
    )
    kraken_viable, kraken_pair = _kraken_credentials_viable()

    if kraken_viable:
        viable_brokers.append("Kraken (Platform)")
        result.add_info(f"✅ Kraken Platform credentials configured and viable ({kraken_pair})")
    elif kraken_key_set or kraken_secret_set:
        result.add_risk(
            StartupRisk.NO_VIABLE_BROKER,
            "Kraken credentials are set but appear to be placeholders or incomplete — "
            "set KRAKEN_PLATFORM_API_KEY + KRAKEN_PLATFORM_API_SECRET with real values",
        )
        result.add_warning(
            "⚠️  KRAKEN CREDENTIALS INVALID: One or both values look like placeholders.\n"
            "    Required format:\n"
            "      KRAKEN_PLATFORM_API_KEY=<alphanumeric key from kraken.com/u/security/api>\n"
            "      KRAKEN_PLATFORM_API_SECRET=<base64 secret (60+ chars)>\n"
            "    Legacy alternative:\n"
            "      KRAKEN_API_KEY=<key>   KRAKEN_API_SECRET=<secret>"
        )
    else:
        result.add_info("ℹ️  Kraken credentials not configured (optional if another broker is set)")

    # ------------------------------------------------------------------
    # Coinbase (fully supported — not disabled in code)
    # ------------------------------------------------------------------
    coinbase_key_set = bool(os.getenv("COINBASE_API_KEY"))
    coinbase_secret_set = bool(os.getenv("COINBASE_API_SECRET"))
    coinbase_viable, coinbase_pair = _coinbase_credentials_viable()

    if coinbase_viable:
        viable_brokers.append("Coinbase")
        result.add_info(f"✅ Coinbase credentials configured and viable ({coinbase_pair})")
    elif coinbase_key_set or coinbase_secret_set:
        result.add_risk(
            StartupRisk.NO_VIABLE_BROKER,
            "Coinbase credentials are set but appear to be placeholders or incomplete — "
            "verify COINBASE_API_KEY and COINBASE_API_SECRET",
        )
        result.add_warning(
            "⚠️  COINBASE CREDENTIALS INVALID: One or both values look like placeholders.\n"
            "    Required format (Cloud API Key):\n"
            "      COINBASE_API_KEY=organizations/{org_id}/apiKeys/{key_id}\n"
            "      COINBASE_API_SECRET=-----BEGIN EC PRIVATE KEY-----\\n<base64>\\n-----END EC PRIVATE KEY-----\n"
            "    In Railway/Docker: use literal \\\\n (backslash-n) to represent newlines\n"
            "    in the PEM block — broker_manager.py converts them automatically.\n"
            "    Get credentials at: https://portal.cdp.coinbase.com/"
        )
    else:
        result.add_info("ℹ️  Coinbase credentials not configured (optional)")

    # ------------------------------------------------------------------
    # Binance
    # ------------------------------------------------------------------
    binance_key_set = bool(os.getenv("BINANCE_API_KEY"))
    binance_secret_set = bool(os.getenv("BINANCE_API_SECRET"))
    binance_viable, binance_pair = _binance_credentials_viable()

    if binance_viable:
        viable_brokers.append("Binance")
        result.add_info(f"✅ Binance credentials configured and viable ({binance_pair})")
    elif binance_key_set or binance_secret_set:
        result.add_warning(
            "⚠️  BINANCE CREDENTIALS INVALID: Values look like placeholders.\n"
            "    Required format:\n"
            "      BINANCE_API_KEY=<64-char alphanumeric key>\n"
            "      BINANCE_API_SECRET=<64-char alphanumeric secret>\n"
            "    Get credentials at: https://www.binance.com/en/my/settings/api-management"
        )
    else:
        result.add_info("ℹ️  Binance credentials not configured (optional)")

    # ------------------------------------------------------------------
    # OKX
    # ------------------------------------------------------------------
    okx_key_set = bool(os.getenv("OKX_API_KEY"))
    okx_viable, okx_pair = _okx_credentials_viable()

    if okx_viable:
        viable_brokers.append("OKX")
        result.add_info(f"✅ OKX credentials configured and viable ({okx_pair})")
    elif okx_key_set:
        result.add_warning(
            "⚠️  OKX CREDENTIALS INVALID: Values look like placeholders.\n"
            "    Required format:\n"
            "      OKX_API_KEY=<alphanumeric key>\n"
            "      OKX_API_SECRET=<alphanumeric secret>\n"
            "      OKX_PASSPHRASE=<your passphrase (set when creating the API key)>\n"
            "    Get credentials at: https://www.okx.com/account/my-api"
        )
    else:
        result.add_info("ℹ️  OKX credentials not configured (optional)")

    # ------------------------------------------------------------------
    # Alpaca
    # ------------------------------------------------------------------
    alpaca_key_set = bool(os.getenv("ALPACA_API_KEY"))
    alpaca_viable, alpaca_pair = _alpaca_credentials_viable()

    if alpaca_viable:
        viable_brokers.append("Alpaca")
        result.add_info(f"✅ Alpaca credentials configured and viable ({alpaca_pair})")
    elif alpaca_key_set:
        result.add_warning(
            "⚠️  ALPACA CREDENTIALS INVALID: Values look like placeholders.\n"
            "    Required format:\n"
            "      ALPACA_API_KEY=PK<alphanumeric>  (live) or CK<alphanumeric> (paper)\n"
            "      ALPACA_API_SECRET=<alphanumeric secret>\n"
            "      ALPACA_PAPER=true  # set false for live trading\n"
            "    Get credentials at: https://alpaca.markets/"
        )
    else:
        result.add_info("ℹ️  Alpaca credentials not configured (optional)")

    # ------------------------------------------------------------------
    # Summary — require at least one viable broker
    # ------------------------------------------------------------------
    result.add_info(f"Viable brokers: {len(viable_brokers)} — {', '.join(viable_brokers) if viable_brokers else 'NONE'}")

    if not viable_brokers:
        result.mark_critical_failure(
            "No viable broker credentials found. At least one exchange must have valid, "
            "non-placeholder credentials set. Check environment variables for: "
            "KRAKEN_PLATFORM_API_KEY/SECRET (or KRAKEN_API_KEY/SECRET), "
            "COINBASE_API_KEY/SECRET, BINANCE_API_KEY/SECRET, "
            "OKX_API_KEY/SECRET/PASSPHRASE, or ALPACA_API_KEY/SECRET."
        )
        result.add_risk(
            StartupRisk.NO_VIABLE_BROKER,
            "CRITICAL: No viable broker — trading cannot occur"
        )

    return result


def validate_trading_mode() -> StartupValidationResult:
    """
    Validate that trading mode (testing vs. live) is intentionally set.
    
    Risk: Multiple mode flags exist (PAPER_MODE, LIVE_CAPITAL_VERIFIED, DRY_RUN_MODE, etc.)
    making it unclear whether the bot is in testing or live mode. Accidental
    live trading can occur if flags are misconfigured.
    
    Returns:
        StartupValidationResult with validation findings
    """
    result = StartupValidationResult()
    
    # Check DRY_RUN_MODE flag (takes priority - safest mode)
    dry_run_str = os.getenv("DRY_RUN_MODE", "false").lower()
    dry_run_mode = dry_run_str in ("true", "1", "yes")
    
    # Check PAPER_MODE flag (default to false for consistency)
    paper_mode_str = os.getenv("PAPER_MODE", "false").lower()
    paper_mode = paper_mode_str in ("true", "1", "yes")
    
    # Check LIVE_CAPITAL_VERIFIED flag (default to false for consistency)
    live_verified_str = os.getenv("LIVE_CAPITAL_VERIFIED", "false").lower()
    live_verified = live_verified_str in ("true", "1", "yes")
    
    # Check if mode flags are contradictory
    if dry_run_mode and live_verified:
        result.add_risk(
            StartupRisk.MODE_AMBIGUOUS,
            "CONTRADICTORY: Both DRY_RUN_MODE=true and LIVE_CAPITAL_VERIFIED=true are set"
        )
        result.add_warning(
            "⚠️  MODE CONFLICT: DRY_RUN_MODE and LIVE_CAPITAL_VERIFIED both enabled. "
            "DRY_RUN_MODE takes priority (simulation mode)."
        )
    
    if paper_mode and live_verified:
        result.add_risk(
            StartupRisk.MODE_AMBIGUOUS,
            "CONTRADICTORY: Both PAPER_MODE=true and LIVE_CAPITAL_VERIFIED=true are set"
        )
        result.add_warning(
            "⚠️  MODE CONFLICT: PAPER_MODE and LIVE_CAPITAL_VERIFIED both enabled. "
            "This is contradictory. Bot behavior may be unpredictable."
        )
    
    # Determine actual mode (priority: DRY_RUN > LIVE > PAPER)
    if dry_run_mode:
        result.add_info("🟡 DRY RUN MODE: DRY_RUN_MODE=true (SAFEST - Full simulation)")
        result.add_info(
            "✅ SIMULATION ONLY: All exchanges in dry-run mode. "
            "No real orders will be placed. No real money at risk."
        )
    elif live_verified:
        result.add_info("🔴 LIVE TRADING MODE: LIVE_CAPITAL_VERIFIED=true")
        result.add_warning(
            "⚠️  LIVE TRADING ENABLED: Real money at risk. "
            "Ensure this is intentional. Set LIVE_CAPITAL_VERIFIED=false to disable live trading."
        )
    elif paper_mode:
        result.add_info("📝 PAPER TRADING MODE: PAPER_MODE=true")
    else:
        # Neither flag is explicitly set - ambiguous
        result.add_risk(
            StartupRisk.MODE_AMBIGUOUS,
            "Trading mode is AMBIGUOUS - no mode flags explicitly set"
        )
        result.add_warning(
            "⚠️  MODE UNCLEAR: Trading mode not explicitly configured. "
            "Set DRY_RUN_MODE=true for full simulation, PAPER_MODE=true for testing, "
            "or LIVE_CAPITAL_VERIFIED=true for live trading."
        )
    
    # Additional mode flags for context
    app_store_mode = os.getenv("APP_STORE_MODE", "false").lower() in ("true", "1", "yes")
    if app_store_mode:
        result.add_info("📱 APP_STORE_MODE enabled (demo mode for App Store reviewers)")
    
    return result


def validate_account_hierarchy() -> StartupValidationResult:
    """
    Validate that platform account credentials are configured before user accounts.

    Risk: When user accounts have credentials configured but the platform account does
    not, users temporarily act as primary traders. This breaks the intended account
    hierarchy and can cause reporting and position-attribution issues.

    Platform account should always be configured first so it acts as the primary
    account; user accounts are secondary.

    Brokers checked:
      - Kraken: platform = KRAKEN_PLATFORM_API_KEY + KRAKEN_PLATFORM_API_SECRET
                users   = KRAKEN_USER_*_API_KEY
      - Alpaca:  platform = ALPACA_API_KEY + ALPACA_API_SECRET   (optional broker)
                users   = ALPACA_USER_*_API_KEY

    Returns:
        StartupValidationResult with validation findings
    """
    result = StartupValidationResult()

    # ── Kraken ────────────────────────────────────────────────────────────────
    kraken_platform_configured = bool(
        os.getenv("KRAKEN_PLATFORM_API_KEY") and os.getenv("KRAKEN_PLATFORM_API_SECRET")
    )

    # Detect any Kraken user credentials by scanning environment variables for
    # the pattern KRAKEN_USER_*_API_KEY (e.g. KRAKEN_USER_DAIVON_API_KEY)
    kraken_users_configured = [
        key for key in os.environ
        if key.startswith("KRAKEN_USER_") and key.endswith("_API_KEY") and os.environ[key]
    ]

    if kraken_users_configured and not kraken_platform_configured:
        user_count = len(kraken_users_configured)
        result.add_risk(
            StartupRisk.PLATFORM_NOT_CONFIGURED_FIRST,
            f"Kraken user account(s) configured ({user_count}) but Platform account credentials are missing"
        )
        result.add_warning(
            "⚠️  HIERARCHY ISSUE: Kraken user account(s) are configured but the Platform account "
            "is NOT. Users will temporarily act as primary traders, which may cause hierarchy "
            "and reporting issues. Configure Platform account credentials first: "
            "KRAKEN_PLATFORM_API_KEY and KRAKEN_PLATFORM_API_SECRET."
        )
        result.add_info(
            "💡 RECOMMENDATION: Set KRAKEN_PLATFORM_API_KEY and KRAKEN_PLATFORM_API_SECRET "
            "so the Platform account is established before user accounts connect. "
            "See PLATFORM_ACCOUNT_REQUIRED.md for setup instructions."
        )
    elif kraken_platform_configured:
        result.add_info("✅ Kraken Platform account configured (correct hierarchy: Platform first)")
        if kraken_users_configured:
            result.add_info(
                f"✅ {len(kraken_users_configured)} Kraken user account(s) configured after Platform (correct order)"
            )

    # ── Alpaca (optional broker) ───────────────────────────────────────────────
    enable_alpaca = os.getenv("ENABLE_ALPACA", "false").lower() in ("1", "true", "yes", "on")
    if not enable_alpaca:
        result.add_info("ℹ️  Alpaca hierarchy checks skipped — ENABLE_ALPACA=false")
    else:
        # Platform credentials: ALPACA_API_KEY + ALPACA_API_SECRET
        # User credentials:     ALPACA_USER_*_API_KEY  (e.g. ALPACA_USER_TANIA_API_KEY)
        alpaca_platform_configured = bool(
            os.getenv("ALPACA_API_KEY") and os.getenv("ALPACA_API_SECRET")
        )

        alpaca_users_configured = [
            key for key in os.environ
            if key.startswith("ALPACA_USER_") and key.endswith("_API_KEY") and os.environ[key]
        ]

        if alpaca_users_configured and not alpaca_platform_configured:
            user_count = len(alpaca_users_configured)
            result.add_risk(
                StartupRisk.PLATFORM_NOT_CONFIGURED_FIRST,
                f"Alpaca user account(s) configured ({user_count}) but Platform account credentials are missing"
            )
            result.add_warning(
                "⚠️  HIERARCHY ISSUE: Alpaca user account(s) are configured but the Platform account "
                "is NOT. Users will temporarily act as primary traders, which may cause hierarchy "
                "and reporting issues. Configure Platform account credentials first: "
                "ALPACA_API_KEY and ALPACA_API_SECRET."
            )
            result.add_info(
                "💡 RECOMMENDATION: Set ALPACA_API_KEY and ALPACA_API_SECRET "
                "so the Alpaca Platform account is established before user accounts connect."
            )
        elif alpaca_platform_configured:
            result.add_info("✅ Alpaca Platform account configured (correct hierarchy: Platform first)")
            if alpaca_users_configured:
                result.add_info(
                    f"✅ {len(alpaca_users_configured)} Alpaca user account(s) configured after Platform (correct order)"
                )

    return result


def validate_ntp_clock() -> StartupValidationResult:
    """
    Validate that the system clock is synchronized within Kraken's ±1 s tolerance.

    A clock that is more than 1 second off from NTP will cause Kraken to reject
    every private API call with "EAPI:Invalid nonce", blocking ALL accounts.

    Returns:
        StartupValidationResult with NTP check findings
    """
    result = StartupValidationResult()
    try:
        try:
            from bot.global_kraken_nonce import check_ntp_sync
        except ImportError:
            from global_kraken_nonce import check_ntp_sync  # type: ignore[import]

        r = check_ntp_sync()
    except Exception as exc:
        result.add_warning(
            f"NTP check could not run ({exc}). "
            "Verify clock manually: sudo ntpdate pool.ntp.org"
        )
        result.add_info("Install ntplib to enable NTP checks: pip install ntplib==0.4.0")
        return result

    if r.get("error"):
        result.add_warning(
            f"NTP check skipped: {r['error']}. "
            "Verify clock manually: sudo ntpdate pool.ntp.org"
        )
        result.add_info("Install ntplib to enable NTP checks: pip install ntplib==0.4.0")
        return result

    offset_s = r.get("offset_s", 0.0)
    server = r.get("server", "pool.ntp.org")
    offset_ms = int(offset_s * 1000)
    abs_s = abs(offset_s)

    if not r.get("ok"):
        result.add_risk(
            StartupRisk.NTP_CLOCK_DRIFT,
            f"CLOCK DRIFT: system clock is {offset_s:+.3f} s ({offset_ms:+d} ms) vs {server}. "
            "Kraken requires ±1 s accuracy — nonce errors WILL occur on ALL accounts."
        )
        result.add_warning(
            f"Fix clock drift now:\n"
            "  sudo ntpdate pool.ntp.org\n"
            "  OR enable chrony: sudo systemctl start chronyd"
        )
    elif abs_s > 0.5:
        result.add_warning(
            f"Clock drift warning: {offset_s:+.3f} s ({offset_ms:+d} ms) vs {server}. "
            "Within ±1 s Kraken window but approaching the limit. "
            "Recommend: sudo ntpdate pool.ntp.org"
        )
        result.add_info(f"NTP clock check: within tolerance (±1 s) — {offset_s:+.3f} s vs {server}")
    else:
        result.add_info(
            f"✅ NTP clock OK: {offset_s:+.3f} s vs {server} (within Kraken ±1 s tolerance)"
        )

    return result


def validate_data_directory() -> StartupValidationResult:
    """
    Ensure the NIJA data directory exists and is writable.

    The data directory stores the Kraken nonce state file and other
    persistence files.  If it cannot be created or is not writable the
    nonce manager will fail on its first write, causing Kraken nonce errors.

    Returns:
        StartupValidationResult with data directory check findings
    """
    import pathlib
    result = StartupValidationResult()
    _default_data_dir = pathlib.Path(__file__).parent.parent / "data"
    data_dir = os.path.abspath(os.environ.get("NIJA_DATA_DIR", str(_default_data_dir)))

    try:
        os.makedirs(data_dir, mode=0o700, exist_ok=True)
    except OSError as exc:
        result.add_risk(
            StartupRisk.DATA_DIR_UNAVAILABLE,
            f"Cannot create data directory {data_dir!r}: {exc}. "
            "Kraken nonce persistence will fail — nonce errors on every restart."
        )
        result.add_warning(
            f"Fix: ensure the process has write access to {data_dir!r}, "
            "or set NIJA_DATA_DIR to a writable path."
        )
        return result

    if not os.access(data_dir, os.W_OK):
        result.add_risk(
            StartupRisk.DATA_DIR_UNAVAILABLE,
            f"Data directory {data_dir!r} exists but is not writable. "
            "Kraken nonce persistence will fail — nonce errors on every restart."
        )
        result.add_warning(
            f"Fix: chmod u+w {data_dir!r} or set NIJA_DATA_DIR to a writable path."
        )
    else:
        result.add_info(f"✅ Data directory OK: {data_dir!r}")

    return result


def run_all_validations(git_branch: str, git_commit: str) -> StartupValidationResult:
    """
    Run all startup validations and combine results.
    
    Args:
        git_branch: Git branch name
        git_commit: Git commit hash
        
    Returns:
        Combined StartupValidationResult
    """
    combined = StartupValidationResult()
    
    # 1. Validate git metadata
    git_result = validate_git_metadata(git_branch, git_commit)
    combined.risks.extend(git_result.risks)
    combined.warnings.extend(git_result.warnings)
    combined.info.extend(git_result.info)
    if git_result.critical_failure:
        combined.mark_critical_failure(git_result.failure_reason)
    
    # 2. Validate exchange configuration
    exchange_result = validate_exchange_configuration()
    combined.risks.extend(exchange_result.risks)
    combined.warnings.extend(exchange_result.warnings)
    combined.info.extend(exchange_result.info)
    if exchange_result.critical_failure:
        combined.mark_critical_failure(exchange_result.failure_reason)
    
    # 3. Validate trading mode
    mode_result = validate_trading_mode()
    combined.risks.extend(mode_result.risks)
    combined.warnings.extend(mode_result.warnings)
    combined.info.extend(mode_result.info)
    if mode_result.critical_failure:
        combined.mark_critical_failure(mode_result.failure_reason)

    # 4. Validate account hierarchy (platform credentials must come before user credentials)
    hierarchy_result = validate_account_hierarchy()
    combined.risks.extend(hierarchy_result.risks)
    combined.warnings.extend(hierarchy_result.warnings)
    combined.info.extend(hierarchy_result.info)
    if hierarchy_result.critical_failure:
        combined.mark_critical_failure(hierarchy_result.failure_reason)

    # 5. Validate NTP clock synchronization (Kraken requires system clock within ±1 s)
    ntp_result = validate_ntp_clock()
    combined.risks.extend(ntp_result.risks)
    combined.warnings.extend(ntp_result.warnings)
    combined.info.extend(ntp_result.info)
    if ntp_result.critical_failure:
        combined.mark_critical_failure(ntp_result.failure_reason)

    # 6. Validate data directory (nonce persistence, position files, etc.)
    data_dir_result = validate_data_directory()
    combined.risks.extend(data_dir_result.risks)
    combined.warnings.extend(data_dir_result.warnings)
    combined.info.extend(data_dir_result.info)
    if data_dir_result.critical_failure:
        combined.mark_critical_failure(data_dir_result.failure_reason)

    # 7. Combined check: escalate to critical failure when live trading with unknown git metadata.
    # Running untraceable code in live mode is prohibited for auditability.
    live_verified = os.getenv("LIVE_CAPITAL_VERIFIED", "false").lower() in ("true", "1", "yes")
    dry_run = os.getenv("DRY_RUN_MODE", "false").lower() in ("true", "1", "yes")
    git_unknown = _is_git_metadata_unknown(git_branch) or _is_git_metadata_unknown(git_commit)
    allow_untraceable = os.getenv("ALLOW_UNTRACEABLE_CODE", "false").lower() in ("true", "1", "yes")
    if live_verified and not dry_run and git_unknown and not allow_untraceable:
        combined.mark_critical_failure(
            "Live trading with unknown git metadata is prohibited. "
            "Set GIT_BRANCH and GIT_COMMIT (or run inject_git_metadata.sh), "
            "or use DRY_RUN_MODE=true for safe testing."
        )
    
    return combined


def display_validation_results(result: StartupValidationResult):
    """
    Display validation results with visual formatting.
    
    Args:
        result: StartupValidationResult to display
    """
    logger.info("=" * 80)
    logger.info("🔍 STARTUP VALIDATION REPORT")
    logger.info("=" * 80)
    
    # Display risks
    if result.has_risks():
        logger.warning("")
        logger.warning("⚠️  RISKS DETECTED:")
        logger.warning("─" * 80)
        for risk_type, message in result.risks:
            logger.warning(f"   [{risk_type.value.upper()}] {message}")
        logger.warning("─" * 80)
    else:
        logger.info("✅ No risks detected")
    
    # Display warnings
    if result.warnings:
        logger.warning("")
        logger.warning("⚠️  WARNINGS:")
        logger.warning("─" * 80)
        for warning in result.warnings:
            logger.warning(f"   {warning}")
        logger.warning("─" * 80)
    
    # Display info
    if result.info:
        logger.info("")
        logger.info("ℹ️  CONFIGURATION INFO:")
        logger.info("─" * 80)
        for info in result.info:
            logger.info(f"   {info}")
        logger.info("─" * 80)
    
    # Critical failure
    if result.critical_failure:
        logger.error("")
        logger.error("=" * 80)
        logger.error("❌ CRITICAL FAILURE - BOT CANNOT START")
        logger.error("=" * 80)
        logger.error(f"   Reason: {result.failure_reason}")
        logger.error("=" * 80)
    
    logger.info("=" * 80)
    
    # Summary
    risk_count = len(result.risks)
    warning_count = len(result.warnings)
    
    if result.critical_failure:
        logger.error(f"RESULT: FAILED (Critical failure)")
    elif risk_count > 0:
        logger.warning(f"RESULT: PASSED WITH RISKS ({risk_count} risks, {warning_count} warnings)")
    elif warning_count > 0:
        logger.warning(f"RESULT: PASSED WITH WARNINGS ({warning_count} warnings)")
    else:
        logger.info("RESULT: PASSED (No risks or warnings)")
    
    logger.info("=" * 80)
    logger.info("")
    
    # Log monitoring reminder
    logger.info("📋 LOG MONITORING: Watch for these patterns in nija.log / stdout:")
    logger.info("   ❌ ORDER REJECTED / EXECUTION ERROR — trade could not be placed")
    logger.info("   ⚠️  API ERROR / RATE LIMITED       — connectivity or throttling issues")
    logger.info("   ⚠️  INSUFFICIENT FUNDS             — balance too low for trade")
    logger.info("=" * 80)
    logger.info("")
