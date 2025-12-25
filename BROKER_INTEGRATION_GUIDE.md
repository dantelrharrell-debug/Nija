# NIJA Apex Strategy v7.1 - Broker Integration Guide

## 🔌 Overview

This guide explains how to integrate NIJA Apex Strategy v7.1 with various broker APIs. The strategy provides a unified interface that abstracts broker-specific details, making it easy to switch between exchanges or trade on multiple platforms simultaneously.

---

## 🏗️ Architecture

```
┌─────────────────────────────────────┐
│   NIJA Apex Strategy v7.1           │
│   (Trading Logic & Risk Management) │
└──────────────┬──────────────────────┘
               │
               │ Unified Interface
               │
       ┌───────┴────────┐
       │                │
       ▼                ▼
┌──────────────┐  ┌──────────────┐
│   Coinbase   │  │   Binance    │
│   Adapter    │  │   Adapter    │
└──────────────┘  └──────────────┘
       │                │
       ▼                ▼
┌──────────────┐  ┌──────────────┐
│  Coinbase    │  │   Binance    │
│  API         │  │   API        │
└──────────────┘  └──────────────┘
```

---

## 📦 Broker Interface

All broker adapters implement the `BrokerInterface` abstract class defined in `broker_integration.py`:

```python
from broker_integration import BrokerInterface

class MyBrokerAdapter(BrokerInterface):
    def connect(self) -> bool:
        """Establish connection to broker API."""
        pass
    
    def get_account_balance(self) -> Dict[str, float]:
        """Get account balance."""
        pass
    
    def get_market_data(self, symbol: str, timeframe: str, limit: int):
        """Get OHLCV candles."""
        pass
    
    def place_market_order(self, symbol: str, side: str, size: float):
        """Place market order."""
        pass
    
    # ... other required methods
```

---

## 🟢 Coinbase Advanced Trade Integration

### Setup

1. **Get API Credentials:**
   - Log in to [Coinbase Advanced Trade](https://www.coinbase.com/advanced-trade)
   - Go to Settings → API
   - Create new API key with trading permissions
   - Save: API Key, API Secret, and download PEM file

2. **Configure Environment Variables:**
```bash
export COINBASE_API_KEY="your_api_key"
export COINBASE_API_SECRET="your_api_secret"
export COINBASE_PEM_CONTENT="$(cat cdp_api_key.pem | base64)"

# Optional: Select specific portfolio
export COINBASE_RETAIL_PORTFOLIO_ID="<portfolio_uuid>"

# Optional: Include consumer USD accounts (default: false)
export ALLOW_CONSUMER_USD="true"
```

3. **Install Required Packages:**
```bash
pip install coinbase-advanced-py
```

### Portfolio Selection & Balance Detection

**Finding Your Portfolios:**

Use the provided CLI tool to scan your portfolios and find where your funds are located:

```bash
python find_usd_portfolio.py
```

This will display:
- All portfolios with their UUIDs and types
- USD/USDC balances in each portfolio
- Which portfolio is currently selected (if override is set)
- Whether consumer USD is being included or excluded

**Portfolio Override:**

By default, NIJA scans all portfolios. To use a specific portfolio, set:

```bash
export COINBASE_RETAIL_PORTFOLIO_ID="<uuid-from-scanner>"
```

**Consumer USD Accounts:**

By default, USD accounts on the consumer platform are excluded from the trading balance (only Advanced Trade and Spot portfolios are counted). To include consumer USD:

```bash
export ALLOW_CONSUMER_USD="true"
```

This is useful if you have funds in a retail/consumer portfolio and want to use them for trading.

### Example Usage

```python
from broker_integration import BrokerFactory

# Create Coinbase adapter
broker = BrokerFactory.create_broker('coinbase')

# Connect
if broker.connect():
    print("Connected to Coinbase!")
    
    # Get balance
    balance = broker.get_account_balance()
    print(f"Balance: ${balance['available_balance']:.2f}")
    
    # Get market data
    market_data = broker.get_market_data('BTC-USD', '5m', 100)
    
    # Place order
    order = broker.place_market_order('BTC-USD', 'buy', 100.0)
    print(f"Order placed: {order['order_id']}")
```

### Connecting to Existing NIJA Infrastructure

The NIJA bot already has Coinbase integration in `broker_manager.py`. To use it with Apex Strategy:

```python
# In your integration script
from broker_manager import BrokerManager

# Get existing broker instance
existing_broker = BrokerManager()

# Adapt to Apex interface
class CoinbaseApexAdapter(CoinbaseBrokerAdapter):
    def __init__(self, broker_manager):
        self.broker = broker_manager
    
    def get_account_balance(self):
        balance = self.broker.get_usd_balance()
        return {
            'total_balance': balance,
            'available_balance': balance,
            'currency': 'USD'
        }
    
    # Implement other methods using broker_manager...

# Use with Apex Strategy
adapter = CoinbaseApexAdapter(existing_broker)
```

---

## 🟡 Binance Integration (Future)

### Setup

1. **Get API Credentials:**
   - Log in to [Binance](https://www.binance.com)
   - Go to API Management
   - Create API key with spot/futures trading enabled
   - Save API Key and Secret Key

2. **Configure Environment Variables:**
```bash
export BINANCE_API_KEY="your_api_key"
export BINANCE_API_SECRET="your_secret_key"
```

3. **Install Required Packages:**
```bash
pip install python-binance
```

### Example Usage (When Implemented)

```python
from broker_integration import BrokerFactory

# Create Binance adapter
broker = BrokerFactory.create_broker('binance', testnet=False)

# Connect
broker.connect()

# Get balance
balance = broker.get_account_balance()

# Get market data (Binance uses different symbol format)
market_data = broker.get_market_data('BTCUSDT', '5m', 100)

# Place order
order = broker.place_market_order('BTCUSDT', 'buy', 100.0)
```

### Implementation Checklist

- [ ] Implement `BinanceBrokerAdapter.connect()`
- [ ] Implement balance fetching
- [ ] Implement candle data retrieval
- [ ] Implement order placement
- [ ] Add error handling and retries
- [ ] Add rate limiting
- [ ] Test on testnet
- [ ] Test on mainnet with small amounts

---

## 🔵 Alpaca Integration (Future - Stocks/Crypto)

### Setup

1. **Get API Credentials:**
   - Sign up at [Alpaca](https://alpaca.markets)
   - Go to Dashboard → API Keys
   - Create API key (paper or live)
   - Save API Key ID and Secret Key

2. **Configure Environment Variables:**
```bash
export ALPACA_API_KEY="your_api_key_id"
export ALPACA_API_SECRET="your_secret_key"
```

3. **Install Required Packages:**
```bash
pip install alpaca-py
```

### Example Usage (When Implemented)

```python
from broker_integration import BrokerFactory

# Create Alpaca adapter (paper trading)
broker = BrokerFactory.create_broker('alpaca', paper=True)

# Connect
broker.connect()

# Get balance
balance = broker.get_account_balance()

# Get market data
market_data = broker.get_market_data('AAPL', '5m', 100)

# Place order
order = broker.place_market_order('AAPL', 'buy', 100.0)
```

---

## 🔄 Multi-Broker Trading

Trade on multiple exchanges simultaneously:

```python
from broker_integration import BrokerFactory
from nija_apex_strategy import NijaApexStrategyV71

# Initialize brokers
coinbase = BrokerFactory.create_broker('coinbase')
binance = BrokerFactory.create_broker('binance')

brokers = {
    'coinbase': {'broker': coinbase, 'pairs': ['BTC-USD', 'ETH-USD']},
    'binance': {'broker': binance, 'pairs': ['BTCUSDT', 'ETHUSDT']}
}

# Get total balance across all brokers
total_balance = sum(
    b['broker'].get_account_balance()['available_balance']
    for b in brokers.values()
)

# Initialize strategy with combined balance
strategy = NijaApexStrategyV71(account_balance=total_balance)

# Scan each broker's pairs
for broker_name, broker_info in brokers.items():
    broker = broker_info['broker']
    
    for symbol in broker_info['pairs']:
        # Get market data
        market_data = broker.get_market_data(symbol, '5m', 100)
        df = convert_to_dataframe(market_data)
        
        # Check for signals
        should_enter, trade_plan = strategy.should_enter_trade(df)
        
        if should_enter:
            # Execute on specific broker
            broker.place_market_order(
                symbol=symbol,
                side='buy' if trade_plan['signal'] == 'long' else 'sell',
                size=trade_plan['position_size_usd']
            )
```

---

## 🛡️ Best Practices

### 1. **Error Handling**

```python
import logging
from requests.exceptions import RequestException

logger = logging.getLogger(__name__)

def safe_api_call(func):
    """Decorator for safe API calls with retry logic."""
    def wrapper(*args, **kwargs):
        max_retries = 3
        for attempt in range(max_retries):
            try:
                return func(*args, **kwargs)
            except RequestException as e:
                logger.warning(f"API call failed (attempt {attempt+1}/{max_retries}): {e}")
                if attempt == max_retries - 1:
                    raise
                time.sleep(2 ** attempt)  # Exponential backoff
    return wrapper

class MyBrokerAdapter(BrokerInterface):
    @safe_api_call
    def get_account_balance(self):
        # API call here
        pass
```

### 2. **Rate Limiting**

```python
import time
from functools import wraps

class RateLimiter:
    def __init__(self, calls_per_second=10):
        self.calls_per_second = calls_per_second
        self.last_call = 0
    
    def wait_if_needed(self):
        now = time.time()
        time_since_last = now - self.last_call
        min_interval = 1.0 / self.calls_per_second
        
        if time_since_last < min_interval:
            time.sleep(min_interval - time_since_last)
        
        self.last_call = time.time()

# Use in broker adapter
class MyBrokerAdapter(BrokerInterface):
    def __init__(self):
        self.rate_limiter = RateLimiter(calls_per_second=10)
    
    def place_market_order(self, *args, **kwargs):
        self.rate_limiter.wait_if_needed()
        # Place order
```

### 3. **Logging All Trades**

```python
import json
from datetime import datetime

class TradeLogger:
    def __init__(self, log_file='trades.log'):
        self.log_file = log_file
    
    def log_trade(self, broker, symbol, side, size, price, order_id):
        trade_data = {
            'timestamp': datetime.utcnow().isoformat(),
            'broker': broker,
            'symbol': symbol,
            'side': side,
            'size': size,
            'price': price,
            'order_id': order_id
        }
        
        with open(self.log_file, 'a') as f:
            f.write(json.dumps(trade_data) + '\n')

# Use in integration
trade_logger = TradeLogger()
order = broker.place_market_order('BTC-USD', 'buy', 100.0)
trade_logger.log_trade('coinbase', 'BTC-USD', 'buy', 100.0, order['filled_price'], order['order_id'])
```

### 4. **Position Synchronization**

Keep track of positions across all brokers:

```python
class PositionManager:
    def __init__(self):
        self.positions = {}
    
    def sync_positions(self, brokers):
        """Sync positions from all brokers."""
        for broker_name, broker in brokers.items():
            positions = broker.get_open_positions()
            self.positions[broker_name] = positions
    
    def get_total_exposure(self):
        """Get total USD exposure across all brokers."""
        total = 0
        for broker_positions in self.positions.values():
            for pos in broker_positions:
                total += pos['size'] * pos['entry_price']
        return total
```

---

## 🔒 Security Checklist

- [ ] Never hardcode API keys in source code
- [ ] Use environment variables for all credentials
- [ ] Enable IP whitelisting on exchange APIs
- [ ] Set API permissions to minimum required (trade only, no withdrawals)
- [ ] Use separate API keys for testing and production
- [ ] Rotate API keys regularly
- [ ] Monitor API key usage for suspicious activity
- [ ] Store PEM files securely (encrypted at rest)
- [ ] Use `.gitignore` to prevent accidental commits of secrets
- [ ] Enable 2FA on exchange accounts
- [ ] Use paper/testnet for development and testing

---

## 📊 Testing Strategy

### 1. **Paper Trading First**

Always test on paper/testnet before live trading:

```python
# Binance testnet
broker = BrokerFactory.create_broker('binance', testnet=True)

# Alpaca paper
broker = BrokerFactory.create_broker('alpaca', paper=True)
```

### 2. **Start Small**

Begin live trading with minimal capital:

```python
# Limit position sizes during testing phase
config = {
    'max_position_size': 0.01,  # 1% max position
    'base_position_size': 0.005,  # 0.5% base
}

strategy = NijaApexStrategyV71(
    account_balance=100.0,  # Start with $100
    config=config
)
```

### 3. **Monitor Closely**

Set up alerts and monitoring:

```python
import smtplib

def send_alert(message):
    """Send email/SMS alert on important events."""
    # Implementation here
    pass

# Alert on every trade
if should_enter:
    send_alert(f"Trade signal: {trade_plan['signal']} {symbol}")
    execute_trade(trade_plan)
```

---

## 🚀 Production Deployment

### Recommended Stack

1. **Hosting:** Cloud VPS (AWS, DigitalOcean, Railway)
2. **Process Manager:** systemd or supervisord
3. **Monitoring:** Prometheus + Grafana
4. **Logging:** ELK Stack or CloudWatch
5. **Alerting:** PagerDuty, Telegram, Email

### Example systemd Service

```ini
[Unit]
Description=NIJA Apex Strategy v7.1
After=network.target

[Service]
Type=simple
User=nija
WorkingDirectory=/opt/nija
EnvironmentFile=/opt/nija/.env
ExecStart=/usr/bin/python3 /opt/nija/example_apex_integration.py --mode continuous
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

---

## 📚 Additional Resources

- [Coinbase Advanced Trade API Docs](https://docs.cloud.coinbase.com/advanced-trade-api/docs)
- [Binance API Docs](https://binance-docs.github.io/apidocs/)
- [Alpaca API Docs](https://alpaca.markets/docs/)

---

**Last Updated:** December 12, 2025  
**Version:** 7.1
