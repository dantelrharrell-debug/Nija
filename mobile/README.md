# NIJA Mobile App

Native iOS and Android application for the NIJA AI Trading Platform, built with Capacitor.

## Overview

The NIJA mobile app provides cryptocurrency traders with a powerful, intuitive interface to:
- Monitor automated trading bot activity 24/7
- Manage multiple exchange connections (Coinbase, Kraken, Binance, OKX, Alpaca)
- Track real-time positions and P&L
- Control trading on/off from anywhere
- Receive instant push notifications for trades and alerts

## Features

### Core Features
- ✅ **Real-Time Trading Dashboard** - Monitor positions, P&L, and trading stats
- ✅ **One-Touch Trading Control** - Enable/disable trading with a single tap
- ✅ **Multi-Exchange Support** - Connect and manage multiple exchange accounts
- ✅ **Push Notifications** - Instant alerts for trades, positions, and account activity
- ✅ **Secure Authentication** - JWT tokens + biometric auth (Face ID/Touch ID)
- ✅ **Dark Mode** - Eye-friendly interface optimized for night trading

### Mobile-Optimized
- 📱 Native iOS and Android apps
- 🔒 Secure credential storage using device keychain
- 📶 Offline mode with cached data
- 🔔 Background push notifications
- 👆 Haptic feedback for key actions
- 🎨 Platform-specific UI (iOS/Android design guidelines)

## Technology Stack

- **Framework**: Capacitor 5.7
- **Frontend**: HTML5, CSS3, JavaScript
- **Backend**: Flask REST API
- **Authentication**: JWT with secure token storage
- **Push Notifications**: Firebase Cloud Messaging (Android) + APNs (iOS)
- **Data Storage**: Secure encrypted storage on device

## Quick Start

### Prerequisites

- **Node.js** 18+ and npm
- **For iOS**: macOS with Xcode 14+
- **For Android**: Android Studio with SDK 33+

### Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/dantelrharrell-debug/Nija.git
   cd Nija
   ```

2. **Run the setup script:**
   ```bash
   ./setup-mobile.sh
   ```

   This will:
   - Install npm dependencies
   - Add iOS and Android platforms
   - Sync web assets with native projects

3. **Configure API endpoint:**

   Edit `frontend/static/js/app.js`:
   ```javascript
   const API_BASE_URL = 'https://your-api-url.com/api';
   ```

### Development

#### iOS Development (macOS only)

```bash
# Open in Xcode
npm run cap:open:ios

# In Xcode:
# 1. Select a simulator or device
# 2. Click Run (⌘R)
```

#### Android Development

```bash
# Open in Android Studio
npm run cap:open:android

# In Android Studio:
# 1. Select an emulator or device
# 2. Click Run
```

### Building for Production

See detailed build instructions in [mobile/BUILD_GUIDE.md](mobile/BUILD_GUIDE.md)

**Quick Build Commands:**

```bash
# iOS (generates archive for App Store)
npm run ios:build

# Android APK
cd android && ./gradlew assembleRelease

# Android App Bundle (for Play Store)
cd android && ./gradlew bundleRelease
```

## Project Structure

```
├── capacitor.config.json      # Capacitor configuration
├── package.json               # Node.js dependencies
├── frontend/                  # Web app source
│   ├── static/
│   │   ├── css/              # Stylesheets
│   │   ├── js/               # JavaScript
│   │   │   ├── app.js        # Main app logic
│   │   │   └── capacitor-init.js  # Native features
│   │   └── manifest.json     # PWA manifest
│   └── templates/
│       └── index.html        # Main HTML
├── mobile/                    # Mobile-specific docs
│   ├── ios/                  # iOS configuration
│   ├── android/              # Android configuration
│   ├── assets/               # App icons, splash screens
│   ├── BUILD_GUIDE.md        # Detailed build instructions
│   ├── PRIVACY_POLICY.md     # Privacy policy
│   └── TERMS_OF_SERVICE.md   # Terms of service
├── mobile_api.py             # Mobile-specific API endpoints
├── api_server.py             # Main API server
└── setup-mobile.sh           # Setup script
```

## Configuration

### Capacitor Configuration

Edit `capacitor.config.json`:

```json
{
  "appId": "com.nija.trading",
  "appName": "NIJA",
  "webDir": "frontend",
  "server": {
    "url": "http://localhost:5000",  // For development only
    "cleartext": true                 // For development only
  }
}
```

**⚠️ Important**: Remove `server.url` and `server.cleartext` for production builds.

### Environment Variables

For production deployment, set these environment variables:

```bash
API_BASE_URL=https://your-production-api.com
JWT_SECRET_KEY=your-secure-secret-key
FLASK_ENV=production
```

## API Integration

The mobile app communicates with the NIJA backend API via REST endpoints:

### Authentication
- `POST /api/auth/register` - Register new user
- `POST /api/auth/login` - Login and get JWT token

### User Management
- `GET /api/user/profile` - Get user profile
- `GET /api/user/stats` - Get trading statistics

### Trading Control
- `POST /api/mobile/trading/quick-toggle` - Enable/disable trading
- `GET /api/mobile/dashboard/summary` - Get dashboard data
- `GET /api/mobile/positions/lightweight` - Get active positions
- `GET /api/mobile/trades/recent` - Get recent trades

### Push Notifications
- `POST /api/mobile/device/register` - Register device for push notifications
- `POST /api/mobile/device/unregister` - Unregister device

See [mobile_api.py](mobile_api.py) for complete API documentation.

## Native Features

### Push Notifications

**iOS**: Uses Apple Push Notification service (APNs)
**Android**: Uses Firebase Cloud Messaging (FCM)

Notification types:
- Trade executions
- Position updates
- Account alerts
- Price alerts
- System notifications

### Biometric Authentication

**iOS**: Face ID / Touch ID
**Android**: Fingerprint / Face unlock

Configured via Capacitor plugins automatically.

### Status Bar

Customized for dark theme:
- iOS: Black translucent with white text
- Android: Dark background (#0f172a)

### Splash Screen

Displays on app launch:
- Background: #0f172a (dark blue)
- Logo: Centered NIJA logo
- Auto-hide after 2 seconds

## App Store Submission

### iOS App Store

1. **Apple Developer Account** ($99/year)
2. **App Store Connect** setup
3. **Screenshots** and metadata
4. **Privacy Policy** (required for Finance apps)
5. **App Review** (1-3 days)

See [mobile/ios/README.md](mobile/ios/README.md) for detailed instructions.

### Google Play Store

1. **Google Play Developer Account** ($25 one-time)
2. **Play Console** setup
3. **Screenshots** and metadata
4. **Privacy Policy** (required for Finance apps)
5. **Content Rating** questionnaire
6. **App Review** (1-7 days)

See [mobile/android/README.md](mobile/android/README.md) for detailed instructions.

## Security

### Data Protection
- All API credentials encrypted on device
- JWT tokens stored in secure keychain/keystore
- TLS/SSL for all network communication
- No sensitive data stored in logs

### Authentication
- JWT tokens with expiration
- Biometric authentication support
- Secure token refresh mechanism
- Automatic logout on token expiration

### Compliance
- GDPR compliant (EU users)
- CCPA compliant (California users)
- Finance app guidelines (iOS/Android)
- No third-party data sharing without consent

See [mobile/PRIVACY_POLICY.md](mobile/PRIVACY_POLICY.md) for full privacy policy.

## Testing

### Unit Tests
```bash
# TODO: Add unit tests
npm test
```

### E2E Tests
```bash
# TODO: Add E2E tests
npm run e2e
```

### Manual Testing Checklist

- [ ] Login/Register flow
- [ ] Dashboard displays correctly
- [ ] Trading toggle works
- [ ] Push notifications received
- [ ] Biometric auth works
- [ ] Network offline handling
- [ ] Dark mode displays correctly
- [ ] Navigation between screens
- [ ] API error handling

## Troubleshooting

### Common Issues

**White screen on launch:**
- Check that `webDir` in capacitor.config.json points to correct directory
- Ensure index.html exists in frontend/templates/
- Run `npm run cap:sync` to sync assets

**Push notifications not working:**
- Verify device is registered via `/api/mobile/device/register`
- Check FCM/APNs configuration
- Ensure app has notification permissions
- Check platform-specific push token format

**Build fails:**
- Clear Capacitor cache: `npx cap sync --force`
- Clean native builds: `cd ios && rm -rf Pods/` or `cd android && ./gradlew clean`
- Update Capacitor: `npm run cap:update`

**iOS signing error:**
- Add Apple Developer account in Xcode preferences
- Select correct team in project settings
- Check provisioning profiles

**Android keystore error:**
- Verify keystore file exists
- Check keystore password in key.properties
- Ensure key.properties is not in .gitignore

See [mobile/BUILD_GUIDE.md](mobile/BUILD_GUIDE.md) for more troubleshooting tips.

## Contributing

We welcome contributions! Please follow these guidelines:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## Roadmap

### Version 1.0 (Current)
- ✅ Basic trading dashboard
- ✅ Push notifications
- ✅ Multi-exchange support
- ✅ Biometric authentication

### Version 1.1 (Planned)
- [ ] Advanced charts and technical indicators
- [ ] Price alerts and custom notifications
- [ ] Trade history export (CSV/PDF)
- [ ] Dark/light theme toggle
- [ ] Multiple language support

### Version 2.0 (Future)
- [ ] Advanced analytics dashboard
- [ ] Custom strategy builder
- [ ] Telegram bot integration
- [ ] Multi-strategy portfolio management

## Support

- **Documentation**: [mobile/BUILD_GUIDE.md](mobile/BUILD_GUIDE.md)
- **Issues**: [GitHub Issues](https://github.com/dantelrharrell-debug/Nija/issues)
- **Email**: support@nija.app
- **Discord**: [Join our community](https://discord.gg/nija)

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- Capacitor team for the amazing framework
- NIJA community for feedback and support
- All contributors who helped build this app

---

**Built with ❤️ by the NIJA team**

**Warning**: Cryptocurrency trading involves substantial risk of loss. Only trade with capital you can afford to lose. This app is a tool to automate your trading strategy, not a guarantee of profits.
