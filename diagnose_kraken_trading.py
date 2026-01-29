#!/usr/bin/env python3
"""
Kraken Trading Diagnostic Script
=================================

Checks all requirements for Kraken trading to work and provides actionable fixes.

This script checks:
1. Master account requirements (4 conditions)
2. User account requirements (5 conditions per user)
3. Environment variable configuration
4. Kraken API credentials
5. User balances and tier eligibility

Usage:
    python diagnose_kraken_trading.py
"""

import os
import sys
import logging

# Setup minimal logging for this diagnostic
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s'
)
logger = logging.getLogger(__name__)

def check_env_var(name, expected_values=None, required=True):
    """
    Check if environment variable is set and has expected value.

    Args:
        name: Environment variable name
        expected_values: List of acceptable values (None = any non-empty value)
        required: If True, marks as error when missing

    Returns:
        tuple: (is_valid, actual_value, message)
    """
    value = os.getenv(name, "").strip()

    if not value:
        status = "❌ MISSING" if required else "⚪ NOT SET"
        return (False, None, f"{status}: {name}")

    if expected_values is None:
        # Any non-empty value is acceptable
        return (True, value, f"✅ SET: {name}={value}")

    if value in expected_values:
        return (True, value, f"✅ VALID: {name}={value}")
    else:
        return (False, value, f"❌ INVALID: {name}={value} (expected: {', '.join(expected_values)})")


def main():
    logger.info("=" * 80)
    logger.info("🔍 KRAKEN TRADING DIAGNOSTIC")
    logger.info("=" * 80)
    logger.info("")

    issues = []
    warnings = []

    # =========================================================================
    # SECTION 1: MASTER ACCOUNT REQUIREMENTS
    # =========================================================================
    logger.info("=" * 80)
    logger.info("📋 SECTION 1: MASTER ACCOUNT REQUIREMENTS")
    logger.info("=" * 80)
    logger.info("")
    logger.info("Copy trading requires ALL 4 master requirements:")
    logger.info("")

    # Requirement 1: PRO_MODE=true
    is_valid, value, msg = check_env_var("PRO_MODE", ["true", "1", "yes"])
    logger.info(f"   1. {msg}")
    if not is_valid:
        issues.append("PRO_MODE must be 'true', '1', or 'yes'")

    # Requirement 2: LIVE_TRADING=1
    is_valid, value, msg = check_env_var("LIVE_TRADING", ["1", "true", "True", "yes"])
    logger.info(f"   2. {msg}")
    if not is_valid:
        issues.append("LIVE_TRADING must be '1', 'true', or 'yes'")

    # Requirement 3: KRAKEN_MASTER_API_KEY
    is_valid, value, msg = check_env_var("KRAKEN_MASTER_API_KEY")
    logger.info(f"   3. {msg}")
    if not is_valid:
        issues.append("KRAKEN_MASTER_API_KEY is not set")
    elif value and len(value) < 20:
        warnings.append("KRAKEN_MASTER_API_KEY looks too short (possible truncation)")

    # Requirement 4: KRAKEN_MASTER_API_SECRET
    is_valid, value, msg = check_env_var("KRAKEN_MASTER_API_SECRET")
    logger.info(f"   4. {msg}")
    if not is_valid:
        issues.append("KRAKEN_MASTER_API_SECRET is not set")
    elif value and len(value) < 20:
        warnings.append("KRAKEN_MASTER_API_SECRET looks too short (possible truncation)")

    logger.info("")

    # =========================================================================
    # SECTION 2: USER ACCOUNT REQUIREMENTS
    # =========================================================================
    logger.info("=" * 80)
    logger.info("📋 SECTION 2: USER ACCOUNT REQUIREMENTS")
    logger.info("=" * 80)
    logger.info("")
    logger.info("Each user requires ALL 5 requirements:")
    logger.info("")

    # Requirement 1: PRO_MODE=true (same as master)
    logger.info(f"   1. PRO_MODE=true (same as master, already checked above)")

    # Requirement 2: COPY_TRADING_MODE=MASTER_FOLLOW
    is_valid, value, msg = check_env_var("COPY_TRADING_MODE", ["MASTER_FOLLOW"])
    logger.info(f"   2. {msg}")
    if not is_valid:
        current = os.getenv("COPY_TRADING_MODE", "INDEPENDENT")
        issues.append(f"COPY_TRADING_MODE is '{current}' but must be 'MASTER_FOLLOW'")

    # Requirement 3: STANDALONE=false (automatic when COPY_TRADING_MODE=MASTER_FOLLOW)
    logger.info(f"   3. ✅ STANDALONE=false (automatic when COPY_TRADING_MODE=MASTER_FOLLOW)")

    # Requirement 4 & 5: Balance and capital checks (can't check without connecting)
    logger.info(f"   4. ⚠️  TIER >= STARTER ($50 minimum) - Cannot verify without connecting")
    logger.info(f"   5. ⚠️  INITIAL_CAPITAL >= 100 - Cannot verify without connecting")

    logger.info("")

    # =========================================================================
    # SECTION 3: KRAKEN USER CREDENTIALS
    # =========================================================================
    logger.info("=" * 80)
    logger.info("📋 SECTION 3: KRAKEN USER CREDENTIALS")
    logger.info("=" * 80)
    logger.info("")

    # Check for common user credentials
    users_found = 0

    # User #1: Daivon
    daivon_key_valid, _, msg1 = check_env_var("KRAKEN_USER_DAIVON_API_KEY", required=False)
    daivon_secret_valid, _, msg2 = check_env_var("KRAKEN_USER_DAIVON_API_SECRET", required=False)

    if daivon_key_valid and daivon_secret_valid:
        logger.info(f"   ✅ User #1 (Daivon): Credentials configured")
        users_found += 1
    elif daivon_key_valid or daivon_secret_valid:
        logger.info(f"   ⚠️  User #1 (Daivon): Partial credentials (missing key or secret)")
        warnings.append("Daivon has partial Kraken credentials")
    else:
        logger.info(f"   ⚪ User #1 (Daivon): No credentials configured")

    # User #2: Tania
    tania_key_valid, _, msg1 = check_env_var("KRAKEN_USER_TANIA_API_KEY", required=False)
    tania_secret_valid, _, msg2 = check_env_var("KRAKEN_USER_TANIA_API_SECRET", required=False)

    if tania_key_valid and tania_secret_valid:
        logger.info(f"   ✅ User #2 (Tania): Credentials configured")
        users_found += 1
    elif tania_key_valid or tania_secret_valid:
        logger.info(f"   ⚠️  User #2 (Tania): Partial credentials (missing key or secret)")
        warnings.append("Tania has partial Kraken credentials")
    else:
        logger.info(f"   ⚪ User #2 (Tania): No credentials configured")

    logger.info("")
    logger.info(f"   📊 Total users with Kraken credentials: {users_found}")

    if users_found == 0:
        warnings.append("No Kraken user accounts configured - master will trade alone")

    logger.info("")

    # =========================================================================
    # SECTION 4: OTHER CONFIGURATION
    # =========================================================================
    logger.info("=" * 80)
    logger.info("📋 SECTION 4: OTHER CONFIGURATION")
    logger.info("=" * 80)
    logger.info("")

    # Check INITIAL_CAPITAL setting
    is_valid, value, msg = check_env_var("INITIAL_CAPITAL", required=False)
    if is_valid:
        logger.info(f"   ✅ INITIAL_CAPITAL={value}")
        if value not in ["auto", "LIVE"]:
            try:
                capital = float(value)
                if capital < 100:
                    warnings.append(f"INITIAL_CAPITAL={capital} < 100 may block SAVER+ tier users. Set INITIAL_CAPITAL=auto or ensure balances are in STARTER tier ($50-$99)")
            except ValueError:
                warnings.append(f"INITIAL_CAPITAL={value} is not a valid number or 'auto'")
    else:
        logger.info(f"   ⚪ INITIAL_CAPITAL not set (will default to 'auto')")

    # Check LIVE_CAPITAL_VERIFIED (safety switch)
    is_valid, value, msg = check_env_var("LIVE_CAPITAL_VERIFIED", required=False)
    if is_valid:
        if value.lower() in ['true', '1', 'yes']:
            logger.info(f"   ✅ LIVE_CAPITAL_VERIFIED={value} (live trading enabled)")
        else:
            logger.info(f"   ⚠️  LIVE_CAPITAL_VERIFIED={value} (live trading may be disabled)")
            warnings.append("LIVE_CAPITAL_VERIFIED is not 'true' - this may block live trading")
    else:
        logger.info(f"   ⚪ LIVE_CAPITAL_VERIFIED not set")

    logger.info("")

    # =========================================================================
    # SUMMARY AND RECOMMENDATIONS
    # =========================================================================
    logger.info("=" * 80)
    logger.info("📊 DIAGNOSTIC SUMMARY")
    logger.info("=" * 80)
    logger.info("")

    if not issues and not warnings:
        logger.info("✅ ALL CHECKS PASSED!")
        logger.info("")
        logger.info("Your configuration looks correct for Kraken copy trading.")
        logger.info("")
        logger.info("If trades still aren't executing, check:")
        logger.info("   1. Bot logs for connection errors")
        logger.info("   2. User balances are >= $50")
        logger.info("   3. Kraken API permissions (Query Funds, Create Orders, etc.)")
        logger.info("   4. Network connectivity to Kraken API")
    else:
        if issues:
            logger.info(f"❌ CRITICAL ISSUES FOUND: {len(issues)}")
            logger.info("")
            for i, issue in enumerate(issues, 1):
                logger.info(f"   {i}. {issue}")
            logger.info("")

        if warnings:
            logger.info(f"⚠️  WARNINGS: {len(warnings)}")
            logger.info("")
            for i, warning in enumerate(warnings, 1):
                logger.info(f"   {i}. {warning}")
            logger.info("")

        logger.info("=" * 80)
        logger.info("🔧 RECOMMENDED FIXES")
        logger.info("=" * 80)
        logger.info("")

        if any("PRO_MODE" in issue for issue in issues):
            logger.info("1. Set PRO_MODE=true")
            logger.info("   In Railway/Render dashboard:")
            logger.info("   • Add environment variable: PRO_MODE=true")
            logger.info("   • Click 'Save' and restart deployment")
            logger.info("")

        if any("LIVE_TRADING" in issue for issue in issues):
            logger.info("2. Set LIVE_TRADING=1")
            logger.info("   In Railway/Render dashboard:")
            logger.info("   • Add environment variable: LIVE_TRADING=1")
            logger.info("   • Click 'Save' and restart deployment")
            logger.info("")

        if any("COPY_TRADING_MODE" in issue for issue in issues):
            logger.info("3. Set COPY_TRADING_MODE=MASTER_FOLLOW")
            logger.info("   In Railway/Render dashboard:")
            logger.info("   • Add environment variable: COPY_TRADING_MODE=MASTER_FOLLOW")
            logger.info("   • Click 'Save' and restart deployment")
            logger.info("")

        if any("KRAKEN_MASTER" in issue for issue in issues):
            logger.info("4. Configure Kraken Master API credentials")
            logger.info("   In Railway/Render dashboard:")
            logger.info("   • Add environment variable: KRAKEN_MASTER_API_KEY=<your-key>")
            logger.info("   • Add environment variable: KRAKEN_MASTER_API_SECRET=<your-secret>")
            logger.info("   • Get these from: https://www.kraken.com/u/security/api")
            logger.info("   • Required permissions: Query Funds, Create Orders, Cancel Orders")
            logger.info("   • Click 'Save' and restart deployment")
            logger.info("")

    logger.info("=" * 80)
    logger.info("📚 DOCUMENTATION")
    logger.info("=" * 80)
    logger.info("")
    logger.info("For detailed setup instructions, see:")
    logger.info("   • COPY_TRADING_SETUP.md - Copy trading configuration")
    logger.info("   • KRAKEN_TRADING_GUIDE.md - Kraken-specific setup")
    logger.info("   • .env.example - All environment variables with descriptions")
    logger.info("")
    logger.info("=" * 80)

    # Exit with error code if issues found
    if issues:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("\n\n🛑 Diagnostic interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error("=" * 80)
        logger.error("❌ DIAGNOSTIC ERROR")
        logger.error("=" * 80)
        logger.error(f"An unexpected error occurred: {e}")
        logger.error("")
        logger.error("Please report this error with the following details:")
        logger.error(f"Error type: {type(e).__name__}")
        logger.error(f"Error message: {str(e)}")
        logger.error("=" * 80)
        sys.exit(1)
