# NIJA User Trading Activation Guide

## Overview

This guide explains how to enable NIJA to actively manage and sell positions for individual user accounts. Once configured, NIJA will automatically:

- ✅ Start independent trading thread for each user account
- ✅ Scan markets for trading opportunities
- ✅ Execute trades based on NIJA's signals
- ✅ Apply stop-loss to protect capital
- ✅ Close profitable positions automatically
- ✅ Manage take-profit targets

## Prerequisites

Before activating user trading, ensure you have:

1. **User configuration files** in `config/users/`
2. **API credentials** from your exchange (Kraken, Alpaca, or Coinbase)
3. **Funded trading account** (minimum $0.50, recommended $25+)
4. **Platform account configured** (recommended for optimal operation)

## Quick Start

### Step 1: Verify User Configuration

Check that user configuration files exist and have `enabled: true`:

```bash
# View current user configurations
cat config/users/daivon_frazier.json
cat config/users/tania_gilbert.json
```

Each file should contain:
```json
{
  "name": "User Name",
  "broker": "kraken",
  "role": "user",
  "enabled": true,
  "independent_trading": true,
  "risk_multiplier": 1.0,
  "disabled_symbols": ["XRP-USD"]
}
```

**Important**: `"independent_trading": true` means each user trades independently using NIJA's strategy logic - **NOT** copy trading from platform.

✅ **Critical**: `"enabled": true` must be set for trading to activate.

### Step 2: Configure API Credentials

Set environment variables for each user's API credentials:

```bash
# For Daivon Frazier (Kraken)
export KRAKEN_USER_DAIVON_API_KEY='your_api_key_here'
export KRAKEN_USER_DAIVON_API_SECRET='your_api_secret_here'

# For Tania Gilbert (Kraken)
export KRAKEN_USER_TANIA_API_KEY='your_api_key_here'
export KRAKEN_USER_TANIA_API_SECRET='your_api_secret_here'
```

**Or** add to `.env` file:
```bash
# Copy example and edit
cp .env.example .env

# Edit .env file and add credentials:
# KRAKEN_USER_DAIVON_API_KEY=your_api_key_here
# KRAKEN_USER_DAIVON_API_SECRET=your_api_secret_here
# KRAKEN_USER_TANIA_API_KEY=your_api_key_here
# KRAKEN_USER_TANIA_API_SECRET=your_api_secret_here
```

#### Getting API Credentials

**For Kraken:**
1. Go to https://www.kraken.com/u/security/api
2. Click "Generate New Key"
3. **Required Permissions** (check all):
   - ✅ Query Funds
   - ✅ Query Open Orders & Trades
   - ✅ Query Closed Orders & Trades
   - ✅ Create & Modify Orders
   - ✅ Cancel/Close Orders
   - ❌ Do NOT enable "Withdraw Funds"
4. Copy API Key and Private Key
5. Set as environment variables (see above)

**For Alpaca:**
1. Go to https://app.alpaca.markets/paper/dashboard/overview
2. Navigate to API Keys section
3. Generate new API key
4. Set `ALPACA_USER_{NAME}_API_KEY` and `ALPACA_USER_{NAME}_API_SECRET`

### Step 3: Configure Platform Account (Recommended)

For optimal operation, configure the platform account for the same exchange:

```bash
# Platform Kraken credentials
export KRAKEN_PLATFORM_API_KEY='platform_api_key'
export KRAKEN_PLATFORM_API_SECRET='platform_api_secret'
```

**Why Platform Account?**
- Provides cleaner startup flow
- Establishes proper connection order
- User accounts trade as secondary to platform
- Better error handling and logging

### Step 4: Verify Setup

Run the activation verification script:

```bash
python scripts/activate_user_trading.py
```

This script checks:
- ✅ User configuration files exist
- ✅ `enabled: true` is set
- ✅ API credentials are configured
- ✅ Platform broker is configured (warning if not)
- ℹ️  PRO_MODE status

**Expected Output (Success):**
```
======================================================================
🔍 NIJA USER TRADING ACTIVATION CHECK
======================================================================

Checking: Daivon Frazier (daivon_frazier)
----------------------------------------------------------------------
   ✅ Configuration: VALID
      Broker: kraken
      Enabled: True
   ✅ API Credentials: SET
   ✅ Platform KRAKEN: CONFIGURED

Checking: Tania Gilbert (tania_gilbert)
----------------------------------------------------------------------
   ✅ Configuration: VALID
      Broker: kraken
      Enabled: True
   ✅ API Credentials: SET
   ✅ Platform KRAKEN: CONFIGURED

======================================================================
SUMMARY
======================================================================
✅ ALL CHECKS PASSED

User accounts ready for independent trading:
   • Daivon Frazier
   • Tania Gilbert

NIJA will automatically:
   ✅ Start independent trading thread for each user
   ✅ Scan markets for opportunities
   ✅ Execute trades based on signals
   ✅ Manage stop-loss and take-profit
   ✅ Close profitable positions

🚀 Start NIJA with: ./start.sh or python bot.py
```

### Step 5: Start NIJA

Once verification passes, start NIJA:

```bash
./start.sh
```

Or:
```bash
python bot.py
```

## Expected Behavior

When NIJA starts with user accounts configured, you'll see:

```
======================================================================
👤 CONNECTING USERS FROM CONFIG FILES
======================================================================
ℹ️  Users are SECONDARY accounts - Platform accounts have priority
======================================================================

📊 Connecting Daivon Frazier (daivon_frazier) to Kraken...
   ✅ Platform KRAKEN is connected (correct priority)
   ✅ Daivon Frazier connected to Kraken
   💰 Daivon Frazier balance: $150.00

📊 Connecting Tania Gilbert (tania_gilbert) to Kraken...
   ✅ Platform KRAKEN is connected (correct priority)
   ✅ Tania Gilbert connected to Kraken
   💰 Tania Gilbert balance: $200.00

======================================================================
👤 STARTING USER BROKER THREADS
======================================================================

   🚀 TRADING THREAD STARTED for daivon_frazier_kraken (USER)
   📊 Thread name: Trader-daivon_frazier_kraken

   🚀 TRADING THREAD STARTED for tania_gilbert_kraken (USER)
   📊 Thread name: Trader-tania_gilbert_kraken

======================================================================
📊 INDEPENDENT MULTI-BROKER TRADING STARTED
======================================================================
   Platform threads: 1
   User threads: 2
   Total capital under management: $850.00
======================================================================
```

## Trading Logic (Independent - NO Copy Trading)

**CRITICAL**: NIJA trades **INDEPENDENTLY** for each user account. This means:
- ❌ **NO copy trading** from platform account
- ✅ Each user account makes its own trading decisions
- ✅ All accounts use the same NIJA APEX v7.1 strategy
- ✅ Same signals, same logic, but executed independently per account

Each user account operates with:

### 1. Independent Threads
- Each user has their own trading thread
- Threads run every 2.5 minutes (150 seconds)
- **Independent of platform and other users** (no trade copying)
- Isolated error handling (one user's error doesn't affect others)

### 2. Trading Signals
- Same NIJA APEX v7.1 strategy
- Dual RSI indicators (RSI_9 + RSI_14)
- Volatility filters (ATR-based)
- Confidence scoring system

### 3. Risk Management
- **Stop-Loss**: Automatically applied to protect capital
- **Take-Profit**: Dynamic targets based on volatility
- **Position Sizing**: Scaled by account balance
- **Maximum Positions**: 8 concurrent positions per account

### 4. Automated Position Management
- **Entry**: Executes when signals meet confidence threshold
- **Monitoring**: Tracks all open positions continuously
- **Exit Triggers**:
  - Stop-loss hit (protect capital)
  - Take-profit reached (lock in gains)
  - Signal reversal (market conditions changed)
  - Time-based exits (if stagnant)

## Optional: PRO_MODE

Enable advanced position scaling for multiple positions:

```bash
export PRO_MODE=true
```

**PRO_MODE enables:**
- Multiple concurrent positions per account
- Advanced scaling algorithms
- Optimized capital allocation
- Higher throughput capacity

**Recommendation**: Start without PRO_MODE, enable after observing successful trading.

## Troubleshooting

### Issue: "No funded brokers detected (platform or user)"

**Cause**: Account balance is below minimum threshold ($0.50)

**Solution**:
1. Verify account has funds
2. Check balance with: `python scripts/show_user_balances.py`
3. Add funds to account if below minimum
4. Restart NIJA

### Issue: "User not connected - credentials missing"

**Cause**: API credentials not set in environment

**Solution**:
1. Verify environment variables are set:
   ```bash
   echo $KRAKEN_USER_DAIVON_API_KEY
   echo $KRAKEN_USER_DAIVON_API_SECRET
   ```
2. If empty, set credentials (see Step 2)
3. Restart NIJA

### Issue: "User broker connection failed"

**Cause**: Invalid API credentials or insufficient permissions

**Solution**:
1. Verify API key has correct permissions (see Step 2)
2. Test credentials manually in exchange web interface
3. Regenerate API keys if needed
4. Update environment variables
5. Restart NIJA

### Issue: "Platform broker not connected - user will be primary"

**Cause**: Platform account credentials not configured

**Impact**: User accounts will trade independently (works but not optimal)

**Solution (Recommended)**:
1. Configure platform credentials:
   ```bash
   export KRAKEN_PLATFORM_API_KEY='...'
   export KRAKEN_PLATFORM_API_SECRET='...'
   ```
2. Restart NIJA
3. Platform will establish connection first
4. User accounts will connect as secondary

### Issue: User trading thread not starting

**Debugging Steps**:
1. Run activation checker:
   ```bash
   python scripts/activate_user_trading.py
   ```
2. Check logs for specific error messages
3. Verify `enabled: true` in config file
4. Confirm API credentials are valid
5. Ensure account is funded (≥ $0.50)

## Monitoring

### Check Trading Thread Status

Look for these log messages during startup:

```
🚀 TRADING THREAD STARTED for {user_id}_{broker} (USER)
📊 Thread name: Trader-{user_id}_{broker}
🔄 This thread will:
   • Scan markets every 2.5 minutes
   • Execute USER trades when signals trigger
   • Manage existing positions
```

### View Active Positions

Each trading cycle logs position status:

```
👤 USER ACCOUNT: daivon_frazier
   Balance: $150.00
   Open Positions: 2
   Available: $120.00
```

### Monitor Position Closures

When positions are closed (profit-taking or stop-loss):

```
💰 PROFIT TAKEN: ETH-USD
   Entry: $2,450.00
   Exit: $2,520.00
   P&L: +$15.50 (+2.86%)
   User: daivon_frazier
```

## Architecture

### Independent Trading Model

```
┌─────────────────────────────────────────────────────┐
│              NIJA Trading Bot                       │
├─────────────────────────────────────────────────────┤
│                                                     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────┐ │
│  │ Platform     │  │ User Thread  │  │ User     │ │
│  │ Thread       │  │ (Daivon)     │  │ Thread   │ │
│  │ (Kraken)     │  │              │  │ (Tania)  │ │
│  └──────────────┘  └──────────────┘  └──────────┘ │
│       ↓                  ↓                 ↓       │
│  ┌──────────┐      ┌──────────┐      ┌──────────┐ │
│  │ Platform │      │ Daivon's │      │ Tania's  │ │
│  │ Kraken   │      │ Kraken   │      │ Kraken   │ │
│  │ Account  │      │ Account  │      │ Account  │ │
│  └──────────┘      └──────────┘      └──────────┘ │
│                                                     │
└─────────────────────────────────────────────────────┘
```

**Key Principles:**
1. **Complete Isolation**: Each account trades independently
2. **No Cross-Contamination**: One account's errors don't affect others
3. **Separate Balances**: Each account uses its own capital
4. **Independent Positions**: No position sharing or mirroring
5. **Same Strategy**: All accounts use NIJA APEX v7.1 logic

## Configuration Reference

### User Config File Schema

Location: `config/users/{user_id}.json`

```json
{
  "name": "Display Name",           // Human-readable name
  "broker": "kraken",                // Exchange: kraken, alpaca, coinbase
  "role": "user",                    // Role: user, platform
  "enabled": true,                   // Enable/disable trading
  "independent_trading": true,       // Independent trading (NOT copy trading)
  "risk_multiplier": 1.0,            // Risk scaling factor
  "disabled_symbols": ["XRP-USD"]    // Symbols to avoid
}
```

**Field Descriptions:**
- `independent_trading: true` - Each user trades independently using NIJA strategy (no copy trading)
- `enabled: true` - Must be true for trading thread to start
- `risk_multiplier` - Scales position sizes (1.0 = standard, 0.5 = half size, 2.0 = double)
- `disabled_symbols` - List of trading pairs to avoid

### Environment Variables

Format: `{BROKER}_USER_{FIRSTNAME}_API_{KEY|SECRET}`

**Examples:**
```bash
# Kraken
KRAKEN_USER_DAIVON_API_KEY
KRAKEN_USER_DAIVON_API_SECRET
KRAKEN_USER_TANIA_API_KEY
KRAKEN_USER_TANIA_API_SECRET

# Alpaca
ALPACA_USER_JOHN_API_KEY
ALPACA_USER_JOHN_API_SECRET
```

**Extraction Rules:**
- `user_id: "daivon_frazier"` → `DAIVON` (first name, uppercase)
- `user_id: "tania_gilbert"` → `TANIA` (first name, uppercase)

### PRO_MODE Configuration

```bash
# Enable advanced features
export PRO_MODE=true

# Or in .env file
PRO_MODE=true
```

## Safety Features

### Built-in Protections

1. **Minimum Balance Check**: Accounts below $0.50 won't trade
2. **Stop-Loss**: Every position has automatic stop-loss
3. **Take-Profit**: Dynamic profit targets
4. **Position Limits**: Maximum 8 positions per account
5. **Error Isolation**: Thread failures don't cascade
6. **Credential Validation**: Invalid credentials prevent startup

### Risk Controls

Each account respects:
- **Position Size Limits**: Based on account balance
- **Volatility Filters**: Only trade suitable market conditions
- **Confidence Thresholds**: Minimum signal quality required
- **Symbol Blacklist**: Respect `disabled_symbols` configuration

## Adding New Users

To add additional user accounts:

### 1. Create Configuration File

```bash
# Create new user config
cat > config/users/john_smith.json << EOF
{
  "name": "John Smith",
  "broker": "kraken",
  "role": "user",
  "enabled": true,
  "independent_trading": true,
  "risk_multiplier": 1.0,
  "disabled_symbols": []
}
EOF
```

### 2. Set API Credentials

```bash
# Add to .env
export KRAKEN_USER_JOHN_API_KEY='john_api_key'
export KRAKEN_USER_JOHN_API_SECRET='john_api_secret'
```

### 3. Verify and Start

```bash
# Verify configuration
python scripts/activate_user_trading.py

# Start NIJA
./start.sh
```

The new user will automatically get an independent trading thread.

## Summary

✅ **What NIJA Will Do Automatically:**
1. Load user configurations from `config/users/`
2. Connect to each user's exchange account
3. Start independent trading thread per user
4. Scan markets every 2.5 minutes
5. Execute trades based on signals
6. Apply stop-loss and take-profit
7. Close positions when targets are hit
8. Manage all positions independently

⚙️ **What You Need to Do:**
1. Set API credentials in environment variables
2. Ensure user configs have `enabled: true`
3. Fund accounts (minimum $0.50, recommended $25+)
4. Run activation checker to verify
5. Start NIJA: `./start.sh`

🎯 **Result:**
NIJA will actively manage and sell positions for each configured user account, automatically applying all risk management rules and profit-taking logic.

## Support

For additional help:
- Review logs in startup output
- Run diagnostic: `python scripts/activate_user_trading.py`
- Check documentation: `README.md`, `GETTING_STARTED.md`
- Verify API permissions match requirements

## Related Documentation

- `GETTING_STARTED.md` - General setup guide
- `APEX_V71_DOCUMENTATION.md` - Strategy details
- `BROKER_INTEGRATION_GUIDE.md` - Exchange integration
- `MULTI_USER_PLATFORM_ARCHITECTURE.md` - Architecture overview
- `PLATFORM_ONLY_GUIDE.md` - Platform account setup
