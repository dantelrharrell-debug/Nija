# NIJA Multi-Asset Platform - Quick Start Guide

## 🚀 Getting Started in 5 Minutes

### Step 1: Installation

```bash
# Clone repository
git clone https://github.com/dantelrharrell-debug/Nija.git
cd Nija

# Install dependencies
pip install -r requirements.txt
```

### Step 2: Configure API Keys

Create a `.env` file with your credentials:

```bash
# Copy example
cp .env.example .env

# Edit .env with your API keys
# For Crypto (required):
COINBASE_API_KEY=your_coinbase_key
COINBASE_API_SECRET=your_coinbase_secret
KRAKEN_API_KEY=your_kraken_key
KRAKEN_API_SECRET=your_kraken_secret

# For Stocks (optional):
ALPACA_API_KEY=your_alpaca_key
ALPACA_API_SECRET=your_alpaca_secret

# JWT Secret
JWT_SECRET_KEY=your_random_secret_key
```

### Step 3: Run Tests

```bash
# Verify installation
python test_multi_asset_platform.py
```

Expected output:
```
✅ All tests passed!
Passed: 6/6
Failed: 0/6
```

### Step 4: Start API Server

```bash
# Start the multi-asset API server
python api_multi_asset.py
```

Server starts on: `http://localhost:8000`

### Step 5: Access API Documentation

Open your browser: `http://localhost:8000/api/docs`

You'll see the interactive Swagger UI with all available endpoints.

---

## 📊 Usage Examples

### Example 1: Register a New User

```bash
curl -X POST "http://localhost:8000/api/v2/register" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "trader@example.com",
    "password": "securepass123",
    "tier": "INVESTOR",
    "initial_capital": 1000.0
  }'
```

Response:
```json
{
  "access_token": "token_user_1",
  "token_type": "bearer",
  "user_id": "user_1",
  "tier": "INVESTOR"
}
```

### Example 2: Get Capital Allocation

```bash
curl -X GET "http://localhost:8000/api/v2/allocation" \
  -H "Authorization: Bearer token_user_1"
```

Response:
```json
{
  "crypto_pct": 50.0,
  "equity_pct": 50.0,
  "derivatives_pct": 0.0,
  "cash_pct": 0.0,
  "crypto_usd": 500.0,
  "equity_usd": 500.0,
  "derivatives_usd": 0.0,
  "cash_usd": 0.0
}
```

### Example 3: Get Trading Status

```bash
curl -X GET "http://localhost:8000/api/v2/status" \
  -H "Authorization: Bearer token_user_1"
```

Response shows:
- Current tier and capital
- Asset allocation breakdown
- Active positions count
- Risk status and limits
- Execution priority

### Example 4: Place a Trade

```bash
# Buy Apple stock
curl -X POST "http://localhost:8000/api/v2/trade" \
  -H "Authorization: Bearer token_user_1" \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "AAPL",
    "asset_class": "equity",
    "side": "buy",
    "size": 100.0,
    "order_type": "market"
  }'
```

Response:
```json
{
  "success": true,
  "message": "Trade submitted successfully",
  "risk_level": "safe",
  "routing": {
    "tier": "INVESTOR",
    "priority": "HIGH",
    "infrastructure": "priority"
  }
}
```

---

## 🎯 Subscription Tiers

Choose the tier that matches your capital:

| Tier | Capital Range | Monthly Fee | Execution Priority | Features |
|------|--------------|-------------|-------------------|----------|
| **STARTER** | $50-$99 | $19/mo | Normal | Copy trading focus |
| **SAVER** | $100-$249 | $49/mo | Normal | Capital protection |
| **INVESTOR** | $250-$999 | $99/mo | High | Crypto + Equity |
| **INCOME** | $1,000-$4,999 | $249/mo | High | Full AI |
| **LIVABLE** | $5,000-$24,999 | $499/mo | Very High | Pro AI |
| **BALLER** | $25,000+ | $999/mo | Ultra High | Custom AI |

### Tier Benefits

**INVESTOR and above get:**
- Multi-asset trading (crypto + stocks)
- Higher execution priority
- More concurrent positions
- Lower latency execution

**LIVABLE and above get:**
- Priority execution nodes
- Advanced AI strategies
- Higher position limits

**BALLER tier gets:**
- Dedicated servers
- Ultra-high priority execution
- All asset classes including derivatives (Phase 2)
- Custom strategy development

---

## 💰 Revenue Model

NIJA earns through 3 revenue streams:

### 1. Subscriptions
- Monthly or annual (20% discount)
- Tier-based pricing
- Recurring revenue

### 2. Performance Fees
- 10% of profits above high water mark
- Only charged on new profits
- Aligns incentives (platform wins when you win)

### 3. Copy Trading Fees
- 2% platform facilitation fee
- 5% goes to master trader
- 93% stays with follower

---

## 🔒 Security Features

- **User Isolation**: Each user has separate execution environment
- **API Key Encryption**: All broker keys encrypted at rest
- **Risk Limits**: Tier-based position and loss limits
- **Kill Switch**: Automatic trading halt on excessive losses
- **4-Gate Validation**: All trades pass through Capital → Drawdown → Volatility → Execution gates

---

## 📈 How It Works

### 1. Market Analysis
The platform continuously analyzes market conditions:
- Crypto volatility and momentum
- Equity market trends
- Overall market regime (trending, ranging, volatile, risk-off)

### 2. Capital Routing
Based on conditions, capital is automatically allocated:
- **High crypto volatility** → 90% crypto (scalping opportunities)
- **Low volatility** → 60% equity (stock momentum)
- **Risk-off** → 50% cash (capital preservation)

### 3. Strategy Selection
Each asset class has multiple strategies:
- **Crypto**: Momentum scalping, trend riding, volatility capture
- **Equity**: AI momentum, mean reversion, ETF rotation

### 4. Execution
Trades are routed based on your tier:
- Higher tiers get faster execution
- Priority infrastructure for premium users
- Automatic retry logic for failed orders

### 5. Risk Management
Every trade passes through 4 gates:
1. **Capital Guard**: Position size limits
2. **Drawdown Guard**: Daily loss caps
3. **Volatility Guard**: Market condition checks
4. **Execution Gate**: Final validation

If any gate rejects, trade is blocked.

---

## 🌐 Deployment

### Local Development
```bash
python api_multi_asset.py
```

### Railway Deployment
```bash
# Install Railway CLI
npm install -g @railway/cli

# Login
railway login

# Deploy
railway up
```

### Docker Deployment
```bash
# Build
docker build -t nija-multi-asset .

# Run
docker run -p 8000:8000 --env-file .env nija-multi-asset
```

---

## 📚 Documentation

- **Technical Blueprint**: `MULTI_ASSET_PLATFORM_BLUEPRINT.md`
- **API Docs**: `http://localhost:8000/api/docs`
- **Tests**: `test_multi_asset_platform.py`

---

## 🆘 Troubleshooting

### Tests Failing?
```bash
# Check Python version (need 3.11+)
python --version

# Reinstall dependencies
pip install -r requirements.txt --force-reinstall
```

### API Server Won't Start?
```bash
# Check if port is in use
lsof -i :8000

# Use different port
PORT=8001 python api_multi_asset.py
```

### Alpaca Integration Issues?
```bash
# Verify library installed
pip install alpaca-py

# Check API keys
echo $ALPACA_API_KEY
```

---

## 🚀 Next Steps

1. **Test locally** with paper trading accounts
2. **Start small** with STARTER or SAVER tier
3. **Monitor performance** via API endpoints
4. **Scale up** as you gain confidence
5. **Upgrade tier** for better execution priority

---

## 📞 Support

- **GitHub Issues**: [Report a bug](https://github.com/dantelrharrell-debug/Nija/issues)
- **API Documentation**: `/api/docs`
- **Technical Docs**: `MULTI_ASSET_PLATFORM_BLUEPRINT.md`

---

**Ready to trade? Let's go! 🚀**

```bash
python api_multi_asset.py
```
