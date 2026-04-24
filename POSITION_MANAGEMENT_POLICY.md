# NIJA Position Management Policy

**Last Updated: February 8, 2026**

## Overview

This document defines exactly when NIJA is allowed to touch user assets and clarifies the distinction between NIJA-managed positions and existing holdings.

---

## Position Categories

### 1. NIJA-Managed Positions

**Definition:** Positions that were opened by NIJA's trading algorithm based on the user's configured strategy.

**Characteristics:**
- Opened automatically when NIJA detects a valid trading signal
- NIJA actively manages exit logic (stop-loss, take-profit, trailing stops)
- NIJA can modify or close these positions based on market conditions
- Tracked with `position_source: 'nija_strategy'` in the database

**User Interface Label:**
```
NIJA-Managed Positions (32)
```

**NIJA's Authority:**
- ✅ Can close position when profit target hit
- ✅ Can close position when stop-loss triggered
- ✅ Can close position when trailing stop triggered
- ✅ Can adjust position size (add to position within risk limits)
- ✅ Can update stop-loss and take-profit levels
- ✅ Full control within user's configured risk parameters

---

### 2. Existing Holdings (Not Managed by NIJA)

**Definition:** Positions that existed in the user's account before NIJA started trading, or positions manually entered by the user outside of NIJA.

**Characteristics:**
- Pre-existing positions from before NIJA activation
- Manually entered by user through exchange interface
- Positions from other trading bots or strategies
- Tracked with `position_source: 'broker_existing'`, `'manual'`, or `'unknown'` in the database

**User Interface Label:**
```
Existing Holdings (not managed by NIJA) (27)
```

**NIJA's Authority:**
- ❌ NIJA **NEVER** closes these positions automatically
- ❌ NIJA **NEVER** modifies these positions
- ❌ NIJA **NEVER** sets stop-losses or take-profits on these positions
- ✅ NIJA may display these positions for informational purposes
- ✅ User can manually choose to let NIJA manage them (adoption)

---

## Position Adoption (Special Case)

When NIJA restarts or reconnects to a user's account, it may find existing open positions. These fall into the "Existing Holdings" category by default.

### Automatic Adoption (Optional Feature)

If the user has enabled "Position Adoption" in settings:

1. **Discovery:** NIJA scans the user's account and identifies all open positions
2. **Classification:** 
   - Positions opened by NIJA before restart → Re-track as `nija_strategy`
   - All other positions → Mark as `broker_existing` (not managed)
3. **Optional User Consent:** 
   - NIJA can prompt: "Found 5 existing positions. Allow NIJA to manage them?"
   - If user approves → Convert to `nija_strategy` and apply exit logic
   - If user declines → Keep as `broker_existing` (display only)

### Important Safeguards

- **No Silent Adoption:** NIJA must never silently take control of user positions without consent
- **Clear Attribution:** Every position must clearly show whether it's NIJA-managed or not
- **User Override:** Users can always manually disable NIJA management of specific positions

---

## UI/UX Implementation

### Position Display Format

**Current (Confusing):**
```
Your Positions: 59 positions
```

**New (Clear):**
```
┌─────────────────────────────────────────────────────┐
│ Your Portfolio Overview                             │
├─────────────────────────────────────────────────────┤
│                                                     │
│ 📊 Total Positions: 59                              │
│                                                     │
│ ✅ NIJA-Managed Positions: 32                       │
│    Actively managed by NIJA's algorithm            │
│                                                     │
│ 📦 Existing Holdings: 27                            │
│    (not managed by NIJA)                           │
│    Pre-existing positions in your account          │
│                                                     │
└─────────────────────────────────────────────────────┘
```

### Position List View

Each position should show a clear indicator:

```
NIJA-Managed Positions (32)
─────────────────────────────────────────────────────
🟢 BTC-USD          +2.3%    $1,234.56    [NIJA]
🟢 ETH-USD          +1.8%    $856.23      [NIJA]
🟢 SOL-USD          +3.1%    $432.10      [NIJA]
...

Existing Holdings - Not Managed by NIJA (27)
─────────────────────────────────────────────────────
⚪ DOGE-USD         -0.5%    $123.45      [MANUAL]
⚪ ADA-USD          +1.2%    $345.67      [PRE-EXISTING]
⚪ XRP-USD          +0.8%    $234.56      [MANUAL]
...
```

### Tooltips/Help Text

**NIJA-Managed Positions:**
```
ℹ️ These positions were opened by NIJA based on your configured 
   trading strategy. NIJA actively manages exits, stop-losses, 
   and profit targets for these positions.
```

**Existing Holdings:**
```
ℹ️ These positions existed in your account before NIJA started 
   trading, or were manually entered by you. NIJA does NOT 
   automatically manage or close these positions. You remain 
   in full control.
```

---

## App Store Explanation

### App Store Description - Position Management Section

```markdown
POSITION MANAGEMENT

NIJA clearly distinguishes between two types of holdings in your account:

1. NIJA-Managed Positions
   • Positions opened by NIJA based on YOUR configured strategy
   • NIJA actively manages exits, stop-losses, and profit targets
   • You control the strategy parameters and risk limits

2. Existing Holdings (Not Managed by NIJA)
   • Pre-existing positions from before you activated NIJA
   • Manual positions you entered yourself
   • Positions from other trading tools
   • NIJA displays these for your information but NEVER 
     automatically modifies or closes them

IMPORTANT: You maintain full control and visibility over all 
positions at all times. NIJA only manages positions that IT 
opened based on your configured strategy.
```

### App Store Review - Key Points

When submitting to Apple App Store, emphasize:

1. **Clear Labeling:** All positions are clearly labeled as NIJA-managed or not
2. **User Control:** Users can always manually override or disable NIJA
3. **No Silent Takeover:** NIJA never silently takes control of existing user positions
4. **Transparency:** Position source is always visible in the UI
5. **Data Attribution:** Backend database tracks position source for audit trail

---

## Technical Implementation

### Database Schema

```sql
-- open_positions table
CREATE TABLE open_positions (
    ...
    position_source TEXT DEFAULT 'unknown',
    -- Values: 'nija_strategy', 'broker_existing', 'manual', 'unknown'
    ...
);
```

### API Response Format

```json
{
  "positions": [
    {
      "symbol": "BTC-USD",
      "size": 0.01,
      "unrealized_pnl": 123.45,
      "position_source": "nija_strategy",
      "managed_by_nija": true,
      "source_label": "NIJA-Managed Position",
      "source_description": "Opened by NIJA trading algorithm"
    },
    {
      "symbol": "ETH-USD",
      "size": 0.5,
      "unrealized_pnl": 45.67,
      "position_source": "broker_existing",
      "managed_by_nija": false,
      "source_label": "Existing Holdings (not managed by NIJA)",
      "source_description": "Pre-existing position in your account"
    }
  ],
  "summary": {
    "total_positions": 59,
    "nija_managed_positions": 32,
    "existing_holdings": 27
  }
}
```

---

## User Education

### First-Time Setup

When a user first connects their exchange account:

```
┌─────────────────────────────────────────────────────┐
│ 🔍 Account Scan Complete                            │
├─────────────────────────────────────────────────────┤
│                                                     │
│ We found 27 existing positions in your account.    │
│                                                     │
│ ⚠️  IMPORTANT:                                       │
│ NIJA will NOT automatically manage these existing  │
│ positions. They will remain under your manual      │
│ control.                                           │
│                                                     │
│ NIJA will only manage NEW positions that it opens  │
│ based on your configured trading strategy.         │
│                                                     │
│ [ ] Allow NIJA to adopt and manage existing        │
│     positions (optional)                           │
│                                                     │
│ [Learn More]  [Continue]                           │
└─────────────────────────────────────────────────────┘
```

### In-App Help

Add help section explaining:

**Q: What happens to my existing crypto holdings when I activate NIJA?**

A: Nothing! NIJA will display your existing positions for informational purposes, but will NOT automatically manage, modify, or close them. NIJA only manages positions that IT opens based on your configured strategy. Your existing holdings remain completely under your manual control.

**Q: How do I know which positions are managed by NIJA?**

A: Every position is clearly labeled:
- Green checkmark (✅) = NIJA-Managed Position
- White circle (⚪) = Existing Holdings (not managed by NIJA)

You can also view the position breakdown in your portfolio overview.

**Q: Can NIJA ever touch my existing holdings?**

A: No, unless you explicitly enable "Position Adoption" and grant permission. Even then, you can selectively choose which positions NIJA can manage.

---

## Compliance & Legal

### Terms of Service Addition

```
POSITION MANAGEMENT POLICY

NIJA distinguishes between two types of positions:

1. NIJA-Managed Positions: Positions opened by NIJA based on 
   your configured strategy. NIJA has authority to manage exits, 
   stop-losses, and take-profits for these positions within your 
   configured risk parameters.

2. Existing Holdings: Pre-existing positions or manually entered 
   positions. NIJA does NOT have authority to modify or close 
   these positions automatically. You retain full manual control.

By using NIJA, you acknowledge that:
- You understand the distinction between managed and unmanaged positions
- You can view position classification at any time in the app
- You can disable NIJA management of any position at any time
- NIJA will never silently take control of your existing holdings 
  without your explicit consent
```

---

## Summary

This policy ensures:

1. ✅ **User Clarity:** Users always know which positions NIJA controls
2. ✅ **User Safety:** NIJA never silently takes control of existing positions
3. ✅ **Transparency:** Position source is tracked and displayed
4. ✅ **Compliance:** Meets App Store requirements for user control
5. ✅ **Trust:** Clear boundaries of NIJA's authority

**Core Principle:** NIJA only manages what IT created, unless explicitly authorized by the user.
