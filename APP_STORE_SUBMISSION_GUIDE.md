# NIJA App Store Submission Guide
## Complete Step-by-Step Process for iOS & Android

> **Version**: 2.0  
> **Last Updated**: February 9, 2026  
> **Status**: Production Ready

---

## 📋 TABLE OF CONTENTS

1. [Pre-Submission Checklist](#pre-submission-checklist)
2. [Environment Configuration](#environment-configuration)
3. [Testing & Verification](#testing--verification)
4. [Apple App Store Submission](#apple-app-store-submission)
5. [Google Play Store Submission](#google-play-store-submission)
6. [Post-Approval Procedures](#post-approval-procedures)
7. [Troubleshooting](#troubleshooting)

---

## 🎯 PRE-SUBMISSION CHECKLIST

Complete ALL items before submission:

### Code & Build

- [ ] APP_STORE_MODE implemented in backend (`bot/safety_controller.py`)
- [ ] Frontend JavaScript updated (`frontend/static/js/app-store-ui.js`)
- [ ] CSS styling added for APP_STORE_MODE (`frontend/static/css/app-store-ui.css`)
- [ ] API endpoints expose APP_STORE_MODE status (`safety_status_api.py`)
- [ ] All trade execution buttons disable when APP_STORE_MODE=true
- [ ] Dashboards remain visible (read-only) in APP_STORE_MODE
- [ ] Risk disclosures prominently displayed
- [ ] Simulator/sandbox trades functional

### Testing

- [ ] QA test suite passes all 22 tests: `python qa_app_store_mode.py --full`
- [ ] Manual testing with APP_STORE_MODE=true completed
- [ ] Verified no live trading possible in APP_STORE_MODE
- [ ] Confirmed dashboards visible and functional
- [ ] Risk disclaimers display correctly
- [ ] Simulator trades work as expected

### Documentation

- [ ] README.md updated with APP_STORE_MODE information
- [ ] .env.example includes APP_STORE_MODE configuration
- [ ] APPLE_APP_REVIEW_SUBMISSION_NOTES.md reviewed
- [ ] REVIEWER_EXPERIENCE_MAP.md created (optional but recommended)
- [ ] Privacy Policy updated
- [ ] Terms of Service reviewed

### App Store Materials

- [ ] App screenshots prepared (in APP_STORE_MODE)
- [ ] App description written
- [ ] Keywords selected
- [ ] Support URL configured
- [ ] Privacy Policy URL configured
- [ ] App icon finalized (1024x1024px)

---

## ⚙️ ENVIRONMENT CONFIGURATION

### Step 1: Enable APP_STORE_MODE

Create or update your `.env` file:

```bash
# For App Store Review Submission
APP_STORE_MODE=true

# Keep these DISABLED for review
LIVE_CAPITAL_VERIFIED=false
DRY_RUN_MODE=false
HEARTBEAT_TRADE=false

# Optional: Set for simulation demonstration
# DRY_RUN_MODE=true  # Can enable to show simulator
```

### Step 2: Verify Configuration

```bash
# Check environment variables
echo $APP_STORE_MODE  # Should output: true

# Or in Python:
python -c "import os; print('APP_STORE_MODE:', os.getenv('APP_STORE_MODE'))"
```

### Step 3: Test App Startup

```bash
# Start the app
./start.sh

# Expected output should show:
# ============================================================
# 📱 APP STORE REVIEW MODE ACTIVE
# ============================================================
#    FOR APP STORE SUBMISSION AND REVIEW
#    All dashboards visible (read-only)
#    Trade execution buttons DISABLED
#    Risk disclosures prominently displayed
#    Simulator/sandbox trades ENABLED
# ============================================================
```

---

## 🧪 TESTING & VERIFICATION

### Step 1: Run QA Test Suite

```bash
# Set environment
export APP_STORE_MODE=true

# Run full test suite (22+ tests)
python qa_app_store_mode.py --full

# Expected output:
# ============================================================
# ✅ ALL TESTS PASSED - READY FOR APP STORE SUBMISSION
# ============================================================
```

**CRITICAL**: All tests MUST pass before proceeding.

### Step 2: Manual Verification

1. **Start the application**:
   ```bash
   APP_STORE_MODE=true python bot.py
   ```

2. **Open the web interface**:
   - Navigate to `http://localhost:5000` (or your server URL)
   - Verify APP_STORE_MODE banner is visible
   - Check that all trade buttons are disabled (grayed out with lock icon 🔒)

3. **Test Dashboard Access**:
   - Verify all metrics and charts are visible
   - Confirm data updates in real-time
   - Ensure NO trade execution is possible

4. **Verify Risk Disclosures**:
   - Check risk disclaimer appears on first launch
   - Verify all required warnings are present
   - Confirm user must acknowledge before proceeding

5. **Test Simulator Mode** (Optional):
   - Enable DRY_RUN_MODE alongside APP_STORE_MODE
   - Verify simulated trades work
   - Confirm no real orders are placed

### Step 3: Screenshot Capture

Capture screenshots showing:
- APP_STORE_MODE banner visible
- Disabled trade buttons (with 🔒 icon)
- Risk disclosures displayed
- Dashboard metrics visible
- Simulator trades (if applicable)

Save these for App Store submission materials.

---

## 🍎 APPLE APP STORE SUBMISSION

### Phase 1: Prepare Build

1. **Xcode Project Configuration**:
   ```bash
   cd mobile/ios
   open NIJA.xcodeproj
   ```

2. **Set Build Configuration**:
   - Target: Generic iOS Device
   - Scheme: Release
   - Version: 1.0.0 (or your version)
   - Build Number: Increment for each submission

3. **Configure Info.plist**:
   - Add privacy usage descriptions
   - Set bundle identifier
   - Configure URL schemes

4. **Archive Build**:
   - Product → Archive
   - Wait for build to complete
   - Validate archive

### Phase 2: Upload to App Store Connect

1. **Create App in App Store Connect**:
   - Go to [appstoreconnect.apple.com](https://appstoreconnect.apple.com)
   - My Apps → New App
   - Fill in app information
   - Bundle ID must match Xcode project

2. **Upload Build**:
   - In Xcode Organizer, select archive
   - Distribute App → App Store Connect
   - Upload
   - Wait for processing (15-30 minutes)

3. **Configure App Store Listing**:
   - App Information
   - Pricing and Availability
   - App Privacy (CRITICAL - see below)
   - Screenshots and descriptions

### Phase 3: App Privacy Configuration

**CRITICAL**: Accurately configure privacy settings.

**Data Collected**:
- User account information (email, password)
- Trading history and performance
- Exchange API credentials (encrypted)

**Data Usage**:
- App functionality (trading automation)
- Analytics (performance tracking)

**Data Sharing**:
- With user's exchange (for trading)
- NO third-party sharing

### Phase 4: Submission Notes for Apple

**Include this in "Notes for Reviewer"**:

```
==========================================================
NIJA - Automated Trading App
Review Mode Configuration
==========================================================

IMPORTANT: This app is submitted with APP_STORE_MODE=true

What This Means:
- All dashboards and metrics are VISIBLE (read-only demonstration)
- All trade execution buttons are DISABLED (grayed out with lock icon)
- Risk disclosures are prominently displayed
- Simulator/sandbox trades are ENABLED to demonstrate functionality
- NO REAL TRADING is possible in this review mode

For Testing:
1. Launch the app
2. You will see "📱 APP STORE REVIEW MODE" banner
3. All features are visible but trade execution is disabled
4. Risk disclaimers appear before any configuration
5. Simulator mode shows how trading logic works (no real money)

Technical Details:
- Environment variable: APP_STORE_MODE=true
- Safety controller prevents all live trading
- Backend enforces read-only mode
- Frontend disables all action buttons

After Approval:
- Production builds will have APP_STORE_MODE=false
- Users must explicitly enable trading (multi-step process)
- Full risk acknowledgment required for live trading

Documentation:
- See APP_STORE_SUBMISSION_GUIDE.md in code repository
- Review APPLE_APP_REVIEW_SUBMISSION_NOTES.md for details
- REVIEWER_EXPERIENCE_MAP.md shows exact reviewer flow

Contact: support@nija.app for any questions
==========================================================
```

### Phase 5: TestFlight (Recommended First)

Before full App Store submission:

1. **Create TestFlight Group**:
   - App Store Connect → TestFlight
   - Create internal testing group
   - Add test users

2. **Upload Beta Build**:
   - Same process as App Store upload
   - Select for TestFlight testing
   - Add testing instructions

3. **Test with Real Users**:
   - Invite beta testers
   - Collect feedback
   - Verify APP_STORE_MODE works correctly
   - Fix any issues before App Store submission

4. **Review TestFlight Results**:
   - Check crash reports
   - Review user feedback
   - Test on multiple iOS versions
   - Verify on different device sizes

### Phase 6: Submit for Review

1. **Final Checks**:
   - [ ] All screenshots uploaded
   - [ ] App description finalized
   - [ ] Privacy policy URL working
   - [ ] Support URL working
   - [ ] Reviewer notes added
   - [ ] Age rating set correctly (17+)

2. **Submit**:
   - Click "Submit for Review"
   - Confirm all information
   - Wait for review (typically 24-48 hours)

3. **Monitor Status**:
   - Check App Store Connect daily
   - Respond to any reviewer questions promptly
   - Be prepared to provide demo account if needed

---

## 🤖 GOOGLE PLAY STORE SUBMISSION

### Phase 1: Prepare Android Build

1. **Build Configuration**:
   ```bash
   cd mobile/android
   ./gradlew assembleRelease
   ```

2. **Sign APK/AAB**:
   ```bash
   jarsigner -verbose -sigalg SHA256withRSA \
     -digestalg SHA-256 \
     -keystore nija-release-key.keystore \
     app/build/outputs/bundle/release/app-release.aab
   ```

3. **Generate Upload Key**:
   - Use Google Play App Signing
   - Upload key to Play Console

### Phase 2: Create App in Play Console

1. **Go to Play Console**:
   - [play.google.com/console](https://play.google.com/console)
   - Create app
   - Fill in basic information

2. **Upload Build**:
   - Production → Create new release
   - Upload AAB file
   - Add release notes

3. **Configure Store Listing**:
   - Screenshots (phone, tablet, TV if applicable)
   - App description (4000 char max)
   - Short description (80 char max)
   - App icon (512x512px)
   - Feature graphic (1024x500px)

### Phase 3: Data Safety Form

**CRITICAL**: Accurately fill out Data Safety section.

**Data Collected**:
- Personal info (email, name)
- Financial info (trading history, NOT payment info)
- App activity (performance metrics)

**Data Usage**:
- App functionality
- Analytics
- Security

**Data Sharing**: None (except with user's exchange)

### Phase 4: Content Rating

Use IARC questionnaire:
- Select "Finance" category
- Answer all questions honestly
- Expected rating: Teen or higher

### Phase 5: Submission Notes

Add to "Notes for Reviewer":

```
This app is configured with APP_STORE_MODE=true for review.
All trading functionality is disabled - only read-only dashboards
and risk disclosures are shown. See included documentation for details.
```

### Phase 6: Submit for Review

1. **Complete all sections**:
   - Store listing
   - App content
   - Pricing & distribution
   - App content
   - Data safety

2. **Submit**:
   - Review all information
   - Click "Send for review"
   - Wait for review (typically 1-3 days)

---

## ✅ POST-APPROVAL PROCEDURES

### When Apple/Google Approves

**DO NOT** immediately switch APP_STORE_MODE=false in production!

### Step 1: Prepare Production Configuration

1. **Create Production Environment**:
   ```bash
   cp .env.example .env.production
   ```

2. **Configure Production Settings**:
   ```bash
   # .env.production
   APP_STORE_MODE=false  # Disable review mode
   LIVE_CAPITAL_VERIFIED=false  # Still require explicit user enable
   DRY_RUN_MODE=false
   
   # Production credentials
   KRAKEN_PLATFORM_API_KEY=your_production_key
   KRAKEN_PLATFORM_API_SECRET=your_production_secret
   
   # Security
   JWT_SECRET_KEY=your_production_jwt_secret
   ALLOWED_ORIGINS=https://app.yourdomain.com
   ```

### Step 2: Deploy Production Build

1. **Build Production Version**:
   - iOS: New build with APP_STORE_MODE=false
   - Android: New AAB with APP_STORE_MODE=false

2. **Test Production Build**:
   - TestFlight (iOS) or Internal Testing (Android)
   - Verify trading functionality works
   - Confirm safety controls work
   - Test with small real amounts

3. **Gradual Rollout**:
   - iOS: Phased release (automatic)
   - Android: Staged rollout (10% → 50% → 100%)

### Step 3: Monitor Post-Launch

1. **Track Metrics**:
   - Crash reports
   - User feedback
   - Trading performance
   - Safety control effectiveness

2. **Be Ready to Respond**:
   - Bug fixes
   - User support
   - Performance improvements

### Step 4: Merge to Main Branch

```bash
# After successful production deployment
git checkout main
git merge copilot/disable-trade-buttons-read-only
git push origin main

# Tag release
git tag -a v1.0.0 -m "App Store approved release"
git push origin v1.0.0
```

### Step 5: Keep Review Mode Ready

**IMPORTANT**: Keep APP_STORE_MODE functionality for future updates!

Every app update goes through review. You'll need to:
- Set APP_STORE_MODE=true for each submission
- Run QA tests before each submission
- Provide reviewer notes for each update

---

## 🔧 TROUBLESHOOTING

### Common Issues

#### Issue: Tests Fail

**Solution**:
```bash
# Verify environment
echo $APP_STORE_MODE

# Reinstall dependencies
pip install -r requirements.txt

# Run tests with verbose output
python qa_app_store_mode.py --full --verbose
```

#### Issue: Trade Buttons Not Disabled

**Check**:
1. JavaScript loaded: Open browser console, check for errors
2. CSS applied: Inspect button elements, look for `.app-store-disabled` class
3. API response: Check `/api/safety/status` returns `app_store_mode: true`

**Fix**:
```javascript
// In browser console
fetch('/api/safety/status')
  .then(r => r.json())
  .then(d => console.log('APP_STORE_MODE:', d.app_store_mode))
```

#### Issue: Reviewer Can't Access App

**Common Causes**:
- App requires login (provide demo account)
- Network restrictions
- Geolocation restrictions

**Solution**:
- Add demo account in reviewer notes
- Disable geolocation checks for review
- Provide VPN if region-specific

#### Issue: App Rejected for Financial Functionality

**Response Template**:
```
Thank you for the review. NIJA is a trading automation tool,
not a payment/financial service. We:

1. Do NOT handle user funds (funds stay on user's exchange)
2. Do NOT process payments
3. Do NOT provide financial advice
4. Require extensive risk disclosures
5. Have APP_STORE_MODE for review (no real trading)

Please see our detailed response in APPLE_APP_REVIEW_SUBMISSION_NOTES.md
which explains our independent trading model and safety controls.

We're happy to provide additional information or clarification.
```

#### Issue: Privacy Policy Concerns

**Ensure Your Policy States**:
- What data is collected
- How data is used
- Data is NOT sold to third parties
- User controls over their data
- How to delete account/data

#### Issue: Build Fails

**Check**:
1. Xcode version compatible
2. Certificates valid
3. Provisioning profiles up to date
4. Dependencies installed

**Fix**:
```bash
# iOS
cd mobile/ios
pod install
pod update

# Android
cd mobile/android
./gradlew clean
./gradlew build
```

---

## 📞 SUPPORT

### Resources

- **Apple Developer**: [developer.apple.com/support](https://developer.apple.com/support)
- **Google Play Support**: [support.google.com/googleplay/android-developer](https://support.google.com/googleplay/android-developer)
- **NIJA Documentation**: See repository docs/
- **Technical Support**: support@nija.app

### Before Contacting Support

1. Run QA tests: `python qa_app_store_mode.py --full --verbose`
2. Check logs for errors
3. Review relevant documentation
4. Prepare specific questions with:
   - What you tried
   - What happened
   - Expected vs actual behavior
   - Screenshots if applicable

---

## 📚 RELATED DOCUMENTATION

- `APPLE_APP_REVIEW_SUBMISSION_NOTES.md` - Detailed reviewer notes
- `NIJA_APP_STORE_LAUNCH_READINESS_CHECKLIST.md` - Complete checklist
- `REVIEWER_EXPERIENCE_MAP.md` - Visual guide for reviewers
- `RISK_DISCLOSURE.md` - Required risk warnings
- `README.md` - Project overview

---

**Last Updated**: February 9, 2026  
**Version**: 2.0  
**Status**: Production Ready

---

🎉 **Good luck with your App Store submission!** 🎉
