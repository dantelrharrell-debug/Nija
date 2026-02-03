# Apple App Store Review Guidelines - NIJA Onboarding Mapping

**Purpose**: Maps NIJA's onboarding sections and UI copy to specific Apple App Store Review Guidelines  
**Last Updated**: February 3, 2026  
**Version**: 1.0

---

## Document Overview

This document provides explicit mappings between NIJA's onboarding flow, UI components, and specific sections of Apple's App Store Review Guidelines. Use this as a compliance reference during development and App Review responses.

---

## Table of Contents

1. [Financial App Guidelines (§2.5.6)](#financial-app-guidelines-256)
2. [Accurate Metadata (§2.3)](#accurate-metadata-23)
3. [Business Model (§3.1.1)](#business-model-311)
4. [Subscriptions (§3.1.2)](#subscriptions-312)
5. [Privacy (§5.1.1)](#privacy-511)
6. [Data Use and Sharing (§5.1.2)](#data-use-and-sharing-512)
7. [Design Guidelines (§4.0)](#design-guidelines-40)
8. [Safety (§1.4)](#safety-14)

---

## Financial App Guidelines (§2.5.6)

**Apple Guideline**: Apps that facilitate trading in financial instruments must comply with applicable law and include appropriate disclaimers, disclosures, and user controls.

### NIJA Implementation Mapping

#### § 2.5.6(a) - Risk Disclosures

**Requirement**: Apps must clearly disclose financial risks to users.

**NIJA Implementation**:

| Component | Location | Apple-Compliant Copy |
|-----------|----------|---------------------|
| **First Launch Screen** | Welcome Screen (Screen 1) | "⚠️ Trading involves risk of loss. Past performance does not guarantee future results." |
| **Risk Acknowledgment Dialog** | Pre-activation modal | Full risk disclosure with 5 required checkboxes (see APPLE_UI_WORDING_GUIDE.md lines 68-102) |
| **Status Banner** | Persistent top banner | Mode indicators with risk context (lines 140-158) |
| **Settings Screen** | Settings page footer | Persistent disclaimer (lines 369-376) |
| **Education Mode Banner** | Dashboard header | "📚 Education Mode - Simulated Trading. All balances and trades are simulated with virtual money. This is not real money." |

**File References**:
- `APPLE_UI_WORDING_GUIDE.md` lines 68-102 (Risk Acknowledgment Dialog)
- `EDUCATION_MODE_ONBOARDING.md` lines 96-136 (Education Mode Active screen)
- `APPLE_APP_REVIEW_FINANCIAL_FUNCTIONALITY.md` lines 92-130 (Financial Risk Disclosures)

---

#### § 2.5.6(b) - No Guaranteed Returns

**Requirement**: Apps must not promise or guarantee financial returns.

**NIJA Implementation**:

| Prohibited Language | Apple-Compliant Alternative | Location |
|---------------------|----------------------------|----------|
| ❌ "Guaranteed profits" | ✅ "Trading involves risk of loss" | All screens |
| ❌ "Passive income" | ✅ "User-directed trading tool" | Welcome screen |
| ❌ "AI trades for you" | ✅ "You configure your own trading rules" | Strategy configuration |
| ❌ "Consistent returns" | ✅ "Past performance does not guarantee future results" | Performance display |

**Forbidden Phrases List**: 
- See `APPLE_UI_WORDING_GUIDE.md` lines 346-365 (complete list of 15 prohibited phrases)

**File References**:
- `APPLE_UI_WORDING_GUIDE.md` lines 196-220 (Performance Display section)
- `APPLE_APP_REVIEW_FINANCIAL_FUNCTIONALITY.md` lines 120-130 (Risk Warnings Include)

---

#### § 2.5.6(c) - User Control and Agency

**Requirement**: Users must maintain control over trading decisions and be able to stop at any time.

**NIJA Implementation**:

| Control Mechanism | UI Component | Copy |
|------------------|--------------|------|
| **Emergency Stop** | Kill switch button | "🚨 EMERGENCY STOP ACTIVATED" (APPLE_UI_WORDING_GUIDE.md lines 249-278) |
| **Trading Toggle** | Main dashboard toggle | "Enable User-Directed Trading" (lines 21-40) |
| **Mode Selection** | Mode picker | "○ Simulation Mode / ○ Independent Trading Mode" (lines 42-64) |
| **Pause/Resume** | Status banner | "🟢 Independent Trading Active • User-Directed • [⏸]" (line 157) |

**Trust Reinforcement Messages**:
- "Your funds never touch our platform. Trades execute directly on your broker." (EDUCATION_MODE_ONBOARDING.md line 47-48)
- "You're always in control. You can stop trading anytime." (line 50-51)
- "You are solely responsible for all trading activity." (APPLE_UI_WORDING_GUIDE.md line 62)

**File References**:
- `APPLE_UI_WORDING_GUIDE.md` lines 21-40 (Main Trading Toggle)
- `APPLE_UI_WORDING_GUIDE.md` lines 249-278 (Kill Switch Activation)
- `APPLE_APP_REVIEW_FINANCIAL_FUNCTIONALITY.md` lines 225-237 (User Control section)

---

#### § 2.5.6(d) - Educational Content

**Requirement**: Financial apps should provide educational resources about risks and functionality.

**NIJA Implementation**:

| Educational Component | Purpose | Guideline Compliance |
|----------------------|---------|---------------------|
| **Education Mode** | Risk-free learning environment | Provides $10,000 simulated balance for practice (EDUCATION_MODE_ONBOARDING.md lines 14-35) |
| **Progress Tracking** | User skill development | Milestones: First Trade, 10 Trades, Profitability, Ready for Live (lines 75-89) |
| **Graduation Criteria** | Ensures user competency | Requires 10+ trades, 50%+ win rate, positive P&L before live trading (lines 160-195) |
| **FAQ Section** | Risk and strategy education | "Why do my trades differ from others?" (APPLE_APP_REVIEW_FINANCIAL_FUNCTIONALITY.md lines 86-88) |

**File References**:
- `EDUCATION_MODE_ONBOARDING.md` entire document
- `APPLE_APP_REVIEW_FINANCIAL_FUNCTIONALITY.md` lines 234-237 (Educational Resources)

---

## Accurate Metadata (§2.3)

**Apple Guideline**: App descriptions, screenshots, and previews should accurately represent the app's functionality.

### NIJA Implementation Mapping

#### § 2.3.1 - App Description Accuracy

**Requirement**: Marketing text must not contain misleading claims.

**NIJA Compliance**:

**App Store Description Template**:
```
NIJA is a user-directed trading tool that executes trades based on 
YOUR strategy and YOUR decisions.

✅ You configure your own trading rules
✅ You control when and how trades execute
✅ You are responsible for all trading activity
✅ Your credentials stay on your device

NIJA does not:
❌ Guarantee profits or returns
❌ Provide investment advice
❌ Trade automatically without your configuration
❌ Access your credentials without permission

⚠️ Trading involves risk of loss. Past performance does not 
   guarantee future results.
```

**File References**:
- `APPLE_UI_WORDING_GUIDE.md` lines 379-386 (App description/marketing)
- `APPLE_APP_REVIEW_FINANCIAL_FUNCTIONALITY.md` lines 15-26 (Executive Summary)

---

#### § 2.3.8 - Metadata Relevance

**Requirement**: Keywords and categories must be relevant to app functionality.

**NIJA Compliance**:

| Metadata Field | Approved Content | Prohibited Content |
|----------------|------------------|-------------------|
| **Primary Category** | Finance | ❌ Games, Entertainment |
| **Keywords** | "trading automation", "algorithmic trading", "crypto trading tool" | ❌ "passive income", "guaranteed profits", "get rich" |
| **Age Rating** | 17+ (Financial Transactions: YES) | ❌ Lower age ratings |

**File References**:
- `APPLE_APP_REVIEW_FINANCIAL_FUNCTIONALITY.md` lines 162-181 (Age Rating & Restrictions)

---

## Business Model (§3.1.1)

**Apple Guideline**: Apps must use approved business models and clearly communicate costs.

### NIJA Implementation Mapping

#### § 3.1.1(a) - Transparency

**Requirement**: Apps must clearly disclose what users are purchasing.

**NIJA Implementation**:

| Business Model Element | Disclosure Location | Copy |
|------------------------|-------------------|------|
| **Software Tool** | Welcome screen | "NIJA is a user-directed trading tool" (APPLE_UI_WORDING_GUIDE.md line 114) |
| **No Hidden Fees** | Settings → Legal | Complete fee disclosure in Terms of Service |
| **Exchange Fees** | Strategy activation | "Understanding exchange fees and costs" (line 95) |

**What NIJA Is NOT** (to avoid regulated services):
- ❌ Financial advisor
- ❌ Investment advisor
- ❌ Broker or dealer
- ❌ Copy trading platform

**File References**:
- `APPLE_APP_REVIEW_FINANCIAL_FUNCTIONALITY.md` lines 135-148 (What NIJA Is / Is NOT)

---

## Subscriptions (§3.1.2)

**Apple Guideline**: Subscriptions must clearly communicate value and renewal terms.

### NIJA Implementation Mapping

*(Note: Only applicable if subscription model is implemented)*

#### § 3.1.2(a) - Clear Value Proposition

**Requirement**: Subscription benefits must be clearly stated.

**NIJA Compliance Template**:
```
Subscription Tiers:

Basic (Free):
  • Education Mode only
  • $10,000 simulated balance
  • All features with virtual money

Pro ($X/month):
  • Independent Trading Mode
  • Connect real broker accounts
  • Advanced analytics
  • Priority support

⚠️ Auto-renews monthly. Cancel anytime.
⚠️ Trading involves risk. Subscription fee is separate from 
   trading capital and exchange fees.
```

**File References**:
- `SUBSCRIPTION_SYSTEM.md` (if implemented)

---

## Privacy (§5.1.1)

**Apple Guideline**: Apps must clearly disclose data collection and use.

### NIJA Implementation Mapping

#### § 5.1.1(i) - Data Collection Transparency

**Requirement**: Apps must have a privacy policy and declare what data is collected.

**NIJA Implementation**:

| Data Type | Collection | Storage | Apple Privacy Label |
|-----------|-----------|---------|-------------------|
| **API Credentials** | ✅ User provides | 🔐 Encrypted on device | "Financial Info" |
| **Trade History** | ✅ Cached for analytics | 📱 Local only | "Financial Info" |
| **Account Balance** | ✅ Read from exchange | 📱 Local only | "Financial Info" |
| **User Identity** | ❌ Not collected | ❌ Not stored | None |
| **Analytics** | ❌ Anonymous only | ❌ Not linked to user | None |

**Privacy Messaging**:
- "🔐 Your API credentials stay on your device" (APPLE_UI_WORDING_GUIDE.md line 117)
- "No sensitive data transmitted to third-party servers" (APPLE_APP_REVIEW_FINANCIAL_FUNCTIONALITY.md line 198)

**File References**:
- `PRIVACY_POLICY.md`
- `APPLE_APP_REVIEW_FINANCIAL_FUNCTIONALITY.md` lines 195-205 (Data Storage)

---

#### § 5.1.1(ii) - Data Use Limitations

**Requirement**: Data must only be used for disclosed purposes.

**NIJA Compliance**:

**API Credentials Usage**:
- ✅ Execute trades on user's exchange account
- ✅ Query balances and positions
- ✅ Retrieve market data
- ❌ NEVER withdraw funds
- ❌ NEVER shared with third parties

**File References**:
- `APPLE_APP_REVIEW_FINANCIAL_FUNCTIONALITY.md` lines 186-194 (API Permissions Required)

---

## Data Use and Sharing (§5.1.2)

**Apple Guideline**: Apps must obtain consent before sharing user data.

### NIJA Implementation Mapping

#### § 5.1.2(i) - Third-Party Sharing

**Requirement**: Apps must disclose and obtain consent for data sharing.

**NIJA Implementation**:

**Data Sharing Policy**:
- ✅ Direct API communication: NIJA ↔ Exchange (no intermediary)
- ❌ No third-party analytics services
- ❌ No advertising networks
- ❌ No data brokers
- ❌ No user tracking

**Messaging**:
- "Trades execute directly on your broker account" (EDUCATION_MODE_ONBOARDING.md line 48)
- "All trades execute directly on user's exchange account" (APPLE_APP_REVIEW_FINANCIAL_FUNCTIONALITY.md line 205)

**File References**:
- `APPLE_APP_REVIEW_FINANCIAL_FUNCTIONALITY.md` lines 201-205 (Network Communication)

---

## Design Guidelines (§4.0)

**Apple Guideline**: Apps must provide a high-quality user experience.

### NIJA Implementation Mapping

#### § 4.2 - Minimum Functionality

**Requirement**: Apps must be functional and provide value.

**NIJA Compliance**:

**Core Functionality**:
1. Education Mode - Complete trading simulation
2. Strategy Configuration - User-controlled parameters
3. Live Trading - Real exchange integration
4. Risk Management - Stop losses, position limits
5. Analytics - Performance tracking

**File References**:
- `EDUCATION_MODE_ONBOARDING.md` lines 14-35 (Layer 1: Education Mode features)

---

#### § 4.5.1 - Location Services

**Requirement**: Location data must be necessary for app functionality.

**NIJA Compliance**:
- ❌ Location services NOT used
- ✅ Geographic restrictions handled via user self-declaration

**Geographic Compliance**:
- "I confirm cryptocurrency trading is legal in my jurisdiction" (checkbox during onboarding)

**File References**:
- `APPLE_APP_REVIEW_FINANCIAL_FUNCTIONALITY.md` lines 177-179 (Geographic Restrictions)

---

## Safety (§1.4)

**Apple Guideline**: Apps must not encourage illegal activity or pose physical harm.

### NIJA Implementation Mapping

#### § 1.4.1 - Objectionable Content

**Requirement**: Apps must not contain content that encourages illegal behavior.

**NIJA Compliance**:

**Age Restrictions**:
- ✅ 17+ age rating
- ✅ Age gate: "Users must confirm 18+ (or 21+ where required)"
- ✅ Legal jurisdiction verification

**Compliance Messaging**:
- "Users must verify cryptocurrency trading is legal in their jurisdiction" (APPLE_APP_REVIEW_FINANCIAL_FUNCTIONALITY.md line 156)
- "Geographic restriction compliance" (line 25)

**File References**:
- `APPLE_APP_REVIEW_FINANCIAL_FUNCTIONALITY.md` lines 162-181 (Age Rating & Restrictions)

---

#### § 1.4.3 - "Enemies" or Targeting Specific Entities

**Requirement**: Apps must not encourage violence or discrimination.

**NIJA Compliance**:
- ✅ Financial tool only
- ✅ No social features
- ✅ No targeting or competitive elements against individuals
- ✅ No leaderboards that identify users

**File References**:
- `EDUCATION_MODE_ONBOARDING.md` lines 519-541 (Future Enhancements - note: leaderboards would be anonymous)

---

## Summary Compliance Matrix

| Apple Guideline | NIJA Compliance | Key Documents |
|-----------------|-----------------|---------------|
| **§2.5.6** Financial Apps | ✅ Full compliance | APPLE_APP_REVIEW_FINANCIAL_FUNCTIONALITY.md |
| **§2.3** Accurate Metadata | ✅ Honest marketing | APPLE_UI_WORDING_GUIDE.md |
| **§3.1.1** Business Model | ✅ Clear value prop | TERMS_OF_SERVICE.md |
| **§3.1.2** Subscriptions | ✅ Transparent terms | SUBSCRIPTION_SYSTEM.md |
| **§5.1.1** Privacy | ✅ Data minimization | PRIVACY_POLICY.md |
| **§5.1.2** Data Sharing | ✅ No third parties | APPLE_APP_REVIEW_FINANCIAL_FUNCTIONALITY.md |
| **§4.0** Design | ✅ High quality UX | EDUCATION_MODE_ONBOARDING.md |
| **§1.4** Safety | ✅ Age-gated, legal | APPLE_APP_REVIEW_FINANCIAL_FUNCTIONALITY.md |

---

## Appendix: Quick Reference Guide for Developers

### When Implementing New UI Components

**Checklist**:
1. ✅ Check APPLE_UI_WORDING_GUIDE.md for approved copy
2. ✅ Verify no forbidden phrases (lines 346-365)
3. ✅ Include risk disclaimer if showing financial data
4. ✅ Map to specific Apple Guideline in this document
5. ✅ Test on all iOS devices (iPhone SE to iPad Pro)

### When Responding to App Review Feedback

**Quick Links**:
- Financial functionality explanation → APPLE_APP_REVIEW_FINANCIAL_FUNCTIONALITY.md
- UI copy justification → APPLE_UI_WORDING_GUIDE.md
- Privacy policy → PRIVACY_POLICY.md
- Terms of service → TERMS_OF_SERVICE.md
- This compliance mapping → APPLE_GUIDELINES_MAPPING.md

### Required Documentation for Every App Submission

1. ✅ APPLE_APP_REVIEW_FINANCIAL_FUNCTIONALITY.md
2. ✅ APPLE_UI_WORDING_GUIDE.md
3. ✅ APPLE_GUIDELINES_MAPPING.md (this document)
4. ✅ PRIVACY_POLICY.md
5. ✅ TERMS_OF_SERVICE.md
6. ✅ Screenshots showing all disclaimers
7. ✅ Video walkthrough of onboarding flow

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | Feb 3, 2026 | Initial creation - comprehensive guideline mapping |

---

**For Questions**: Reference specific guideline sections in this document when discussing compliance.  
**Last Reviewed**: February 3, 2026  
**Next Review**: Before each App Store submission
