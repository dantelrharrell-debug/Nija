# Live Trade Simulation - Quick Start Guide

This guide explains how to use NIJA's live trade simulation tool to verify position sizing calculations and demonstrate the safety of the independent trading model.

## Purpose

The simulation demonstrates:
1. ✅ **Independent Trading Model** - Each account calculates its own position size
2. ✅ **Proportional Position Sizing** - Smaller accounts = smaller positions
3. ✅ **Safety Mechanisms** - Exchange minimums, tier limits, fee awareness
4. ✅ **Mathematical Transparency** - Simple, verifiable calculations

## Quick Start

### Run Basic Simulation

```bash
python simulate_live_trade.py
```

This runs a default simulation with:
- Platform account: $10,000 balance, $200 trade
- 10 user accounts ranging from $50 to $50,000
- Coinbase exchange
- Summary output

**Expected Output:**
- Position sizing table showing all accounts
- Statistics (valid trades, invalid trades, variance)
- Key insights about the independent trading model

### Run Detailed Simulation

```bash
python simulate_live_trade.py --detailed
```

This shows:
- Per-user breakdown with full calculations
- Fee breakdown for each account
- Profitability requirements
- Step-by-step math verification

### Test Different Scenarios

**Different Exchange (Kraken has higher minimums):**
```bash
python simulate_live_trade.py --exchange kraken
```

**Larger Platform Account:**
```bash
python simulate_live_trade.py --platform-balance 25000 --platform-trade-size 500
```

**More Users:**
```bash
python simulate_live_trade.py --num-users 20
```

**Combined:**
```bash
python simulate_live_trade.py --platform-balance 50000 --platform-trade-size 1000 --num-users 15 --exchange kraken --detailed
```

## Command-Line Options

| Option | Description | Default |
|--------|-------------|---------|
| `--platform-balance` | Platform account balance in USD | 10000 |
| `--platform-trade-size` | Platform trade size in USD | 200 |
| `--num-users` | Number of user accounts to simulate | 10 |
| `--exchange` | Exchange (coinbase, kraken, okx, binance) | coinbase |
| `--detailed` | Show detailed per-user breakdown | false |

## Understanding the Output

### Summary View

```
📊 USER ACCOUNTS (10 accounts):
----------------------------------------------------------------------------------------------------
User ID           Balance       Tier   Trade Size    Effective    Scale %       Status
----------------------------------------------------------------------------------------------------
micro_1      $      50.00    STARTER $       1.00 $       0.00      0.50%    ❌ Invalid (too small)
micro_2      $     100.00      SAVER $       2.00 $       1.99      1.00%      ✅ Valid
...
```

**Columns:**
- **User ID**: Account identifier
- **Balance**: User's account balance
- **Tier**: Auto-assigned tier based on balance
- **Trade Size**: Calculated position size (before fees)
- **Effective**: Position size after entry fee
- **Scale %**: User balance as % of platform balance
- **Status**: ✅ Valid or ❌ Invalid
- **Reason**: Why trade was approved/rejected

### Key Metrics

```
📈 SIMULATION STATISTICS:
   Total Accounts: 10
   Valid Trades: 9 (90.0%)
   Invalid Trades: 1 (10.0%)
   Average Trade Size: $209.67
   Min Trade Size: $2.00
   Max Trade Size: $1,000.00
   Total Trading Volume: $1,887.00
```

**What to Look For:**
- **Valid Trades %**: Should be high for properly balanced scenarios
- **Invalid Trades %**: Usually small accounts below exchange minimums
- **Size Variance**: Shows natural differences (500x is normal from $2 to $1000)

### Position Sizing Formula

Every calculation follows this simple formula:

```
user_position_size = platform_position_size × (user_balance ÷ platform_balance)
```

**Example:**
- Platform: $10,000 balance, $200 trade
- User: $1,000 balance
- Calculation: $200 × ($1,000 ÷ $10,000) = $200 × 0.1 = $20

This ensures:
- All accounts maintain the same risk ratio (2% in this example)
- Smaller accounts take smaller positions (safer)
- Larger accounts take larger positions (capital efficient)

## Safety Mechanisms Demonstrated

### 1. Exchange Minimum Enforcement

**Coinbase:** $2.00 minimum
- Account with $50 → $1.00 calculated → **BLOCKED**
- Account with $100 → $2.00 calculated → **APPROVED**

**Kraken:** $10.50 minimum
- Account with $500 → $10.00 calculated → **BLOCKED**
- Account with $1,000 → $20.00 calculated → **APPROVED**

### 2. Fee-Aware Sizing

Every position accounts for fees:
- Entry fee: 0.4% (Coinbase limit orders)
- Spread cost: 0.2%
- Exit fee: 0.4%
- **Total:** 1.0% round-trip

Position must be large enough to overcome fees and make profit.

### 3. Tier-Based Limits

Accounts automatically assigned to tiers based on balance:
- **STARTER** ($50-$300): Max $10 position, 2 max positions
- **SAVER** ($300-$1,000): Max $50 position, 3 max positions
- **INVESTOR** ($1,000-$5,000): Max $150 position, 4 max positions
- **INCOME** ($5,000-$10,000): Max $350 position, 5 max positions
- **LIVABLE** ($10,000-$25,000): Max $750 position, 6 max positions
- **BALLER** ($25,000+): Max $1,500 position, 8 max positions

## For App Store Reviewers

### Why This Simulation Matters

This tool demonstrates that NIJA uses an **independent trading model**, NOT copy trading:

1. **Each account calculates its own position size** based on its balance
2. **No account "copies" another account** - calculations are independent
3. **Results naturally differ** due to balance differences, timing, and execution
4. **Safety mechanisms prevent over-leveraging** on small accounts

### Key Verification Steps

1. **Run the simulation:**
   ```bash
   python simulate_live_trade.py --detailed
   ```

2. **Verify the math:**
   - Check that scale factors are correct (user_balance ÷ platform_balance)
   - Confirm position sizes are proportional
   - Validate safety mechanisms (minimums, tier limits)

3. **Test edge cases:**
   ```bash
   # Very small accounts
   python simulate_live_trade.py --platform-balance 100 --platform-trade-size 2
   
   # Kraken's higher minimums
   python simulate_live_trade.py --exchange kraken
   ```

4. **Review documentation:**
   - `APP_STORE_SAFETY_EXPLANATION.md` - Comprehensive safety guide
   - `APPLE_APP_REVIEW_FINANCIAL_FUNCTIONALITY.md` - App review submission notes

### No API Credentials Required

This simulation:
- ✅ Requires **NO** exchange API credentials
- ✅ Uses **NO** real money
- ✅ Is purely mathematical demonstration
- ✅ Can be run by anyone to verify calculations

### Questions?

See the comprehensive documentation:
- **Full Safety Guide:** `APP_STORE_SAFETY_EXPLANATION.md`
- **App Review Notes:** `APPLE_APP_REVIEW_FINANCIAL_FUNCTIONALITY.md`
- **Position Sizing Code:** `bot/position_sizer.py`
- **Tier Configuration:** `bot/tier_config.py`

---

## Example Output

### Default Simulation

```bash
$ python simulate_live_trade.py

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
micro_1      $      50.00    STARTER $       1.00 $       0.00      0.50%    ❌ Invalid
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

====================================================================================================

🔑 KEY INSIGHTS - WHY THIS IS SAFE FOR APP STORE REVIEW
====================================================================================================

1. ✅ INDEPENDENT TRADING MODEL
   Each account calculates its own position size based on its balance.
   No account 'copies' another account - each makes independent decisions.

2. ✅ PROPORTIONAL RISK MANAGEMENT
   All accounts maintain the same risk/reward ratio.
   Smaller accounts take smaller positions (safer).
   Example: 2.00% of balance is consistent.

3. ✅ TRANSPARENT MATHEMATICS
   Position sizing formula is simple and verifiable:
   user_size = platform_size × (user_balance ÷ platform_balance)

4. ✅ SAFETY MECHANISMS
   • Exchange minimum trade sizes enforced
   • COINBASE minimum: $2.00
   • Fee-aware position sizing
   • Tier-based limits

5. ✅ RESULTS NATURALLY DIFFER
   Position sizes range from $2.00 to $1000.00
   Size variance: 500.00x (due to different account balances)
   This is EXPECTED and TRANSPARENT.

6. ✅ USER MAINTAINS CONTROL
   • Users connect their own exchange accounts
   • Users can revoke API access anytime
   • No withdrawal permissions ever granted

====================================================================================================

💡 FOR APP STORE REVIEWERS:
   This simulation demonstrates NIJA's independent trading model.
   Each account calculates positions based on its own balance.
   This is NOT copy trading - it's algorithmic automation with proportional scaling.

   For more details, see: APP_STORE_SAFETY_EXPLANATION.md
```

---

**Last Updated:** February 2, 2026  
**For Questions:** See `APP_STORE_SAFETY_EXPLANATION.md`
