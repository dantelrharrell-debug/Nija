#!/bin/bash

# NIJA Mobile App Setup Script
# Permanent application identifier: com.nijaaitrading.app

set -e

echo "======================================"
echo "NIJA Mobile App Setup"
echo "======================================"

if ! command -v node >/dev/null 2>&1; then
    echo "Node.js 18+ is required"
    exit 1
fi
NODE_VERSION=$(node -v | cut -d 'v' -f 2 | cut -d '.' -f 1)
if [ "$NODE_VERSION" -lt 18 ]; then
    echo "Node.js 18+ is required"
    exit 1
fi
if ! command -v npm >/dev/null 2>&1; then
    echo "npm is required"
    exit 1
fi

npm install

if [ ! -d "ios" ]; then
    npm run cap:add:ios
fi
if [ ! -d "android" ]; then
    npm run cap:add:android
fi
npm run cap:sync

API_URL="${API_BASE_URL:-http://localhost:5000}"
if command -v curl >/dev/null 2>&1; then
    if curl -s -o /dev/null -w "%{http_code}" "$API_URL/health" | grep -q "200"; then
        echo "Backend API reachable at $API_URL"
    else
        echo "Warning: backend API not reachable at $API_URL"
    fi
fi

echo ""
echo "Permanent app ID: com.nijaaitrading.app"
echo ""
if [ -d "ios" ]; then
    echo "iOS:"
    echo "  1. Open with: npm run cap:open:ios"
    echo "  2. Confirm Bundle Identifier is com.nijaaitrading.app"
    echo "  3. Select the Apple development team"
    echo "  4. Enable Push Notifications and Associated Domains"
    echo "  5. Add applinks:nijaaitrading.com and applinks:www.nijaaitrading.com"
    echo "  6. Apply mobile/ios/config/NIJA.entitlements.template to the App target"
fi
if [ -d "android" ]; then
    echo "Android:"
    echo "  1. Open with: npm run cap:open:android"
    echo "  2. Confirm applicationId/namespace is com.nijaaitrading.app"
    echo "  3. Apply mobile/android/config/AndroidManifest.xml.template"
    echo "  4. Host /.well-known/assetlinks.json after the Play signing SHA-256 is known"
    echo "  5. Configure Firebase and release signing when credentials are available"
fi

echo ""
echo "Store identity is locked. Do not change com.nijaaitrading.app after registration."
