# NIJA PRO MODE - Quick Start Guide

## What is PRO MODE?

PRO MODE transforms NIJA into a hedge-fund style trading bot that:
- ✅ Counts open position values as available capital
- ✅ Can close weak positions to fund better opportunities  
- ✅ Never locks all capital in positions (maintains reserve)
- ✅ Maximizes capital efficiency through intelligent rotation

## Quick Enable (5 minutes)

### Step 1: Enable in Configuration

Edit your `.env` file and add:

```bash
# Enable PRO MODE
PRO_MODE=true

# Set minimum free balance reserve (15% recommended)
PRO_MODE_MIN_RESERVE_PCT=0.15
```

### Step 2: Restart Bot

```bash
# Stop current instance
# Then restart with:
python main.py
# or
./start.sh
```

### Step 3: Verify Activation

Look for this in the logs:

```
======================================================================
🔄 PRO MODE ACTIVATED - Position Rotation Enabled
   Min free balance reserve: 15%
   Position values count as capital
   Can rotate positions for better opportunities
======================================================================
```

### Step 4: Monitor Operation

Watch for PRO MODE messages:

```
💰 PRO MODE Capital:
   Free balance: $10.00
   Position value: $90.00
   Total capital: $100.00
   Positions: 3
```

## Example: PRO MODE in Action

**Before PRO MODE:**
```
Account: $100
Free: $5
Positions: $95 (locked in 3 trades)
New Signal: XRP needs $15
Result: ❌ Cannot trade (only $5 free)
```

**With PRO MODE:**
```
Account: $100  
Free: $5
Positions: $95
New Signal: XRP needs $15

PRO MODE Action:
1. Identifies SOL position losing -3%
2. Closes SOL ($20 freed)
3. Opens XRP position ($15)
4. Maintains $10 reserve (10%)

Result: ✅ Traded successfully, rotated from loser to better opportunity
```

## Configuration Options

| Setting | Default | Description |
|---------|---------|-------------|
| `PRO_MODE` | false | Enable/disable PRO MODE |
| `PRO_MODE_MIN_RESERVE_PCT` | 0.15 | Minimum free balance % (15%) |

### Reserve Percentage Guide

- **10%** - Aggressive (maximum utilization)
- **15%** - Balanced (recommended)
- **20%** - Conservative (more safety)
- **25%** - Very Conservative (minimal rotation)

## How It Works

### 1. Capital Calculation
```
Total Capital = Free USD + Position Values
```

### 2. Position Rotation
When new opportunity requires more capital than free balance:
1. Score all positions (0-100)
2. Close worst performers
3. Free up capital
4. Open new position

### 3. Rotation Scoring
Higher score = More likely to close:
- Big loser (< -5%): +30 points
- Stale position (> 8h): +15 points  
- Overbought (RSI > 70): +15 points
- Small size (< $5): +10 points

### 4. Reserve Protection
Always maintains minimum free balance:
- Default: 15% of total capital
- Never allows 100% lock-up
- Ensures liquidity for volatility

## Best Practices

### ✅ Do This:
1. Start with 15-20% reserve
2. Monitor first week closely
3. Track rotation success rate
4. Use with $100+ accounts
5. Review logs regularly

### ❌ Avoid This:
1. Don't set reserve below 10%
2. Don't enable with < $50 account
3. Don't ignore rotation frequency
4. Don't disable monitoring
5. Don't use passively

## Troubleshooting

### "PRO MODE not activating"

Check:
```bash
# Verify in .env
PRO_MODE=true

# Not "True" or "TRUE" or "1"
# Must be lowercase "true"
```

### "Too many rotations"

Solutions:
1. Increase reserve to 20-25%
2. Review entry criteria (be more selective)
3. Check if rotations are improving P&L

### "Reserve always low"

Fixes:
1. Reduce MAX_CONCURRENT_POSITIONS
2. Increase reserve percentage
3. Fund account with more capital

## Safety Features

✅ **Built-in Protection:**
- Minimum 15% reserve maintained
- Profitable positions protected
- Only rotates for 20%+ improvement
- Statistics tracked for monitoring

⚠️ **Understand the Risks:**
- Higher trade frequency = more fees
- Potential premature exits
- Increased complexity
- Requires understanding

## Verification Test

Run the test script:

```bash
python3 test_pro_mode.py --skip-broker
```

Expected output:
```
✅ All PRO MODE tests passed!
✅ PRO MODE READY TO USE
```

## Support & Documentation

- **Full Guide**: See `PRO_MODE_README.md`
- **Test Script**: Run `test_pro_mode.py`
- **Configuration**: Check `.env.example`

## Version Info

- **Version**: 1.0 (Initial Release)
- **Status**: Production Ready
- **Tested**: ✅ Core functionality verified

---

**Ready to enable?** Just add `PRO_MODE=true` to your `.env` file and restart! 🚀
