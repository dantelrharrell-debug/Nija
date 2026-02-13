# App Store Screenshot Guide

## Overview

This guide provides templates and instructions for creating professional screenshots for the NIJA mobile app submission to Apple App Store and Google Play Store.

## Screenshot Requirements

### iOS App Store

**6.7" Display (iPhone 14 Pro Max)** - 1290 x 2796 pixels
- Minimum: 3 screenshots
- Maximum: 10 screenshots
- Format: PNG or JPEG
- No alpha channel

**5.5" Display (iPhone 8 Plus)** - 1242 x 2208 pixels
- Minimum: 3 screenshots
- Maximum: 10 screenshots
- Format: PNG or JPEG
- No alpha channel

### Google Play Store

**Phone Screenshots**
- Minimum: 2 screenshots
- Maximum: 8 screenshots
- Dimensions: 16:9 or 9:16 aspect ratio
- Min width/height: 320px
- Max width/height: 3840px
- Format: PNG or JPEG (no transparency)

**Feature Graphic** (Required)
- Dimensions: 1024 x 500 pixels
- Format: PNG or JPEG
- High quality image showcasing app

## Required Screenshots

### Screenshot 1: Subscription Selection Screen

**Description:** "Choose the perfect plan for your trading needs"

**Elements to Capture:**
- [ ] All three subscription tiers visible (Basic, Pro, Enterprise)
- [ ] Pricing clearly displayed
- [ ] Monthly/Yearly toggle in view
- [ ] "Save 20%" badge visible on yearly option
- [ ] Feature comparison visible
- [ ] "Most Popular" badge on Pro tier
- [ ] Clean, professional UI
- [ ] Dark theme enabled

**How to Create:**
```javascript
// In app console or before screenshot
showSubscriptionModal('free');

// Ensure:
// - Monthly is selected (default)
// - All tiers visible
// - Clean UI state
```

**Text Overlay (Optional):**
- Top: "Flexible Subscription Plans"
- Bottom: "14-day free trial on all plans"

---

### Screenshot 2: Pro Tier Features

**Description:** "Advanced AI-powered trading features"

**Elements to Capture:**
- [ ] Dashboard showing "Pro" tier badge
- [ ] Advanced features highlighted
- [ ] Meta-AI optimization panel
- [ ] MMIN multi-market intelligence
- [ ] Active trading positions
- [ ] Performance metrics
- [ ] Professional, data-rich interface

**How to Create:**
- Use demo account with Pro tier
- Populate with sample data
- Show impressive performance metrics
- Highlight AI features

**Text Overlay (Optional):**
- Top: "AI-Powered Trading"
- Bottom: "Meta-AI optimization & MMIN intelligence"

---

### Screenshot 3: Education Mode (Free Tier)

**Description:** "Learn trading risk-free with paper trading"

**Elements to Capture:**
- [ ] "Education Mode" banner visible
- [ ] "Simulated Funds - Not Real Money" indicator
- [ ] Paper trading dashboard
- [ ] $10,000 starting balance
- [ ] Practice trades visible
- [ ] Educational tooltips
- [ ] Safety emphasis

**How to Create:**
- Switch to education mode
- Show simulated balance
- Display practice trades
- Emphasize learning aspect

**Text Overlay (Optional):**
- Top: "Practice Without Risk"
- Bottom: "Start with $10,000 simulated funds"

---

### Screenshot 4: Live Trading Dashboard

**Description:** "Real-time cryptocurrency trading"

**Elements to Capture:**
- [ ] Active positions displayed
- [ ] Live market data
- [ ] P&L metrics
- [ ] Recent trades
- [ ] Exchange connections
- [ ] Real-time updates indicator

**How to Create:**
- Use sandbox/demo data
- Show active positions
- Display positive P&L
- Clean, professional layout

**Text Overlay (Optional):**
- Top: "Live Trading Platform"
- Bottom: "Connect to Coinbase, Kraken & more"

---

### Screenshot 5: Security & Safety Features

**Description:** "Advanced risk management and safety controls"

**Elements to Capture:**
- [ ] Emergency stop button prominent
- [ ] Risk management settings
- [ ] Stop-loss indicators
- [ ] Position limits displayed
- [ ] Safety disclaimers visible
- [ ] Secure connection indicators

**How to Create:**
- Navigate to settings/safety screen
- Show risk controls
- Display safety features
- Emphasize security

**Text Overlay (Optional):**
- Top: "Your Safety is Priority"
- Bottom: "Advanced risk controls & emergency stop"

---

### Screenshot 6: Account Settings & Management

**Description:** "Easy subscription and account management"

**Elements to Capture:**
- [ ] Current subscription tier shown
- [ ] Subscription status
- [ ] Manage subscription button
- [ ] Account settings
- [ ] Help & support links
- [ ] Clear navigation

**How to Create:**
- Open settings screen
- Show subscription details
- Display account info
- Clean layout

**Text Overlay (Optional):**
- Top: "Simple Account Management"
- Bottom: "Manage your subscription anytime"

---

## Feature Graphic (Android Only)

### Dimensions: 1024 x 500 pixels

**Design Elements:**
- NIJA logo prominently displayed
- "AI Trading Platform" tagline
- Visual elements: charts, graphs, AI symbols
- Color scheme: Dark blues, purples (#6366f1)
- Professional, modern aesthetic

**Text to Include:**
- "NIJA"
- "AI-Powered Trading Platform"
- "Learn • Trade • Profit"

**Design Tips:**
- Keep text large and readable
- Use brand colors
- High contrast
- No screenshots in feature graphic
- Pure promotional image

---

## Screenshot Creation Process

### Option 1: Actual Device Screenshots

1. **Prepare Device**
   - Clean device with full battery
   - Remove notifications
   - Set to maximum brightness
   - Use dark mode (consistent with app theme)

2. **Populate App with Data**
   ```javascript
   // Use demo data population script
   populateDemoData({
     tier: 'pro',
     positions: 5,
     trades: 20,
     balance: 15000,
     profitPercent: 12.5
   });
   ```

3. **Take Screenshots**
   - iPhone: Volume Up + Side button
   - Android: Volume Down + Power button
   - Ensure full screen (no status bar issues)
   - Take multiple angles of each screen

4. **Review & Select Best**
   - Sharp, clear images
   - No UI glitches
   - Proper alignment
   - Consistent lighting

### Option 2: Simulator/Emulator Screenshots

1. **iOS Simulator**
   ```bash
   # Open Xcode
   # Select iPhone 14 Pro Max simulator
   # Run app
   # Screenshot: Cmd + S
   ```

2. **Android Emulator**
   ```bash
   # Open Android Studio
   # Launch emulator with Google Play API
   # Run app
   # Screenshot button in emulator toolbar
   ```

### Option 3: Professional Screenshot Service

Consider using:
- **AppLaunchpad** - Automated screenshot generation
- **Fastlane** - CLI tool for screenshots
- **Screenshot Builder** - iOS app for creating promo screenshots

## Screenshot Enhancement

### Recommended Tools

1. **Sketch / Figma** - Add text overlays and frames
2. **Adobe Photoshop** - Professional editing
3. **Canva** - Easy template-based design
4. **Previewed** - App mockup generator

### Enhancement Steps

1. **Resize to Exact Dimensions**
   - Use iOS/Android specific sizes
   - Maintain aspect ratio
   - No cropping of important content

2. **Add Device Frame** (Optional but Recommended)
   - Makes screenshots more appealing
   - Shows app in context
   - Use official device mockups

3. **Add Text Overlays** (Optional)
   - Keep text minimal (1-2 lines max)
   - Use large, readable fonts
   - High contrast with background
   - Match brand colors

4. **Optimize File Size**
   - Compress without quality loss
   - Use PNG for screenshots with text
   - Use JPEG for photo-realistic content
   - Target < 500KB per screenshot

## Screenshot Order & Strategy

### Recommended Order (Most Important First)

1. **Subscription Selection** - Shows value proposition
2. **Pro Features** - Highlights premium offering
3. **Education Mode** - Shows accessibility
4. **Live Trading** - Core functionality
5. **Safety Features** - Builds trust
6. **Account Management** - Shows ease of use

### Alternative Order (Feature-First)

1. **Live Trading Dashboard** - Core functionality first
2. **Pro AI Features** - Premium value
3. **Subscription Plans** - Clear pricing
4. **Education Mode** - Risk-free learning
5. **Safety & Security** - Trust building
6. **Account Settings** - Management ease

## Text Captions for Screenshots

### iOS App Store (Optional Promotional Text)

**Screenshot 1:**
"Choose your perfect plan with 14-day free trial"

**Screenshot 2:**
"Advanced AI features for professional traders"

**Screenshot 3:**
"Practice risk-free with $10,000 simulated funds"

**Screenshot 4:**
"Trade crypto across multiple exchanges"

**Screenshot 5:**
"Bank-grade security with advanced risk controls"

**Screenshot 6:**
"Manage everything from one simple dashboard"

### Google Play Store (Required Descriptions)

Each screenshot needs a description (max 80 characters):

1. "Flexible subscription plans with 14-day free trial"
2. "AI-powered trading with Meta-AI optimization"
3. "Learn trading risk-free in education mode"
4. "Trade cryptocurrencies across top exchanges"
5. "Advanced safety features and risk management"
6. "Simple account and subscription management"

## Quality Checklist

Before submitting screenshots:

- [ ] Correct dimensions for each platform
- [ ] High resolution (not blurry or pixelated)
- [ ] Consistent visual style across all screenshots
- [ ] No placeholder text or "Lorem ipsum"
- [ ] No spelling or grammar errors
- [ ] Brand colors consistent
- [ ] UI is in good state (no loading spinners)
- [ ] Data looks realistic and professional
- [ ] No personal/test data visible
- [ ] File sizes optimized
- [ ] Named clearly (ios_1.png, android_1.png, etc.)

## Localization Considerations

If supporting multiple languages:

- [ ] Create screenshot sets for each language
- [ ] Translate all text overlays
- [ ] Verify UI text is translated
- [ ] Check text doesn't overflow
- [ ] Maintain consistent layout

## Testing Screenshots

Before submission:

1. **View on Actual Device**
   - How do they look on phone screen?
   - Are they recognizable at thumbnail size?
   - Do they tell a story?

2. **Show to Others**
   - Can they understand the app's value?
   - Is the pricing clear?
   - Do they want to try it?

3. **A/B Test Ideas**
   - Try different screenshot orders
   - Test with/without text overlays
   - Get feedback on which converts better

## Storage & Organization

```
screenshots/
├── ios/
│   ├── 6.7inch/
│   │   ├── 1_subscription.png
│   │   ├── 2_pro_features.png
│   │   ├── 3_education.png
│   │   ├── 4_live_trading.png
│   │   ├── 5_security.png
│   │   └── 6_settings.png
│   └── 5.5inch/
│       └── (same as above)
├── android/
│   ├── phone/
│   │   ├── 1_subscription.png
│   │   ├── 2_pro_features.png
│   │   └── (etc.)
│   └── feature_graphic.png
└── source/
    └── (original unedited screenshots)
```

## Resources

**iOS Screenshot Sizes:**
- https://developer.apple.com/help/app-store-connect/reference/screenshot-specifications

**Android Screenshot Requirements:**
- https://support.google.com/googleplay/android-developer/answer/9866151

**Free Device Mockups:**
- https://mockuphone.com
- https://www.screely.com
- https://previewed.app

**Screenshot Tools:**
- https://www.fastlane.tools
- https://appure.io
- https://launchkit.io

---

**Last Updated:** February 13, 2026  
**Next Review:** Before app store submission
