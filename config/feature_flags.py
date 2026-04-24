"""
NIJA Feature Flags Configuration

This module defines all feature flags for the NIJA trading bot.
Feature flags allow safe progressive rollout and easy toggling of features.

Following Option A (Recommended):
- Define flags globally and explicitly
- Import where needed: from config.feature_flags import PROFIT_CONFIRMATION_AVAILABLE
- Keeps flags explicit, testable, and toggleable

Author: NIJA Trading Systems
Date: February 6, 2026
"""

# ============================================================================
# PROFIT CONFIRMATION FEATURE FLAG
# ============================================================================

# Control whether profit confirmation logging is enabled
# When True: Track and log profit confirmations with detailed metrics
# When False: Skip profit confirmation tracking (lightweight mode)
#
# This flag can be controlled via environment variable:
#   FEATURE_PROFIT_CONFIRMATION=true
#
# Default: True (recommended for production trading)
PROFIT_CONFIRMATION_AVAILABLE = True


# ============================================================================
# FUTURE FEATURE FLAGS
# ============================================================================

# Add additional feature flags here following the same pattern:
# FEATURE_NAME_AVAILABLE = True/False
