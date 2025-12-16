# NIJA - Autonomous Cryptocurrency Trading Bot

**Version**: APEX v7.1 Stable  
**Status**: Production Ready ✅  
**Last Updated**: December 16, 2025  
**Balance Detection**: v2 API ($35.31 confirmed)

---

## 🎯 What is NIJA?

NIJA is a fully autonomous cryptocurrency trading bot that connects to Coinbase Advanced Trade API and executes trades using a sophisticated dual RSI strategy (RSI_9 + RSI_14) with dynamic position management, automatic profit compounding, and intelligent trailing systems.

### Key Features

- ✅ **Dual-Mode Operation**: Autonomous scanning (every 15 sec) + TradingView webhooks (instant execution)
- ✅ **732+ Market Coverage**: Scans ALL cryptocurrency pairs on Coinbase Advanced Trade dynamically
- ✅ **APEX v7.1 ULTRA AGGRESSIVE**: ADX 5, Volume 5%, 3/5 filter agreement, 5-25% position sizing
- ✅ **Adaptive Risk Management**: Dynamic position sizing with 50% max exposure
- ✅ **Automatic Balance Detection**: v2 API support for retail/consumer accounts
- ✅ **24/7 Autonomous Trading**: Containerized deployment on Railway
- ✅ **Profit Compounding**: $17.31 → $100 in 8-17 days (targeting $5-10/day)
- ✅ **Real-time Logging**: Comprehensive trade execution and strategy logs

### Performance Metrics & Profit Targets

**Current Trading Balance**: $17.31 USDC  
**Strategy Mode**: ULTRA AGGRESSIVE (ADX 5, Vol 5%, 3/5 filters, 5-25% positions)  
**Markets Scanned**: ALL 732+ cryptocurrency pairs on Coinbase  
**Scan Frequency**: Every 15 seconds  
**Uptime**: 24/7 containerized on Railway

#### Realistic Profit Expectations

**Phase 1: Starting Balance ($17.31)**
- **Daily Target**: $5-10/day (29-58% daily return)
- **Position Sizing**: 5-25% per trade ($0.87-$4.33 per position)
- **Time to $100**: 8-17 trading days (compounding daily)
- **Strategy**: Very aggressive, high volume of small wins

**Phase 2: $100 Account Balance**
- **Daily Target**: $20-30/day (20-30% daily return)
- **Position Sizing**: 5-25% per trade ($5-$25 per position)
- **Monthly Potential**: $600-900/month
- **Strategy**: Maintain aggressive stance, more capital to work with

**Phase 3: $500+ Account Balance**
- **Daily Target**: $50-100/day (10-20% daily return)
- **Position Sizing**: 5-15% per trade ($25-$75 per position)
- **Monthly Potential**: $1,500-3,000/month
- **Strategy**: Can reduce aggressiveness, sustainable long-term gains

#### Compounding Growth Chart

| Starting Balance | Daily Target | Days to $100 | Days to $500 | Days to $1,000 |
|-----------------|--------------|--------------|--------------|----------------|
| $17.31 | $5-10/day | 8-17 days | 48-97 days | 98-197 days |
| $100 | $20-30/day | Already there | 13-20 days | 30-45 days |
| $500 | $50-100/day | Already there | Already there | 5-10 days |

**Note**: These are aggressive targets. Actual results depend on market conditions, strategy performance, and risk management. Always expect 20-40% drawdown periods.

---

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- Coinbase Advanced Trade account
- API credentials from Coinbase
- Docker (for deployment)
- Railway account (optional, for hosting)

### Installation

```bash
# 1. Clone the repository
git clone https://github.com/dantelrharrell-debug/Nija.git
cd Nija

# 2. Create virtual environment
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment variables
cp .env.example .env
# Edit .env with your Coinbase API credentials

# 5. Test balance detection
python test_v2_balance.py

# 6. Run the bot
python main.py
```

---

## 🔐 Coinbase API Setup

### Critical: Use v2 API for Retail Accounts

NIJA requires v2 API access to detect balances in retail/consumer Coinbase accounts.

### Step 1: Generate API Credentials

**Option A: From Coinbase Cloud Portal (Recommended)**

1. Go to: https://portal.cloud.coinbase.com/access/api
2. Click "Create API Key"
3. Set permissions:
   - ✅ **View** (to read account balances)
   - ✅ **Trade** (to execute orders)
4. Copy **BOTH**:
   - API Key (starts with `organizations/...`)
   - Private Key (PEM format - multiple lines)

**Option B: From Coinbase Website**

1. Go to: https://www.coinbase.com/settings/api
2. Create new API key with View + Trade permissions
3. Save credentials securely

### Step 2: Configure Environment Variables

Create `.env` file in project root:

```bash
# Coinbase Advanced Trade API Credentials
COINBASE_API_KEY="organizations/YOUR-ORG-ID/apiKeys/YOUR-KEY-ID"
COINBASE_API_SECRET="-----BEGIN EC PRIVATE KEY-----\nYOUR_PRIVATE_KEY_HERE\n-----END EC PRIVATE KEY-----\n"

# Optional Configuration
ALLOW_CONSUMER_USD=true
PORT=5000
WEB_CONCURRENCY=1
```

**IMPORTANT**: The API_SECRET must be in PEM format with escaped newlines (`\n`).

### Step 3: Verify Balance Detection

```bash
python test_v2_balance.py
```

Expected output:
```
✅ Connected!
💰 BALANCES:
   USD:  $30.31
   USDC: $5.00
   TRADING BALANCE: $35.31
✅✅✅ SUCCESS! NIJA CAN SEE YOUR FUNDS!
```

---

## 📁 Project Structure

```
Nija/
├── bot/                          # Core trading bot code
│   ├── trading_strategy.py      # Main trading strategy
│   ├── nija_apex_strategy_v71.py  # APEX v7.1 implementation
│   ├── broker_integration.py    # Coinbase API integration (legacy)
│   ├── broker_manager.py        # Multi-broker manager (current)
│   ├── risk_manager.py          # Risk management logic
│   ├── execution_engine.py      # Trade execution
│   ├── indicators.py            # Technical indicators
│   ├── apex_*.py                # APEX strategy components
│   └── tradingview_webhook.py  # Webhook server
│
├── scripts/                     # Utility scripts
│   ├── print_accounts.py        # Balance checker
│   └── ...
│
├── archive/                     # Historical implementations
├── .env                         # Environment variables (SECRET)
├── .gitignore                   # Git ignore rules
├── Dockerfile                   # Container definition
├── docker-compose.yml           # Docker Compose config
├── requirements.txt             # Python dependencies
├── runtime.txt                  # Python version (3.11)
├── start.sh                     # Startup script
├── main.py                      # Bot entry point
├── railway.json                 # Railway deployment config
└── README.md                    # This file
```

---

## 🔧 Configuration

### Environment Variables

| Variable | Required | Description | Example |
|----------|----------|-------------|---------|
| `COINBASE_API_KEY` | ✅ | Coinbase API key | `organizations/.../apiKeys/...` |
| `COINBASE_API_SECRET` | ✅ | PEM private key | `-----BEGIN EC PRIVATE KEY-----\n...` |
| `ALLOW_CONSUMER_USD` | ⚠️ | Accept consumer balances | `true` |
| `PORT` | ❌ | Webhook server port | `5000` |
| `WEB_CONCURRENCY` | ❌ | Worker processes | `1` |

### Strategy Parameters

Edit `bot/nija_apex_strategy_v71.py`:

```python
# Risk Management
POSITION_SIZE_PERCENT = 0.02  # 2% per trade
MAX_POSITION_SIZE = 0.10      # 10% max

# RSI Settings
RSI_PERIOD_FAST = 9
RSI_PERIOD_SLOW = 14
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70

# Trend Filters
USE_VOLUME_FILTER = True
USE_MOMENTUM_FILTER = True
```

---

## 🐳 Docker Deployment

### Build Container

```bash
docker build -t nija-bot .
```

### Run Container

```bash
docker run -d \
  --name nija \
  --env-file .env \
  -p 5000:5000 \
  nija-bot
```

### View Logs

```bash
docker logs -f nija
```

### Stop Container

```bash
docker stop nija
docker rm nija
```

---

## 🚂 Railway Deployment

### Prerequisites

1. Railway account: https://railway.app
2. Railway CLI installed: `npm i -g @railway/cli`
3. GitHub repository connected

### Deploy

```bash
# 1. Login to Railway
railway login

# 2. Link project
railway link

# 3. Set environment variables
railway variables set COINBASE_API_KEY="your-key"
railway variables set COINBASE_API_SECRET="your-secret"

# 4. Deploy
git push origin main
```

Railway will automatically:
- Build the Docker container
- Deploy to production
- Start the bot
- Provide logs and monitoring

### Access Logs

```bash
railway logs
```

Or visit: https://railway.app → Your Project → Deployments → Logs

---

## 🧪 Testing

### Balance Detection Test

```bash
python test_v2_balance.py
```

### Diagnostic Tools

```bash
# Full account diagnostics
python diagnose_balance.py

# Raw API test
python test_raw_api.py

# Print all accounts
python scripts/print_accounts.py
```

### Strategy Backtests

```bash
# APEX v7.1 backtest
python bot/apex_backtest.py

# Test strategy integration
python test_apex_strategy.py
```

---

## 📊 Trading Strategy: APEX v7.1

### Overview

APEX v7.1 uses a dual RSI system with trend confirmation and volume filters.

### Entry Signals

**BUY Signal** requires ALL of:
1. ✅ RSI_9 crosses above RSI_14
2. ✅ Both RSI < 70 (not overbought)
3. ✅ Price above 50-period moving average
4. ✅ Volume above 20-period average
5. ✅ Momentum indicator positive

**SELL Signal** requires ALL of:
1. ✅ RSI_9 crosses below RSI_14
2. ✅ Both RSI > 30 (not oversold)
3. ✅ Price below 50-period moving average
4. ✅ Volume above 20-period average
5. ✅ Momentum indicator negative

### Position Management

- **Entry Size**: 2-10% of balance (adaptive)
- **Stop Loss**: 3% below entry
- **Take Profit**: 5% above entry
- **Trailing Stop**: Activates at +2%, trails at 1.5%

### Risk Controls

- Maximum 3 concurrent positions
- Maximum 20% total portfolio risk
- Circuit breaker if 3 losses in 24 hours
- Minimum $5 per trade

---

## 🔍 Monitoring & Logs

### Log Files

- **Main Log**: `nija.log`
- **Location**: `/usr/src/app/nija.log` (in container)
- **Format**: `YYYY-MM-DD HH:MM:SS | LEVEL | Message`

### Key Log Messages

```
✅ Connection successful
💰 Balance detected: $35.31
📊 Signal: BUY on BTC-USD
✅ Order executed: Buy 0.001 BTC
🎯 Position opened: BTC-USD at $42,500
```

### Error Logs

```
❌ Balance detection failed
🔥 ERROR get_account_balance: [details]
⚠️ API rate limit exceeded
```

---

## ⚠️ Troubleshooting

### Problem: Balance shows $0.00

**Solution**: Your funds are in retail Coinbase, not Advanced Trade

1. Check API credentials are correct
2. Verify API key has View + Trade permissions
3. Run `python test_v2_balance.py` to test v2 API
4. If still $0, funds may need transfer to Advanced Trade portfolio

See: `API_KEY_ISSUE.md`

### Problem: API Authentication Failed (401)

**Solution**: API key expired or incorrect

1. Regenerate API key at https://portal.cloud.coinbase.com
2. Update `.env` file with new credentials
3. Verify PEM key has proper newlines: `\n`
4. Test with `python scripts/print_accounts.py`

### Problem: IndentationError in trading_strategy.py

**Solution**: Python indentation issue

1. Check line indentation (4 spaces, never tabs)
2. Verify `close_full_position()` method indentation
3. Run `python -m py_compile bot/trading_strategy.py`

### Problem: No trades executing

**Possible causes**:
- Market signals are "HOLD" (waiting for clear trend)
- Balance too low (< $5 minimum)
- Risk manager blocking trades (max positions reached)
- Circuit breaker active (3 losses in 24h)

**Check logs for**:
```
Symbol: BTC-USD, Signal: HOLD, Reason: Mixed signals (Up:4/5, Down:3/5)
```

---

## 🎓 How to Recreate NIJA from Scratch

### Step 1: Set Up Python Environment

```bash
# Create project directory
mkdir nija-bot
cd nija-bot

# Initialize git repository
git init

# Create Python virtual environment
python3.11 -m venv .venv
source .venv/bin/activate

# Create requirements.txt
cat > requirements.txt << EOF
coinbase-advanced-py==1.8.2
Flask==2.3.3
pandas==2.1.1
numpy==1.26.3
requests==2.31.0
PyJWT==2.8.0
cryptography==42.0.0
python-dotenv==1.0.0
EOF

# Install dependencies
pip install -r requirements.txt
```

### Step 2: Create Project Structure

```bash
# Create directories
mkdir -p bot scripts archive

# Create main files
touch main.py
touch bot/__init__.py
touch bot/trading_strategy.py
touch bot/broker_manager.py
touch bot/risk_manager.py
touch bot/indicators.py
```

### Step 3: Implement Broker Integration

Create `bot/broker_manager.py` with v2 API support for retail balance detection. See the full implementation in this repository.

Key features:
- JWT authentication with PEM keys
- v2 API fallback for retail accounts
- Automatic PEM newline normalization
- Balance aggregation across USD/USDC

### Step 4: Implement Trading Strategy

Create `bot/trading_strategy.py` with APEX v7.1 logic:
- Dual RSI system (RSI_9 + RSI_14)
- Trend filters (50-period MA)
- Volume confirmation
- Momentum indicators

See `bot/nija_apex_strategy_v71.py` for complete implementation.

### Step 5: Create Main Entry Point

Create `main.py`:

```python
import os
import logging
from bot.broker_manager import CoinbaseBroker
from bot.trading_strategy import TradingStrategy

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s'
)

def main():
    # Load environment
    from dotenv import load_dotenv
    load_dotenv()
    
    # Initialize broker
    broker = CoinbaseBroker()
    if not broker.connect():
        print("Failed to connect to broker")
        return
    
    # Get balance
    balance = broker.get_account_balance()
    print(f"Trading Balance: ${balance['trading_balance']:.2f}")
    
    # Initialize strategy
    strategy = TradingStrategy(broker, balance['trading_balance'])
    
    # Start trading loop
    strategy.run()

if __name__ == "__main__":
    main()
```

### Step 6: Configure Environment

Create `.env`:

```bash
COINBASE_API_KEY="your-api-key-here"
COINBASE_API_SECRET="-----BEGIN EC PRIVATE KEY-----\nYOUR-KEY\n-----END EC PRIVATE KEY-----\n"
ALLOW_CONSUMER_USD=true
```

Create `.gitignore`:

```
.env
*.pyc
__pycache__/
.venv/
*.log
*.pem
```

### Step 7: Create Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /usr/src/app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "main.py"]
```

### Step 8: Deploy to Railway

1. Create `railway.json`:

```json
{
  "build": {
    "builder": "DOCKERFILE",
    "dockerfilePath": "Dockerfile"
  },
  "deploy": {
    "startCommand": "python main.py",
    "restartPolicyType": "ON_FAILURE",
    "restartPolicyMaxRetries": 10
  }
}
```

2. Push to GitHub
3. Connect Railway to repository
4. Set environment variables
5. Deploy

### Step 9: Monitor & Test

```bash
# Test locally
python main.py

# Test balance detection
python test_v2_balance.py

# View logs
tail -f nija.log

# Deploy and monitor on Railway
railway logs -f
```

---

## 📜 License

This project is proprietary software. All rights reserved.

**Unauthorized copying, modification, or distribution is prohibited.**

---

## ⚡ Quick Reference

### Essential Commands

```bash
# Start bot
python main.py

# Test balance
python test_v2_balance.py

# View logs
tail -f nija.log

# Deploy to Railway
git push origin main

# Check Railway logs
railway logs -f
```

### Important Files

- `.env` - API credentials (SECRET)
- `main.py` - Bot entry point
- `bot/broker_manager.py` - Coinbase integration
- `bot/trading_strategy.py` - Trading logic
- `nija.log` - Bot logs

### Key Metrics

- **Starting Balance**: $17.31 USDC
- **Target Balance**: $100 (in 8-17 days)
- **Daily Profit Goal**: $5-10/day initially, $20-30/day at $100
- **Position Size**: 5-25% adaptive (ULTRA AGGRESSIVE)
- **Markets**: ALL 732+ crypto pairs (dynamically fetched)
- **Status**: LIVE on Railway ✅

---

**NIJA v7.1 - December 16, 2025**  
*Autonomous. Adaptive. Always Trading.*

🚀 Bot is LIVE and monitoring markets 24/7
