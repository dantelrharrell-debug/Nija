# NIJA Ultimate Trading Logic™ – Cross-Market Edition

**24/7 Automated Crypto Trading Bot with Precision 5-Point Entry Validation**

NIJA is a fully autonomous trading system running on **Railway.app** that scans multiple cryptocurrency markets (BTC-USD, ETH-USD, SOL-USD) every 5 minutes and executes trades using a rigorous 5-point validation system. The bot operates independently 24/7 in the cloud—your device can be off, and NIJA keeps trading.

---

## 🚀 Live Deployment Status

| Component | Status |
|-----------|--------|
| Platform | 🟢 Railway.app (24/7 Cloud) |
| Coinbase API | 🟢 Connected & Validated |
| Trading Mode | 🟢 LIVE (Real Trades) |
| Market Scan | 🟢 Every 5 Minutes |
| Multi-Market | 🟢 BTC/ETH/SOL |
| Independence | 🟢 Device-Off Operation |

**Current State**: Bot is LIVE on Railway. Runs continuously without requiring your device. Stops only when you manually execute `railway down`.

---

## 🎯 NIJA Ultimate Trading Logic™

### **5-Point Entry Validation System**

NIJA uses a **5-point checklist** where **ALL conditions must be TRUE** before entering a trade:

1. **📊 VWAP Alignment**: Price must be above VWAP for LONG, below for SHORT
2. **📈 EMA Momentum**: 9 EMA > 21 EMA for LONG, 9 EMA < 21 EMA for SHORT  
3. **🎯 RSI Cross**: RSI must cross 50 (above for LONG, below for SHORT)
4. **📢 Volume Surge**: Current volume ≥ 1.2× average volume
5. **🕯️ Candle Close Confirmation**: Close price confirms direction vs. open

**Signal Scoring**:
- **5/5 points** = Maximum conviction → 10% position size
- **4/5 points** = Strong signal → 6% position size
- **3/5 points** = Moderate signal → 3.5% position size
- **<3/5 points** = No trade (insufficient validation)

---

## �� Multi-Market Support with Auto-Detection

NIJA automatically detects market type and applies appropriate rules:

| Market Type | Detection Logic | Position Size | Special Rules |
|-------------|-----------------|---------------|---------------|
| **Crypto** | 24/7 operation, pair ends in -USD | 3.5%–10% | No market hours restriction |
| **Stocks** | M-F 9:30am-4pm ET | 4%–12% | Respect market hours |
| **Futures** | /ES, /NQ, /CL prefix | 2%–8% | Extended hours allowed |
| **Options** | Greek-based validation | 1.5%–5% | Theta/IV checks |

Currently monitoring: **BTC-USD, ETH-USD, SOL-USD** (every 5 minutes)

---

## 📐 Position Management: TSL/TTP System

NIJA uses **Trailing Stop Loss (TSL)** and **Trailing Take Profit (TTP)** with a 3-tier exit strategy:

### **Exit Breakdown**:
1. **First 50%** exits at +1.5% profit (lock initial gains)
2. **Next 25%** exits at +3% profit (capture momentum)
3. **Final 25%** trails at +5% profit (ride the wave)

### **Trailing Mechanics**:
- **TSL**: Starts at 1% below entry, tightens as profit increases
- **TTP**: Trails at 0.5% from peak—locks profit if price reverses
- **Burn-Down Limit**: If position drops >2% from entry, exit immediately (prevents deep losses)

---

## 🛡️ Safety Controls & Risk Management

### **1. Profit Lock**
- Once position reaches +2% profit, TSL moves to breakeven
- Ensures no losing trades after initial profit is captured

### **2. No-Trade Zones**
- Avoids trading during high-volatility events (Fed announcements, NFP, etc.)
- Skips trades if spread > 0.5% (prevents slippage on illiquid markets)

### **3. Cooldown Period**
- After ANY trade (win or loss), NIJA waits 2 minutes before next entry
- Prevents overtrading and emotional revenge trades

### **4. Max Daily Drawdown**
- If account drops >5% in a single day, bot stops trading until next session
- Protects against catastrophic loss days

---

## 🔧 How It Works (Technical Flow)

1. **Market Scan**: Every 5 minutes, NIJA fetches candles from Coinbase for BTC/ETH/SOL
2. **Data Analysis**: Calculates VWAP, EMAs, RSI, volume ratios using 5-minute granularity
3. **5-Point Check**: Evaluates all 5 entry conditions (VWAP, EMA, RSI, volume, candle)
4. **Signal Score**: Counts how many conditions are TRUE (3/5, 4/5, or 5/5)
5. **Position Sizing**: 5/5 → 10%, 4/5 → 6%, 3/5 → 3.5% (based on account balance)
6. **Trade Execution**: Places market order via Coinbase Advanced Trade API
7. **Position Monitoring**: Tracks profit/loss, adjusts TSL/TTP every minute
8. **Exit Logic**: Automatically exits at profit targets or TSL trigger

---

## 📊 Example Trade Scenario

**Market**: BTC-USD  
**Entry Price**: $43,500  
**Signal Score**: 5/5 (all conditions met)  
**Position Size**: $1,000 (10% of $10,000 account)

**Exit Plan**:
- **50%** ($500) sells at $43,652 (+1.5% profit) → **+$7.50** locked
- **25%** ($250) sells at $43,805 (+3% profit) → **+$7.63** locked  
- **25%** ($250) trails from $45,675 (+5%) → **Final exit**: $45,446 → **+$48.65** locked

**Total Profit**: $63.78 on $1,000 position = **+6.38% return**

---

## 🚦 How to Monitor & Control

### **View Live Logs**:
```bash
railway logs --follow
```

### **Check Bot Status**:
```bash
railway status
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
| `bot/trading_strategy.py` | 5-point validation logic, position sizing |
| `bot/coinbase_client.py` | Coinbase Advanced Trade API integration |
| `bot/indicators.py` | VWAP, EMA, RSI calculations |
| `bot/data_fetcher.py` | Market data retrieval (5-min candles) |
| `bot/bot_live.py` | Main execution loop, market scanning |

---

## 🎓 Key Principles

1. **Precision Over Frequency**: Quality 5-point setups beat random trades
2. **Risk Management First**: TSL/TTP and burn-down prevent disasters  
3. **Automation = Discipline**: No emotional trades, no FOMO, no panic sells
4. **24/7 Advantage**: Crypto never sleeps—NIJA doesn't either
5. **Device Independence**: Railway cloud hosting means your laptop can be off

---

## ⚠️ Warnings

- **LIVE MODE**: This bot executes REAL trades with REAL money on Coinbase
- **Not Financial Advice**: NIJA is a tool. You are responsible for your trading decisions
- **Risk of Loss**: All trading involves risk. Never trade more than you can afford to lose
- **API Rate Limits**: Coinbase has rate limits—NIJA respects them with 5-min intervals
- **Market Volatility**: Crypto markets can be extremely volatile. TSL protects but doesn't eliminate risk

---

## 🏆 NIJA Philosophy

> "The best traders don't predict the future—they respond to the present with precision and discipline."

NIJA Ultimate Trading Logic™ is designed to:
- ✅ Remove emotion from trading decisions
- ✅ Enforce strict risk management on every trade
- ✅ Capture high-probability setups with 5-point validation
- ✅ Trail profits intelligently without giving back gains
- ✅ Operate 24/7 without human intervention

---

**Bot Status**: 🟢 LIVE on Railway  
**Last Updated**: 2025 (Deployed with granularity="FIVE_MINUTE" fix)  
**Maintainer**: Auto-deployed via GitHub → Railway integration
