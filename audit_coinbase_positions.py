#!/usr/bin/env python3
"""
Verify No Losing Coinbase Trades
=================================

This script checks all open Coinbase positions and verifies that:
1. No positions are currently at a loss beyond stop-loss threshold
2. No positions have been held longer than max hold time
3. Aggressive sell logic is working correctly

Based on current strategy (AGGRESSIVE_SELL_FIX_JAN_13_2026.md):
- Stop loss: -1.0%
- Max hold time: 8 hours
- Profit targets: 1.5%, 1.2%, 1.0%
- Warning at: -0.7% loss, 4 hours hold

Usage:
    python3 verify_no_losing_coinbase_trades.py
"""

import os
import sys
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Strategy thresholds (from trading_strategy.py)
STOP_LOSS_THRESHOLD = -1.0  # -1.0% loss triggers exit
STOP_LOSS_WARNING = -0.7    # -0.7% triggers warning
MAX_POSITION_HOLD_HOURS = 8  # 8 hours max hold
STALE_POSITION_WARNING_HOURS = 4  # 4 hours triggers warning
PROFIT_TARGETS = [1.5, 1.2, 1.0]  # Profit targets in %


def print_banner():
    """Print script banner"""
    print()
    print("=" * 80)
    print("COINBASE LOSING TRADES VERIFICATION".center(80))
    print("=" * 80)
    print()
    print("Checking for positions that should have been sold...")
    print()


def check_coinbase_credentials():
    """Check if Coinbase credentials are configured"""
    api_key = os.getenv("COINBASE_API_KEY", "").strip()
    api_secret = os.getenv("COINBASE_API_SECRET", "").strip()
    
    if not api_key or not api_secret:
        print("❌ ERROR: Coinbase credentials not configured")
        print()
        print("   Set these environment variables:")
        print("   - COINBASE_API_KEY")
        print("   - COINBASE_API_SECRET")
        print()
        return False
    
    print(f"✅ Coinbase credentials detected (Key: {len(api_key)} chars)")
    return True


def get_coinbase_positions():
    """
    Get all open Coinbase positions
    
    Returns:
        List of position dicts with symbol, size, entry_price, current_price, etc.
    """
    try:
        from broker_manager import BrokerType, AccountType, MultiBrokerManager
        
        print("📊 Connecting to Coinbase...")
        
        # Initialize broker manager
        manager = MultiBrokerManager()
        
        # Add Coinbase master broker
        coinbase = manager.add_broker(
            broker_type=BrokerType.COINBASE,
            account_type=AccountType.MASTER,
            user_id=None
        )
        
        if not coinbase:
            print("❌ Failed to initialize Coinbase broker")
            return None
        
        # Get positions
        positions = coinbase.get_all_positions()
        
        if positions is None:
            print("⚠️  Could not retrieve positions (API error)")
            return None
        
        print(f"✅ Retrieved {len(positions)} open positions")
        return positions
        
    except ImportError as e:
        print(f"❌ Import error: {e}")
        print("   Make sure you're running from the repository root")
        return None
    except Exception as e:
        print(f"❌ Error getting positions: {e}")
        import traceback
        traceback.print_exc()
        return None


def calculate_pnl_percent(entry_price: float, current_price: float) -> float:
    """Calculate P&L percentage"""
    if not entry_price or entry_price == 0:
        return 0.0
    return ((current_price - entry_price) / entry_price) * 100


def calculate_position_age_hours(position: Dict) -> Optional[float]:
    """
    Calculate how long position has been held
    
    Args:
        position: Position dict with 'entry_time' or 'created_at'
        
    Returns:
        Hours held, or None if unknown
    """
    # Try different timestamp fields
    timestamp = position.get('entry_time') or position.get('created_at') or position.get('timestamp')
    
    if not timestamp:
        return None
    
    # Parse timestamp (handle both datetime objects and strings)
    if isinstance(timestamp, datetime):
        entry_time = timestamp
    elif isinstance(timestamp, str):
        try:
            # Try ISO format
            entry_time = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        except ValueError:
            try:
                # Try other common formats
                entry_time = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                return None
    else:
        # Unix timestamp
        try:
            entry_time = datetime.fromtimestamp(timestamp)
        except (ValueError, OSError):
            return None
    
    # Calculate age
    age = datetime.now() - entry_time.replace(tzinfo=None)
    return age.total_seconds() / 3600  # Convert to hours


def verify_position(position: Dict) -> Dict:
    """
    Verify a single position against strategy rules
    
    Returns:
        Dict with verification results
    """
    symbol = position.get('symbol', 'UNKNOWN')
    entry_price = position.get('entry_price', 0) or position.get('avg_entry_price', 0)
    current_price = position.get('current_price', 0)
    size = position.get('size', 0) or position.get('quantity', 0)
    size_usd = position.get('size_usd', 0) or position.get('value_usd', 0)
    
    result = {
        'symbol': symbol,
        'status': 'OK',
        'issues': [],
        'warnings': [],
        'entry_price': entry_price,
        'current_price': current_price,
        'pnl_percent': 0,
        'age_hours': None
    }
    
    # Calculate P&L
    if entry_price and current_price:
        pnl_percent = calculate_pnl_percent(entry_price, current_price)
        result['pnl_percent'] = pnl_percent
        
        # Check stop loss threshold
        if pnl_percent <= STOP_LOSS_THRESHOLD:
            result['status'] = 'VIOLATION'
            result['issues'].append(
                f"STOP LOSS VIOLATION: {pnl_percent:.2f}% (threshold: {STOP_LOSS_THRESHOLD}%)"
            )
        elif pnl_percent <= STOP_LOSS_WARNING:
            result['warnings'].append(
                f"Approaching stop loss: {pnl_percent:.2f}% (warning: {STOP_LOSS_WARNING}%)"
            )
        
        # Check profit targets
        for target in PROFIT_TARGETS:
            if pnl_percent >= target:
                result['warnings'].append(
                    f"Hit profit target: {pnl_percent:.2f}% >= {target}%"
                )
                break  # Only report highest hit target
    
    # Calculate position age
    age_hours = calculate_position_age_hours(position)
    if age_hours is not None:
        result['age_hours'] = age_hours
        
        # Check max hold time
        if age_hours >= MAX_POSITION_HOLD_HOURS:
            result['status'] = 'VIOLATION'
            result['issues'].append(
                f"MAX HOLD TIME VIOLATION: {age_hours:.1f}h (max: {MAX_POSITION_HOLD_HOURS}h)"
            )
        elif age_hours >= STALE_POSITION_WARNING_HOURS:
            result['warnings'].append(
                f"Position aging: {age_hours:.1f}h (warning: {STALE_POSITION_WARNING_HOURS}h)"
            )
    
    return result


def print_position_report(result: Dict):
    """Print detailed position report"""
    symbol = result['symbol']
    status = result['status']
    pnl = result['pnl_percent']
    age = result['age_hours']
    
    # Status icon
    if status == 'VIOLATION':
        icon = "🚨"
        color = "RED"
    elif result['warnings']:
        icon = "⚠️ "
        color = "YELLOW"
    else:
        icon = "✅"
        color = "GREEN"
    
    print(f"{icon} {symbol}")
    
    # P&L
    if pnl != 0:
        pnl_sign = "+" if pnl >= 0 else ""
        print(f"   P&L: {pnl_sign}{pnl:.2f}%")
    
    # Age
    if age is not None:
        print(f"   Age: {age:.1f} hours")
    
    # Issues
    for issue in result['issues']:
        print(f"   ❌ {issue}")
    
    # Warnings
    for warning in result['warnings']:
        print(f"   ⚠️  {warning}")
    
    print()


def main():
    """Main verification function"""
    print_banner()
    
    # Check credentials
    if not check_coinbase_credentials():
        return 1
    
    print()
    
    # Get positions
    positions = get_coinbase_positions()
    
    if positions is None:
        print("❌ Could not verify positions (connection failed)")
        return 1
    
    print()
    print("-" * 80)
    print()
    
    if len(positions) == 0:
        print("✅ NO OPEN POSITIONS")
        print()
        print("   Coinbase has no open positions to verify.")
        print("   This is good - no risk of losing trades.")
        print()
        return 0
    
    # Verify each position
    print(f"📋 VERIFYING {len(positions)} OPEN POSITIONS")
    print()
    
    violations = []
    warnings_only = []
    ok_positions = []
    
    for position in positions:
        result = verify_position(position)
        
        if result['status'] == 'VIOLATION':
            violations.append(result)
        elif result['warnings']:
            warnings_only.append(result)
        else:
            ok_positions.append(result)
    
    # Print results
    if violations:
        print("🚨 VIOLATIONS FOUND:")
        print()
        for result in violations:
            print_position_report(result)
    
    if warnings_only:
        print("⚠️  WARNINGS:")
        print()
        for result in warnings_only:
            print_position_report(result)
    
    if ok_positions:
        print("✅ HEALTHY POSITIONS:")
        print()
        for result in ok_positions:
            print_position_report(result)
    
    # Summary
    print("-" * 80)
    print()
    print("📊 SUMMARY")
    print()
    print(f"   Total Positions: {len(positions)}")
    print(f"   🚨 Violations: {len(violations)}")
    print(f"   ⚠️  Warnings: {len(warnings_only)}")
    print(f"   ✅ Healthy: {len(ok_positions)}")
    print()
    
    # Strategy reminder
    print("📖 STRATEGY RULES (AGGRESSIVE_SELL_FIX_JAN_13_2026)")
    print()
    print(f"   Stop Loss: {STOP_LOSS_THRESHOLD}% (exit immediately)")
    print(f"   Max Hold Time: {MAX_POSITION_HOLD_HOURS} hours (force exit)")
    print(f"   Profit Targets: {', '.join([f'{t}%' for t in PROFIT_TARGETS])}")
    print()
    
    if violations:
        print("⚠️  ACTION REQUIRED:")
        print()
        print("   Violations found! These positions should have been sold.")
        print("   Possible causes:")
        print("   - Trading bot not running")
        print("   - API connection issues")
        print("   - Strategy logic bug")
        print()
        print("   Recommended actions:")
        print("   1. Check if bot is running")
        print("   2. Review recent logs for errors")
        print("   3. Manually close violating positions if needed")
        print()
        return 2
    elif warnings_only:
        print("✅ NO VIOLATIONS")
        print()
        print("   Some positions have warnings but no violations.")
        print("   Monitor these positions - they may exit soon.")
        print()
        return 0
    else:
        print("✅ ALL POSITIONS HEALTHY")
        print()
        print("   No violations or warnings found.")
        print("   Aggressive sell logic is working correctly.")
        print()
        return 0


if __name__ == "__main__":
    try:
        exit_code = main()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print()
        print("⚠️  Verification interrupted by user")
        sys.exit(1)
    except Exception as e:
        print()
        print(f"❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
