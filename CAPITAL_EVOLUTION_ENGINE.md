# 🔥 CAPITAL EVOLUTION ENGINE 🔥

## YOUR AUTO-SCALING SYSTEM = CAPITAL EVOLUTION ENGINE

The **Capital Evolution Engine** is NIJA's intelligent auto-scaling system that automatically adjusts trading parameters based on your current capital. As your account grows, the system evolves through three distinct modes, each optimized for capital at that stage.

## 🚀 Three Evolution Modes

### 🔥 STARTER — SURVIVAL MODE ($15 → $249)

**Capital Range:** $15 - $249  
**Max Positions:** 3  
**Risk Per Trade:** 4%  
**Copy Trading:** DISABLED  
**Leverage:** DISABLED  
**Goal:** **ACCELERATE COMPOUNDING**

This is the foundation stage. Focus is on rapid capital growth through aggressive compounding while maintaining strict position limits to protect your small account.

**Key Features:**
- Conservative position count (3 max)
- Moderate risk per trade (4%)
- All profits reinvested for maximum compound growth
- No leverage to protect against catastrophic losses
- Single-account focus

**Best For:**
- New traders learning the system
- Small accounts building capital base
- Testing and validating strategies
- Accounts recovering from drawdowns

---

### ⚡ ADVANCED — MULTIPLIER MODE ($500 → $999)

**Capital Range:** $500 - $999  
**Max Positions:** 4  
**Risk Per Trade:** 4%  
**Copy Trading:** **ENABLED ✅**  
**Leverage:** DISABLED  
**Goal:** **MULTI-ACCOUNT SCALE**

The scaling stage. Your capital is now sufficient to support multiple positions AND copy trading to other accounts.

**Key Features:**
- Increased position capacity (4 positions)
- Same risk level (4%) - proven at STARTER
- **Copy trading activated** - scale to multiple accounts
- Still conservative on leverage
- Multi-account revenue potential

**Best For:**
- Traders ready to scale beyond single account
- Managing multiple client accounts
- Building recurring revenue through copy trading
- Proven track record at STARTER level

**Copy Trading Benefits:**
- Mirror trades to unlimited user accounts
- Proportional position sizing per account
- Single master account controls all
- Automatic trade replication

---

### 👑 ELITE — DOMINATION MODE ($1000+)

**Capital Range:** $1,000+  
**Max Positions:** 6  
**Risk Per Trade:** 5%  
**Copy Trading:** **ENABLED ✅**  
**Leverage:** **ENABLED ✅**  
**Goal:** **CAPITAL ACCELERATION + SaaS SCALE**

The domination stage. Full system capabilities unlocked. Maximum positions, increased risk tolerance, leverage enabled, and SaaS-scale copy trading.

**Key Features:**
- Maximum position capacity (6 positions)
- Elevated risk tolerance (5%)
- Copy trading at scale
- **Leverage enabled** for capital acceleration
- SaaS platform revenue potential
- Institutional-grade scaling

**Best For:**
- Established traders with proven results
- Professional trading operations
- SaaS platform operators
- Maximum capital velocity
- Building trading-as-a-service business

**Leverage Benefits:**
- Amplified position sizes
- Faster capital growth
- More opportunities captured
- Professional-grade execution

---

## 📊 Mode Transition Mechanics

### Automatic Tier Detection

The system automatically detects your current tier based on account balance:

```python
from bot.capital_evolution_engine import get_evolution_engine

# Initialize with current capital
engine = get_evolution_engine(initial_capital=100.0)

# Engine automatically sets mode to STARTER
print(engine.get_quick_summary())
# Output: 🔥 STARTER — SURVIVAL MODE | 💰 $100.00 | 🎯 3 pos | 4% risk
```

### Seamless Transitions

As your capital grows, the engine automatically transitions to the next mode:

```python
# Update capital after profitable trading
engine.update_capital(500.0)

# Engine automatically transitions to ADVANCED
# Logs transition:
# 🚀 EVOLUTION MODE TRANSITION!
# From: 🔥 STARTER — SURVIVAL MODE
#   To: ⚡ ADVANCED — MULTIPLIER MODE
# Max Positions: 3 → 4
# Copy Trading: False → True
```

### Transition Thresholds

| From Mode | To Mode | Capital Threshold | Changes |
|-----------|---------|-------------------|---------|
| STARTER | ADVANCED | $500.00 | +1 position, Copy trading ON |
| ADVANCED | ELITE | $1,000.00 | +2 positions, +1% risk, Leverage ON |

**Important:** There's a deliberate gap ($250-$499) that keeps you in STARTER mode. This prevents premature scaling before you have sufficient capital for ADVANCED tier benefits.

---

## 💻 Usage Guide

### Basic Integration

```python
from bot.capital_evolution_engine import get_evolution_engine

# 1. Initialize engine
engine = get_evolution_engine(
    initial_capital=100.0,    # Your starting capital
    current_capital=150.0     # Current balance (optional)
)

# 2. Get current configuration
max_positions = engine.get_max_positions()  # 3 (STARTER)
risk_pct = engine.get_risk_per_trade_pct()  # 4.0%
copy_enabled = engine.is_copy_trading_enabled()  # False
leverage_enabled = engine.is_leverage_enabled()  # False

# 3. Update capital after each trade
engine.update_capital(175.0)  # Returns new mode if transition occurred

# 4. Get status
status = engine.get_evolution_status()
print(f"Current Mode: {status['mode_display_name']}")
print(f"Max Positions: {status['max_positions']}")
print(f"ROI: {status['roi_pct']:.2f}%")
```

### Advanced Features

```python
# Get comprehensive status report
print(engine.get_evolution_report())

# Get quick summary
summary = engine.get_quick_summary()
# Output: 🔥 STARTER — SURVIVAL MODE | 💰 $175.00 (+75.0% ROI) | 🎯 3 pos | 4% risk | 📈 5% to next tier

# Check progress to next tier
status = engine.get_evolution_status()
if status['next_mode']:
    print(f"Progress to {status['next_mode']}: {status['progress_to_next_pct']:.1f}%")
    print(f"Need ${status['remaining_to_next']:.2f} more")

# View transition history
for transition in engine.mode_transitions:
    print(f"{transition['timestamp']} | {transition['to_mode']} | ${transition['capital']:.2f}")
```

### Integration with Trading Strategy

```python
from bot.capital_evolution_engine import get_singleton_evolution_engine
from bot.broker_integration import get_account_balance

# Initialize once at bot startup
balance = get_account_balance()
evolution_engine = get_singleton_evolution_engine(
    initial_capital=balance,
    current_capital=balance
)

# In your trading loop
def execute_trade_logic():
    # Get current balance
    current_balance = get_account_balance()
    
    # Update evolution engine
    evolution_engine.update_capital(current_balance)
    
    # Get current configuration
    max_positions = evolution_engine.get_max_positions()
    risk_pct = evolution_engine.get_risk_per_trade_pct()
    
    # Count open positions
    open_positions = get_open_position_count()
    
    # Check if we can open new position
    if open_positions >= max_positions:
        logger.info(f"Position limit reached ({max_positions} at {evolution_engine.current_mode.value})")
        return
    
    # Calculate position size with evolution risk %
    position_size = calculate_position_size(
        balance=current_balance,
        risk_pct=risk_pct
    )
    
    # Execute trade...
```

---

## 📈 Growth Scenarios

### Scenario 1: $50 → $1000 (STARTER to ELITE)

```
Initial: $50 (STARTER MODE)
  - 3 positions max
  - 4% risk per trade
  - No copy trading
  - No leverage

After growth to $500 (ADVANCED MODE)
  - 4 positions max (+1)
  - 4% risk per trade (same)
  - Copy trading ENABLED ✅
  - No leverage
  
After growth to $1000 (ELITE MODE)
  - 6 positions max (+2)
  - 5% risk per trade (+1%)
  - Copy trading ENABLED ✅
  - Leverage ENABLED ✅
```

### Scenario 2: Starting at ELITE ($5000)

```
Initial: $5000 (ELITE MODE)
  - Immediate access to all features
  - 6 positions max
  - 5% risk per trade
  - Copy trading enabled
  - Leverage enabled
  - SaaS-scale ready from day one
```

### Scenario 3: Drawdown Recovery

```
Peak: $1500 (ELITE MODE)
  - 6 positions, 5% risk, all features enabled

After drawdown to $450 (back to STARTER)
  - Automatically scales down to 3 positions
  - Reduces risk to 4%
  - Disables leverage for capital protection
  - Copy trading disabled
  - Survival mode activated

Recovery to $500+ (ADVANCED MODE)
  - Scales back up to 4 positions
  - Re-enables copy trading
  - Still conservative on leverage until $1000+
```

---

## 🎯 Best Practices

### 1. Let the System Work

Don't override the auto-scaling. The tiers are designed based on:
- Optimal position count for capital size
- Risk levels that balance growth vs. protection
- Feature activation at appropriate capital levels

### 2. Focus on Mode Goals

**STARTER:** Compound aggressively. Every dollar reinvested accelerates your path to ADVANCED.

**ADVANCED:** Build your copy trading infrastructure. This is where you scale beyond a single account.

**ELITE:** Maximize capital velocity. Use leverage wisely. Build your SaaS platform.

### 3. Track Transitions

Monitor your mode transitions. They're milestones:
- STARTER → ADVANCED: You've 10x'd from $50 or proven stability at $500+
- ADVANCED → ELITE: You've reached professional capital levels

### 4. Respect Downgrades

If you drop below a tier threshold, accept the downgrade:
- Reduced positions = risk management during drawdown
- Disabled features = capital protection
- It's temporary - focus on recovery

### 5. Use Reports

Generate evolution reports regularly:
```python
print(engine.get_evolution_report())
```

This shows:
- Your current mode and configuration
- Progress to next tier
- ROI since inception
- Transition history

---

## 🔧 Configuration

### Environment Variables

No environment variables needed! The system is fully automatic based on capital.

### Manual Override (Not Recommended)

If you absolutely need to override:

```python
# Not recommended - bypasses intelligent auto-scaling
from bot.capital_evolution_engine import EvolutionMode, EVOLUTION_CONFIGS

# Force a specific mode (for testing only)
engine.current_mode = EvolutionMode.ELITE_DOMINATION
engine.mode_config = EVOLUTION_CONFIGS[EvolutionMode.ELITE_DOMINATION]
```

**Warning:** Manual overrides defeat the purpose of the auto-scaling system. Only use for testing.

---

## 📊 Performance Tracking

### Metrics Available

```python
status = engine.get_evolution_status()

# Capital metrics
status['initial_capital']        # Starting capital
status['current_capital']        # Current balance
status['peak_capital']          # All-time high
status['total_profit']          # Total profit/loss
status['roi_pct']               # Return on investment %

# Mode metrics
status['current_mode']          # Current evolution mode
status['mode_display_name']     # Formatted display name
status['max_positions']         # Current max positions
status['risk_per_trade_pct']    # Current risk %
status['copy_trading_enabled']  # Copy trading status
status['leverage_enabled']      # Leverage status

# Progress metrics
status['next_mode']             # Next tier (if any)
status['progress_to_next_pct']  # % progress to next tier
status['remaining_to_next']     # $ needed for next tier
status['mode_transitions']      # Number of transitions
```

---

## 🚨 Important Notes

### Capital Ranges

- **STARTER:** $15 - $249 (includes $250-$499 transition zone)
- **ADVANCED:** $500 - $999
- **ELITE:** $1000+

The $250-$499 gap is intentional. It keeps you in STARTER mode until you have sufficient capital for meaningful copy trading at ADVANCED tier.

### Feature Activation

Features activate based on capital:
- **Copy Trading:** Requires $500+ (ADVANCED mode)
- **Leverage:** Requires $1000+ (ELITE mode)

These are automatic - no manual configuration needed.

### Risk Management

Risk percentages are maximums:
- STARTER/ADVANCED: 4% max per trade
- ELITE: 5% max per trade

Your actual risk per trade can be lower based on:
- Market conditions
- Volatility
- Drawdown protection
- Other risk management layers

---

## 🎓 Philosophy

The Capital Evolution Engine embodies a core NIJA principle:

**"Your trading system should grow with your capital."**

Small accounts need:
- Fewer positions (capital efficiency)
- Moderate risk (protection)
- Simple setups (learning)

Medium accounts need:
- More positions (diversification)
- Copy trading (scale)
- Same proven risk (consistency)

Large accounts need:
- Maximum positions (capital deployment)
- Higher risk tolerance (acceleration)
- Leverage (velocity)
- SaaS infrastructure (business scale)

The engine handles these transitions automatically, so you focus on trading.

---

## 📚 Related Documentation

- [CAPITAL_SCALING_ENGINE.md](CAPITAL_SCALING_ENGINE.md) - Base capital management
- [AUTONOMOUS_SCALING_ENGINE.md](AUTONOMOUS_SCALING_ENGINE.md) - Advanced autonomous features
- [COPY_TRADING_SETUP.md](COPY_TRADING_SETUP.md) - Copy trading configuration
- [TIER_AND_RISK_CONFIG_GUIDE.md](TIER_AND_RISK_CONFIG_GUIDE.md) - Tier system details

---

## 🔥 Summary

The Capital Evolution Engine is your automated growth partner:

1. **Automatic tier detection** based on capital
2. **Seamless transitions** as you grow
3. **Progressive feature unlocks** at appropriate levels
4. **Intelligent risk scaling** for each stage
5. **Complete transparency** with reports and metrics

Start with $15. Focus on trading. Let the system scale with you.

From Survival to Domination. 🚀

---

**Version:** 1.0  
**Last Updated:** January 30, 2026  
**Author:** NIJA Trading Systems
