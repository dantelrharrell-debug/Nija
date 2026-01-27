#!/bin/bash

# NIJA Mobile App Setup Script
# This script helps initialize the Capacitor mobile app

set -e  # Exit on error

echo "======================================"
echo "NIJA Mobile App Setup"
echo "======================================"
echo ""

# Check prerequisites
echo "Checking prerequisites..."

# Check Node.js
if ! command -v node &> /dev/null; then
    echo "❌ Node.js is not installed. Please install Node.js 18+ from https://nodejs.org/"
    exit 1
fi

NODE_VERSION=$(node -v | cut -d 'v' -f 2 | cut -d '.' -f 1)
if [ "$NODE_VERSION" -lt 18 ]; then
    echo "❌ Node.js version is too old. Please upgrade to Node.js 18+"
    exit 1
fi

echo "✅ Node.js $(node -v) found"

# Check npm
if ! command -v npm &> /dev/null; then
    echo "❌ npm is not installed"
    exit 1
fi

echo "✅ npm $(npm -v) found"

# Install npm dependencies
echo ""
echo "Installing npm dependencies..."
npm install

echo "✅ Dependencies installed"

# Initialize Capacitor
echo ""
echo "Initializing Capacitor..."

if [ ! -d "ios" ]; then
    echo "Adding iOS platform..."
    npm run cap:add:ios
    echo "✅ iOS platform added"
else
    echo "✅ iOS platform already exists"
fi

if [ ! -d "android" ]; then
    echo "Adding Android platform..."
    npm run cap:add:android
    echo "✅ Android platform added"
else
    echo "✅ Android platform already exists"
fi

# Sync web assets
echo ""
echo "Syncing web assets with native projects..."
npm run cap:sync
echo "✅ Assets synced"

# Platform-specific instructions
echo ""
echo "======================================"
echo "Platform-Specific Setup"
echo "======================================"
echo ""

# iOS setup
if [ -d "ios" ]; then
    echo "📱 iOS Setup:"
    echo ""
    echo "1. Ensure you have Xcode installed (macOS only)"
    echo "2. Open the iOS project:"
    echo "   npm run cap:open:ios"
    echo ""
    echo "3. In Xcode:"
    echo "   - Select the App target"
    echo "   - Update the Bundle Identifier (com.nija.trading)"
    echo "   - Select your development team for code signing"
    echo "   - Add required capabilities (Push Notifications, Background Modes)"
    echo ""
    echo "4. Update Info.plist with privacy descriptions"
    echo "   (See mobile/ios/README.md for required keys)"
    echo ""
fi

# Android setup
if [ -d "android" ]; then
    echo "🤖 Android Setup:"
    echo ""
    echo "1. Ensure you have Android Studio installed"
    echo "2. Open the Android project:"
    echo "   npm run cap:open:android"
    echo ""
    echo "3. In Android Studio:"
    echo "   - Update applicationId in app/build.gradle (com.nija.trading)"
    echo "   - Generate a release keystore for signing"
    echo "   - Add required permissions in AndroidManifest.xml"
    echo ""
    echo "4. Generate signing keystore:"
    echo "   keytool -genkey -v -keystore android/release.keystore \\"
    echo "     -alias nija-release -keyalg RSA -keysize 2048 -validity 10000"
    echo ""
fi

echo ""
echo "======================================"
echo "Next Steps"
echo "======================================"
echo ""
echo "1. Configure your API endpoint in frontend/static/js/app.js"
echo ""
echo "2. Test on iOS (macOS only):"
echo "   npm run ios:build"
echo ""
echo "3. Test on Android:"
echo "   npm run android:build"
echo ""
echo "4. Read the build guide for detailed instructions:"
echo "   cat mobile/BUILD_GUIDE.md"
echo ""
echo "5. For App Store submission, see:"
echo "   mobile/ios/README.md"
echo "   mobile/android/README.md"
echo ""
echo "======================================"
echo "✅ Setup Complete!"
echo "======================================"
echo ""
echo "For support, visit: https://github.com/dantelrharrell-debug/Nija/issues"
echo ""
