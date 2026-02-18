# NIJA Institutional Trading System - Architecture Documentation

## Overview

The NIJA Institutional Trading System is a three-tier enhancement that transforms NIJA from a reactive trading bot into an institutional-grade trading system. It implements the architectural philosophy that **"if entry logic is weak, scaling multiplies losses."**

## The Three Layers

### 1️⃣ Entry Logic Audit (The Brain)

**Purpose**: Make every entry decision intentional, tracked, and analyzable.

**Location**: `bot/entry_audit_system.py`

**Key Features**:
- ✅ Hierarchical validation tracking (confidence → score → filters → execution)
- ✅ Explicit rejection codes for every validation failure
- ✅ Win/loss attribution to entry signal type
- ✅ Entry quality metrics (EXCELLENT, GOOD, ACCEPTABLE, MARGINAL, POOR)
- ✅ Signal hierarchy tracking (which indicator triggered entry)
- ✅ Liquidity and spread validation structures
- ✅ Slippage tolerance checks
- ✅ Double-entry prevention (5-minute lookback)
- ✅ Entry reason logging for analytics and debugging

**Components**:

```python
class EntryTrigger(Enum):
    RSI_OVERSOLD, RSI_OVERBOUGHT, VWAP_PULLBACK, MACD_CROSS, 
    EMA_PULLBACK, VOLUME_SPIKE, BOLLINGER_BOUNCE, ADX_TREND, 
    MULTI_FACTOR, UNKNOWN

class EntryQuality(Enum):
    EXCELLENT (90-100%), GOOD (75-89%), ACCEPTABLE (60-74%), 
    MARGINAL (50-59%), POOR (<50%)

class EntryAuditSystem:
    - log_entry_decision(record)
    - update_outcome(audit_id, exit_price, pnl_usd)
    - check_duplicate_entry(symbol, lookback_minutes)
    - get_stats_summary()
    - get_top_rejection_reasons()
```

**Usage**:
```python
from entry_audit_system import get_entry_audit_system

audit = get_entry_audit_system()

# Log entry decision
record = EntryAuditRecord(...)
audit.log_entry_decision(record)

# Update outcome after trade closes
audit.update_outcome(audit_id, exit_price, pnl_usd, closed_at)

# Get analytics
stats = audit.get_stats_summary()
print(f"Win rate by trigger: {stats['win_rates_by_trigger']}")
```

---

### 2️⃣ Position Architecture Redesign (The Skeleton)

**Purpose**: Prevent capital violations through portfolio-aware position management.

**Location**: `bot/position_architecture.py`

**Key Features**:
- ✅ Hard max open positions per tier
- ✅ Per-symbol exposure cap (15% max per symbol)
- ✅ Capital reserve buffer (20% idle minimum)
- ✅ Daily max loss lock (5% daily loss limit)
- ✅ Weekly drawdown lock (10% weekly loss limit)
- ✅ Auto position reduction during volatility spikes
- ✅ Position health monitoring (ACTIVE, STALE, AGED, ZOMBIE states)
- ✅ Force-close recommendations for zombie positions
- ✅ Position age tracking (24h aged, 12h stale thresholds)

**Components**:

```python
class PositionState(Enum):
    ACTIVE     # Healthy position
    STALE      # No movement for 12+ hours
    AGED       # Open for 24+ hours
    ZOMBIE     # Stale + aged + underwater
    LIQUIDATING

class PositionArchitecture:
    - can_open_position(symbol, size_usd) -> (bool, reason)
    - register_position(symbol, size_usd, entry_price, side, stop_loss)
    - update_position(symbol, current_price)
    - close_position(symbol, exit_price, pnl_usd)
    - get_positions_to_force_close() -> List[str]
    - should_reduce_positions() -> (bool, target_count)
    - get_architecture_status() -> Dict
```

**Exposure Limits**:
```python
max_total_exposure_pct = 0.80    # 80% max of account
capital_reserve_pct = 0.20        # 20% idle buffer
max_per_symbol_pct = 0.15         # 15% per symbol
max_correlated_sector_pct = 0.40  # 40% in correlated assets
```

**Drawdown Protection**:
```python
daily_max_loss_pct = 0.05    # 5% daily max loss
weekly_max_loss_pct = 0.10   # 10% weekly max loss

# Automatic trading halt when limits breached
# Lock duration: 24 hours (daily), 7 days (weekly)
```

**Usage**:
```python
from position_architecture import get_position_architecture

arch = get_position_architecture("GROWTH", 5000.0, max_positions=5)

# Check if position can be opened
can_open, reason = arch.can_open_position("BTC-USD", 100.0)

if can_open:
    arch.register_position("BTC-USD", 100.0, 96000.0, "LONG", 95000.0)

# Update position
arch.update_position("BTC-USD", 97000.0)

# Check for zombie positions
zombies = arch.get_positions_to_force_close()

# Get status
status = arch.get_architecture_status()
print(f"Exposure: {status['exposure']['total_pct']:.1%}")
```

---

### 3️⃣ Capital Tier Scaling (The Growth System)

**Purpose**: Enable scaling from $50 to $250k without rewriting logic.

**Location**: `bot/capital_tier_scaling.py`

**Key Features**:
- ✅ Dynamic tier detection and auto-assignment
- ✅ Institutional tier model (4 tiers from MICRO to INSTITUTIONAL)
- ✅ Tier-specific risk percentage calculations
- ✅ Tier-specific max position counts
- ✅ Tier-appropriate behavior modifications
- ✅ Tier transition logging and milestone system
- ✅ Capital-based aggression scaling
- ✅ Diversification requirements per tier
- ✅ Stability prioritization for high tiers

**Tier Model**:

| Tier | Capital Range | Risk/Trade | Max Positions | Behavior |
|------|--------------|------------|---------------|----------|
| **MICRO** | $50-$500 | 2-3% | 1-2 | High precision, concentrated |
| **GROWTH** | $500-$5k | 1-2% | 3-5 | Controlled scaling |
| **PRO** | $5k-$50k | 0.5-1% | 5-10 | Capital preservation focus |
| **INSTITUTIONAL** | $50k-$250k | 0.25-0.5% | 10-20 | Stability priority |

**Tier Configuration Example (INSTITUTIONAL)**:
```python
TierConfiguration(
    tier_level=INSTITUTIONAL,
    min_capital=50000.0,
    max_capital=250000.0,
    risk_per_trade_pct=(0.0025, 0.005),  # 0.25-0.5%
    max_positions=(10, 20),
    aggression_level=0.2,  # Low aggression
    diversification_required=True,
    min_symbols_for_full_allocation=10,
    min_profit_target_pct=0.025,
    max_profit_target_pct=0.10,
    max_stop_loss_pct=0.008,
    max_daily_trades=30,
    cooldown_after_loss_minutes=15,
    daily_loss_limit_pct=0.02,  # 2% daily
    weekly_loss_limit_pct=0.04,  # 4% weekly
    allow_aggressive_entries=False,
    require_high_confidence=True,
    prioritize_stability=True
)
```

**Usage**:
```python
from capital_tier_scaling import get_capital_tier_system

tier_system = get_capital_tier_system(5000.0)

# Get tier info
info = tier_system.get_tier_info()
print(f"Current tier: {info['tier']}")
print(f"Max positions: {info['config']['max_positions']}")

# Update balance (auto tier transitions)
tier_system.update_balance(75000.0)  # Upgrades to INSTITUTIONAL

# Calculate position size
pos_size = tier_system.calculate_position_size(
    signal_confidence=0.75,
    available_capital=50000.0
)

# Check signal requirements
should_accept, reason = tier_system.should_accept_signal(
    confidence=0.70,
    quality_score=80.0
)
```

---

## Integration Layer

**Location**: `bot/institutional_integration.py`

**Purpose**: Unified interface for institutional trading that combines all three systems.

**Key Features**:
- ✅ Comprehensive entry validation pipeline
- ✅ Position lifecycle management
- ✅ Automatic tier transitions
- ✅ Unified decision context

**Main Class**:
```python
class InstitutionalIntegration:
    def __init__(self, initial_balance, broker_name)
    
    def validate_entry_comprehensive(
        symbol, signal_type, entry_score, confidence,
        signal_contributions, primary_trigger, price,
        proposed_size_usd, stop_loss_price, ...
    ) -> (allowed, reason, audit_id)
    
    def register_position_opened(symbol, size_usd, entry_price, ...)
    def update_position_price(symbol, current_price)
    def register_position_closed(symbol, exit_price, pnl_usd, ...)
    
    def get_positions_to_force_close() -> List[str]
    def should_reduce_positions() -> (bool, target_count)
    def calculate_position_size(signal_confidence) -> float
```

**Usage Example**:
```python
from institutional_integration import get_institutional_integration

# Initialize
integration = get_institutional_integration(5000.0, "coinbase")

# Validate entry
allowed, reason, audit_id = integration.validate_entry_comprehensive(
    symbol="BTC-USD",
    signal_type="LONG",
    entry_score=4.2,
    confidence=0.75,
    signal_contributions={'rsi': 2.5, 'vwap': 1.8, 'macd': 1.2},
    primary_trigger="rsi",
    price=96000.0,
    proposed_size_usd=100.0,
    stop_loss_price=95000.0,
    adx=25.0,
    rsi=35.0,
    volume_24h=1000000.0
)

if allowed:
    # Execute trade
    execution_price = execute_trade(...)
    
    # Register position
    integration.register_position_opened(
        "BTC-USD", 100.0, execution_price, "LONG", 95000.0, audit_id
    )
    
    # Later: Update position
    integration.update_position_price("BTC-USD", 97000.0)
    
    # Later: Close position
    integration.register_position_closed("BTC-USD", 97000.0, 10.0, audit_id)
else:
    print(f"Entry rejected: {reason}")
```

---

## Testing

**Location**: `bot/test_institutional_integration.py`

All tests passing ✅:
- ✅ Entry Audit System tests (PASSED)
- ✅ Position Architecture tests (PASSED)
- ✅ Capital Tier Scaling tests (PASSED)
- ✅ Full Integration tests (PASSED)

**Run tests**:
```bash
cd /path/to/Nija
python bot/test_institutional_integration.py
```

---

## Data Persistence

### Entry Audit System
- `data/entry_audit_log.jsonl` - JSONL log of all entry decisions
- `data/entry_audit_stats.json` - Aggregate statistics

### Position Architecture
- Position state is tracked in memory (integrates with existing position manager)

### Capital Tier System
- `data/capital_milestones.json` - Milestone achievements
- `data/tier_history.jsonl` - Tier transition history

---

## Key Metrics

### Entry Audit Metrics
- Total signals processed
- Acceptance rate
- Rejection reasons (top 10)
- Win rate by trigger type
- Average confidence by outcome
- Quality distribution

### Position Architecture Metrics
- Current positions / max positions
- Total exposure percentage
- Reserve buffer percentage
- Drawdown lock status
- Position health scores
- Zombie position count

### Capital Tier Metrics
- Current tier level
- Account balance
- Tier progress percentage
- Milestones achieved
- Next milestone target
- Tier transition count
- Highest balance achieved

---

## Integration with Existing NIJA Code

### Entry Validation Flow

**Before (existing)**:
```python
# trading_strategy.py
if confidence >= MIN_CONFIDENCE and entry_score >= threshold:
    execute_trade(...)
```

**After (institutional)**:
```python
# trading_strategy.py
from institutional_integration import get_institutional_integration

integration = get_institutional_integration(balance, broker_name)

allowed, reason, audit_id = integration.validate_entry_comprehensive(
    symbol, signal_type, entry_score, confidence,
    signal_contributions, primary_trigger, price,
    proposed_size_usd, stop_loss_price, ...
)

if allowed:
    execution_price = execute_trade(...)
    integration.register_position_opened(
        symbol, proposed_size_usd, execution_price,
        signal_type, stop_loss_price, audit_id
    )
else:
    logger.info(f"Entry rejected: {reason}")
```

### Position Management Flow

**Position lifecycle tracking**:
```python
# execution_engine.py
from institutional_integration import get_institutional_integration

integration = get_institutional_integration(balance, broker_name)

# On position open
integration.register_position_opened(symbol, size, entry_price, side, stop_loss)

# On price update (in monitoring loop)
integration.update_position_price(symbol, current_price)

# Check for forced exits
zombies = integration.get_positions_to_force_close()
for symbol in zombies:
    force_close_position(symbol)

# Check for position reduction
should_reduce, target_count = integration.should_reduce_positions()
if should_reduce:
    reduce_positions_to(target_count)

# On position close
integration.register_position_closed(symbol, exit_price, pnl_usd, audit_id)
```

### Position Sizing Flow

**Before (existing)**:
```python
# risk_manager.py
position_size = balance * risk_pct
```

**After (institutional)**:
```python
# risk_manager.py
from institutional_integration import get_institutional_integration

integration = get_institutional_integration(balance, broker_name)
position_size = integration.calculate_position_size(signal_confidence)
```

---

## Benefits

### 1. Institutional-Grade Entry Discipline
- Every entry is validated through multiple gates
- Clear audit trail for every trade decision
- Win/loss attribution enables strategy improvement
- No more "reactive" trading - every entry is intentional

### 2. Capital Protection
- Hard position limits prevent overtrading
- Exposure caps prevent concentration risk
- Drawdown locks prevent spiral losses
- Zombie position detection prevents capital traps

### 3. Scalable Architecture
- Same code works from $50 to $250k+
- Automatic behavior adjustment as capital grows
- Risk decreases as capital increases (institutional model)
- Milestone system celebrates growth

### 4. Transparency & Analytics
- Complete entry decision history
- Rejection reason analytics
- Position health monitoring
- Tier transition tracking
- Performance attribution by entry type

---

## Summary

The NIJA Institutional Trading System transforms NIJA from a reactive bot into an institutional-grade trading system by implementing three critical layers:

1. **Entry Logic Audit** - Makes every entry intentional and trackable
2. **Position Architecture** - Prevents capital violations through hard limits
3. **Capital Tier Scaling** - Enables growth from $50 to $250k+ without code changes

**The order matters**: Build entry logic first, then position architecture, then capital scaling. If you scale instability, you just multiply losses faster.

**Result**: A trading system that:
- Knows why it enters trades
- Protects capital through hard limits
- Scales intelligently as capital grows
- Provides complete transparency and analytics

---

## Next Steps

To integrate with main NIJA trading loop:

1. **Import institutional integration in trading_strategy.py**
2. **Replace entry validation with comprehensive validation**
3. **Add position lifecycle hooks in execution_engine.py**
4. **Update position sizing in risk_manager.py**
5. **Add daily summary reporting**
6. **Monitor entry audit analytics for strategy improvement**

See integration examples above for specific code changes.
