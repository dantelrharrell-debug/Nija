# NIJA User Trading Tiers

## Overview

NIJA uses **five official trading tiers** optimized for different capital levels, experience, and trading goals. Each tier is precisely calibrated with appropriate risk parameters, position limits, and capital requirements.

**Official Tiers (Updated Jan 22, 2026):**
1. **SAVER/Starter** ($10-$25) - Learn the system (Coinbase-only or disabled on Kraken)
2. **INVESTOR** ($25-$100) - DEFAULT tier for new users
3. **INCOME** ($100-$500) - ⭐ **NIJA's core retail power tier**
4. **LIVABLE** ($500-$2,500) - Stable returns, serious users
5. **BALLER** ($2,500+) - Scale capital, precision deployment

**System Authority:**
- **MASTER** - Strategy governance and execution authority (NOT a user tier)

**Important Note on Kraken:** Kraken enforces a $10 minimum trade size. The SAVER tier is recommended for Coinbase only, or users should upgrade to INVESTOR tier ($25+) when using Kraken.

Each tier has been carefully tuned to maximize performance while managing risk appropriately for the capital level.

---

## 📊 Tier Comparison Table

| Parameter | SAVER/Starter | INVESTOR | INCOME ⭐ | LIVABLE | BALLER |
|-----------|---------------|----------|----------|---------|--------|
| **Capital Range** | $10-$25 | $25-$100 | $100-$500 | $500-$2,500 | $2,500+ |
| **Risk Per Trade** | 10-15% | 7-10% | 4-7% | 2-4% | 1-2% |
| **Trade Size** | $10-$25 | $10-$25 | $15-$50 | $25-$100 | $50-$500 |
| **Max Positions** | 1 | 2-3 | 3-5 | 5-6 | 6-8 |
| **Trading Frequency** | Low | Moderate | Active | Selective | Precision |
| **Experience Level** | Beginner | Intermediate | Active Trader | Serious User | Capital Deployer |
| **Primary Goal** | Learn System | Build Consistency | Generate Returns | Stable Returns | Preserve Dominance |
| **Exchange Support** | Coinbase** | All | All | All | All |

**Default Tier**: **INVESTOR** ($25-$100) - "Where NIJA starts to feel 'real'"

** SAVER tier: Coinbase-only recommended due to Kraken $10 minimum

---

## 🌱 TIER 1: SAVER/Starter ($10-$25)

### Goal
**"Protect capital. Learn the system."**

### When to Use
✅ You have **$10-$25 capital**  
✅ You are **new to algorithmic trading**  
✅ You want to **validate system execution** before scaling  
✅ You prioritize **learning over profits**  
✅ You understand this tier is **not for income generation**
⚠️ **You are using Coinbase** (Kraken minimum is $10, limiting trade options)

### Tier Specifications
- **Risk Per Trade**: 10-15%
- **Trade Size**: $10-$25
- **Max Positions**: 1
- **Trading Frequency**: Low (selective only)
- **Experience Required**: Beginner
- **Recommended Exchange**: Coinbase (Kraken has $10 minimum trade size)

### Key Features
- **Capital preservation focus**: Validates execution without risking significant capital
- **Single position limit**: Keeps risk extremely concentrated and manageable
- **Exchange-aware sizing**: Minimum trade sizes respect Kraken $10 minimum
- **Low frequency**: Only highest-conviction setups
- **Learning mode**: Understand NIJA's behavior before committing more capital

### Important Notes
> ⚠️ **NOT FOR INCOME**: This tier validates execution and teaches the system. Don't expect meaningful profits.
> 
> ✅ **VALIDATION TIER**: Learn how NIJA executes, manages positions, and handles risk before upgrading.
>
> ⚠️ **KRAKEN LIMITATION**: Kraken enforces a $10 minimum trade size. With $10-$25 capital and $10-$25 trade sizes, you'll be limited to a single trade at a time. Consider using Coinbase for more flexibility in this tier, or upgrade to INVESTOR tier ($25+) for better capital utilization.

### Who Should Use This
- Complete beginners to crypto trading
- Users validating NIJA before depositing more capital
- Anyone with $10-$25 who wants to start small
- Traders learning algorithmic execution
- Users with Coinbase accounts (recommended over Kraken for this tier)

### Configuration
```bash
# Add to .env
TRADING_TIER=SAVER
```

Or use the preset template:
```bash
cp .env.saver_tier .env
# Edit .env and add your API credentials
```

---

## 📊 TIER 2: INVESTOR ($25-$100) - DEFAULT

### Goal
**"Build consistency. Reduce randomness."**

### When to Use
✅ You have **$25-$100 capital**  
✅ You are **learning systematic trading**  
✅ You want **NIJA to feel 'real'** without huge risk  
✅ You can monitor positions **once or twice daily**  
✅ You're building **trading consistency**

### Tier Specifications
- **Risk Per Trade**: 7-10%
- **Trade Size**: $10-$25
- **Max Positions**: 2-3
- **Trading Frequency**: Moderate
- **Experience Required**: Beginner to Intermediate
- **Exchange Support**: All exchanges (meets Kraken $10 minimum)

### Key Features
- **Balanced approach**: Enough capital to see meaningful results
- **Multiple positions**: 2-3 concurrent trades for diversification
- **Real execution**: Trade sizes feel substantial, not trivial
- **Moderate frequency**: Active enough to build experience
- **Default tier**: This is where most users start
- **Exchange flexibility**: Works with all exchanges including Kraken

### Important Notes
> ✅ **DEFAULT TIER**: If you don't specify a tier, you get INVESTOR.
> 
> 📈 **"NIJA Starts to Feel Real"**: This is the minimum capital where NIJA's performance becomes noticeable.
> 
> 🎯 **CONSISTENCY FOCUS**: Build repeatable results, reduce random outcomes.

### Who Should Use This
- New NIJA users with $25-$100
- Traders learning systematic approaches
- Users upgrading from SAVER tier
- Anyone wanting to see NIJA perform without major risk
- Users with Kraken accounts (meets $10 minimum)

### Configuration
```bash
# Add to .env
TRADING_TIER=INVESTOR

# Or don't set it - INVESTOR is the default
```

Or use the preset template:
```bash
cp .env.investor_tier .env
# Edit .env and add your API credentials
```

---

## ⭐ TIER 3: INCOME ($100-$500) - CORE RETAIL POWER TIER

### Goal
**"Generate repeatable returns."**

### When to Use
✅ You have **$100-$500 capital**  
✅ You want **meaningful income generation**  
✅ You are an **active retail trader**  
✅ You can monitor positions **regularly**  
✅ You understand this is **NIJA's sweet spot**

### Tier Specifications
- **Risk Per Trade**: 4-7%
- **Trade Size**: $15-$50
- **Max Positions**: 3-5
- **Trading Frequency**: Active but selective
- **Experience Required**: Intermediate to Advanced

### Key Features
- **⭐ CORE RETAIL POWER TIER**: This is where NIJA delivers maximum retail performance
- **Income generation**: Capital sufficient for repeatable, meaningful returns
- **Active diversification**: 3-5 positions for balanced exposure
- **Optimal trade sizes**: $15-$50 positions hit the sweet spot
- **Selective activity**: High-confidence setups with active execution
- **Professional feel**: This tier operates like a small trading account

### Important Notes
> ⭐ **NIJA'S CORE RETAIL POWER TIER**: This is the sweet spot for retail algorithmic trading.
> 
> 💰 **INCOME GENERATION**: First tier designed to generate repeatable returns, not just learn or test.
> 
> 🎯 **ACTIVE RETAIL FOCUS**: Perfect balance of capital, frequency, and position management.

### Who Should Use This
- Active retail traders with proven experience
- Users upgrading from INVESTOR tier
- Traders seeking income from algorithmic trading
- Anyone with $100-$500 wanting optimal NIJA performance

### Performance Expectations
- **Monthly Return Target**: 8-15%
- **Win Rate Target**: 60-70%
- **Drawdown Tolerance**: Moderate (5-8%)
- **Trading Style**: Active, selective, high-conviction

### Configuration
```bash
# Add to .env
TRADING_TIER=INCOME
```

Or use the preset template:
```bash
cp .env.income_tier .env
# Edit .env and add your API credentials
```

---

## 💼 TIER 4: LIVABLE ($500-$2,500)

### Goal
**"Stable returns. Capital protection."**

### When to Use
✅ You have **$500-$2,500 capital**  
✅ You are a **serious trader**, not a gambler  
✅ You want **consistent, stable returns**  
✅ You prioritize **capital protection** over aggressive growth  
✅ You understand **professional risk management**

### Tier Specifications
- **Risk Per Trade**: 2-4%
- **Trade Size**: $25-$100
- **Max Positions**: 5-6
- **Trading Frequency**: Selective, high-confidence only
- **Experience Required**: Advanced

### Key Features
- **Serious capital deployment**: $500+ requires professional approach
- **Capital protection focus**: Preserve account, generate stable returns
- **Lower risk per trade**: 2-4% ensures longevity
- **Diversified positions**: 5-6 concurrent positions spread risk
- **Selective execution**: Only high-confidence setups
- **Professional management**: This tier is for serious users

### Important Notes
> 💼 **SERIOUS USERS, NOT GAMBLERS**: This tier is for traders who respect capital and understand risk.
> 
> 🛡️ **CAPITAL PROTECTION FIRST**: Stable, repeatable returns prioritized over aggressive speculation.
> 
> 📊 **PROFESSIONAL APPROACH**: Disciplined, selective, and systematic execution.

### Who Should Use This
- Serious retail traders with proven track records
- Users with $500-$2,500 seeking stable returns
- Traders upgrading from INCOME tier
- Anyone prioritizing capital preservation over aggressive growth

### Performance Expectations
- **Monthly Return Target**: 5-10%
- **Win Rate Target**: 65-75%
- **Drawdown Tolerance**: Low (3-5%)
- **Trading Style**: Selective, precision-focused, systematic

### Configuration
```bash
# Add to .env
TRADING_TIER=LIVABLE
```

Or use the preset template:
```bash
cp .env.livable_tier .env
# Edit .env and add your API credentials
```

---

## 🏆 TIER 5: BALLER ($2,500+)

### Goal
**"Scale capital. Preserve dominance."**

### When to Use
✅ You have **$2,500+ capital**  
✅ You are **deploying capital**, not speculating  
✅ You want **precision execution** with minimal risk  
✅ You can **manage large positions** professionally  
✅ You understand this is **capital deployment, not gambling**

### Tier Specifications
- **Risk Per Trade**: 1-2%
- **Trade Size**: $50-$500
- **Max Positions**: 6-8
- **Trading Frequency**: Precision-only (highest conviction)
- **Experience Required**: Professional

### Key Features
- **Capital deployment**: Scale large sums systematically
- **Ultra-low risk**: 1-2% per trade preserves capital at scale
- **High diversification**: 6-8 positions spread risk across markets
- **Precision execution**: Only absolute highest-conviction setups
- **Professional-grade**: Institutional-quality risk management
- **Dominance preservation**: Protect and grow significant capital

### Important Notes
> 🏆 **CAPITAL DEPLOYMENT, NOT SPECULATION**: This tier is for scaling capital, not chasing returns.
> 
> 💎 **PRESERVE DOMINANCE**: Protect large capital while generating consistent returns.
> 
> 🎯 **PRECISION-ONLY**: Ultra-selective execution. Quality over quantity.

### Who Should Use This
- Professional traders with $2,500+ accounts
- Funded accounts requiring institutional risk management
- Traders scaling from LIVABLE tier
- Anyone deploying significant capital systematically

### Performance Expectations
- **Monthly Return Target**: 3-8%
- **Win Rate Target**: 70-80%
- **Drawdown Tolerance**: Minimal (2-3%)
- **Trading Style**: Precision, systematic, professional-grade

### Configuration
```bash
# Add to .env
TRADING_TIER=BALLER
```

Or use the preset template:
```bash
cp .env.baller_tier .env
# Edit .env and add your API credentials
```

---

## 🔐 MASTER - System Authority (NOT A USER TIER)

### Role
**Strategy governance and execution authority**

### What MASTER Is
- **Signal Generation**: Creates trading signals from market analysis
- **Risk Enforcement**: Enforces tier-specific risk parameters
- **Multi-Exchange Coordination**: Manages cross-exchange execution
- **Strategy Authority**: Governs profit logic and position management

### What MASTER Is NOT
- ❌ **NOT a user-facing tier**: Users cannot select MASTER as their tier
- ❌ **NOT for profit trading**: MASTER governs logic, doesn't trade for profit
- ❌ **NOT higher capital requirement**: This is system infrastructure, not a capital tier

### Important Notes
> 🔐 **SYSTEM AUTHORITY ONLY**: MASTER is the strategy source and execution coordinator.
> 
> ⚙️ **GOVERNS PROFIT LOGIC**: MASTER defines how profits are generated, not generates them itself.
> 
> 🚫 **NOT USER-SELECTABLE**: Users choose from SAVER, INVESTOR, INCOME, LIVABLE, or BALLER.

### MASTER Functions
1. **Strategy Definition**: Defines entry/exit logic, indicators, and filters
2. **Risk Parameter Enforcement**: Ensures tier-specific limits are respected
3. **Multi-Account Coordination**: Synchronizes copy trading and multi-user execution
4. **System Monitoring**: Tracks overall system health and performance
5. **Emergency Controls**: Circuit breakers, kill switches, and emergency stops

---

## 🔧 Setup Instructions

### Option 1: Manual Tier Selection

Add to your `.env` file:

```env
# Choose your tier:
TRADING_TIER=SAVER       # For $25-$99 capital
TRADING_TIER=INVESTOR    # For $100-$249 capital (default)
TRADING_TIER=INCOME      # For $250-$999 capital (⭐ core retail tier)
TRADING_TIER=LIVABLE     # For $1k-$5k capital
TRADING_TIER=BALLER      # For $5k+ capital
```

### Option 2: Use Preset Templates

Copy the appropriate template for your tier:

```bash
# SAVER tier ($25-$99)
cp .env.saver_tier .env

# INVESTOR tier ($100-$249)
cp .env.investor_tier .env

# INCOME tier ($250-$999) ⭐
cp .env.income_tier .env

# LIVABLE tier ($1k-$5k)
cp .env.livable_tier .env

# BALLER tier ($5k+)
cp .env.baller_tier .env
```

Then edit `.env` and add your exchange API credentials.

### Option 3: Automatic Tier Selection

Set the tier to `AUTO` and it will automatically select based on your account balance:

```env
TRADING_TIER=AUTO
ACCOUNT_BALANCE=500.00     # Your current balance
```

**Auto-Selection Logic:**
- Balance < $100 → **SAVER** tier
- Balance $100-$249 → **INVESTOR** tier (default)
- Balance $250-$999 → **INCOME** tier
- Balance $1k-$5k → **LIVABLE** tier
- Balance >= $5k → **BALLER** tier

### Option 4: No Configuration (Uses Default)

If you don't set `TRADING_TIER`, the system defaults to **INVESTOR** tier.

---

## 📈 Performance Expectations by Tier

### SAVER Tier ($25-$99)
**Target Returns**: Validation mode - not income-focused  
**Expected Win Rate**: Learning phase  
**Expected Drawdowns**: Minimal due to small positions  
**Trading Frequency**: Very low (selective only)  
**Monitoring Required**: Weekly check-ins  
**Primary Focus**: Learning system behavior

### INVESTOR Tier ($100-$249)
**Target Returns**: 5-10% monthly  
**Expected Win Rate**: 55-65%  
**Expected Drawdowns**: 5-8%  
**Trading Frequency**: Moderate (several trades weekly)  
**Monitoring Required**: Daily check-ins  
**Primary Focus**: Building consistency

### INCOME Tier ($250-$999) ⭐
**Target Returns**: 8-15% monthly  
**Expected Win Rate**: 60-70%  
**Expected Drawdowns**: 5-8%  
**Trading Frequency**: Active (daily trades)  
**Monitoring Required**: Multiple daily check-ins  
**Primary Focus**: Repeatable income generation

### LIVABLE Tier ($1k-$5k)
**Target Returns**: 5-10% monthly  
**Expected Win Rate**: 65-75%  
**Expected Drawdowns**: 3-5%  
**Trading Frequency**: Selective (high-confidence only)  
**Monitoring Required**: Daily monitoring  
**Primary Focus**: Stable, consistent returns

### BALLER Tier ($5k+)
**Target Returns**: 3-8% monthly  
**Expected Win Rate**: 70-80%  
**Expected Drawdowns**: 2-3%  
**Trading Frequency**: Precision-only (ultra-selective)  
**Monitoring Required**: Regular professional monitoring  
**Primary Focus**: Capital preservation and systematic growth

---

## 🔄 Tier Migration & Upgrade Paths

### Recommended Progression

```
SAVER ($25-$99)
    ↓ [Validate system, learn execution]
INVESTOR ($100-$249)
    ↓ [Build consistency, prove profitability]
INCOME ($250-$999) ⭐
    ↓ [Generate repeatable returns, scale capital]
LIVABLE ($1k-$5k)
    ↓ [Stable returns, professional management]
BALLER ($5k+)
```

### When to Upgrade

**SAVER → INVESTOR**
- ✅ You understand how NIJA executes
- ✅ You've validated the system works
- ✅ You're ready to increase capital to $100+
- ✅ You want to see meaningful results

**INVESTOR → INCOME**
- ✅ You've built consistency (60%+ win rate)
- ✅ Your account has grown to $250+
- ✅ You want to generate actual income
- ✅ You can monitor positions actively

**INCOME → LIVABLE**
- ✅ You have $1,000+ capital
- ✅ You've proven profitability in INCOME tier
- ✅ You want lower risk, stable returns
- ✅ You prioritize capital protection

**LIVABLE → BALLER**
- ✅ You have $5,000+ capital
- ✅ You have a proven long-term track record
- ✅ You understand professional risk management
- ✅ You want to deploy significant capital systematically

### How to Upgrade

1. **Verify Capital Requirements**: Ensure you meet minimum for new tier
2. **Review Performance**: Check win rate and consistency metrics
3. **Update Configuration**:
   ```bash
   # Edit .env
   TRADING_TIER=INCOME  # Or whatever tier you're upgrading to
   ```
4. **Restart Bot**:
   ```bash
   ./start.sh
   ```
5. **Monitor Closely**: Watch first week of new tier performance
6. **Review After 2 Weeks**: Validate upgrade was appropriate

### When to Downgrade

Consider downgrading if:
- 🚨 Account balance drops below tier minimum
- 🚨 Experiencing repeated circuit breaker triggers
- 🚨 Win rate drops below 45% for 30+ days
- 🚨 Maximum drawdown hit repeatedly
- 🚨 High stress from position monitoring

**Downgrade Process**:
1. **Immediate**: Change tier in `.env`
   ```env
   TRADING_TIER=INVESTOR  # Or appropriate lower tier
   ```
2. **Close Existing Positions**: Don't force-exit, let them close naturally
3. **Review What Went Wrong**: Analyze logs and performance
4. **Rebuild Slowly**: Prove consistency before upgrading again

---

## ⚠️ Important Warnings & Best Practices

### DO NOT Override Safety Features

All tiers include built-in circuit breakers for protection:
- Tier-specific position limits
- Risk per trade caps
- Trading frequency controls
- Emergency stop mechanisms

**Never disable these manually** - they exist to protect your capital.

### Tier Mismatch Risks

❌ **Using INCOME tier with <$250**: Insufficient capital for diversification  
❌ **Using SAVER tier with >$500**: Severe underutilization of capital  
❌ **Frequent tier switching**: Inconsistent risk management, poor results  
❌ **Skipping tiers**: Upgrading too fast leads to poor risk management

✅ **Match tier to your capital**: Use the tier appropriate for your balance  
✅ **Stay with tier for 30+ days**: Build consistency before changing  
✅ **Only change based on capital or performance**: Don't change randomly  
✅ **Follow upgrade progression**: Don't skip tiers (SAVER → INVESTOR → INCOME → etc.)

### Capital Requirements

| Tier | Minimum | Recommended | Optimal |
|------|---------|-------------|---------|
| **SAVER** | $25 | $50-$99 | $75-$99 |
| **INVESTOR** | $100 | $150-$249 | $200-$249 |
| **INCOME** ⭐ | $250 | $400-$999 | $600-$999 |
| **LIVABLE** | $1,000 | $2,000-$5,000 | $3,000-$5,000 |
| **BALLER** | $5,000 | $10,000+ | $15,000+ |

---

## 🧪 Testing Recommendations

### Paper Trading First

Before going live with any tier:

1. Enable **paper trading mode**:
   ```env
   LIVE_MODE=false
   TRADING_TIER=INVESTOR  # Or your chosen tier
   ```

2. Run for **minimum 2 weeks**
3. Review **all key metrics**:
   - Win rate
   - Average win/loss ratio
   - Maximum drawdown
   - Daily P&L volatility
   - Position hold times

4. Only switch to live when **comfortable with results**

### Tier Testing Sequence

For new users, we recommend this progression:

1. **Week 1-2**: INVESTOR (paper trading) - Learn the system
2. **Week 3-4**: INVESTOR (live, $100-$150) - Validate with small capital
3. **Week 5-8**: Continue INVESTOR or upgrade to INCOME if capital allows
4. **Month 3+**: Consider upgrading tiers based on capital and performance

**Don't rush tier upgrades** - Build consistency first.

---

## 📊 Monitoring Your Tier

### Key Metrics to Track

**Daily:**
- Current positions count
- Open P&L
- Daily realized P&L
- Win rate (last 10 trades)
- Available capital for new positions

**Weekly:**
- Weekly P&L
- Win/loss streak
- Average position hold time
- Number of trades executed
- Any circuit breaker triggers

**Monthly:**
- Total return %
- Maximum drawdown this month
- Total trades executed
- Tier appropriateness (should you upgrade/downgrade?)

### Warning Signs

🚨 **Consider downgrading if:**
- Account balance drops below tier minimum
- Win rate <45% for 30+ days
- Frequent emergency stops or circuit breakers
- High stress monitoring positions
- Unable to meet tier's trading frequency requirements

✅ **Consider upgrading if:**
- Account grown significantly (next tier minimum met)
- Consistently profitable (60%+ win rate for 60+ days)
- Comfortable with current tier's risk
- Want more position diversification
- Current tier feels "too small"

---

## 🔍 Advanced Configuration

### Custom Tier Overrides

For advanced users who understand the implications:

```python
# In your configuration or startup script
import os
os.environ['TRADING_TIER'] = 'INCOME'

# Override specific parameters (ADVANCED ONLY)
# This is not recommended unless you fully understand risk management
from bot.apex_config import TIER_CONFIG
TIER_CONFIG['income']['max_positions'] = 4  # Override max positions
TIER_CONFIG['income']['risk_per_trade'] = 0.05  # Override risk
```

**⚠️ Warning**: Only override tier parameters if you:
- Fully understand position sizing and risk management
- Have proven profitability at standard tier settings
- Are willing to accept responsibility for custom parameters
- Have backtested custom parameters extensively

### Exchange-Specific Tier Adjustments

Different exchanges have different fee structures:

**Kraken** (Low fees 0.16%-0.26%): Use standard tier parameters  
**Coinbase** (Higher fees 0.4%-0.6%): Consider reducing position sizes by 20%  
**OKX** (Very low fees 0.08%-0.10%): Can be slightly more aggressive  

For high-fee exchanges like Coinbase:
```env
TRADING_TIER=INCOME
# Reduce position sizes for fee management
MIN_TRADE_PERCENT=0.03  # Reduce from default
MAX_TRADE_PERCENT=0.06  # Reduce from default
```

### Tier-Specific Customization

Each tier can be customized in `bot/apex_config.py`:

```python
TIER_CONFIG = {
    'saver': {...},
    'investor': {...},
    'income': {...},
    'livable': {...},
    'baller': {...}
}
```

See configuration file for complete tier specifications.

---

## 📚 Related Documentation

- **[GETTING_STARTED.md](GETTING_STARTED.md)** - Complete setup guide for new users
- **[USER_MANAGEMENT.md](USER_MANAGEMENT.md)** - Multi-user and permission system
- **[SMALL_ACCOUNT_QUICKSTART.md](SMALL_ACCOUNT_QUICKSTART.md)** - Specific guidance for SAVER tier
- **[APEX_V71_DOCUMENTATION.md](APEX_V71_DOCUMENTATION.md)** - Complete strategy documentation
- **[COPY_TRADING_SETUP.md](COPY_TRADING_SETUP.md)** - Multi-account copy trading
- **[BROKER_INTEGRATION_GUIDE.md](BROKER_INTEGRATION_GUIDE.md)** - Exchange integration details
- **[bot/apex_config.py](bot/apex_config.py)** - Full tier configuration file

---

## 💡 Best Practices

### 1. Start Conservative
Begin with **SAVER** or **INVESTOR** tier even if you have capital for higher tiers. Validate the system before increasing risk.

### 2. Match Tier to Capital
Use the tier appropriate for your account balance. Don't use BALLER parameters with $500.

### 3. Don't Override Safety
Circuit breakers, position limits, and tier controls exist for protection. Never disable them.

### 4. Monitor Regularly
Even with automatic risk management, review positions and performance metrics regularly.

### 5. Respect Circuit Breakers
If the system stops trading due to losses or limits, **don't immediately restart**. Review logs and understand what went wrong.

### 6. Gradual Upgrades
When upgrading tiers, start conservatively and monitor performance closely for 2-4 weeks.

### 7. Document Changes
Keep a log of tier changes and why you made them. Review periodically.

### 8. Follow Tier Progression
Don't skip tiers. Progress through SAVER → INVESTOR → INCOME → LIVABLE → BALLER systematically.

### 9. Use Preset Templates
Start with official `.env.{tier}_tier` templates rather than building from scratch.

### 10. Paper Trade First
Test any tier change in paper trading mode before going live.

---

## ❓ Frequently Asked Questions

**Q: Which tier should I start with?**  
A: Start with **INVESTOR** tier ($100-$249) if you have the capital. If not, start with **SAVER** ($25-$99) to validate the system.

**Q: Can I use BALLER tier with $500?**  
A: No. BALLER tier requires $5,000+ for proper diversification and position management. Use INCOME tier for $500.

**Q: What's the difference between INCOME and LIVABLE tiers?**  
A: **INCOME** is the active retail tier for generating returns. **LIVABLE** is more conservative, focusing on capital protection and stable returns for serious users.

**Q: Is MASTER a user tier?**  
A: No. **MASTER** is system authority for strategy governance and execution coordination. Users choose from SAVER, INVESTOR, INCOME, LIVABLE, or BALLER.

**Q: Can I switch tiers mid-day?**  
A: Yes, but it only affects **new positions**. Existing positions follow their original tier parameters.

**Q: Which tier is safest?**  
A: **SAVER** is the most conservative with smallest positions and lowest frequency. **INVESTOR** is the conservative default for regular trading.

**Q: What tier is best for income generation?**  
A: **INCOME** tier ($250-$999) is specifically designed for repeatable income generation. It's NIJA's core retail power tier.

**Q: Can I create a custom tier?**  
A: Advanced users can modify `bot/apex_config.py`, but we strongly recommend using built-in tiers first and proving profitability before customizing.

**Q: Do tiers affect copy trading?**  
A: Yes - follower accounts use their own tiers, so positions are scaled appropriately to each account's balance and tier.

**Q: What if I have $2,000 but I'm a beginner?**  
A: Start with **INVESTOR** tier despite higher capital. Build experience and consistency, then upgrade to LIVABLE tier after proving profitability.

**Q: How long should I stay in each tier before upgrading?**  
A: Minimum **30 days** to build consistency. Ideally **60-90 days** to prove profitability before upgrading.

**Q: What happens if my balance drops below my tier's minimum?**  
A: The system will warn you. Consider downgrading to the appropriate tier for your new balance to maintain proper risk management.

---

## 🆘 Support & Troubleshooting

### Common Issues

**Issue: "Tier not recognized"**  
Solution: Check spelling in `.env` - must be exactly `SAVER`, `INVESTOR`, `INCOME`, `LIVABLE`, or `BALLER`

**Issue: "Insufficient capital for tier"**  
Solution: Your balance is below the tier minimum. Downgrade or deposit more capital.

**Issue: "No trades executing"**  
Solution: Check if you're in SAVER tier (very low frequency) or if circuit breakers are active.

**Issue: "Position sizes too small"**  
Solution: You may be in SAVER tier with limited capital. Upgrade when appropriate.

### Checking Your Current Tier

```bash
# Check environment variable
echo $TRADING_TIER

# Check bot logs
tail -f logs/nija_apex.log | grep "tier"

# Verify in Python
python3 -c "import os; print(os.getenv('TRADING_TIER', 'INVESTOR (default)'))"
```

### Getting Help

1. **Check logs**: `logs/nija_apex.log`
2. **Verify tier config**: Check `.env` file
3. **Review tier requirements**: See tier specifications above
4. **Test in paper mode**: Set `LIVE_MODE=false`
5. **Read related documentation**: See links above

---

## 📝 Tier Selection Checklist

Before choosing your tier, answer these questions:

- [ ] What is my current account balance?
- [ ] What is my trading experience level?
- [ ] How often can I monitor positions?
- [ ] What are my profit expectations?
- [ ] Am I okay with the tier's risk per trade?
- [ ] Do I meet the minimum capital requirement?
- [ ] Have I paper-traded this tier first?
- [ ] Do I understand the tier's limitations?

**If you answered all questions confidently**, proceed with your tier selection.

**If you're uncertain**, start with **INVESTOR** tier (default) and upgrade later.

---

**Version**: 2.0  
**Last Updated**: January 2025  
**Status**: ✅ Production Ready  
**Official Tiers**: SAVER, INVESTOR, INCOME, LIVABLE, BALLER  
**System Authority**: MASTER (not user-selectable)
