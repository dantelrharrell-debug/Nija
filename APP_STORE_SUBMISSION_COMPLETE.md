# NIJA Mobile App - App Store Submission Checklist

Complete checklist for submitting NIJA to Apple App Store and Google Play Store.

## 📱 Apple App Store Submission

### Prerequisites
- [ ] Apple Developer Account ($99/year)
- [ ] Xcode 14+ on macOS
- [ ] iOS app built and tested
- [ ] TestFlight beta testing completed (optional but recommended)

### App Information

**App Name:** NIJA - AI Crypto Trading Bot

**Subtitle (30 characters):** Automated Trading Made Simple

**Keywords (100 characters):** crypto trading bot,automated trading,cryptocurrency,bitcoin,AI trading,portfolio,investment,RSI

**Privacy Policy URL:** https://nija.app/privacy-policy

**Support URL:** https://nija.app/support

**Marketing URL:** https://nija.app

**Category:** Finance

**Age Rating:** 17+ (Financial transactions)

### App Description (4000 characters max)

```
NIJA is an advanced AI-powered cryptocurrency trading bot that automates your trading strategy across multiple exchanges. Trade smarter, not harder.

🤖 AUTOMATED TRADING
• Proprietary Dual RSI (9+14) strategy
• 24/7 market scanning across 732+ crypto pairs
• Intelligent entry and exit signals
• Dynamic position management
• Automatic profit compounding

📊 MULTI-EXCHANGE SUPPORT
• Coinbase Advanced Trade
• Kraken Pro
• Binance
• OKX
• Alpaca (for stocks)

🛡️ RISK MANAGEMENT
• Customizable risk profiles (Conservative to Aggressive)
• Automatic stop-loss protection
• Position size limits
• Daily profit targets
• Capital preservation mode

📈 REAL-TIME MONITORING
• Live position tracking with P&L
• Trade history and analytics
• Performance metrics and charts
• Push notifications for trades
• WebSocket real-time updates

🎓 EDUCATION (PRO TIER)
• Trading fundamentals tutorials
• Technical analysis lessons
• Strategy development guides
• Risk management training
• AI-powered Q&A

💰 SUBSCRIPTION TIERS
• FREE: Paper trading to practice strategies
• BASIC ($49/mo): Live trading with core features
• PRO ($99/mo): Advanced AI + education content
• ENTERPRISE ($299/mo): Full features + white-label

⚠️ IMPORTANT DISCLAIMERS
Cryptocurrency trading involves substantial risk of loss. Only invest capital you can afford to lose. Past performance does not guarantee future results. NIJA is a trading tool and does not provide investment advice. Users are responsible for their own trading decisions.

🔒 SECURITY & PRIVACY
• Bank-level encryption
• API keys never leave your device
• No third-party data sharing
• SOC 2 compliant infrastructure
• Two-factor authentication

FEATURES BY TIER

FREE TIER
✓ Paper trading (virtual money)
✓ APEX V7.2 strategy
✓ 1 exchange connection
✓ Basic analytics
✓ Community support

BASIC TIER ($49/month)
✓ Live trading
✓ 2 exchange connections
✓ 5 concurrent positions
✓ 30 daily trades
✓ Email support (48h)
✓ Mobile app access
✓ Trade history export

PRO TIER ($99/month) ⭐ MOST POPULAR
✓ Everything in Basic
✓ 5 exchange connections
✓ 10 concurrent positions
✓ 100 daily trades
✓ Advanced AI features (Meta AI, MMIN)
✓ Education content
✓ Custom risk profiles
✓ TradingView webhooks
✓ Priority support (24h)
✓ Advanced analytics

ENTERPRISE TIER ($299/month)
✓ Everything in Pro
✓ Unlimited positions & trades
✓ Unlimited exchanges
✓ White-label option
✓ Dedicated support
✓ API access
✓ Custom integrations

WHY NIJA?

1. PROVEN STRATEGY: Our Dual RSI strategy has been backtested across 5 years of market data
2. AUTOMATION: Never miss a trading opportunity - NIJA works 24/7
3. RISK-FIRST: Capital protection is our #1 priority
4. TRANSPARENCY: Full trade history and performance metrics
5. EDUCATION: Learn while you earn with our comprehensive guides

GETTING STARTED

1. Download NIJA and create your free account
2. Connect your exchange API keys (read-only for safety)
3. Choose your risk profile
4. Start with paper trading to learn
5. Upgrade to live trading when ready

CUSTOMER SUPPORT
• In-app chat support
• Email: support@nija.app
• Discord community: discord.gg/nija
• Documentation: docs.nija.app

LEGAL
By using NIJA, you agree to our Terms of Service and Privacy Policy. NIJA is not a registered investment advisor. All trading decisions are made by the user.

Download NIJA today and start trading smarter! 🚀
```

### Screenshots Requirements

**iPhone (6.7"):** 6-10 screenshots
1. Dashboard with active positions
2. Trading performance chart
3. Position details screen
4. Risk management settings
5. Education content viewer
6. Subscription tiers comparison

**iPhone (6.5"):** Same 6-10 screenshots (different device size)

**iPhone (5.5"):** Same 6-10 screenshots (different device size)

**iPad Pro (12.9"):** 6-10 screenshots optimized for tablet

### App Preview Videos (Optional but Recommended)

- **Length:** 15-30 seconds
- **Content:** Show key features - trading, analytics, education
- **Audio:** Optional background music, no voiceover needed
- **Orientation:** Portrait for iPhone, landscape optional for iPad

### App Review Information

**Contact Information:**
- First Name: [Your First Name]
- Last Name: [Your Last Name]
- Phone: [Your Phone Number]
- Email: support@nija.app

**Demo Account Credentials:**
```
Username: reviewer@nija.app
Password: AppleReview2026!

Note: Account is in demo mode with paper trading only.
Real trading is disabled for review purposes.
```

**Notes for Reviewer:**
```
Thank you for reviewing NIJA!

DEMO ACCOUNT SETUP:
- Login with: reviewer@nija.app / AppleReview2026!
- App is in "App Store Mode" (APP_STORE_MODE=true)
- All trading features visible but execution is disabled
- Paper trading (simulated) is available for testing
- No real money can be traded during review

TESTING THE APP:
1. Login with demo credentials
2. View dashboard with simulated positions
3. Check education content (Pro tier features unlocked for demo)
4. Test push notifications (trade alerts)
5. Review subscription tiers (purchases disabled in demo)

COMPLIANCE NOTES:
- Risk disclaimers shown prominently throughout app
- Users must acknowledge risks before live trading
- Age-gated (17+) for financial content
- Privacy policy and terms clearly displayed
- No investment advice provided

FINANCIAL DISCLOSURE:
NIJA is a trading automation tool. We do not:
- Provide investment advice
- Guarantee profits
- Handle user funds
- Process payments (uses Stripe/Apple IAP)

All API keys are encrypted and stored securely on device.

If you have questions, please contact: support@nija.app
```

### Age Rating Questionnaire

Select the appropriate ratings for each category:

**Unrestricted Web Access:** No  
**Gambling and Contests:** No  
**Made for Kids:** No  
**Frequent/Intense Mature/Suggestive Themes:** No  
**Frequent/Intense Realistic Violence:** No  
**Frequent/Intense Simulated Gambling:** No  

**Financial Transactions:** Yes (cryptocurrency trading)

**Age Rating Result:** 17+

### Compliance Checklist

- [x] App includes prominent risk warnings
- [x] Terms of Service and Privacy Policy linked
- [x] Age gate (17+) for financial content
- [x] No guaranteed returns promised
- [x] Clear subscription terms and pricing
- [x] Restore purchases functionality
- [x] Cancel subscription instructions
- [x] Customer support contact info
- [x] Demo mode for App Review
- [x] No external payment methods (use IAP only)

### Build & Upload

1. **Archive app in Xcode:**
```bash
# Select "Any iOS Device" as target
# Product → Archive
# Wait for archive to complete
```

2. **Upload to App Store Connect:**
```bash
# In Organizer, select archive
# Click "Distribute App"
# Select "App Store Connect"
# Upload
```

3. **Or use command line:**
```bash
xcodebuild -workspace ios/App/App.xcworkspace \
  -scheme App \
  -configuration Release \
  -archivePath $PWD/build/App.xcarchive \
  clean archive

xcodebuild -exportArchive \
  -archivePath $PWD/build/App.xcarchive \
  -exportPath $PWD/build \
  -exportOptionsPlist exportOptions.plist
```

### Submission Steps

1. Log in to App Store Connect: https://appstoreconnect.apple.com
2. Select "My Apps" → "+ New App"
3. Fill in app information
4. Add screenshots and app preview videos
5. Set pricing and availability
6. Add in-app purchases (subscriptions)
7. Complete age rating questionnaire
8. Add app review information
9. Submit for review

### Expected Review Time

- **Initial Review:** 1-3 business days
- **Rejections:** Common on first submission
- **Resolution:** Usually 24-48 hours for appeals

---

## 🤖 Google Play Store Submission

### Prerequisites
- [ ] Google Play Developer Account ($25 one-time)
- [ ] Android Studio
- [ ] Signed APK or App Bundle
- [ ] Closed/open testing completed (optional)

### App Information

**App Name:** NIJA - AI Crypto Trading Bot

**Short Description (80 characters):**
AI-powered crypto trading bot. Automate your trades across multiple exchanges.

**Full Description (4000 characters max):**
```
[Same description as Apple App Store]
```

### Screenshots Requirements

**Phone:** 2-8 screenshots (minimum 2)
- Resolution: 16:9 or 9:16 aspect ratio
- Minimum dimension: 320px
- Maximum dimension: 3840px

**7-inch Tablet:** 2-8 screenshots (optional)
**10-inch Tablet:** 2-8 screenshots (optional)

### Feature Graphic

- **Size:** 1024w x 500h px
- **Format:** PNG or JPEG
- **Content:** NIJA branding with tagline

### App Icon

- **Size:** 512 x 512 px
- **Format:** PNG (no alpha)

### Categorization

**Application Type:** Application  
**Category:** Finance  
**Tags:** trading, cryptocurrency, automation, AI, investment

### Content Rating

Complete questionnaire at: https://play.google.com/console

**Rating Result:** Teen (13+) or Mature 17+

Questions:
- Does your app contain user-generated content? No
- Does your app facilitate gambling? No
- Does your app contain violence? No
- Does your app allow users to trade financial instruments? Yes

### Privacy Policy

- **URL:** https://nija.app/privacy-policy
- **In-app disclosure:** Yes (shown on first launch)

### Data Safety Section

**Data Collected:**
- Personal Info: Name, Email, User ID
- Financial Info: Purchase history, Transaction history
- App Activity: In-app actions, App interactions

**Data Shared:** None

**Security Practices:**
- Data encrypted in transit
- Data encrypted at rest
- User can request data deletion
- Committed to Google Play Families Policy

### Build & Upload

1. **Generate signed App Bundle:**
```bash
cd android
./gradlew bundleRelease

# Sign the bundle
jarsigner -verbose -sigalg SHA256withRSA \
  -digestalg SHA-256 \
  -keystore nija-release-key.jks \
  app/build/outputs/bundle/release/app-release.aab \
  nija-key-alias
```

2. **Upload to Play Console:**
- Go to: https://play.google.com/console
- Select "Create app"
- Follow wizard to upload AAB file

### In-App Products (Subscriptions)

Create subscription products in Play Console:

**Basic Monthly:**
- Product ID: `basic_monthly`
- Price: $49.00/month
- Free trial: 14 days
- Grace period: 7 days

**Basic Yearly:**
- Product ID: `basic_yearly`
- Price: $470.00/year (save $118)

**Pro Monthly:**
- Product ID: `pro_monthly`
- Price: $99.00/month
- Free trial: 14 days

**Pro Yearly:**
- Product ID: `pro_yearly`
- Price: $950.00/year (save $238)

**Enterprise Monthly:**
- Product ID: `enterprise_monthly`
- Price: $299.00/month

**Enterprise Yearly:**
- Product ID: `enterprise_yearly`
- Price: $2,870.00/year (save $718)

### Release Tracks

1. **Internal Testing:** Small group (< 100 users)
2. **Closed Testing:** Beta testers
3. **Open Testing:** Public beta
4. **Production:** Live release

### Submission Steps

1. Log in to Google Play Console
2. Create new app
3. Fill in store listing
4. Add screenshots and graphics
5. Complete content rating
6. Set pricing and distribution
7. Add in-app products
8. Upload App Bundle
9. Create release
10. Submit for review

### Expected Review Time

- **Initial Review:** 1-7 business days (usually 2-3 days)
- **Updates:** 24-48 hours

---

## 📋 Pre-Submission Testing Checklist

### Functional Testing
- [ ] Login/Registration works
- [ ] Trading start/stop functionality
- [ ] Position tracking displays correctly
- [ ] Push notifications work
- [ ] Subscription purchase flow
- [ ] Education content loads
- [ ] Analytics display correctly
- [ ] App doesn't crash
- [ ] Offline mode handles gracefully

### Compliance Testing
- [ ] Risk disclaimers shown
- [ ] Terms of Service accessible
- [ ] Privacy Policy accessible
- [ ] Age gate (if applicable)
- [ ] Subscription terms clear
- [ ] Cancel subscription works
- [ ] Restore purchases works
- [ ] Customer support accessible

### Security Testing
- [ ] API keys encrypted
- [ ] JWT tokens secure
- [ ] HTTPS only
- [ ] No hardcoded secrets
- [ ] Input validation
- [ ] SQL injection prevention
- [ ] XSS prevention

---

## 🚀 Post-Submission

### Monitoring
- Check review status daily
- Respond to reviewer questions within 24 hours
- Monitor crash reports
- Check user reviews

### Marketing
- Prepare launch announcement
- Update website with app store links
- Create social media posts
- Send email to beta testers
- Update documentation

---

## ⚠️ Common Rejection Reasons

### Apple
1. **Incomplete demo account** - Provide working credentials
2. **Missing risk disclaimers** - Add prominent warnings
3. **External payment methods** - Must use IAP
4. **Crashes during review** - Test thoroughly
5. **Misleading screenshots** - Ensure accuracy

### Google
1. **Privacy policy missing** - Add URL
2. **Content rating incorrect** - Complete questionnaire
3. **Permissions unexplained** - Add usage descriptions
4. **Crashes** - Test on multiple devices
5. **Misleading description** - Be accurate

---

## 📞 Support Contacts

**Apple Developer Support:**
- Phone: 1-800-633-2152
- Email: developer@apple.com
- Forum: developer.apple.com/forums

**Google Play Support:**
- Help Center: support.google.com/googleplay/android-developer
- Contact: play.google.com/console/support

**NIJA Support:**
- Email: support@nija.app
- Discord: discord.gg/nija
- Docs: docs.nija.app
