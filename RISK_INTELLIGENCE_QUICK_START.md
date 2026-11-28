# Quick Start Guide: Risk Intelligence Features

## 🚀 Quick Start (5 Minutes)

### 1. Run Legacy Cleanup with Monitoring

```bash
# Command line - simplest way
python run_legacy_exit_protocol.py --broker coinbase
```

**What it does:**
- ✅ Classifies all positions (strategy-aligned, legacy, zombie)
- ✅ Cancels stale orders (>30 min old) and frees capital
- ✅ Monitors high-exposure assets (PEPE, LUNA, SHIB, DOGE, FLOKI)
- ✅ Generates alerts for risky positions
- ✅ Executes controlled exits (dust, over-cap, legacy)
- ✅ Verifies account is CLEAN

### 2. Check Results

```bash
# View state file
cat data/legacy_exit_protocol_state.json

# Key metrics to check:
# - account_state: "CLEAN" or "NEEDS_CLEANUP"
# - cleanup_metrics.capital_freed_usd: $$$
# - high_exposure_assets_tracked: ["PEPE-USD", ...]
# - high_exposure_alerts: [...]
```

### 3. Use in Trading Strategy

```python
from bot.risk_intelligence_gate import create_risk_intelligence_gate

# Initialize once at startup
risk_gate = create_risk_intelligence_gate()

# Before EVERY new trade
approved, assessment = risk_gate.pre_trade_risk_assessment(
    symbol='BTC-USD',
    df=market_data,
    proposed_position_size=500.0,
    current_positions=broker.get_open_positions(),
    account_balance=broker.get_account_balance()
)

if approved:
    broker.place_order(...)  # ✅ Safe to trade
else:
    logger.warning(f"Trade rejected")  # ❌ Don't trade
```

---

## 📋 Common Commands

### Check Account Status
```bash
python run_legacy_exit_protocol.py --verify-only
```

### Dry Run (Simulate)
```bash
python run_legacy_exit_protocol.py --dry-run
```

### Custom Settings
```bash
python run_legacy_exit_protocol.py \
  --broker coinbase \
  --max-positions 10 \
  --dust-pct 0.02 \
  --stale-minutes 60
```

---

## 🚨 High-Exposure Assets Monitored

Automatically flagged and monitored:
- **PEPE-USD, PEPE-USDT** (meme coin, high volatility)
- **LUNA-USD, LUNA-USDT, LUNA2-USD** (delisting risk)
- **SHIB-USD, SHIB-USDT** (meme coin)
- **DOGE-USD, DOGE-USDT** (meme coin)
- **FLOKI-USD, FLOKI-USDT** (meme coin)

### Alerts Generated

| Alert | Trigger | Action |
|-------|---------|--------|
| OVERSIZED_HIGH_EXPOSURE | Position >10% of account | Reduce size or tighten stops |
| NEAR_DUST_THRESHOLD | Position <2x dust | Monitor for auto-cleanup |
| EXCESSIVE_CONCENTRATION | Total high-exposure >25% | Diversify portfolio |

---

## 🎯 Risk Intelligence Checks

### Before Opening New Position

The risk gate checks TWO things:

1. **Volatility Check** ✅
   - Is market volatility acceptable? (< 3x target)
   - PASS: Normal volatility, safe to trade
   - FAIL: Extreme volatility, wait for calm

2. **Correlation Check** ✅
   - Will this add too much correlated exposure? (< 40% per group)
   - PASS: Good diversification
   - FAIL: Over-concentrated, pick different asset

**Both must pass to approve trade.**

---

## 📊 State File Location

**Path**: `data/legacy_exit_protocol_state.json`

**Key Fields:**
```json
{
  "account_state": "CLEAN",
  "cleanup_metrics": {
    "total_positions_cleaned": 15,
    "capital_freed_usd": 247.50
  },
  "high_exposure_assets_tracked": ["PEPE-USD"],
  "high_exposure_alerts": [...]
}
```

---

## 🔄 Integration Patterns

### Pattern 1: Startup Check
```python
def bot_startup():
    protocol = LegacyPositionExitProtocol(...)
    state, _ = protocol.verify_clean_state()

    if state != AccountState.CLEAN:
        protocol.run_full_protocol()
```

### Pattern 2: Pre-Trade Gate
```python
def execute_trade(symbol, size):
    approved, _ = risk_gate.pre_trade_risk_assessment(...)

    if not approved:
        return None  # Reject trade

    return broker.place_order(...)
```

### Pattern 3: Scheduled Cleanup
```python
# Cron job: Every 6 hours
0 */6 * * * python run_legacy_exit_protocol.py
```

---

## ⚠️ Common Issues

### "Account not CLEAN"
**Solution**: Run full protocol to cleanup
```bash
python run_legacy_exit_protocol.py
```

### "Trade rejected - volatility too high"
**Solution**: Wait for volatility to normalize (check later)

### "Trade rejected - correlation exposure too high"
**Solution**: Close some correlated positions first, or pick different asset

### High-exposure alert
**Solution**:
- If CRITICAL: Reduce position size immediately
- If WARNING: Monitor closely, tighten stops

---

## 📚 Documentation

- **User Guide**: `RISK_INTELLIGENCE_README.md` (complete documentation)
- **Examples**: `example_risk_intelligence_integration.py` (4 examples)
- **Technical**: `IMPLEMENTATION_SUMMARY_RISK_INTELLIGENCE.md` (details)

---

## 💡 Best Practices

### ✅ DO

1. Run cleanup at bot startup
2. Enable high-exposure monitoring
3. Use risk gate for ALL new entries
4. Review alerts daily
5. Track capital freed

### ❌ DON'T

1. Bypass risk gate checks
2. Ignore CRITICAL alerts
3. Disable monitoring in production
4. Trade high-exposure assets without stops
5. Exceed correlation limits

---

## 🆘 Support

**If you need help:**

1. Check logs: `logs/nija.log`
2. Check state file: `data/legacy_exit_protocol_state.json`
3. Run dry run: `python run_legacy_exit_protocol.py --dry-run`
4. Review examples: `example_risk_intelligence_integration.py`

---

## 🎓 Learning Path

1. **Start here**: Run `python run_legacy_exit_protocol.py --verify-only`
2. **Next**: Read `RISK_INTELLIGENCE_README.md` sections 1-3
3. **Then**: Try examples in `example_risk_intelligence_integration.py`
4. **Finally**: Integrate into your trading strategy

---

**That's it! You're ready to use risk intelligence features.** 🎉

For detailed documentation, see `RISK_INTELLIGENCE_README.md`.
