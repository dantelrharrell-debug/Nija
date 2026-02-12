# Soft + Hard Position & Sector Limit Enforcement

## Overview

This implementation adds best-practice graduated enforcement for position and sector concentration limits, providing **flexibility without breaking discipline**.

## Features

### 1. Position-Level Enforcement

**Single Asset Limits:**
- **Soft Limit: 4%** - Triggers warning and reduces position size by 50%
- **Hard Limit: 5%** - Blocks position entirely

Example:
- Propose 4.5% position → Reduced to 2.25% (soft limit)
- Propose 6.0% position → Blocked completely (hard limit)
- Propose 3.0% position → Passes through unchanged

### 2. Sector-Level Enforcement

**Cryptocurrency Sector Limits:**
- **Soft Limit: 15%** - Triggers warning and reduces new position by 50%
- **Hard Limit: 20%** - Blocks new entries in that sector

Example (Layer-1 sector):
- Existing: 14% → Propose +4% → Soft limit → Reduced to +2% (total: 16%)
- Existing: 19% → Propose +2% → Hard limit → Blocked (would exceed 20%)

### 3. Cryptocurrency Sector Taxonomy

Defined **19 distinct sectors** with global tracking:

1. **Bitcoin** - BTC and derivatives
2. **Ethereum** - ETH and ETH-based assets
3. **Stablecoins** - USDT, USDC, DAI, etc.
4. **Layer-1 (Alternative)** - SOL, ADA, AVAX, DOT, ATOM, NEAR, etc.
5. **Layer-1 (EVM)** - FTM, CELO, etc.
6. **Layer-2 & Scaling** - ARB, OP, MATIC, IMX, LRC
7. **DeFi - Lending** - AAVE, COMP, MKR, CRV
8. **DeFi - DEX** - UNI, SUSHI, CAKE, 1INCH
9. **DeFi - Derivatives** - GMX, SNX, PERP, DYDX
10. **DeFi - Staking** - LDO, RPL, RETH, STETH
11. **Exchange Tokens** - BNB, CRO, FTT, HT, OKB
12. **Oracles** - LINK, BAND, TRB, API3
13. **Gaming & Metaverse** - AXS, SAND, MANA, ENJ, GALA
14. **NFT Ecosystem** - BLUR, LOOKS
15. **Social Media** - MASK
16. **Meme Coins** - DOGE, SHIB, PEPE, FLOKI
17. **AI Tokens** - FET, AGIX, RNDR, OCEAN
18. **Privacy Coins** - XMR, ZEC, DASH
19. **Miscellaneous** - Uncategorized assets

**100+ symbol mappings** covering major trading pairs.

## Implementation

### Files Modified

1. **`bot/crypto_sector_taxonomy.py`** (NEW)
   - Sector definitions and classifications
   - Symbol-to-sector mapping (100+ pairs)
   - Global sector tracking configuration

2. **`bot/risk_manager.py`**
   - Added `soft_position_limit_pct` and `hard_position_limit_pct` parameters
   - New `check_position_limits()` method
   - Integrated into `calculate_position_size()` workflow
   - Position blocking or reduction based on limits

3. **`bot/portfolio_risk_engine.py`**
   - Added `soft_sector_limit_pct` and `hard_sector_limit_pct` parameters
   - Loaded crypto sector taxonomy
   - New `check_sector_limits()` method
   - Integrated into `_check_new_position_risk()` workflow
   - Sector-based position adjustments

4. **`bot/test_soft_hard_limits.py`** (NEW)
   - Comprehensive test suite (6 tests)
   - All tests passing ✅

5. **`bot/demo_soft_hard_limits.py`** (NEW)
   - Integration demonstration
   - Realistic workflow examples

## Configuration

### Default Values

```python
# Position Limits (AdaptiveRiskManager)
soft_position_limit_pct = 0.04  # 4% - warning + 50% reduction
hard_position_limit_pct = 0.05  # 5% - block position

# Sector Limits (PortfolioRiskEngine)
soft_sector_limit_pct = 0.15    # 15% - warning + 50% reduction
hard_sector_limit_pct = 0.20    # 20% - block sector entries
```

### Customization

Both limits are configurable via initialization parameters:

```python
# Custom position limits
risk_mgr = AdaptiveRiskManager(
    soft_position_limit_pct=0.03,  # 3% soft
    hard_position_limit_pct=0.04   # 4% hard
)

# Custom sector limits
portfolio_risk = PortfolioRiskEngine({
    'soft_sector_limit_pct': 0.12,  # 12% soft
    'hard_sector_limit_pct': 0.18   # 18% hard
})
```

## Benefits

1. **Flexibility** - Soft limits allow trades while reducing size for safety
2. **Discipline** - Hard limits provide absolute guardrails
3. **Institutional-Grade** - Sector tracking across all brokers prevents hidden concentration
4. **Transparency** - Clear warning messages explain all enforcement actions
5. **Testable** - Comprehensive test coverage ensures reliability

## Usage Examples

### Example 1: Position-Level Check

```python
from risk_manager import AdaptiveRiskManager

risk_mgr = AdaptiveRiskManager()

# Check if 4.5% position is allowed
allowed, adjusted_pct, info = risk_mgr.check_position_limits(0.045)
# Result: allowed=True, adjusted_pct=0.0225 (reduced by 50%)
```

### Example 2: Sector-Level Check

```python
from portfolio_risk_engine import PortfolioRiskEngine

portfolio_risk = PortfolioRiskEngine()

# Check if adding $500 to Layer-1 sector is allowed
allowed, adjusted_size, info = portfolio_risk.check_sector_limits(
    symbol="SOL-USD",
    position_size_usd=500.0,
    portfolio_value=10000.0
)
```

### Example 3: Integration in Workflow

The enforcement happens automatically in `calculate_position_size()`:

```python
position_size, breakdown = risk_mgr.calculate_position_size(
    account_balance=5000,
    adx=35,
    signal_strength=4,
    ai_confidence=0.8
)

# Check if soft limit was applied
if 'soft_limit_applied' in breakdown:
    print("Position size was reduced due to soft limit")

# Check if position was blocked
if 'position_blocked' in breakdown:
    print("Position blocked by hard limit")
```

## Testing

Run the test suite:

```bash
cd bot
python test_soft_hard_limits.py
```

Expected output:
```
✅ PASS: Soft limit correctly reduces position by 50%
✅ PASS: Hard limit correctly blocks position
✅ PASS: Position within limits passes through unchanged
✅ PASS: Sector taxonomy mapping works correctly
✅ PASS: Sector soft limit correctly reduces position by 50%
✅ PASS: Sector hard limit correctly blocks position

🎉 ALL TESTS PASSED!
```

Run the integration demo:

```bash
cd bot
python demo_soft_hard_limits.py
```

## Global vs Per-Broker Sector Tracking

**Decision: GLOBAL tracking (across all brokers)**

This provides institutional-grade risk management:
- Prevents hidden concentration across multiple exchanges
- Ensures true diversification
- More conservative and safer approach

Example:
- Binance: 10% in Layer-1 (SOL)
- Coinbase: 8% in Layer-1 (ADA)
- **Total Layer-1: 18%** - triggers soft limit globally

## Monitoring & Logging

All enforcement actions are logged with clear messages:

```
⚠️ SOFT LIMIT WARNING for BTC-USD: Position 4.50% exceeds soft limit 4%. 
   REDUCING position size by 50% to 2.25%

🚫 HARD LIMIT BLOCK for ETH-USD: Position 6.00% exceeds hard limit 5%. 
   NO NEW POSITIONS ALLOWED.

⚠️ SOFT SECTOR LIMIT WARNING for ADA-USD (Layer-1 (Alternative)): 
   Projected 17.0% exceeds soft limit 15%. 
   REDUCING position size by 50%: $700.00 → $350.00

🚫 HARD SECTOR LIMIT BLOCK for AVAX-USD (Layer-1 (Alternative)): 
   Projected 21.0% exceeds hard limit 20%. 
   NO NEW ENTRIES IN THIS SECTOR.
```

## Security

- ✅ No security vulnerabilities detected (CodeQL scan passed)
- ✅ No hard-coded secrets or credentials
- ✅ Safe mathematical operations with proper bounds checking
- ✅ Input validation for all parameters

## Version History

- **v1.0** (Feb 12, 2026) - Initial implementation
  - Soft + hard position limits
  - Soft + hard sector limits
  - Cryptocurrency sector taxonomy
  - Global sector tracking
  - Comprehensive test coverage

## Future Enhancements

Potential improvements for future versions:

1. **Dynamic Limits** - Adjust limits based on market conditions
2. **Per-Sector Custom Limits** - Different limits for different sectors
3. **Time-Based Relaxation** - Temporary limit overrides with time decay
4. **Portfolio Correlation** - Factor in cross-sector correlations
5. **User-Specific Overrides** - Allow experienced users custom limits

---

**Author:** NIJA Trading Systems  
**Date:** February 12, 2026  
**Status:** Production Ready ✅
