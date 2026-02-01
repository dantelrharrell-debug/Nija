# Apple App Review - Financial Functionality Explanation

**App Name:** NIJA - Automated Crypto Trading  
**Category:** Finance  
**Submission Date:** February 2026  
**Review Team:** Apple App Review

---

## Executive Summary

NIJA is an automated cryptocurrency trading application that uses algorithmic analysis to execute trades on users' existing exchange accounts. The app operates as a **trading automation tool**, NOT as a financial advisor, broker, or copy trading service.

**Key Points for Review:**
- ✅ Independent trading model (no copy trading, no signal distribution)
- ✅ User maintains full control of their funds (funds never touch our servers)
- ✅ Comprehensive risk disclaimers throughout the app
- ✅ Transparent about how results may differ between users
- ✅ Age-gated (18+, 21+ where required)
- ✅ Geographic restriction compliance

---

## How NIJA Works

### 1. User Connection Model

**Users connect their own exchange accounts:**
1. User creates account on supported exchange (Coinbase, Kraken, etc.)
2. User generates API credentials on exchange (read + trade permissions only)
3. User enters API credentials into NIJA app
4. NIJA connects to user's exchange account via API
5. NIJA executes trades on user's account based on algorithmic analysis

**Important:** 
- NIJA **NEVER** holds user funds
- NIJA **NEVER** has withdrawal permissions
- Users can revoke API access at any time via their exchange
- Users maintain full control via their exchange account

### 2. Independent Trading Model

**Each account operates independently:**

- **Market Analysis:** Each account scans cryptocurrency markets independently every ~2.5 minutes
- **Decision Making:** Each account evaluates entry/exit criteria independently using the same algorithm
- **Risk Management:** Each account applies risk checks based on its specific balance, positions, and settings
- **Execution:** Each account executes trades independently when conditions are met

**What NIJA Does NOT Do:**
- ❌ Does NOT copy trades between accounts
- ❌ Does NOT synchronize execution across accounts
- ❌ Does NOT distribute trade signals between users
- ❌ Does NOT have a "platform account" that controls user accounts
- ❌ Does NOT promise identical results for all users

### 3. Why Trading Results Differ Between Users

**This is a critical transparency point for Apple's review:**

Users are clearly informed that their results WILL differ from other users because:

1. **Timing Variations**
   - Network latency affects when market data is received
   - API response times vary between requests
   - Each account scans on its own independent schedule
   - Market conditions change between scans

2. **Account-Specific Factors**
   - **Balance:** Position sizes scale to account balance
   - **Existing Positions:** Open positions affect new entry decisions
   - **Risk Settings:** User's risk tolerance affects trade approval
   - **Capital Availability:** Free capital determines position sizing

3. **Execution Differences**
   - Fill prices vary based on market conditions at execution time
   - Slippage affects actual entry/exit prices
   - Exchange order book depth impacts execution quality

**User Education:**
- In-app FAQ explains "Why do my trades differ from others?"
- Disclaimers shown during onboarding and before activation
- Clear messaging: "Results may differ per account"

---

## Financial Risk Disclosures

### Required Disclaimers (Shown Throughout App)

**1. First Launch Screen:**
- Explains independent trading model
- Lists risks (loss of capital, volatility, no guarantees)
- Requires user acknowledgment before proceeding
- Age verification (18+ or 21+)
- Geographic compliance confirmation

**2. Strategy Activation Screen:**
- Shows account balance and exchange
- Explains what will happen when trading is activated
- Reinforces independent trading model
- Requires explicit opt-in checkboxes
- Recommends starting small and monitoring

**3. Daily Notifications:**
- Remind users of independent trading model
- Include disclaimer: "Past results ≠ future performance"
- Encourage regular monitoring

**4. Settings Screen:**
- Persistent disclaimer about independent trading
- Explains why accounts operate independently
- Links to FAQ and documentation

### Risk Warnings Include:

- ✅ Substantial risk of loss
- ✅ Potential to lose all invested capital
- ✅ No guaranteed profits
- ✅ Past performance does not predict future results
- ✅ Cryptocurrency volatility
- ✅ Market risks
- ✅ Not financial advice
- ✅ User responsibility for all trading decisions

---

## Regulatory Compliance

### What NIJA Is:
- ✅ Software tool for trading automation
- ✅ Algorithmic trading assistant
- ✅ Trading strategy execution engine

### What NIJA Is NOT:
- ❌ Financial advisor
- ❌ Investment advisor
- ❌ Broker or dealer
- ❌ Financial planning service
- ❌ Copy trading platform
- ❌ Signal distribution service
- ❌ Managed account service

### User Agreement Terms:
- Users acknowledge they are responsible for trading decisions
- Users acknowledge NIJA is software, not advice
- Users acknowledge substantial risk of loss
- Users acknowledge no guaranteed returns
- Users acknowledge independent trading model
- Users must be 18+ (21+ where required)
- Users must verify cryptocurrency trading is legal in their jurisdiction

---

## Age Rating & Restrictions

### Appropriate Age Rating: **17+**

**Reason:** Financial risk, potential for significant monetary loss, requires mature judgment

**Content Descriptors:**
- Financial Transactions: YES (cryptocurrency trading)
- Gambling & Contests: NO
- Unrestricted Web Access: NO
- Simulated Gambling: NO

### Age Verification:
- Users must confirm 18+ (or 21+ where required) during onboarding
- Checkbox acknowledgment required before proceeding
- Enforced before any API credentials can be entered

### Geographic Restrictions:
- Users must confirm cryptocurrency trading is legal in their jurisdiction
- Warning displayed about geographic restrictions
- Users acknowledge responsibility for local law compliance

---

## Technical Implementation

### API Permissions Required:
**From User's Exchange Account:**
- ✅ Query Funds (read balance)
- ✅ Query Open Orders & Trades (read positions)
- ✅ Query Closed Orders & Trades (read history)
- ✅ Create & Modify Orders (execute trades)
- ✅ Cancel/Close Orders (close positions)
- ❌ **NEVER** Withdraw Funds (explicitly denied)

### Data Storage:
- API credentials stored securely on device (encrypted)
- Trade history cached locally for performance tracking
- No sensitive data transmitted to third-party servers
- Users can delete all data at any time

### Network Communication:
- HTTPS only for all API communications
- Direct communication between app and exchange APIs
- No intermediary servers for trade execution
- All trades execute directly on user's exchange account

---

## User Protection Features

### 1. Risk Management
- Position size limits based on account balance
- Stop loss enforcement on all positions
- Maximum daily loss limits (circuit breakers)
- Drawdown protection
- Leverage monitoring

### 2. Transparency
- Complete trade history visible in app
- Real-time position tracking
- P&L calculation and display
- Fee tracking and reporting
- Execution logs

### 3. User Control
- Users can pause/resume trading at any time
- Users can adjust risk settings
- Users can close positions manually
- Users can revoke API access anytime via exchange
- Users can delete account and all data

### 4. Educational Resources
- In-app FAQ explaining independent trading
- Strategy documentation
- Risk education materials
- Example scenarios showing potential outcomes
- Links to exchange security best practices

---

## Comparison to Prohibited Models

### ❌ Copy Trading (PROHIBITED - We Do NOT Do This)
- One account copies trades from another account
- "Master" account controls "follower" accounts
- Signal distribution between accounts
- Synchronized execution
- **Why prohibited:** Creates managed account relationship, requires broker-dealer license

### ✅ Independent Trading (NIJA's Model - Compliant)
- Each account evaluates markets independently
- Same algorithm, independent execution
- No account controls another account
- No signal distribution
- Results naturally differ due to timing and account factors
- **Why compliant:** Software tool, user maintains control, transparent operation

---

## Questions App Review May Ask

### Q: "How is this different from copy trading?"
**A:** Copy trading involves one account replicating trades from another account. NIJA does NOT do this. Each account runs the same algorithm independently and makes its own trading decisions based on its own market analysis, balance, and risk profile. Think of it like everyone using the same GPS app - same routing algorithm, but your actual route depends on where you start, current traffic when YOU drive, and your preferences.

### Q: "Why would someone use this if results differ?"
**A:** Users want algorithmic trading automation without needing to build their own system. The algorithm is sophisticated (dual RSI strategy, risk management, profit targeting) and users benefit from the automation even though results vary. We're transparent that results differ - this is a feature (transparency) not a bug.

### Q: "Are you providing financial advice?"
**A:** No. NIJA is a software tool that executes a pre-programmed algorithmic strategy. We do not provide personalized financial advice, investment recommendations, or act as a financial advisor. Users make the decision to use the software and accept full responsibility for trading outcomes.

### Q: "What if users lose money?"
**A:** Trading involves risk of loss. We display comprehensive risk warnings throughout the app, require acknowledgment of risks before activation, and recommend starting with small amounts. Users are repeatedly informed they can lose money and should only invest what they can afford to lose. We do NOT guarantee profits or suggest users can't lose money.

### Q: "Do you hold user funds?"
**A:** No. NIJA never holds, custodies, or has withdrawal access to user funds. Users maintain funds on their exchange account. NIJA only has trading permissions via API keys. Users can revoke access at any time via their exchange settings.

### Q: "What about geographic restrictions?"
**A:** Users must confirm during onboarding that cryptocurrency trading is legal in their jurisdiction. We display warnings about geographic restrictions. Users acknowledge responsibility for compliance with local laws. The app can be made unavailable in restricted regions via App Store geographic controls.

---

## Supporting Documentation

**Included in App Submission:**

1. **USER_FAQ.md** - Comprehensive FAQ explaining independent trading
2. **APP_STORE_DISCLAIMER.md** - All disclaimers and legal language
3. **TERMS_OF_SERVICE.md** - Complete terms of service
4. **PRIVACY_POLICY.md** - Privacy policy and data handling

**Available for Review Team:**

- Screenshots of all disclaimer screens
- Video walkthrough of onboarding flow
- Documentation of independent trading model
- Risk disclosure placements
- Age gate implementation

---

## Compliance Checklist

### Apple Financial App Requirements:

- [x] **Clear disclosure of risks** - ✅ Multiple disclaimers throughout app
- [x] **No guaranteed returns** - ✅ Explicitly stated in all disclaimers
- [x] **Transparent operation** - ✅ Independent trading model clearly explained
- [x] **User maintains control** - ✅ Users control their exchange accounts
- [x] **Age restrictions** - ✅ 17+ rating, 18+/21+ age gate
- [x] **Geographic compliance** - ✅ User must confirm legal jurisdiction
- [x] **Not financial advice** - ✅ Clearly stated throughout app
- [x] **Risk warnings visible** - ✅ First launch, activation, daily notifications, settings
- [x] **Terms of service** - ✅ Comprehensive ToS included
- [x] **Privacy policy** - ✅ Privacy policy included
- [x] **No misleading claims** - ✅ Transparent about result variations
- [x] **Educational content** - ✅ FAQ and documentation provided

---

## Contact for Review Questions

**Developer Contact:** support@nija.app  
**Review Questions:** Please reference this document and included documentation  
**Demo Account:** Available upon request for App Review team testing

---

## Conclusion

NIJA is a **transparent, compliant trading automation tool** that:

1. **Empowers users** with algorithmic trading capabilities
2. **Maintains user control** over their funds and accounts
3. **Clearly discloses risks** throughout the user experience
4. **Uses an independent trading model** (not copy trading or signal distribution)
5. **Educates users** about why results differ between accounts
6. **Complies with age and geographic requirements**
7. **Does not provide financial advice** - it's a software tool

We've designed NIJA to meet Apple's high standards for financial applications while providing genuine value to users who want trading automation.

Thank you for your consideration.

---

*Last Updated: February 1, 2026*  
*Document Version: 1.0*
