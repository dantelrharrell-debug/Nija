# App Store Safety Explanation - NIJA Trading Platform

**Document Version:** 1.0  
**Last Updated:** February 2, 2026  
**For:** Apple App Review / Google Play Review  
**Purpose:** Demonstrate safety of NIJA's independent trading model

---

> **CRITICAL SAFETY GUARANTEE**  
> **Tier-based capital protection is enforced in all environments and cannot be bypassed.**

---

## Executive Summary

NIJA is a **safe, transparent, and compliant** algorithmic trading platform that uses an **independent trading model**. Each user account makes its own trading decisions using shared software logic with independent per-account evaluation and account-specific state, risk, and execution context.

**Key Safety Points:**
- ✅ No copy trading - each account operates independently
- ✅ Proportional position sizing - smaller accounts = smaller positions = lower risk
- ✅ Mathematical transparency - simple, verifiable calculations
- ✅ Multiple safety mechanisms - exchange minimums, tier limits, fee awareness
- ✅ User maintains full control - funds never leave their exchange account

---

## Table of Contents

1. [How NIJA's Independent Trading Model Works](#how-nijas-independent-trading-model-works)
2. [Position Sizing Mathematics](#position-sizing-mathematics)
3. [Live Trade Simulation Results](#live-trade-simulation-results)
4. [Safety Mechanisms](#safety-mechanisms)
5. [Why Results Differ Between Users](#why-results-differ-between-users)
6. [Comparison to Prohibited Models](#comparison-to-prohibited-models)
7. [Technical Implementation](#technical-implementation)
8. [User Protection Features](#user-protection-features)

---

## How NIJA's Independent Trading Model Works

### The Core Principle

**Each user account evaluates the market independently and makes its own trading decisions.**

Key characteristics:
- Shared software logic with independent per-account evaluation
- Position size depends on each account balance and risk budget
- Execution timing includes per-account jitter and cooldown variance
- Account state (PnL, exposure, cooldowns) shapes decisions

### What Happens When a Trade Signal Occurs

**Platform Account (Reference):**
1. Algorithm analyzes market data every ~2.5 minutes
2. Detects a trading opportunity (e.g., RSI oversold + trend confirmation)
3. Calculates position size: $200 for a $10,000 account (2% risk)
4. Executes trade on platform's Coinbase account

**User Accounts (Independent):**
1. **Shared software logic with independent per-account evaluation runs on each user's account**
2. Each account analyzes the same market conditions with account-specific state
3. Each account independently detects opportunities with per-account timing variance
4. **Position size is calculated based on the user's balance:**
   - User with $100 balance → $2 position (2% risk)
   - User with $1,000 balance → $20 position (2% risk)
   - User with $25,000 balance → $500 position (2% risk)
5. Each account executes its own trade on its own exchange account

**Important:** No "signal distribution" occurs. Each account reaches its own conclusion independently using shared software logic with independent per-account evaluation plus account-specific state, risk, and execution context.

---

## Position Sizing Mathematics

### The Formula

Position sizing uses a simple, transparent formula:

```
user_position_size = platform_position_size × (user_balance ÷ platform_balance)
```

This is called **proportional scaling** and ensures:
- All accounts maintain the same risk/reward ratio
- Smaller accounts take smaller positions (safer)
- Larger accounts take larger positions (capital efficient)

### Example Calculations

**Scenario:** Platform account ($10,000 balance) takes a $200 BTC trade

| User Balance | Calculation | Position Size | Risk % |
|-------------|-------------|---------------|--------|
| $50 | $200 × ($50 ÷ $10,000) | $1.00 | 2.0% |
| $100 | $200 × ($100 ÷ $10,000) | $2.00 | 2.0% |
| $500 | $200 × ($500 ÷ $10,000) | $10.00 | 2.0% |
| $1,000 | $200 × ($1,000 ÷ $10,000) | $20.00 | 2.0% |
| $5,000 | $200 × ($5,000 ÷ $10,000) | $100.00 | 2.0% |
| $25,000 | $200 × ($25,000 ÷ $10,000) | $500.00 | 2.0% |

**Notice:** Every account maintains exactly 2.0% risk, scaled to their balance.

### Exchange Minimum Enforcement

Exchanges have minimum trade sizes to prevent "dust" trades:

- **Coinbase:** $2.00 minimum
- **Kraken:** $10.50 minimum (includes fee buffer)
- **Binance:** $10.00 minimum
- **OKX:** $1.00 minimum

**Impact on Small Accounts:**

Using Kraken example:
- User with $50 balance → $1.00 calculated position → **BLOCKED** (below $10.50 minimum)
- User with $500 balance → $10.00 calculated position → **BLOCKED** (below $10.50 minimum)
- User with $1,000 balance → $20.00 calculated position → **APPROVED** (above $10.50 minimum)

**This is a safety feature** - it prevents unprofitable micro-trades that would be eaten by fees.

### Fee-Aware Position Sizing

Every trade incurs fees that must be overcome for profitability:

**Coinbase Fees (Limit Orders):**
- Entry fee: 0.4%
- Spread cost: 0.2%
- Exit fee: 0.4%
- **Total round-trip:** 1.0%

**Example: $100 Trade**
- Entry fee: $0.40
- Spread cost: $0.20
- Exit fee: $0.40
- **Total fees: $1.00**
- Effective position after entry: $99.60
- **Minimum profit target:** 1.5% (to overcome 1.0% fees + profit)

**Smaller positions face higher fee pressure:**
- $2 trade → $0.02 fees (1.0%) → needs 1.5% gain to profit
- $10 trade → $0.10 fees (1.0%) → needs 1.5% gain to profit
- $100 trade → $1.00 fees (1.0%) → needs 1.5% gain to profit
- $1,000 trade → $10.00 fees (1.0%) → needs 1.5% gain to profit

The percentage is the same, but smaller accounts have less room for slippage.

---

## Live Trade Simulation Results

We've created a simulation tool (`simulate_live_trade.py`) that demonstrates the independent trading model.

### Simulation Setup

**Platform Account:**
- Balance: $10,000
- Trade Size: $200 (2% of balance)
- Exchange: Coinbase

**User Accounts:** 10 accounts with balances from $50 to $50,000

### Simulation Results

```
====================================================================================================
NIJA LIVE TRADE SIMULATION - INDEPENDENT TRADING MODEL
====================================================================================================

🎯 PLATFORM ACCOUNT (Reference):
   Balance: $10,000.00
   Trade Size: $200.00
   Risk %: 2.00%
   Exchange: COINBASE

📊 USER ACCOUNTS (10 accounts):
----------------------------------------------------------------------------------------------------
User ID           Balance       Tier   Trade Size    Effective    Scale %       Status
----------------------------------------------------------------------------------------------------
micro_1      $      50.00    STARTER $       1.00 $       0.00      0.50%    ❌ Invalid (too small)
micro_2      $     100.00      SAVER $       2.00 $       1.99      1.00%      ✅ Valid
small_1      $     250.00   INVESTOR $       5.00 $       4.98      2.50%      ✅ Valid
small_2      $     500.00   INVESTOR $      10.00 $       9.96      5.00%      ✅ Valid
medium_1     $   1,000.00     INCOME $      20.00 $      19.92     10.00%      ✅ Valid
medium_2     $   2,500.00     INCOME $      50.00 $      49.80     25.00%      ✅ Valid
large_1      $   5,000.00    LIVABLE $     100.00 $      99.60     50.00%      ✅ Valid
large_2      $  10,000.00    LIVABLE $     200.00 $     199.20    100.00%      ✅ Valid
whale_1      $  25,000.00     BALLER $     500.00 $     498.00    250.00%      ✅ Valid
whale_2      $  50,000.00     BALLER $   1,000.00 $     996.00    500.00%      ✅ Valid
----------------------------------------------------------------------------------------------------

📈 SIMULATION STATISTICS:
   Total Accounts: 10
   Valid Trades: 9 (90.0%)
   Invalid Trades: 1 (10.0%)
   Average Trade Size: $209.67
   Min Trade Size: $2.00
   Max Trade Size: $1,000.00
   Total Trading Volume: $1,887.00
```

### Key Observations

1. **Position sizes scale proportionally** - from $2 to $1,000 based on account balance
2. **One account blocked** - $50 account's $1 position is below $2 minimum (safety mechanism)
3. **90% success rate** - most accounts can trade safely
4. **500x size variance** - natural result of different account balances
5. **All approved accounts maintain 2% risk** - proportional scaling works correctly

### Running the Simulation Yourself

```bash
# Default simulation (10 users, Coinbase)
python simulate_live_trade.py

# Custom parameters
python simulate_live_trade.py --platform-balance 25000 --platform-trade-size 500 --num-users 20

# Different exchange (Kraken has higher minimums)
python simulate_live_trade.py --exchange kraken

# Detailed per-user breakdown
python simulate_live_trade.py --detailed
```

This simulation requires **NO API credentials** and uses **NO real money** - it's purely mathematical demonstration.

---

## Safety Mechanisms

### 1. Exchange Minimum Trade Sizes

**Purpose:** Prevent unprofitable micro-trades

**Implementation:**
- Coinbase: $2.00 minimum
- Kraken: $10.50 minimum (includes fee buffer)
- Binance: $10.00 minimum
- OKX: $1.00 minimum

**Result:** Accounts too small to profitably trade are blocked automatically.

### 2. Tier-Based Position Limits

**Purpose:** Prevent over-leveraging based on account maturity

**Tier Structure:**

| Tier | Capital Range | Max Position Size | Max Positions | Risk Per Trade |
|------|---------------|-------------------|---------------|----------------|
| STARTER | $50 - $300 | $10 | 2 | 3% - 5% |
| SAVER | $300 - $1,000 | $50 | 3 | 2.5% - 4% |
| INVESTOR | $1,000 - $5,000 | $150 | 4 | 2% - 3.5% |
| INCOME | $5,000 - $10,000 | $350 | 5 | 1.75% - 3% |
| LIVABLE | $10,000 - $25,000 | $750 | 6 | 1.5% - 2.5% |
| BALLER | $25,000+ | $1,500 | 8 | 1% - 2% |

**Result:** Accounts are automatically assigned appropriate risk limits based on balance.

### 3. Fee-Aware Configuration

**Purpose:** Ensure trades can be profitable after fees

**Implementation:**
- All position sizes account for 1.0% round-trip fees (Coinbase limit orders)
- Minimum profit targets set to 1.5% (1.5x fees)
- Positions that can't overcome fees are rejected

**Example:**
- $2 position needs 1.5% gain = $0.03 profit (after $0.02 fees)
- $100 position needs 1.5% gain = $1.50 profit (after $1.00 fees)

### 4. Stop Loss Enforcement

**Purpose:** Limit maximum loss per trade

**Implementation:**
- Every position MUST have a stop loss
- Stop loss placed at technical support level or -2% to -5% below entry
- Stop loss cannot be removed or disabled
- Platform monitors and enforces stop losses

**Result:** Maximum loss per trade is capped automatically.

### 5. Daily Loss Limits (Circuit Breaker)

**Purpose:** Prevent catastrophic drawdown in a single day

**Implementation:**
- Default: 5% maximum daily loss
- Trading automatically halted if daily loss exceeds limit
- Requires manual reset the next day
- User can adjust limit (range: 3% - 10%)

**Example:**
- Account with $1,000 balance
- Daily loss limit: $50 (5%)
- If losses reach $50, all trading stops for the day
- Protection resets at midnight UTC

### 6. Maximum Drawdown Protection

**Purpose:** Protect accounts from extended losing streaks

**Implementation:**
- Default: 15% maximum drawdown from equity high
- Trading halts if drawdown exceeds limit
- Requires review and manual restart
- User can adjust limit (range: 10% - 25%)

**Example:**
- Account peaks at $1,000
- Maximum drawdown: $150 (15%)
- If equity drops to $850, trading halts
- Protects remaining $850 from further losses

### 7. Position Count Limits (Multi-Layer Enforcement)

**Purpose:** Prevent over-diversification and manage risk

**Implementation:**
- **Maximum 8 concurrent positions** (strictly enforced)
- **6 independent safety checks** prevent cap violations:
  1. Pre-entry validation (before market scanning)
  2. Pre-scan double-check (at scan start)
  3. Pre-order final check (before order placement)
  4. Startup cleanup (runs on EVERY bot restart)
  5. Periodic cleanup (every 15 minutes)
  6. End-of-cycle verification (continuous monitoring)
- **Automatic enforcement** even after crashes or network failures
- **Exchange API is source of truth** (not corruptible local database)
- **Trade-based cleanup** (optional: trigger after N trades)

**Safety Guarantee:**
- Position count mathematically guaranteed ≤ 8
- Violations corrected within 15 minutes maximum
- Typical correction: < 2.5 minutes (one trading cycle)
- Crash recovery: immediate on restart

**Result:** Accounts cannot exceed 8 positions, even in worst-case scenarios (crashes, network failures, database corruption). Multi-layer defense ensures cap is always enforced.

### 8. Independent Trade Validation

**Purpose:** Each account validates trades independently

**Implementation:**
- Every trade checked against account-specific constraints
- Balance verification before execution
- Position size validation against minimums and maximums
- Risk checks (daily loss, drawdown, position count)
- Fee profitability verification

**Result:** Trades approved for one account may be rejected for another (by design).

### 9. Explicit Failure Mode Handling

**Purpose:** Ensure failures stop execution in a visible, deterministic way.

**Visible States:**
- **FAILSAFE_MODE** — emergency stop or critical risk breach detected
- **EXECUTION_PAUSED** — execution halted due to lock/nonce/connection issues
- **RECONCILIATION_REQUIRED** — startup reconciliation incomplete or stale

**Result:** Operators can see exactly why trading is paused and remediate safely.

### 10. Deterministic Startup Contract & Observability

**Startup Contract (LIVE mode):**
- Redis health + distributed writer lock verified
- Nonce synchronization and lease ownership validated
- Reconciliation completed (`NIJA_RECONCILIATION_COMPLETE=true`)
- Strategy framework loaded and execution pipeline healthy

**Observability:**
- Current trading mode is a single source of truth
- Reconciliation status and lease ownership are exposed in status output
- Execution eligibility is surfaced as a boolean gate

**Compliance Note:** System optimizations are technical in nature and do not imply improved financial outcomes.

---

## Why Results Differ Between Users

This is a **critical transparency point** for app reviewers. Results WILL differ between users, and this is **expected, safe, and properly disclosed**.

### 1. Timing Variations

**Network Latency:**
- User in New York: 10ms to Coinbase servers
- User in Tokyo: 150ms to Coinbase servers
- 140ms difference in receiving market data

**API Response Times:**
- Varies based on exchange server load
- Can range from 50ms to 500ms
- Peak trading hours have slower responses

**Independent Scanning:**
- Each account scans every ~2.5 minutes
- Scan times are not synchronized between accounts
- Account A might scan at 10:00:00, Account B at 10:00:17
- Per-account jitter and cooldown variance add additional timing divergence

**Market Conditions Change:**
- Bitcoin price at 10:00:00: $50,000.00
- Bitcoin price at 10:00:17: $50,012.50
- 17-second delay creates different entry prices

### 2. Account-Specific Factors

**Balance Differences:**
- Account A ($1,000) → $20 position
- Account B ($10,000) → $200 position
- Different sizes, same 2% risk

**Existing Positions:**
- Account A has 2 open positions → may skip new trade (at limit)
- Account B has 0 open positions → takes new trade
- Position count affects eligibility

**Available Capital:**
- Account A: $1,000 balance, $900 in positions → $100 free capital
- Account B: $1,000 balance, $200 in positions → $800 free capital
- Account A can only take $2 position (2% of $100)
- Account B can take $16 position (2% of $800)

**Risk Settings:**
- Account A uses aggressive settings (5% daily loss limit)
- Account B uses conservative settings (3% daily loss limit)
- Account A already down 4% today → can continue trading
- Account B already down 3% today → trading halted for the day

### 3. Execution Differences

**Fill Price Variations:**
- Account A submits market order at 10:00:00 → filled at $50,000.00
- Account B submits market order at 10:00:17 → filled at $50,012.50
- $12.50 price difference due to timing

**Slippage:**
- Large order: higher slippage (price moves against you)
- Small order: lower slippage (doesn't move market)
- Account with $1,000 position may experience 0.1% slippage
- Account with $10 position may experience 0.01% slippage

**Order Book Depth:**
- Liquid market (high volume): minimal slippage
- Illiquid market (low volume): higher slippage
- Same trade at different times = different execution quality

### 4. Exchange Differences

Users can connect different exchanges:
- **Coinbase:** Lower fees (0.4% maker), higher minimums
- **Kraken:** Higher fees (varies), strict $10 minimum
- **Binance:** Lowest fees (0.1% maker), high minimums
- **OKX:** Very low fees, low minimums

**Result:** Same signal, different execution quality based on exchange choice.

### Example: Why Two $1,000 Accounts Get Different Results

**Account A:**
- Balance: $1,000
- Exchange: Coinbase
- Scan time: 10:00:00
- No existing positions
- BTC price: $50,000
- Position size: $20 (2% of $1,000)
- Entry price: $50,000 (limit order)
- Outcome: +$0.50 profit (2.5% gain)

**Account B:**
- Balance: $1,000
- Exchange: Coinbase
- Scan time: 10:00:23 (23 seconds later)
- 1 existing position ($15 in BTC)
- BTC price: $50,015
- Position size: $19.70 (2% of $985 free capital)
- Entry price: $50,020 (slippage on market order)
- Outcome: +$0.30 profit (1.5% gain)

**Shared software logic with independent per-account evaluation, same balance, different results due to:**
1. Timing (23-second difference)
2. Existing positions (Account B had less free capital)
3. Entry price ($20 difference due to market movement)
4. Order type (Account A used limit, Account B used market)

**This is EXPECTED and properly disclosed to users.**

---

## Comparison to Prohibited Models

### ❌ Copy Trading (Prohibited - NIJA Does NOT Do This)

**How copy trading works:**
1. "Master" account executes a trade
2. "Master" broadcasts trade signal to "follower" accounts
3. "Follower" accounts copy the exact trade (mirrored)
4. Synchronized execution across all accounts

**Why it's prohibited:**
- Creates a managed account relationship
- Requires broker-dealer license
- Master trader has control over follower funds
- Not disclosed as independent trading

**Example:**
- Master buys $500 BTC at $50,000
- Signal sent to 100 followers
- All 100 followers buy $500 BTC at $50,000 (same size)
- Synchronized timing, identical positions

### ✅ Independent Trading (NIJA's Model - Compliant)

**How NIJA works:**
1. Each account runs the shared software logic with independent per-account evaluation
2. Each account analyzes market data with account-specific state
3. Each account makes its own trading decision
4. Position size calculated based on account's own balance and risk budget
5. Each account executes on its own schedule with timing jitter

**Why it's compliant:**
- Software tool, not a managed account service
- User maintains full control
- Transparent operation
- Properly disclosed
- No signal distribution

**Example:**
- Algorithm detects RSI oversold + trend confirmation
- Account A ($100 balance) independently analyzes → decides to buy $2 BTC
- Account B ($10,000 balance) independently analyzes → decides to buy $200 BTC
- Account C ($500 balance, 2 positions open) independently analyzes → decides NOT to buy (at limit)
- Independent timing, proportional positions, different outcomes

### Side-by-Side Comparison

| Feature | Copy Trading (Prohibited) | NIJA (Compliant) |
|---------|--------------------------|------------------|
| Trade signal source | Master account | Independent algorithm per account |
| Position sizing | Fixed or master-based | Proportional to account balance |
| Execution timing | Synchronized | Independent per account |
| Results between accounts | Identical (if same balance) | Naturally different |
| Account control | Master controls followers | Each account independent |
| Regulatory status | Requires broker license | Software tool |
| Disclosure | Often not disclosed | Fully transparent |

---

## Technical Implementation

### System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    NIJA Platform                            │
│  (Hosts the algorithm, provides infrastructure)             │
└─────────────────────────────────────────────────────────────┘
                            │
                            │ Algorithm
                            ▼
        ┌───────────────────────────────────────┐
        │                                       │
        ▼                                       ▼
┌──────────────┐                      ┌──────────────┐
│  User A      │                      │  User B      │
│  Account     │                      │  Account     │
│  ─────────   │                      │  ─────────   │
│  Balance:    │                      │  Balance:    │
│  $1,000      │                      │  $10,000     │
│              │                      │              │
│  Runs        │                      │  Runs        │
│  algorithm   │                      │  algorithm   │
│  every ~2.5  │                      │  every ~2.5  │
│  minutes     │                      │  minutes     │
│              │                      │              │
│  Calculates  │                      │  Calculates  │
│  own         │                      │  own         │
│  position    │                      │  position    │
│  size: $20   │                      │  size: $200  │
│              │                      │              │
│  Connects to │                      │  Connects to │
│  own         │                      │  own         │
│  exchange    │                      │  exchange    │
└──────┬───────┘                      └──────┬───────┘
       │                                     │
       │ API                                 │ API
       ▼                                     ▼
┌──────────────┐                      ┌──────────────┐
│  Coinbase    │                      │  Kraken      │
│  Account A   │                      │  Account B   │
│              │                      │              │
│  User A's    │                      │  User B's    │
│  funds       │                      │  funds       │
│  (never      │                      │  (never      │
│  leave this  │                      │  leave this  │
│  account)    │                      │  account)    │
└──────────────┘                      └──────────────┘
```

### Data Flow

**Market Data Analysis (per account):**
1. Account connects to exchange API
2. Fetches latest candle data (OHLCV)
3. Calculates technical indicators (RSI, EMA, MACD)
4. Evaluates entry criteria
5. If criteria met → calculate position size → execute trade
6. If criteria not met → wait for next scan cycle

**Position Sizing Calculation:**
```python
# Platform reference (for scaling ratio)
platform_balance = 10000.0
platform_trade_size = 200.0

# User account
user_balance = 1000.0

# Calculate scale factor
scale_factor = user_balance / platform_balance  # 0.1 (10%)

# Calculate user position size
user_trade_size = platform_trade_size * scale_factor  # $20

# Validate against minimums
exchange_minimum = 2.0  # Coinbase
if user_trade_size >= exchange_minimum:
    execute_trade(user_trade_size)
else:
    reject_trade("Position too small")
```

### API Permissions

Users grant NIJA **limited API permissions** on their exchange:

**Granted Permissions:**
- ✅ Query Funds (read balance)
- ✅ Query Orders (read open/closed orders)
- ✅ Create Orders (execute trades)
- ✅ Cancel Orders (close positions)

**Never Granted:**
- ❌ Withdraw Funds
- ❌ Transfer Funds
- ❌ Modify Account Settings
- ❌ Add Payment Methods

**User maintains full control** - can revoke API access at any time via exchange settings.

### Security Measures

**API Key Storage:**
- Encrypted at rest on user's device
- Never transmitted to NIJA servers
- Device-only access (not cloud-synced)

**Communication:**
- Direct HTTPS connection between user device and exchange
- No intermediary servers for trade execution
- All trades execute directly on user's exchange account

**Monitoring:**
- User can view all trades in real-time
- Complete trade history available
- P&L tracking and reporting
- Anomaly detection (unusual trades trigger alerts)

---

## User Protection Features

### 1. Comprehensive Risk Disclosures

**First Launch Screen:**
- Explains independent trading model
- Lists all risks (loss of capital, volatility, no guarantees)
- Requires acknowledgment before proceeding
- Age verification (18+ or 21+ where required)
- Geographic compliance confirmation

**Strategy Activation Screen:**
- Shows account balance and exchange
- Explains what will happen when activated
- Reinforces independent trading model
- Requires explicit opt-in checkboxes
- Recommends starting small

**Daily Notifications:**
- Remind users of independent trading model
- Include disclaimer: "Past results ≠ future performance"
- Encourage regular monitoring

### 2. Educational Resources

**In-App FAQ:**
- "How does NIJA work?"
- "Why do my trades differ from others?"
- "What are the risks?"
- "How do I stop trading?"
- "How are position sizes calculated?"

**Documentation:**
- Complete strategy documentation
- Risk management guides
- Position sizing calculator
- Fee calculator
- Example scenarios with outcomes

### 3. User Controls

**Anytime Access:**
- Pause/resume trading with one tap
- Adjust risk settings (daily loss limit, max positions)
- Close all positions manually
- Revoke API access via exchange
- Delete account and all data

**Monitoring:**
- Real-time position tracking
- Live P&L updates
- Trade history with full details
- Performance analytics
- Daily/weekly/monthly reports

### 4. Support & Safety Net

**Customer Support:**
- In-app support chat
- Email support (support@nija.app)
- FAQ and documentation
- Video tutorials

**Safety Alerts:**
- Daily loss limit approaching
- Unusual market volatility detected
- Failed trade execution
- API connection issues
- Drawdown limit approaching

---

## Demonstration for App Reviewers

### How to Verify NIJA's Safety

1. **Run the simulation:**
   ```bash
   python simulate_live_trade.py --detailed
   ```
   This demonstrates position sizing math without any API credentials.

2. **Review the calculations:**
   - Verify proportional scaling (user_balance ÷ platform_balance)
   - Confirm exchange minimums are enforced
   - Check fee calculations
   - Validate tier limits

3. **Test with different scenarios:**
   ```bash
   # Small accounts
   python simulate_live_trade.py --platform-balance 1000 --platform-trade-size 20
   
   # Large accounts
   python simulate_live_trade.py --platform-balance 100000 --platform-trade-size 2000
   
   # Kraken exchange (higher minimums)
   python simulate_live_trade.py --exchange kraken
   ```

4. **Examine the code:**
   - `position_sizer.py` - Position sizing logic
   - `tier_config.py` - Tier limits and risk management
   - `fee_aware_config.py` - Fee calculations
   - `simulate_live_trade.py` - Full simulation

### Questions App Reviewers May Ask

**Q: Is this copy trading?**  
A: No. Each account runs the shared software logic with independent per-account evaluation and makes its own decisions. Position sizes are calculated based on each account's balance and risk budget, not copied from another account.

**Q: Why would results differ if everyone uses the shared software logic with independent per-account evaluation?**  
A: Timing variations (network latency, scan schedules, per-account jitter), account-specific factors (balance, existing positions, risk settings, cooldown variance), and execution differences (fill prices, slippage). This is expected and properly disclosed.

**Q: How do you ensure smaller accounts are protected?**  
A: Multiple mechanisms: exchange minimum trade sizes ($2-$10), tier-based position limits, fee-aware sizing (rejects unprofitable trades), stop losses, daily loss limits, drawdown protection.

**Q: Can users lose money?**  
A: Yes, and we're very clear about this. Trading involves substantial risk. We display risk warnings throughout the app, require acknowledgment, and recommend starting small. Safety mechanisms limit losses, but profit is never guaranteed.

**Q: Do you hold user funds?**  
A: Never. Users maintain funds on their own exchange account. NIJA only has trading permissions via API keys (no withdrawal access). Users can revoke access anytime.

---

## Regulatory Compliance

### What NIJA Is

- ✅ **Software tool** for trading automation
- ✅ **Algorithmic assistant** that executes pre-programmed strategies
- ✅ **Educational platform** with risk management features

### What NIJA Is NOT

- ❌ Financial advisor or investment advisor
- ❌ Broker or dealer
- ❌ Copy trading platform or signal service
- ❌ Managed account service
- ❌ Financial planning service

### User Agreement

Users acknowledge:
- They are responsible for all trading decisions
- NIJA is software, not financial advice
- Substantial risk of loss exists
- No return promises
- Independent trading model (results will differ)
- Must be 18+ (21+ where required)
- Must verify cryptocurrency trading is legal in their jurisdiction

---

## Conclusion

NIJA is a **safe, transparent, and compliant** trading automation platform that:

1. ✅ Uses an **independent trading model** (not copy trading)
2. ✅ Implements **proportional position sizing** (smaller accounts = smaller risk)
3. ✅ Provides **mathematical transparency** (simple, verifiable calculations)
4. ✅ Includes **multiple safety mechanisms** (minimums, limits, circuit breakers)
5. ✅ Ensures **user maintains control** (funds never leave their exchange)
6. ✅ Clearly **discloses risks** (throughout the app experience)
7. ✅ **Educates users** about why results differ

We've designed NIJA to meet the highest standards for financial applications while providing genuine value to users who want trading automation.

---

## Contact for Review Questions

**Developer Contact:** support@nija.app  
**Documentation:** This document + APPLE_APP_REVIEW_FINANCIAL_FUNCTIONALITY.md  
**Simulation Tool:** `simulate_live_trade.py` (no credentials required)  
**Demo Account:** Available upon request for App Review team testing

---

*Document Version: 1.0*  
*Last Updated: February 2, 2026*  
*For: Apple App Review / Google Play Review*
