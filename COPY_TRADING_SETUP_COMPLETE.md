# NIJA Pro Mode & Copy Trading - Complete Setup

## ✅ What Has Been Implemented

### 1. Copy Trading Platform (Complete)
NIJA is now a **true copy trading platform** with the following features:

#### XRP Protection ✅
- **All XRP variants permanently blacklisted**
  - XRP-USD, XRPUSD, XRP-USDT, XRPUSDT
  - Applied across all brokers
  - Net-negative performance protection

#### Kraken Copy-Only Mode ✅
- **Kraken users skip independent trading when master is active**
  - No conflicting signals
  - Users only execute trades copied from master
  - Master-first architecture enforced
  - Implemented in: `bot/independent_broker_trader.py` lines 778-790

#### on_master_trade Hook ✅
- **Clean copy execution interface**
  ```python
  def on_master_trade(trade):
      for user in kraken_users:
          scaled_size = trade.size * (user.balance / master.balance)
          user.execute(trade.symbol, trade.side, scaled_size)
  ```
  - Integrated in: `bot/broker_manager.py`
  - Called after every master trade
  - Balance-based scaling
  - 10% max risk per user per trade

### 2. PRO MODE Configuration (Complete)
PRO MODE has been **enabled** with the following settings:

#### Configuration
```bash
PRO_MODE=true
PRO_MODE_MIN_RESERVE_PCT=0.15  # 15% free balance reserve
LIVE_TRADING=1
```

#### What PRO MODE Does
- ✅ **Counts position values as available capital**
  - Total Capital = Free Balance + Position Values
  - Example: $10 free + $90 in positions = $100 total capital

- ✅ **Enables position rotation**
  - Can close weak positions to fund better opportunities
  - Automatic rotation for trades needing more capital
  - Never starves by having all capital locked

- ✅ **Maintains free balance reserve**
  - Always keeps 15% of total capital as free USD
  - Example: $100 total → minimum $15 free
  - Ensures liquidity for volatility

- ✅ **Maximum capital efficiency**
  - Uses total capital for position sizing
  - Hedge-fund style trading
  - Intelligent rotation decisions

## 🎯 Trading Behavior

### Master Accounts (Nija System)
```
✅ Coinbase Master: Trades independently with PRO MODE
✅ Kraken Master: Trades independently + emits copy signals
```

### User Accounts
```
✅ Kraken Users: Copy master trades ONLY
   • Receive scaled trades from master
   • Position size = master_size * (user_balance / master_balance)
   • Same symbol, same side, same exit logic
   • No independent trading loops
```

### Copy Trading Flow
```
1. MASTER places trade on Kraken
   ↓
2. Trade executed successfully
   ↓
3. on_master_trade(trade) hook called
   ↓
4. For each Kraken user:
   a. Fetch current balance
   b. Calculate: scaled_size = trade.size * (user.balance / master.balance)
   c. Apply 10% max risk limit
   d. Execute same trade on user account
   ↓
5. All users mirror master position (scaled)
```

## 📋 Setup Checklist

### ✅ Completed
- [x] XRP blacklist enforced (all variants)
- [x] Kraken copy-only mode implemented
- [x] on_master_trade hook created and integrated
- [x] PRO MODE enabled in .env
- [x] Live trading enabled
- [x] Configuration files updated
- [x] Test suite created and passing (5/5 tests)

### ⚠️ Required Before Trading
- [ ] **Add Coinbase Master credentials**
  ```bash
  COINBASE_API_KEY=organizations/.../apiKeys/...
  COINBASE_API_SECRET="-----BEGIN EC PRIVATE KEY-----..."
  ```

- [ ] **Add Kraken Master credentials**
  ```bash
  KRAKEN_MASTER_API_KEY=your-kraken-master-key
  KRAKEN_MASTER_API_SECRET=your-kraken-master-secret
  ```

- [ ] **Add Kraken User credentials** (for each user)
  ```bash
  # Example for user "john_smith"
  KRAKEN_USER_JOHN_API_KEY=user-kraken-key
  KRAKEN_USER_JOHN_API_SECRET=user-kraken-secret
  ```

- [ ] **Configure user accounts** in JSON files
  - Edit: `config/users/retail_kraken.json`
  - Add user entries with enabled: true

- [ ] **Restart the bot**
  ```bash
  python bot.py
  # or
  ./start.sh
  ```

## 🚀 How to Start Trading

### Step 1: Add Credentials

#### Get Coinbase Credentials
1. Visit: https://portal.cdp.coinbase.com/
2. Create Cloud API Key
3. Copy key ID and private key (PEM format)
4. Add to .env:
   ```bash
   COINBASE_API_KEY=organizations/.../apiKeys/...
   COINBASE_API_SECRET="-----BEGIN EC PRIVATE KEY-----..."
   ```

#### Get Kraken Master Credentials
1. Visit: https://www.kraken.com/u/security/api
2. Generate New Key (Classic API Key)
3. Enable permissions:
   - Query Funds ✅
   - Query Orders ✅
   - Create/Modify Orders ✅
   - Cancel Orders ✅
4. Add to .env:
   ```bash
   KRAKEN_MASTER_API_KEY=your-key
   KRAKEN_MASTER_API_SECRET=your-secret
   ```

#### Get Kraken User Credentials
For each user (e.g., "john_smith"):
1. Same process as master
2. Add to .env with user prefix:
   ```bash
   KRAKEN_USER_JOHN_API_KEY=user-key
   KRAKEN_USER_JOHN_API_SECRET=user-secret
   ```

### Step 2: Configure Users
Edit `config/users/retail_kraken.json`:
```json
[
  {
    "user_id": "john_smith",
    "name": "John Smith",
    "broker_type": "kraken",
    "enabled": true
  }
]
```

### Step 3: Start Bot
```bash
python bot.py
```

### Step 4: Verify in Logs
Look for these messages:
```
🔄 PRO MODE ACTIVATED - Position Rotation Enabled
✅ KRAKEN COPY TRADING SYSTEM READY
   🔷 MASTER: Initialized and connected
   👥 USERS: 2 ready for copy trading
✅ COPY TRADING ACTIVE
```

## 📊 Monitoring

### PRO MODE Status
```
💰 PRO MODE Capital:
   Free balance: $15.00
   Position value: $85.00
   Total capital: $100.00
   Reserve: 15% (maintaining $15 minimum free)
```

### Copy Trading Status
```
🔔 RECEIVED MASTER TRADE SIGNAL
   Symbol: BTC-USD
   Side: BUY
   Size: $50.00 (USD)

🔄 COPY TRADING TO 2 USERS
   ✅ john_smith: $25.00 (scaled by balance ratio)
   ✅ jane_doe: $12.50 (scaled by balance ratio)
```

## 🔒 Security

### Implemented Protections
- ✅ API keys never logged
- ✅ Balance validation before trades
- ✅ 10% max risk per user per trade
- ✅ Master offline = copy trading disabled (safe)
- ✅ User account isolation
- ✅ Graceful error handling

### Best Practices
1. **Use API keys with minimal permissions**
   - No withdrawal permissions
   - Trading and query only

2. **Start with small balances**
   - Test with $50-100 first
   - Verify copy trading works
   - Scale up gradually

3. **Monitor daily**
   - Check logs regularly
   - Verify copy execution
   - Track P&L per account

## 🧪 Testing

### Run Test Suite
```bash
python test_copy_trading_implementation.py
```

Expected output:
```
✅ PASS: XRP Blacklist
✅ PASS: on_master_trade Hook
✅ PASS: Broker Manager Integration
✅ PASS: Kraken Copy-Only Mode
✅ PASS: Module Exports
Results: 5/5 tests passed
```

### Manual Testing
1. **Test XRP blocked:**
   - Check logs for "XRP" - should not trade
   
2. **Test copy trading:**
   - Master places trade
   - Check user accounts for matching trades
   
3. **Test PRO MODE:**
   - Fill account to 100% positions
   - New signal should rotate positions

## 📁 Files Modified/Created

### Core Implementation
1. `bot/apex_config.py` - XRP blacklist
2. `bot/trading_strategy.py` - XRP filtering  
3. `bot/kraken_copy_trading.py` - on_master_trade hook
4. `bot/broker_manager.py` - Hook integration
5. `bot/independent_broker_trader.py` - Copy-only mode (existing)

### Configuration
6. `.env` - PRO MODE enabled
7. `enable_pro_mode_trading.py` - Setup script

### Testing
8. `test_copy_trading_implementation.py` - Test suite

### Documentation
9. `COPY_TRADING_SETUP_COMPLETE.md` - This file

## ❓ FAQ

### Q: How do I disable PRO MODE?
A: Set `PRO_MODE=false` in .env and restart

### Q: Can users trade independently?
A: No, Kraken users only copy master. Other brokers can trade independently.

### Q: What if master goes offline?
A: Copy trading stops. Users don't trade until master reconnects.

### Q: Can I adjust position scaling?
A: Yes, it's automatic based on balance ratio. No manual config needed.

### Q: What's the max risk per trade?
A: 10% of user balance per trade (hardcoded safety limit)

### Q: Can I use different brokers for users?
A: Currently only Kraken supports copy trading. Coinbase is master-only.

## 🎓 Next Steps

### Immediate (Before Trading)
1. ✅ Add credentials to .env
2. ✅ Configure users in JSON
3. ✅ Restart bot
4. ✅ Verify logs show correct setup

### Short Term (First Week)
1. Monitor copy trading execution
2. Track PRO MODE rotation frequency
3. Verify position scaling is correct
4. Check P&L on all accounts

### Long Term (Optional)
1. Add more users
2. Configure per-user risk limits
3. Add copy trading metrics dashboard
4. Implement selective symbol copying

## ✅ Summary

**NIJA is now configured as a PRO MODE copy trading platform:**

- ✅ XRP permanently disabled
- ✅ Master trades on Coinbase + Kraken
- ✅ Users copy Kraken master trades
- ✅ PRO MODE for capital efficiency
- ✅ on_master_trade hook for clean execution
- ✅ 10% max risk per user per trade
- ✅ All tests passing

**Status: Ready to trade once credentials are added! 🚀**
