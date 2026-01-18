# NIJA Multi-Asset Trading Guide

## Overview

NIJA now supports trading **multiple asset types** beyond just cryptocurrency:

- ✅ **Crypto Spot Trading** (Kraken, Coinbase)
- ✅ **Futures Trading** (Kraken Futures - ENABLED)
- ✅ **Stock Trading** (Alpaca integration - US equities)
- ⏳ **Options Trading** (Kraken - In Development)

This guide explains how multi-asset trading works for **master and all user accounts**.

---

## Supported Asset Classes by Broker

| Broker | Crypto | Stocks | Futures | Options | Status |
|--------|--------|--------|---------|---------|--------|
| **Kraken** | ✅ Yes | Via Alpaca | ✅ Yes | In Dev | **PRIMARY** |
| **Alpaca** | Limited | ✅ Yes | No | No | Stocks only |
| **Coinbase** | ✅ Yes | No | No | No | Crypto only |

---

## Configuration Changes (January 2026)

### ✅ What Changed

1. **Kraken Futures ENABLED** for all accounts
   - `enable_futures: bool = True` (previously `False`)
   - Max leverage: 3x
   - Supports futures pairs (e.g., BTC-PERP, ETH-F0)

2. **Enhanced Asset Detection**
   - `KrakenBroker.supports_asset_class()` now returns:
     - `crypto` ✅
     - `futures` ✅
     - `cryptocurrency` ✅

3. **Market Discovery Enhanced**
   - `get_all_products()` now discovers both spot and futures pairs
   - Automatic filtering of futures symbols (PERP, F0, etc.)
   - Futures pairs only included when `enable_futures=True`

4. **Trade Confirmation Logging**
   - All trades now log with account identification (MASTER / USER:username)
   - Enhanced logging for Kraken, Coinbase, and Alpaca
   - Immediate log flushing for real-time confirmation

---

## How Multi-Asset Trading Works

### Master Account
- Trades **all enabled asset types** across all configured brokers
- Kraken: Crypto spot + Futures
- Alpaca: US stocks
- Coinbase: Crypto spot only

### User Accounts
- Same multi-asset support as master
- Each user needs separate API credentials per broker
- Example: User "Tania Gilbert" can trade:
  - Kraken crypto + futures (if `KRAKEN_USER_TANIA_API_KEY` set)
  - Alpaca stocks (if `ALPACA_USER_TANIA_API_KEY` set)

---

## Trade Confirmation

Every trade now includes enhanced confirmation logging:

```
======================================================================
✅ TRADE CONFIRMATION - MASTER
======================================================================
   Exchange: Kraken
   Order Type: BUY
   Symbol: BTC-PERP
   Quantity: 100.0
   Order ID: XXXXXX-XXXXX-XXXXX
   Account: MASTER
   Timestamp: 2026-01-18 01:00:00 UTC
======================================================================
```

This applies to:
- ✅ Master account trades
- ✅ All user account trades
- ✅ All brokers (Kraken, Coinbase, Alpaca)
- ✅ All asset types (crypto, futures, stocks)

---

## Profit-Taking Guarantees

### Fee-Aware Profit Calculations

All profit targets are **net profit after fees**:

| Broker | Round-Trip Fee | Min Profit Target | Net After Fees |
|--------|----------------|-------------------|----------------|
| **Kraken** | 0.36% | 0.5% | 0.14% net |
| **Coinbase** | 1.4% | 2.0% | 0.6% net |
| **Alpaca** | ~0.0% | 0.3% | 0.3% net |

### Stepped Profit Exits

NIJA automatically takes profit at multiple levels:
- Exit 10% at 2.0% gross profit
- Exit 15% at 2.5% gross profit
- Exit 25% at 3.0% gross profit
- Exit 50% at 4.0% gross profit

This ensures **profits are locked in** before market reversals.

### Stop Loss Protection

Every position has automatic stop loss:
- Kraken: -0.7% stop loss
- Coinbase: -1.0% stop loss
- Alpaca: Configurable per strategy

**GUARANTEE**: No position can lose more than the configured stop loss percentage.

---

## How to Enable Different Asset Types

### 1. Enable Kraken Futures (Already Enabled)

Futures are **enabled by default** as of January 2026.

To verify:
```python
from bot.broker_configs.kraken_config import KRAKEN_CONFIG
print(KRAKEN_CONFIG.enable_futures)  # Should be True
```

### 2. Enable Stock Trading (Alpaca)

Set environment variables:
```bash
# Master account
ALPACA_API_KEY=your-alpaca-key
ALPACA_API_SECRET=your-alpaca-secret
ALPACA_PAPER=true  # or false for live trading

# User accounts
ALPACA_USER_TANIA_API_KEY=user-alpaca-key
ALPACA_USER_TANIA_API_SECRET=user-alpaca-secret
ALPACA_USER_TANIA_PAPER=true
```

### 3. Options Trading (Not Yet Available)

Kraken is developing options support. Check back for updates.

---

## Verification

### Check Which Asset Classes Are Enabled

```python
from bot.broker_manager import BrokerType, KrakenBroker

broker = KrakenBroker()
print(broker.supports_asset_class('crypto'))    # True
print(broker.supports_asset_class('futures'))   # True
print(broker.supports_asset_class('stocks'))    # False (use Alpaca)
print(broker.supports_asset_class('options'))   # False (in dev)
```

### Check Available Markets

```python
# Get all tradeable pairs (crypto + futures)
products = broker.get_all_products()
print(f"Total tradeable pairs: {len(products)}")

# Filter by type
crypto_pairs = [p for p in products if 'PERP' not in p and 'F0' not in p]
futures_pairs = [p for p in products if 'PERP' in p or 'F0' in p]

print(f"Crypto spot pairs: {len(crypto_pairs)}")
print(f"Futures pairs: {len(futures_pairs)}")
```

### Verify Trade Confirmations

Watch logs for trade confirmations:
```bash
# All trades will show:
# "✅ TRADE CONFIRMATION - MASTER" or
# "✅ TRADE CONFIRMATION - USER:tania_gilbert"

tail -f logs/nija.log | grep "TRADE CONFIRMATION"
```

---

## Architecture Notes

### Why Stocks Are Via Alpaca

Kraken stocks are only available through Alpaca partnership. NIJA already has:
- ✅ AlpacaBroker implementation
- ✅ Multi-broker support
- ✅ Master + user account separation

**Best Practice**: Use Kraken for crypto/futures, Alpaca for stocks.

### Futures vs Spot Trading

**Spot Trading** (Kraken Spot API):
- Own the actual cryptocurrency
- No leverage
- Hold positions indefinitely
- Lower risk

**Futures Trading** (Kraken Futures API):
- Trade contracts (don't own crypto)
- Leverage up to 3x
- Contracts expire
- Higher risk, higher reward

---

## Safety & Risk Management

### 1. Leverage Limits
- Futures leverage capped at **3x maximum**
- Prevents over-leveraging and liquidation risk

### 2. Position Limits
- Kraken: Max 12 positions (more than Coinbase's 8)
- Coinbase: Max 8 positions
- Alpaca: Varies by account type

### 3. Exposure Limits
- Kraken: Max 60% of capital deployed
- Coinbase: Max 40% of capital deployed
- Ensures liquidity reserve for opportunities

### 4. Profit-Taking is Mandatory
- **Cannot be disabled** - built into core strategy
- Automatic stepped exits
- Fee-aware calculations ensure NET profitability

---

## Troubleshooting

### "Futures Not Showing Up"

Check if futures are actually available on Kraken in your region:
```bash
python3 -c "
from bot.broker_manager import KrakenBroker
broker = KrakenBroker()
broker.connect()
products = broker.get_all_products()
futures = [p for p in products if 'PERP' in p or 'F0' in p]
print(f'Futures pairs found: {len(futures)}')
print('Sample:', futures[:5] if futures else 'None')
"
```

### "Trades Not Confirmed"

Ensure logging is configured:
```python
import logging
logging.basicConfig(level=logging.INFO)
# All trade confirmations use INFO level
```

### "Can't Trade Stocks on Kraken"

Stocks require **Alpaca broker**. Set up Alpaca credentials:
```bash
ALPACA_API_KEY=...
ALPACA_API_SECRET=...
```

---

## Summary

✅ **Multi-asset trading is ENABLED** for master and all users  
✅ **Kraken futures are ENABLED** by default  
✅ **Stocks available via Alpaca** integration  
✅ **Trade confirmations log all accounts** (master + users)  
✅ **Profit-taking is guaranteed** with fee-aware calculations  
✅ **Stop losses protect all positions** automatically  

**Next Steps**:
1. Ensure Kraken credentials are configured
2. Add Alpaca credentials for stock trading (optional)
3. Monitor logs for trade confirmations
4. Verify profit-taking on live trades

---

## Related Documentation

- [KRAKEN_MASTER_SETUP_COMPLETE_GUIDE.md](KRAKEN_MASTER_SETUP_COMPLETE_GUIDE.md) - Kraken setup
- [MULTI_USER_SETUP_GUIDE.md](MULTI_USER_SETUP_GUIDE.md) - User accounts
- [PRO_MODE_README.md](PRO_MODE_README.md) - Position rotation trading
- [BROKER_INTEGRATION_GUIDE.md](BROKER_INTEGRATION_GUIDE.md) - Technical details

---

**Last Updated**: January 18, 2026  
**Version**: Multi-Asset v1.0  
**Status**: ✅ PRODUCTION READY
