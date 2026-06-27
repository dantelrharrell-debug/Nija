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
import threading
import math
from typing import Dict, List, Optional, Tuple
from enum import Enum
from urllib.parse import urlparse

logger = logging.getLogger("nija")
_VALIDATION_REPORT_LOCK = threading.Lock()
_VALIDATION_REPORT_EMITTED = False
# Execution unlock timeout guardrails:
# - minimum 1s avoids zero/negative no-wait unlock paths
# - maximum 300s avoids long silent startup stalls due to bad configuration
MIN_EXECUTION_UNLOCK_TIMEOUT_S = 1.0
MAX_EXECUTION_UNLOCK_TIMEOUT_S = 300.0

try:
    from bot.runtime_mode import resolve_runtime_mode
except ImportError:
    from runtime_mode import resolve_runtime_mode  # type: ignore[import]


def _import_redis_env_helpers():
    """Import Redis env helper functions with package/local fallback."""
    try:
        from bot.redis_env import get_nija_url_format_error, get_redis_url, get_redis_url_source
    except ImportError:
        from redis_env import get_nija_url_format_error, get_redis_url, get_redis_url_source  # type: ignore[import]
    return get_nija_url_format_error, get_redis_url, get_redis_url_source


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
    ENVIRONMENT_MISCONFIGURATION = "environment_misconfiguration"


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


def _kraken_user_env_suffixes(user_id: str) -> List[str]:
    """Return credential suffixes accepted by Kraken user-account loading code."""
    normalized = str(user_id or "").strip().replace("-", "_")
    if not normalized:
        return []
    if normalized.lower().startswith("user_"):
        normalized = normalized[5:]
    pieces = [normalized.split("_")[0], normalized, str(user_id).strip().replace("-", "_")]
    suffixes: List[str] = []
    seen = set()
    for piece in pieces:
        suffix = re.sub(r"[^A-Za-z0-9_]", "_", piece).upper().strip("_")
        if suffix and suffix not in seen:
            suffixes.append(suffix)
            seen.add(suffix)
    return suffixes


def _kraken_user_credentials_viable(user_id: str) -> Tuple[bool, str, str]:
    """Check one configured Kraken user's key/secret pair without making API calls."""
    first_key_var = ""
    first_secret_var = ""
    for suffix in _kraken_user_env_suffixes(user_id):
        key_var = f"KRAKEN_USER_{suffix}_API_KEY"
        secret_var = f"KRAKEN_USER_{suffix}_API_SECRET"
        if not first_key_var:
            first_key_var = key_var
            first_secret_var = secret_var
        key = os.getenv(key_var, "").strip()
        secret = os.getenv(secret_var, "").strip()
        if (_credential_looks_valid(key, _MIN_LENGTHS["kraken_key"]) and
                _credential_looks_valid(secret, _MIN_LENGTHS["kraken_secret"])):
            return True, f"{key_var} / {secret_var}", ""
        if key or secret:
            missing = []
            if not _credential_looks_valid(key, _MIN_LENGTHS["kraken_key"]):
                missing.append(key_var)
            if not _credential_looks_valid(secret, _MIN_LENGTHS["kraken_secret"]):
                missing.append(secret_var)
            return False, f"{key_var} / {secret_var}", ", ".join(missing)
    expected = (
        f"{first_key_var} / {first_secret_var}"
        if first_key_var
        else "KRAKEN_USER_<USER>_API_KEY / KRAKEN_USER_<USER>_API_SECRET"
    )
    return False, expected, "missing key and secret"


def _enabled_kraken_config_users() -> List[str]:
    """Return enabled Kraken users from config, respecting user-account feature flags."""
    if os.getenv("NIJA_DISABLE_USER_ACCOUNTS", "false").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    ):
        return []
    if os.getenv("ENABLE_KRAKEN_USER_TRADING", "true").strip().lower() in (
        "0",
        "false",
        "no",
        "off",
    ):
        return []
    try:
        from config.user_loader import get_user_config_loader

        loader = get_user_config_loader()
        if not loader.all_users:
            loader.load_all_users()
        return [
            str(user.user_id)
            for user in loader.get_all_enabled_users()
            if str(getattr(user, "broker_type", "")).lower() == "kraken"
        ]
    except Exception as exc:
        logger.debug("Unable to load Kraken user config during startup validation: %s", exc)
        return []


def _coinbase_credentials_viable() -> Tuple[bool, str]:
    """
    Check whether Coinbase credentials look viable.

    Accepts both the new Cloud API key format
    (``organizations/{org_id}/apiKeys/{key_id}``) and the shorter legacy key
    format.  The secret must contain PEM markers **or** be a sufficiently long
    non-placeholder string (some integrations store only the raw EC key body).
    """
    key = os.getenv("COINBASE_API_KEY", "").strip()
    secret = (
        os.getenv("COINBASE_API_SECRET", "").strip()
        or os.getenv("COINBASE_PEM_CONTENT", "").strip()
    )

    if not _credential_looks_valid(key, _MIN_LENGTHS["coinbase_key"]):
        return False, ""
    if not _credential_looks_valid(secret, _MIN_LENGTHS["coinbase_secret"]):
        return False, ""
    # If the secret looks like a PEM key (recommended) that's a strong signal
    if "-----BEGIN" in secret or "-----END" in secret:
        return True, "COINBASE_API_KEY / COINBASE_API_SECRET|COINBASE_PEM_CONTENT (PEM format)"
    return True, "COINBASE_API_KEY / COINBASE_API_SECRET|COINBASE_PEM_CONTENT"


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
    coinbase_secret_set = bool(
        os.getenv("COINBASE_API_SECRET") or os.getenv("COINBASE_PEM_CONTENT")
    )
    coinbase_viable, coinbase_pair = _coinbase_credentials_viable()

    if coinbase_viable:
        viable_brokers.append("Coinbase")
        result.add_info(f"✅ Coinbase credentials configured and viable ({coinbase_pair})")
    elif coinbase_key_set or coinbase_secret_set:
        result.add_risk(
            StartupRisk.NO_VIABLE_BROKER,
            "Coinbase credentials are set but appear to be placeholders or incomplete — "
            "verify COINBASE_API_KEY and COINBASE_API_SECRET/COINBASE_PEM_CONTENT",
        )
        result.add_warning(
            "⚠️  COINBASE CREDENTIALS INVALID: One or both values look like placeholders.\n"
            "    Required format (Cloud API Key):\n"
            "      COINBASE_API_KEY=organizations/{org_id}/apiKeys/{key_id}\n"
            "      COINBASE_API_SECRET=-----BEGIN EC PRIVATE KEY-----\\n<base64>\\n-----END EC PRIVATE KEY-----\n"
            "      or COINBASE_PEM_CONTENT with the same PEM content\n"
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
    # OKX (direct REST client; no okx/candlelite SDK import)
    # ------------------------------------------------------------------
    okx_disabled = os.getenv("NIJA_DISABLE_OKX", "false").strip().lower() in ("1", "true", "yes")
    okx_key_set = bool(os.getenv("OKX_API_KEY"))
    okx_viable, okx_pair = _okx_credentials_viable()

    if okx_disabled:
        result.add_info("ℹ️  OKX disabled by NIJA_DISABLE_OKX=true")
    elif okx_viable:
        viable_brokers.append("OKX")
        result.add_info(f"✅ OKX credentials configured and viable for direct REST trading ({okx_pair})")
    elif okx_key_set:
        result.add_warning(
            "⚠️  OKX CREDENTIALS INVALID: Values look like placeholders.\n"
            "    Required format:\n"
            "      OKX_API_KEY=<alphanumeric key>\n"
            "      OKX_API_SECRET=<alphanumeric secret>\n"
            "      OKX_PASSPHRASE=<your passphrase (set when creating the API key)>\n"
            "    OKX uses NIJA direct REST now; the okx/candlelite SDK is not imported."
        )
    else:
        result.add_info("ℹ️  OKX credentials not configured (optional direct REST broker)")

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
    
    runtime_mode = resolve_runtime_mode()
    dry_run_mode = runtime_mode.dry_run
    paper_mode = runtime_mode.paper
    if "dry_run_vs_live" in runtime_mode.conflicts:
        result.add_risk(
            StartupRisk.MODE_AMBIGUOUS,
            "CONTRADICTORY: DRY_RUN_MODE=true with LIVE_CAPITAL_VERIFIED/LIVE_TRADING enabled"
        )
        result.add_warning(
            "⚠️  MODE CONFLICT: DRY_RUN_MODE and LIVE trading flags both enabled. "
            "DRY_RUN_MODE takes priority (simulation mode)."
        )

    if "paper_vs_live" in runtime_mode.conflicts:
        result.add_risk(
            StartupRisk.MODE_AMBIGUOUS,
            "CONTRADICTORY: PAPER_MODE=true with LIVE_CAPITAL_VERIFIED/LIVE_TRADING enabled"
        )
        result.add_warning(
            "⚠️  MODE CONFLICT: PAPER_MODE and LIVE trading flags both enabled. "
            "This is contradictory. Bot behavior may be unpredictable."
        )

    # Determine actual mode (priority: DRY_RUN > LIVE > PAPER)
    if runtime_mode.mode == "dry_run":
        result.add_info("🟡 DRY RUN MODE: DRY_RUN_MODE=true (SAFEST - Full simulation)")
        result.add_info(
            "✅ SIMULATION ONLY: All exchanges in dry-run mode. "
            "No real orders will be placed. No real money at risk."
        )
    elif runtime_mode.mode == "live":
        result.add_info("🔴 LIVE TRADING MODE: LIVE_CAPITAL_VERIFIED/LIVE_TRADING enabled")
        result.add_warning(
            "⚠️  LIVE TRADING ENABLED: Real money at risk. "
            "Ensure this is intentional. Set LIVE_CAPITAL_VERIFIED=false to disable live trading."
        )
    elif runtime_mode.mode == "paper":
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
        enabled_kraken_users = _enabled_kraken_config_users()
        viable_enabled_users: List[str] = []
        for user_id in enabled_kraken_users:
            viable, pair, missing = _kraken_user_credentials_viable(user_id)
            if viable:
                viable_enabled_users.append(user_id)
                result.add_info(f"✅ Kraken user {user_id} credentials configured and viable ({pair})")
            else:
                result.add_warning(
                    f"⚠️  KRAKEN USER CREDENTIALS INCOMPLETE: enabled user {user_id} cannot connect "
                    f"until {missing or pair} is configured. Expected {pair}."
                )
        if viable_enabled_users:
            result.add_info(
                f"✅ {len(viable_enabled_users)} enabled Kraken user account(s) have viable credentials after Platform (correct order)"
            )
        elif kraken_users_configured:
            result.add_warning(
                "⚠️  KRAKEN USER CREDENTIALS PRESENT BUT NOT MATCHED: found "
                f"{len(kraken_users_configured)} KRAKEN_USER_*_API_KEY value(s), but no enabled Kraken "
                "user config has a complete key/secret pair. User capital will not connect until "
                "the env var names match enabled config users and include API secrets."
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


def validate_operational_environment_config() -> StartupValidationResult:
    """
    Validate high-impact operational environment settings.

    This check fail-closes startup on environment misconfiguration that can
    silently alter safety behavior:
      1) contradictory runtime mode flags
      2) invalid/missing Redis URL in live-authorized mode
      3) invalid execution unlock timeout
    """
    result = StartupValidationResult()

    runtime_mode = resolve_runtime_mode()
    if runtime_mode.conflicts:
        conflict_list = ", ".join(runtime_mode.conflicts)
        result.add_risk(
            StartupRisk.ENVIRONMENT_MISCONFIGURATION,
            f"Conflicting mode flags detected: {conflict_list}",
        )
        result.add_warning(
            "❌ MODE FLAG MISCONFIGURATION: resolve conflicting mode flags before startup "
            f"(conflicts: {conflict_list})."
        )
        result.mark_critical_failure(
            f"Contradictory runtime mode flags: {conflict_list}. "
            "Set only one operational mode (dry-run, paper, or live)."
        )

    try:
        get_nija_url_format_error, get_redis_url, get_redis_url_source = _import_redis_env_helpers()
        nija_format_error = get_nija_url_format_error()
        if nija_format_error:
            result.add_risk(
                StartupRisk.ENVIRONMENT_MISCONFIGURATION,
                "NIJA_REDIS_URL format is invalid",
            )
            result.add_warning(f"❌ REDIS URL MISCONFIGURATION: {nija_format_error}")
            result.mark_critical_failure(
                "Invalid NIJA_REDIS_URL format. Set NIJA_REDIS_URL to a valid redis:// or rediss:// URL."
            )
        else:
            redis_url = get_redis_url()
            redis_source = get_redis_url_source() or "unset"
            if runtime_mode.live_authorized and not redis_url:
                result.add_risk(
                    StartupRisk.ENVIRONMENT_MISCONFIGURATION,
                    "Live-authorized mode requires a valid Redis URL",
                )
                result.add_warning(
                    "❌ REDIS MISCONFIGURATION: LIVE_CAPITAL_VERIFIED/LIVE_TRADING is enabled but no "
                    "valid Redis URL could be resolved."
                )
                result.mark_critical_failure(
                    "Live-authorized mode requires Redis lock configuration. "
                    "Set NIJA_REDIS_URL (or valid Redis component env vars) before startup."
                )
            elif redis_url:
                parsed = urlparse(redis_url)
                scheme = (parsed.scheme or "").lower()
                if scheme not in {"redis", "rediss"}:
                    result.add_risk(
                        StartupRisk.ENVIRONMENT_MISCONFIGURATION,
                        f"Resolved Redis URL from {redis_source} has unsupported scheme '{scheme or 'missing'}'",
                    )
                    result.add_warning(
                        "❌ REDIS MISCONFIGURATION: resolved Redis URL must use redis:// or rediss://."
                    )
                    result.mark_critical_failure(
                        f"Resolved Redis URL from {redis_source} uses unsupported scheme '{scheme or 'missing'}'."
                    )
                if not parsed.hostname:
                    result.add_risk(
                        StartupRisk.ENVIRONMENT_MISCONFIGURATION,
                        f"Resolved Redis URL from {redis_source} is missing host",
                    )
                    result.add_warning(
                        "❌ REDIS MISCONFIGURATION: resolved Redis URL is missing hostname."
                    )
                    result.mark_critical_failure(
                        f"Resolved Redis URL from {redis_source} is missing hostname."
                    )
    except Exception as exc:
        result.add_risk(
            StartupRisk.ENVIRONMENT_MISCONFIGURATION,
            "Operational Redis configuration validation failed to run",
        )
        result.add_warning(
            f"❌ REDIS VALIDATION ERROR: unable to validate Redis configuration ({exc})"
        )
        result.mark_critical_failure(
            "Could not validate Redis environment configuration."
        )

    unlock_timeout_raw = os.getenv("NIJA_EXECUTION_UNLOCK_TIMEOUT_S", "").strip()
    if unlock_timeout_raw:
        def _record_invalid_unlock_timeout(err_message: str) -> None:
            result.add_risk(
                StartupRisk.ENVIRONMENT_MISCONFIGURATION,
                "NIJA_EXECUTION_UNLOCK_TIMEOUT_S is invalid",
            )
            result.add_warning(
                "❌ EXECUTION UNLOCK TIMEOUT MISCONFIGURATION: "
                f"NIJA_EXECUTION_UNLOCK_TIMEOUT_S={unlock_timeout_raw!r} ({err_message})"
            )
            result.mark_critical_failure(
                "Invalid NIJA_EXECUTION_UNLOCK_TIMEOUT_S. Set a finite value between 1 and 300 seconds."
            )

        try:
            unlock_timeout_s = float(unlock_timeout_raw)
        except (TypeError, ValueError):
            _record_invalid_unlock_timeout("Value must be a valid number")
            return result
        else:
            if not math.isfinite(unlock_timeout_s):
                _record_invalid_unlock_timeout("Value must be a finite number (not infinity or NaN)")
                return result
            # Keep unlock timeout bounded: at least 1s to prevent a zero/negative
            # no-wait startup path, and at most 300s to avoid long silent stalls.
            elif (
                unlock_timeout_s < MIN_EXECUTION_UNLOCK_TIMEOUT_S
                or unlock_timeout_s > MAX_EXECUTION_UNLOCK_TIMEOUT_S
            ):
                _record_invalid_unlock_timeout(
                    f"Timeout must be between {MIN_EXECUTION_UNLOCK_TIMEOUT_S:.1f} and "
                    f"{MAX_EXECUTION_UNLOCK_TIMEOUT_S:.1f} seconds"
                )
                return result
            else:
                result.add_info(
                    f"✅ NIJA_EXECUTION_UNLOCK_TIMEOUT_S valid: {unlock_timeout_s:.3f}s"
                )
    else:
        result.add_info(
            "ℹ️ NIJA_EXECUTION_UNLOCK_TIMEOUT_S not set — using default runtime timeout"
        )

    return result


def check_and_reset_generation_mismatch() -> StartupValidationResult:
    """Detect and auto-reset a generation counter mismatch at startup.

    Reads the local ``NIJA_WRITER_LEASE_GENERATION`` env var and the live
    Redis value.  When they diverge, calls ``reset_generation_to_redis()`` to
    force-sync the local counter before the heartbeat monitor starts.  This
    prevents the SEAK from being halted by a stale generation value that
    accumulated across deployments (e.g. local=882339 vs redis=753).

    The check is non-blocking and non-fatal: a Redis connectivity failure or
    an unusable generation value is logged as a warning and does not prevent
    startup.
    """
    result = StartupValidationResult()

    try:
        try:
            from bot.writer_generation_tracker import (
                get_local_generation,
                get_redis_generation,
                reset_generation_to_redis,
            )
        except ImportError:
            from writer_generation_tracker import (  # type: ignore[import]
                get_local_generation,
                get_redis_generation,
                reset_generation_to_redis,
            )

        local = get_local_generation()
        if local <= 0:
            # Generation not yet set — nothing to check at this stage.
            result.add_info(
                "GENERATION_STARTUP_CHECK: local generation not yet set — skipping"
            )
            return result

        redis_gen, err = get_redis_generation()
        if err:
            result.add_warning(
                f"GENERATION_STARTUP_CHECK: could not read Redis generation "
                f"(non-fatal) — {err}"
            )
            return result

        if redis_gen <= 0:
            result.add_warning(
                "GENERATION_STARTUP_CHECK: Redis generation key missing or zero — "
                "skipping reset (Redis may not have a lease yet)"
            )
            return result

        delta = abs(local - redis_gen)
        if local == redis_gen:
            result.add_info(
                f"GENERATION_STARTUP_CHECK: generation OK local={local} redis={redis_gen}"
            )
            return result

        # Mismatch detected — auto-reset.
        logger.critical(
            "GENERATION_STARTUP_CHECK: generation mismatch detected at startup "
            "local=%d redis=%d delta=%d — auto-resetting to Redis value",
            local,
            redis_gen,
            delta,
        )
        reset_ok, reset_msg = reset_generation_to_redis()
        if reset_ok:
            result.add_info(
                f"GENERATION_STARTUP_CHECK: generation reset succeeded — {reset_msg}"
            )
            logger.critical(
                "GENERATION_STARTUP_CHECK: startup generation reset complete — "
                "local generation is now %d (was %d, delta=%d)",
                redis_gen,
                local,
                delta,
            )
        else:
            result.add_warning(
                f"GENERATION_STARTUP_CHECK: generation reset failed (non-fatal) — "
                f"{reset_msg}"
            )
    except Exception as exc:
        result.add_warning(
            f"GENERATION_STARTUP_CHECK: unexpected error during startup generation "
            f"check (non-fatal) — {exc}"
        )

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

    # 7. Validate high-impact operational environment configuration.
    env_result = validate_operational_environment_config()
    combined.risks.extend(env_result.risks)
    combined.warnings.extend(env_result.warnings)
    combined.info.extend(env_result.info)
    if env_result.critical_failure:
        combined.mark_critical_failure(env_result.failure_reason)

    # 8. Detect and auto-reset generation counter mismatch before the heartbeat
    #    monitor starts.  This is a non-fatal, non-blocking check that prevents
    #    SEAK lockdown caused by a stale local generation (e.g. local=882339 vs
    #    redis=753 after a deployment that did not cleanly persist the counter).
    gen_result = check_and_reset_generation_mismatch()
    combined.risks.extend(gen_result.risks)
    combined.warnings.extend(gen_result.warnings)
    combined.info.extend(gen_result.info)

    # 9. Combined check: warn when live trading with unknown git metadata.
    # Git metadata is for auditability only and must not block live trading on
    # cloud deployments (e.g. Railway) where the git directory is unavailable
    # at runtime.  Downgraded from critical_failure to an audit risk warning so
    # that missing GIT_BRANCH / GIT_COMMIT env vars never silently loop-block
    # startup.  Operators can suppress the warning with ALLOW_UNTRACEABLE_CODE=true.
    live_verified = os.getenv("LIVE_CAPITAL_VERIFIED", "false").lower() in ("true", "1", "yes")
    dry_run = os.getenv("DRY_RUN_MODE", "false").lower() in ("true", "1", "yes")
    git_unknown = _is_git_metadata_unknown(git_branch) or _is_git_metadata_unknown(git_commit)
    allow_untraceable = os.getenv("ALLOW_UNTRACEABLE_CODE", "false").lower() in ("true", "1", "yes")
    if live_verified and not dry_run and git_unknown and not allow_untraceable:
        combined.add_risk(
            StartupRisk.GIT_METADATA_UNKNOWN,
            "Live trading with unknown git metadata — code version is unverifiable. "
            "Set GIT_BRANCH and GIT_COMMIT (or RAILWAY_GIT_BRANCH/RAILWAY_GIT_COMMIT_SHA) "
            "for full auditability, or set ALLOW_UNTRACEABLE_CODE=true to suppress.",
        )
        combined.add_warning(
            "⚠️  AUDIT WARNING: Live trading with unknown git metadata. "
            "Set GIT_BRANCH and GIT_COMMIT env vars to enable full auditability."
        )
    
    return combined


def display_validation_results(result: StartupValidationResult):
    """
    Display validation results with visual formatting.

    Args:
        result: StartupValidationResult to display
    """
    global _VALIDATION_REPORT_EMITTED
    with _VALIDATION_REPORT_LOCK:
        duplicate_report = _VALIDATION_REPORT_EMITTED and not result.critical_failure
        if not _VALIDATION_REPORT_EMITTED:
            _VALIDATION_REPORT_EMITTED = True

    if duplicate_report:
        logger.info(
            "🔍 STARTUP VALIDATION REPORT already emitted for this process; "
            "suppressing duplicate retry report (warnings=%d risks=%d)",
            len(result.warnings),
            len(result.risks),
        )
        return

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
    logger.info("📋 LOG MONITORING (informational): Watch for these patterns only if they appear in nija.log / stdout:")
    logger.info("   These are runtime alert examples, not startup trade attempts.")
    logger.info("   ❌ ORDER REJECTED / EXECUTION ERROR — trade could not be placed")
    logger.info("   ⚠️  API ERROR / RATE LIMITED       — connectivity or throttling issues")
    logger.info("   ⚠️  INSUFFICIENT FUNDS             — balance too low for trade")
    logger.info("=" * 80)
    logger.info("")
