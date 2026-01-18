# NIJA PRO MODE - Position Rotation Trading

## Overview

PRO MODE transforms NIJA into a hedge-fund style trading system that counts open position values as available capital and can rotate positions to capture better opportunities.

## What is PRO MODE?

In standard mode, NIJA can only open new positions when it has free USD balance available. This means if all your capital is locked in positions, the bot cannot take advantage of new opportunities even if they're better than your current holdings.

**PRO MODE solves this by:**
- ✅ Counting open position values as available capital
- ✅ Enabling position-to-position rotation
- ✅ Closing weak positions to fund better opportunities
- ✅ Never "starving" by having all capital locked

## How It Works

### Capital Calculation

**Standard Mode:**
```
Available Capital = Free USD Balance
```

**PRO MODE:**
```
Total Capital = Free USD Balance + Position Values
Available for New Trades = Total Capital (with minimum reserve)
```

Example with $100 account:
- Standard Mode: $10 free + $90 in positions = Can only use $10 for new trades
- PRO Mode: $10 free + $90 in positions = Can use up to $100 for new trades (maintaining 15% reserve)

### Position Rotation

When PRO MODE detects a better opportunity but insufficient free balance, it automatically:

1. **Scores Current Positions** (0-100 scale)
   - Lower scores = Better candidates for rotation
   - Factors: P&L, age, RSI, position size

2. **Selects Positions to Close**
   - Prioritizes losing positions first
   - Then stale/old positions
   - Then overbought positions
   - Keeps profitable positions when possible

3. **Executes Rotation**
   - Closes selected positions
   - Frees up capital
   - Opens new position with better setup

4. **Maintains Reserve**
   - Always keeps minimum free balance (default 15%)
   - Prevents being 100% locked in positions
   - Ensures liquidity for market volatility

### Rotation Scoring System

Positions are scored for rotation priority (higher score = more likely to close):

| Factor | Impact | Score Adjustment |
|--------|--------|------------------|
| **P&L** | Most Important | |
| - Big loser (< -5%) | Close first | +30 |
| - Small loser (-2% to -5%) | High priority | +20 |
| - Slight loser (0% to -2%) | Medium priority | +10 |
| - Big winner (> +5%) | Keep | -30 |
| - Good profit (+2% to +5%) | Keep | -20 |
| **Age** | | |
| - Very stale (> 8 hours) | Close | +15 |
| - Moderately stale (4-8 hours) | Consider | +10 |
| - Very new (< 30 min) | Keep | -10 |
| **RSI** | | |
| - Overbought (> 70) | Good exit time | +15 |
| - Oversold (< 30) | Might recover | -15 |
| **Size** | | |
| - Very small (< $5) | Easy to rotate | +10 |
| - Small ($5-$10) | Easy to rotate | +5 |

## Configuration

### Enable PRO MODE

**Option 1: Environment Variable**
```bash
# In your .env file
PRO_MODE=true
PRO_MODE_MIN_RESERVE_PCT=0.15  # 15% minimum free balance
```

**Option 2: Railway/Render Deployment**
```
Add environment variables:
- PRO_MODE = true
- PRO_MODE_MIN_RESERVE_PCT = 0.15
```

### Configuration Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `PRO_MODE` | false | Enable/disable PRO MODE |
| `PRO_MODE_MIN_RESERVE_PCT` | 0.15 | Minimum free balance % (15% default) |

### Reserve Percentage Guide

Choose based on your risk tolerance and trading style:

| Reserve % | Profile | Use Case |
|-----------|---------|----------|
| 10% | Aggressive | Maximum capital utilization, higher risk |
| 15% | Balanced | Recommended for most traders |
| 20% | Conservative | More safety buffer, less rotation |
| 25% | Very Conservative | Maximum stability, minimal rotation |

## Usage Examples

### Example 1: Basic Rotation

**Scenario:**
- Total Capital: $100
- Free Balance: $5
- Positions: $95 (BTC, ETH, SOL)
- New Opportunity: XRP (needs $10)

**Without PRO MODE:**
- ❌ Cannot trade - only $5 free
- ❌ Must wait for positions to close
- ❌ Misses opportunity

**With PRO MODE:**
- ✅ Scores positions (SOL is losing -3%)
- ✅ Closes SOL position ($10 freed)
- ✅ Opens XRP position
- ✅ Maintains $5 minimum reserve (5% of $100)

### Example 2: Multiple Position Rotation

**Scenario:**
- Total Capital: $200
- Free Balance: $10
- Positions: 6 positions totaling $190
- New Opportunity: Strong signal requiring $50

**PRO MODE Actions:**
1. Identifies need for $40 more capital ($50 - $10 free)
2. Scores all 6 positions
3. Selects 2-3 weakest positions totaling $40+
4. Closes selected positions
5. Opens new $50 position
6. Maintains $30 minimum reserve (15% of $200)

### Example 3: Reserve Protection

**Scenario:**
- Total Capital: $100
- Free Balance: $12 (already at minimum 12%)
- Opportunity: Needs $20

**PRO MODE Actions:**
- ⚠️ Below minimum reserve (need 15% = $15)
- ✅ Must rotate $8 from positions
- ✅ Closes small losing position
- ✅ Restores reserve before new trade

## Risk Considerations

### Advantages ✅

1. **Never Starves**: Always has capital available for opportunities
2. **Adaptive**: Responds to better setups by rotating
3. **Efficient**: Maximizes capital utilization
4. **Disciplined**: Automatically closes losers
5. **Protected**: Maintains minimum reserve

### Risks ⚠️

1. **Higher Trading Frequency**: More trades = more fees
2. **Premature Exits**: Might close positions that would recover
3. **Complexity**: More moving parts to understand
4. **Market Volatility**: Rapid rotations in choppy markets

### When to Use PRO MODE

**Good For:**
- ✅ Experienced traders comfortable with rotation
- ✅ Accounts with sufficient capital ($100+ recommended)
- ✅ Strong trending markets with clear opportunities
- ✅ Active monitoring and understanding of rotation logic

**Not Recommended For:**
- ❌ Beginners new to trading
- ❌ Very small accounts (< $50)
- ❌ Set-and-forget passive trading
- ❌ Low-liquidity markets

## Monitoring PRO MODE

### Key Metrics to Watch

1. **Free Balance Reserve**
   - Should stay above minimum (15% default)
   - Alerts if consistently below minimum

2. **Rotation Count**
   - Track daily/weekly rotations
   - High rotation count may indicate instability

3. **Position Age**
   - Average holding time
   - Excessive rotation = very short holds

4. **P&L per Rotation**
   - Did rotation improve performance?
   - Track rotation effectiveness

### Log Messages

PRO MODE adds specific log messages:

```
💰 PRO MODE Capital:
   Free balance: $10.00
   Position value: $90.00
   Total capital: $100.00
   Positions: 3

🔄 PRO MODE: Position size $15.00 exceeds free balance $10.00
   → Rotation needed: $5.00

✅ Rotation allowed: Below minimum free balance reserve (10.0% < 15%)

🔄 Closing 1 position(s) for rotation:
   Closing SOL-USD: 0.15000000
   ✅ Closed SOL-USD successfully

✅ Rotation complete: Closed 1 positions
💰 Updated free balance: $15.00

🎯 BUY SIGNAL: XRP-USD - size=$15.00
```

## Troubleshooting

### PRO MODE Not Working

**Issue**: Bot still stops trading when out of free balance

**Solutions:**
1. Check `PRO_MODE=true` in .env file
2. Restart bot after enabling
3. Verify rotation_manager.py exists in bot/
4. Check logs for PRO MODE initialization message

### Excessive Rotations

**Issue**: Bot rotating positions too frequently

**Solutions:**
1. Increase `PRO_MODE_MIN_RESERVE_PCT` to 20-25%
2. Review rotation quality - are new opportunities better?
3. Tighten entry criteria to be more selective
4. Consider disabling PRO MODE temporarily

### Reserve Always Below Minimum

**Issue**: Free balance consistently below reserve

**Solutions:**
1. Bot has too many open positions
2. Increase reserve percentage
3. Reduce MAX_CONCURRENT_POSITIONS
4. Fund account with more capital

### Positions Not Rotating

**Issue**: PRO MODE enabled but no rotations happening

**Check:**
1. Are position sizes larger than free balance?
2. Do positions have low rotation scores (all profitable)?
3. Is minimum improvement threshold (20%) met?
4. Check logs for rotation decision details

## Advanced Configuration

### Custom Rotation Scoring

To customize rotation logic, edit `bot/rotation_manager.py`:

```python
def score_position_for_rotation(self, position, position_metrics):
    # Adjust weights for your strategy
    # Higher score = more likely to close
    
    # Example: Prioritize age over P&L
    if age_hours > 6:
        score += 40  # Increased from 15
    if pnl_pct < -2.0:
        score += 15  # Decreased from 20
```

### Integration with Risk Manager

PRO MODE integrates with existing risk management:

```python
# In risk_manager.py
AdaptiveRiskManager(
    min_position_pct=0.02,
    max_position_pct=0.05,
    max_total_exposure=0.80,
    pro_mode=True,  # Enable PRO MODE
    min_free_reserve_pct=0.15
)
```

## Performance Tips

1. **Start Conservative**: Use 20% reserve initially
2. **Monitor Closely**: Watch first week of PRO MODE operation
3. **Track Metrics**: Log rotation success rate
4. **Adjust Gradually**: Fine-tune reserve % based on results
5. **Backtest First**: Test on paper trading before live

## Version History

- **v1.0** (Current) - Initial PRO MODE release
  - Total capital calculation
  - Position rotation scoring
  - Automatic weak position closing
  - Minimum reserve protection

## Support

For questions or issues:
1. Check logs for PRO MODE messages
2. Review rotation statistics
3. Verify configuration in .env
4. Test with small capital first

---

**Remember**: PRO MODE is an advanced feature. Start with standard mode to learn the basics, then graduate to PRO MODE when comfortable with position rotation concepts.
