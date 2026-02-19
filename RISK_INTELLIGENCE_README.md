# Risk Intelligence & High-Exposure Asset Management

## Overview

This guide describes the enhanced risk management features added to NIJA to address Phase 3 requirements:

1. **Legacy Position Exit Protocol** with high-exposure asset monitoring
2. **Risk Intelligence Gate** for pre-entry verification
3. **Volatility scaling** checks before increasing position sizes
4. **Correlation-weighted exposure** checks before adding positions

## Problem Statement (Addressed)

✅ **Run Legacy Position Exit Protocol now on all accounts**
   - Gradually unwind legacy/non-compliant positions
   - Clear stale orders and dust positions
   - Track capital freed
   - Mark accounts CLEAN

✅ **Monitor high-exposure assets (PEPE, LUNA)**
   - Keep an eye on price swings
   - Use dust/over-cap rules to prevent unintended risk

✅ **Phase in risk intelligence next**
   - Volatility scaling → before increasing position sizes
   - Risk-weighted exposure → before adding correlated positions

---

## 1. High-Exposure Asset Monitoring

### What It Does

The Legacy Position Exit Protocol now includes **automatic monitoring of high-risk volatile assets**:

- **PEPE-USD, PEPE-USDT** (volatile meme coin)
- **LUNA-USD, LUNA-USDT, LUNA2-USD** (historically risky, delisted concerns)
- **SHIB-USD, SHIB-USDT** (high volatility meme coin)
- **DOGE-USD, DOGE-USDT** (meme coin with high price swings)
- **FLOKI-USD, FLOKI-USDT** (emerging meme coin)

### Features

✅ **Automatic Classification**
   - High-exposure assets are flagged as `LEGACY_NON_COMPLIANT`
   - Applies dust/over-cap rules more aggressively
   - Enhanced monitoring and alerting

✅ **Alert Generation**
   - `OVERSIZED_HIGH_EXPOSURE`: Position >10% of account (CRITICAL)
   - `NEAR_DUST_THRESHOLD`: Position approaching dust threshold (WARNING)
   - `EXCESSIVE_HIGH_EXPOSURE_CONCENTRATION`: Total high-exposure >25% of account (CRITICAL)

✅ **Capital Tracking**
   - Tracks total exposure to high-risk assets
   - Monitors % of account in volatile positions
   - Historical alert tracking in state file

### Usage

```python
from bot.legacy_position_exit_protocol import LegacyPositionExitProtocol
from bot.position_tracker import PositionTracker
from bot.broker_integration import get_broker_integration

# Initialize
position_tracker = PositionTracker()
broker = get_broker_integration('coinbase')

# Create protocol with monitoring ENABLED
protocol = LegacyPositionExitProtocol(
    position_tracker=position_tracker,
    broker_integration=broker,
    monitor_high_exposure=True  # ✅ Enable monitoring
)

# Run full protocol
results = protocol.run_full_protocol()

# Check monitoring results
monitoring = results['high_exposure_monitoring']
print(f"Assets Tracked: {monitoring['positions_tracked']}")
print(f"Alerts: {monitoring['alert_count']}")

for alert in monitoring['alerts']:
    print(f"{alert['severity']}: {alert['message']}")
```

### Command Line

```bash
# Run with monitoring (default is enabled)
python run_legacy_exit_protocol.py --broker coinbase

# Check what high-exposure assets are held
python run_legacy_exit_protocol.py --verify-only
```

### State Tracking

The protocol tracks high-exposure assets in `data/legacy_exit_protocol_state.json`:

```json
{
  "high_exposure_assets_tracked": ["PEPE-USD", "SHIB-USD"],
  "high_exposure_alerts": [
    {
      "type": "OVERSIZED_HIGH_EXPOSURE",
      "severity": "CRITICAL",
      "symbol": "PEPE-USD",
      "size_usd": 1500.0,
      "pct_of_account": 15.0,
      "message": "PEPE-USD is 15.0% of account (>10% threshold)",
      "recommendation": "Consider reducing position size or setting tighter stop-loss",
      "timestamp": "2026-02-19T00:00:00"
    }
  ]
}
```

---

## 2. Risk Intelligence Gate

### What It Does

The **Risk Intelligence Gate** provides **pre-entry verification** to ensure trades meet risk management criteria BEFORE execution.

### Features

✅ **Volatility Scaling Check**
   - Verifies volatility is within acceptable limits before entry
   - Prevents entries during extreme volatility (>3x target)
   - Uses ATR-based volatility measurement
   - Integrates with `VolatilityAdaptiveSizer`

✅ **Correlation Exposure Check**
   - Prevents over-concentration in correlated assets
   - Enforces max 40% exposure to any correlation group
   - Ensures minimum diversification ratio (0.5)
   - Integrates with `PortfolioRiskEngine`

✅ **Pre-Trade Risk Assessment**
   - Comprehensive multi-layer risk check
   - ALL checks must pass to approve trade
   - Detailed rejection reasons if trade fails
   - Audit trail of all assessments

### Usage

```python
from bot.risk_intelligence_gate import create_risk_intelligence_gate
from bot.broker_integration import get_broker_integration

# Initialize
broker = get_broker_integration('coinbase')

# Create risk gate
risk_gate = create_risk_intelligence_gate(
    volatility_sizer=None,  # Optional: pass instance
    portfolio_risk_engine=None,  # Optional: pass instance
    config={
        'max_volatility_multiplier': 3.0,
        'max_correlation_exposure': 0.40,
        'min_diversification_ratio': 0.5
    }
)

# Proposed trade
symbol = 'BTC-USD'
proposed_size = 500.0  # $500 position
account_balance = 10000.0
current_positions = broker.get_open_positions()
df = broker.get_market_data(symbol, timeframe='1h', limit=100)

# Pre-trade assessment
approved, assessment = risk_gate.pre_trade_risk_assessment(
    symbol=symbol,
    df=df,
    proposed_position_size=proposed_size,
    current_positions=current_positions,
    account_balance=account_balance
)

if approved:
    print("✅ Trade approved - proceed with execution")
else:
    print("❌ Trade rejected:")
    for reason in assessment['rejection_reasons']:
        print(f"  - {reason}")
```

### Integration with Trading Strategy

```python
# In your trading strategy execute method:

def execute_trade(self, symbol, signal, df):
    # Calculate position size
    position_size = self.calculate_position_size(symbol, df)
    
    # ✅ NEW: Pre-trade risk check
    approved, assessment = self.risk_gate.pre_trade_risk_assessment(
        symbol=symbol,
        df=df,
        proposed_position_size=position_size,
        current_positions=self.broker.get_open_positions(),
        account_balance=self.broker.get_account_balance()
    )
    
    if not approved:
        logger.warning(f"Trade rejected by risk gate: {symbol}")
        for reason in assessment['rejection_reasons']:
            logger.warning(f"  - {reason}")
        return None  # Don't execute
    
    # Risk checks passed - proceed with trade
    return self.broker.place_order(symbol, 'buy', position_size)
```

---

## 3. Complete Integration Example

### Bot Startup Sequence

```python
from bot.position_tracker import PositionTracker
from bot.broker_integration import get_broker_integration
from bot.legacy_position_exit_protocol import LegacyPositionExitProtocol, AccountState
from bot.risk_intelligence_gate import create_risk_intelligence_gate

def bot_startup():
    # 1. Initialize components
    position_tracker = PositionTracker()
    broker = get_broker_integration('coinbase')
    
    # 2. Run legacy cleanup with high-exposure monitoring
    protocol = LegacyPositionExitProtocol(
        position_tracker=position_tracker,
        broker_integration=broker,
        monitor_high_exposure=True
    )
    
    state, diagnostics = protocol.verify_clean_state()
    
    if state != AccountState.CLEAN:
        logger.warning("Account needs cleanup - running protocol...")
        results = protocol.run_full_protocol()
        
        if not results['success']:
            logger.error("Cleanup failed - manual intervention needed")
            return False
    
    logger.info("✅ Account is CLEAN")
    
    # 3. Initialize risk intelligence gate
    risk_gate = create_risk_intelligence_gate()
    
    logger.info("✅ Bot startup complete")
    return True
```

### Trading Loop Integration

```python
def trading_loop():
    while True:
        # Scan for signals
        signals = strategy.scan_markets()
        
        for signal in signals:
            symbol = signal['symbol']
            
            # Get market data
            df = broker.get_market_data(symbol, timeframe='1h', limit=100)
            
            # Calculate position size
            position_size = risk_manager.calculate_position_size(df, account_balance)
            
            # ✅ Pre-trade risk assessment
            approved, assessment = risk_gate.pre_trade_risk_assessment(
                symbol=symbol,
                df=df,
                proposed_position_size=position_size,
                current_positions=broker.get_open_positions(),
                account_balance=account_balance
            )
            
            if not approved:
                logger.warning(f"Trade rejected: {symbol}")
                continue  # Skip this trade
            
            # Execute trade
            broker.place_order(symbol, 'buy', position_size)
```

---

## 4. Configuration

### Legacy Exit Protocol Config

```python
protocol = LegacyPositionExitProtocol(
    position_tracker=position_tracker,
    broker_integration=broker,
    max_positions=8,                # Max positions allowed
    dust_pct_threshold=0.01,        # 1% of account = dust
    stale_order_minutes=30,         # Orders >30 min are stale
    gradual_unwind_pct=0.25,        # Unwind 25% per cycle
    unwind_cycles=4,                # 4 cycles for gradual unwind
    monitor_high_exposure=True      # Enable high-exposure monitoring
)
```

### Risk Intelligence Gate Config

```python
risk_gate = create_risk_intelligence_gate(
    config={
        'max_volatility_multiplier': 3.0,    # Max 3x target volatility
        'max_correlation_exposure': 0.40,     # Max 40% in correlated assets
        'min_diversification_ratio': 0.5      # Min diversification ratio
    }
)
```

---

## 5. Monitoring & Alerts

### High-Exposure Alert Types

| Alert Type | Severity | Trigger | Action |
|------------|----------|---------|--------|
| `OVERSIZED_HIGH_EXPOSURE` | CRITICAL | Position >10% of account | Reduce size or tighten stops |
| `NEAR_DUST_THRESHOLD` | WARNING | Position <2x dust threshold | Monitor for auto-cleanup |
| `EXCESSIVE_HIGH_EXPOSURE_CONCENTRATION` | CRITICAL | Total high-exposure >25% | Diversify portfolio |

### Risk Gate Rejection Reasons

| Check | Rejection Reason | Solution |
|-------|------------------|----------|
| Volatility Scaling | "Volatility too high: 4.5x vs 3.0x limit" | Wait for volatility to normalize |
| Correlation Exposure | "Correlated exposure too high: 45% vs 40% limit" | Reduce exposure to correlated assets |
| Diversification | "Insufficient diversification: 0.3 vs 0.5 minimum" | Add uncorrelated positions |

---

## 6. Testing

### Test Legacy Exit Protocol

```bash
# Test with dry run
python run_legacy_exit_protocol.py --dry-run

# Verify only (no trades)
python run_legacy_exit_protocol.py --verify-only

# Run on specific broker
python run_legacy_exit_protocol.py --broker coinbase
```

### Test Risk Intelligence Gate

```bash
# Run integration examples
python example_risk_intelligence_integration.py
```

### Unit Tests

```bash
# Test legacy exit protocol
python test_legacy_exit_protocol.py

# Test risk intelligence gate
python -m pytest bot/test_risk_intelligence_gate.py -v
```

---

## 7. Best Practices

### ✅ DO

1. **Run legacy cleanup at startup** before opening new positions
2. **Enable high-exposure monitoring** for all accounts
3. **Use risk intelligence gate** for ALL new entries
4. **Review alerts daily** and take action on CRITICAL alerts
5. **Track capital freed** from stale orders and cleanup

### ❌ DON'T

1. **Don't bypass risk gate** checks to force trades
2. **Don't ignore high-exposure alerts** - they indicate real risk
3. **Don't disable monitoring** in production
4. **Don't trade high-exposure assets** without tight stops
5. **Don't exceed correlation limits** - diversify instead

---

## 8. Files

| File | Purpose | Lines |
|------|---------|-------|
| `bot/legacy_position_exit_protocol.py` | Enhanced legacy cleanup with monitoring | 1200+ |
| `bot/risk_intelligence_gate.py` | Pre-entry risk verification | 500+ |
| `example_risk_intelligence_integration.py` | Integration examples | 300+ |
| `run_legacy_exit_protocol.py` | CLI interface | 214 |
| `RISK_INTELLIGENCE_README.md` | This documentation | 350+ |

---

## 9. FAQ

**Q: What happens if I have PEPE or LUNA positions?**
A: They are automatically flagged as `LEGACY_NON_COMPLIANT` and monitored closely. If >10% of account, a CRITICAL alert is generated. Consider reducing size.

**Q: Will the risk gate block all my trades?**
A: No. It only blocks trades that violate risk limits (excessive volatility or correlation). Most normal trades will pass.

**Q: Can I disable high-exposure monitoring?**
A: Yes, set `monitor_high_exposure=False`, but this is NOT recommended for production.

**Q: How do I know if my account is CLEAN?**
A: Run `python run_legacy_exit_protocol.py --verify-only`. It will report `CLEAN` or `NEEDS_CLEANUP`.

**Q: What if cleanup fails?**
A: Check logs for specific errors. Common issues: delisted assets, API errors, insufficient balance. May need manual intervention.

---

## 10. Support

For issues or questions:
- Check logs for detailed error messages
- Review state file: `data/legacy_exit_protocol_state.json`
- Run with `--dry-run` to simulate
- See integration examples: `example_risk_intelligence_integration.py`

---

**Version**: 1.0  
**Last Updated**: February 2026  
**Author**: NIJA Trading Systems
