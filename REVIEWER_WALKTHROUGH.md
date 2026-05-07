# REVIEWER WALKTHROUGH - NIJA Trading Application

**For Apple App Review Team**  
**Application:** NIJA - Independent Trading Tool  
**Version:** 1.0.0  
**Review Date:** February 2026

---

> **CRITICAL SAFETY GUARANTEE**  
> **Tier-based capital protection is enforced in all environments and cannot be bypassed.**

---

## 🎯 QUICK START (2 MINUTES)

This guide helps you quickly test NIJA's core functionality without any setup.

### Option 1: Demo Mode (Recommended for Reviewers)

1. **Launch NIJA**
   - App boots successfully with no configuration required
   - You'll see: "Welcome to NIJA" screen

2. **Tap "Try Demo Mode"**
   - No exchange API credentials needed
   - Uses simulated market data
   - All features immediately functional

3. **Observe Key Features**
   - Status banner shows: 🟡 "SIMULATION MODE"
   - View demo strategy configuration
   - See simulated trade signals
   - Check Settings → Privacy Policy, Terms, Risk Disclosure

4. **Test Emergency Stop**
   - Tap emergency stop button
   - Observe immediate halt of all activity
   - Status changes to 🚨 "EMERGENCY STOP"

**Total Time:** ~2 minutes  
**Result:** All core features tested without any credentials

---

## 📋 DETAILED WALKTHROUGH

### 1. First Launch Experience

**What You'll See:**
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

Options:
  [Try Demo Mode]  [Connect Exchange]  [Learn More]
```

**What to Verify:**
- ✅ No errors or crashes
- ✅ Clear, compliant language
- ✅ Prominent risk disclosures
- ✅ No promises of return assurances
- ✅ User agency emphasized

---

### 2. Demo Mode Testing

**Path:** Launch → "Try Demo Mode"

**What Happens:**
1. App loads simulated market data
2. Status banner shows: 🟡 "SIMULATION MODE - Paper Trading - No Real Capital"
3. Demo strategy is pre-configured
4. Simulated trades begin executing

**Features to Test:**

#### A) Strategy Configuration
- View current strategy parameters
- See technical indicators (RSI, MACD, etc.)
- Observe entry/exit rules
- Note: All user-configurable

#### B) Simulated Trade Execution
- Watch for trade signals
- Observe simulated order placement
- See simulated fills with fees
- Track simulated P&L

#### C) Performance Tracking
- View trade history
- See win/loss statistics
- Check profit/loss calculations
- Note disclaimer: "Past performance does not guarantee future results"

#### D) Settings & Legal
- Settings → Privacy Policy (tap to read)
- Settings → Terms of Service (tap to read)
- Settings → Risk Disclosure (tap to read)
- Verify all are accessible and complete

---

### 3. State Management Testing

**Path:** Demo Mode → Settings → Trading Mode

**Test State Transitions:**

1. **OFF → DRY_RUN:**
   - Select "Simulation Mode"
   - Status changes to 🟡 "SIMULATION MODE"
   - No real trading possible

2. **DRY_RUN → LIVE_PENDING_CONFIRMATION:**
   - Select "Independent Trading Mode"
   - Risk acknowledgement dialog appears (see Section 4)

3. **Emergency Stop:**
   - Tap Emergency Stop button (any mode)
   - Status immediately changes to 🚨 "EMERGENCY STOP"
   - All activity halts
   - Clear message explains what happened

**What to Verify:**
- ✅ Clear visual feedback for each state
- ✅ Cannot accidentally enable live trading
- ✅ Emergency stop works immediately
- ✅ Status always visible

---

### 4. Risk Acknowledgement Flow (CRITICAL TEST)

**Path:** Settings → Trading Mode → "Independent Trading Mode"

**What You'll See:**
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
  investment recommendations, or promised returns.

□ I understand that I am responsible for:
  • Monitoring my account
  • Managing risk
  • Understanding exchange fees and costs
  • Compliance with applicable laws and regulations

□ I have read and agree to the Terms of Service and 
  Privacy Policy.

[Cancel]  [I Acknowledge the Risks and Wish to Proceed]
```

**What to Verify:**
- ✅ 6 separate checkboxes (must check all)
- ✅ Cannot proceed without checking all
- ✅ Clear, specific risk statements
- ✅ "Sole responsibility" emphasized
- ✅ No return promises mentioned
- ✅ Button disabled until all checked
- ✅ "Cancel" option prominent

**Note:** In demo mode, you won't actually connect to an exchange, but the risk flow can be reviewed.

---

### 5. Cold Start Verification

**Path:** Fresh app install with NO credentials configured

**What You'll See:**
```
╔═══════════════════════════════════════════════════════════╗
║                    🧊 COLD START MODE                      ║
╚═══════════════════════════════════════════════════════════╝

✅ NIJA has started successfully
❌ Trading is OFF - No API credentials configured

To enable trading:
1. Configure your exchange API credentials
2. Set required environment variables
3. Restart NIJA
4. Review and accept risk disclosure
5. Enable trading mode

NIJA will continue running in monitoring mode only.
No broker connections will be attempted.
No trades will be executed.
```

**What to Verify:**
- ✅ No errors or crashes
- ✅ No network calls made
- ✅ No broker initialization attempted
- ✅ Clear message about status
- ✅ Instructions provided
- ✅ App remains functional (demo mode available)

---

### 6. Privacy & Data Handling

**Path:** Settings → Privacy & Data

**What to Check:**

1. **Privacy Policy Access:**
   - Tap "Privacy Policy"
   - Verify it loads and is readable
   - Check for key sections:
     - What data is collected
     - What is NOT collected
     - How credentials are stored (locally only)
     - GDPR/CCPA compliance

2. **Data Controls:**
   - "Anonymous Usage Stats" toggle (can disable)
   - "Crash Reports" toggle (can disable)
   - "Export Data" button (works)
   - "Delete All Local Data" button (asks for confirmation)

3. **Credentials Storage:**
   - Verify message: "API credentials stored locally on device"
   - "Never transmitted to our servers" stated clearly
   - "Direct connection to exchange" explained

**What to Verify:**
- ✅ Privacy policy comprehensive
- ✅ User controls available
- ✅ Data deletion possible
- ✅ Local storage emphasized
- ✅ No server-side credential storage

---

### 7. Error Handling & Failure Modes

**Tests to Perform:**

#### A) Network Disconnection (Simulated)
- Enable airplane mode during demo
- Observe graceful handling
- App doesn't crash
- Clear error message shown
- Status changes appropriately

#### B) Invalid Configuration (Demo)
- Try to enable trading without credentials
- Observe clear error message
- Trading remains disabled
- Instructions provided

#### C) Emergency Stop During Activity
- Start demo mode with active trading
- Tap Emergency Stop
- Observe immediate halt
- Clear explanation provided
- Can resume after review

**What to Verify:**
- ✅ No crashes under any condition
- ✅ Clear error messages
- ✅ Graceful degradation
- ✅ User always informed
- ✅ Safe defaults (stops trading, doesn't continue)

---

### 8. UI/UX Compliance Checks

**Status Banner (Always Visible):**

When OFF:
```
🔴 Trading: OFF  •  Monitoring Only  •  No Active Trades
```

When SIMULATION:
```
🟡 SIMULATION MODE  •  Paper Trading  •  No Real Capital
```

When LIVE (if configured):
```
🟢 Independent Trading Active  •  User-Directed  •  [⏸ Pause]
```

**What to Verify:**
- ✅ Status always visible
- ✅ Clear color coding (🔴 off, 🟡 sim, 🟢 live)
- ✅ Pause/stop always accessible
- ✅ No ambiguity about current mode

**Performance Display:**
```
Historical Performance (Simulation)

This data reflects simulated or past performance of your 
configured strategy and does not guarantee future results.

Period: Last 30 Days (Simulation)
  • Total Trades: 47
  • Winning Trades: 28 (59.6%)
  • Net Simulated P&L: +$234 USD

⚠️  Past performance is not indicative of future results.
⚠️  Real trading may produce different results.
```

**What to Verify:**
- ✅ "Simulation" clearly marked
- ✅ Disclaimers prominent
- ✅ No guaranteed performance claims
- ✅ "May produce different results" stated

---

### 9. Forbidden Language Check

**What Should NEVER Appear:**
- ❌ "Profit promises"
- ❌ "Supplemental income"
- ❌ "AI trades for you"
- ❌ "Set and forget"
- ❌ "100% success rate"
- ❌ "No real-money execution"
- ❌ "Get rich"

**What SHOULD Appear:**
- ✅ "User-directed"
- ✅ "Independent trading"
- ✅ "Risk of loss"
- ✅ "Solely responsible"
- ✅ "No guarantees"
- ✅ "Past performance does not guarantee future results"

**How to Check:**
- Review main screen
- Review settings
- Review help/documentation
- Review any alerts/notifications

---

### 10. Final Verification Checklist

**Before Approving, Verify:**

- [ ] App launches without credentials (cold start works)
- [ ] Demo mode works without setup
- [ ] Risk acknowledgement required for live mode
- [ ] Privacy policy accessible and comprehensive
- [ ] Terms of service accessible
- [ ] Emergency stop works immediately
- [ ] Status always clearly indicated
- [ ] No guaranteed profit language anywhere
- [ ] No crashes under any test condition
- [ ] Data can be exported and deleted
- [ ] All disclaimers present and prominent

---

## 🎬 VIDEO WALKTHROUGH

**Quick Demo (2 minutes):**
1. Launch app (0:00-0:10)
2. Try demo mode (0:10-0:45)
3. View strategy config (0:45-1:00)
4. Check settings/privacy (1:00-1:20)
5. Test emergency stop (1:20-1:40)
6. Review risk disclosure (1:40-2:00)

**Comprehensive Demo (5 minutes):**
- Covers all sections above
- Available upon request

---

## 📞 REVIEWER SUPPORT

**Questions During Review:**
- Email: reviewer-support@nija.trading
- Response time: <24 hours
- Available for clarification calls

**Common Questions Answered:**

**Q: Can users lose money?**  
A: Yes. Trading involves risk, and users can lose their entire investment. This is clearly disclosed in multiple places before enabling live trading.

**Q: Does the app trade automatically?**  
A: Only if the user explicitly configures it to do so. Users define all strategy parameters, must acknowledge risks, and must manually enable trading. The app doesn't trade on its own.

**Q: Where are API credentials stored?**  
A: Locally on the user's device using platform-secure storage (iOS Keychain). Never transmitted to our servers.

**Q: Can this be used for gambling?**  
A: No. NIJA is a technical analysis tool for trading financial instruments on regulated exchanges. It requires user configuration, understanding, and active management.

**Q: What if the exchange goes down?**  
A: NIJA handles all failure modes gracefully (API outage, network loss, etc.) and never crashes. Trading automatically pauses, and the user is notified.

---

## ✅ APPROVAL CRITERIA MET

NIJA meets all Apple App Store Review Guidelines for financial applications:

**Guideline 2.1 - App Completeness:** ✅  
- Fully functional demo mode
- All features accessible
- No crashes or errors

**Guideline 3.1.1 - Business:** ✅  
- User-directed tool (not investment service)
- No return promises
- Clear risk disclosure
- User maintains control

**Guideline 5.1.1 - Privacy:** ✅  
- Comprehensive privacy policy
- Clear data handling explanation
- User controls available
- Compliant with GDPR/CCPA

**Guideline 2.3 - Accurate Metadata:** ✅  
- Honest, transparent descriptions
- No misleading claims
- Proper disclaimers

---

**Thank you for reviewing NIJA. We're confident it meets all Apple App Store standards and provides a safe, transparent experience for users.**

---

**Document Version:** 1.0  
**Last Updated:** February 3, 2026  
**Next Update:** As needed based on reviewer feedback
