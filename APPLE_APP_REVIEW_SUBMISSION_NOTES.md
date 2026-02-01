# App Review Notes for NIJA - Automated Crypto Trading

**Submission Contact:** support@nija.app  
**App Category:** Finance  
**Age Rating:** 17+  
**Review Date:** February 2026

---

## For the App Review Team

Thank you for reviewing NIJA. This document addresses common questions about financial apps and explains how NIJA complies with Apple's App Store guidelines.

---

## What NIJA Is

**NIJA is a trading automation tool** that executes cryptocurrency trades on users' existing exchange accounts using algorithmic analysis.

**Think of it as:** Software that runs a trading algorithm on behalf of the user - similar to how a smart thermostat automates temperature control based on programmed logic.

---

## How NIJA Works (Simple Explanation)

1. **User connects their exchange account** (Coinbase, Kraken, etc.) by entering API credentials
2. **User activates trading** after reviewing risk disclaimers
3. **NIJA's algorithm runs independently on user's account:**
   - Scans cryptocurrency markets every ~2.5 minutes
   - Evaluates entry/exit criteria based on technical indicators (RSI, moving averages)
   - Executes trades when conditions are met AND risk checks pass
4. **User maintains full control** - can pause/stop anytime, revoke API access via exchange

**Critical Point:** NIJA never holds user funds. All money stays on the user's exchange account.

---

## Independent Trading Model (KEY FOR REVIEW)

### What This Means

**Each account evaluates markets independently and makes its own trading decisions.**

- Account A scans markets → evaluates conditions → executes trade (if approved)
- Account B scans markets → evaluates conditions → executes trade (if approved)
- Same algorithm, independent execution, different results

### Why Results Differ Between Users

Users are explicitly informed that results WILL differ because:

1. **Timing Variations**
   - Network latency (few milliseconds difference = different prices)
   - API response times vary
   - Each account scans on its own schedule

2. **Account-Specific Factors**
   - Balance size affects position sizing
   - Existing positions affect new trade decisions
   - User's risk settings affect trade approval
   - Available capital determines position size

3. **Market Conditions**
   - Price changes between executions
   - Liquidity varies by second
   - Slippage affects fill prices

**User Education:** We created a comprehensive FAQ ("Why do my trades differ from others?") that explains this transparently.

---

## What NIJA Does NOT Do (Critical Distinctions)

### ❌ NOT Copy Trading
- **Copy Trading:** One account replicates trades from another account
- **NIJA:** Each account runs the same algorithm independently
- **Why Different:** No account "follows" another; each evaluates markets itself

### ❌ NOT Signal Distribution
- **Signal Distribution:** Platform sends trade signals to users who execute them
- **NIJA:** No signals sent between accounts; each account analyzes markets independently
- **Why Different:** No signal transmission; independent market evaluation

### ❌ NOT Synchronized Execution
- **Synchronized:** Multiple accounts execute at the exact same time
- **NIJA:** Each account executes when ITS conditions are met
- **Why Different:** Independent timing based on each account's scan cycle and risk approval

### ❌ NOT A Platform Account Controlling Users
- **Platform Control:** One "master" account makes decisions, users follow
- **NIJA:** No account controls another; each account operates independently
- **Why Different:** No hierarchy; all accounts evaluate independently using risk-gated execution

---

## Risk Disclosures (Required by Apple)

### Where We Show Risk Warnings

1. **First Launch Screen**
   - Explains substantial risk of loss
   - Lists risks: loss of capital, volatility, no guarantees
   - Requires acknowledgment before proceeding

2. **Strategy Activation Screen**
   - Shows current account balance
   - Explains what will happen when activated
   - Requires explicit opt-in checkboxes
   - Warning: "You may lose money"

3. **Daily Notifications**
   - Reminder: "Past results ≠ future performance"
   - Encourages regular monitoring

4. **Settings Screen**
   - Persistent disclaimer about independent trading
   - Links to FAQ and risk documentation

### Key Risk Messages

✅ "Substantial risk of loss - you may lose all invested capital"  
✅ "No guaranteed profits"  
✅ "Past performance does not predict future results"  
✅ "Results may differ per account"  
✅ "Not financial advice - you are responsible for trading decisions"  
✅ "Only invest what you can afford to lose"

---

## NOT Financial Advice (Required Clarification)

**NIJA is software, NOT a financial advisor.**

### What We Don't Do:
- ❌ Provide personalized investment advice
- ❌ Recommend specific investments
- ❌ Act as a broker or dealer
- ❌ Provide financial planning services
- ❌ Guarantee returns

### What We Are:
- ✅ Algorithmic trading automation software
- ✅ Tool that executes pre-programmed strategy
- ✅ User makes decision to use the tool
- ✅ User responsible for all trading outcomes

**Analogy:** Like TurboTax (software tool for taxes) vs. a CPA (professional advisor). NIJA is the tool, not the advisor.

---

## User Control & Fund Security

### User Maintains Control

1. **Funds Never Touch Our Servers**
   - Money stays on user's exchange account
   - We never custody or hold funds
   - We can't withdraw funds (API permission explicitly denied)

2. **User Can Stop Anytime**
   - Pause/resume button in app
   - Revoke API access via exchange (instant cutoff)
   - Close positions manually via exchange

3. **API Permissions (Least Privilege)**
   - ✅ Read balance
   - ✅ Read positions
   - ✅ Execute trades
   - ✅ Close positions
   - ❌ **NEVER** withdraw funds

### If User Loses Phone/Access
- User logs into exchange account directly
- User revokes NIJA's API key
- NIJA immediately loses all access
- User retains full control of funds

---

## Age & Geographic Restrictions

### Age Rating: 17+

**Reason:** Financial risk, potential for monetary loss, requires mature judgment

**Age Gate:**
- Users must confirm 18+ years old (21+ where required)
- Checkbox acknowledgment during onboarding
- Enforced before any trading can begin

### Geographic Restrictions

**User Responsibility:**
- Users must confirm crypto trading is legal in their jurisdiction
- Warning shown about geographic restrictions
- Users acknowledge local law compliance

**Not Available Where Prohibited:**
- App can be restricted by region via App Store
- Clear disclaimer: "May not be legal in all jurisdictions"

---

## Technical Architecture (For Verification)

### API Integration
```
User's Phone → HTTPS → Exchange API (Coinbase/Kraken)
              ↑
           NIJA App
```

**No Intermediary Servers for Trading**
- Direct communication between app and exchange
- All trades execute on user's account
- No NIJA server in the middle

### Data Storage
- API credentials: Encrypted on device
- Trade history: Cached locally for performance
- No sensitive data sent to third parties
- User can delete all data anytime

---

## Common Review Questions (Anticipated)

### Q: "Is this copy trading?"
**A:** No. Copy trading is when Account A copies trades from Account B. NIJA has each account run the same algorithm independently. Same algorithm ≠ copying trades. Each account makes its own decisions based on its own market scan and risk evaluation.

### Q: "Why would results differ if they use the same algorithm?"
**A:** Because of timing (market scans happen at slightly different times), account size (position sizes scale to balance), and market conditions (prices change between executions). We're transparent about this - it's explained in our FAQ and disclaimers.

### Q: "Are you providing financial advice?"
**A:** No. We provide software that automates a trading strategy. The user decides whether to use the software. We don't tell users what to invest in - the algorithm analyzes markets automatically. It's software automation, not advice.

### Q: "What if users lose money?"
**A:** Trading involves risk of loss. We show comprehensive warnings before activation and in daily notifications. We recommend starting small, we don't guarantee profits, and we clearly state users can lose money. We meet financial app disclosure requirements.

### Q: "Do you hold user funds?"
**A:** No. Funds stay on user's exchange account. We only have trading API access (can't withdraw). User maintains custody and can revoke access instantly via their exchange.

---

## Compliance Checklist

### Apple Financial App Requirements:

✅ **Clear risk disclosure** - Multiple warnings throughout app  
✅ **No guaranteed returns** - Explicitly stated in all disclaimers  
✅ **Transparent operation** - Independent trading model clearly explained  
✅ **User control** - Users maintain control via exchange accounts  
✅ **Age restrictions** - 17+ rating, 18+/21+ age gate enforced  
✅ **Geographic compliance** - User must confirm legal jurisdiction  
✅ **Not financial advice** - Clearly stated throughout  
✅ **Risk warnings visible** - First launch, activation, daily, settings  
✅ **Terms of service** - Complete ToS included  
✅ **Privacy policy** - Privacy policy included  
✅ **No misleading claims** - Transparent about result variations  
✅ **Educational content** - FAQ explains trading model  

---

## Testing for Review Team

### Demo Account Available
If you need a demo account to review functionality, please contact support@nija.app and we'll provide:
- Test API credentials (paper trading mode)
- Walkthrough of disclaimer screens
- Example of independent trading operation

### Review App Flow
1. Launch app → See first launch disclaimer
2. Enter API credentials → See security warnings
3. Activate trading → See activation screen with risks
4. View settings → See persistent disclaimer
5. Check FAQ → See "Why trades differ" explanation

---

## Supporting Documentation Included

1. **USER_FAQ.md** - Explains "Why do my trades differ from others?"
2. **APP_STORE_DISCLAIMER.md** - All risk disclaimers and legal text
3. **TERMS_OF_SERVICE.md** - Complete terms of service
4. **PRIVACY_POLICY.md** - Privacy policy

---

## Key Terminology (Our Language)

We consistently use these terms throughout the app:

- ✅ **"Evaluates independently"** - How accounts operate
- ✅ **"Risk-gated execution"** - How trades are approved
- ✅ **"Results may differ per account"** - User expectation setting
- ✅ **"Independent market analysis"** - How decisions are made
- ✅ **"Account-specific factors"** - Why results vary

We avoid these terms:
- ❌ "Copy trading"
- ❌ "Follow trades"
- ❌ "Signal distribution"
- ❌ "Synchronized execution"
- ❌ "Platform account leads users"

---

## Summary for Quick Review

**What:** Trading automation software  
**How:** Runs algorithm on user's exchange account via API  
**Funds:** Stay on user's exchange, never held by app  
**Model:** Independent evaluation per account (NOT copy trading)  
**Results:** Differ between users (clearly disclosed)  
**Risks:** Clearly disclosed at launch, activation, daily  
**Advice:** NOT financial advice - it's software  
**Control:** User maintains full control via exchange  
**Age:** 17+ rating, 18+/21+ gate  
**Compliance:** ✅ All Apple financial app requirements met  

---

## Contact for Questions

**Email:** support@nija.app  
**Response Time:** Within 24 hours  
**Available For:** Clarifications, demo account, technical questions

Thank you for your thorough review. We've designed NIJA to meet Apple's high standards while providing genuine value to users who want trading automation.

---

**Document Version:** 1.0  
**Last Updated:** February 1, 2026  
**Prepared For:** Apple App Review Team
