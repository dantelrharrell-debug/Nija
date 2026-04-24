# 🎯 NIJA Final Pre-Submission Checklist (One-Page)
**Complete ALL items before clicking "Submit for Review" to Apple/Google**

---

## 🚨 CRITICAL BLOCKERS (Must Be 100% Complete)

### Financial Services Compliance (Apple §2.5.6, Google Financial Policy)
- [ ] **Risk disclaimer shows FIRST on app launch** (before any functionality)
- [ ] **User MUST acknowledge "I can lose money"** (cannot skip, required checkbox)
- [ ] **NO "guaranteed profit" language** anywhere (grep codebase, screenshots, descriptions)
- [ ] **Education mode is DEFAULT** on first launch (NOT live trading)
- [ ] **"Not Real Money" indicator** always visible in education mode (orange banner, sticky)
- [ ] **Emergency stop button** prominently displayed and functional

### Fresh Install Testing (Most Critical Path)
- [ ] **Factory reset device** → Install app → Launches without crash
- [ ] **First screen shows onboarding** (NOT login or dashboard)
- [ ] **Risk disclaimer is step 2-3** (not buried at end)
- [ ] **Cannot skip disclaimer** (must scroll and acknowledge all checkboxes)
- [ ] **Land in education mode** after onboarding (shows $10,000 simulated balance)
- [ ] **App works WITHOUT broker credentials** (education mode accessible)
- [ ] **No white screen, crashes, or network errors** blocking first use

### Legal Documentation (Instant Rejection if Missing)
- [ ] **Privacy Policy URL live** and accessible (https://...)
- [ ] **Terms of Service URL live** and accessible (https://...)
- [ ] **Support email functional** and monitored (support@...)

---

## 📱 CORE FUNCTIONALITY VERIFICATION

### Education/Simulation Mode
- [ ] **Simulation API endpoints working** (`/api/simulation/results`, `/status`, `/trades`)
- [ ] **Education mode shows metrics** (P&L, win rate, trade history)
- [ ] **"EDUCATION MODE" banner** always visible (top of screen, sticky)
- [ ] **Simulated balance clearly labeled** ("$10,000 (Simulated)")
- [ ] **Can execute simulated trades** without real broker connection
- [ ] **Mode isolation verified** (education mode NEVER touches real funds)

### Risk Disclaimers & Acknowledgments
- [ ] **All 6 consent checkboxes present** and functional:
  - "I understand I can lose money"
  - "No guarantees of profit"
  - "I am responsible for my trades"
  - "Independent trading model"
  - "I will start in Education Mode"
  - "I am 18+ years old"
- [ ] **Cannot proceed without ALL boxes checked**
- [ ] **Acknowledgment saved** to localStorage with timestamp
- [ ] **Disclaimers accessible from settings** (can re-read anytime)

### Safety & Control Features
- [ ] **Emergency stop button** visible on main screen (one-tap to halt all trading)
- [ ] **Trading status always visible** (Mode: Education/Live, Status: Active/Stopped)
- [ ] **Color-coded indicators** (green=live, orange=simulation, red=stopped)
- [ ] **No profit guarantee claims** anywhere in UI or copy

---

## 📋 APP STORE SUBMISSION MATERIALS

### Apple App Store Connect
- [ ] **iOS build uploaded** (Build #: ___, Version: ___, Date: ___)
- [ ] **Build selected** in App Store Connect (green checkmark visible)
- [ ] **App name**: "NIJA" or "NIJA Trading" (30 chars max)
- [ ] **Category**: Finance (Primary), Age Rating: 17+
- [ ] **Privacy Policy URL**: ________________________
- [ ] **Support URL**: ________________________
- [ ] **Keywords**: cryptocurrency, trading, education, simulation, bitcoin (100 chars)

### Screenshots (iPhone 6.7" REQUIRED)
- [ ] **Screenshot 1**: Onboarding - Risk Disclaimer screen
- [ ] **Screenshot 2**: Education Mode Dashboard (orange "Not Real Money" banner visible)
- [ ] **Screenshot 3**: Simulated Trade History
- [ ] **Screenshot 4**: Safety Controls (Emergency Stop button visible)
- [ ] **Screenshot 5**: Settings screen
- [ ] **All screenshots**: High resolution (1242x2688+), no placeholder text, actual app

### App Review Information
- [ ] **Demo credentials provided** OR explain education mode needs no login
- [ ] **Notes for reviewer**:
```
TESTING INSTRUCTIONS:
1. App launches in Education Mode (no credentials needed)
2. Complete onboarding to access $10,000 simulated balance
3. All trades are simulated (no real money)
4. Emergency Stop: Top-right red button
5. Risk disclaimers shown during onboarding (cannot skip)

Contact: support@nija.app
Response time: <24 hours
```

### Google Play Console (if applicable)
- [ ] **Android AAB uploaded** (Version code: ___, Name: ___, Date: ___)
- [ ] **Store listing complete** (name, description, screenshots, icon)
- [ ] **Data Safety section complete** (data collection, encryption, sharing)
- [ ] **Content rating received** (IARC questionnaire completed)
- [ ] **Privacy Policy URL live**

---

## 🔍 FINAL QUALITY CHECKS

### Code Quality
- [ ] **No debug code**: `grep -r "console.log\|debugger\|TODO" frontend/ mobile/` (only intentional logging)
- [ ] **No hardcoded secrets**: `grep -r "sk_live_\|pk_live_\|AIza" .` (all secrets in .env)
- [ ] **No profanity**: `grep -ri "damn\|hell\|fuck\|shit" frontend/ mobile/` (clean language)
- [ ] **Environment variables correct**: `APP_STORE_MODE`, `DRY_RUN_MODE`, etc.

### Performance (Test on Actual Device)
- [ ] **App launch time** < 3 seconds
- [ ] **Dashboard load** < 2 seconds  
- [ ] **Memory usage** < 100 MB idle
- [ ] **No crashes** in 10-minute testing session
- [ ] **Smooth animations** (60fps)

### Accessibility
- [ ] **VoiceOver (iOS)** can navigate app
- [ ] **Text adjusts** with system settings
- [ ] **Color contrast** meets WCAG 2.1 AA (4.5:1)
- [ ] **Touch targets** ≥ 44x44 points

---

## ✅ GO/NO-GO DECISION

### ALL BLOCKERS MUST BE ✅ (Check Every Box)
| Critical Item | Status | GO? |
|--------------|--------|-----|
| 1. Risk disclaimer on first launch | ⬜ | |
| 2. Education mode is default | ⬜ | |
| 3. App works without credentials | ⬜ | |
| 4. No profit guarantees anywhere | ⬜ | |
| 5. All 6 consent checkboxes work | ⬜ | |
| 6. Privacy policy URL live | ⬜ | |
| 7. No crashes on fresh install | ⬜ | |
| 8. Screenshots show actual app | ⬜ | |
| 9. Reviewer notes complete | ⬜ | |
| 10. Build uploaded successfully | ⬜ | |

**If ANY blocker is not ✅, DO NOT SUBMIT. Fix first.**

---

## 🚀 FINAL APPROVAL & SUBMISSION

### Team Sign-Off (ALL Required)
- [ ] **Engineering Lead**: Code complete, tested, no critical bugs — Name: _______ Date: _______
- [ ] **QA Lead**: All tests passed, verified on devices — Name: _______ Date: _______
- [ ] **Product Manager**: Features complete, ready for users — Name: _______ Date: _______
- [ ] **Legal/Compliance**: All policies approved — Name: _______ Date: _______

### Ready to Submit
- [ ] **Apple**: All metadata entered → "Submit for Review" button ready
- [ ] **Google**: AAB uploaded → "Send for Review" button ready
- [ ] **Monitor**: Check status daily, respond within 24 hours

---

## 📞 EMERGENCY CONTACTS

**If Rejected**:
- Engineering Lead: _______________________
- Product Manager: _______________________
- Apple Support: https://developer.apple.com/contact/
- Google Support: https://support.google.com/googleplay/android-developer/

---

## 📊 COMMON REJECTION FIXES

| Rejection Reason | Fix |
|-----------------|-----|
| "No test account" | Add demo account OR explain education mode needs no login |
| "Insufficient risk warnings" | Make disclaimer more prominent, cannot be skipped |
| "Guarantees financial return" | Remove "profitable", "guaranteed wins" language |
| "Unclear app purpose" | Emphasize education mode, add screenshots |
| "Privacy policy incomplete" | Update to include all data types collected |

---

**🎉 GOOD LUCK!**  
**Focus on: Risk disclaimers ✅ Education mode ✅ No crashes ✅**

**Submission Date**: __________ **By**: __________ **Build**: Apple _____ Android _____
