# NIJA Profit-Taking Guarantee

**Version:** 1.0  
**Date:** January 22, 2026  
**Status:** ✅ ACTIVE

---

## 🎯 Guarantee Statement

**NIJA GUARANTEES profit-taking occurs 24/7 on ALL accounts, ALL brokerages, and ALL tiers.**

This is a **hard-coded guarantee** - profit-taking **CANNOT** be disabled through configuration.

---

## 📋 What This Means

### ✅ Always Enabled
- Profit-taking logic runs **every trading cycle** (every 2.5 minutes)
- **No configuration flag** can disable profit-taking
- Works **24 hours a day, 7 days a week**
- Automatically monitors **all open positions**

### ✅ All Accounts
- Works for **individual accounts**
- Works for **copy trading** (master and follower accounts)
- Works for **multi-account** setups
- Each account monitored independently

### ✅ All Brokerages
- **Coinbase** - Fee-aware targets (1.4% fees)
- **Kraken** - Fee-aware targets (0.36% fees)
- **Binance** - Fee-aware targets (0.28% fees)
- **OKX** - Fee-aware targets (0.3% fees)
- **Alpaca** - Stock market profit targets
- **Any future broker** integrations

### ✅ All Tiers
- **SAVER** ($10-$25) - Full profit-taking support
- **INVESTOR** ($100-$249) - Full profit-taking support
- **INCOME** ($250-$999) ⭐ - Full profit-taking support
- **LIVABLE** ($1k-$5k) - Full profit-taking support
- **BALLER** ($5k+) - Full profit-taking support

---

## 🔧 How It Works

### Dual Profit-Taking System

NIJA uses **two independent** profit-taking systems for maximum reliability:

#### 1. **Stepped Profit Exits** (Primary)
More aggressive, takes profits gradually:
- Exit 10% at 2.0% gross profit → ~0.6% NET (after fees)
- Exit 15% at 2.5% gross profit → ~1.1% NET
- Exit 25% at 3.0% gross profit → ~1.6% NET
- Exit 50% at 4.0% gross profit → ~2.6% NET

#### 2. **Traditional Take Profit Levels** (Backup)
Based on R-multiples (risk-reward ratio):
- **TP1:** 1.0R (minimum for fee coverage)
- **TP2:** 1.5R (solid profit target)
- **TP3:** 2.0R (excellent trade)

### Checking Frequency

| System Component | Check Frequency |
|-----------------|-----------------|
| **Main Trading Loop** | Every 2.5 minutes |
| **Position Analysis** | Every cycle for all open positions |
| **Profit Guardian** | Available for independent monitoring |

### Fee-Aware Calculations

All profit targets are **adjusted for broker fees**:

| Broker | Round-Trip Fee | Minimum Profit Target |
|--------|---------------|---------------------|
| Coinbase | 1.4% | 2.0% gross (0.6% net) |
| Kraken | 0.36% | 1.0% gross (0.64% net) |
| Binance | 0.28% | 0.8% gross (0.52% net) |
| OKX | 0.3% | 0.8% gross (0.5% net) |

This ensures **every profit-taking exit is NET PROFITABLE** after fees.

---

## 📊 Monitoring & Verification

### Logging

Every profit-taking event is logged:

```
🎯 TAKE PROFIT TP2 HIT: BTC-USD at $42,150.00 (PnL: +2.4%)
💰 STEPPED PROFIT EXIT TRIGGERED: ETH-USD
   Gross profit: 3.2% | Net profit: 1.8%
   Exit level: tp_exit_3.0pct | Exit size: 25% of position
```

### Statistics

The system tracks:
- Total profit checks performed
- Profit opportunities found
- Profits taken by tier
- Profits taken by broker
- Profit discovery rate

---

## 🔒 Technical Implementation

### Code Location

**Primary Implementation:**
- `bot/nija_apex_strategy_v71.py` - Main strategy with profit-taking logic
- `bot/execution_engine.py` - `check_take_profit_hit()` and `check_stepped_profit_exits()`
- `bot/risk_manager.py` - `calculate_take_profit_levels()`

**Monitoring & Guardrails:**
- `bot/profit_monitoring_guardian.py` - Independent profit monitoring
- `config/__init__.py` - Default `enable_take_profit: True`

### Enforcement

In `nija_apex_strategy_v71.py` initialization:

```python
# PROFIT-TAKING ENFORCEMENT: Always enabled, cannot be disabled
# This ensures profit-taking works 24/7 on all accounts, brokerages, and tiers
self.config['enable_take_profit'] = True
```

This **hard-codes** profit-taking to always be enabled, overriding any configuration.

---

## ⚠️ Important Notes

### What Profit-Taking Does NOT Mean

❌ **Does NOT guarantee profits on every trade**
- Market conditions matter
- Some trades will hit stop loss before take profit
- This is normal and expected

✅ **DOES guarantee profit-taking ATTEMPTS**
- If price reaches take profit level, exit WILL be attempted
- All open positions WILL be checked every cycle
- No profit opportunity will be missed due to disabled logic

### Edge Cases

The system handles:
- **Network failures** - Retries with exponential backoff
- **API rate limits** - Automatic throttling and delays
- **Broker outages** - Multi-broker setups provide redundancy
- **Price gaps** - Stepped exits catch profits at multiple levels

---

## 🚀 Usage

### For Users

**You don't need to do anything!** Profit-taking is automatic.

Just ensure:
1. Bot is running (check logs for "NIJA Apex Strategy v7.1 initialized")
2. You have open positions
3. Positions reach profit targets

### For Developers

To verify profit-taking is active:

```python
from bot.profit_monitoring_guardian import ensure_profit_taking_always_on

# Call at startup
ensure_profit_taking_always_on()
```

To monitor profit statistics:

```python
from bot.profit_monitoring_guardian import ProfitMonitoringGuardian

# Initialize guardian
guardian = ProfitMonitoringGuardian(execution_engine, risk_manager)

# Check positions
recommendations = guardian.check_all_positions_for_profit(current_prices)

# Log statistics
guardian.log_status()
```

---

## 📖 Related Documentation

- `APEX_V71_DOCUMENTATION.md` - Complete strategy documentation
- `BROKER_INTEGRATION_GUIDE.md` - Broker-specific configurations
- `RISK_PROFILES_GUIDE.md` - Tier-specific risk management
- `TRADE_EXECUTION_GUARDS.md` - Safety mechanisms

---

## ✅ Verification Checklist

Use this checklist to verify profit-taking is working:

- [ ] Bot logs show "PROFIT-TAKING: ALWAYS ENABLED" at startup
- [ ] Open positions are checked every 2.5 minutes
- [ ] Logs show profit level checks (TP1/TP2/TP3 or stepped exits)
- [ ] When profit target is hit, exit is attempted and logged
- [ ] Works across different brokers (if using multi-broker setup)
- [ ] Works across different account tiers

---

## 🔍 Troubleshooting

### "I don't see profit-taking happening"

**Possible reasons:**
1. **Position hasn't reached profit target yet** - Check current price vs. entry price
2. **Position is in loss** - Profit-taking only triggers when profitable
3. **Stop loss hit first** - Normal trading outcome
4. **Bot not running** - Check bot status and logs

**How to verify:**
```bash
# Check bot logs for profit monitoring
grep "PROFIT" nija.log

# Check for take profit level logging
grep "TP[123]" nija.log
grep "STEPPED PROFIT" nija.log
```

### "Profit target seems wrong for my broker"

Each broker has **fee-adjusted** profit targets. Check `BROKER_INTEGRATION_GUIDE.md` for broker-specific targets.

---

## 📞 Support

If you believe profit-taking is not working correctly:

1. **Check logs** for profit-related messages
2. **Verify positions** are actually profitable
3. **Review broker fees** to understand net profit calculations
4. **Open an issue** with logs and position details

---

**Last Updated:** January 22, 2026  
**Maintained By:** NIJA Trading Systems  
**Version:** 1.0
