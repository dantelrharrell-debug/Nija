# NIJA Trading Bot 🚀

**Autonomous Cryptocurrency Trading with Dual RSI Strategy & Intelligent Trailing System**

NIJA is a fully autonomous trading bot connected to **Coinbase Advanced Trade API** that scans **732 cryptocurrency markets** and executes trades using a sophisticated **dual RSI strategy** (RSI_9 + RSI_14) with dynamic position management. The bot automatically compounds profits, manages risk, and trails positions to maximize winners while protecting capital.

---

## 🚀 System Status

| Component | Status |
|-----------|--------|
| Exchange | 🟢 **Coinbase Advanced Trade** |
| API Connection | 🟢 Connected & Authenticated |
| Trading Mode | 🟢 **LIVE** (Real Trades) |
| Markets Monitored | 🟢 **732 Crypto Pairs** |
| Auto-Compounding | 🟢 **Active** (Real-time balance) |
| Position Management | 🟢 **NIJA + Manual Positions** |
| Universal Management | 🟢 **All holdings tracked** |

**Latest Updates** (Dec 4, 2025):
- ✅ **PROFIT MAXIMIZATION MODE ACTIVATED**
- ✅ 50% max exposure (increased from 30%) - deploy more capital
- ✅ Accept 1/5 signals with momentum - catch early breakouts
- ✅ Pyramiding enabled - add to winning positions (>2% profit)
- ✅ Micro trades: $0.005 minimum (from $0.01) - maximize small accounts
- ✅ Faster profit taking: TP0.5 at 0.75%, TP1 at 1.5%, TP2 at 3.0%
- ✅ Aggressive sizing: 3-15% per trade (from 2-10%)
- ✅ Runners to 10% (from 5%) with 3% wide trailing
- ✅ Volatility boost: +20% size in high volatility
- ✅ RSI no-trade zones ultra-relaxed (98/2 instead of 95/5)
- ✅ NO burn-down mode, NO profit locks - maximum opportunities
- ✅ Universal position management: ALL holdings protected
- ✅ Market detection fixed: USDC/USDT pairs = CRYPTO

---

## 🎯 Trading Strategy: Dual RSI System

### **Two RSI Indicators = Two Opportunity Types**

NIJA uses **RSI_9** (fast) and **RSI_14** (classic) to capture different market dynamics:

**1. Momentum Breakouts (RSI_9)**
- Detects rapid price acceleration early
- Entry when RSI_9 rising and < 80 (LONG) / falling and > 20 (SHORT)
- Captures strong directional moves before the crowd

**2. Pullback/Mean Reversion (RSI_14)**
- Identifies healthy pullbacks in established trends
- Entry when RSI_14 in 30-70 range and falling in uptrend (LONG)
- Buys dips in strong trends, avoiding overheated entries

### **Signal Scoring System**

Each potential trade is scored 0-5 based on these conditions:

1. **📊 VWAP Alignment**: Price above VWAP (LONG) or below (SHORT)
2. **📈 EMA Trend**: 9 EMA > 21 EMA > 50 EMA (LONG) / reverse for SHORT
3. **🎯 Dual RSI Favorable**: Either momentum OR pullback signal detected
4. **📢 Volume Confirmation**: Current volume ≥ 50% of recent average
5. **🕯️ Candle Close**: Bullish close for LONG, bearish for SHORT

**Entry Requirements**:
- **Minimum**: 2/5 conditions must be true
- **Position Sizing**: Higher scores = larger positions

| Score | Signal Quality | Position Size | Example |
|-------|---------------|---------------|---------|
| 5/5 | A+ Setup | 10% of account | Perfect pullback in strong uptrend |
| 4/5 | Strong | 6.8% of account | Most conditions aligned |
| 3/5 | Moderate | 4.4% of account | Valid setup, some confirmation missing |
| 2/5 | Minimum | 2.0% of account | Enough validation to enter |
| 0-1/5 | No Trade | 0% | Insufficient confirmation |

---

## 💰 Automatic Profit Compounding

**NIJA automatically compounds profits** without any configuration needed:

### **How It Works:**

1. **Before EVERY trade** → Bot calls `get_usd_balance()` to fetch current USD balance from Coinbase API
2. **Balance includes realized profits** → As positions close with profit, USD balance increases
3. **Position size calculated from current balance** → Next trade uses NEW higher balance
4. **Exponential growth** → Larger balance = larger positions = faster growth

**Example Compounding:**
```
Day 1: $100 balance → 5% position = $5.00 per trade
Day 5: $110 balance (after profits) → 5% position = $5.50 per trade
Day 10: $121 balance → 5% position = $6.05 per trade
Day 30: $150 balance → 5% position = $7.50 per trade
```

**Technical Implementation:**
- Line 170 in `trading_strategy.py`: `usd_balance = self.get_usd_balance()`
- Called inside `calculate_position_size()` before every entry
- NOT a stored variable - fetched fresh from API each time
- Ensures position sizing always uses most current account balance

**No configuration required** - compounding is built into the core system architecture.

---

## 📐 NIJA Trailing System (Position Management)

Advanced trailing system designed to **let winners run while protecting profits** - now manages **ALL positions** including manual trades!

### **Universal Position Management** 🌐

**NEW**: NIJA automatically imports and manages ALL Coinbase holdings:
- ✅ **Bot-created positions**: Full NIJA trailing from entry
- ✅ **Manual positions**: Imported and protected with same TSL/TTP logic
- ✅ **Synced every cycle**: Scans all account balances, imports crypto holdings
- ✅ **Intelligent exposure**: Manual positions excluded from 30% NIJA trade limit
- ✅ **Unified protection**: Every position gets trailing stops and profit targets

**How it works**: On every trading cycle, NIJA scans your Coinbase account for ALL cryptocurrency holdings (excludes USD/stablecoins). Any position not already managed is imported with current price as entry, then protected with full NIJA trailing system.

### **Dynamic Trailing Stop-Loss (TSL)**

Adjusts based on profit level to give trends room to breathe:

| Profit Level | TSL Distance | Purpose |
|--------------|-------------|---------|
| +1% profit | 1.2% trailing | Initial protection |
| +2% profit | 1.0% trailing | Looser for trend continuation |
| +3% profit | 0.5% trailing | Standard trailing |
| +5%+ profit | 0.3% trailing | Tight protection of large gains |

### **Intelligent Partial Exits**

Locks profits progressively while letting runners maximize:

- **TP1 (+0.5%)**: Exit 50% of position → Lock initial gains
- **TP2 (+1.0%)**: Exit 25% of position → Capture momentum
- **Runner**: Final 25% trails with TSL → No cap, can run to 5%+ profits

### **Peak Detection System**

Monitors **5 reversal signals** to identify trend exhaustion:

1. Price pullback from recent peak (> 0.5%)
2. RSI divergence (price new high, RSI lower high)
3. RSI extreme reversal (RSI > 70 and falling)
4. VWAP breakdown (price crosses below VWAP)
5. Volume decline (< 70% of recent average)

**Exit Trigger**: When 2+ signals detected → Exit remaining position

### **EMA-21 Support Trailing**

- TSL trails 0.5% below EMA-21 (not tight to price)
- Prevents stop-outs on normal pullbacks
- Respects support levels during consolidation

---

## 🛡️ Risk Management & Safety Controls

### **1. Smart Burn-Down Mode**
- **Trigger**: 3 consecutive losses
- **Action**: Reduce position size to 2% for next 3 trades
- **Reset**: After 3 wins, return to normal sizing
- **Purpose**: Prevents capital bleed during losing streaks

### **2. Daily Profit Lock**
- **Trigger**: +3% daily profit achieved
- **Action**: Only take A+ setups (5/5 score), reduce size to 2.5%
- **Purpose**: Protect profits, avoid giving back gains

### **3. Max Daily Loss Limit**
- **Limit**: -2.5% account drawdown in single day
- **Action**: Stop all trading until next session
- **Purpose**: Prevent catastrophic loss days

### **4. Position Exposure Limits**
- **Max total exposure**: 30% of account across all positions
- **Per-trade limit**: 2-10% based on signal score
- **Purpose**: Prevent overconcentration risk

### **5. No-Trade Zones**

Bot skips entries when:
- ❌ Large unpredictable wicks (> 2% wick size)
- ❌ Low volume consolidation (< 50% average volume)
- ❌ Wide spreads (> 0.3%)
- ✅ Only trades clean, high-probability setups

---

## 🌐 Multi-Market Framework

While currently trading **cryptocurrency on Coinbase**, NIJA's architecture supports multiple asset classes with intelligent market detection:

| Market Type | Current Status | Position Sizing | Detection |
|-------------|---------------|-----------------|-----------|
| **Crypto** | 🟢 **ACTIVE** (732 markets) | 2-10% | -USD/-USDC/-USDT pairs (all correctly identified) |
| **Stocks** | 🟡 Framework ready | 1-5% | Traditional ticker patterns |
| **Futures** | 🟡 Framework ready | 0.25-0.75% | /ES, /NQ, /CL patterns |
| **Options** | 🟡 Framework ready | 1-3% | Greek-based validation |

**Recent Fix** (Dec 4, 2025): Market detection improved - USDC/USDT pairs (like FORTH-USDC, AERO-USDC) now correctly identified as CRYPTO instead of STOCKS. Pattern matching checks `-USD`, `-USDC`, `-USDT` first before other crypto detection.

**Note**: Coinbase Advanced Trade only offers **cryptocurrency spot trading**. To trade stocks, futures, or options, you would need to connect to a different broker (Interactive Brokers, TD Ameritrade, etc.).

**Current Active Markets**: All USD/USDC/USDT cryptocurrency pairs with 'online' status

---

## 🔧 System Architecture

### **Core Components**

| File | Purpose |
|------|---------|
| `bot/trading_strategy.py` | Main trading engine, signal validation, position management |
| `bot/indicators.py` | Dual RSI (9/14), VWAP, EMA (9/21/50), volume calculations |
| `bot/nija_trailing_system.py` | TSL/TTP logic, partial exits, peak detection |
| `bot/market_adapter.py` | Multi-market detection and adaptive risk parameters |
| `bot/live_trading.py` | Coinbase API connection, market scanning, execution loop |
| `bot/nija_config.py` | Configuration parameters and trading pairs |

### **Trading Flow**

1. **Market Scan** → Fetch 732 products from Coinbase Advanced Trade
2. **Filter Markets** → Only USD/USDC/USDT pairs with 'online' status
3. **Sync Positions** → Import ALL Coinbase holdings into NIJA management (NEW)
4. **Get Candles** → Fetch 100 5-minute candles for each monitored pair
5. **Calculate Indicators** → Dual RSI, VWAP, EMA, volume
6. **Score Signal** → Evaluate 5 conditions, count TRUE values
7. **Check No-Trade Zones** → Filter out low-quality setups
8. **Calculate Position Size** → Fetch current USD balance, apply signal score
9. **Execute Trade** → Market order via Coinbase API
10. **Position Tracking** → NIJA system manages TSL/TTP (bot + manual positions)
11. **Continuous Monitoring** → Update stops, check peak signals
12. **Intelligent Exits** → TP1, TP2, runner, or peak detection

### **API Integration**

```python
from coinbase.rest import RESTClient  # Official Coinbase Advanced Trade API

# Initialize client
client = RESTClient(api_key=API_KEY, api_secret=API_SECRET)

# Get products
products = client.get_products()

# Get candles
candles = client.get_candles(
    product_id="BTC-USD",
    granularity="FIVE_MINUTE",
    start=start_time,
    end=end_time
)

# Place order
order = client.market_order_buy(
    product_id="BTC-USD",
    quote_size="10.00"  # $10 USD
)
```

---

## 📊 Live Trading Results

**Recent Execution** (Dec 4, 2025):

| Asset | Pair | Status | Entry Price | Current Status | Strategy |
|-------|------|--------|-------------|----------------|----------|
| ZEC | USD | Active | $352.36 | Trailing | Dual RSI Signal |
| ZEC | USDC | Active | $352.21 | Trailing | Dual RSI Signal |
| BOBBOB | USD | Active | $0.03 | Trailing | High-conviction setup |
| BOBBOB | USDC | Active | $0.03 | Trailing | High-conviction setup |
| ICP | USD | Active | $3.79 | 50% remaining (TP1 hit) | Partial exit executed |
| ICP | USDC | Active | $3.79 | 50% remaining (TP1 hit) | Partial exit executed |
| AERO | USD | Active | $0.69 | 50% remaining (TP1 hit) | Perfect 5/5 setup |
| LINK | USD | Active | $14.79 | Trailing | Recent entry |

**Performance Summary**:
- Total Trades: 8 positions opened
- Partial Exits: 2 positions (ICP, AERO) hit TP1, exited 50%
- Current P&L: -$0.00 (-0.03%) - positions still open with trailing stops
- Max Exposure: 36.4% reached (blocked additional entries as designed)
- NIJA Trailing: Active on all positions

**System Validations**:
✅ Universal position management working (syncs all holdings)
✅ Market detection fixed (all USDC/USDT pairs showing as CRYPTO)
✅ Partial exits executing correctly (50% at TP1)
✅ Max exposure limit enforced (stopped new trades at 36.4%)
✅ Position syncing handles Coinbase object formats
✅ Manual positions excluded from exposure calculation
✅ Compounding active (fresh balance fetch confirmed)

---

## 🚀 Getting Started

### **Prerequisites**

1. **Coinbase Account** with API access
2. **Coinbase Advanced Trade API credentials**:
   - API Key
   - API Secret
   - Private Key (PEM file)
3. **Python 3.9+**
4. **Environment** (local or cloud hosting)

### **Local Setup**

```bash
# Clone repository
git clone <your-repo-url>
cd Nija

# Install dependencies
pip install -r requirements.txt

# Configure environment variables
export COINBASE_API_KEY="your_api_key"
export COINBASE_API_SECRET="your_api_secret"
export COINBASE_PEM_CONTENT="your_pem_base64"
export LIVE_MODE="true"

# Run the bot
bash restart_nija.sh
```

### **Environment Variables**

Required secrets (store securely):

```bash
COINBASE_API_KEY=<your_coinbase_api_key>
COINBASE_API_SECRET=<your_coinbase_api_secret>
COINBASE_PEM_CONTENT=<base64_encoded_private_key>
LIVE_MODE=true  # Set to "false" for paper trading
```

### **Monitor the Bot**

```bash
# View live logs
tail -f nija.log

# Check active positions
grep "Position opened" nija.log | tail -10

# View recent signals
grep "Score:" nija.log | tail -20
```

---

## 🔐 Security Best Practices

1. **Never commit API keys** to version control
2. **Use environment variables** for all secrets
3. **Enable IP whitelisting** on Coinbase API settings
4. **Set API permissions** to trade-only (no withdrawals)
5. **Monitor account activity** regularly
6. **Use secure hosting** with encrypted storage
7. **Backup PEM keys** securely offline

---

## ⚙️ Configuration

### **Trading Pairs**

Edit `bot/nija_config.py`:

```python
TRADING_PAIRS = [
    'BTC-USD',
    'ETH-USD',
    'SOL-USD',
    # Add more pairs as needed
]
```

### **Risk Parameters**

Adjust in `bot/trading_strategy.py`:

```python
self.max_exposure = 0.30  # 30% max total exposure
self.max_daily_loss = 0.025  # -2.5% max daily loss
self.daily_profit_lock_threshold = 0.03  # +3% profit lock
self.trade_cooldown_seconds = 120  # 2 minutes between trades
```

### **Position Sizing**

Adjust in `bot/market_adapter.py`:

```python
# Crypto parameters
position_min = 0.02  # 2% minimum
position_max = 0.10  # 10% maximum
```

### **Stop the Bot**:
```bash
railway down
```

### **Restart After Update**:
```bash
git push origin main  # Railway auto-deploys on push
```

---

## 🔐 Environment Variables (Railway)

NIJA requires the following secrets configured in Railway:

```
COINBASE_API_KEY=your_api_key
COINBASE_API_SECRET=your_api_secret  
COINBASE_PEM_CONTENT=your_private_key_pem_base64
LIVE_MODE=true
```

**Security**: All keys stored in Railway's encrypted vault. Never committed to GitHub.

---

## 📁 Core Files

| File | Purpose |
|------|---------|
| `bot/trading_strategy.py` | 5-point validation, NIJA trailing system, position management |
| `bot/live_trading.py` | Main execution loop, 2.5-minute scan cycle |
| `bot/indicators.py` | VWAP, EMA (9/21/50), RSI, volume calculations |
| `bot/nija_trailing_system.py` | TSL/TTP logic, partial exits, position tracking |
| `bot/market_adapter.py` | Multi-market detection (crypto/stocks/futures/options) |
| `start.sh` | Railway startup script with error handling |

**Recent Fixes** (Dec 2025):
- ✅ Import path resolution for Railway deployment
- ✅ Coinbase API response object handling (converts to DataFrame)
- ✅ High-frequency configuration (2.5min scans, 2/5 threshold)
- ✅ Verbose logging for production debugging

---

## 🎓 Key Principles

1. **Frequency Meets Quality**: 12+ trades/hour but only on validated setups (2/5+ conditions)
2. **Risk-First Approach**: TSL, TTP, burn-down, profit lock prevent disasters  
3. **Automation = Discipline**: No emotional trades, no FOMO, no revenge trading
4. **24/7 Crypto Advantage**: Never sleep, never miss opportunities
5. **Device Independence**: Railway cloud hosting means your laptop/phone can be off
6. **Adaptive Intelligence**: No-trade zones filter bad markets automatically
7. **Trailing Mastery**: NIJA system locks profits while letting winners run

**High-Frequency Philosophy**:
> "More trades = more data = faster learning. But every trade must still earn its place through validation."

The 2/5 threshold doesn't mean "lower quality"—it means "more opportunities to capture edge in favorable conditions."

---

## 📈 Performance Expectations

**Realistic Targets**:
- Win Rate: 55-65% (good for algo trading)
- Average Win: +1.5% to +3.0%
- Average Loss: -0.8% to -1.2% (TSL protection)
- Daily Profit Target: +1% to +3% (conservative)
- Max Drawdown: -5% to -8% (normal volatility)

**Risk Factors**:
- Crypto Volatility: 24/7 markets can gap unexpectedly
- Exchange Fees: Coinbase fees ~0.5-0.6% per trade
- Slippage: Market orders may have price impact
- API Downtime: Exchange outages can prevent exits
- Flash Crashes: Stop-losses may not fill at expected prices

**Capital Requirements**:
- Minimum: $100 (supports $0.01+ position sizes)
- Recommended: $1,000+ (better fee absorption and position sizing)
- Optimal: $5,000+ (full flexibility across signal scores)

---

## 🎓 Trading Philosophy

> **"Discipline, not prediction, generates profits."**

NIJA embodies these core principles:

1. **Systematic Execution** → No emotions, no FOMO, no revenge trading
2. **Risk-First Approach** → Every trade has defined stop-loss and take-profit
3. **Let Winners Run** → Trailing system captures extended moves
4. **Cut Losers Fast** → TSL prevents small losses from becoming large
5. **Compound Relentlessly** → Profits automatically reinvested for exponential growth
6. **Adapt to Conditions** → Profit lock, burn-down, no-trade zones adjust to markets
7. **Quality Over Quantity** → 2/5 threshold ensures valid setups, not random entries

**The Edge**: Consistent application of a positive-expectancy strategy without human error or emotional interference.

---

## ⚠️ Disclaimers & Warnings

- **LIVE TRADING RISK**: This bot executes REAL trades with REAL money. You can lose your entire account balance.
- **Not Financial Advice**: NIJA is a tool. You are solely responsible for all trading decisions and outcomes.
- **No Guarantees**: Past performance does not guarantee future results. Markets can change.
- **Cryptocurrency Volatility**: Crypto markets are extremely volatile and can experience sudden, severe price movements.
- **Exchange Risk**: Coinbase outages, hacks, or regulatory issues could affect your ability to trade or access funds.
- **Regulatory Risk**: Cryptocurrency regulations vary by jurisdiction and can change.
- **Tax Implications**: Trading generates taxable events. Consult a tax professional.
- **Total Loss Possible**: Never trade with money you cannot afford to lose completely.

**USE AT YOUR OWN RISK**

---

## 📝 License & Support

**License**: MIT (modify and use freely, no warranty provided)

**Support**:
- Review code in repository
- Check logs for debugging
- Understand the strategy before deploying live
- Start with small capital to validate behavior

**Maintenance**: This is autonomous software. Monitor regularly and adjust parameters based on market conditions.

---

## 🏆 NIJA Core Values

✅ **Transparency**: Every trade logged, every decision explainable  
✅ **Automation**: 24/7 operation without human intervention  
✅ **Risk Management**: Multiple layers of protection  
✅ **Compounding**: Automatic profit reinvestment  
✅ **Adaptability**: Responds to market conditions dynamically  
✅ **Discipline**: Never deviates from rules  

---

**Last Updated**: December 4, 2025  
**Version**: 3.0 (PROFIT MAXIMIZATION - Aggressive Mode)  
**Status**: 🟢 Live Trading on Coinbase Advanced Trade

**Recent Updates**:
- 🚀 **AGGRESSIVE PROFIT MODE**: 50% exposure, 1/5 signals, pyramiding, micro trades
- ✅ Faster profit capture: 4-stage exits (0.75%/1.5%/3%/10%)
- ✅ Position sizing: 3-15% per trade (50% more aggressive)
- ✅ Volatility boost: +20% sizing in high volatility markets
- ✅ NO restrictions: Removed burn-down, profit locks - pure opportunity capture
- ✅ Pyramiding: Add to winners (>2% profit)
- ✅ Universal position management: NIJA manages ALL positions (bot + manual)
- ✅ Market detection fixed: USDC/USDT pairs correctly identified as CRYPTO
- ✅ Micro trades enabled: $0.005 minimum (maximize small accounts)

---

**Quick Reference**:
```bash
# Start bot
bash restart_nija.sh

# View logs
tail -f nija.log

# Check positions
grep "Position opened" nija.log
```

**Current Configuration**:
- Exchange: Coinbase Advanced Trade
- Markets: 732 cryptocurrency pairs
- Strategy: Dual RSI (9/14) with 5-point validation
- Entry: 2/5 minimum conditions
- Position: 2-10% based on signal score
- Compounding: Automatic (real-time balance)
- Risk: 30% max exposure, -2.5% daily stop

🚀 **NIJA is LIVE and compounding profits automatically!**
- ✅ Win rate: 55-65% (good for 2/5 threshold)
- ✅ Average win: +2-4%
- ✅ Average loss: -1-1.5% (TSL protection)
- ❌ Don't expect 8% daily returns every day
- ❌ Drawdown periods are normal (markets consolidate)

**Recommended Capital**: Minimum $1,000 to handle position sizing and fee impact

---

## 🏆 NIJA Philosophy

> "The best traders don't predict the future—they respond to the present with precision, frequency, and discipline."

NIJA Ultimate Trading Bot is designed to:
- ✅ Execute validated setups at high frequency (12+ trades/hour capability)
- ✅ Remove emotion through algorithmic decision-making
- ✅ Enforce strict risk management on EVERY trade (TSL/TTP/burn-down)
- ✅ Capture micro-edges consistently through volume + probability
- ✅ Trail profits intelligently without giving back gains
- ✅ Operate 24/7 without human intervention or fatigue
- ✅ Adapt to market conditions (no-trade zones, profit lock, burn-down)

**The Edge**: While 2/5 signals are more frequent, the combination of NIJA trailing, no-trade zones, and risk controls maintains positive expectancy. It's not about being right 100% of the time—it's about managing losses and maximizing winners.

---

**Bot Status**: 🟢 **LIVE on Railway (High-Frequency Mode)**  
**Last Updated**: December 3, 2025 (v2.0 - High-Frequency Configuration)  
**Deployment**: Auto-deploy via GitHub → Railway integration  
**Maintainer**: Autonomous 24/7 operation with verbose logging

---

**Quick Start Commands**:
```bash
# View live logs
railway logs --follow

# Check status
railway status

# Stop bot
railway down

# Update & redeploy
git push origin main
```

**Current Configuration**:
- Scan: 2.5 minutes
- Threshold: 2/5 conditions
- Cooldown: 0 seconds
- Max daily trades: 200
- Markets: BTC-USD, ETH-USD, SOL-USD
