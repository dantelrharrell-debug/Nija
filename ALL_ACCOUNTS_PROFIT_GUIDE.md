# NIJA All Accounts Profit-Taking Guide
## Ensuring Profit-Taking Works on EVERY Account Type

**Version:** 1.0
**Date:** January 22, 2026
**Status:** ✅ COMPREHENSIVE

---

## 🎯 Overview

NIJA **GUARANTEES** profit-taking works on **ALL account types**, in **BOTH directions** (long AND short), across **ALL supported brokerages and tiers**.

### Supported Account Types

1. **Individual Accounts** - Single standalone trading accounts
2. **Master Accounts** - Accounts that generate signals for copy trading
3. **Follower Accounts** - Accounts that copy master account trades
4. **Multi-Account Setups** - Multiple accounts trading independently or via copy trading

---

## 📊 Account Type Breakdown

### 1. Individual Accounts

**Description:** Single standalone accounts trading independently.

**Characteristics:**
- Trades based on NIJA's autonomous strategy
- No connection to other accounts
- Full control over positions and risk
- Works on any supported broker

**Profit-Taking:**
- ✅ Long positions: TP1, TP2, TP3 + stepped exits
- ✅ Short positions: TP1, TP2, TP3 + stepped exits (if broker supports)
- ✅ Fee-aware targets for specific broker
- ✅ All tiers supported (SAVER → BALLER)

**Configuration:**
```bash
# .env file
TRADING_MODE=individual  # Default mode
COINBASE_API_KEY=your_key
COINBASE_API_SECRET=your_secret
# or
KRAKEN_MASTER_API_KEY=your_key
KRAKEN_MASTER_API_SECRET=your_secret
```

**Example:**
```
Individual Account on Coinbase:
- Account ID: user_12345
- Balance: $500
- Tier: INVESTOR
- Long only (Coinbase doesn't support shorts)
- Profit taken at TP1 (1.5% gross, 0.1% net after fees)
```

---

### 2. Master Accounts

**Description:** Accounts that trade and emit signals for followers to copy.

**Characteristics:**
- Primary trading account for copy trading system
- Generates TradeSignal objects for each trade
- Can trade independently even without followers
- Typically larger capital accounts

**Profit-Taking:**
- ✅ Long positions: Full profit-taking enabled
- ✅ Short positions: Full profit-taking enabled (if broker supports)
- ✅ Signals emitted for BOTH entry AND profit-taking exits
- ✅ Works on all brokers with master credentials

**Configuration:**
```bash
# .env file
COPY_TRADING_MODE=MASTER
MASTER_ACCOUNT_ID=master_trader_001

# Master broker credentials
KRAKEN_MASTER_API_KEY=your_master_key
KRAKEN_MASTER_API_SECRET=your_master_secret
```

**Signal Flow:**
```
1. Master detects opportunity → LONG BTC-USD @ $42,000
2. Master executes → Order fills at $42,000
3. Master emits signal → TradeSignal(side="buy", symbol="BTC-USD", ...)
4. Master monitors position → Checks TP levels every cycle
5. Master hits TP1 → Price reaches $42,840 (2% profit)
6. Master takes profit → Sells position
7. Master emits exit signal → TradeSignal(side="sell", symbol="BTC-USD", ...)
```

**Example:**
```
Master Account on Kraken:
- Account ID: master_001
- Balance: $10,000
- Tier: LIVABLE
- Long AND short enabled
- Profit taken at TP2 (3% gross, 2.64% net on Kraken)
- 15 follower accounts copied this profit-taking exit
```

---

### 3. Follower Accounts (Copy Trading)

**Description:** Accounts that automatically copy master account trades.

**Characteristics:**
- Replicates master trades with position sizing scaled to account balance
- Follows BOTH entries AND exits (including profit-taking)
- Can trade independently if master is offline
- Works across different brokers than master

**Profit-Taking:**
- ✅ Copies master's profit-taking exits automatically
- ✅ Position sizing scaled to follower's account balance
- ✅ Can use different broker than master (cross-broker copy trading)
- ✅ Fee-aware scaling based on follower's broker

**Configuration:**
```bash
# .env file
COPY_TRADING_MODE=MASTER_FOLLOW
MASTER_ACCOUNT_ID=master_trader_001

# Follower broker credentials (can be different from master)
COINBASE_API_KEY=your_follower_key
COINBASE_API_SECRET=your_follower_secret
```

**Copy Trading Flow:**
```
Master Account (Kraken):          Follower Account (Coinbase):
---------------------             -------------------------
Entry: $10,000 → BTC-USD          Entry: $500 → BTC-USD
Position: $1,000 (10%)            Position: $50 (10% scaled)
Price: $42,000                    Price: $42,000
TP1: $42,840                      TP1: $42,840

[Price hits TP1]                  [Price hits TP1]

Exit: Sell $1,000 at $42,840      Exit: Sell $50 at $42,840
Gross: +2.0%                      Gross: +2.0%
Fees: -0.36% (Kraken)             Fees: -1.4% (Coinbase)
Net: +1.64% = $16.40 profit       Net: +0.6% = $0.30 profit
```

**Example:**
```
Follower Account:
- Account ID: user_54321
- Balance: $250
- Master: master_001 (Kraken)
- Follower Broker: Coinbase
- Tier: SAVER
- Copied master's TP1 exit successfully
- Profit: $0.30 (net after Coinbase fees)
```

---

### 4. Multi-Account Setups

**Description:** Multiple accounts managed together, can be mix of master/followers/independent.

**Characteristics:**
- Can have multiple masters (one per broker)
- Can have multiple followers per master
- Each account can have different tier/balance
- Accounts can operate independently or in copy mode

**Profit-Taking:**
- ✅ Each account has independent profit-taking logic
- ✅ Master accounts take profit independently
- ✅ Follower accounts copy master's profit-taking
- ✅ Independent accounts use autonomous strategy
- ✅ All accounts monitored simultaneously

**Configuration:**
```bash
# .env file
MULTI_ACCOUNT_MODE=true

# Master Kraken
KRAKEN_MASTER_API_KEY=master_kraken_key
KRAKEN_MASTER_API_SECRET=master_kraken_secret

# Master Coinbase
COINBASE_MASTER_API_KEY=master_coinbase_key
COINBASE_MASTER_API_SECRET=master_coinbase_secret

# User accounts configured via USER_MANAGEMENT.md
```

**Example Setup:**
```
Multi-Account Configuration:
├── Master Kraken ($10,000, LIVABLE tier)
│   ├── Follower 1: user_001 Kraken ($500, INVESTOR)
│   ├── Follower 2: user_002 Kraken ($250, SAVER)
│   └── Follower 3: user_003 Kraken ($1,000, INVESTOR)
│
├── Master Coinbase ($5,000, INCOME tier)
│   ├── Follower 1: user_004 Coinbase ($200, SAVER)
│   └── Follower 2: user_005 Coinbase ($800, INVESTOR)
│
└── Independent OKX ($2,000, INCOME tier)
    └── Trades autonomously, no copy trading
```

---

## 🔄 Profit-Taking Across Account Types

### Matrix: Account Type × Position Type × Broker

| Account Type | Long Profit-Taking | Short Profit-Taking | Broker Support |
|--------------|-------------------|-------------------|----------------|
| **Individual - Coinbase** | ✅ Yes | ❌ No (spot only) | Coinbase spot only |
| **Individual - Kraken** | ✅ Yes | ✅ Yes | Kraken margin |
| **Individual - Binance** | ✅ Yes | ✅ Yes | Binance futures |
| **Individual - OKX** | ✅ Yes | ✅ Yes | OKX margin |
| **Individual - Alpaca** | ✅ Yes | ✅ Yes (stocks) | Alpaca margin |
| **Master - Coinbase** | ✅ Yes | ❌ No | Coinbase spot only |
| **Master - Kraken** | ✅ Yes | ✅ Yes | Kraken margin |
| **Master - Binance** | ✅ Yes | ✅ Yes | Binance futures |
| **Follower - Any** | ✅ Yes | ✅ Yes* | *If follower's broker supports |
| **Multi-Account** | ✅ Yes | ✅ Yes* | *Per account's broker |

---

## 💰 Fee-Aware Profit Targets by Account Type

### Individual Accounts

**Coinbase (Long Only):**
- TP1: 1.5% gross → 0.1% NET
- TP2: 1.2% gross → -0.2% NET (acceptable)
- TP3: 1.0% gross → -0.4% NET (emergency)

**Kraken (Long + Short):**
- TP1: 1.0% gross → 0.64% NET
- TP2: 0.7% gross → 0.34% NET
- TP3: 0.5% gross → 0.14% NET

### Master Accounts

**Same as individual** - master accounts use identical profit targets.

### Follower Accounts

**Scaled to follower's broker fees:**
- If master on Kraken (0.36% fees), follower on Coinbase (1.4% fees)
- Master TP1 at 1.0% → Follower may not be NET profitable
- **Solution:** Followers can override with higher targets

**Configuration for followers:**
```bash
# Override profit targets for follower account
OVERRIDE_PROFIT_TARGETS=true
MIN_PROFIT_TARGET=1.5  # 1.5% minimum for Coinbase follower
```

---

## 🔧 Configuration Examples

### Example 1: Single Individual Account

```bash
# .env
TRADING_TIER=INVESTOR
KRAKEN_MASTER_API_KEY=your_key
KRAKEN_MASTER_API_SECRET=your_secret
LIVE_MODE=true
```

**Result:**
- 1 account trading on Kraken
- Long + Short positions
- Profit-taking at 1.0%, 0.7%, 0.5% (Kraken targets)
- Net profitable after 0.36% fees

### Example 2: Master + 3 Followers

```bash
# .env for Master
COPY_TRADING_MODE=MASTER
MASTER_ACCOUNT_ID=master_001
KRAKEN_MASTER_API_KEY=master_key
KRAKEN_MASTER_API_SECRET=master_secret
TRADING_TIER=LIVABLE

# .env for Follower 1
COPY_TRADING_MODE=MASTER_FOLLOW
MASTER_ACCOUNT_ID=master_001
KRAKEN_USER_API_KEY=follower1_key
KRAKEN_USER_API_SECRET=follower1_secret
TRADING_TIER=INVESTOR

# .env for Follower 2
COPY_TRADING_MODE=MASTER_FOLLOW
MASTER_ACCOUNT_ID=master_001
COINBASE_API_KEY=follower2_key
COINBASE_API_SECRET=follower2_secret
TRADING_TIER=SAVER

# .env for Follower 3
COPY_TRADING_MODE=MASTER_FOLLOW
MASTER_ACCOUNT_ID=master_001
KRAKEN_USER_API_KEY=follower3_key
KRAKEN_USER_API_SECRET=follower3_secret
TRADING_TIER=INCOME
```

**Result:**
- Master trades on Kraken (LIVABLE tier, $1k-$5k)
- Follower 1 copies on Kraken (INVESTOR tier, $100-$249)
- Follower 2 copies on Coinbase (SAVER tier, $10-$25)
- Follower 3 copies on Kraken (INCOME tier, $250-$999)
- All accounts take profit when master does
- Position sizes scaled to each account's balance

### Example 3: Multi-Account Independent Trading

```bash
# .env
MULTI_ACCOUNT_MODE=true
MULTI_BROKER_INDEPENDENT=true

KRAKEN_MASTER_API_KEY=account1_key
KRAKEN_MASTER_API_SECRET=account1_secret

COINBASE_API_KEY=account2_key
COINBASE_API_SECRET=account2_secret

OKX_MASTER_API_KEY=account3_key
OKX_MASTER_API_SECRET=account3_secret
```

**Result:**
- 3 accounts trading independently
- Each scans markets and trades autonomously
- No copy trading between accounts
- All accounts have independent profit-taking
- Failures on one account don't affect others

---

## 🎯 Profit-Taking Guarantees by Account Type

### Individual Accounts
- ✅ Profit-taking ALWAYS enabled
- ✅ Cannot be disabled via configuration
- ✅ Works 24/7 (every 2.5 minutes)
- ✅ Long + Short (broker dependent)
- ✅ All tiers supported

### Master Accounts
- ✅ Profit-taking ALWAYS enabled
- ✅ Emits signals for followers on exits
- ✅ Works independently even without followers
- ✅ Long + Short (broker dependent)
- ✅ All tiers supported

### Follower Accounts
- ✅ Copies master's profit-taking exits
- ✅ Position sizing automatically scaled
- ✅ Works even if on different broker than master
- ✅ Fee-aware scaling for follower's broker
- ✅ Can trade independently if master offline

### Multi-Account Setups
- ✅ All accounts monitored independently
- ✅ One failure doesn't affect others
- ✅ Parallel profit-taking across all accounts
- ✅ Each account uses appropriate fee-aware targets
- ✅ Comprehensive logging for all accounts

---

## 📊 Monitoring All Account Types

### Log Examples

**Individual Account:**
```
🎯 TAKE PROFIT TP1 HIT: BTC-USD at $42,840 (PnL: +2.0%)
   Account: individual_user_12345
   Tier: INVESTOR
   Broker: Kraken
```

**Master Account:**
```
🎯 TAKE PROFIT TP2 HIT: ETH-USD at $2,575 (PnL: +3.0%)
   Account: MASTER_master_001
   Tier: LIVABLE
   Broker: Kraken
📡 Emitting exit signal to 5 followers...
```

**Follower Account:**
```
🔄 Copying MASTER exit signal: ETH-USD
   Master: master_001
   Follower: user_54321
   Master position: $1,000
   Follower position: $25 (scaled to balance)
✅ Follower profit taken: $0.65 net
```

**Multi-Account:**
```
📊 Multi-Account Profit Summary:
   Account 1 (Kraken Master): +$16.40
   Account 2 (Follower 1): +$8.20
   Account 3 (Follower 2): +$0.30
   Account 4 (Independent OKX): +$24.50
   Total profit across 4 accounts: +$49.40
```

---

## 🔍 Verification Checklist

Use this to verify profit-taking works on all your accounts:

### Individual Accounts
- [ ] Bot logs show "Individual account mode" at startup
- [ ] Profit checks logged every 2.5 minutes
- [ ] TP hits logged with account ID
- [ ] Position exits executed successfully
- [ ] Net profit calculated correctly for broker fees

### Master Accounts
- [ ] Bot logs show "MASTER account mode" at startup
- [ ] Trade signals emitted for entries
- [ ] Trade signals emitted for profit-taking exits
- [ ] Follower count shown in logs
- [ ] Master trades independently even without followers

### Follower Accounts
- [ ] Bot logs show "FOLLOWER mode" at startup
- [ ] Master account ID shown in logs
- [ ] Copy signals received and executed
- [ ] Position sizing scaled correctly
- [ ] Exits copied when master takes profit

### Multi-Account Setups
- [ ] All accounts listed at startup
- [ ] Each account has independent profit monitoring
- [ ] Parallel profit-taking across accounts
- [ ] Individual account statistics logged
- [ ] Failures isolated (one account failure doesn't stop others)

---

## 🚨 Troubleshooting

### "Follower not copying master's profit-taking exit"

**Check:**
1. Master is connected and online
2. Follower has same broker or compatible broker
3. Copy trading mode is enabled
4. Follower account has sufficient balance
5. Trade signals are being emitted

**Solution:**
```bash
# Check master connection
grep "MASTER.*connected" nija.log

# Check signal emission
grep "Emitting.*signal" nija.log

# Check follower copying
grep "Copying.*exit" nija.log
```

### "Multi-account setup not taking profit on all accounts"

**Check:**
1. Each account has valid credentials
2. Each account is connected
3. Independent trading mode is enabled
4. Accounts have open positions to take profit on

**Solution:**
```bash
# Check account connections
grep "connected.*successfully" nija.log

# Check profit monitoring for each account
grep "PROFIT.*account" nija.log
```

---

## 📖 Related Documentation

- `PROFIT_TAKING_GUARANTEE.md` - Core profit-taking guarantee
- `BIDIRECTIONAL_TRADING_GUIDE.md` - Long + Short position guide
- `COPY_TRADING_SETUP.md` - Copy trading configuration
- `USER_MANAGEMENT.md` - Multi-account setup
- `MULTI_EXCHANGE_TRADING_GUIDE.md` - Cross-broker trading

---

**Last Updated:** January 22, 2026
**Maintained By:** NIJA Trading Systems
**Version:** 1.0
