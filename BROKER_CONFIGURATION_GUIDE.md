# Broker Configuration Guide

This guide explains how to configure and use the different broker integrations available in NIJA for scaling your trading operations.

## Overview

NIJA supports multiple brokers with different fee structures, capabilities, and optimal trading strategies:

| Broker | Fees (Round-Trip) | Asset Types | Strategy Focus | Min Balance |
|--------|------------------|-------------|----------------|-------------|
| **OKX** | 0.20% (lowest) | Crypto, Futures, Perpetuals | Bidirectional, High Frequency | $25 |
| **Binance** | 0.28% (very low) | Crypto, Futures | Bidirectional, High Volume | $25 |
| **Alpaca** | 0.20% (zero commissions) | Stocks, ETFs, Options | Aggressive, PDT-aware | $25 |
| **Kraken** | 0.36% (low) | Crypto, Futures | Bidirectional | $25 |
| **Coinbase** | 1.40% (high) | Crypto only | Buy-Focused | $10 |

## Broker Configurations

### OKX Exchange

**Best For**: Ultra-low fee crypto trading with futures/perpetuals

**Key Features**:
- Ultra-low fees: 0.08% taker, 0.06% maker (VIP tier)
- Round-trip cost: 0.20% (lowest in market)
- Supports: Crypto, Futures, Perpetual Swaps, Options
- Profit targets: 0.4%+ (very tight due to ultra-low fees)
- Stop loss: -0.5% (tightest of all brokers)
- Max positions: 15 (highest frequency trading)
- Max trades/day: 80 (highest volume)

**Configuration File**: `bot/broker_configs/okx_config.py`

**Environment Variables**:
```bash
OKX_API_KEY=your_api_key
OKX_API_SECRET=your_api_secret
OKX_PASSPHRASE=your_passphrase
OKX_USE_TESTNET=false  # Set to true for demo trading
```

**Symbol Format**: `BTC-USDT`, `ETH-USDT` (dash separator, USDT pairs)

**Trading Strategy**:
- Bidirectional (both long and short equally profitable)
- Very tight profit targets (0.4-0.8%)
- Aggressive position sizing (60% for small accounts)
- Highest trade frequency (80 trades/day)
- Ideal for scaling due to ultra-low fees

---

### Binance Exchange

**Best For**: High-volume crypto trading with excellent liquidity

**Key Features**:
- Low fees: 0.10% taker/maker (0.075% with BNB discount)
- Round-trip cost: 0.28% (very competitive)
- Supports: Crypto (1000+ pairs), Futures, Margin
- Profit targets: 0.5%+ (tight due to low fees)
- Stop loss: -0.6%
- Max positions: 12
- Max trades/day: 70

**Configuration File**: `bot/broker_configs/binance_config.py`

**Environment Variables**:
```bash
BINANCE_API_KEY=your_api_key
BINANCE_API_SECRET=your_api_secret
BINANCE_USE_TESTNET=false  # Set to true for demo trading
```

**Symbol Format**: `BTCUSDT`, `ETHUSDT` (no separator, USDT pairs)

**Trading Strategy**:
- Bidirectional (both directions profitable)
- Tight profit targets (0.5-0.9%)
- Aggressive position sizing (55% for small accounts)
- High trade frequency (70 trades/day)
- Best liquidity in crypto markets

---

### Alpaca Trading

**Best For**: Zero-commission US stock trading

**Key Features**:
- Zero commissions (only spread costs ~0.20%)
- Supports: US Stocks, ETFs, Options (premium tier)
- Profit targets: 0.3%+ (very tight due to zero fees)
- Stop loss: -0.4%
- Max positions: 10
- Max trades/day: 50
- **PDT Rule Enforcement**: Accounts under $25k limited to 3 day trades per 5 days
- **Market Hours Only**: 9:30 AM - 4:00 PM ET

**Configuration File**: `bot/broker_configs/alpaca_config.py`

**Environment Variables**:
```bash
ALPACA_API_KEY=your_api_key
ALPACA_API_SECRET=your_api_secret
ALPACA_PAPER=true  # Set to false for live trading

# For user accounts:
ALPACA_USER_TANIA_API_KEY=user_api_key
ALPACA_USER_TANIA_API_SECRET=user_api_secret
ALPACA_USER_TANIA_PAPER=true
```

**Symbol Format**: `AAPL`, `TSLA`, `SPY` (stock tickers)

**Trading Strategy**:
- Bidirectional (both long and short profitable)
- Very tight profit targets (0.3-0.6%)
- Aggressive position sizing (50% for small non-PDT accounts)
- PDT-aware position sizing (30% for PDT-restricted accounts)
- Only trades during market hours

**Important Notes**:
- Paper trading recommended for testing
- PDT rule applies to accounts under $25,000
- Market hours: 9:30 AM - 4:00 PM ET (no 24/7 trading)
- Fractional shares supported (minimum $1 positions)

---

### Kraken Pro

**Best For**: Low-fee bidirectional crypto trading

**Key Features**:
- Low fees: 0.16% taker, 0.10% maker
- Round-trip cost: 0.36%
- Supports: Crypto, Futures, Stocks (via Alpaca)
- Profit targets: 0.5%+
- Max positions: 12
- Already configured (see `bot/broker_configs/kraken_config.py`)

---

### Coinbase Advanced Trade

**Best For**: Quick crypto trades (higher fees, use selectively)

**Key Features**:
- Higher fees: 0.60% taker, 0.40% maker
- Round-trip cost: 1.40%
- Crypto only
- Buy-focused strategy (quick profit-taking)
- Already configured (see `bot/broker_configs/coinbase_config.py`)

---

## Broker Adapters

Broker adapters ensure that trade intents are validated and adjusted according to each broker's specific requirements:

### BinanceAdapter

Located in `bot/broker_adapters.py`

**Features**:
- Enforces $10 minimum notional
- Symbol normalization: `BTC-USD` → `BTCUSDT`
- Converts USD to USDT (Binance's primary quote currency)
- Fee-aware validation (0.28% round-trip)

### OKXAdapter

Located in `bot/broker_adapters.py`

**Features**:
- Enforces $10 minimum order size
- Symbol normalization: `BTC-USD` → `BTC-USDT`
- Dash separator format (`BTC-USDT`)
- Fee-aware validation (0.20% round-trip)
- Supports futures and perpetuals

### AlpacaAdapter

Located in `bot/broker_adapters.py`

**Features**:
- Enforces $1 minimum (fractional shares)
- PDT rule checking (accounts under $25k)
- Market hours validation
- Stock ticker normalization
- Zero commission awareness

---

## Using Multiple Brokers for Scaling

### Multi-Broker Strategy

NIJA supports independent trading across multiple brokers simultaneously:

```bash
# Enable multi-broker independent trading
MULTI_BROKER_INDEPENDENT=true
```

### Recommended Broker Allocation

For optimal scaling with diverse fee structures:

1. **Primary (70%)**: OKX + Binance (lowest fees, highest frequency)
2. **Secondary (20%)**: Kraken (low fees, good liquidity)
3. **Selective (10%)**: Coinbase (higher fees, use for specific pairs)
4. **Stocks**: Alpaca (zero commissions, separate from crypto)

### Capital Allocation Example

For a $1,000 account across multiple brokers:

```
OKX:      $400 (40%) - Ultra-low fees, high frequency
Binance:  $300 (30%) - Best liquidity, high volume
Kraken:   $200 (20%) - Low fees, reliable
Alpaca:   $100 (10%) - Stocks, zero commissions
```

---

## Testing Broker Configurations

### 1. Test Connection

All brokers support testnet/paper trading:

```bash
# OKX Testnet
OKX_USE_TESTNET=true

# Binance Testnet
BINANCE_USE_TESTNET=true

# Alpaca Paper Trading
ALPACA_PAPER=true
```

### 2. Verify Credentials

Run the bot with `LIVE_CAPITAL_VERIFIED=false` to test connections without trading:

```bash
LIVE_CAPITAL_VERIFIED=false
python bot.py
```

Check logs for connection confirmations:
- `✅ BINANCE CONNECTED (🧪 TESTNET)` or `✅ BINANCE CONNECTED (🔴 LIVE)`
- `✅ OKX CONNECTED (🧪 TESTNET)` or `✅ OKX CONNECTED (🔴 LIVE)`
- `✅ ALPACA CONNECTED (🧪 PAPER)` or `✅ ALPACA CONNECTED (🔴 LIVE)`

### 3. Test Small Positions

Start with minimum position sizes to verify order execution:

- OKX: $10 minimum
- Binance: $10 minimum
- Alpaca: $1 minimum (fractional shares)

---

## Broker Selection Logic

The trading strategy automatically selects the best broker for each trade based on:

1. **Fee Structure**: Lower fees = more aggressive trading
2. **Pair Availability**: Some pairs only available on specific brokers
3. **Account Balance**: PDT rules (Alpaca), minimum balances
4. **Asset Type**: Crypto (OKX/Binance/Kraken), Stocks (Alpaca)

Example from `bot/broker_configs/__init__.py`:

```python
from bot.broker_configs import get_broker_config

# Get broker-specific configuration
okx_config = get_broker_config('okx')
binance_config = get_broker_config('binance')
alpaca_config = get_broker_config('alpaca')

# Configurations include:
# - Profit targets
# - Stop loss levels
# - Position sizing rules
# - Fee structures
# - Max positions/trades
```

---

## API Credentials Setup

### OKX

1. Visit: https://www.okx.com/account/my-api
2. Create API key with permissions:
   - ✅ Read
   - ✅ Trade
   - ❌ Withdraw (never enable)
3. Save: API Key, API Secret, Passphrase
4. Add to `.env`:
   ```
   OKX_API_KEY=your_key
   OKX_API_SECRET=your_secret
   OKX_PASSPHRASE=your_passphrase
   ```

### Binance

1. Visit: https://www.binance.com/en/my/settings/api-management
2. Create API key with permissions:
   - ✅ Enable Reading
   - ✅ Enable Spot & Margin Trading
   - ❌ Enable Withdrawals (never enable)
3. Save: API Key, API Secret
4. Add to `.env`:
   ```
   BINANCE_API_KEY=your_key
   BINANCE_API_SECRET=your_secret
   ```

### Alpaca

1. Visit: https://alpaca.markets/
2. Create account and generate API keys
3. For testing, use Paper Trading keys first
4. Add to `.env`:
   ```
   ALPACA_API_KEY=your_key
   ALPACA_API_SECRET=your_secret
   ALPACA_PAPER=true
   ```

---

## Security Best Practices

1. **Never commit credentials** to version control
2. **Use testnet/paper trading** first
3. **Start with small amounts** ($10-25)
4. **Never enable withdrawal permissions** on API keys
5. **Use IP whitelisting** when available
6. **Rotate API keys** regularly
7. **Monitor for unusual activity**

---

## Troubleshooting

### Connection Failures

**OKX "Invalid Passphrase" Error**:
- Verify passphrase is not a placeholder value
- Check for extra spaces or newlines
- Ensure API key has trading permissions

**Binance 403 "Too Many Errors"**:
- API key temporarily blocked due to failed attempts
- Wait 5-10 minutes before retrying
- Verify API key and secret are correct

**Alpaca Paper Trading Not Working**:
- Ensure `ALPACA_PAPER=true` is set
- Use paper trading API keys, not live keys
- Check that keys are from https://alpaca.markets/

### Minimum Order Size Errors

Each broker has different minimums:
- OKX: $10
- Binance: $10
- Alpaca: $1
- Kraken: $10
- Coinbase: $25

Adjust position sizing in config files if needed.

### Symbol Format Issues

Different brokers use different symbol formats:
- **OKX**: `BTC-USDT` (dash separator)
- **Binance**: `BTCUSDT` (no separator)
- **Alpaca**: `AAPL` (stock ticker)
- **Kraken**: `BTCUSD` (no separator)
- **Coinbase**: `BTC-USD` (dash separator)

Adapters handle normalization automatically.

---

## Next Steps

1. **Set up credentials** for desired brokers in `.env`
2. **Test connections** using testnet/paper trading
3. **Start with small positions** ($10-25)
4. **Monitor performance** and adjust allocations
5. **Scale up** as you gain confidence

For more details, see:
- `bot/broker_configs/` - Individual broker configurations
- `bot/broker_adapters.py` - Broker-specific adapters
- `.env.example` - Environment variable templates
- `BROKER_INTEGRATION_GUIDE.md` - General integration guide
