# NIJA PLATFORM_ONLY Mode Guide
## A+ Setups Only - Focus on BTC, ETH, SOL

**Version:** 1.0  
**Last Updated:** January 30, 2026  
**Author:** NIJA Trading Systems

---

## Overview

PLATFORM_ONLY mode is designed for traders who want to:

- ✅ **Trade independently** (no copy trading)
- ✅ **Focus on top-tier cryptocurrencies** (BTC, ETH, SOL only)
- ✅ **Use strict A+ setup criteria** (minimum entry score 8/10)
- ✅ **Maintain conservative risk** (3-5% per trade)
- ✅ **Work with small accounts** (starting from $74)
- ✅ **Ignore low-liquidity altcoins** (quality over quantity)

This mode is perfect for traders who want maximum control and focus on the most reliable cryptocurrency markets.

---

## Quick Start

### 1. Copy Configuration File

```bash
# Copy the PLATFORM_ONLY preset to your .env file
cp .env.platform_only .env
```

### 2. Add Your API Credentials

Edit `.env` and add your exchange API credentials:

**For Coinbase:**
```bash
COINBASE_API_KEY=organizations/your-org-id/apiKeys/your-api-key-id
COINBASE_API_SECRET="-----BEGIN EC PRIVATE KEY-----
YOUR_PRIVATE_KEY_HERE
-----END EC PRIVATE KEY-----"
```

**For Kraken:**
```bash
KRAKEN_PLATFORM_API_KEY=your-api-key
KRAKEN_PLATFORM_API_SECRET=your-api-secret
```

### 3. Enable Live Trading

⚠️ **IMPORTANT:** Only enable after you understand the risks!

```bash
# In your .env file:
LIVE_CAPITAL_VERIFIED=true
```

### 4. Start Trading

```bash
./start.sh
```

---

## Configuration Details

### Trading Mode

```bash
COPY_TRADING_MODE=INDEPENDENT  # No copy trading
PRO_MODE=true                   # Position rotation enabled
```

- **INDEPENDENT**: Trade only with your own account
- **No copy trading**: You make all the decisions
- **PRO_MODE**: Enables smart position rotation for capital efficiency

### Position Management

```bash
MAX_CONCURRENT_POSITIONS=2  # Maximum 2 positions at once
MIN_CASH_TO_BUY=5.00        # Minimum $5 per trade
LEVERAGE_ENABLED=false      # No leverage
```

- **2 positions max**: Focus on quality, not quantity
- **$5 minimum**: Balances profitability with small account sizes
- **No leverage**: Conservative risk management

### Symbol Whitelist

```bash
ENABLE_SYMBOL_WHITELIST=true
```

Only these symbols will be traded:

1. **BTC-USD** (Bitcoin)
   - Highest liquidity
   - Most reliable price action
   - King of crypto

2. **ETH-USD** (Ethereum)
   - Smart contract platform leader
   - Strong market structure
   - Second largest by market cap

3. **SOL-USD** (Solana)
   - High-performance blockchain
   - Growing ecosystem
   - Good volatility for trading

**All other altcoins are blocked** - this prevents trading low-liquidity pairs that can hurt profitability.

### Risk Management

```bash
MIN_TRADE_PERCENT=0.03   # 3% minimum risk per trade
MAX_TRADE_PERCENT=0.05   # 5% maximum risk per trade
DEFAULT_TRADE_PERCENT=0.04  # 4% default (midpoint)
```

#### Risk Per Trade: 3-5%

For a **$74 account**:
- Minimum trade: $2.22 (3%)
- Maximum trade: $3.70 (5%)
- Default trade: $2.96 (4%)

For a **$100 account**:
- Minimum trade: $3.00 (3%)
- Maximum trade: $5.00 (5%)
- Default trade: $4.00 (4%)

For a **$250 account**:
- Minimum trade: $7.50 (3%)
- Maximum trade: $12.50 (5%)
- Default trade: $10.00 (4%)

#### Account-Level Limits

```bash
MAX_DAILY_LOSS_PERCENT=0.10   # 10% max daily loss
MAX_TOTAL_EXPOSURE=0.35       # 35% max total exposure
```

- **Daily loss limit**: Trading stops if you lose 10% in one day
- **Total exposure**: Never risk more than 35% of capital at once

---

## A+ Setup Criteria

This configuration only trades **A+ setups** - the highest quality trading opportunities.

### Minimum Entry Score: 8/10

Each potential trade is scored from 0-10. Only trades scoring **8 or higher** are executed.

### Technical Requirements

#### 1. Strong Trend
- **ADX > 25**: Must have a strong directional trend
- **No choppy markets**: Avoids ranging/sideways conditions

#### 2. Volume Confirmation
- **Volume ≥ 100% of average**: Must have sufficient participation
- Filters out low-volume false signals

#### 3. Volatility Check
- **ATR 1.5% - 10%**: Enough movement to profit, not too volatile
- Avoids both dead markets and chaotic conditions

#### 4. RSI Alignment (Dual RSI Strategy)
- **RSI_9 < 30**: Short-term oversold
- **RSI_14 < 35**: Medium-term oversold
- Both must align for entry

#### 5. Clean Chart Structure
- No conflicting signals
- Clear trend direction
- Proper support/resistance levels

### Exit Strategy

#### Profit Targets
1. **Quick profit**: 2% (take partial profits)
2. **Standard target**: 5% (main exit)
3. **Extended target**: 10% (let winners run)

#### Stop Losses
1. **Initial stop**: 2.5% (protect capital)
2. **Trailing stop**: 1.5% (lock in profits)

#### Time-Based Exits
- **Maximum hold**: 48 hours (avoid dead positions)
- **Minimum hold**: 15 minutes (avoid chop)

---

## Growth Path

Your capital growth milestones:

### Starting Point: $74

This is the absolute minimum to start trading profitably with the $5 minimum trade size.

### Milestone 1: $100 (+35%)
**Profit Needed:** $26  
**Strategy:**
- 7-10 successful trades at 4% risk each
- Focus on high-quality BTC/ETH setups
- Be patient - quality over quantity

### Milestone 2: $150 (+50%)
**Profit Needed:** $50 (from $100)  
**Strategy:**
- 13-17 successful trades
- Can increase position sizes slightly
- Begin trading all 3 symbols (BTC, ETH, SOL)

### Milestone 3: $250 (+67%)
**Profit Needed:** $100 (from $150)  
**Strategy:**
- 25-30 successful trades
- Full 2-position rotation
- Can handle more aggressive entries

### Milestone 4: $500 (+100%)
**Profit Needed:** $250 (from $250)  
**Strategy:**
- 50-60 successful trades
- Professional-level capital management
- Ready to scale to higher tiers

### Time Estimates

**Conservative (50% win rate, 2:1 R:R):**
- $74 → $100: 2-4 weeks
- $100 → $150: 4-6 weeks
- $150 → $250: 6-8 weeks
- $250 → $500: 8-12 weeks

**Total:** 5-7 months to reach $500

**Aggressive (60% win rate, 2:1 R:R):**
- $74 → $100: 1-2 weeks
- $100 → $150: 2-3 weeks
- $150 → $250: 3-4 weeks
- $250 → $500: 4-6 weeks

**Total:** 2.5-4 months to reach $500

---

## Why Only BTC, ETH, SOL?

### Liquidity
- Deep order books
- Tight spreads
- Easy entry/exit at any time

### Reliability
- Established track records
- Not prone to sudden delistings
- Strong community support

### Price Action
- Clear trends
- Predictable patterns
- Good for technical analysis

### Volume
- Sufficient trading activity
- Accurate indicator readings
- Real market moves (not manipulated)

### Low Risk of Scams
- Blue-chip cryptocurrencies
- Not pump-and-dump schemes
- Regulatory clarity

**Avoiding low-cap altcoins prevents:**
- ❌ Liquidity traps
- ❌ Pump and dump schemes
- ❌ Wide spreads eating profits
- ❌ Sudden delistings
- ❌ Manipulation

---

## What Is an "A+ Setup"?

An A+ setup is a trade that meets **all** of these criteria:

1. ✅ **Strong trend** (ADX > 25)
2. ✅ **High volume** (≥ 100% average)
3. ✅ **Clean chart** (no chop/range)
4. ✅ **RSI alignment** (both RSI_9 and RSI_14 oversold)
5. ✅ **Good volatility** (ATR 1.5%-10%)
6. ✅ **Entry score ≥ 8/10**

### Example A+ Setup: BTC-USD

```
✅ ADX: 32 (strong uptrend)
✅ Volume: 120% of average
✅ Clean chart: Clear higher lows
✅ RSI_9: 28 (oversold)
✅ RSI_14: 33 (oversold)
✅ ATR: 2.3% (good movement)
✅ Entry Score: 9/10

→ ENTRY TRIGGERED
```

### Example Non-A+ Setup: ETH-USD

```
❌ ADX: 18 (weak trend)
❌ Volume: 65% of average (low)
❌ Chart: Choppy/ranging
✅ RSI_9: 29 (oversold)
✅ RSI_14: 34 (oversold)
✅ ATR: 1.8% (acceptable)
❌ Entry Score: 5/10

→ ENTRY SKIPPED (not A+ quality)
```

---

## Risk Management Best Practices

### Never Risk More Than You Can Afford to Lose

- Start with money you can afford to lose entirely
- Don't use rent money, bill money, or emergency funds
- Crypto trading is high-risk

### Follow the Limits

- ✅ **3-5% per trade**: Don't increase this
- ✅ **2 positions max**: Quality over quantity
- ✅ **10% daily loss**: Stop trading if hit
- ✅ **35% total exposure**: Never go all-in

### Take Breaks After Losses

- Lost 2 trades in a row? Take a break
- Hit daily loss limit? Stop for the day
- Feeling emotional? Don't trade

### Celebrate Wins Properly

- Don't increase risk after wins
- Don't revenge trade after losses
- Stay disciplined always

---

## Common Questions

### Q: Why only 2 positions?

**A:** With a small account, focus beats diversification. Two high-quality A+ setups will outperform five mediocre trades. Plus, it's easier to manage and monitor.

### Q: Why not trade more altcoins?

**A:** Most altcoins have:
- Low liquidity (hard to exit)
- Wide spreads (eat profits)
- High manipulation risk
- Pump and dump schemes

BTC, ETH, and SOL have none of these issues.

### Q: Can I use leverage?

**A:** **NO.** This configuration explicitly disables leverage. For small accounts, leverage is extremely dangerous and can wipe out your capital quickly.

### Q: What if I want to copy trade?

**A:** This is PLATFORM_ONLY mode (independent trading). If you want copy trading, use a different configuration preset (see `COPY_TRADING_SETUP.md`).

### Q: Why 3-5% risk per trade?

**A:** For small accounts ($74-$500), this provides:
- Meaningful profits when you win
- Acceptable losses when you lose
- Fast capital growth
- Still conservative enough to avoid blowups

Lower risk (1-2%) is too slow for small accounts. Higher risk (10%+) is too dangerous.

### Q: How long to reach each milestone?

**A:** It depends on:
- Win rate (aim for 50%+)
- Risk:reward ratio (aim for 2:1+)
- Number of trades per week
- Market conditions

**Realistic timeline:** 5-7 months from $74 to $500 with consistent trading.

### Q: What if I don't have $74?

**A:** Unfortunately, $74 is the practical minimum for profitable trading with:
- $5 minimum trades
- Exchange minimums
- Fee considerations

Below $74, fees eat too much profit. Consider saving more first.

---

## Monitoring Your Progress

### Daily Checklist

- [ ] Check account balance
- [ ] Review open positions
- [ ] Check if approaching daily loss limit
- [ ] Review filled trades
- [ ] Note lessons learned

### Weekly Review

- [ ] Calculate win rate
- [ ] Calculate average profit/loss
- [ ] Track progress toward next milestone
- [ ] Review trade journal
- [ ] Adjust if needed

### Monthly Review

- [ ] Calculate monthly return
- [ ] Compare to growth path
- [ ] Review all trades
- [ ] Identify patterns
- [ ] Celebrate progress!

---

## Safety Tips

### 🔐 Security

- Never share your API keys
- Use API keys with minimal permissions
- Enable 2FA on exchange accounts
- Use strong, unique passwords

### ⚠️ Risk Warnings

- Cryptocurrency trading is extremely risky
- You can lose all your capital
- Past performance ≠ future results
- No strategy wins 100% of the time
- Start small, learn first

### 🛡️ Protection

- Use stop losses always
- Never turn off safety features
- Don't override risk limits
- Take breaks when losing
- Don't trade when emotional

---

## Troubleshooting

### "No trades executing"

**Check:**
1. Is `LIVE_CAPITAL_VERIFIED=true`?
2. Is `ENABLE_SYMBOL_WHITELIST=true`?
3. Are you monitoring BTC, ETH, or SOL?
4. Is MIN_ENTRY_SCORE set correctly (8)?
5. Check logs for entry score reasons

### "Trades too small"

**Check:**
1. Account balance ≥ $74?
2. MIN_CASH_TO_BUY = 5.00?
3. MIN_TRADE_PERCENT = 0.03?

Increase account balance if needed.

### "Position cap reached"

**This is normal!** MAX_CONCURRENT_POSITIONS=2 means only 2 positions at once. Wait for a position to close before entering new trades.

### "Symbol not whitelisted"

**This is correct!** Only BTC-USD, ETH-USD, SOL-USD are allowed. All other symbols are intentionally blocked.

---

## Advanced Tips

### Optimize for Your Schedule

- **Part-time traders**: Use longer timeframes (1H charts)
- **Full-time traders**: Use 5m-15m charts
- **Night traders**: Trade Asian/European sessions

### Scale Up Gradually

Don't jump from $74 to huge positions. Follow the growth path:
1. Master $74-$100 first
2. Then $100-$150
3. Then $150-$250
4. Finally $250-$500

Each milestone teaches new lessons.

### Learn From Every Trade

- Keep a trade journal
- Note why you entered
- Record your emotions
- Review wins AND losses

### Stay Disciplined

- Follow the rules
- Don't chase trades
- Wait for A+ setups
- Be patient

---

## Support and Resources

### Documentation
- `RISK_PROFILES_GUIDE.md` - Risk management details
- `GETTING_STARTED.md` - Initial setup
- `BROKER_INTEGRATION_GUIDE.md` - Exchange setup
- `TRADINGVIEW_SETUP.md` - TradingView integration

### Configuration Files
- `.env.platform_only` - Configuration template
- `bot/platform_only_config.py` - Python configuration
- `bot/apex_config.py` - Strategy parameters

### Community
- GitHub Issues - Report bugs
- GitHub Discussions - Ask questions
- README.md - General information

---

## Conclusion

PLATFORM_ONLY mode is designed for traders who want:
- **Independence**: No copy trading
- **Focus**: Only BTC, ETH, SOL
- **Quality**: A+ setups only
- **Conservative risk**: 3-5% per trade
- **Growth**: $74 → $500 path

Follow the rules, stay disciplined, and you'll reach your milestones.

**Remember:**
- Quality > Quantity
- Patience > Emotion
- Discipline > Hope

Happy trading! 🚀

---

**Version:** 1.0  
**Last Updated:** January 30, 2026  
**Author:** NIJA Trading Systems
