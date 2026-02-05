# PROFIT GATES INTEGRATION GUIDE

## Overview

This guide explains how to integrate the profit gates features into NIJA's existing trading system.

## Four Requirements Implemented

### A. Profit Gates ✅
**What**: No neutral/breakeven outcomes - all trades are win or loss
**Why**: Honest accounting - after fees, breakeven is a loss
**Critical Rule**: Any trade with net P&L ≤ 0 is a LOSS

**This is the most important line in the entire system.**

Why it matters:
- Fees are real
- Slippage is real
- "Breakeven" is emotional cope

**Files Modified**:
- `bot/trade_journal.py` - Outcome classification logic
- `bot/position_mirror.py` - Position close outcomes
- `bot/risk_manager.py` - Streak tracking
- `bot/ai_ml_base.py` - Documentation updates

**Profit logic lives below strategy logic.** This hard-codes truth into the system.

### B. Dust Prevention ✅
**What**: Position caps, asset ranking, forced exits on stagnation
**Why**: Own few things with intention, not a little of everything

**Real Problem Solved**:
- Earlier logs showed $45-$63 balances with ~50 positions
- This is index fund cosplay, not intentional trading
- Dust prevention fixes this pathology

**What's Good**:
- Hard position caps (default: 5)
- Health scoring (P&L + age + stagnation)
- Forced exits after 4h of dead money
- **Explicit profit status logging: PENDING → CONFIRMED**

**Files Created**:
- `bot/dust_prevention_engine.py` - Core dust prevention logic

**Critical**: Forced exits log explicitly as `PROFIT_STATUS = PENDING → CONFIRMED`
This ensures trade outcomes are immediately recorded, not left pending.

### C. User Truth Layer ✅
**What**: Clear daily P&L reporting ("Today you made +$0.42")
**Why**: Users deserve honest, simple money reporting
**Files Created**:
- `bot/user_truth_layer.py` - User-facing truth layer

### D. Health Metric ✅
**What**: Golden metric logged every cycle with aggression control
**Why**: The one metric that determines if NIJA is profitable
**Files Created**:
- `bot/nija_health_metric.py` - Health metric engine

---

## Integration Steps

### Step 1: Integrate Profit Gates (Already Active)

The profit gate changes are already active in the core files. No additional integration needed.

**Verification**:
```python
from bot.trade_journal import TradeJournal
journal = TradeJournal()
# All logged trades will now be 'win' or 'loss', never 'breakeven'
```

---

### Step 2: Integrate Dust Prevention Engine

Add to `bot/execution_engine.py` or `bot/trading_strategy.py`:

```python
from dust_prevention_engine import DustPreventionEngine

class ExecutionEngine:
    def __init__(self, ...):
        # Initialize dust prevention
        self.dust_engine = DustPreventionEngine(
            max_positions=5,  # Adjust based on account tier
            stagnation_hours=4.0,
            min_pnl_movement=0.002
        )
    
    def check_position_health(self):
        """Check and close unhealthy positions"""
        positions = self.get_open_positions()
        
        # Identify positions to close
        to_close = self.dust_engine.identify_positions_to_close(
            positions,
            force_to_limit=True
        )
        
        # Close identified positions
        for pos in to_close:
            logger.info(f"🧹 Dust cleanup: Closing {pos['symbol']} - {pos['reason']}")
            self.close_position(pos['symbol'])
    
    def before_new_trade(self, symbol):
        """Check if new trade is allowed"""
        current_count = len(self.get_open_positions())
        allowed, reason = self.dust_engine.should_allow_new_position(current_count)
        
        if not allowed:
            logger.warning(f"❌ Trade blocked: {reason}")
            return False
        
        return True
```

**Usage in Trading Loop**:
```python
# In main trading loop
def run_trading_cycle():
    # 1. Check and cleanup dust positions
    execution_engine.check_position_health()
    
    # 2. Scan for new opportunities
    signals = scan_market()
    
    # 3. Before taking new trade, check position limit
    for signal in signals:
        if execution_engine.before_new_trade(signal.symbol):
            execution_engine.enter_trade(signal)

# Example of forced exit with profit status logging
def check_position_health(self):
    """Check and close unhealthy positions"""
    positions = self.get_open_positions()
    
    # Identify positions to close
    to_close = self.dust_engine.identify_positions_to_close(
        positions,
        force_to_limit=True
    )
    
    # Close identified positions with explicit profit status logging
    for pos in to_close:
        # Log the forced exit
        self.dust_engine.log_forced_exit(
            symbol=pos['symbol'],
            reason=pos['reason'],
            current_pnl_pct=pos['current_pnl']
        )
        
        # Execute the close
        self.close_position(pos['symbol'])
        
        # PROFIT_STATUS = PENDING → CONFIRMED
        # This ensures the trade outcome is immediately recorded
```

---

### Step 3: Integrate User Truth Layer

Add to `bot/execution_engine.py` or wherever trades are closed:

```python
from user_truth_layer import UserTruthLayer

class ExecutionEngine:
    def __init__(self, ...):
        # Initialize truth layer
        self.truth_layer = UserTruthLayer(
            storage_path="/home/runner/work/Nija/Nija/data/user_truth.json"
        )
    
    def close_position(self, symbol, ...):
        """Close position and record truth"""
        # ... existing close logic ...
        
        # Calculate net P&L (after fees)
        net_pnl = self.calculate_pnl(symbol)
        
        # Record truth
        self.truth_layer.record_trade_pnl(net_pnl)
        
        # Get today's truth for logging
        today_truth = self.truth_layer.get_today_truth()
        logger.info(f"💰 {today_truth}")
```

**Display to Users**:
```python
# In dashboard or API endpoint
def get_daily_summary():
    truth = UserTruthLayer()
    
    return {
        'today': truth.get_today_truth(),
        'yesterday': truth.get_yesterday_truth(),
        'weekly_summary': truth.get_truth_summary(7)
    }
```

---

### Step 4: Integrate Health Metric

Add to main trading loop or scheduler:

```python
from nija_health_metric import NIJAHealthMetric
from broker_integration import get_account_balance

class TradingBot:
    def __init__(self, ...):
        # Initialize health metric
        self.health_metric = NIJAHealthMetric(
            storage_path="/home/runner/work/Nija/Nija/data/health_metric.json",
            lookback_hours=24
        )
        
        # Store starting balance
        self.daily_starting_balance = None
    
    def daily_health_check(self):
        """Run once per day (or every cycle)"""
        current_balance = get_account_balance()
        
        # If first check of the day, store starting balance
        if self.daily_starting_balance is None:
            self.daily_starting_balance = current_balance
        
        # Record health check
        snapshot = self.health_metric.record_health_check(
            starting_balance=self.daily_starting_balance,
            current_balance=current_balance
        )
        
        # Update starting balance for tomorrow
        if snapshot.timestamp.hour == 0:  # Midnight reset
            self.daily_starting_balance = current_balance
        
        return snapshot
    
    def get_position_size_multiplier(self):
        """Get aggression multiplier for position sizing"""
        return self.health_metric.get_aggression_multiplier()
    
    def should_pause_trading(self):
        """Check if losses are severe enough to pause"""
        return self.health_metric.should_pause_trading()
```

**Usage in Trading Logic**:
```python
def calculate_position_size(base_size):
    # Apply health-based aggression multiplier
    aggression = trading_bot.get_position_size_multiplier()
    actual_size = base_size * aggression
    
    logger.info(f"Position size: ${base_size:.2f} × {aggression:.2f} = ${actual_size:.2f}")
    return actual_size

def before_trade():
    # Check if we should pause due to severe losses
    if trading_bot.should_pause_trading():
        logger.error("🛑 Trading PAUSED due to severe losses")
        return False
    return True
```

---

## Configuration Recommendations

### Dust Prevention Settings by Account Size

| Account Size | Max Positions | Stagnation Hours | Min Movement |
|-------------|---------------|------------------|--------------|
| < $100 | 1-2 | 2.0 | 0.003 (0.3%) |
| $100-$500 | 3-4 | 3.0 | 0.002 (0.2%) |
| $500-$1000 | 5-6 | 4.0 | 0.002 (0.2%) |
| > $1000 | 6-8 | 4.0 | 0.001 (0.1%) |

### Health Metric Settings

- **Lookback**: 24 hours (daily comparison)
- **Update Frequency**: Every trading cycle (e.g., every 2.5 minutes)
- **Storage**: Persistent JSON file to survive restarts

### Aggression Levels

The health metric automatically adjusts aggression:
- **1.0 (100%)**: Strong profits (>5% gain)
- **0.95 (95%)**: Good profits (2-5% gain)
- **0.85 (85%)**: Minor losses (<2% loss)
- **0.7 (70%)**: Moderate losses (2-5% loss)
- **0.5 (50%)**: Significant losses (5-10% loss)
- **0.3 (30%)**: Severe losses (>10% loss)

---

## Testing

Run the test suite to verify integration:
```bash
python test_profit_gates.py
```

Expected output:
```
✅ ALL TESTS PASSED
- Profit gates: No neutral outcomes
- Dust prevention: Position caps + ranking + forced exits
- User truth layer: Clear, honest P&L reporting
- Health metric: Golden metric with aggression control
```

---

## Monitoring

### Key Logs to Watch

**Dust Prevention**:
```
🧹 DUST CLEANUP: 7 positions exceeds limit of 5
🧹 Identified 2 positions for dust cleanup
```

**User Truth Layer**:
```
📝 Truth recorded: 2026-02-05 → Today you made +$0.42
💰 Today you made +$0.24
```

**Health Metric**:
```
📊 NIJA HEALTH METRIC
Starting Balance (24h): $61.20
Current Balance: $63.38
Net Change: +$2.18
Status: PROFITABLE
Aggression Level: 95%
```

---

## Migration Checklist

- [ ] Review profit gates changes in trade_journal.py, position_mirror.py, risk_manager.py
- [ ] Add dust prevention engine to execution logic
- [ ] Add user truth layer to trade close logic
- [ ] Add health metric to main trading loop
- [ ] Configure max_positions based on account tier
- [ ] Set up persistent storage paths for truth layer and health metric
- [ ] Test with paper trading first
- [ ] Monitor logs for dust cleanup events
- [ ] Verify aggression adjustments are working
- [ ] Deploy to production

---

## FAQ

**Q: Why is breakeven a loss now?**
A: Because fees were paid. If you pay 1.4% in fees and exit at breakeven on price, you lost 1.4% of your capital.

**Q: What happens if I have more positions than the limit?**
A: Dust prevention will automatically close the worst positions (lowest health scores) until you're at or under the limit.

**Q: How do I display truth messages to users?**
A: Use `truth_layer.get_user_facing_message('today')` or `truth_layer.get_today_truth()` - both return simple strings like "Today you made +$0.42"

**Q: When should I run the health check?**
A: Every trading cycle is ideal. At minimum, once per day. The metric compares current balance to starting balance from 24h ago.

**Q: Can I disable aggression adjustments?**
A: Yes, but not recommended. The aggression multiplier is what makes NIJA self-aware and prevents it from digging deeper holes when losing.

---

## Support

For questions or issues:
1. Check test output: `python test_profit_gates.py`
2. Review logs for the 🧹, 💰, and 📊 emoji markers
3. Verify configuration matches your account size
4. Ensure persistent storage paths exist and are writable

---

**Remember**: NIJA is now ready for public money because it has:
- ✅ Honest accounting (profit gates)
- ✅ Discipline (dust prevention)
- ✅ Transparency (user truth layer)
- ✅ Self-awareness (health metric)
