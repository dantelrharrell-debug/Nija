# NIJA Mobile App - Build & Deployment Guide

This guide walks you through building and deploying the NIJA mobile app for iOS and Android.

## Table of Contents
1. [Prerequisites](#prerequisites)
2. [Initial Setup](#initial-setup)
3. [Building for iOS](#building-for-ios)
4. [Building for Android](#building-for-android)
5. [App Store Submission](#app-store-submission)
6. [Testing](#testing)
7. [Troubleshooting](#troubleshooting)

---

## Prerequisites

### Required Software

**For iOS Development:**
- macOS (required for iOS builds)
- Xcode 14.0+ (download from Mac App Store)
- CocoaPods (`sudo gem install cocoapods`)
- Apple Developer Account ($99/year)

**For Android Development:**
- Android Studio (download from developer.android.com)
- Java Development Kit (JDK) 11+
- Android SDK (API level 33+)
- Google Play Developer Account ($25 one-time fee)

**For Both Platforms:**
- Node.js 18+ and npm
- Git

### Verify Prerequisites

```bash
# Check Node.js version
node --version  # Should be 18.0.0 or higher

# Check npm version
npm --version

# Check Xcode (macOS only)
xcodebuild -version

# Check Android Studio
android --version  # or check in Android Studio
```

---

## Initial Setup

### 1. Install Dependencies

```bash
# Navigate to project root
cd /path/to/Nija

# Install npm dependencies
npm install

# Verify Capacitor installation
npx cap --version
```

### 2. Configure API Endpoint

Update the API endpoint in `frontend/static/js/app.js`:

```javascript
// For production
const API_BASE_URL = 'https://your-production-api.com/api';

// For development
const API_BASE_URL = 'http://localhost:5000/api';
```

### 3. Prepare Web Assets

Ensure your frontend is ready:
- All HTML, CSS, JS files are in `frontend/`
- Images and icons are optimized
- Manifest.json is configured

---

## Building for iOS

### Step 1: Add iOS Platform

```bash
# Add iOS platform to Capacitor
npm run cap:add:ios

# This creates the ios/ directory with Xcode project
```

### Step 2: Configure iOS Project

1. **Open in Xcode:**
   ```bash
   npm run cap:open:ios
   ```

2. **Set Bundle Identifier:**
   - Select project in Xcode navigator
   - Select "App" target
   - Under "General" tab, set Bundle Identifier: `com.nija.trading`

3. **Configure Signing:**
   - Under "Signing & Capabilities" tab
   - Select your Team (requires Apple Developer Account)
   - Xcode will automatically create provisioning profiles

4. **Add Required Capabilities:**
   - Click "+ Capability" button
   - Add: Push Notifications
   - Add: Background Modes → Remote notifications

5. **Update Info.plist Privacy Descriptions:**
   - Open `App/App/Info.plist`
   - Add privacy descriptions (see `mobile/ios/README.md`)

### Step 3: Add App Icons

1. Create app icons using a tool like:
   - https://appicon.co/
   - https://makeappicon.com/

2. Add to Xcode:
   - Open `App/App/Assets.xcassets/AppIcon.appiconset/`
   - Drag and drop icon files
   - Or use Xcode's asset catalog

### Step 4: Configure Launch Screen

1. Open `App/App/Base.lproj/LaunchScreen.storyboard`
2. Customize background color: #0f172a
3. Add app logo (optional)

### Step 5: Build for Testing

```bash
# Sync web assets with iOS
npm run cap:sync

# Open in Xcode
npm run cap:open:ios

# Select a simulator or device
# Click Run (⌘R) to build and test
```

### Step 6: Build for App Store

1. **In Xcode:**
   - Select "Any iOS Device" as target
   - Product → Archive
   - Wait for build to complete

2. **Upload to App Store Connect:**
   - Window → Organizer
   - Select your archive
   - Click "Distribute App"
   - Choose "App Store Connect"
   - Follow prompts to upload

---

## Building for Android

### Step 1: Add Android Platform

```bash
# Add Android platform to Capacitor
npm run cap:add:android

# This creates the android/ directory with Android Studio project
```

### Step 2: Configure Android Project

1. **Open in Android Studio:**
   ```bash
   npm run cap:open:android
   ```

2. **Update App Configuration:**
   
   Edit `android/app/build.gradle`:
   ```gradle
   defaultConfig {
       applicationId "com.nija.trading"
       minSdkVersion 22
       targetSdkVersion 33
       versionCode 1
       versionName "1.0.0"
   }
   ```

3. **Configure Permissions:**
   
   Edit `android/app/src/main/AndroidManifest.xml`:
   ```xml
   <uses-permission android:name="android.permission.INTERNET" />
   <uses-permission android:name="android.permission.ACCESS_NETWORK_STATE" />
   <uses-permission android:name="android.permission.POST_NOTIFICATIONS" />
   ```

4. **Add Network Security Config:**
   
   Create `android/app/src/main/res/xml/network_security_config.xml`
   (See `mobile/android/README.md` for details)

### Step 3: Add App Icons

1. **Generate Icons:**
   - Use Android Asset Studio: https://romannurik.github.io/AndroidAssetStudio/
   - Or use an icon generator

2. **Add to Project:**
   - Replace files in `android/app/src/main/res/mipmap-*/`
   - Include all density folders (mdpi, hdpi, xhdpi, xxhdpi, xxxhdpi)

### Step 4: Generate Signing Key

```bash
# Generate release keystore
keytool -genkey -v -keystore android/release.keystore \
  -alias nija-release -keyalg RSA -keysize 2048 -validity 10000

# Follow prompts to set passwords
# IMPORTANT: Save passwords securely!
```

**Create `android/key.properties`:**
```properties
storePassword=YOUR_KEYSTORE_PASSWORD
keyPassword=YOUR_KEY_PASSWORD
keyAlias=nija-release
storeFile=release.keystore
```

**⚠️ IMPORTANT:** Add to `.gitignore`:
```
android/release.keystore
android/key.properties
```

### Step 5: Configure Release Signing

Edit `android/app/build.gradle`:

```gradle
// Add above android { block
def keystoreProperties = new Properties()
def keystorePropertiesFile = rootProject.file('key.properties')
if (keystorePropertiesFile.exists()) {
    keystoreProperties.load(new FileInputStream(keystorePropertiesFile))
}

android {
    // ... existing config ...
    
    signingConfigs {
        release {
            keyAlias keystoreProperties['keyAlias']
            keyPassword keystoreProperties['keyPassword']
            storeFile keystoreProperties['storeFile'] ? file(keystoreProperties['storeFile']) : null
            storePassword keystoreProperties['storePassword']
        }
    }
    
    buildTypes {
        release {
            signingConfig signingConfigs.release
            minifyEnabled true
            shrinkResources true
            proguardFiles getDefaultProguardFile('proguard-android-optimize.txt'), 'proguard-rules.pro'
        }
    }
}
```

### Step 6: Build Release APK/AAB

```bash
# Sync web assets
npm run cap:sync

# Build release APK
cd android
./gradlew assembleRelease

# Build release AAB (App Bundle - recommended for Play Store)
./gradlew bundleRelease

# Outputs:
# APK: android/app/build/outputs/apk/release/app-release.apk
# AAB: android/app/build/outputs/bundle/release/app-release.aab
```

---

## App Store Submission

### iOS App Store (via App Store Connect)

#### 1. Prepare App Store Connect

1. Go to https://appstoreconnect.apple.com/
2. Click "My Apps" → "+" → "New App"
3. Fill in app information:
   - Platform: iOS
   - Name: NIJA
   - Bundle ID: com.nija.trading
   - SKU: unique identifier
   - User Access: Full Access

#### 2. Complete App Information

**App Information:**
- Name: NIJA AI Trading Platform
- Subtitle: Automated Crypto Trading
- Category: Finance
- Content Rights: Own or have rights to use

**Pricing and Availability:**
- Price: Free (with in-app purchases)
- Availability: All countries (or select specific)

**App Privacy:**
- Privacy Policy URL: https://nija.app/privacy
- Privacy Details: Complete questionnaire about data collection

#### 3. Prepare Screenshots

Required sizes:
- 6.7" (iPhone 14 Pro Max): 1290x2796
- 6.5" (iPhone 11 Pro Max): 1242x2688
- 5.5" (iPhone 8 Plus): 1242x2208

At least 2 screenshots per size required.

#### 4. Write App Description

**App Description (max 4000 chars):**
```
NIJA is your AI-powered cryptocurrency trading platform that works 24/7 to maximize your trading opportunities.

Features:
• Automated Trading: AI algorithms monitor markets and execute trades automatically
• Multi-Exchange Support: Connect Coinbase, Kraken, Binance, and more
• Real-Time Monitoring: Track positions, P&L, and trading performance
• Risk Management: Set position limits and stop losses
• Instant Alerts: Get notified of trade executions and market movements

[Continue with compelling description...]
```

**Keywords (max 100 chars):**
```
crypto,trading,bitcoin,ethereum,automated,ai,cryptocurrency,finance
```

#### 5. Upload Build

1. In Xcode, archive your app (Product → Archive)
2. Upload to App Store Connect
3. Wait for processing (usually 15-30 minutes)
4. Select build in App Store Connect

#### 6. Submit for Review

1. Complete all sections (green checkmarks)
2. Add demo account credentials if required
3. Add notes for reviewer (explain trading features)
4. Submit for review
5. Wait for approval (typically 1-3 days)

---

### Android Play Store (via Google Play Console)

#### 1. Create App in Play Console

1. Go to https://play.google.com/console/
2. Click "Create app"
3. Fill in app details:
   - App name: NIJA
   - Default language: English (US)
   - App or game: App
   - Free or paid: Free

#### 2. Set Up App Content

**App Access:**
- Provide demo login credentials for testing

**Ads:**
- Declare if app contains ads (No for NIJA)

**Content Rating:**
- Complete IARC questionnaire
- Select "Finance" category
- Answer questions honestly
- Likely rating: Everyone or Teen

**Target Audience:**
- Age: 18+
- Declare app not designed for children

**Privacy Policy:**
- URL: https://nija.app/privacy

#### 3. Complete Store Listing

**Main Store Listing:**
- Short description (80 chars max)
- Full description (4000 chars max)
- App icon: 512x512 PNG
- Feature graphic: 1024x500 PNG

**Screenshots:**
- Phone: Min 2, max 8
- 7" tablet (optional)
- 10" tablet (optional)

**App Category:**
- Category: Finance
- Tags: Trading, Cryptocurrency, Bitcoin

#### 4. Upload Release

1. Go to "Production" track
2. Create new release
3. Upload AAB file
4. Add release notes
5. Save and review

#### 5. Roll Out Release

1. Review all sections
2. Start rollout to production
3. Choose rollout percentage (start with 10-20%)
4. Submit for review
5. Wait for approval (typically 1-7 days)

---

## Testing

### Testing on Devices

**iOS:**
```bash
# Physical device
1. Connect iPhone via USB
2. Open Xcode
3. Select your device
4. Click Run

# Simulator
1. Open Xcode
2. Select simulator (e.g., iPhone 14)
3. Click Run
```

**Android:**
```bash
# Physical device
1. Enable Developer Mode on device
2. Enable USB Debugging
3. Connect via USB
4. Run: npm run cap:sync
5. In Android Studio, click Run

# Emulator
1. Open Android Studio
2. AVD Manager → Create Virtual Device
3. Select device and system image
4. Start emulator
5. Click Run
```

### Beta Testing

**iOS (TestFlight):**
1. Upload build to App Store Connect
2. Go to TestFlight section
3. Add internal testers (up to 100)
4. Add external testers (up to 10,000)
5. Share TestFlight link

**Android (Internal Testing):**
1. Create internal testing track in Play Console
2. Add tester email addresses
3. Share testing opt-in link
4. Testers download from Play Store

---

## Troubleshooting

### Common iOS Issues

**Build Error: "No signing certificate"**
- Solution: Add Apple Developer account in Xcode preferences
- Go to Xcode → Preferences → Accounts → Add Account

**Pod Install Fails:**
```bash
cd ios/App
pod deintegrate
pod install
```

**App Crashes on Launch:**
- Check Console.app for crash logs
- Verify Info.plist configuration
- Check for missing permissions

### Common Android Issues

**Gradle Build Fails:**
```bash
cd android
./gradlew clean
./gradlew build
```

**Keystore Error:**
- Verify key.properties file exists
- Check keystore passwords are correct
- Ensure release.keystore is in android/ directory

**App Not Installing:**
- Increase versionCode in build.gradle
- Uninstall previous version
- Check device has enough storage

### Common Capacitor Issues

**Changes Not Reflecting:**
```bash
npm run cap:sync
```

**Plugin Not Working:**
```bash
npm run cap:update
npm install
npm run cap:sync
```

**White Screen on Launch:**
- Check browser console for errors
- Verify webDir in capacitor.config.json
- Check that index.html exists in frontend/

---

## Continuous Integration (Optional)

### GitHub Actions for iOS

Create `.github/workflows/ios-build.yml`:

```yaml
name: iOS Build

on:
  push:
    branches: [ main ]

jobs:
  build:
    runs-on: macos-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-node@v3
        with:
          node-version: 18
      - run: npm install
      - run: npm run cap:sync
      # Additional steps for signing and building
```

### GitHub Actions for Android

Create `.github/workflows/android-build.yml`:

```yaml
name: Android Build

on:
  push:
    branches: [ main ]

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-node@v3
        with:
          node-version: 18
      - run: npm install
      - run: npm run cap:sync
      - run: cd android && ./gradlew assembleRelease
```

---

## Support

For issues or questions:
- GitHub Issues: https://github.com/dantelrharrell-debug/Nija/issues
- Email: support@nija.app
- Documentation: https://nija.app/docs

---

**Congratulations!** You're now ready to build and deploy the NIJA mobile app! 🎉
