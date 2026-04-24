# NIJA In-App Onboarding Copy - Ready for Implementation

**Purpose**: Production-ready text for mobile app onboarding screens  
**Compliance**: Apple App Store Review Guidelines §2.5.6, §5.1.1  
**Last Updated**: February 3, 2026  
**Version**: 1.0

---

## 📱 Implementation Guide

This document provides **copy-paste ready** text for all onboarding screens in the NIJA mobile app. All copy is:

✅ Apple-compliant (based on APPLE_UI_WORDING_GUIDE.md)  
✅ Risk-transparent (meets financial app requirements)  
✅ User-empowering (emphasizes control and agency)  
✅ Legally defensible (reviewed by compliance)  

**For Developers**: Use exact wording. Do not modify without legal review.

---

## 🎯 Onboarding Flow Overview

```
Screen 1: Welcome / Cold Start
    ↓
Screen 2: Age & Jurisdiction Verification
    ↓
Screen 3: Education Mode Introduction
    ↓
Screen 4: Education Mode Active / Progress
    ↓
Screen 5: Dashboard (Education Mode)
    ↓
[Optional Path When Ready]
    ↓
Screen 6: Upgrade to Live Trading Consent
    ↓
Screen 7: Broker Connection
    ↓
Screen 8: Live Trading Active
```

---

## Screen 1: Welcome / Cold Start

**Screen Type**: Full-screen onboarding  
**Trigger**: First app launch  
**Primary CTA**: "Get Started"  
**Secondary CTA**: "Learn More"

### Title
```
Welcome to NIJA
```

### Subtitle
```
A User-Directed Trading Tool
```

### Body Copy
```
NIJA executes trades based on YOUR strategy and YOUR decisions.

🔐 Your API credentials stay on your device
📊 You configure your own trading rules
⚙️ You control when and how trades execute
🛡️ You are responsible for all trading activity
```

### What NIJA Does NOT Do (Expandable Section)
```
NIJA does not:
  ❌ Guarantee profits or returns
  ❌ Provide investment advice
  ❌ Trade automatically without your configuration
  ❌ Access your credentials without permission
```

### Disclaimer (Footer - Always Visible)
```
⚠️ Trading involves risk of loss. Past performance does not 
   guarantee future results.
```

### CTA Buttons
```
[Primary Button: Get Started]
[Secondary Link: Learn More About How NIJA Works]
```

**Apple Guideline Reference**: §2.5.6(a), §3.1.1  
**Source**: APPLE_UI_WORDING_GUIDE.md lines 106-135

---

## Screen 2: Age & Jurisdiction Verification

**Screen Type**: Modal dialog (blocking)  
**Trigger**: After clicking "Get Started"  
**Cannot Proceed Without**: Both checkboxes checked

### Title
```
⚠️ Important: Age & Legal Verification
```

### Body Copy
```
Before you can use NIJA, you must confirm the following:
```

### Required Checkboxes
```
□ I am at least 18 years old (or 21+ where required by law)

□ I confirm that cryptocurrency trading is legal in my 
  jurisdiction and I am responsible for compliance with 
  all applicable laws and regulations
```

### Additional Information (Collapsible)
```
Why we ask:
• NIJA facilitates cryptocurrency trading
• Legal age and jurisdiction requirements vary by location
• You are responsible for ensuring you can legally use this service
```

### Disclaimer
```
⚠️ NIJA does not provide legal advice. Consult a legal professional 
   if you are unsure about your jurisdiction's regulations.
```

### CTA Buttons
```
[Cancel]  [I Confirm and Wish to Continue] (disabled until both checked)
```

**Apple Guideline Reference**: §1.4.1, §2.5.6(a)  
**Source**: APPLE_APP_REVIEW_FINANCIAL_FUNCTIONALITY.md lines 172-179

---

## Screen 3: Education Mode Introduction

**Screen Type**: Full-screen onboarding  
**Trigger**: After age/jurisdiction verification  
**Primary CTA**: "Start in Education Mode"

### Title (with Icon)
```
🎓 Learn Trading Without Risking Real Money
```

### Subtitle
```
Master algorithmic trading with our simulated environment
```

### Feature Highlights (Card Grid)

#### Card 1: Simulated Balance
```
💰 $10,000 Simulated Balance

Practice with virtual money. Learn without risk.
```

#### Card 2: Real Market Data
```
📊 Real Market Data

Trade on live market conditions with simulated execution.
```

#### Card 3: Track Progress
```
📈 Track Your Progress

Monitor win rate, risk control, and profitability.
```

#### Card 4: Upgrade When Ready
```
🎯 Upgrade When Ready

Connect your broker and trade live after you've built confidence.
```

### Trust Messages (Footer Cards)

#### Trust Card 1
```
🔒 Your funds never touch our platform.
   Trades execute directly on your broker.
```

#### Trust Card 2
```
✨ You're always in control.
   You can stop trading anytime.
```

### CTA Button
```
[Primary Button: Start in Education Mode]
```

**Apple Guideline Reference**: §2.5.6(d), §4.0  
**Source**: EDUCATION_MODE_ONBOARDING.md lines 5-55

---

## Screen 4: Education Mode Active / Progress

**Screen Type**: Modal overlay  
**Trigger**: Immediately after clicking "Start in Education Mode"  
**Primary CTA**: "Continue to Dashboard"

### Title (with Icon)
```
📚 Education Mode Active
```

### Subtitle
```
You're Learning with Simulated Money
```

### Important Notice (Highlighted Box)
```
ℹ️ This is not real money. All trades are simulated for 
   learning purposes.
```

### Progress Section

#### Progress Bar
```
Your Progress: [Visual progress bar] 0% Complete
```

#### Milestones Checklist
```
Milestones:
  ⚪ Complete First Trade
  ⚪ Complete 10 Trades
  ⚪ Achieve Profitability
  ⚪ Ready for Live Trading
```

### What Happens Next
```
Next Steps:
  1. Explore the dashboard
  2. Review your strategy settings
  3. Start simulated trading
  4. Track your progress
  5. Upgrade to live when ready
```

### CTA Button
```
[Primary Button: Continue to Dashboard]
```

**Apple Guideline Reference**: §2.5.6(d)  
**Source**: EDUCATION_MODE_ONBOARDING.md lines 57-96

---

## Screen 5: Dashboard (Education Mode)

**Screen Type**: Main app screen  
**Persistent Element**: Education Mode Banner

### Top Banner (Always Visible - Cannot Be Dismissed)
```
┌─────────────────────────────────────────────────────────┐
│ 📚 Education Mode - Simulated Trading                   │
│                                                          │
│ All balances and trades are simulated with virtual      │
│ money. This is not real money.                          │
│                                                          │
│ [View Progress]  [Upgrade to Live Trading]              │
└─────────────────────────────────────────────────────────┘
```

### Balance Display
```
Simulated Balance (Not Real Money)
$10,000.00 USD
```

### Stats Cards
```
┌──────────────┬──────────────┬──────────────┬─────────┐
│ Total P&L    │  Win Rate    │ Total Trades │ Active  │
│ (Simulated)  │              │              │ Positions│
│              │              │              │         │
│  $0.00       │    0%        │     0        │    0    │
└──────────────┴──────────────┴──────────────┴─────────┘
```

### Trading Control Panel
```
Trading Control

🔴 Trading: OFF

When enabled, NIJA will execute trades based on your 
configured strategy parameters. You maintain full control 
and can modify or disable at any time.

[Toggle: Enable User-Directed Trading]

ℹ️ All trades are simulated. No real money at risk.
```

### Footer Disclaimer (Persistent)
```
⚠️ Education Mode Active. Simulated trading only.
```

**Apple Guideline Reference**: §2.5.6(a), §4.0  
**Source**: EDUCATION_MODE_ONBOARDING.md lines 98-137

---

## Screen 6: Upgrade to Live Trading Consent

**Screen Type**: Modal dialog (blocking)  
**Trigger**: User clicks "Upgrade to Live Trading" AND meets graduation criteria  
**Requirements**: 10+ trades, 50%+ win rate, positive P&L  
**Cannot Proceed Without**: All checkboxes checked

### Title (with Celebration Icon)
```
🎉 Congratulations! You're Ready
```

### Subtitle
```
You've demonstrated consistent profitability in education mode.
```

### Your Stats (Card Display)
```
┌──────────────┬──────────────┬──────────────┐
│  Win Rate    │ Total Trades │  Total P&L   │
│              │              │ (Simulated)  │
│    58%       │     15       │  +$125.50    │
└──────────────┴──────────────┴──────────────┘
```

### Prompt
```
Want to Trade Live?

Connect your broker account and start trading with real money.
```

### Risk Acknowledgment Section
```
╔═══════════════════════════════════════════════════════════╗
║        ⚠️ RISK ACKNOWLEDGMENT REQUIRED                     ║
╚═══════════════════════════════════════════════════════════╝

Before enabling Independent Trading Mode, you must 
acknowledge and accept the following:
```

### Required Checkboxes (All Must Be Checked)
```
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
```

### CTA Buttons
```
[Secondary: Stay in Education Mode]  
[Primary: I Acknowledge the Risks and Wish to Proceed] (disabled until all checked)
```

### Additional Links
```
[Read Full Terms of Service]
[Read Privacy Policy]
[View Risk Disclosure]
```

**Apple Guideline Reference**: §2.5.6(a)(b)(c), §5.1.1  
**Source**: APPLE_UI_WORDING_GUIDE.md lines 68-102, EDUCATION_MODE_ONBOARDING.md lines 139-190

---

## Screen 7: Broker Connection

**Screen Type**: Full-screen form  
**Trigger**: After consent acknowledgment  
**Primary CTA**: "Connect Broker"

### Title
```
Connect Your Broker Account
```

### Subtitle
```
NIJA needs API access to execute trades on your exchange.
```

### Important Security Information (Highlighted Box)
```
🔐 Security & Privacy:

• Your API credentials are encrypted and stored only on your device
• NIJA NEVER has withdrawal permissions
• You can revoke access anytime via your exchange settings
• We recommend creating API keys with ONLY trading permissions
```

### Broker Selection
```
Select Your Broker:

○ Coinbase Advanced Trade
○ Kraken
○ Other (Coming Soon)
```

### API Credentials Form (After Broker Selection)
```
Coinbase API Configuration:

API Key:
[Text input field]

API Secret:
[Password input field]

PEM Content (Optional):
[Text area]

[Help: How to create Coinbase API keys]
```

### Required Permissions Checklist (Read-Only)
```
✅ Required Permissions:
  • Query Funds (read balance)
  • Query Open Orders & Trades (read positions)
  • Query Closed Orders & Trades (read history)
  • Create & Modify Orders (execute trades)
  • Cancel/Close Orders (close positions)

❌ NOT Required (Should Be Disabled):
  • Withdraw Funds ← NEVER enable this
```

### Testing Connection
```
[Button: Test Connection]

Connection Status: Not Connected
```

### CTA Buttons
```
[Cancel]  [Connect Broker] (disabled until connection successful)
```

### Footer Disclaimer
```
⚠️ You are responsible for the security of your API credentials.
   Never share your API secret with anyone.
```

**Apple Guideline Reference**: §5.1.1, §5.1.2  
**Source**: APPLE_APP_REVIEW_FINANCIAL_FUNCTIONALITY.md lines 186-194

---

## Screen 8: Live Trading Active

**Screen Type**: Main app screen  
**Persistent Element**: Live Mode Banner

### Top Banner (Always Visible - Different Color from Education)
```
┌─────────────────────────────────────────────────────────┐
│ 🟢 Independent Trading Active • User-Directed • [⏸]      │
│                                                          │
│ Broker: Coinbase Advanced Trade                         │
│ Status: Connected                                        │
│                                                          │
│ [Emergency Stop]  [Settings]                             │
└─────────────────────────────────────────────────────────┘
```

### Balance Display
```
Account Balance (Live)
$1,000.00 USD

Exchange: Coinbase
Last Updated: 2 minutes ago
[Refresh]
```

### Stats Cards
```
┌──────────────┬──────────────┬──────────────┬─────────┐
│ Total P&L    │  Win Rate    │ Total Trades │ Active  │
│ (Live)       │              │              │ Positions│
│              │              │              │         │
│  +$5.00      │    60%       │     5        │    1    │
└──────────────┴──────────────┴──────────────┴─────────┘
```

### Trading Control Panel
```
Trading Control

🟢 Trading: ON

Independent Trading Mode is active. Trades are executing 
on your connected broker account.

[Toggle: ON]

⚠️ Live trading involves real money. Monitor regularly.
```

### Quick Actions
```
[View Open Positions]
[View Trade History]
[Adjust Risk Settings]
[Switch to Education Mode]
```

### Footer Disclaimer (Persistent)
```
⚠️ Live Trading Active. Real money at risk. You are solely 
   responsible for all trading activity.
```

**Apple Guideline Reference**: §2.5.6(a)(c), §4.0  
**Source**: APPLE_UI_WORDING_GUIDE.md lines 140-158

---

## Persistent UI Elements

### Status Banner Text (Context-Aware)

#### When Trading is OFF
```
🔴 Trading: OFF  •  Monitoring Only  •  No Active Trades
```

#### When in Simulation Mode
```
🟡 SIMULATION MODE  •  Paper Trading  •  No Real Capital
```

#### When Live Trading Active
```
🟢 Independent Trading Active  •  User-Directed  •  [⏸]
```

**Source**: APPLE_UI_WORDING_GUIDE.md lines 140-158

---

### Emergency Stop Modal

**Trigger**: User clicks emergency stop button  
**Modal Type**: Blocking dialog

### Title
```
╔═══════════════════════════════════════════════════════════╗
║            🚨 EMERGENCY STOP ACTIVATED 🚨                  ║
╚═══════════════════════════════════════════════════════════╝
```

### Body Copy
```
All trading activity has been immediately halted.

Reason: User-initiated
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
```

### CTA Buttons
```
[View Open Positions on Exchange]  [Dismiss]
```

**Apple Guideline Reference**: §2.5.6(c)  
**Source**: APPLE_UI_WORDING_GUIDE.md lines 249-278

---

## Error Messages

### API Connection Failed
```
⚠️ Unable to Connect to Exchange

Trading has been paused to protect your capital.

Possible causes:
  • API credentials invalid or expired
  • Exchange API temporarily unavailable
  • Network connectivity issue

Recommendation: Review your API settings and try 
reconnecting. Trading will remain paused until 
connection is restored.

[Review Settings]  [Retry Connection]  [Contact Support]
```

**Source**: APPLE_UI_WORDING_GUIDE.md lines 225-245

---

### Position Close Failed
```
⚠️ Failed to Close Position

We encountered an error while attempting to close 
your position.

Position: BTC-USD Long
Error: [Error message from exchange]

Your position remains open. Please take action:
  1. Try closing again from NIJA
  2. Close manually via your exchange
  3. Contact support if issue persists

⚠️ You are responsible for managing this position.

[Retry Close]  [Open Exchange App]  [Contact Support]
```

**Apple Guideline Reference**: §2.5.6(c)

---

### Insufficient Balance
```
⚠️ Insufficient Balance

Cannot execute trade. Your account balance is too low.

Required: $100.00 USD
Available: $45.00 USD
Shortfall: $55.00 USD

Actions:
  • Deposit more funds on your exchange
  • Reduce position size in settings
  • Wait for current positions to close

Trading will resume automatically when balance is sufficient.

[Adjust Settings]  [Dismiss]
```

**Apple Guideline Reference**: §2.5.6(c)

---

## Push Notifications

### Trade Signal Detected (If Enabled)
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
```

**Source**: APPLE_UI_WORDING_GUIDE.md lines 318-343

---

### Position Closed (If Enabled)
```
Position Closed

BTC-USD Long position closed
Entry: $42,150.00
Exit: $42,990.00
P&L: +$84.00 (2.0%)

This notification is informational only. Review your 
full trade history in the app.
```

**Apple Guideline Reference**: §2.5.6(a)

---

### Daily Summary (If Enabled)
```
NIJA Daily Summary

Trading Mode: Independent Trading Active
Today's Trades: 3
Win Rate: 66.7%
Total P&L: +$45.00

⚠️ Reminder: You are solely responsible for all trading 
activity. Past performance does not guarantee future results.

[View Full Report]
```

**Apple Guideline Reference**: §2.5.6(a)(b)

---

## Settings Screen Copy

### Trading Mode Section
```
TRADING CONTROL

Trading Mode: [OFF / Simulation / Independent Trading]
  
  ○ OFF - Monitoring only, no trades executed
  ○ Simulation - Paper trading with virtual money
  ○ Independent Trading - Real trades on connected broker

Emergency Stop: [Activate]
  Immediately halt all trading activity
```

**Source**: APPLE_UI_WORDING_GUIDE.md lines 280-314

---

### Risk Management Section
```
RISK MANAGEMENT (Your Responsibility)

Position Size Limit: [Configure]
  Maximum size for any single position

Daily Loss Limit: [Configure]
  Circuit breaker to stop trading after losses

Maximum Open Positions: [Configure]
  Limit simultaneous positions

⚠️ You are responsible for configuring appropriate risk 
   limits for your account size and risk tolerance.
```

**Apple Guideline Reference**: §2.5.6(c)

---

### Exchange Connection Section
```
EXCHANGE CONNECTION

Coinbase API: [Connected ✓ / Not Connected]
  Last sync: 5 minutes ago
  [Manage Connection]

Kraken API: [Not Connected]
  [Connect Kraken]

⚠️ API credentials are stored encrypted on your device.
   You can revoke access anytime via your exchange.
```

**Apple Guideline Reference**: §5.1.1

---

### Legal & Support Section
```
LEGAL & SUPPORT

Terms of Service: [View]
Privacy Policy: [View]
Risk Disclosure: [View]

Support & Documentation: [Open]
Contact Support: [Email / Chat]

Delete Account & Data: [Delete]
  ⚠️ This action cannot be undone

App Version: 1.0.0
```

**Source**: APPLE_UI_WORDING_GUIDE.md lines 307-314

---

## Footer Disclaimers (Required on All Financial Screens)

### Short Version (Always Visible)
```
⚠️ Trading involves risk of loss. Past performance does 
   not guarantee future results. You are solely responsible 
   for your trading decisions.
```

### Long Version (Legal Pages)
```
⚠️ RISK DISCLOSURE

Trading cryptocurrencies and other financial instruments 
involves substantial risk of loss and may not be suitable 
for all investors. You should carefully consider whether 
trading is appropriate for your financial situation.

NIJA is a software tool for executing YOUR trading strategy. 
NIJA does not provide investment advice, financial planning, 
or guaranteed returns. You are solely responsible for all 
trading decisions and outcomes.

Past performance is not indicative of future results. 
Simulated results do not reflect actual trading costs, 
slippage, or market impact. Real trading may produce 
different results.

You may lose all or more than your invested capital. Only 
invest what you can afford to lose.
```

**Apple Guideline Reference**: §2.5.6(a)(b)  
**Source**: APPLE_UI_WORDING_GUIDE.md lines 369-386

---

## Implementation Checklist for Developers

### Before Implementing Any Screen

- [ ] Copy exact text from this document (do not modify)
- [ ] Verify no forbidden phrases used (see APPLE_UI_WORDING_GUIDE.md lines 346-365)
- [ ] Include required disclaimer for financial screens
- [ ] Test on smallest screen size (iPhone SE)
- [ ] Test on largest screen size (iPad Pro)
- [ ] Verify all checkboxes are functional
- [ ] Confirm CTAs are disabled until requirements met
- [ ] Test with VoiceOver (accessibility)
- [ ] Ensure minimum touch target size (44x44pt)

### Localization Notes

When translating to other languages:
- Maintain same level of legal precision
- Preserve all warnings and disclaimers
- Do not soften or remove risk language
- Have legal team review translations
- Apple may reject if translations are misleading

---

## Version History

| Version | Date | Changes | Approved By |
|---------|------|---------|-------------|
| 1.0 | Feb 3, 2026 | Initial creation | Compliance Team |

---

## Questions or Modifications

**DO NOT modify copy without approval from**:
- Legal/Compliance Team (risk disclaimers)
- Product Team (user experience flow)
- Apple Review Consultant (guideline compliance)

**For questions**: Reference screen number and specific text in question.

---

**Status**: ✅ Ready for Implementation  
**Compliance**: ✅ Apple Guidelines §2.5.6, §5.1.1  
**Legal Review**: ✅ Approved  
**Last Updated**: February 3, 2026
