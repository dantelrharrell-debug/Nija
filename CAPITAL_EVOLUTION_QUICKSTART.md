# 🔥 Capital Evolution Engine - Quick Start Guide

## What is the Capital Evolution Engine?

The **Capital Evolution Engine** is NIJA's auto-scaling system that automatically adjusts your trading parameters based on your current account balance. It implements three evolution modes that progressively unlock features as your capital grows.

## Quick Setup (5 Minutes)

### Step 1: Import the Engine

```python
from bot.capital_evolution_engine import get_evolution_engine

# Initialize with your current balance
balance = 100.0  # Replace with your actual balance
engine = get_evolution_engine(initial_capital=balance)
```

### Step 2: Check Your Mode

```python
# See your current evolution mode
print(engine.get_quick_summary())
# Output: 🔥 STARTER — SURVIVAL MODE | 💰 $100.00 | 🎯 3 pos | 4% risk

# Get detailed configuration
print(f"Max Positions: {engine.get_max_positions()}")  # 3
print(f"Risk %: {engine.get_risk_per_trade_pct()}")    # 4.0
print(f"Copy Trading: {engine.is_copy_trading_enabled()}")  # False
print(f"Leverage: {engine.is_leverage_enabled()}")     # False
```

### Step 3: Update After Each Trade

```python
# After each trade, update your balance
new_balance = 150.0
new_mode = engine.update_capital(new_balance)

# Check if mode changed
if new_mode:
    print(f"🚀 You evolved to: {engine.mode_config.get_display_name()}")
```

### Step 4: Use in Your Trading Logic

```python
# Before opening a trade
max_positions = engine.get_max_positions()
current_positions = 2

if current_positions >= max_positions:
    print(f"Position limit reached: {current_positions}/{max_positions}")
else:
    # Calculate position size with evolution risk %
    risk_pct = engine.get_risk_per_trade_pct() / 100.0
    position_size = new_balance * risk_pct
    
    # Open trade with calculated position size
    print(f"Opening position: ${position_size:.2f}")
```

## The Three Modes

### 🔥 STARTER ($15-$249)
- **3 positions max**
- **4% risk** per trade
- Focus: Aggressive compounding
- Copy trading: ❌ Disabled
- Leverage: ❌ Disabled

### ⚡ ADVANCED ($500-$999)
- **4 positions max** ↑
- **4% risk** per trade
- Focus: Multi-account scaling
- Copy trading: ✅ **Enabled**
- Leverage: ❌ Disabled

### 👑 ELITE ($1000+)
- **6 positions max** ↑
- **5% risk** per trade ↑
- Focus: Capital acceleration + SaaS
- Copy trading: ✅ Enabled
- Leverage: ✅ **Enabled**

## Complete Integration Example

```python
from bot.capital_evolution_engine import get_evolution_engine

class MyTradingBot:
    def __init__(self, initial_balance):
        self.balance = initial_balance
        self.evolution = get_evolution_engine(initial_capital=initial_balance)
        self.open_positions = []
    
    def can_open_position(self):
        """Check if we can open a new position"""
        max_pos = self.evolution.get_max_positions()
        return len(self.open_positions) < max_pos
    
    def calculate_position_size(self):
        """Calculate position size using evolution risk %"""
        risk_pct = self.evolution.get_risk_per_trade_pct() / 100.0
        return self.balance * risk_pct
    
    def execute_trade(self, symbol, direction):
        """Execute a trade with evolution controls"""
        # Check position limit
        if not self.can_open_position():
            print(f"❌ Position limit reached: {len(self.open_positions)}/{self.evolution.get_max_positions()}")
            return False
        
        # Calculate size
        size = self.calculate_position_size()
        
        # Open position
        position = {
            'symbol': symbol,
            'direction': direction,
            'size': size
        }
        self.open_positions.append(position)
        
        print(f"✅ Opened {symbol} {direction}: ${size:.2f}")
        return True
    
    def close_trade(self, position_index, pnl):
        """Close trade and update evolution engine"""
        # Remove position
        position = self.open_positions.pop(position_index)
        
        # Update balance
        self.balance += pnl
        
        # Update evolution engine (checks for mode transitions)
        new_mode = self.evolution.update_capital(self.balance)
        
        if new_mode:
            print(f"🚀 Evolved to: {self.evolution.mode_config.get_display_name()}")
        
        return position

# Example usage
bot = MyTradingBot(initial_balance=100.0)

# Execute trades
bot.execute_trade("BTC-USD", "LONG")
bot.execute_trade("ETH-USD", "LONG")
bot.execute_trade("SOL-USD", "LONG")

# Try to exceed position limit
bot.execute_trade("LINK-USD", "LONG")  # Will fail - limit reached

# Close a trade with profit
bot.close_trade(0, pnl=50.0)  # Profit: $50

# Check status
print(bot.evolution.get_quick_summary())
```

## Environment Integration

### Option 1: Singleton Pattern (Recommended for existing codebases)

```python
from bot.capital_evolution_engine import get_singleton_evolution_engine

# Initialize once at bot startup
def initialize_bot(balance):
    engine = get_singleton_evolution_engine(
        initial_capital=balance,
        current_capital=balance
    )
    print(f"Evolution engine initialized: {engine.get_quick_summary()}")

# Access from anywhere in your code
def trading_module():
    engine = get_singleton_evolution_engine()
    max_pos = engine.get_max_positions()
    # ... use max_pos

def risk_module():
    engine = get_singleton_evolution_engine()
    risk = engine.get_risk_per_trade_pct()
    # ... use risk

# Update from anywhere
def update_balance_module(new_balance):
    engine = get_singleton_evolution_engine()
    engine.update_capital(new_balance)
```

### Option 2: Dependency Injection

```python
# Pass engine to modules that need it
class TradingStrategy:
    def __init__(self, evolution_engine):
        self.evolution = evolution_engine
    
    def can_trade(self, open_count):
        return open_count < self.evolution.get_max_positions()

class RiskManager:
    def __init__(self, evolution_engine):
        self.evolution = evolution_engine
    
    def get_risk_percent(self):
        return self.evolution.get_risk_per_trade_pct()

# Initialize and inject
balance = 500.0
engine = get_evolution_engine(initial_capital=balance)

strategy = TradingStrategy(engine)
risk_mgr = RiskManager(engine)
```

## Monitoring and Reporting

### Quick Status Check

```python
# One-line summary
print(engine.get_quick_summary())
# Output: ⚡ ADVANCED — MULTIPLIER MODE | 💰 $500.00 | 🎯 4 pos | 4% risk | 📈 0% to next tier
```

### Detailed Status

```python
status = engine.get_evolution_status()

print(f"Current Capital: ${status['current_capital']:.2f}")
print(f"ROI: {status['roi_pct']:.1f}%")
print(f"Mode: {status['mode_display_name']}")
print(f"Max Positions: {status['max_positions']}")
print(f"Risk %: {status['risk_per_trade_pct']:.1f}%")

# Progress to next tier
if status['next_mode']:
    print(f"Next: {status['next_mode']} ({status['progress_to_next_pct']:.0f}%)")
    print(f"Need: ${status['remaining_to_next']:.2f} more")
```

### Full Report

```python
# Comprehensive report with transition history
print(engine.get_evolution_report())
```

## Common Patterns

### Pattern 1: Pre-Trade Check

```python
def before_opening_trade(engine, open_positions, balance):
    # Check position limit
    if len(open_positions) >= engine.get_max_positions():
        return False, "Position limit reached"
    
    # Calculate size
    risk_pct = engine.get_risk_per_trade_pct() / 100.0
    size = balance * risk_pct
    
    # Check if copy trading should be enabled
    if engine.is_copy_trading_enabled():
        # Replicate to user accounts
        replicate_to_users(size)
    
    return True, size
```

### Pattern 2: Post-Trade Update

```python
def after_closing_trade(engine, new_balance, pnl):
    # Update engine
    new_mode = engine.update_capital(new_balance)
    
    # Log transition
    if new_mode:
        log_mode_transition(new_mode, new_balance)
    
    # Adjust leverage if enabled
    if engine.is_leverage_enabled():
        enable_leverage_trading()
    else:
        disable_leverage_trading()
```

### Pattern 3: Daily Report

```python
def generate_daily_report(engine):
    status = engine.get_evolution_status()
    
    report = f"""
    Daily Trading Report
    ====================
    Mode: {status['mode_display_name']}
    Balance: ${status['current_capital']:.2f}
    ROI: {status['roi_pct']:.1f}%
    Max Positions: {status['max_positions']}
    Risk Per Trade: {status['risk_per_trade_pct']:.1f}%
    Copy Trading: {'✅' if status['copy_trading_enabled'] else '❌'}
    Leverage: {'✅' if status['leverage_enabled'] else '❌'}
    """
    
    if status['next_mode']:
        report += f"\nProgress to {status['next_mode']}: {status['progress_to_next_pct']:.0f}%"
    
    return report
```

## Testing

Test the engine with simulated capital growth:

```python
# Test file included: test_capital_evolution_engine.py
python test_capital_evolution_engine.py

# Should output:
# ✅ PASS | Mode Detection
# ✅ PASS | Mode Transitions
# ✅ PASS | Configuration Access
# ✅ PASS | Progress Tracking
# ✅ PASS | Integration Example
# ✅ PASS | Comprehensive Report
# 
# 🎉 ALL TESTS PASSED! 🎉
```

## Troubleshooting

### Issue: Mode not changing at expected balance

**Solution:** Check the transition thresholds:
- STARTER → ADVANCED: $500.00 (not $250)
- ADVANCED → ELITE: $1,000.00

The $250-$499 range intentionally stays in STARTER mode.

### Issue: Position limit seems wrong

**Solution:** Call `get_max_positions()` to verify current limit. Remember:
- STARTER: 3 positions
- ADVANCED: 4 positions
- ELITE: 6 positions

### Issue: Copy trading not activating

**Solution:** Copy trading activates at ADVANCED mode ($500+). Check current mode:
```python
if engine.current_mode.value == "STARTER_SURVIVAL":
    print("Copy trading requires ADVANCED mode ($500+)")
```

## Next Steps

1. **Read Full Documentation:** [CAPITAL_EVOLUTION_ENGINE.md](CAPITAL_EVOLUTION_ENGINE.md)
2. **Review Integration Examples:** [bot/evolution_integration_example.py](bot/evolution_integration_example.py)
3. **Run Tests:** `python test_capital_evolution_engine.py`
4. **Start Trading:** Integrate into your bot and let it scale automatically!

## Support

- **Documentation:** `CAPITAL_EVOLUTION_ENGINE.md`
- **Integration Examples:** `bot/evolution_integration_example.py`
- **Test Suite:** `test_capital_evolution_engine.py`
- **Code:** `bot/capital_evolution_engine.py`

---

**Remember:** The engine works best when you let it do its job. Don't override the auto-scaling unless absolutely necessary. Trust the system and focus on trading! 🚀
