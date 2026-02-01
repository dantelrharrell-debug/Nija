# NIJA "Starter-Safe" Copy Trading Profile

## Public-Facing Message

> **"NIJA AI Trading is designed for accounts starting at $100.**
> **Smaller balances may connect, but full trading performance begins at Starter tier."**

This simple message protects:
- ✅ Your brand (users don't think the bot is broken)
- ✅ Your support inbox (no "why isn't it trading?" tickets)
- ✅ Your users' money (fees won't destroy tiny accounts)

## Platform Account Tiers (Updated Jan 23, 2026)

NIJA now enforces **hard minimum funding rules** for platform accounts to prevent lockouts and ensure reliable operation.

### Master Funding Tiers

| Tier | Balance Range | Hard Minimum | Description |
|------|---------------|--------------|-------------|
| **MICRO_MASTER** | $25-$49 | $25 | Ultra-minimal, Coinbase only, learning mode |
| **STARTER** | $50-$99 | $50 | Entry level, copy trading recommended |
| **SAVER** | $100-$249 | $100 | Minimum viable platform account |
| **INVESTOR** | $250-$999 | $250 | Multi-position support, rotation enabled |
| **INCOME** | $1,000-$4,999 | $1,000 | Professional-grade platform |
| **LIVABLE** | $5,000-$24,999 | $5,000 | Pro-style scaling |
| **BALLER** | $25,000+ | $25,000 | Institutional-quality platform |

**NEW:** See **MICRO_PLATFORM_GUIDE.md** for detailed instructions on operating with $25-$50 capital.

## Why $100 Minimum for Regular Users?

Below $100, several critical issues emerge:

### 1. **Fees Dominate**
- Coinbase: ~1.4% round-trip fees
- On a $50 account with $5 trades: Fees consume most profits
- $100+ accounts can afford $10+ trades where fees are manageable

### 2. **Exchange Minimums**
- Kraken requires $10 minimum order size
- With $50 balance, only 5 trades max before funds exhausted
- $100+ allows proper position sizing

### 3. **Tier Enforcement Blocks Entries**
- STARTER tier (< $100): Limited, often blocked
- SAVER tier ($100+): Full feature access with proper risk management

### 4. **Users Think Bot is Broken**
- Small accounts hit limits constantly
- Support tickets: "Why won't it trade?"
- $100+ provides smooth, expected operation

## The "Starter-Safe" Profile

This is NIJA's **GOLD STANDARD** configuration for new users starting with $100.

### Configuration Parameters

| Parameter | Value | Why This Matters |
|-----------|-------|------------------|
| **TIER** | SAVER | Absolute minimum where fees/minimums/risk coexist |
| **INITIAL_CAPITAL** | $100 | Engineering-driven minimum, not marketing fluff |
| **MAX_RISK_PER_TRADE** | 10% | Fixed tier-locked risk (no chaos) |
| **MAX_POSITIONS** | 1 | Single position focus for small accounts |
| **MAX_CONCURRENT_TRADES** | 1 | One trade at a time |
| **MIN_TRADE_SIZE** | $10 | Kraken minimum + fee requirements |
| **STOP_LOSS_PRIMARY** | 1.0% | Tight risk control |
| **TIME_EXIT** | 15 minutes | Quick exits to minimize exposure |
| **BROKER_PRIORITY** | KRAKEN | Lower fees than Coinbase |
| **COPY_MODE** | STRICT | Safe mirroring of platform trades |
| **PRO_MODE** | true | Enabled but invisible to users |
| **TIER_LOCK** | SAVER | Retail gets PRO logic with tier-capped risk |

## PRO MODE + Tier Lock (The Key to Safety)

The magic happens with this combination:

### What is PRO MODE?
- Smart execution logic
- Position rotation capability
- Fee-aware execution
- Advanced risk management

### What is TIER_LOCK?
- Prevents full aggression on small accounts
- Caps risk to tier limits (SAVER = 10% max)
- Users never toggle it (invisible)
- Provides institutional logic with retail safety

### Why This Works
```
PRO MODE (smart) + TIER_LOCK (safe) = Protected retail trading
```

Users get sophisticated execution without the risk of over-leveraging their small accounts.

## Tier Comparison

| NIJA Tier | Capital Min | Why This Number |
|-----------|-------------|-----------------|
| **STARTER** | $50 | ❌ DEPRECATED - Copy trading only, NOT for live |
| **SAVER** | $100 | ✅ Absolute minimum where fees/minimums/risk coexist |
| **INVESTOR** | $250 | Allows multi-position rotation without risk blocks |
| **INCOME** | $1,000 | First tier where NIJA trades as designed |
| **LIVABLE** | $5,000 | Enables pro-style scaling + streak logic |
| **BALLER** | $25,000 | Capital deployment mode (institutional behavior) |

## Hard Rule (Do Not Violate Publicly)

**Accounts below $100 should NOT be advertised as "live trading."**

Why?
1. **Fees dominate** - 1.4% round-trip on Coinbase eats tiny accounts
2. **Kraken rejects orders** - $10 minimum can't be met consistently
3. **Tier enforcement blocks entries** - System designed for $100+
4. **Users think bot is broken** - It's not, it's protecting them

## Copy Trading Scaling

When users copy trade from a platform account:

```
User Position = Master Position × (User Balance / Master Balance)
```

Example:
- Master has $1,000, takes $50 position (5%)
- User has $100, gets $5 position (5%)
- Same risk percentage, scaled to account size

This ensures small accounts can safely mirror larger accounts.

## Setup Instructions

### For $100 Starter Accounts

1. **Fund Account**: Deposit at least $100
2. **Copy `.env.saver_tier` to `.env`**
3. **Add Your API Keys**: Coinbase or Kraken credentials
4. **Verify Settings**:
   ```bash
   TRADING_TIER=SAVER
   INITIAL_CAPITAL=100
   PRO_MODE=true
   TIER_LOCK=SAVER
   COPY_TRADING_MODE=STRICT
   ```
5. **Start Trading**: `./start.sh`

### Important Notes

- ✅ **Paper trade first** if you're new to algorithmic trading
- ✅ **Monitor closely** for the first week
- ✅ **Fees impact small accounts** - expect ~1.4% per round trip
- ✅ **Don't expect income generation** at $100 - this is learning tier
- ✅ **Upgrade to INVESTOR tier** ($250+) when ready for better flexibility

## Safety Features (Always Active)

Regardless of tier, NIJA enforces:

1. **Stop-loss required** on all trades
2. **Daily loss limits** enforced
3. **Maximum position limits** respected
4. **Fee-aware execution** prevents unprofitable trades
5. **Emergency stops** at critical balance levels

## Frequently Asked Questions

### Q: Can I trade with $50?
**A:** Technically yes via copy trading, but NOT recommended for live trading. Fees will dominate. Fund to $100 minimum.

### Q: Why can't I take more than 1 position at SAVER tier?
**A:** With $100 balance and $10 minimums, multiple positions would exceed safe risk limits. Upgrade to INVESTOR tier ($250+) for multi-position trading.

### Q: Is 10% risk too high?
**A:** 10% is the MAXIMUM, not typical. Actual trade sizes are often smaller based on market conditions. TIER_LOCK ensures you never exceed 10% even in optimal conditions.

### Q: What if I want to disable PRO MODE?
**A:** Not recommended. PRO MODE provides fee-aware execution and smart position management. It's designed to be invisible - you won't notice it's there, but you'll benefit from its protection.

### Q: How do I upgrade tiers?
**A:** As your balance grows:
- $250+: Change to `TRADING_TIER=INVESTOR`
- $1,000+: Change to `TRADING_TIER=INCOME`
- $5,000+: Change to `TRADING_TIER=LIVABLE`
- $25,000+: Change to `TRADING_TIER=BALLER`

Restart the bot after tier changes.

## Best Practices

1. **Start at $100** - Don't go below
2. **Use Kraken** - Lower fees than Coinbase for small accounts
3. **Enable copy trading** - Learn from experienced traders
4. **Monitor performance** - Track your first 20 trades
5. **Compound profits** - Let winning trades build your balance
6. **Upgrade tiers** - Move up as capital grows

## Support

For questions or issues:
- Check logs: `tail -f logs/nija.log`
- Verify balance: Ensure you have $100+ available
- Review configuration: Confirm TIER and INITIAL_CAPITAL settings
- Restart bot: `./restart_nija.sh`

## Version History

- **v4.1** (Jan 23, 2026) - Initial Starter-Safe profile release
  - $100 minimum enforcement
  - PRO MODE + TIER_LOCK implementation
  - Deprecated STARTER tier for live trading
  - Updated all tier capital minimums

---

**Remember**: NIJA AI Trading is designed for $100+ accounts. Below that, you're fighting fees and exchange minimums. Start right, trade smart.
