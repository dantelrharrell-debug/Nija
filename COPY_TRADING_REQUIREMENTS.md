# NIJA Copy Trading Requirements

## 🔥 CRITICAL: Non-Negotiable Requirements

Copy trading in NIJA will **NOT** work unless **ALL** requirements are met for both master and user accounts. If **ANY ONE** requirement is false, copy trading will be **DISABLED**.

## Master Account Requirements (ALL must be TRUE)

For the master account to send copy trades to users:

| Requirement | Description | How to Set |
|------------|-------------|------------|
| ✅ `PRO_MODE=true` | Enable position rotation trading | Set `PRO_MODE=true` in `.env` |
| ✅ `LIVE_TRADING=true` | Enable live trading (not paper) | Set `LIVE_TRADING=1` in `.env` |
| ✅ `MASTER_BROKER=KRAKEN` | Master must use Kraken | Set `KRAKEN_MASTER_API_KEY` and `KRAKEN_MASTER_API_SECRET` |
| ✅ `MASTER_CONNECTED=true` | Kraken master must connect successfully | Verify credentials and connection |

**Important:** If the master is not using Kraken or Kraken is not connected, **NO** copy trades will be sent to users.

## User Account Requirements (ALL must be TRUE)

For each user account to receive copy trades:

| Requirement | Description | How to Set |
|------------|-------------|------------|
| ✅ `PRO_MODE=true` | Enable position rotation (shared with master) | Set `PRO_MODE=true` in `.env` |
| ✅ `COPY_TRADING=true` | Enable copy trading mode | Set `COPY_TRADING_MODE=MASTER_FOLLOW` in `.env` |
| ✅ `STANDALONE=false` | User must NOT be in standalone mode | Automatic when `COPY_TRADING_MODE=MASTER_FOLLOW` |
| ✅ `TIER >= STARTER` | Minimum tier is STARTER ($50+) | Ensure account balance >= $50 |
| ✅ `INITIAL_CAPITAL >= 100` | For SAVER+ tiers only | Ensure balance >= $100 for non-STARTER tiers |

**Note:** STARTER tier ($50-$99) does NOT require `INITIAL_CAPITAL >= 100`. This requirement is only for SAVER tier ($100+) and above.

## Quick Setup Guide

### Step 1: Configure Master Account

Add these to your `.env` file:

```bash
# Enable PRO MODE (MANDATORY)
PRO_MODE=true

# Enable live trading (MANDATORY)
LIVE_TRADING=1

# Kraken Master credentials (MANDATORY)
KRAKEN_MASTER_API_KEY=your-master-api-key
KRAKEN_MASTER_API_SECRET=your-master-api-secret
```

### Step 2: Configure Copy Trading

Add these to your `.env` file:

```bash
# Enable copy trading mode (MANDATORY)
COPY_TRADING_MODE=MASTER_FOLLOW

# Set initial capital tracking (RECOMMENDED)
INITIAL_CAPITAL=LIVE
```

### Step 3: Verify User Accounts

For each user in `config/users/*.json`:

```json
{
  "user_id": "your_user",
  "name": "Your Name",
  "broker_type": "kraken",
  "enabled": true,
  "copy_from_master": true,  // Must be true
  "disabled_symbols": ["XRP-USD"]
}
```

Ensure user has Kraken credentials:

```bash
# User credentials in .env
KRAKEN_USER_YOURNAME_API_KEY=your-user-api-key
KRAKEN_USER_YOURNAME_API_SECRET=your-user-api-secret
```

### Step 4: Verify Minimum Balance

Ensure each user account has sufficient balance:

- **STARTER tier**: Minimum $50
- **SAVER+ tiers**: Minimum $100

## Troubleshooting

### ❌ "Copy trading blocked - master requirements not met"

**Cause:** One or more master requirements are not satisfied.

**Solution:**
1. Check `PRO_MODE=true` is set in `.env`
2. Check `LIVE_TRADING=1` is set in `.env`
3. Verify Kraken master credentials are configured
4. Check logs for Kraken connection errors

### ❌ "User requirements not met"

**Cause:** One or more user requirements are not satisfied.

**Solution:**
1. Check `PRO_MODE=true` is set in `.env`
2. Check `COPY_TRADING_MODE=MASTER_FOLLOW` is set
3. Verify user has `copy_from_master: true` in their JSON config
4. Check user balance is >= $50 (STARTER tier minimum)
5. For SAVER+ users, check balance is >= $100

### ❌ "User is in STANDALONE mode"

**Cause:** `COPY_TRADING_MODE` is set to `INDEPENDENT` or not set.

**Solution:**
Set `COPY_TRADING_MODE=MASTER_FOLLOW` in `.env` and restart.

## Viewing Requirements Status

When the bot starts, you'll see a requirements status report:

```
══════════════════════════════════════════════════════════════════════
📋 COPY TRADING REQUIREMENTS STATUS
══════════════════════════════════════════════════════════════════════
MASTER REQUIREMENTS:
   ✅ PRO_MODE=true
   ✅ LIVE_TRADING=true
   ✅ MASTER_BROKER=KRAKEN
   ✅ MASTER_CONNECTED=true

✅ Master: ALL REQUIREMENTS MET - Copy trading enabled
══════════════════════════════════════════════════════════════════════
```

If any requirement is not met, you'll see:

```
══════════════════════════════════════════════════════════════════════
❌ COPY TRADING BLOCKED - MASTER REQUIREMENTS NOT MET
══════════════════════════════════════════════════════════════════════
   ❌ MASTER PRO_MODE=true
   ❌ LIVE_TRADING=true

🔧 FIX: Ensure these are set:
   PRO_MODE=true
   LIVE_TRADING=1
   KRAKEN_MASTER_API_KEY=<key>
   KRAKEN_MASTER_API_SECRET=<secret>
══════════════════════════════════════════════════════════════════════
```

## FAQs

### Q: Why is PRO_MODE mandatory?

**A:** PRO_MODE enables position rotation, which is critical for proper capital management in copy trading. Without it, accounts can become locked with all capital in positions, preventing new trades.

### Q: Can I use a different broker for master besides Kraken?

**A:** Currently, copy trading requires Kraken as the master broker. This may change in future versions.

### Q: What if my user has $75 balance?

**A:** A $75 balance puts the user in STARTER tier ($50-$99). The `INITIAL_CAPITAL >= 100` requirement is **waived** for STARTER tier. Copy trading will work as long as the other 4 requirements are met.

### Q: What if I want users to trade independently?

**A:** Set `COPY_TRADING_MODE=INDEPENDENT` in `.env`. Users will trade on their own strategies without copying the master.

### Q: Do all users need the same tier?

**A:** No. Each user's tier is determined by their individual account balance. Users can be in different tiers simultaneously.

## Environment Variable Summary

Required in `.env`:

```bash
# Master Requirements
PRO_MODE=true                              # MANDATORY
LIVE_TRADING=1                             # MANDATORY
KRAKEN_MASTER_API_KEY=<key>               # MANDATORY
KRAKEN_MASTER_API_SECRET=<secret>         # MANDATORY

# User Requirements
COPY_TRADING_MODE=MASTER_FOLLOW           # MANDATORY
INITIAL_CAPITAL=LIVE                      # RECOMMENDED

# User Credentials (for each user)
KRAKEN_USER_<FIRSTNAME>_API_KEY=<key>     # MANDATORY
KRAKEN_USER_<FIRSTNAME>_API_SECRET=<secret> # MANDATORY
```

## Related Documentation

- `COPY_TRADING_SETUP.md` - Detailed setup guide
- `PRO_MODE_README.md` - PRO MODE documentation
- `TIER_AND_RISK_CONFIG_GUIDE.md` - Tier system details
- `.env.example` - Environment variable template
