# Mobile App Assets

This directory contains assets required for the NIJA mobile app.

## Structure

```
mobile/assets/
├── icons/           # App icons for iOS and Android
├── splash/          # Splash screen images
└── README.md        # This file
```

## App Icons

### Required Sizes

#### iOS Icons
- **1024x1024** - App Store icon
- **180x180** - iPhone (@3x)
- **120x120** - iPhone (@2x)
- **167x167** - iPad Pro (@2x)
- **152x152** - iPad (@2x)
- **76x76** - iPad (@1x)
- **60x60** - iPhone (@1x)
- **40x40** - Spotlight (@2x)
- **29x29** - Settings (@1x)
- **58x58** - Settings (@2x)
- **87x87** - Settings (@3x)

#### Android Icons
- **512x512** - Google Play Store icon
- **192x192** - xxxhdpi
- **144x144** - xxhdpi
- **96x96** - xhdpi
- **72x72** - hdpi
- **48x48** - mdpi

### Design Guidelines

**Colors:**
- Primary: #6366f1 (Indigo)
- Background: #0f172a (Dark blue)

**Requirements:**
- No transparency in background (Android)
- Rounded corners handled by OS
- Clear, recognizable at small sizes
- Consistent branding

**Recommended:**
- Use a simple, bold design
- Avoid small text or details
- Use high contrast
- Test on different backgrounds

### Icon Generation Tools

1. **Online Generators:**
   - https://appicon.co/
   - https://makeappicon.com/
   - https://icon.kitchen/

2. **Design Tools:**
   - Figma (free)
   - Adobe Illustrator
   - Sketch

3. **Command Line:**
   ```bash
   # Using ImageMagick
   convert logo.png -resize 1024x1024 icon-1024.png
   convert logo.png -resize 512x512 icon-512.png
   # etc.
   ```

### Adding Icons to Project

**iOS:**
```bash
# After generating icons, run:
npm run cap:sync

# Then in Xcode:
# 1. Open ios/App/App.xcworkspace
# 2. Select Assets.xcassets
# 3. Select AppIcon
# 4. Drag and drop icon files to appropriate slots
```

**Android:**
```bash
# Copy icons to res directories:
cp icon-48.png android/app/src/main/res/mipmap-mdpi/ic_launcher.png
cp icon-72.png android/app/src/main/res/mipmap-hdpi/ic_launcher.png
cp icon-96.png android/app/src/main/res/mipmap-xhdpi/ic_launcher.png
cp icon-144.png android/app/src/main/res/mipmap-xxhdpi/ic_launcher.png
cp icon-192.png android/app/src/main/res/mipmap-xxxhdpi/ic_launcher.png
```

## Splash Screens

### Required Sizes

#### iOS Launch Images
- **1242x2688** - iPhone Xs Max, 11 Pro Max
- **1125x2436** - iPhone X, Xs, 11 Pro
- **828x1792** - iPhone 11, XR
- **1242x2208** - iPhone 8 Plus, 7 Plus, 6s Plus
- **750x1334** - iPhone SE, 8, 7, 6s
- **640x1136** - iPhone SE (1st gen), 5s

#### Android Splash Screens
- **drawable-xxxhdpi** - 1920x1920
- **drawable-xxhdpi** - 1440x1440
- **drawable-xhdpi** - 960x960
- **drawable-hdpi** - 720x720
- **drawable-mdpi** - 480x480

### Design Guidelines

**Layout:**
```
┌─────────────────────┐
│                     │
│                     │
│    [NIJA Logo]      │
│                     │
│    Loading...       │
│                     │
└─────────────────────┘
```

**Colors:**
- Background: #0f172a (Dark blue)
- Logo: White or #6366f1
- Loading indicator: #6366f1

**Requirements:**
- Center-aligned logo
- Safe area margins (iOS)
- Works in portrait and landscape
- Fast loading (< 500KB)

### Splash Screen Configuration

Configured in `capacitor.config.json`:

```json
{
  "plugins": {
    "SplashScreen": {
      "launchShowDuration": 2000,
      "backgroundColor": "#0f172a",
      "showSpinner": false,
      "androidSpinnerStyle": "large",
      "spinnerColor": "#6366f1",
      "splashFullScreen": true,
      "splashImmersive": true
    }
  }
}
```

### Adding Splash Screens

**iOS:**
1. Open Xcode
2. Navigate to App/App/Base.lproj/LaunchScreen.storyboard
3. Add ImageView with your logo
4. Set background color to #0f172a
5. Add Auto Layout constraints

**Android:**
1. Create splash.png in various densities
2. Copy to res/drawable-* directories
3. Update styles.xml:
   ```xml
   <style name="AppTheme.NoActionBarLaunch">
       <item name="android:background">@drawable/splash</item>
   </style>
   ```

## Screenshots (for App Stores)

### iOS App Store

**Required Sizes:**
- 6.7" (iPhone 14 Pro Max): 1290x2796
- 6.5" (iPhone 11 Pro Max): 1242x2688
- 5.5" (iPhone 8 Plus): 1242x2208

**iPad:**
- 12.9" (iPad Pro): 2048x2732

**Quantity:**
- Minimum: 2 screenshots per size
- Maximum: 10 screenshots per size

### Google Play Store

**Required Sizes:**
- Phone: 1080x1920 (or 1080x2340 for 19.5:9)
- 7" Tablet: 1200x1920
- 10" Tablet: 1600x2560

**Quantity:**
- Minimum: 2 screenshots
- Maximum: 8 screenshots

### Screenshot Guidelines

**Content:**
1. Main dashboard showing key features
2. Trading control interface
3. Position management
4. Charts and analytics
5. Settings and account management

**Design:**
- Use actual app UI
- Add descriptive captions
- Show key features
- Use realistic data (not test data)
- Consistent branding

**Tools:**
- iOS: Xcode Simulator + Screenshot
- Android: Android Studio Emulator + Screenshot
- Design: Figma, Sketch, Photoshop for annotations

## Marketing Assets

### Feature Graphic (Google Play)

**Size:** 1024x500 pixels

**Content:**
- App name/logo
- Key features
- Eye-catching design
- No screenshots

### Promo Video (Optional)

**Length:** 15-30 seconds

**Content:**
- Quick app demo
- Key features highlight
- Call to action

**Platforms:**
- YouTube (for App Store)
- Uploaded to Play Console (for Google Play)

## Checklist

Before app submission:

- [ ] All required icon sizes generated
- [ ] Icons added to iOS project
- [ ] Icons added to Android project
- [ ] Splash screens configured
- [ ] Screenshots captured for all required sizes
- [ ] Feature graphic created (Android)
- [ ] Marketing assets prepared
- [ ] All assets optimized (< 1MB each)
- [ ] No placeholder or demo content
- [ ] Branding consistent across all assets

## Notes

- All assets should be in PNG format (except videos)
- Use RGB color space (not CMYK)
- No transparency in Android icons
- iOS icons automatically rounded by system
- Test on actual devices before submission
- Keep source files (AI, PSD, Sketch) for future updates

## Resources

- [iOS Human Interface Guidelines](https://developer.apple.com/design/human-interface-guidelines/)
- [Android Material Design](https://material.io/design)
- [App Store Screenshot Requirements](https://help.apple.com/app-store-connect/#/devd274dd925)
- [Google Play Asset Guidelines](https://support.google.com/googleplay/android-developer/answer/9866151)
