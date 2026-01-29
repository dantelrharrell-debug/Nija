# NIJA Mobile App - Testing Guide

This guide covers testing procedures for the NIJA mobile app on iOS and Android.

## Table of Contents
1. [Prerequisites](#prerequisites)
2. [Development Testing](#development-testing)
3. [Beta Testing](#beta-testing)
4. [Pre-Release Checklist](#pre-release-checklist)
5. [Test Scenarios](#test-scenarios)
6. [Known Issues](#known-issues)

---

## Prerequisites

### Testing Tools

**iOS:**
- Xcode with iOS Simulators
- Physical iOS device (recommended for final testing)
- TestFlight account

**Android:**
- Android Studio with emulators
- Physical Android device (recommended for final testing)
- Google Play Console access

**General:**
- NIJA backend API running (local or remote)
- Test user accounts
- Test API keys (sandbox/testnet)

### Environment Setup

```bash
# Clone repository
git clone https://github.com/dantelrharrell-debug/Nija.git
cd Nija

# Install dependencies
npm install

# Run setup
./setup-mobile.sh

# Configure API endpoint
# Edit frontend/static/js/app.js
# Set API_BASE_URL to your test server
```

---

## Development Testing

### Local Development Server

1. **Start Backend API:**
   ```bash
   # In terminal 1
   python web_server.py
   ```

2. **Configure Mobile App:**

   Edit `capacitor.config.json` for development:
   ```json
   {
     "server": {
       "url": "http://localhost:5000",
       "cleartext": true
     }
   }
   ```

3. **Test on iOS:**
   ```bash
   npm run cap:sync
   npm run cap:open:ios
   # In Xcode, select simulator and run
   ```

4. **Test on Android:**
   ```bash
   npm run cap:sync
   npm run cap:open:android
   # In Android Studio, select emulator and run
   ```

### Hot Reload Development

For rapid iteration:

1. **Make changes to frontend files**
2. **Sync changes:**
   ```bash
   npm run cap:sync
   ```
3. **Reload app** (⌘R in iOS Simulator, R+R in Android Emulator)

### Debugging

**iOS:**
- Safari → Develop → [Your Simulator] → localhost
- View console logs and network requests
- Set breakpoints in JavaScript

**Android:**
- Chrome → chrome://inspect
- Select your device/emulator
- View console logs and network requests

**Native Logs:**
- iOS: Xcode → View → Debug Area → Console
- Android: Android Studio → Logcat

---

## Beta Testing

### TestFlight (iOS)

1. **Prepare for TestFlight:**
   - Archive app in Xcode (Product → Archive)
   - Upload to App Store Connect
   - Wait for processing (15-30 minutes)

2. **Create TestFlight Group:**
   - Go to App Store Connect
   - Select your app
   - Go to TestFlight tab
   - Create internal or external testing group

3. **Add Testers:**
   - Internal: Up to 100 Apple Developer team members
   - External: Up to 10,000 testers (requires beta review)

4. **Share TestFlight Link:**
   - Testers receive email invitation
   - Download TestFlight app from App Store
   - Install NIJA app

### Google Play Internal Testing (Android)

1. **Build Release AAB:**
   ```bash
   cd android
   ./gradlew bundleRelease
   ```

2. **Upload to Play Console:**
   - Go to Google Play Console
   - Select your app
   - Go to Testing → Internal testing
   - Create new release
   - Upload AAB file

3. **Add Testers:**
   - Create email list of testers
   - Share opt-in link

4. **Testers Install:**
   - Click opt-in link
   - Download from Play Store

---

## Pre-Release Checklist

### Functionality Testing

#### Authentication
- [ ] User can register new account
- [ ] User can login with email/password
- [ ] JWT token is stored securely
- [ ] Token refresh works
- [ ] Biometric authentication works (if enabled)
- [ ] Logout clears session
- [ ] Invalid credentials show error

#### Dashboard
- [ ] Dashboard loads without errors
- [ ] Stats display correctly (P&L, win rate, trades)
- [ ] Trading toggle works
- [ ] Position list updates
- [ ] Recent trades display
- [ ] Pull to refresh works
- [ ] Loading states display

#### Broker Management
- [ ] Can add new broker
- [ ] API keys are encrypted
- [ ] Can remove broker
- [ ] Broker list displays correctly
- [ ] Connection status shows
- [ ] Error handling for invalid keys

#### Trading Control
- [ ] Enable trading works
- [ ] Disable trading works
- [ ] Status updates in real-time
- [ ] Confirmations display
- [ ] Error handling works

#### Push Notifications
- [ ] Device registration works
- [ ] Notifications received when app closed
- [ ] Notifications received when app backgrounded
- [ ] Notification tap opens app
- [ ] Notification settings work
- [ ] Can disable notifications

#### Settings
- [ ] User profile displays
- [ ] Account info correct
- [ ] Subscription tier shows
- [ ] Can update settings
- [ ] Logout works
- [ ] Delete account works (if implemented)

### Platform-Specific Testing

#### iOS-Specific
- [ ] Face ID/Touch ID authentication works
- [ ] Status bar displays correctly
- [ ] Safe area insets respected
- [ ] Dark mode compatible
- [ ] Haptic feedback works
- [ ] Splash screen displays
- [ ] App icon displays correctly
- [ ] Works on all supported iOS versions (14+)

#### Android-Specific
- [ ] Fingerprint authentication works
- [ ] Status bar displays correctly
- [ ] Navigation bar compatible
- [ ] Dark mode compatible
- [ ] Haptic feedback works
- [ ] Splash screen displays
- [ ] App icon displays correctly
- [ ] Adaptive icon works
- [ ] Back button handled correctly
- [ ] Works on all supported Android versions (8.0+)

### Network Testing

- [ ] Works on Wi-Fi
- [ ] Works on cellular data
- [ ] Handles offline mode
- [ ] Handles slow network
- [ ] Handles network errors
- [ ] Retry mechanism works
- [ ] Timeout handling works

### Performance Testing

- [ ] App launches < 3 seconds
- [ ] Dashboard loads < 2 seconds
- [ ] Smooth scrolling
- [ ] No memory leaks
- [ ] Battery usage acceptable
- [ ] Network usage reasonable
- [ ] App size < 50MB

### Security Testing

- [ ] API keys encrypted at rest
- [ ] HTTPS enforced
- [ ] JWT tokens secure
- [ ] No sensitive data in logs
- [ ] Biometric auth secure
- [ ] Session timeout works
- [ ] SSL pinning (if implemented)

### Accessibility Testing

- [ ] VoiceOver works (iOS)
- [ ] TalkBack works (Android)
- [ ] Text scaling works
- [ ] Color contrast sufficient
- [ ] Touch targets > 44pt
- [ ] Keyboard navigation works

---

## Test Scenarios

### Scenario 1: First-Time User

1. Download and install app
2. Open app (splash screen displays)
3. Register new account
4. Verify email (if implemented)
5. Login to app
6. Complete onboarding (if implemented)
7. Add first broker
8. Enable trading
9. Receive first notification

**Expected Result:** User successfully onboarded and trading enabled.

### Scenario 2: Existing User

1. Open app
2. Login with existing credentials
3. Enable biometric auth
4. View dashboard
5. Check positions
6. Toggle trading off
7. View recent trades
8. Update settings
9. Logout

**Expected Result:** All features work smoothly.

### Scenario 3: Network Interruption

1. Login to app
2. Enable airplane mode
3. Attempt to load dashboard
4. See offline message
5. Disable airplane mode
6. Dashboard refreshes automatically

**Expected Result:** Graceful handling of network issues.

### Scenario 4: Push Notification

1. Enable trading
2. Close app completely
3. Wait for trade execution
4. Receive push notification
5. Tap notification
6. App opens to trade details

**Expected Result:** Notification received and handled correctly.

### Scenario 5: Multiple Devices

1. Login on Device A
2. Login on Device B (same account)
3. Enable trading on Device A
4. Verify status updates on Device B
5. Disable trading on Device B
6. Verify status updates on Device A

**Expected Result:** Real-time sync across devices.

---

## Known Issues

### iOS

**Issue:** Simulator doesn't support push notifications
- **Workaround:** Test on physical device

**Issue:** Biometric auth fails in simulator
- **Workaround:** Test on physical device with Face ID/Touch ID

### Android

**Issue:** Emulator slow performance
- **Workaround:** Use x86 emulator or physical device

**Issue:** Google Play Services required for FCM
- **Workaround:** Use emulator with Google Play or physical device

### General

**Issue:** CORS errors during development
- **Solution:** Ensure Flask-CORS configured correctly in api_server.py

**Issue:** WebSocket connections fail
- **Solution:** Check firewall settings and WebSocket support

---

## Reporting Issues

When reporting bugs, include:

1. **Platform:** iOS/Android version
2. **Device:** Model and OS version
3. **Steps to Reproduce:** Detailed steps
4. **Expected Behavior:** What should happen
5. **Actual Behavior:** What actually happened
6. **Screenshots:** If applicable
7. **Logs:** Console logs or crash reports

**Submit to:** https://github.com/dantelrharrell-debug/Nija/issues

---

## Automated Testing (Future)

### Unit Tests
```bash
# TODO: Add Jest/Mocha tests
npm test
```

### E2E Tests
```bash
# TODO: Add Appium/Detox tests
npm run e2e:ios
npm run e2e:android
```

### CI/CD Pipeline
```yaml
# TODO: Add GitHub Actions workflow
# - Build on every commit
# - Run tests
# - Deploy to TestFlight/Play Console
```

---

## Success Criteria

Before release, ensure:

- ✅ All checklist items passed
- ✅ All test scenarios passed
- ✅ No critical bugs
- ✅ Performance acceptable
- ✅ Security verified
- ✅ Beta testers satisfied
- ✅ App Store requirements met
- ✅ Privacy policy reviewed
- ✅ Terms of service reviewed

---

**Happy Testing!** 🚀
