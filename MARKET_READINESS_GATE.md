# Market Readiness Gate Documentation

## Overview

The Market Readiness Gate is a global entry quality control system that prevents trading in unfavorable market conditions. It implements three operating modes to protect capital and improve profitability:

1. **AGGRESSIVE MODE** - Full trading with optimal conditions
2. **CAUTIOUS MODE** - Limited trading with reduced position sizes
3. **IDLE MODE** - No entries, exits only

## Philosophy

**Profitability doesn't come from more trades. It comes from fewer, higher-quality trades.**

The Market Readiness Gate:
- Stops trading when edge ≈ 0
- Preserves capital
- Waits for expansion, not noise
- Ensures when trades happen, they matter

## Operating Modes

### AGGRESSIVE MODE (Full Trading)

**Activate only if ALL conditions are true:**
- ATR ≥ 0.6%
- ADX ≥ 25
- Volume percentile ≥ 60%
- Spread ≤ 0.15%
- Meaningful win rate (rolling 24h) ≥ 45%

**Effect:**
- ✅ Full position sizing allowed
- ✅ All entry signals permitted
- ✅ Normal trading operations

**Example Log:**
```
🚀 AGGRESSIVE MODE: ATR=0.67%, ADX=30.0, Vol=70%, WR=52.3%
```

---

### CAUTIOUS MODE (Limited Trading)

**Activate if some conditions pass:**
- ATR 0.4%–0.6%
- ADX 18–25
- Volume ≥ 40%

**Effect:**
- ⚠️ Size capped at 20% of normal
- ⚠️ Only A+ setups (score ≥ 85)
- ⚠️ Reduced trading frequency

**Example Log:**
```
⚠️ CAUTIOUS MODE - Position size reduced to 20%
   Original: $50.00 → Cautious: $10.00
   Entry score: 88/100 (A+ setup)
```

---

### IDLE MODE (No Entries)

**Activate if ANY of these are true:**
- ATR < 0.4%
- Spread > expected move
- 3 consecutive non-meaningful wins
- Circuit breaker recently cleared (<2h)

**Effect:**
- 🛑 No entries
- ✅ Exits only
- 📊 Log: "Market not paying traders right now"

**Example Log:**
```
🛑 IDLE MODE: ATR too low (0.33% < 0.40%)
   Market not paying traders right now
```

---

## Key Metrics

### ATR (Average True Range)
- Measures market volatility
- Calculated as percentage of price
- **Why it matters:** Low ATR means small moves → fees eat profits

### ADX (Average Directional Index)
- Measures trend strength
- Range: 0-100
- **Why it matters:** Weak trends → choppy markets → false signals

### Volume Percentile
- Current volume vs 20-period average
- Range: 0-100%
- **Why it matters:** Low volume → wide spreads → poor fills

### Meaningful Win Rate
- Rolling 24h win rate
- **Meaningful win:** Profit > 0.2% (covers fees + small profit)
- **Why it matters:** Many small wins = not actually profitable

---

## Integration

### In Trading Strategy

The Market Readiness Gate is checked **twice** per entry:

1. **Pre-analysis check** (without entry score)
   - Blocks IDLE mode conditions early
   - Saves API calls and computation

2. **Post-analysis check** (with entry score)
   - Applies CAUTIOUS mode score filtering
   - Adjusts position size based on mode

```python
# Example integration in trading_strategy.py
if self.market_readiness_gate:
    # Pre-check
    mode, conditions, details = gate.check_market_readiness(...)
    if mode == MarketMode.IDLE:
        continue  # Skip this market
    
    # Analyze market
    analysis = self.apex.analyze_market(df, symbol, balance)
    entry_score = analysis.get('score', 0)
    
    # Post-check with score
    mode, conditions, details = gate.check_market_readiness(..., entry_score=entry_score)
    if mode == MarketMode.CAUTIOUS:
        position_size *= details['position_size_multiplier']  # Reduce to 20%
```

### With Circuit Breakers

When the broker failsafe system triggers a circuit breaker (3 consecutive losses), it automatically notifies the Market Readiness Gate:

```python
# In broker_failsafes.py
if consecutive_losses >= 3:
    gate.record_circuit_breaker_clear()
    # IDLE mode activated for 2 hours
```

### Trade Result Tracking

All trade results are recorded for win rate calculation:

```python
# In trading_strategy.py
if self.market_readiness_gate:
    pnl_pct = profit_usd / position_size
    gate.record_trade_result(pnl_pct)
```

---

## State Persistence

The Market Readiness Gate persists state to `.market_readiness_state.json`:

```json
{
  "trades_24h": [
    {
      "timestamp": "2026-02-05T23:45:08.563456",
      "profit_pct": 0.015,
      "meaningful": true
    }
  ],
  "last_circuit_breaker_clear": "2026-02-05T22:30:00.000000"
}
```

**Cleanup:** Trades older than 24 hours are automatically removed.

---

## Configuration

### Thresholds (in `market_readiness_gate.py`)

```python
# AGGRESSIVE mode
AGGRESSIVE_ATR_MIN = 0.006        # 0.6%
AGGRESSIVE_ADX_MIN = 25.0
AGGRESSIVE_VOLUME_PERCENTILE_MIN = 60.0
AGGRESSIVE_SPREAD_MAX = 0.0015    # 0.15%
AGGRESSIVE_WIN_RATE_MIN = 0.45    # 45%

# CAUTIOUS mode
CAUTIOUS_ATR_MIN = 0.004          # 0.4%
CAUTIOUS_ATR_MAX = 0.006          # 0.6%
CAUTIOUS_ADX_MIN = 18.0
CAUTIOUS_ADX_MAX = 25.0
CAUTIOUS_VOLUME_PERCENTILE_MIN = 40.0
CAUTIOUS_SIZE_MIN = 0.15          # 15%
CAUTIOUS_SIZE_MAX = 0.25          # 25%
CAUTIOUS_MIN_SCORE = 85           # Only A+ setups

# IDLE mode
IDLE_ATR_MAX = 0.004              # 0.4%
IDLE_NON_MEANINGFUL_WIN_THRESHOLD = 3
IDLE_CIRCUIT_BREAKER_COOLDOWN_HOURS = 2.0

# Meaningful win threshold
MEANINGFUL_WIN_THRESHOLD = 0.002  # 0.2% profit
```

---

## Testing

Run the test suite to validate the Market Readiness Gate:

```bash
python bot/test_market_readiness_gate.py
```

Tests cover:
1. ✅ AGGRESSIVE mode activation
2. ✅ CAUTIOUS mode with A+ setup
3. ✅ CAUTIOUS mode blocking low scores
4. ✅ IDLE mode - low ATR
5. ✅ IDLE mode - circuit breaker cooldown
6. ✅ IDLE mode - non-meaningful wins
7. ✅ Win rate tracking

---

## Logs and Monitoring

### Example Live Logs

**AGGRESSIVE Mode:**
```
🚀 AGGRESSIVE MODE: ATR=0.67%, ADX=30.0, Vol=70%, WR=52.3%
   BTC-USD: LONG entry at $65,432.10
   Position size: $50.00 (full sizing)
```

**CAUTIOUS Mode:**
```
⚠️ CAUTIOUS MODE: Limited trading (20% size, score≥85)
   ETH-USD: LONG entry at $3,210.45
   Original: $50.00 → Cautious: $10.00
   Entry score: 88/100 (A+ setup)
```

**IDLE Mode:**
```
🛑 IDLE MODE: ATR too low (0.33% < 0.40%)
   Market not paying traders right now
   No entries until conditions improve
```

### Status Checking

To check current market readiness state:

```python
from bot.market_readiness_gate import MarketReadinessGate

gate = MarketReadinessGate()
win_rate, total, meaningful = gate.calculate_win_rate_24h()
hours_since_cb = gate.get_hours_since_circuit_breaker_clear()

print(f"Win Rate (24h): {win_rate*100:.1f}%")
print(f"Total Trades: {total}")
print(f"Meaningful Wins: {meaningful}")
print(f"Circuit Breaker: {hours_since_cb:.1f}h ago")
```

---

## Benefits

### Capital Preservation
- Prevents trading when edge is minimal
- Stops loss-accumulation in poor conditions
- Enforces cooldown after circuit breakers

### Improved Win Rate
- Filters low-quality setups in marginal conditions
- Only trades A+ setups when conditions are marginal
- Waits for expansion instead of noise

### Better Position Sizing
- Reduces size when conditions are uncertain
- Full size only when conditions are optimal
- Protects against over-leverage in choppy markets

### Honest Performance
- Doesn't force trades for activity
- Acknowledges when market isn't paying
- Creates auditable decision trail

---

## FAQs

**Q: Why do we need three modes instead of just entry filters?**

A: Different market conditions require different approaches. AGGRESSIVE mode allows full trading, CAUTIOUS mode limits risk while still participating, and IDLE mode prevents capital erosion when conditions are poor. This gradient approach is more nuanced than binary on/off.

**Q: What counts as a "meaningful" win?**

A: A meaningful win is one that covers fees plus provides actual profit. With typical 1.4% round-trip fees, we set the threshold at 0.2% profit. Wins below this threshold indicate the strategy is churning without real profitability.

**Q: Can I override IDLE mode manually?**

A: No. IDLE mode is a hard block designed to protect capital. If you need to trade during IDLE mode, you should investigate why conditions are poor and address the root cause rather than forcing trades.

**Q: How long does circuit breaker cooldown last?**

A: 2 hours. This gives time for market conditions to reset and prevents immediate re-entry into the same poor conditions that triggered losses.

**Q: What happens to existing positions in IDLE mode?**

A: Existing positions are managed normally (exits, stops, profit-taking). IDLE mode only blocks new entries.

---

## See Also

- `bot/market_readiness_gate.py` - Implementation
- `bot/test_market_readiness_gate.py` - Test suite
- `bot/broker_failsafes.py` - Circuit breaker integration
- `bot/trading_strategy.py` - Integration in main strategy
