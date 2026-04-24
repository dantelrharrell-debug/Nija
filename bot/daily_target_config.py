"""
NIJA Daily Target Configuration
Optimize settings for consistent $25/day profit target

This module calculates optimal position sizing, trade frequency,
and risk parameters to achieve a daily profit target while managing risk.

Key Features:
- Dynamic position sizing based on account balance
- Realistic trade frequency calculations
- Fee-aware profit targets
- Multi-exchange optimization support

Author: NIJA Trading Systems
Version: 1.0
Date: December 30, 2025
"""

import logging
from typing import Dict, Tuple

logger = logging.getLogger("nija.daily_target")

# ============================================================================
# DAILY PROFIT TARGET CONFIGURATION
# ============================================================================

# Target daily profit in USD
DAILY_PROFIT_TARGET_USD = 25.00

# Minimum account balance to attempt $25/day target
# Below this, target is proportionally reduced
MIN_BALANCE_FOR_TARGET = 100.00

# Expected win rate (conservative estimate)
EXPECTED_WIN_RATE = 0.60  # 60% win rate

# Average profit per winning trade (after fees)
# Conservative: 2.0% net profit per win
AVG_WIN_PROFIT_PCT = 0.020  # 2.0%

# Average loss per losing trade (after fees)
# Updated Jan 28, 2026: Tightened to -0.6% target (was -1.0%)
# Aligns with ENHANCED_STRATEGY_GUIDE.md line 393: "Keep under -0.6% per losing trade"
# Conservative: 0.6% loss (tighter stops for better capital preservation)
AVG_LOSS_PCT = 0.006  # 0.6% (improved from 1.0% for better capital preservation)

# Maximum trades per day (quality over quantity)
MAX_TRADES_PER_DAY = 20

# Minimum trades per day to hit target
MIN_TRADES_PER_DAY = 5

# ============================================================================
# POSITION SIZING FOR DAILY TARGET
# ============================================================================

def calculate_optimal_position_size(
    account_balance: float,
    daily_target_usd: float = DAILY_PROFIT_TARGET_USD,
    win_rate: float = EXPECTED_WIN_RATE,
    avg_win_pct: float = AVG_WIN_PROFIT_PCT,
    avg_loss_pct: float = AVG_LOSS_PCT,
    max_trades: int = MAX_TRADES_PER_DAY
) -> Dict:
    """
    Calculate optimal position sizing to achieve daily profit target.

    Formula:
    Daily P&L = (Wins × Avg Win) - (Losses × Avg Loss)

    Where:
    - Wins = Total Trades × Win Rate
    - Losses = Total Trades × (1 - Win Rate)

    Args:
        account_balance: Current account balance in USD
        daily_target_usd: Target daily profit in USD
        win_rate: Expected win rate (0-1)
        avg_win_pct: Average profit per win (as decimal)
        avg_loss_pct: Average loss per loss (as decimal)
        max_trades: Maximum trades per day

    Returns:
        Dict with:
        - position_size_usd: Recommended position size in USD
        - position_size_pct: Recommended position size as % of account
        - trades_needed: Number of trades needed to hit target
        - expected_daily_pnl: Expected daily P&L in USD
        - risk_per_trade: Risk per trade in USD
        - achievable: Whether target is achievable
    """

    # Calculate expected P&L per trade
    expected_pnl_per_trade_pct = (win_rate * avg_win_pct) - ((1 - win_rate) * avg_loss_pct)

    # Calculate trades needed to hit target
    if expected_pnl_per_trade_pct <= 0:
        logger.warning(f"❌ Negative expected value: {expected_pnl_per_trade_pct:.4f}")
        return {
            'position_size_usd': 0,
            'position_size_pct': 0,
            'trades_needed': 0,
            'expected_daily_pnl': 0,
            'risk_per_trade': 0,
            'achievable': False,
            'reason': 'Negative expected value - adjust win rate or profit targets'
        }

    # Position size needed per trade to hit daily target
    # Daily Target = Trades × Position Size × Expected P&L %
    # Position Size = Daily Target / (Trades × Expected P&L %)

    trades_needed = MIN_TRADES_PER_DAY
    position_size_usd = daily_target_usd / (trades_needed * expected_pnl_per_trade_pct)

    # Adjust if position size exceeds account balance
    max_position_size = account_balance * 0.50  # Max 50% per trade for safety

    if position_size_usd > max_position_size:
        # Need more trades with smaller positions
        position_size_usd = max_position_size
        trades_needed = daily_target_usd / (position_size_usd * expected_pnl_per_trade_pct)
        trades_needed = int(trades_needed) + 1  # Round up

    if trades_needed > max_trades:
        # Target not achievable with current parameters
        trades_needed = max_trades
        position_size_usd = min(max_position_size, daily_target_usd / (trades_needed * expected_pnl_per_trade_pct))
        expected_daily_pnl = position_size_usd * expected_pnl_per_trade_pct * trades_needed
        achievable = False
        reason = f"Need {trades_needed} trades but limited to {max_trades}/day"
    else:
        expected_daily_pnl = daily_target_usd
        achievable = True
        reason = "Target achievable"

    # Ensure minimum position size
    min_position_usd = 10.00  # $10 minimum for fee efficiency
    if position_size_usd < min_position_usd:
        position_size_usd = min_position_usd
        expected_daily_pnl = position_size_usd * expected_pnl_per_trade_pct * trades_needed
        if expected_daily_pnl < daily_target_usd:
            achievable = False
            reason = f"Account too small. Expected ${expected_daily_pnl:.2f}/day vs ${daily_target_usd}/day target"

    position_size_pct = position_size_usd / account_balance if account_balance > 0 else 0
    risk_per_trade = position_size_usd * avg_loss_pct

    result = {
        'position_size_usd': round(position_size_usd, 2),
        'position_size_pct': round(position_size_pct, 4),
        'trades_needed': trades_needed,
        'expected_daily_pnl': round(expected_daily_pnl, 2),
        'risk_per_trade': round(risk_per_trade, 2),
        'achievable': achievable,
        'reason': reason,
        'expected_pnl_per_trade_pct': round(expected_pnl_per_trade_pct * 100, 2),
        'max_daily_loss': round(risk_per_trade * trades_needed * (1 - win_rate), 2)
    }

    return result


def get_scaled_daily_target(account_balance: float) -> float:
    """
    Scale daily profit target based on account balance.

    For small accounts, targeting $25/day may be unrealistic.
    This function scales the target proportionally.

    Args:
        account_balance: Current account balance

    Returns:
        Scaled daily profit target in USD
    """
    if account_balance >= MIN_BALANCE_FOR_TARGET:
        return DAILY_PROFIT_TARGET_USD

    # Scale proportionally for smaller accounts
    # e.g., $50 account → $12.50/day target
    scaled_target = (account_balance / MIN_BALANCE_FOR_TARGET) * DAILY_PROFIT_TARGET_USD

    # Minimum $1/day target
    return max(1.00, scaled_target)


def get_optimal_settings_for_balance(account_balance: float) -> Dict:
    """
    Get complete optimal settings for current account balance.

    Args:
        account_balance: Current account balance in USD

    Returns:
        Dict with all optimal settings for achieving daily target
    """
    # Get scaled target for this balance
    daily_target = get_scaled_daily_target(account_balance)

    # Calculate optimal position sizing
    sizing = calculate_optimal_position_size(
        account_balance=account_balance,
        daily_target_usd=daily_target
    )

    # Determine max positions based on position size
    if sizing['position_size_pct'] > 0.30:
        max_positions = 2  # Large positions → fewer concurrent
    elif sizing['position_size_pct'] > 0.20:
        max_positions = 3
    elif sizing['position_size_pct'] > 0.10:
        max_positions = 5
    else:
        max_positions = 8  # Standard max

    # Determine scan frequency (more frequent for higher targets)
    if daily_target >= 25:
        scan_interval_seconds = 180  # 3 minutes - more aggressive
    elif daily_target >= 10:
        scan_interval_seconds = 240  # 4 minutes
    else:
        scan_interval_seconds = 300  # 5 minutes - conservative

    return {
        'account_balance': account_balance,
        'daily_target_usd': daily_target,
        'position_size_usd': sizing['position_size_usd'],
        'position_size_pct': sizing['position_size_pct'],
        'max_positions': max_positions,
        'trades_per_day': sizing['trades_needed'],
        'scan_interval_seconds': scan_interval_seconds,
        'expected_daily_pnl': sizing['expected_daily_pnl'],
        'risk_per_trade': sizing['risk_per_trade'],
        'max_daily_loss': sizing['max_daily_loss'],
        'achievable': sizing['achievable'],
        'reason': sizing['reason']
    }


def print_daily_target_summary(account_balance: float) -> None:
    """
    Print summary of daily target configuration.

    Args:
        account_balance: Current account balance
    """
    settings = get_optimal_settings_for_balance(account_balance)

    print("\n" + "="*70)
    print("NIJA DAILY PROFIT TARGET OPTIMIZATION")
    print("="*70)
    print(f"\n💰 ACCOUNT STATUS:")
    print(f"   Current Balance: ${account_balance:.2f}")
    print(f"   Daily Target: ${settings['daily_target_usd']:.2f}")
    print(f"   Achievable: {'✅ YES' if settings['achievable'] else '❌ NO'}")
    print(f"   Reason: {settings['reason']}")

    print(f"\n📊 POSITION SIZING:")
    print(f"   Position Size: ${settings['position_size_usd']:.2f} ({settings['position_size_pct']*100:.1f}%)")
    print(f"   Max Positions: {settings['max_positions']}")
    print(f"   Risk per Trade: ${settings['risk_per_trade']:.2f}")
    print(f"   Max Daily Loss: ${settings['max_daily_loss']:.2f}")

    print(f"\n🎯 TRADING PLAN:")
    print(f"   Trades Needed: {settings['trades_per_day']} per day")
    print(f"   Scan Interval: {settings['scan_interval_seconds']}s")
    print(f"   Expected Daily P&L: ${settings['expected_daily_pnl']:.2f}")

    print(f"\n📈 PERFORMANCE METRICS:")
    print(f"   Win Rate Needed: {EXPECTED_WIN_RATE*100:.0f}%")
    print(f"   Avg Win: {AVG_WIN_PROFIT_PCT*100:.1f}%")
    print(f"   Avg Loss: {AVG_LOSS_PCT*100:.1f}%")

    if not settings['achievable']:
        print(f"\n⚠️  RECOMMENDATIONS:")
        if account_balance < MIN_BALANCE_FOR_TARGET:
            print(f"   • Fund account to ${MIN_BALANCE_FOR_TARGET:.0f}+ for full $25/day target")
        print(f"   • Current scaled target: ${settings['daily_target_usd']:.2f}/day")
        print(f"   • Focus on consistent profitability first")
        print(f"   • Compound profits to grow account")

    print("="*70 + "\n")


# ============================================================================
# CONFIGURATION EXPORT
# ============================================================================

def get_daily_target_config(account_balance: float) -> Dict:
    """
    Export configuration for integration with main trading system.

    Args:
        account_balance: Current account balance

    Returns:
        Config dict compatible with apex_config.py
    """
    settings = get_optimal_settings_for_balance(account_balance)

    return {
        'DAILY_TARGET': {
            'enabled': True,
            'target_usd': settings['daily_target_usd'],
            'position_size_pct': settings['position_size_pct'],
            'position_size_usd': settings['position_size_usd'],
            'max_positions': settings['max_positions'],
            'trades_per_day': settings['trades_per_day'],
            'scan_interval_seconds': settings['scan_interval_seconds'],
        },
        'RISK_CONFIG_OVERRIDE': {
            'max_risk_per_trade': settings['position_size_pct'] * AVG_LOSS_PCT,
            'max_daily_loss': settings['max_daily_loss'] / account_balance if account_balance > 0 else 0.05,
        }
    }


if __name__ == "__main__":
    # Test with different account balances
    test_balances = [25, 50, 100, 200, 500, 1000]

    for balance in test_balances:
        print_daily_target_summary(balance)
        print()
