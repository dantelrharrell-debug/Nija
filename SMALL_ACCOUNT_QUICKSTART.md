# NIJA Safe Small-Account Preset - Quick Start Guide

## 🎯 Overview

The NIJA Safe Small-Account Preset is a **turnkey configuration** designed specifically for accounts between **$20-$100**. This preset provides:

✅ **Full copy trading support** - Mirror master account trades automatically  
✅ **Minimal API risk** - Conservative position sizing and strict limits  
✅ **Controlled drawdown** - Multiple circuit breakers and safety features  
✅ **Fee optimization** - Trades on lowest-fee exchanges (Kraken recommended)  
✅ **Beginner-friendly** - Works out of the box with minimal configuration  

---

## 📋 Quick Start (5 Minutes)

### Step 1: Get Your API Credentials

**Kraken (Recommended for $20-$100 accounts)**
1. Go to [Kraken API Settings](https://www.kraken.com/u/security/api)
2. Click "Generate New Key"
3. Enable permissions:
   - ✅ Query Funds
   - ✅ Query Open Orders & Trades
   - ✅ Query Closed Orders & Trades
   - ✅ Create & Modify Orders
   - ✅ Cancel/Close Orders
   - ❌ **DO NOT** enable "Withdraw Funds"
4. Copy your API Key and Private Key

### Step 2: Configure Your Environment

1. Copy the preset file to `.env`:
   ```bash
   cp .env.small_account_preset .env
   ```

2. Edit `.env` and add your credentials:
   ```bash
   nano .env  # or use any text editor
   ```

3. Add your Kraken credentials:
   ```env
   KRAKEN_MASTER_API_KEY=your-api-key-here
   KRAKEN_MASTER_API_SECRET=your-private-key-here
   ```

4. Save and close the file

### Step 3: Start Trading

```bash
# Start the bot
./start.sh

# Or if using Docker
docker-compose up -d
```

**That's it!** The bot will now trade using the safe small-account preset.

---

## 🛡️ Safety Features (Always Active)

### Automatic Protection
- ✅ **Emergency Stop**: Trading halts if balance drops below $15
- ✅ **Daily Loss Limit**: Stops trading after 2% daily loss
- ✅ **Consecutive Loss Protection**: Pauses after 3 losses in a row
- ✅ **Position Limits**: Maximum 2 concurrent positions
- ✅ **Required Stop-Loss**: Every trade has a hard stop-loss
- ✅ **Drawdown Protection**: Stops trading at 8% account drawdown

### Burn-Down Mode
If you hit 2 consecutive losses:
- Position sizes automatically reduce to 2% (from 3-5%)
- System requires 2 wins to return to normal sizing
- Helps prevent larger losses during unfavorable conditions

---

## 💰 Position Sizing (Auto-Scaled)

Your position sizes automatically adjust based on your balance:

| Account Balance | Position Size | Example Trade Value |
|----------------|---------------|---------------------|
| $20 - $30      | 2%            | $0.40 - $0.60       |
| $30 - $50      | 3%            | $0.90 - $1.50       |
| $50 - $75      | 4%            | $2.00 - $3.00       |
| $75 - $100     | 5%            | $3.75 - $5.00       |

**Minimum**: $5.00 per trade (for fee efficiency)  
**Maximum**: $10.00 per trade (risk protection)

---

## 🎯 Profit Targets & Stop-Loss

### Take-Profit Ladder
- **TP1**: +1.5% profit → Close 50% of position, move stop to breakeven
- **TP2**: +2.5% profit → Close 30% more (80% total), activate trailing stop
- **TP3**: +4.0% profit → Close remaining 20%, full exit

### Stop-Loss Protection
- **Default Stop**: 0.5% loss
- **Range**: 0.3% - 0.7%
- **Trailing**: Activates at +0.8% profit, trails at 0.3%
- **Breakeven**: Moves to breakeven (+0.1%) at +0.8% profit

---

## 📊 Trading Frequency

- **Max Trades per Day**: 8 trades
- **Max Trades per Hour**: 3 trades
- **Min Time Between Trades**: 5 minutes
- **Scan Interval**: Every 5 minutes

This prevents over-trading and keeps fees manageable.

---

## 🏦 Exchange Recommendations

### ✅ Kraken (RECOMMENDED)
- **Fees**: 0.26% taker, 0.16% maker
- **Total Round-Trip**: ~0.67%
- **Best For**: $20-$100 accounts
- **Why**: Low fees, reliable, good for small positions

### ⚠️ Coinbase (NOT RECOMMENDED)
- **Fees**: 0.6% taker, 0.4% maker
- **Total Round-Trip**: ~1.4%
- **Best For**: Accounts over $100
- **Why**: High fees eat into small account profits

### ✅ OKX (ALTERNATIVE)
- **Fees**: 0.10% taker, 0.08% maker
- **Total Round-Trip**: ~0.3%
- **Best For**: $25+ accounts
- **Why**: Lowest fees, but less regulated than Kraken

**Preset Default**: Kraken is used by default. Coinbase is automatically disabled for accounts under $100.

---

## 🔄 Copy Trading Mode

If you have multiple user accounts that should copy the master account:

### Setup User Accounts

1. Create user config file: `config/users/retail_kraken.json`
   ```json
   {
     "users": [
       {
         "user_id": "jane_smith",
         "allocation_pct": 1.0,
         "max_position_pct": 0.05
       }
     ]
   }
   ```

2. Add user credentials to `.env`:
   ```env
   KRAKEN_USER_JANE_API_KEY=user-api-key
   KRAKEN_USER_JANE_API_SECRET=user-private-key
   ```

3. Restart the bot

**Automatic Scaling**: User positions are automatically scaled based on the ratio of user balance to master balance.

**Example**:
- Master account: $100 balance, opens $5 position (5%)
- User account: $50 balance, opens $2.50 position (5%)

---

## 📈 Trading Pairs

**Allowed Pairs** (Liquid majors only):
- BTC-USD / BTCUSD (Bitcoin)
- ETH-USD / ETHUSD (Ethereum)
- SOL-USD / SOLUSD (Solana)

**Blacklisted Pairs**:
- XRP-USD (High spread, low profit potential for small accounts)

---

## 📊 Expected Performance

### Conservative Estimates (Past performance ≠ future results)

**Daily Target**: Not applicable for small accounts. Focus on consistency.

**Risk Profile**:
- Max Risk per Trade: 0.5%
- Max Daily Loss: 2%
- Max Weekly Loss: 4%
- Max Drawdown: 8%

**Win Rate Goal**: 50-60% (with proper 2:1 risk/reward)

**Monthly Return Target**: 5-15% (conservative, compounding)

---

## 🔧 Advanced Configuration

If you want to customize beyond the preset defaults, you can:

1. Edit `bot/small_account_preset.py` directly
2. Modify environment variables in `.env`
3. Override specific settings in your startup script

**Common Customizations**:

```env
# Adjust position sizes
MIN_TRADE_PERCENT=0.02  # 2% minimum
MAX_TRADE_PERCENT=0.05  # 5% maximum

# Adjust risk limits
MAX_CONCURRENT_POSITIONS=2  # Max 2 positions

# Adjust balances
MINIMUM_TRADING_BALANCE=20.0  # Min $20 to trade
MIN_CASH_TO_BUY=5.0  # Min $5 per trade
```

---

## 🚨 Troubleshooting

### Bot Won't Start Trading

**Check balances**:
```bash
# View your current balance
grep -A 5 "Balance:" logs/nija.log
```

- Ensure balance > $20
- Ensure free cash > $5
- Check emergency stop hasn't triggered

**Check API credentials**:
- Verify API key format is correct
- Ensure permissions are enabled on Kraken
- Check for typos in `.env` file

### Positions Not Opening

**Common causes**:
- Signal quality too low (requires 5/6 confirmations)
- Daily loss limit hit (2%)
- Consecutive losses (3 in a row)
- Insufficient free cash (<$5)
- Spread too wide (>0.2%)

**Check logs**:
```bash
tail -f logs/nija_apex.log
```

### Trades Losing Money

**First steps**:
1. Check if burn-down mode is active (after 2 losses)
2. Review entry signals (need 5/6 confirmations)
3. Verify stop-loss is properly set
4. Check market conditions (high volatility?)

**Circuit breakers will protect you**:
- Automatic stop at 2% daily loss
- Automatic pause after 3 consecutive losses
- Emergency stop at $15 balance

---

## 📚 Additional Resources

- **Copy Trading Guide**: `COPY_TRADING_SETUP.md`
- **General Setup**: `GETTING_STARTED.md`
- **Strategy Documentation**: `APEX_V71_DOCUMENTATION.md`
- **Risk Management**: `bot/small_account_preset.py`

---

## ⚠️ Important Disclaimers

### Trading Risks
- **Past performance does not guarantee future results**
- **You can lose money trading** - Only trade with funds you can afford to lose
- **This preset reduces but does not eliminate risk**
- **You are responsible for monitoring your account**

### Regulatory Compliance
- Ensure crypto trading is legal in your jurisdiction
- Comply with all tax obligations
- Keep records of all trades for tax purposes

### Liability
- NIJA is provided "as-is" without warranties
- You are responsible for your trading decisions
- Review all code and configurations before live trading
- Start with paper trading or minimal capital to test

---

## 📞 Getting Help

### Self-Service
1. Check logs: `logs/nija.log` and `logs/nija_apex.log`
2. Review documentation in repository
3. Verify API credentials and permissions
4. Check balance and position limits

### Common Issues
- **"Insufficient balance"**: Ensure balance > $20
- **"API key invalid"**: Check credentials in `.env`
- **"No trades executing"**: Check signal quality requirements
- **"Too many losses"**: Circuit breaker activated (automatic protection)

### Still Need Help?
- Review the issue tracker on GitHub
- Check the community discussions
- Ensure you're using the latest version

---

## ✅ Success Checklist

Before you start:
- [ ] API credentials added to `.env`
- [ ] Account balance confirmed > $20
- [ ] Trading pairs configured (BTC, ETH, SOL)
- [ ] Copy trading mode enabled (if using multiple accounts)
- [ ] Reviewed all safety limits
- [ ] Understood profit targets and stop-loss
- [ ] Read all disclaimers and warnings
- [ ] Ready to monitor first few trades

**You're ready to trade safely with NIJA!** 🚀

---

## 💡 Pro Tips

1. **Start Small**: Begin with $50-75 to have room for 2 positions
2. **Monitor Closely**: Watch your first 5-10 trades carefully
3. **Trust the System**: Let stop-losses and circuit breakers protect you
4. **Be Patient**: Don't override safety limits manually
5. **Compound Slowly**: Withdraw profits regularly, don't over-leverage
6. **Use Kraken**: Lowest fees for small accounts
7. **Review Daily**: Check your P&L and adjust if needed

---

**Last Updated**: January 20, 2026  
**Version**: 1.0  
**Preset File**: `bot/small_account_preset.py`  
**Environment File**: `.env.small_account_preset`
