# APPLE APP STORE - PREFERRED UI WORDING GUIDE

**For NIJA Trading Application**  
**Last Updated: February 8, 2026**

This document provides **EXACT UI wording** that aligns with Apple App Store Review Guidelines for financial applications.

---

## 🎯 CRITICAL PRINCIPLES

Apple reviewers look for:
1. **User agency** - User is in control, not the app
2. **No guarantees** - No promises of profit
3. **Risk transparency** - Clear disclosure of risks
4. **Manual control** - User initiates actions
5. **No misleading claims** - Honest, factual language
6. **Clear Position Attribution** - Users know which assets NIJA manages

---

## 📊 POSITION MANAGEMENT WORDING (NEW - Feb 8, 2026)

### Position Overview Screen

**✅ EXACT WORDING:**
```
Your Portfolio Overview

Total Positions: 59

✅ NIJA-Managed Positions: 32
   Opened and managed by NIJA's trading algorithm

📦 Existing Holdings: 27
   (not managed by NIJA)
   Pre-existing or manually entered positions
```

### Position List View

**✅ EXACT WORDING:**
```
NIJA-Managed Positions (32)
───────────────────────────────────────────────
These positions were opened by NIJA based on your 
configured strategy. NIJA actively manages exits, 
stop-losses, and profit targets.

🟢 BTC-USD    +2.3%    $1,234.56    [NIJA-Managed]
🟢 ETH-USD    +1.8%      $856.23    [NIJA-Managed]
...

────────────────────────────────────────────────

Existing Holdings - Not Managed by NIJA (27)
───────────────────────────────────────────────
These positions existed before NIJA started or 
were manually entered by you. NIJA does NOT 
automatically manage or close these positions.

⚪ DOGE-USD    -0.5%     $123.45    [Manual]
⚪ ADA-USD     +1.2%     $345.67    [Pre-existing]
...
```

### Position Detail Tooltip

**For NIJA-Managed:**
```
ℹ️ NIJA-Managed Position

This position was opened by NIJA based on your 
configured trading strategy. NIJA actively manages:
  • Exit timing based on profit targets
  • Stop-loss protection
  • Trailing stops to lock in gains

You can manually close this position at any time.
```

**For Existing Holdings:**
```
ℹ️ Existing Holdings (Not Managed by NIJA)

This position existed in your account before NIJA 
started trading, or was manually entered by you.

NIJA does NOT automatically manage or close this 
position. You remain in full manual control.

You can optionally enable NIJA management for this 
position in settings.
```

### First Account Connection

**✅ EXACT WORDING:**
```
╔═══════════════════════════════════════════════════════╗
║         🔍 Account Scan Complete                      ║
╚═══════════════════════════════════════════════════════╝

We found 27 existing positions in your account.

⚠️  IMPORTANT:
NIJA will NOT automatically manage these existing 
positions. They will remain under your manual control.

NIJA will only manage NEW positions that it opens 
based on your configured trading strategy.

What would you like to do?

○ Display only (recommended)
  Show existing positions for information but do 
  not manage them

○ Allow NIJA to adopt and manage
  Apply NIJA's exit logic to existing positions
  (requires your explicit consent for each position)

[Learn More]  [Continue]
```

---

## ✅ APPROVED WORDING (USE THESE EXACT PHRASES)

### Main Trading Toggle

**❌ DON'T SAY:**
- "Enable Auto-Trading"
- "Turn On AI Trader"
- "Activate Automatic Profits"
- "Start Making Money"

**✅ DO SAY:**
```
Enable User-Directed Trading

When enabled, NIJA will execute trades based on your 
configured strategy parameters. You maintain full control 
and can modify or disable at any time.

⚠️ Trading involves risk of loss.
```

---

### Mode Selection Screen

**❌ DON'T SAY:**
- "Live Trading Mode"
- "Real Money Mode"
- "Profit Mode"

**✅ DO SAY:**
```
Trading Mode Selection

○ Simulation Mode
  Practice with simulated trades. No real capital at risk.
  
○ Independent Trading Mode
  Execute trades on your connected exchange using your 
  own capital and API credentials.
  
  ⚠️ You are solely responsible for all trading activity.
  ⚠️ Past performance does not guarantee future results.
```

---

### Risk Acknowledgment Dialog (MANDATORY BEFORE LIVE TRADING)

**✅ EXACT WORDING:**
```
╔═══════════════════════════════════════════════════════════╗
║              ⚠️  RISK ACKNOWLEDGMENT REQUIRED              ║
╚═══════════════════════════════════════════════════════════╝

Before enabling Independent Trading Mode, you must 
acknowledge and accept the following:

□ I understand that trading cryptocurrencies and other 
  financial instruments involves substantial risk of loss.

□ I understand that NIJA is a tool for executing MY OWN 
  trading strategy, and I am solely responsible for all 
  trading decisions.

□ I understand that past performance does not guarantee 
  future results and that I may lose all invested capital.

□ I understand that NIJA does not provide financial advice, 
  investment recommendations, or guaranteed returns.

□ I understand that I am responsible for:
  • Monitoring my account
  • Managing risk
  • Understanding exchange fees and costs
  • Compliance with applicable laws and regulations

□ I have read and agree to the Terms of Service and 
  Privacy Policy.

[Cancel]  [I Acknowledge the Risks and Wish to Proceed]
```

---

### First Launch Screen (Cold Start)

**✅ EXACT WORDING:**
```
╔═══════════════════════════════════════════════════════════╗
║                   Welcome to NIJA                         ║
╚═══════════════════════════════════════════════════════════╝

NIJA is a user-directed trading tool that executes trades 
based on YOUR strategy and YOUR decisions.

🔐 Your API credentials stay on your device
📊 You configure your own trading rules
⚙️ You control when and how trades execute
🛡️ You are responsible for all trading activity

NIJA does not:
  ❌ Guarantee profits or returns
  ❌ Provide investment advice
  ❌ Trade automatically without your configuration
  ❌ Access your credentials without permission

To get started:
  1. Review our Terms of Service and Privacy Policy
  2. Connect your exchange API (optional)
  3. Configure your trading strategy
  4. Start in Simulation Mode (recommended)

[Learn More]  [Get Started]
```

---

### Status Banner (Always Visible)

**✅ EXACT WORDING:**

```
When OFF:
┌─────────────────────────────────────────────────────────┐
│ 🔴 Trading: OFF  •  Monitoring Only  •  No Active Trades │
└─────────────────────────────────────────────────────────┘

When DRY RUN:
┌─────────────────────────────────────────────────────────┐
│ 🟡 SIMULATION MODE  •  Paper Trading  •  No Real Capital │
└─────────────────────────────────────────────────────────┘

When LIVE:
┌─────────────────────────────────────────────────────────┐
│ 🟢 Independent Trading Active  •  User-Directed  •  [⏸]  │
└─────────────────────────────────────────────────────────┘
```

---

### Strategy Configuration Screen

**❌ DON'T SAY:**
- "AI will optimize your profits"
- "Guaranteed win rate: 65%"
- "Make $X per day"
- "Set it and forget it"

**✅ DO SAY:**
```
Strategy Configuration

Configure the technical indicators and rules that will 
trigger trade signals. You are responsible for backtesting 
and validating your strategy before live use.

Entry Rules:
  • RSI(9) < 30 AND RSI(14) < 35
  • Configurable thresholds
  
Exit Rules:
  • Take profit at +2% (configurable)
  • Stop loss at -1% (configurable)
  
⚠️ These are YOUR rules. NIJA executes based on your 
   configuration. No strategy is guaranteed to be profitable.

[Test in Simulation]  [Save Configuration]
```

---

### Performance Display

**❌ DON'T SAY:**
- "Profit Guaranteed"
- "Consistent Returns"
- "Passive Income Generated"

**✅ DO SAY:**
```
Historical Performance (Simulation)

This data reflects simulated or past performance of your 
configured strategy and does not guarantee future results.

Period: Last 30 Days (Simulation)
  • Total Trades: 47
  • Winning Trades: 28 (59.6%)
  • Losing Trades: 19 (40.4%)
  • Net Simulated P&L: +$234 USD

⚠️ Past performance is not indicative of future results.
⚠️ Simulated results do not reflect actual trading costs.
⚠️ Real trading may produce different results.

[View Detailed Report]
```

---

### Error Messages

**✅ EXACT WORDING:**

```
API Connection Failed:
┌───────────────────────────────────────────────────────┐
│ ⚠️  Unable to Connect to Exchange                      │
│                                                        │
│ Trading has been paused to protect your capital.      │
│                                                        │
│ Possible causes:                                      │
│  • API credentials invalid or expired                 │
│  • Exchange API temporarily unavailable               │
│  • Network connectivity issue                         │
│                                                        │
│ Recommendation: Review your API settings and try      │
│ reconnecting. Trading will remain paused until        │
│ connection is restored.                               │
│                                                        │
│ [Review Settings]  [Retry Connection]  [Contact Support]│
└───────────────────────────────────────────────────────┘
```

---

### Kill Switch Activation

**✅ EXACT WORDING:**
```
╔═══════════════════════════════════════════════════════════╗
║            🚨 EMERGENCY STOP ACTIVATED 🚨                  ║
╚═══════════════════════════════════════════════════════════╝

All trading activity has been immediately halted.

Reason: [User-initiated / System protection / Error detected]
Time: [Timestamp]

Current Status:
  • No new trades will be executed
  • Existing positions remain open (not automatically closed)
  • All background processing stopped
  
⚠️ You are responsible for managing any open positions 
   through your exchange.

Next Steps:
  1. Review your account on your exchange
  2. Investigate the cause of the stop
  3. Resolve any issues
  4. Manually re-enable trading when ready

[View Open Positions on Exchange]  [Dismiss]
```

---

### Settings Screen

**✅ EXACT WORDING:**
```
Settings

TRADING CONTROL
  ○ Trading Mode: [OFF / Simulation / Independent Trading]
  ○ Emergency Stop: [Activate]
  
RISK MANAGEMENT (Your Responsibility)
  ○ Position Size Limit: [Configure]
  ○ Daily Loss Limit: [Configure]
  ○ Maximum Open Positions: [Configure]
  
EXCHANGE CONNECTION
  ○ Coinbase API: [Connected / Not Connected]
  ○ Kraken API: [Connected / Not Connected]
  
PRIVACY & DATA
  ○ Anonymous Usage Stats: [On / Off]
  ○ Crash Reports: [On / Off]
  ○ Cloud Backup: [On / Off]
  ○ Export Data: [Export]
  ○ Delete All Local Data: [Delete]
  
LEGAL & SUPPORT
  ○ Terms of Service: [View]
  ○ Privacy Policy: [View]
  ○ Risk Disclosure: [View]
  ○ Support & Documentation: [Open]
  
App Version: 1.0.0
```

---

### Notification/Alert Wording

**❌ DON'T SAY:**
- "Profit opportunity detected!"
- "Buy signal - act now!"
- "Your AI just made money!"

**✅ DO SAY:**
```
Trade Signal Detected

Your configured strategy has generated a signal:
  • Pair: BTC-USD
  • Signal: Entry (Long)
  • Confidence: Based on your RSI parameters
  
Action: [Depends on your settings]
  • If Independent Trading is enabled: Trade will execute
  • If Simulation Mode: Simulated trade recorded
  • If OFF: No action taken (notification only)

This is not investment advice. You configured these rules.

[View Details]  [Dismiss]
```

---

## 🚫 FORBIDDEN PHRASES (NEVER USE)

These will cause **INSTANT REJECTION**:

1. ❌ "Guaranteed profits"
2. ❌ "Passive income"
3. ❌ "Get rich"
4. ❌ "AI trades for you"
5. ❌ "Automatic money"
6. ❌ "No risk"
7. ❌ "Can't lose"
8. ❌ "100% win rate"
9. ❌ "Consistent returns"
10. ❌ "Set and forget"
11. ❌ "Financial freedom"
12. ❌ "Replace your job"
13. ❌ "Guaranteed ROI"
14. ❌ "Always profitable"
15. ❌ "Risk-free"

---

## ✅ REQUIRED DISCLAIMERS

**On EVERY screen that shows trading or performance:**

```
⚠️ Trading involves risk of loss. Past performance does 
   not guarantee future results. You are solely responsible 
   for your trading decisions.
```

**On app description/marketing:**

```
NIJA is a user-directed trading tool. You maintain full 
control over trading decisions, strategy configuration, 
and risk management. NIJA does not provide investment 
advice or guaranteed returns.
```

---

## 📱 UI ELEMENT GUIDELINES

### Buttons
- Use clear, action-oriented labels
- No "clickbait" language
- Example: "Configure Strategy" not "Make Money Now"

### Colors
- Red for risks/warnings/stop
- Yellow for caution/simulation
- Green for active (but not "profit")
- Gray for disabled/off

### Icons
- ⚠️ for warnings and risks
- 🔴 for stopped/off
- 🟡 for simulation/caution
- 🟢 for active (not profit)
- 🚨 for emergency/critical
- 🔐 for security/privacy
- 📊 for data/analytics

### Tone
- **Professional** - Not hype or excitement
- **Educational** - Informative, not persuasive
- **Transparent** - Honest about risks
- **Empowering** - User is in control
- **Factual** - No exaggeration

---

## 🎓 EXAMPLE: Complete User Flow

### 1. First Launch
```
"Welcome to NIJA - A user-directed trading tool.
[Review Terms] [Get Started]"
```

### 2. Setup Wizard
```
"Step 1: Understand the Risks
[Show risk disclosure, require acknowledgment]

Step 2: Connect Exchange (Optional)
You can connect your exchange API to enable trading.
Your credentials stay on your device.
[Configure] [Skip for Now]

Step 3: Configure Strategy
Define YOUR trading rules and parameters.
[Use Template] [Custom Configuration]

Step 4: Choose Mode
○ Simulation Mode (Recommended)
○ Independent Trading Mode (Requires risk acknowledgment)
[Continue]"
```

### 3. Main Screen
```
Status: 🟡 SIMULATION MODE
Last Signal: 2 minutes ago (No action - monitoring only)

Your Strategy Performance (Simulated):
  • 30-day simulated P&L: +$156
  • ⚠️ Past simulation does not guarantee future results

[View Details] [Settings]
```

---

## 📋 COMPLIANCE CHECKLIST

Before submitting to App Store, verify:

- [ ] No guaranteed profit language anywhere
- [ ] Risk disclaimers on all relevant screens
- [ ] "User-directed" or "Independent trading" terminology used
- [ ] Clear differentiation between simulation and live
- [ ] Risk acknowledgment required before live trading
- [ ] Privacy Policy and Terms accessible
- [ ] No automatic trading without user configuration
- [ ] Emergency stop clearly accessible
- [ ] Status always visible
- [ ] No misleading performance claims

---

**This guide ensures NIJA complies with Apple App Store Review Guidelines §3.1.1, §3.2.1, and §5.1.1 regarding financial applications.**
