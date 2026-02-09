# Optional Enhancements & Future Work

## Overview

This document outlines optional enhancements for the position normalization and PLATFORM account safety features. These are **not required** for production deployment but can improve robustness over time.

**Current Status:** ✅ PRODUCTION READY - All critical mechanisms validated, documented, and tested.

---

## 1. Periodic Automated Verification

### Goal
Catch broker-side changes (symbol updates, API changes) before they cause issues in production.

### Implementation Plan

#### Weekly Automated Test Run

```python
#!/usr/bin/env python3
"""
Weekly automated verification script.
Run via cron or scheduler to validate all systems.
"""

import logging
import sys
from datetime import datetime
from pathlib import Path

# Add bot directory to path
sys.path.insert(0, str(Path(__file__).parent / 'bot'))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[
        logging.FileHandler(f'weekly_verification_{datetime.now():%Y%m%d}.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger("weekly_verification")


def run_position_normalization_tests():
    """Run position normalization test suite."""
    import subprocess
    
    logger.info("=" * 70)
    logger.info("Running Position Normalization Tests")
    logger.info("=" * 70)
    
    result = subprocess.run(
        ['python', 'test_position_normalization.py'],
        capture_output=True,
        text=True
    )
    
    if result.returncode == 0:
        logger.info("✅ Position normalization tests PASSED")
        return True
    else:
        logger.error("❌ Position normalization tests FAILED")
        logger.error(result.stderr)
        return False


def run_platform_safety_tests():
    """Run PLATFORM account safety test suite."""
    import subprocess
    
    logger.info("=" * 70)
    logger.info("Running PLATFORM Account Safety Tests")
    logger.info("=" * 70)
    
    result = subprocess.run(
        ['python', 'test_platform_account_safety.py'],
        capture_output=True,
        text=True
    )
    
    if result.returncode == 0:
        logger.info("✅ PLATFORM safety tests PASSED")
        return True
    else:
        logger.error("❌ PLATFORM safety tests FAILED")
        logger.error(result.stderr)
        return False


def verify_broker_connectivity():
    """Verify all brokers are accessible."""
    from bot.broker_manager import CoinbaseBroker, BrokerType
    
    logger.info("=" * 70)
    logger.info("Verifying Broker Connectivity")
    logger.info("=" * 70)
    
    brokers_to_test = [
        ('Coinbase', CoinbaseBroker)
    ]
    
    all_connected = True
    
    for name, BrokerClass in brokers_to_test:
        try:
            broker = BrokerClass()
            if broker.connect():
                logger.info(f"✅ {name}: Connected")
            else:
                logger.error(f"❌ {name}: Connection failed")
                all_connected = False
        except Exception as e:
            logger.error(f"❌ {name}: Error - {e}")
            all_connected = False
    
    return all_connected


def check_symbol_mappings():
    """Verify problematic symbols still have fallback logic."""
    from bot.broker_manager import CoinbaseBroker
    
    logger.info("=" * 70)
    logger.info("Checking Symbol Mappings")
    logger.info("=" * 70)
    
    # Known problematic symbols
    test_symbols = [
        'AUT-USD',  # Known to have price fetch issues
        'BTC-USD',  # Should work normally
        'ETH-USD',  # Should work normally
    ]
    
    broker = CoinbaseBroker()
    if not broker.connect():
        logger.error("Cannot test symbols - broker not connected")
        return False
    
    issues_found = []
    
    for symbol in test_symbols:
        try:
            price = broker.get_current_price(symbol)
            
            if price is None and symbol == 'AUT-USD':
                logger.info(f"✅ {symbol}: Correctly returns None (fallback should apply)")
            elif price is not None and symbol in ['BTC-USD', 'ETH-USD']:
                logger.info(f"✅ {symbol}: Price fetched successfully (${price:.2f})")
            elif price is None and symbol in ['BTC-USD', 'ETH-USD']:
                logger.warning(f"⚠️  {symbol}: Unexpected None price")
                issues_found.append(symbol)
            
        except Exception as e:
            logger.error(f"❌ {symbol}: Error - {e}")
            issues_found.append(symbol)
    
    if issues_found:
        logger.warning(f"Symbol issues found: {issues_found}")
        return False
    
    return True


def verify_dust_blacklist():
    """Verify dust blacklist is accessible and functional."""
    from bot.dust_blacklist import get_dust_blacklist
    
    logger.info("=" * 70)
    logger.info("Verifying Dust Blacklist")
    logger.info("=" * 70)
    
    try:
        blacklist = get_dust_blacklist()
        stats = blacklist.get_stats()
        
        logger.info(f"✅ Blacklist accessible")
        logger.info(f"   Blacklisted symbols: {stats['count']}")
        logger.info(f"   Threshold: ${stats['threshold_usd']:.2f}")
        
        # Test add/remove
        test_symbol = "TEST-VERIFY-USD"
        blacklist.add_to_blacklist(test_symbol, 0.50, "weekly verification test")
        
        if blacklist.is_blacklisted(test_symbol):
            logger.info(f"✅ Add to blacklist works")
        else:
            logger.error(f"❌ Add to blacklist failed")
            return False
        
        blacklist.remove_from_blacklist(test_symbol)
        
        if not blacklist.is_blacklisted(test_symbol):
            logger.info(f"✅ Remove from blacklist works")
        else:
            logger.error(f"❌ Remove from blacklist failed")
            return False
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Blacklist verification failed: {e}")
        return False


def send_alert_if_failures(results):
    """Send alert if any tests failed."""
    failures = [name for name, passed in results.items() if not passed]
    
    if failures:
        logger.error("=" * 70)
        logger.error("⚠️  WEEKLY VERIFICATION FAILURES DETECTED")
        logger.error("=" * 70)
        logger.error(f"Failed checks: {', '.join(failures)}")
        logger.error("Please investigate immediately!")
        logger.error("=" * 70)
        
        # TODO: Add email/Slack notification here
        # send_email("admin@example.com", "NIJA Weekly Verification Failed", ...)
        # send_slack_message("#alerts", "Weekly verification failed", ...)
    else:
        logger.info("=" * 70)
        logger.info("✅ ALL WEEKLY VERIFICATIONS PASSED")
        logger.info("=" * 70)


def main():
    """Run weekly automated verification."""
    logger.info("")
    logger.info("╔" + "=" * 68 + "╗")
    logger.info("║" + " " * 20 + "WEEKLY VERIFICATION" + " " * 29 + "║")
    logger.info("╚" + "=" * 68 + "╝")
    logger.info("")
    logger.info(f"Date: {datetime.now():%Y-%m-%d %H:%M:%S}")
    logger.info("")
    
    results = {
        'Position Normalization Tests': run_position_normalization_tests(),
        'PLATFORM Safety Tests': run_platform_safety_tests(),
        'Broker Connectivity': verify_broker_connectivity(),
        'Symbol Mappings': check_symbol_mappings(),
        'Dust Blacklist': verify_dust_blacklist(),
    }
    
    # Send alerts if needed
    send_alert_if_failures(results)
    
    # Summary
    passed = sum(1 for r in results.values() if r)
    total = len(results)
    
    logger.info("")
    logger.info("=" * 70)
    logger.info(f"VERIFICATION SUMMARY: {passed}/{total} checks passed")
    logger.info("=" * 70)
    
    return 0 if all(results.values()) else 1


if __name__ == '__main__':
    sys.exit(main())
```

#### Cron Schedule

```bash
# Add to crontab for weekly execution
# Run every Monday at 2 AM
0 2 * * 1 cd /path/to/nija && python scripts/weekly_verification.py

# Or use systemd timer (more modern)
# Create /etc/systemd/system/nija-weekly-verification.timer
[Unit]
Description=NIJA Weekly Verification Timer

[Timer]
OnCalendar=Mon *-*-* 02:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

---

## 2. Cross-User Interaction Safety

### Goal
Ensure user accounts don't accidentally exceed caps when trading in parallel.

### Current Status
- PLATFORM account: Cap enforced (max 8)
- User accounts: Need per-user cap enforcement

### Implementation Plan

#### Per-User Position Cap

```python
# In bot/multi_account_broker_manager.py

class UserPositionLimits:
    """
    Enforces per-user position limits to prevent cross-user cap violations.
    """
    
    def __init__(self):
        self.user_limits = {}  # user_id -> max_positions
        self._lock = threading.Lock()
    
    def set_user_limit(self, user_id: str, max_positions: int):
        """Set position cap for specific user."""
        with self._lock:
            self.user_limits[user_id] = max_positions
    
    def check_can_enter(self, user_id: str, current_positions: int) -> bool:
        """Check if user can open new position."""
        with self._lock:
            max_allowed = self.user_limits.get(user_id, 5)  # Default 5
            return current_positions < max_allowed
    
    def get_user_status(self, user_id: str, current_positions: int) -> dict:
        """Get user position status."""
        with self._lock:
            max_allowed = self.user_limits.get(user_id, 5)
            return {
                'user_id': user_id,
                'current_positions': current_positions,
                'max_allowed': max_allowed,
                'can_enter': current_positions < max_allowed,
                'utilization_pct': (current_positions / max_allowed) * 100
            }


# Usage in trading_strategy.py
def check_user_position_cap(self, user_id: str):
    """Check if user can enter new position."""
    
    # Get user's current positions
    user_positions = self.get_user_positions(user_id)
    
    # Check against user's limit
    user_limits = UserPositionLimits()
    status = user_limits.get_user_status(user_id, len(user_positions))
    
    if not status['can_enter']:
        logger.warning(f"🛑 USER CAP BLOCKED: {user_id}")
        logger.warning(f"   Positions: {status['current_positions']}/{status['max_allowed']}")
        return False
    
    return True
```

#### Global Position Monitor

```python
class GlobalPositionMonitor:
    """
    Monitors total positions across all accounts to prevent system overload.
    """
    
    def __init__(self, max_total_positions: int = 100):
        self.max_total_positions = max_total_positions
    
    def get_global_position_count(self, multi_account_manager) -> dict:
        """Get total positions across all accounts."""
        
        platform_positions = 0
        user_positions = 0
        
        # Count PLATFORM positions
        for broker in multi_account_manager.platform_brokers.values():
            if broker and broker.connected:
                platform_positions += len(broker.get_positions())
        
        # Count USER positions
        for broker in multi_account_manager.user_brokers.values():
            if broker and broker.connected:
                user_positions += len(broker.get_positions())
        
        total = platform_positions + user_positions
        
        return {
            'platform_positions': platform_positions,
            'user_positions': user_positions,
            'total_positions': total,
            'max_allowed': self.max_total_positions,
            'within_limit': total < self.max_total_positions,
            'utilization_pct': (total / self.max_total_positions) * 100
        }
    
    def should_block_new_entries(self, stats: dict) -> bool:
        """Determine if new entries should be blocked system-wide."""
        
        # Block if total positions exceed 90% of max
        if stats['utilization_pct'] > 90:
            logger.warning(f"🚨 GLOBAL CAP WARNING: {stats['utilization_pct']:.1f}% utilization")
            return True
        
        return False
```

---

## 3. Edge Cases Handling

### Goal
Handle very low balances (<$10) and highly volatile markets without errors.

### Edge Cases to Address

#### 3.1 Very Low Balance (<$10)

```python
# In bot/position_cap_enforcer.py

def validate_minimum_balance(broker, min_balance_usd: float = 10.0):
    """
    Validate account has minimum balance for trading.
    
    Prevents errors when balance is too low to meet exchange minimums.
    """
    balance = broker.get_balance()
    
    if balance < min_balance_usd:
        logger.warning(f"⚠️  Balance ${balance:.2f} below minimum ${min_balance_usd:.2f}")
        logger.warning(f"   Recommend depositing at least ${min_balance_usd - balance:.2f}")
        logger.warning(f"   Trading may fail due to exchange minimum order sizes")
        return False
    
    return True


# In trading_strategy.py
def can_trade_with_balance(self, balance: float) -> bool:
    """Check if balance is sufficient for trading."""
    
    MIN_TRADING_BALANCE = 10.0  # Absolute minimum
    
    if balance < MIN_TRADING_BALANCE:
        logger.error(f"🛑 BALANCE TOO LOW: ${balance:.2f} < ${MIN_TRADING_BALANCE:.2f}")
        logger.error(f"   Cannot trade - deposit more funds")
        return False
    
    # Warn if balance is marginal
    if balance < 50.0:
        logger.warning(f"⚠️  Low balance: ${balance:.2f}")
        logger.warning(f"   Consider depositing more for better position sizing")
    
    return True
```

#### 3.2 Highly Volatile Markets

```python
# In bot/risk_manager.py

def adjust_for_volatility(self, symbol: str, base_size: float) -> float:
    """
    Adjust position size based on market volatility.
    
    Reduces size in highly volatile markets to manage risk.
    """
    try:
        # Get recent volatility (e.g., ATR, standard deviation)
        volatility = self.get_market_volatility(symbol)
        
        # Define volatility thresholds
        LOW_VOLATILITY = 0.02  # 2%
        HIGH_VOLATILITY = 0.10  # 10%
        
        if volatility > HIGH_VOLATILITY:
            # Reduce size by 50% in highly volatile markets
            adjusted_size = base_size * 0.5
            logger.warning(f"⚠️  High volatility ({volatility*100:.1f}%) - reducing size")
            logger.warning(f"   Original: ${base_size:.2f} → Adjusted: ${adjusted_size:.2f}")
            return adjusted_size
        
        elif volatility > LOW_VOLATILITY:
            # Slightly reduce size in moderate volatility
            adjusted_size = base_size * 0.75
            logger.info(f"ℹ️  Moderate volatility ({volatility*100:.1f}%) - adjusting size")
            return adjusted_size
        
        # Normal volatility - no adjustment
        return base_size
        
    except Exception as e:
        logger.error(f"Error calculating volatility adjustment: {e}")
        # Return original size if error
        return base_size


def get_market_volatility(self, symbol: str, periods: int = 20) -> float:
    """
    Calculate market volatility (standard deviation of returns).
    
    Returns:
        float: Volatility as decimal (e.g., 0.05 = 5%)
    """
    try:
        # Get recent candles
        market_data = self.broker.get_market_data(symbol, timeframe='1h', limit=periods)
        
        if not market_data or not market_data.get('candles'):
            return 0.05  # Default to moderate volatility
        
        # Calculate returns
        prices = [float(candle['close']) for candle in market_data['candles']]
        returns = [(prices[i] - prices[i-1]) / prices[i-1] for i in range(1, len(prices))]
        
        # Calculate standard deviation
        import numpy as np
        volatility = np.std(returns)
        
        return volatility
        
    except Exception as e:
        logger.error(f"Error calculating volatility: {e}")
        return 0.05  # Default
```

#### 3.3 Graceful Degradation

```python
# In bot/trading_strategy.py

def execute_with_fallback(self, operation, fallback_value=None):
    """
    Execute operation with graceful fallback on error.
    
    Ensures system continues operating even if non-critical components fail.
    """
    try:
        return operation()
    except Exception as e:
        logger.error(f"Operation failed: {e}")
        logger.warning(f"Using fallback value: {fallback_value}")
        return fallback_value


# Example usage
def get_position_count_safe(self, broker):
    """Get position count with fallback."""
    return self.execute_with_fallback(
        operation=lambda: len(broker.get_positions()),
        fallback_value=0  # Assume 0 positions if error
    )
```

---

## Testing Plan for Enhancements

### 1. Automated Verification Testing

```bash
# Test weekly verification manually
python scripts/weekly_verification.py

# Expected: All checks pass
# If any fail, investigate immediately
```

### 2. Cross-User Testing

```python
# Test multi-user position caps
def test_cross_user_caps():
    """Test that users don't interfere with each other."""
    
    # Create two users
    user1_positions = 5
    user2_positions = 3
    
    # Both should be independent
    user1_limit = UserPositionLimits()
    user1_limit.set_user_limit("user1", 5)
    
    user2_limit = UserPositionLimits()
    user2_limit.set_user_limit("user2", 5)
    
    # User1 at cap, user2 can still trade
    assert not user1_limit.check_can_enter("user1", 5)
    assert user2_limit.check_can_enter("user2", 3)
```

### 3. Edge Case Testing

```python
# Test very low balance
def test_low_balance():
    """Test handling of balances < $10."""
    
    broker = MockBroker()
    broker.balance = 5.0
    
    # Should warn but not crash
    can_trade = can_trade_with_balance(broker.balance)
    assert not can_trade
    
    # Increase balance
    broker.balance = 15.0
    can_trade = can_trade_with_balance(broker.balance)
    assert can_trade
```

---

## Deployment Priority

**Priority Levels:**

1. **HIGH (Recommended within 1 month):**
   - Weekly automated verification
   - Low balance handling

2. **MEDIUM (Recommended within 3 months):**
   - Cross-user position caps
   - Global position monitor

3. **LOW (Nice to have):**
   - Volatility-based sizing
   - Advanced edge case handling

---

## Monitoring & Alerts

### Metrics to Track

```python
metrics = {
    # Verification
    'last_verification_date': datetime,
    'verification_pass_rate': float,
    'failed_checks': list,
    
    # Cross-user
    'total_users_active': int,
    'users_at_cap': int,
    'global_position_count': int,
    
    # Edge cases
    'low_balance_warnings': int,
    'high_volatility_adjustments': int,
    'fallback_activations': int,
}
```

### Alert Thresholds

- Weekly verification failure → Immediate alert
- Global positions > 90% → Warning alert
- Multiple low balance warnings → Review needed
- High volatility adjustments > 50% of trades → Market review

---

## Conclusion

These optional enhancements will improve system robustness over time:

✅ **Weekly verification** catches API changes early  
✅ **Cross-user caps** prevent system overload  
✅ **Edge case handling** ensures graceful degradation  

**Current Status:** Production ready without these enhancements.  
**Future Work:** Implement based on priority and operational needs.

---

**Document Created:** February 9, 2026  
**Status:** Optional - Not required for production
