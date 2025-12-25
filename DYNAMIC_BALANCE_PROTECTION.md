# Dynamic Balance Protection

## Overview
Nija now automatically scales the minimum balance reserve as your account grows, ensuring continuous trading capability while protecting profits.

## Balance Reserve Tiers

### Tier 1: Starting Phase ($0 - $100)
- **Reserve**: $15.00 fixed
- **Purpose**: Ensure minimum capital for Coinbase trades
- **Example**: $80 balance → $15 reserve, $65 tradable

### Tier 2: Growth Phase ($100 - $500)
- **Reserve**: 15% of balance
- **Purpose**: Protect growing capital while maintaining flexibility
- **Examples**:
  - $100 balance → $15 reserve, $85 tradable
  - $200 balance → $30 reserve, $170 tradable
  - $500 balance → $75 reserve, $425 tradable

### Tier 3: Expansion Phase ($500 - $2,000)
- **Reserve**: 10% of balance
- **Purpose**: Balance growth and risk management
- **Examples**:
  - $500 balance → $50 reserve, $450 tradable
  - $1,000 balance → $100 reserve, $900 tradable
  - $2,000 balance → $200 reserve, $1,800 tradable

### Tier 4: Mature Phase ($2,000+)
- **Reserve**: 5% of balance
- **Purpose**: Maximize capital efficiency while maintaining safety buffer
- **Examples**:
  - $2,000 balance → $100 reserve, $1,900 tradable
  - $5,000 balance → $250 reserve, $4,750 tradable
  - $10,000 balance → $500 reserve, $9,500 tradable

## How It Works

1. **Every trade cycle**, bot checks total account balance
2. **Calculates reserve** based on current tier
3. **Only trades with balance above reserve**
4. **Automatically scales** as balance grows
5. **Never runs out of capital** - always maintains minimum

## Benefits

✅ **Continuous Trading**: Never drops below minimum capital
✅ **Profit Protection**: Reserves grow with account
✅ **Automatic Scaling**: No manual adjustments needed
✅ **Risk Management**: Larger reserves as stakes increase
✅ **Fee Coverage**: Always enough for Coinbase transaction fees

## Current Status (Example)

### When your held positions sell (~$100+ balance):
- **Balance**: ~$100-120
- **Reserve**: ~$15-18 (15%)
- **Tradable**: ~$85-102
- **Max position**: $20-30 (20-30% of tradable)
- **Can open**: 3-5 positions simultaneously

### At $500 balance:
- **Reserve**: $75 (15%)
- **Tradable**: $425
- **Max position**: $85-170 (20-40% of tradable)
- **Can open**: 3-8 positions

### At $2,000 balance:
- **Reserve**: $200 (10%)
- **Tradable**: $1,800
- **Max position**: $150-720 (8-40% of tradable)
- **Can open**: 3-8 positions

### At $5,000 balance (15-day goal):
- **Reserve**: $250 (5%)
- **Tradable**: $4,750
- **Max position**: $380-1,900 (8-40% of tradable)
- **Can open**: 3-8 positions

## Implementation

The bot automatically:
1. Checks balance before every trade
2. Calculates appropriate reserve tier
3. Logs reserve amount and percentage
4. Only uses tradable balance for positions
5. Updates reserve as balance changes

**No configuration needed** - it just works! 🚀
