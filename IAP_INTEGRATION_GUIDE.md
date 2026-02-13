# NIJA In-App Purchase (IAP) Integration Guide

## Overview

This guide covers the integration of in-app purchases for the NIJA mobile app using Capacitor and native IAP functionality for iOS (StoreKit) and Android (Google Play Billing).

## Architecture

### Components

1. **Frontend Layer** (`frontend/static/js/`)
   - `iap-service.js` - Core IAP service using Capacitor IAP plugin
   - `subscription-ui.js` - Subscription selection and management UI
   - `subscription.css` - Styling for subscription modals

2. **Backend Layer** (`api/`)
   - `subscription_routes.py` - FastAPI routes for IAP verification and webhooks

3. **Integration Points**
   - Capacitor IAP plugin for native store interactions
   - Backend receipt verification
   - Webhook handlers for subscription lifecycle events

## Setup Instructions

### 1. Install Dependencies

```bash
# Install Capacitor IAP plugin
npm install @capacitor-community/in-app-purchases

# Sync with native projects
npm run cap:sync
```

### 2. iOS Setup (App Store Connect)

#### Create In-App Purchase Products

1. Go to [App Store Connect](https://appstoreconnect.apple.com)
2. Select your app
3. Navigate to **Features** → **In-App Purchases**
4. Create new subscription groups and products:

**Basic Monthly** (`com.nija.trading.basic.monthly`)
- Type: Auto-renewable subscription
- Price: $49.00/month
- Subscription group: NIJA Subscriptions
- Duration: 1 month

**Basic Yearly** (`com.nija.trading.basic.yearly`)
- Type: Auto-renewable subscription
- Price: $470.00/year
- Subscription group: NIJA Subscriptions
- Duration: 1 year

**Pro Monthly** (`com.nija.trading.pro.monthly`)
- Type: Auto-renewable subscription
- Price: $149.00/month
- Subscription group: NIJA Subscriptions
- Duration: 1 month

**Pro Yearly** (`com.nija.trading.pro.yearly`)
- Type: Auto-renewable subscription
- Price: $1,430.00/year
- Subscription group: NIJA Subscriptions
- Duration: 1 year

**Enterprise Monthly** (`com.nija.trading.enterprise.monthly`)
- Type: Auto-renewable subscription
- Price: $499.00/month
- Subscription group: NIJA Subscriptions
- Duration: 1 month

**Enterprise Yearly** (`com.nija.trading.enterprise.yearly`)
- Type: Auto-renewable subscription
- Price: $4,790.00/year
- Subscription group: NIJA Subscriptions
- Duration: 1 year

#### Configure Free Trial

For each subscription product:
1. Set **Free Trial Duration** to 14 days
2. Enable **Introductory Offer**
3. Set offer type to Free Trial

#### Set Up Server Notifications

1. In App Store Connect, go to **App Information**
2. Scroll to **App Store Server Notifications**
3. Enter webhook URL: `https://your-api-domain.com/api/subscriptions/webhooks/apple`
4. Generate and save the shared secret

### 3. Android Setup (Google Play Console)

#### Create Subscription Products

1. Go to [Google Play Console](https://play.google.com/console)
2. Select your app
3. Navigate to **Monetize** → **Products** → **Subscriptions**
4. Create new subscription products:

**Basic Monthly** (`com.nija.trading.basic.monthly`)
- Price: $49.00
- Billing period: Monthly
- Free trial: 14 days

**Basic Yearly** (`com.nija.trading.basic.yearly`)
- Price: $470.00
- Billing period: Yearly
- Free trial: 14 days

**Pro Monthly** (`com.nija.trading.pro.monthly`)
- Price: $149.00
- Billing period: Monthly
- Free trial: 14 days

**Pro Yearly** (`com.nija.trading.pro.yearly`)
- Price: $1,430.00
- Billing period: Yearly
- Free trial: 14 days

**Enterprise Monthly** (`com.nija.trading.enterprise.monthly`)
- Price: $499.00
- Billing period: Monthly
- Free trial: 14 days

**Enterprise Yearly** (`com.nija.trading.enterprise.yearly`)
- Price: $4,790.00
- Billing period: Yearly
- Free trial: 14 days

#### Set Up Real-time Developer Notifications

1. Create a Google Cloud Pub/Sub topic
2. Grant publish permissions to Google Play
3. In Google Play Console, go to **Monetization setup**
4. Enter topic name: `projects/your-project/topics/iap-notifications`
5. Set up subscription to forward to webhook:
   - Push endpoint: `https://your-api-domain.com/api/subscriptions/webhooks/google`

### 4. Frontend Integration

Add the subscription UI to your app:

```html
<!-- In index.html, add CSS -->
<link rel="stylesheet" href="../static/css/subscription.css">

<!-- Add JavaScript -->
<script src="../static/js/iap-service.js"></script>
<script src="../static/js/subscription-ui.js"></script>

<!-- Initialize on app load -->
<script>
document.addEventListener('DOMContentLoaded', async () => {
    // Initialize IAP service
    if (window.IAPService) {
        await window.IAPService.initialize();
    }
});
</script>

<!-- Add subscription button -->
<button onclick="showSubscriptionModal('free')">Upgrade Plan</button>
```

### 5. Backend Integration

Mount the subscription routes in your FastAPI app:

```python
# In your main FastAPI app (e.g., api_server.py or fastapi_backend.py)
from api.subscription_routes import router as subscription_router

app = FastAPI()
app.include_router(subscription_router)
```

## Testing

### iOS Testing (Sandbox)

1. **Create Sandbox Tester Account**
   - Go to App Store Connect → Users and Access → Sandbox Testers
   - Create test account with unique email

2. **Configure Device for Sandbox**
   - On iOS device, go to Settings → App Store → Sandbox Account
   - Sign in with sandbox tester account

3. **Test Purchase Flow**
   ```javascript
   // In browser console or app
   await window.IAPService.initialize();
   await window.IAPService.purchaseSubscription('com.nija.trading.pro.monthly');
   ```

4. **Verify Purchase**
   - Check that purchase completes
   - Verify subscription shows in app
   - Verify backend receives webhook

### Android Testing

1. **Add License Testers**
   - Go to Google Play Console → Setup → License testing
   - Add test email addresses

2. **Create Internal Test Track**
   - Upload app to Internal Testing track
   - Add testers to track

3. **Test Purchase Flow**
   - Install app from Internal Testing
   - Purchases will be free for testers
   - Verify subscription flow works

## Subscription Flow

### Purchase Flow

1. **User initiates purchase**
   ```javascript
   showSubscriptionModal('free'); // Current tier
   ```

2. **User selects plan and interval**
   - Monthly or Yearly
   - Basic, Pro, or Enterprise

3. **IAP service processes purchase**
   ```javascript
   await window.IAPService.purchaseSubscription(productId);
   ```

4. **Native store handles transaction**
   - iOS: StoreKit
   - Android: Google Play Billing

5. **Backend verifies receipt**
   ```
   POST /api/subscriptions/verify
   {
     "productId": "com.nija.trading.pro.monthly",
     "transactionId": "1000000...",
     "receipt": "base64...",
     "platform": "ios"
   }
   ```

6. **Subscription activated**
   - User tier updated in database
   - Features unlocked in app
   - Success notification shown

### Renewal Flow

1. **Store auto-renews subscription**
   - Happens automatically at billing date
   - No user interaction needed

2. **Webhook notification sent**
   ```
   POST /api/subscriptions/webhooks/apple
   {
     "notification_type": "DID_RENEW",
     ...
   }
   ```

3. **Backend updates subscription**
   - Extend subscription period
   - Update payment status
   - Log renewal event

### Cancellation Flow

1. **User cancels through App Store/Play Store**
   - Settings → Subscriptions → Cancel
   - OR in-app manage subscription link

2. **Webhook notification sent**
   ```
   POST /api/subscriptions/webhooks/apple
   {
     "notification_type": "CANCEL",
     ...
   }
   ```

3. **Backend marks subscription for end-of-period**
   - Subscription remains active until period end
   - No new charges
   - User retains access until expiration

## App Store Submission Requirements

### Screenshots Required

Create screenshots showing:

1. **Subscription selection screen**
   - All three tiers visible
   - Pricing clearly displayed
   - Features comparison

2. **Active subscription status**
   - User dashboard showing "Pro" tier
   - Subscription benefits visible

3. **Upgrade flow**
   - Step-by-step upgrade process
   - Payment confirmation

### Metadata Requirements

#### App Description

Must include:
- "In-app purchases available"
- Clear explanation of subscription tiers
- What each tier includes
- Pricing (managed by App Store)

#### Privacy Policy

Update privacy policy to include:
- Subscription data collection
- Payment processing (handled by Apple/Google)
- Subscription management

#### Support URL

Provide URL with:
- How to manage subscriptions
- How to cancel
- Refund policy
- Contact information

### Review Guidelines

**For iOS:**
- Subscriptions managed through App Store only
- No external payment links
- Clear value proposition for each tier
- Accurate feature descriptions

**For Android:**
- Subscriptions managed through Google Play only
- No external payment links
- Data safety section complete
- In-app purchases declared

## Troubleshooting

### Common Issues

**"Product not found" error**
- Verify product IDs match exactly in code and store
- Ensure products are approved in App Store Connect/Play Console
- Check that subscription group is configured

**Purchase fails silently**
- Check sandbox/test account is signed in
- Verify IAP service initialized
- Check console for errors

**Webhook not received**
- Verify webhook URL is publicly accessible
- Check firewall/security settings
- Test webhook with curl

**Receipt verification fails**
- Check using correct verification URL (sandbox vs production)
- Verify receipt data is base64 encoded
- Check shared secret is correct

### Debug Mode

Enable debug logging:

```javascript
// In iap-service.js
localStorage.setItem('iap_debug', 'true');

// Then check console for detailed logs
```

## Security Considerations

1. **Always verify receipts server-side**
   - Never trust client-only validation
   - Use Apple/Google verification APIs

2. **Protect webhook endpoints**
   - Verify signatures from Apple/Google
   - Use HTTPS only
   - Rate limit webhook endpoints

3. **Store receipts securely**
   - Encrypt in database
   - Keep audit trail
   - Comply with data retention policies

4. **Handle subscription status carefully**
   - Check subscription is active before granting access
   - Handle edge cases (expired, refunded, etc.)
   - Implement grace periods properly

## Next Steps

1. ✅ Complete IAP plugin integration
2. ✅ Create subscription UI
3. ✅ Implement backend verification
4. ⏳ Configure App Store Connect products
5. ⏳ Configure Google Play Console products
6. ⏳ Set up webhook endpoints
7. ⏳ Test sandbox purchases
8. ⏳ Generate screenshots
9. ⏳ Update privacy policy
10. ⏳ Submit for review

## Support

For issues or questions:
- Email: support@nija.app
- Documentation: https://docs.nija.app
- Community: Discord

---

**Version:** 1.0  
**Last Updated:** February 13, 2026  
**Author:** NIJA Development Team
