# Education Mode Onboarding - Implementation Guide

**Version**: 1.0  
**Date**: February 3, 2026  
**Status**: ✅ Implemented

## Overview

NIJA now features a three-layer onboarding UX that positions the product as an educational platform first, with an optional upgrade path to live trading. This architecture meets regulatory requirements and builds user trust.

---

## Three-Layer Architecture

### Layer 1: Education Mode (Default Entry Point)

**Purpose**: Learn trading without risk

**Features**:
- ✅ Simulated $10,000 balance
- ✅ All trading functionality with virtual money
- ✅ Real market data
- ✅ Progress tracking (win rate, profitability, risk control)
- ✅ Clear "Not Real Money" indicators throughout UI

**Access**: Automatic - all new users start here

**User Message**: 
> "Learn trading without risking real money"

**No Requirements**:
- ❌ No broker connection needed
- ❌ No real funds required
- ❌ No KYC needed

---

### Layer 2: Platform (Isolated & Internal)

**Purpose**: Trading engine that executes user strategies

**Characteristics**:
- Isolated execution per user
- Strategy logic protected (never exposed to API)
- Respects user mode (education vs live)
- Tracks progress and metrics

**User Control**:
- Users can start/stop trading
- Users can view statistics
- Users CANNOT access strategy parameters

---

### Layer 3: User Live Trading (Explicit Opt-In)

**Purpose**: Real money trading after user is ready

**Requirements**:
1. ✅ Demonstrated profitability in education mode
2. ✅ Minimum 10 trades completed
3. ✅ Win rate ≥ 50%
4. ✅ Positive total P&L
5. ✅ Explicit consent with risk acknowledgment
6. ✅ Broker account connected

**Upgrade Path**:
- User must explicitly opt-in
- Separate consent screen with checkboxes
- Clear warning copy about real money risk
- Cannot proceed without consent

**Trust Reinforcement Messages**:
- "Your funds never touch our platform"
- "Trades execute directly on your broker"
- "You're always in control"

---

## Onboarding Flow

### Step 1: Welcome Screen

**Screen Copy**:
```
🎓 Learn Trading Without Risking Real Money

Master algorithmic trading with our simulated environment

Features:
💰 $10,000 Simulated Balance
   Practice with virtual money. Learn without risk.

📊 Real Market Data
   Trade on live market conditions with simulated execution.

📈 Track Your Progress
   Monitor win rate, risk control, and profitability.

🎯 Upgrade When Ready
   Connect your broker and trade live after you've built confidence.

[Primary CTA: Start in Education Mode]

🔒 Your funds never touch our platform. Trades execute directly on your broker.
✨ You're always in control. You can stop trading anytime.
```

**Action**: Click "Start in Education Mode" → Go to Step 2

---

### Step 2: Education Mode Active

**Screen Copy**:
```
📚 Education Mode Active

You're Learning with Simulated Money
This is not real money. All trades are simulated for learning purposes.

Your Progress: [Progress bar]

Milestones:
⚪ Complete First Trade
⚪ Complete 10 Trades  
⚪ Achieve Profitability
⚪ Ready for Live Trading

[Continue to Dashboard]
```

**Features**:
- Progress bar showing completion percentage
- Milestone checklist
- Clear education mode badge
- "Not real money" disclaimer

**Action**: Click "Continue to Dashboard" → Dashboard with education mode active

---

### Step 3: Dashboard (Education Mode)

**Visual Indicators**:
- 📚 Education Mode banner at top
- "Simulated Balance (Not Real Money)" labels
- "All trades are simulated with virtual money" disclaimer
- No broker connection required

**Available Actions**:
- View progress
- Continue trading with simulated money
- [When ready] Upgrade to live trading button appears

---

### Step 4: Upgrade to Live Trading (Optional)

**Trigger**: Only shown when user meets graduation criteria:
- 10+ trades completed
- 50%+ win rate
- Positive total P&L

**Screen Copy**:
```
🎉 Congratulations! You're Ready

You've demonstrated consistent profitability in education mode.

Your Stats:
Win Rate: XX%
Total Trades: XX
Total P&L: $XX.XX

Want to Trade Live?
Connect your broker account and start trading with real money.

[Consent Checklist]
☐ I understand that live trading involves real financial risk
☐ I can afford to lose the capital I'm trading with
☐ I understand trades execute directly on my broker account
☐ I understand I'm always in control and can stop anytime

[Connect Broker & Go Live] (disabled until all checked)

[Stay in Education Mode]
```

**Required Actions**:
1. Check all consent boxes
2. Click "Connect Broker & Go Live"
3. Connect broker credentials
4. Trading mode automatically switches to live

---

## API Endpoints

### Get Onboarding Status
```
GET /api/user/onboarding/status
```

**Response**:
```json
{
  "success": true,
  "onboarding": {
    "mode": "education",
    "is_new_user": false,
    "show_welcome": false,
    "progress": {
      "total_trades": 15,
      "win_rate": 60.0,
      "total_pnl": 150.25,
      "progress_percentage": 80,
      "ready_for_live_trading": true
    }
  }
}
```

---

### Get User Mode
```
GET /api/user/mode
```

**Response**:
```json
{
  "success": true,
  "mode": "education",
  "education_mode": true,
  "consented_to_live_trading": false,
  "progress": { ... },
  "ready_for_upgrade": true
}
```

---

### Update Education Progress
```
POST /api/user/mode/education/progress
```

Syncs progress from paper trading account.

---

### Consent to Live Trading
```
POST /api/user/mode/live/consent

{
  "consent_confirmed": true,
  "risks_acknowledged": true
}
```

Records explicit user consent.

---

### Activate Live Trading
```
POST /api/user/mode/live/activate
```

**Requirements**:
- User has consented
- Broker credentials connected

Switches user from education mode to live trading.

---

### Revert to Education Mode
```
POST /api/user/mode/education/revert
```

Allows user to switch back to safe simulation mode anytime.

---

## Database Changes

### User Model Updates

**New Fields**:
```python
education_mode = Column(Boolean, default=True)  # Start in education mode
consented_to_live_trading = Column(Boolean, default=False)  # Explicit consent
```

**Migration**: `alembic/versions/add_education_mode.py`

To apply migration:
```bash
alembic upgrade head
```

---

## Frontend Files

### New Files Created

1. **`/frontend/static/css/onboarding.css`**
   - Onboarding screen styles
   - Education mode banner styles
   - Progress tracking UI
   - Consent checklist styles

2. **`/frontend/static/js/onboarding.js`**
   - Onboarding flow logic
   - Progress tracking
   - Mode switching
   - Consent validation

### Modified Files

1. **`/frontend/templates/index.html`**
   - Added onboarding screens (welcome, education, upgrade)
   - Added education mode banner to dashboard
   - Added progress tracking UI

---

## Backend Files

### New Files Created

1. **`/bot/education_mode.py`**
   - `UserMode` enum
   - `EducationProgress` dataclass
   - `EducationModeManager` class
   - Progress tracking logic
   - Graduation criteria checking

### Modified Files

1. **`/gateway.py`**
   - Added education mode API endpoints
   - Onboarding status endpoint
   - Mode switching endpoints
   - Consent recording endpoint

2. **`/database/models.py`**
   - Added `education_mode` field to User model
   - Added `consented_to_live_trading` field to User model

---

## Regulatory Compliance

### Why This Matters

This three-layer architecture addresses key concerns from:
- 📱 **Apple App Store reviewers**
- 🏛️ **Financial regulators**
- 💰 **Investors and stakeholders**

### Key Compliance Points

1. **Education-First Positioning**
   - Product is positioned as educational tool
   - No pressure to use real money
   - Users can stay in education mode indefinitely

2. **Explicit Consent**
   - Live trading requires explicit opt-in
   - Clear risk disclosures
   - Cannot proceed without acknowledging risks

3. **User Control**
   - Users can revert to education mode anytime
   - Users maintain control of broker accounts
   - Funds never touch platform

4. **Clear Separation**
   - Education mode clearly marked as "not real money"
   - Live mode clearly marked when active
   - No confusion between modes

---

## Testing the Implementation

### Manual Testing Steps

1. **Test New User Flow**:
   ```
   - Register new user
   - Should see welcome screen
   - Click "Start in Education Mode"
   - Should see education active screen
   - Continue to dashboard
   - Should see education mode banner
   ```

2. **Test Progress Tracking**:
   ```
   - Make simulated trades
   - Click "View Progress"
   - Should see updated progress metrics
   - Milestones should update
   ```

3. **Test Upgrade Flow**:
   ```
   - Complete 10+ trades with positive P&L
   - "Upgrade to Live Trading" button should appear
   - Click upgrade button
   - Should see consent screen
   - Check all boxes
   - Button should enable
   ```

4. **Test Mode Switching**:
   ```
   - In education mode, call mode API
   - Should return education_mode: true
   - Switch to live (after consent + broker)
   - Should return education_mode: false
   ```

---

## User Documentation

### For New Users

**Getting Started**:
1. Register for an account
2. Start in Education Mode (automatic)
3. Trade with $10,000 simulated balance
4. Track your progress
5. When ready, upgrade to live trading

**Education Mode Benefits**:
- Learn without risk
- No real money required
- Full trading functionality
- Real market data
- Track your performance

**When to Upgrade**:
- You've completed 10+ trades
- You have a 50%+ win rate
- You're consistently profitable
- You understand the risks

### For Existing Users

**Switching to Education Mode**:
```
Settings → Trading Mode → Switch to Education Mode
```

**Benefits of Reverting**:
- Test new strategies risk-free
- Practice without real money
- Refresh skills
- No pressure

---

## Monitoring & Analytics

### Key Metrics to Track

1. **Onboarding Funnel**:
   - Users who complete welcome screen
   - Users who start education mode
   - Users who make first trade
   - Users who reach upgrade criteria
   - Users who consent to live trading

2. **Education Mode Engagement**:
   - Average trades per user
   - Average time in education mode
   - Win rate distribution
   - Progression to live trading rate

3. **Mode Distribution**:
   - % users in education mode
   - % users in live trading mode
   - % users who reverted to education

---

## Support & FAQs

### Common Questions

**Q: Can I skip education mode?**
A: No. All new users start in education mode. This ensures you understand the platform before risking real money.

**Q: How long do I stay in education mode?**
A: As long as you want. There's no time limit. You control when to upgrade.

**Q: Can I go back to education mode?**
A: Yes! You can switch back anytime from settings.

**Q: Is my simulated money saved?**
A: Yes. Your education mode progress is saved and tracked.

**Q: Do I need a broker for education mode?**
A: No. Education mode uses simulated trading. Broker is only needed for live trading.

---

## Future Enhancements

### Potential Improvements

1. **Advanced Progress Metrics**:
   - Sharpe ratio
   - Maximum drawdown
   - Risk-adjusted returns

2. **Educational Content**:
   - Guided tutorials
   - Trading tips
   - Strategy explanations

3. **Gamification**:
   - Achievement badges
   - Leaderboards (simulated)
   - Challenges and goals

4. **Social Features**:
   - Share progress
   - Compare with peers (anonymous)
   - Community tips

---

## Conclusion

The Education Mode onboarding creates a safe, regulatory-compliant entry point for users. By positioning the product as educational-first with optional live trading, we:

✅ Build user trust  
✅ Meet regulatory requirements  
✅ Reduce user anxiety about real money  
✅ Create natural upgrade path  
✅ Maintain full control and transparency  

**The architecture is now locked in. UX can be aggressive without risk.**

---

**Questions or Issues?**
See: `CONSUMER_PLATFORM_README.md`, `PAPER_TO_LIVE_GRADUATION.md`
