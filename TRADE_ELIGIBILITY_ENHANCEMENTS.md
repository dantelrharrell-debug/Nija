# Trade Eligibility and Kraken Safety Enhancements

**Implementation Date:** January 30, 2026  
**Feature:** Comprehensive trade eligibility verification with Kraken-specific safety tuning

## Overview

This update adds three critical improvements to the NIJA trading system:

1. **Comprehensive Trade Eligibility Verification** - Unified pre-trade checks for RSI, volatility, and spread
2. **Kraken-Specific Safety Tuning** - Configurable conservative thresholds for Kraken trading
3. **First Trade Sanity Check** - Detailed logging before the first trade execution

## Features

### 1. Trade Eligibility Verification

The new `verify_trade_eligibility()` method performs comprehensive pre-trade validation:

#### Checks Performed

- **RSI Range Check**: Ensures RSI is within acceptable range (30-70 for both long/short)
  - Prevents trading in extreme overbought/oversold conditions
  - Reduces false signals from RSI extremes

- **Volatility Check (ATR)**: Verifies sufficient market volatility
  - Minimum: 0.5% ATR (configurable)
  - Ensures adequate price movement for profitable trading
  - Avoids choppy, low-volatility markets

- **Spread Check** (optional): Validates bid-ask spread if prices provided
  - Maximum: 0.15% spread
  - Prevents high slippage costs
  - Only applied when bid/ask prices are available

- **Broker-Specific Safety**: Additional checks for specific brokers
  - Kraken: Stricter RSI and ATR thresholds
  - Prevents over-aggressive trading on high-fee platforms

#### Example Output

```
✅ Trade eligible: RSI=50.0, ATR=0.95%
```

or

```
❌ Trade not eligible: RSI 75.0 outside LONG range 30-70; Volatility too low: ATR 0.10% < 0.5% minimum
```

### 2. Kraken-Specific Safety Tuning

Kraken trading now has configurable conservative thresholds to prevent over-aggressive trading:

#### Configuration via Environment Variables

Add to your `.env` file:

```bash
# Kraken RSI Range (default: 35-65, more conservative than general 30-70)
KRAKEN_MIN_RSI=35  # Minimum RSI for trade entry
KRAKEN_MAX_RSI=65  # Maximum RSI for trade entry

# Kraken Confidence Threshold (default: 0.65, higher than general 0.60)
KRAKEN_MIN_CONFIDENCE=0.65  # Minimum confidence score (0.0-1.0)

# Kraken Volatility Threshold (default: 0.6%, higher than general 0.5%)
KRAKEN_MIN_ATR_PCT=0.6  # Minimum ATR as percentage
```

#### Tuning Guidelines

**More Aggressive** (More trades, potentially lower quality):
```bash
KRAKEN_MIN_RSI=30
KRAKEN_MAX_RSI=70
KRAKEN_MIN_CONFIDENCE=0.60
KRAKEN_MIN_ATR_PCT=0.5
```

**More Conservative** (Fewer trades, higher quality):
```bash
KRAKEN_MIN_RSI=40
KRAKEN_MAX_RSI=60
KRAKEN_MIN_CONFIDENCE=0.70
KRAKEN_MIN_ATR_PCT=0.8
```

**Default (Balanced)**:
```bash
KRAKEN_MIN_RSI=35
KRAKEN_MAX_RSI=65
KRAKEN_MIN_CONFIDENCE=0.65
KRAKEN_MIN_ATR_PCT=0.6
```

### 3. First Trade Sanity Check

Before executing the first trade, the system logs comprehensive details for review:

#### Example Output

```
================================================================================
🔔 FIRST TRADE SANITY CHECK - Review before execution
================================================================================
Symbol: BTC-USD
Direction: LONG
Entry Price: $42,150.25
Position Size: $50.00
Account Balance: $250.00
Broker: KRAKEN
--------------------------------------------------------------------------------
Signal Quality:
  - Entry Score: 4.2/5 (legacy)
  - Confidence: 0.68
  - ADX: 24.5
--------------------------------------------------------------------------------
Eligibility Checks:
  ✅ rsi: {'value': 48.5, 'range': '30-70', 'valid': True}
  ✅ volatility: {'atr_pct': 0.85, 'min_required': 0.5, 'valid': True}
  ✅ spread: {'valid': True, 'note': 'Bid/ask prices not provided'}
  ✅ kraken_rsi_safety: {'value': 48.5, 'safe_range': '35.0-65.0', 'valid': True}
  ✅ kraken_atr_safety: {'atr_pct': 0.85, 'min_required': 0.6, 'valid': True}
--------------------------------------------------------------------------------
Risk Management:
  - Trend: uptrend
  - Reason: LONG | Regime:trending | Legacy:4/5 | Enhanced:72.5/100 | Good
================================================================================
```

This gives you a final chance to verify:
- Entry conditions are correct
- Position sizing is appropriate
- Risk parameters are set correctly
- All safety checks have passed

## Integration

### In Code

The eligibility check is automatically integrated into the strategy:

```python
# Comprehensive eligibility verification
eligibility = self.verify_trade_eligibility(
    symbol, df, indicators, 'long', position_size
)
if not eligibility['eligible']:
    logger.info(f"Trade eligibility check failed: {eligibility['reason']}")
    return {'action': 'hold', 'reason': eligibility['reason']}
```

### Trade Flow

1. Market filter checks trend conditions
2. Entry signal calculated (RSI, MACD, price action)
3. Position size calculated
4. **Trade quality validation** (confidence, minimum size)
5. **✅ NEW: Comprehensive eligibility check** (RSI, ATR, spread)
6. **✅ NEW: Kraken safety checks** (if on Kraken)
7. **✅ NEW: First trade sanity check** (if first trade)
8. Calculate stop loss and take profit
9. Execute trade

## Benefits

### 1. Reduced False Signals
- Filters out extreme RSI conditions
- Avoids low-volatility choppy markets
- Prevents wide-spread trades with high slippage

### 2. Kraken Safety
- Conservative thresholds prevent over-trading on Kraken
- Configurable tuning for different risk appetites
- Separate controls from general strategy parameters

### 3. Transparency
- First trade sanity check provides visibility
- Detailed logging of all eligibility checks
- Easy to diagnose why trades are rejected

### 4. Flexibility
- Environment variable configuration (no code changes)
- Per-broker customization
- Easy to adjust based on market conditions

## Testing

Run the test suite to verify functionality:

```bash
python test_trade_eligibility.py
```

Expected output:
```
✅ All trade eligibility tests passed!
```

## Monitoring

Watch the logs for:

- `✅ Trade eligible:` - Trade passed all checks
- `❌ Trade not eligible:` - Trade rejected with reason
- `⏭️ Trade eligibility check failed:` - Eligibility check blocked trade
- `🔔 FIRST TRADE SANITY CHECK` - First trade details

## Rollback

If you need to disable these features temporarily:

1. Set less restrictive thresholds:
   ```bash
   KRAKEN_MIN_RSI=20
   KRAKEN_MAX_RSI=80
   KRAKEN_MIN_CONFIDENCE=0.50
   KRAKEN_MIN_ATR_PCT=0.3
   ```

2. The checks are still performed but will allow more trades through

## Future Enhancements

Potential improvements for future versions:

1. Dynamic threshold adjustment based on market regime
2. Machine learning-based eligibility scoring
3. Historical performance tracking by eligibility score
4. Real-time spread monitoring from exchange APIs
5. News event filtering integration
6. Multi-timeframe confirmation

## Support

For issues or questions:
1. Check logs for detailed eligibility check results
2. Verify environment variables are set correctly
3. Run test suite to ensure functionality
4. Review sanity check output for first trade
