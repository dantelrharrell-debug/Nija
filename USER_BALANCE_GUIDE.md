# User Balance Visibility Guide

This guide explains how to view and monitor user account balances in the NIJA copy trading system.

## Quick Start

### View All User Balances

**Command Line (Formatted Table):**
```bash
python scripts/show_user_balances.py
```

**Output:**
```
================================================================================
NIJA USER ACCOUNT BALANCES
================================================================================
Generated: 2026-01-21 16:00:00
================================================================================

🔷 MASTER ACCOUNT (Nija System)
--------------------------------------------------------------------------------
   COINBASE             $1,234.56
   KRAKEN               $5,678.90
--------------------------------------------------------------------------------
   TOTAL                $6,913.46

🔷 USER ACCOUNTS
--------------------------------------------------------------------------------

   👤 User: alice
   ----------------------------------------------------------------------------
      COINBASE         $250.00
      KRAKEN           $750.00
   ----------------------------------------------------------------------------
      SUBTOTAL         $1,000.00

   👤 User: bob
   ----------------------------------------------------------------------------
      KRAKEN           $2,500.00
   ----------------------------------------------------------------------------
      SUBTOTAL         $2,500.00

================================================================================
SUMMARY
================================================================================
   Total Users:           2
   Total User Capital:    $3,500.00
   Average per User:      $1,750.00
================================================================================
```

**Command Line (JSON Format):**
```bash
python scripts/show_user_balances.py --json
```

**Output:**
```json
{
  "timestamp": "2026-01-21T16:00:00.000000",
  "balances": {
    "master": {
      "coinbase": 1234.56,
      "kraken": 5678.90
    },
    "users": {
      "alice": {
        "coinbase": 250.00,
        "kraken": 750.00
      },
      "bob": {
        "kraken": 2500.00
      }
    }
  },
  "summary": {
    "master_total": 6913.46,
    "user_totals": {
      "alice": 1000.00,
      "bob": 2500.00
    },
    "total_user_capital": 3500.00,
    "user_count": 2,
    "average_per_user": 1750.00
  }
}
```

## Programmatic Access

### In Python Code

```python
from bot.multi_account_broker_manager import multi_account_broker_manager

# Method 1: Log all balances to console (formatted)
multi_account_broker_manager.log_all_balances()

# Method 2: Get all balances as dictionary
balances = multi_account_broker_manager.get_all_balances()
print(f"Master balances: {balances['master']}")
print(f"User balances: {balances['users']}")

# Method 3: Get user balance summary (sorted by total)
summary = multi_account_broker_manager.get_user_balance_summary()
print(f"Total users: {summary['user_count']}")
print(f"Total capital: ${summary['total_capital']:,.2f}")
print(f"Average per user: ${summary['average_balance']:,.2f}")

# Iterate through users (sorted by balance, highest first)
for user in summary['users']:
    print(f"{user['user_id']}: ${user['total']:,.2f}")
    for broker, balance in user['brokers'].items():
        print(f"  {broker}: ${balance:,.2f}")

# Method 4: Get status report as formatted string
report = multi_account_broker_manager.get_status_report()
print(report)
```

### Get Balance for Specific User

```python
from bot.multi_account_broker_manager import multi_account_broker_manager
from bot.broker_manager import BrokerType

# Get balance for specific user and broker
user_id = "alice"
broker_type = BrokerType.COINBASE

balance = multi_account_broker_manager.get_user_balance(user_id, broker_type)
print(f"{user_id}'s {broker_type.value} balance: ${balance:,.2f}")
```

## Available Methods

### `get_all_balances()`
Returns dictionary with all balances:
```python
{
    'master': {'coinbase': 1234.56, 'kraken': 5678.90},
    'users': {
        'alice': {'coinbase': 250.00, 'kraken': 750.00},
        'bob': {'kraken': 2500.00}
    }
}
```

### `get_user_balance_summary()`
Returns structured summary with calculated totals:
```python
{
    'user_count': 2,
    'total_capital': 3500.00,
    'average_balance': 1750.00,
    'users': [
        {
            'user_id': 'bob',
            'total': 2500.00,
            'brokers': {'kraken': 2500.00}
        },
        {
            'user_id': 'alice',
            'total': 1000.00,
            'brokers': {'coinbase': 250.00, 'kraken': 750.00}
        }
    ]
}
```
*Note: Users are sorted by total balance (highest first)*

### `get_status_report()`
Returns formatted text report (same as `log_all_balances()` output)

### `log_all_balances()`
Logs formatted balance report to console

## Web Dashboard

User balances are also visible in the web dashboard at:
- `http://localhost:5000/users` - Users dashboard with balance cards
- `http://localhost:5000/api/users` - JSON API endpoint

Each user card shows:
- Current balance
- Total trades
- Win rate
- Daily P&L
- Total P&L
- Recent trades

## Automated Monitoring

### Periodic Balance Logging

Add to your trading loop:

```python
import time

while trading:
    # Your trading logic...
    
    # Log balances every hour
    if should_log_balances():
        multi_account_broker_manager.log_all_balances()
    
    time.sleep(60)
```

### Balance Change Alerts

Use the monitoring system for balance alerts:

```python
from bot.monitoring_system import get_monitoring_system

monitor = get_monitoring_system()
# Monitoring system automatically tracks balance changes
# and sends alerts for BALANCE_LOW and BALANCE_DROP events
```

## Balance Caching

**Important:** The system caches balances for 120 seconds to prevent excessive API calls (especially for Kraken which requires sequential calls with delays).

To force a fresh balance fetch, restart the bot or wait for cache expiration.

## Troubleshooting

### "No user brokers configured"

**Cause:** No user accounts are connected or enabled.

**Solution:**
1. Check `config/users/*.json` files exist
2. Ensure users have `"enabled": true` in their config
3. Verify broker credentials are configured
4. Restart the bot to reload user configurations

### Balance shows $0.00

**Causes:**
- Broker not connected
- Account actually has $0 balance
- API error retrieving balance

**Solution:**
1. Check connection status: `multi_account_broker_manager.get_status_report()`
2. Verify credentials in `.env` or user config files
3. Check broker logs for connection errors

### Slow balance retrieval

**Cause:** Kraken API requires sequential calls with 1.1s delay between requests.

**Solution:** This is normal. Balance caching (120s TTL) minimizes the impact.

## See Also

- [MULTI_EXCHANGE_TRADING_GUIDE.md](../MULTI_EXCHANGE_TRADING_GUIDE.md) - Multi-exchange setup
- [USER_MANAGEMENT.md](../USER_MANAGEMENT.md) - User account configuration
- [COPY_TRADING_SETUP.md](../COPY_TRADING_SETUP.md) - Copy trading setup

## API Reference

All balance methods are in:
- `bot/multi_account_broker_manager.py` - `MultiAccountBrokerManager` class
- `scripts/show_user_balances.py` - Command-line tool
