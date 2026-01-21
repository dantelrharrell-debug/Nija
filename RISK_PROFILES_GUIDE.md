# NIJA Risk Profile Configuration Guide

## Overview

NIJA now supports **three distinct risk profiles** optimized for different trading styles, capital levels, and risk tolerances:

1. **MASTER** - Professional trader with high capital
2. **RETAIL** - Active retail trader with moderate capital
3. **INVESTOR_SAFE** - Conservative investor prioritizing capital preservation

Each profile has been carefully tuned with appropriate risk parameters, position limits, and circuit breakers.

---

## 📊 Profile Comparison Table

| Parameter | MASTER | RETAIL | INVESTOR_SAFE |
|-----------|--------|--------|---------------|
| **Recommended Capital** | $1,000+ | $100-$1,000 | $50+ |
| **Risk Level** | Moderate-High | Moderate | Low |
| **Experience Required** | Professional | Intermediate | Beginner-Friendly |
| **Max Risk Per Trade** | 3% | 2% | 1% |
| **Min Risk/Reward** | 1.5:1 | 2:1 | 3:1 |
| **Max Daily Loss** | 5% | 3% | 1.5% |
| **Max Weekly Loss** | 10% | 6% | 3% |
| **Max Total Exposure** | 60% | 40% | 20% |
| **Max Drawdown** | 15% | 10% | 5% |
| **Max Concurrent Positions** | 10 | 5 | 3 |
| **Max Position Size** | 15% | 10% | 8% |
| **Consecutive Loss Limit** | 5 | 3 | 2 |
| **Max Daily Trades** | 50 | 30 | 15 |
| **Min Time Between Trades** | 30 sec | 60 sec | 5 min |

---

## 🎯 Profile 1: MASTER Account

### When to Use
✅ You have **$1,000+ capital**  
✅ You are an **experienced trader** with proven track record  
✅ You can **actively monitor** positions throughout the day  
✅ You understand **advanced risk management** concepts  
✅ You can **handle higher volatility** in your P&L  

### Key Features
- **Aggressive position sizing**: Up to 3% risk per trade
- **High diversification**: Up to 10 concurrent positions
- **Flexible risk/reward**: Accepts 1.5:1 setups for high-quality trades
- **High daily volume**: Up to 50 trades per day
- **Extended drawdown tolerance**: 15% before stopping
- **Fast execution**: 30-second minimum between trades

### Risk Management
- Circuit breaker at **5 consecutive losses**
- Position sizing reduces at **8% drawdown**
- Trading stops at **15% drawdown**
- Daily loss limit: **5%**
- Weekly loss limit: **10%**

### Recommended For
- Professional day traders
- Funded accounts with professional management
- Experienced traders with proven strategies
- High-capital accounts ($1,000+)

### Configuration
```bash
export RISK_PROFILE=MASTER
```

---

## 👥 Profile 2: RETAIL User (Default)

### When to Use
✅ You have **$100-$1,000 capital**  
✅ You are an **intermediate trader** learning the markets  
✅ You want **balanced risk/reward**  
✅ You can check positions **several times per day**  
✅ You prefer **sustainable growth** over aggressive returns  

### Key Features
- **Balanced position sizing**: Up to 2% risk per trade
- **Moderate diversification**: Up to 5 concurrent positions
- **Quality-focused**: Requires 2:1 risk/reward minimum
- **Active trading**: Up to 30 trades per day
- **Standard protection**: 10% maximum drawdown
- **Controlled pacing**: 60-second minimum between trades

### Risk Management
- Circuit breaker at **3 consecutive losses**
- Position sizing reduces at **5% drawdown**
- Trading stops at **10% drawdown**
- Daily loss limit: **3%**
- Weekly loss limit: **6%**

### Recommended For
- Active retail traders
- Intermediate-level traders
- Moderate capital accounts ($100-$1,000)
- Traders building their track record

### Configuration
```bash
export RISK_PROFILE=RETAIL
# Or simply don't set RISK_PROFILE (this is the default)
```

---

## 🛡️ Profile 3: INVESTOR_SAFE

### When to Use
✅ You are **risk-averse** and prioritize capital preservation  
✅ You have **any capital size** but want maximum protection  
✅ You prefer **hands-off trading** with minimal monitoring  
✅ You are a **beginner trader** learning the system  
✅ You want **strict loss limits** and conservative positions  

### Key Features
- **Ultra-conservative sizing**: Only 1% risk per trade
- **Minimal diversification**: Maximum 3 concurrent positions
- **High-quality only**: Requires 3:1 risk/reward minimum
- **Selective trading**: Maximum 15 trades per day
- **Strict protection**: 5% maximum drawdown
- **Deliberate pacing**: 5-minute minimum between trades

### Risk Management
- Circuit breaker at **2 consecutive losses**
- Position sizing reduces at **3% drawdown**
- Trading stops at **5% drawdown**
- Daily loss limit: **1.5%**
- Weekly loss limit: **3%**

### Recommended For
- Risk-averse investors
- Complete beginners
- Small accounts ($50-$100)
- Hands-off investors
- Testing/learning mode

### Configuration
```bash
export RISK_PROFILE=INVESTOR
```

---

## 🔧 Setup Instructions

### Option 1: Manual Profile Selection

Add to your `.env` file:

```env
# Choose one:
RISK_PROFILE=MASTER        # For professional traders
RISK_PROFILE=RETAIL        # For active retail traders (default)
RISK_PROFILE=INVESTOR      # For conservative investors
```

### Option 2: Automatic Profile Selection

Set the profile to `AUTO` and it will automatically select based on your account balance:

```env
RISK_PROFILE=AUTO
ACCOUNT_BALANCE=500.00     # Your current balance
```

**Auto-Selection Logic:**
- Balance >= $1,000 → **MASTER** profile
- Balance >= $100 → **RETAIL** profile
- Balance < $100 → **INVESTOR_SAFE** profile

### Option 3: No Configuration (Default)

If you don't set `RISK_PROFILE`, the system defaults to **RETAIL** profile.

---

## 📈 Performance Expectations

### MASTER Profile
**Target Returns**: 10-20% monthly (high variance)  
**Expected Win Rate**: 50-60%  
**Expected Drawdowns**: 10-15% (recovered within weeks)  
**Trading Frequency**: Very active (daily trades)  
**Monitoring Required**: High (active management)

### RETAIL Profile
**Target Returns**: 5-10% monthly (moderate variance)  
**Expected Win Rate**: 55-65%  
**Expected Drawdowns**: 5-10% (recovered within weeks)  
**Trading Frequency**: Active (regular trades)  
**Monitoring Required**: Moderate (daily check-ins)

### INVESTOR_SAFE Profile
**Target Returns**: 2-5% monthly (low variance)  
**Expected Win Rate**: 60-70% (quality focus)  
**Expected Drawdowns**: 2-5% (recovered quickly)  
**Trading Frequency**: Selective (quality over quantity)  
**Monitoring Required**: Low (weekly check-ins)

---

## 🔄 Profile Migration

### Upgrading from INVESTOR → RETAIL

When your account grows or you gain experience:

1. Update your `.env`:
   ```env
   RISK_PROFILE=RETAIL
   ```

2. Restart the bot:
   ```bash
   ./start.sh
   ```

3. Monitor closely for first week
4. Review performance after 2 weeks

### Upgrading from RETAIL → MASTER

When you reach professional level:

1. Ensure **minimum $1,000 capital**
2. Review your **win rate** (should be >55%)
3. Verify you can **actively monitor** positions
4. Update configuration:
   ```env
   RISK_PROFILE=MASTER
   ```

5. Start with reduced position sizes initially
6. Gradually increase to full MASTER parameters

### Downgrading (Risk Reduction)

If experiencing losses or reducing capital:

1. **Immediate**: Switch to INVESTOR_SAFE
   ```env
   RISK_PROFILE=INVESTOR
   ```

2. **Let existing positions close** (don't force exit)
3. **Review what went wrong** before resuming
4. **Rebuild slowly** with conservative profile

---

## ⚠️ Important Warnings

### DO NOT Override Safety Features

All profiles include circuit breakers for protection:
- Consecutive loss limits
- Daily/weekly loss limits
- Drawdown protection
- Position concentration limits

**Never disable these manually** - they exist to protect your capital.

### Profile Mismatch Risks

❌ **Using MASTER with <$1,000**: Risk of rapid account depletion  
❌ **Using INVESTOR with >$5,000**: Severe underutilization of capital  
❌ **Frequent profile switching**: Inconsistent risk management  

✅ **Pick appropriate profile for your capital and experience**  
✅ **Stay with profile for at least 30 days**  
✅ **Only change based on performance or capital changes**

### Capital Requirements

| Profile | Minimum | Recommended | Optimal |
|---------|---------|-------------|---------|
| **MASTER** | $500 | $1,000+ | $5,000+ |
| **RETAIL** | $50 | $100-$1,000 | $500-$2,000 |
| **INVESTOR** | $20 | $50-$500 | $100-$500 |

---

## 🧪 Testing Recommendations

### Paper Trading First

Before going live with any profile:

1. Enable **paper trading mode**:
   ```env
   LIVE_MODE=false
   ```

2. Run for **minimum 2 weeks**
3. Review **all key metrics**:
   - Win rate
   - Average win/loss
   - Maximum drawdown
   - Daily P&L volatility

4. Only switch to live when **comfortable with results**

### Profile Testing Sequence

For new users, we recommend this progression:

1. **Week 1-2**: INVESTOR_SAFE (paper trading)
2. **Week 3-4**: INVESTOR_SAFE (live, small capital)
3. **Week 5-8**: RETAIL (paper trading)
4. **Week 9+**: RETAIL (live, moderate capital)
5. **After 3+ months**: Consider MASTER (if capital and performance justify)

---

## 📊 Monitoring Your Profile

### Key Metrics to Track

**Daily:**
- Current drawdown %
- Open positions count
- Daily P&L
- Win rate (recent 10 trades)

**Weekly:**
- Weekly P&L
- Consecutive wins/losses
- Average position hold time
- Circuit breaker triggers

**Monthly:**
- Total return %
- Maximum drawdown
- Sharpe ratio
- Total trades executed

### Warning Signs

🚨 **Consider downgrading if:**
- Hitting max drawdown repeatedly
- Win rate <45% for 30+ days
- Frequent circuit breaker triggers
- High stress from position monitoring
- Account below recommended minimum

✅ **Consider upgrading if:**
- Consistently profitable (60%+ win rate)
- Rarely hit drawdown limits
- Capital significantly increased
- Comfortable with current risk level
- Proven track record (3+ months)

---

## 🔍 Advanced Configuration

### Custom Profile Overrides

For advanced users, you can override specific parameters:

```python
# In your startup script or config
import os
os.environ['RISK_PROFILE'] = 'RETAIL'

# Override specific parameters
from bot.apex_config import RISK_CONFIG
RISK_CONFIG['max_risk_per_trade'] = 0.015  # 1.5% instead of 2%
RISK_CONFIG['max_concurrent_positions'] = 3  # 3 instead of 5
```

**⚠️ Warning**: Only do this if you fully understand the implications.

### Exchange-Specific Adjustments

Different exchanges may require profile adjustments:

**Kraken** (Low fees): Can use standard profile parameters  
**Coinbase** (High fees): Consider reducing position sizes by 20-30%  
**OKX** (Very low fees): Can be slightly more aggressive  

See `EXCHANGE_PROFILES` in `apex_config.py` for exchange-specific settings.

---

## 📚 Related Documentation

- **`USER_MANAGEMENT.md`** - User tier and permission system
- **`SMALL_ACCOUNT_QUICKSTART.md`** - Specific guidance for <$100 accounts
- **`APEX_V71_DOCUMENTATION.md`** - Complete strategy documentation
- **`COPY_TRADING_SETUP.md`** - Multi-account copy trading
- **`bot/apex_config.py`** - Full configuration file

---

## 💡 Best Practices

### 1. Start Conservative
Begin with **INVESTOR_SAFE** even if you have capital for higher profiles. Prove your system works before increasing risk.

### 2. Match Profile to Capital
Use the recommended capital ranges. Don't use MASTER profile with $200 capital.

### 3. Don't Override Safety
Circuit breakers and drawdown limits exist for protection. Never disable them.

### 4. Monitor Regularly
Even with automatic risk management, review your positions and performance regularly.

### 5. Respect Circuit Breakers
If the system stops trading due to losses, **don't immediately restart**. Review what went wrong.

### 6. Gradual Upgrades
When upgrading profiles, start with reduced position sizes and gradually increase.

### 7. Document Changes
Keep a log of when you change profiles and why. Review periodically.

---

## ❓ FAQ

**Q: Can I use MASTER profile with $500?**  
A: Not recommended. MASTER profile assumes $1,000+ for proper diversification. Use RETAIL instead.

**Q: Which profile is safest?**  
A: INVESTOR_SAFE is the most conservative with strictest limits.

**Q: Can I switch profiles mid-day?**  
A: Yes, but it only affects **new positions**. Existing positions follow original risk parameters.

**Q: What if I have $2,000 but I'm a beginner?**  
A: Start with INVESTOR_SAFE or RETAIL despite higher capital. Experience matters more than capital.

**Q: Do profiles affect copy trading?**  
A: Yes - follower accounts use their own risk profiles, so positions may be scaled differently.

**Q: Can I create a custom profile?**  
A: Advanced users can modify `apex_config.py` directly, but we recommend using built-in profiles first.

---

## 🆘 Support

For issues with risk profiles:

1. **Check logs**: `logs/nija_apex.log`
2. **Verify environment**: `echo $RISK_PROFILE`
3. **Review configuration**: Check `.env` file
4. **Check balance**: Ensure sufficient capital for profile
5. **Review documentation**: See related guides above

---

**Version**: 1.0  
**Last Updated**: January 21, 2026  
**Status**: ✅ Production Ready  
**Profiles Available**: MASTER, RETAIL, INVESTOR_SAFE
