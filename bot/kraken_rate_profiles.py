"""
Kraken-Specific Rate Limiting Profiles

Provides separate API rate budgets for entry (trading) vs exit (monitoring) operations
and low-capital mode for small accounts to minimize API usage costs.

Kraken API Rate Limits (as of Jan 2026):
- Private endpoints: Counter-based system (15-20 points per minute)
- AddOrder: 0 points (can spam trades)
- Balance: 1 point
- TradeBalance: 1 point
- QueryOrders: 1 point
- CancelOrder: 0 points

Strategy:
- Entry operations (AddOrder): No rate limiting needed (0 points)
- Exit operations (Balance checks, queries): Conservative rate limiting
- Low-capital mode: Minimal Balance checks to save API budget

Author: NIJA Trading Systems
Version: 1.0
Date: January 23, 2026
"""

import logging
from typing import Dict, Optional
from enum import Enum

logger = logging.getLogger("nija.kraken_rate_profiles")


class KrakenRateMode(Enum):
    """Kraken API rate limiting modes"""
    STANDARD = "standard"           # Normal mode for larger accounts ($100+)
    LOW_CAPITAL = "low_capital"     # Conservative mode for small accounts ($20-$100)
    AGGRESSIVE = "aggressive"        # High-frequency mode for professional accounts ($1000+)


class KrakenAPICategory(Enum):
    """Categories of Kraken API operations"""
    ENTRY = "entry"           # Trade entry operations (AddOrder)
    EXIT = "exit"             # Trade exit operations (AddOrder for sells)
    MONITORING = "monitoring" # Balance checks, order queries
    QUERY = "query"           # Order status, trade history


# ============================================================================
# KRAKEN API BUDGET PROFILES
# ============================================================================

# Kraken API counter system:
# - Counter increases with each call (based on endpoint cost)
# - Counter decreases over time
# - If counter exceeds limit, API returns 429 (rate limit exceeded)
# - Tier 0 (default): 15-20 points/minute recovery rate

KRAKEN_RATE_PROFILES = {
    # STANDARD MODE: Balanced for accounts $100-$1000
    # - Suitable for copy trading with moderate position counts
    # - Balances API efficiency with real-time monitoring
    KrakenRateMode.STANDARD: {
        'name': 'Standard Rate Profile',
        'description': 'Balanced mode for $100-$1000 accounts',
        'min_account_balance': 100.0,
        'max_account_balance': 1000.0,
        
        # Entry operations (AddOrder buy): 0 points
        # Can execute rapidly without API cost
        'entry': {
            'min_interval_seconds': 2.0,  # 2 seconds between entry orders
            'max_per_minute': 30,          # Up to 30 entries/minute
            'api_cost_points': 0,          # Free on Kraken
        },
        
        # Exit operations (AddOrder sell): 0 points
        # Can execute rapidly without API cost
        'exit': {
            'min_interval_seconds': 2.0,  # 2 seconds between exit orders
            'max_per_minute': 30,          # Up to 30 exits/minute
            'api_cost_points': 0,          # Free on Kraken
        },
        
        # Monitoring operations (Balance, TradeBalance): 1 point each
        # These consume API budget, so rate limit conservatively
        'monitoring': {
            'min_interval_seconds': 10.0,  # 10 seconds between balance checks
            'max_per_minute': 6,            # Max 6 balance checks/minute
            'api_cost_points': 1,           # 1 point per check
        },
        
        # Query operations (QueryOrders, OpenOrders): 1-2 points
        # Conservative rate limiting for order queries
        'query': {
            'min_interval_seconds': 5.0,   # 5 seconds between queries
            'max_per_minute': 12,           # Max 12 queries/minute
            'api_cost_points': 1,           # 1-2 points per query
        },
        
        # Overall API budget management
        'budget': {
            'total_points_per_minute': 15,  # Kraken Tier 0 limit
            'reserve_points': 3,             # Keep 3 points reserve
            'monitoring_budget_pct': 0.40,   # 40% of budget for monitoring
            'query_budget_pct': 0.60,        # 60% of budget for queries
        },
    },
    
    # LOW-CAPITAL MODE: Conservative for small accounts $20-$100
    # - Minimizes API calls to reduce "overhead cost"
    # - Prioritizes trade execution over frequent monitoring
    # - Suitable for accounts where API costs matter
    KrakenRateMode.LOW_CAPITAL: {
        'name': 'Low-Capital Rate Profile',
        'description': 'Conservative mode for $20-$100 small accounts',
        'min_account_balance': 20.0,
        'max_account_balance': 100.0,
        
        # Entry operations (AddOrder buy): 0 points
        # No rate limiting needed (free on Kraken)
        'entry': {
            'min_interval_seconds': 3.0,  # 3 seconds between entry orders
            'max_per_minute': 20,          # Up to 20 entries/minute
            'api_cost_points': 0,          # Free on Kraken
        },
        
        # Exit operations (AddOrder sell): 0 points
        # No rate limiting needed (free on Kraken)
        'exit': {
            'min_interval_seconds': 3.0,  # 3 seconds between exit orders
            'max_per_minute': 20,          # Up to 20 exits/minute
            'api_cost_points': 0,          # Free on Kraken
        },
        
        # Monitoring operations (Balance, TradeBalance): 1 point each
        # HEAVILY rate limited to save API budget for small accounts
        'monitoring': {
            'min_interval_seconds': 30.0,  # 30 seconds between balance checks
            'max_per_minute': 2,            # Max 2 balance checks/minute
            'api_cost_points': 1,           # 1 point per check
        },
        
        # Query operations (QueryOrders, OpenOrders): 1-2 points
        # Conservative queries for small accounts
        'query': {
            'min_interval_seconds': 15.0,  # 15 seconds between queries
            'max_per_minute': 4,            # Max 4 queries/minute
            'api_cost_points': 1,           # 1-2 points per query
        },
        
        # Overall API budget management
        'budget': {
            'total_points_per_minute': 15,  # Kraken Tier 0 limit
            'reserve_points': 5,             # Keep 5 points reserve (33%)
            'monitoring_budget_pct': 0.20,   # 20% of budget for monitoring
            'query_budget_pct': 0.80,        # 80% of budget for queries
        },
        
        # Small account optimizations
        'optimizations': {
            'cache_balance': True,          # Cache balance for 60s
            'cache_ttl_seconds': 60,        # 60 second cache
            'skip_pre_trade_balance': False, # Still check balance before trades
            'batch_queries': True,           # Batch multiple queries when possible
        },
    },
    
    # AGGRESSIVE MODE: High-frequency for professional accounts $1000+
    # - Maximum API utilization for active trading
    # - Real-time monitoring and rapid execution
    # - Suitable for accounts with high volume
    KrakenRateMode.AGGRESSIVE: {
        'name': 'Aggressive Rate Profile',
        'description': 'High-frequency mode for $1000+ professional accounts',
        'min_account_balance': 1000.0,
        'max_account_balance': None,  # No upper limit
        
        # Entry operations (AddOrder buy): 0 points
        # Maximum speed for trade execution
        'entry': {
            'min_interval_seconds': 1.0,  # 1 second between entry orders
            'max_per_minute': 60,          # Up to 60 entries/minute
            'api_cost_points': 0,          # Free on Kraken
        },
        
        # Exit operations (AddOrder sell): 0 points
        # Maximum speed for trade execution
        'exit': {
            'min_interval_seconds': 1.0,  # 1 second between exit orders
            'max_per_minute': 60,          # Up to 60 exits/minute
            'api_cost_points': 0,          # Free on Kraken
        },
        
        # Monitoring operations (Balance, TradeBalance): 1 point each
        # Frequent monitoring for real-time tracking
        'monitoring': {
            'min_interval_seconds': 5.0,   # 5 seconds between balance checks
            'max_per_minute': 12,           # Max 12 balance checks/minute
            'api_cost_points': 1,           # 1 point per check
        },
        
        # Query operations (QueryOrders, OpenOrders): 1-2 points
        # Frequent queries for active position management
        'query': {
            'min_interval_seconds': 3.0,   # 3 seconds between queries
            'max_per_minute': 20,           # Max 20 queries/minute
            'api_cost_points': 1,           # 1-2 points per query
        },
        
        # Overall API budget management
        'budget': {
            'total_points_per_minute': 15,  # Kraken Tier 0 limit
            'reserve_points': 2,             # Keep 2 points reserve
            'monitoring_budget_pct': 0.50,   # 50% of budget for monitoring
            'query_budget_pct': 0.50,        # 50% of budget for queries
        },
    },
}


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_kraken_rate_profile(
    mode: KrakenRateMode = KrakenRateMode.STANDARD,
    account_balance: Optional[float] = None
) -> Dict:
    """
    Get Kraken rate limiting profile for the specified mode.
    
    Args:
        mode: Rate limiting mode (STANDARD, LOW_CAPITAL, AGGRESSIVE)
        account_balance: Optional account balance to auto-select mode
        
    Returns:
        Dict with rate limiting configuration
    """
    # Auto-select mode based on account balance if provided
    if account_balance is not None:
        if account_balance < 100.0:
            mode = KrakenRateMode.LOW_CAPITAL
            logger.info(f"Auto-selected LOW_CAPITAL mode for ${account_balance:.2f} balance")
        elif account_balance < 1000.0:
            mode = KrakenRateMode.STANDARD
            logger.info(f"Auto-selected STANDARD mode for ${account_balance:.2f} balance")
        else:
            mode = KrakenRateMode.AGGRESSIVE
            logger.info(f"Auto-selected AGGRESSIVE mode for ${account_balance:.2f} balance")
    
    profile = KRAKEN_RATE_PROFILES.get(mode, KRAKEN_RATE_PROFILES[KrakenRateMode.STANDARD])
    logger.debug(f"Using Kraken rate profile: {profile['name']}")
    return profile


def get_operation_rate_limit(
    category: KrakenAPICategory,
    mode: KrakenRateMode = KrakenRateMode.STANDARD
) -> Dict:
    """
    Get rate limit configuration for a specific API operation category.
    
    Args:
        category: API operation category (ENTRY, EXIT, MONITORING, QUERY)
        mode: Rate limiting mode
        
    Returns:
        Dict with rate limit settings for the category
    """
    profile = KRAKEN_RATE_PROFILES.get(mode, KRAKEN_RATE_PROFILES[KrakenRateMode.STANDARD])
    category_key = category.value
    
    if category_key not in profile:
        logger.warning(f"Category {category_key} not found in profile, using monitoring defaults")
        category_key = 'monitoring'
    
    return profile[category_key]


def calculate_min_interval(
    category: KrakenAPICategory,
    mode: KrakenRateMode = KrakenRateMode.STANDARD
) -> float:
    """
    Calculate minimum interval between API calls for a category.
    
    Args:
        category: API operation category
        mode: Rate limiting mode
        
    Returns:
        Minimum seconds between calls
    """
    limits = get_operation_rate_limit(category, mode)
    return limits.get('min_interval_seconds', 5.0)


def get_category_for_method(method: str) -> KrakenAPICategory:
    """
    Determine API category for a Kraken API method.
    
    Args:
        method: Kraken API method name (e.g., 'AddOrder', 'Balance')
        
    Returns:
        KrakenAPICategory enum value
    """
    # Entry operations (buy orders)
    if method == 'AddOrder':
        # Note: We can't distinguish buy vs sell here without params
        # Caller should specify category explicitly
        return KrakenAPICategory.ENTRY
    
    # Monitoring operations
    if method in ['Balance', 'TradeBalance']:
        return KrakenAPICategory.MONITORING
    
    # Query operations
    if method in ['QueryOrders', 'OpenOrders', 'ClosedOrders', 'TradesHistory']:
        return KrakenAPICategory.QUERY
    
    # Default to monitoring (most conservative)
    logger.debug(f"Unknown method '{method}', defaulting to MONITORING category")
    return KrakenAPICategory.MONITORING


def should_cache_balance(mode: KrakenRateMode = KrakenRateMode.STANDARD) -> bool:
    """
    Check if balance caching is enabled for the mode.
    
    Args:
        mode: Rate limiting mode
        
    Returns:
        True if balance should be cached
    """
    profile = KRAKEN_RATE_PROFILES.get(mode, KRAKEN_RATE_PROFILES[KrakenRateMode.STANDARD])
    
    # Check if optimizations section exists
    optimizations = profile.get('optimizations', {})
    return optimizations.get('cache_balance', False)


def get_cache_ttl(mode: KrakenRateMode = KrakenRateMode.STANDARD) -> int:
    """
    Get cache TTL for the mode.
    
    Args:
        mode: Rate limiting mode
        
    Returns:
        Cache TTL in seconds
    """
    profile = KRAKEN_RATE_PROFILES.get(mode, KRAKEN_RATE_PROFILES[KrakenRateMode.STANDARD])
    optimizations = profile.get('optimizations', {})
    return optimizations.get('cache_ttl_seconds', 45)


# ============================================================================
# SUMMARY FUNCTION FOR LOGGING
# ============================================================================

def get_rate_profile_summary(mode: KrakenRateMode = KrakenRateMode.STANDARD) -> str:
    """
    Get human-readable summary of rate profile settings.
    
    Args:
        mode: Rate limiting mode
        
    Returns:
        Formatted string with profile details
    """
    profile = KRAKEN_RATE_PROFILES.get(mode, KRAKEN_RATE_PROFILES[KrakenRateMode.STANDARD])
    
    return f"""
╔══════════════════════════════════════════════════════════════════════════╗
║              KRAKEN RATE LIMITING PROFILE: {mode.value.upper()}
╚══════════════════════════════════════════════════════════════════════════╝

📊 PROFILE: {profile['name']}
   {profile['description']}
   Account Range: ${profile['min_account_balance']:.0f}+

⚡ ENTRY OPERATIONS (Buy Orders):
   • Min Interval: {profile['entry']['min_interval_seconds']:.1f}s
   • Max Per Minute: {profile['entry']['max_per_minute']} trades
   • API Cost: {profile['entry']['api_cost_points']} points (FREE)

🚪 EXIT OPERATIONS (Sell Orders):
   • Min Interval: {profile['exit']['min_interval_seconds']:.1f}s
   • Max Per Minute: {profile['exit']['max_per_minute']} trades
   • API Cost: {profile['exit']['api_cost_points']} points (FREE)

📈 MONITORING OPERATIONS (Balance Checks):
   • Min Interval: {profile['monitoring']['min_interval_seconds']:.1f}s
   • Max Per Minute: {profile['monitoring']['max_per_minute']} checks
   • API Cost: {profile['monitoring']['api_cost_points']} point(s)

🔍 QUERY OPERATIONS (Order Status):
   • Min Interval: {profile['query']['min_interval_seconds']:.1f}s
   • Max Per Minute: {profile['query']['max_per_minute']} queries
   • API Cost: {profile['query']['api_cost_points']} point(s)

💰 API BUDGET:
   • Total Budget: {profile['budget']['total_points_per_minute']} points/minute
   • Reserve: {profile['budget']['reserve_points']} points
   • Monitoring: {profile['budget']['monitoring_budget_pct']*100:.0f}%
   • Queries: {profile['budget']['query_budget_pct']*100:.0f}%

═══════════════════════════════════════════════════════════════════════════

Key Benefits:
✅ Separate entry/exit budgets (AddOrder is FREE on Kraken)
✅ Conservative monitoring limits (save API points)
✅ Optimized for account size and trading style
"""


if __name__ == "__main__":
    # Print all rate profiles
    print("\n" + "="*80)
    print("KRAKEN RATE LIMITING PROFILES")
    print("="*80)
    
    for mode in KrakenRateMode:
        print(get_rate_profile_summary(mode))
        print("\n")
    
    # Test auto-selection
    print("\n" + "="*80)
    print("AUTO-SELECTION TESTS")
    print("="*80)
    
    test_balances = [50.0, 150.0, 1500.0]
    for balance in test_balances:
        profile = get_kraken_rate_profile(account_balance=balance)
        print(f"\nBalance: ${balance:.2f} → {profile['name']}")
        print(f"  Entry interval: {profile['entry']['min_interval_seconds']:.1f}s")
        print(f"  Monitoring interval: {profile['monitoring']['min_interval_seconds']:.1f}s")
