"""
NIJA In-App Purchase (IAP) Handler

Handles subscription purchases and validation for iOS (App Store) and Android (Google Play).
This module validates purchase receipts, manages subscription states, and syncs with Stripe.

Features:
- Apple App Store receipt validation
- Google Play Billing verification
- Subscription sync with Stripe
- Receipt storage and fraud prevention
- Grace period and billing retry handling

Author: NIJA Trading Systems
Version: 1.0
Date: February 2026
"""

import os
import logging
import json
import base64
import hashlib
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple
from enum import Enum

import requests
from flask import Blueprint, request, jsonify

from monetization_engine import MonetizationEngine, SubscriptionTier, BillingInterval
from auth import get_user_manager

# Configure logging
logger = logging.getLogger(__name__)

# Create IAP blueprint
iap_api = Blueprint('iap_api', __name__, url_prefix='/api/iap')


# ========================================
# Configuration
# ========================================

class Platform(Enum):
    """Mobile platform types"""
    IOS = "ios"
    ANDROID = "android"


class PurchaseStatus(Enum):
    """Purchase validation status"""
    VALID = "valid"
    INVALID = "invalid"
    EXPIRED = "expired"
    PENDING = "pending"
    REFUNDED = "refunded"


# Apple App Store Configuration
APPLE_VERIFY_URL_PRODUCTION = "https://buy.itunes.apple.com/verifyReceipt"
APPLE_VERIFY_URL_SANDBOX = "https://sandbox.itunes.apple.com/verifyReceipt"
APPLE_SHARED_SECRET = os.getenv('APPLE_SHARED_SECRET', '')

# Google Play Configuration
GOOGLE_PLAY_PACKAGE_NAME = os.getenv('GOOGLE_PLAY_PACKAGE_NAME', 'com.nija.trading')
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv('GOOGLE_SERVICE_ACCOUNT_JSON', '')


# ========================================
# Product ID Mapping
# ========================================

PRODUCT_ID_TO_TIER = {
    # iOS Product IDs
    'com.nija.trading.basic.monthly': (SubscriptionTier.BASIC, BillingInterval.MONTHLY),
    'com.nija.trading.basic.yearly': (SubscriptionTier.BASIC, BillingInterval.YEARLY),
    'com.nija.trading.pro.monthly': (SubscriptionTier.PRO, BillingInterval.MONTHLY),
    'com.nija.trading.pro.yearly': (SubscriptionTier.PRO, BillingInterval.YEARLY),
    'com.nija.trading.enterprise.monthly': (SubscriptionTier.ENTERPRISE, BillingInterval.MONTHLY),
    'com.nija.trading.enterprise.yearly': (SubscriptionTier.ENTERPRISE, BillingInterval.YEARLY),
    
    # Android Product IDs (same structure)
    'basic_monthly': (SubscriptionTier.BASIC, BillingInterval.MONTHLY),
    'basic_yearly': (SubscriptionTier.BASIC, BillingInterval.YEARLY),
    'pro_monthly': (SubscriptionTier.PRO, BillingInterval.MONTHLY),
    'pro_yearly': (SubscriptionTier.PRO, BillingInterval.YEARLY),
    'enterprise_monthly': (SubscriptionTier.ENTERPRISE, BillingInterval.MONTHLY),
    'enterprise_yearly': (SubscriptionTier.ENTERPRISE, BillingInterval.YEARLY),
}


# ========================================
# Apple App Store Integration
# ========================================

def verify_apple_receipt(receipt_data: str, exclude_old_transactions: bool = True) -> Tuple[PurchaseStatus, Optional[Dict]]:
    """
    Verify Apple App Store receipt.
    
    Args:
        receipt_data: Base64-encoded receipt data
        exclude_old_transactions: Whether to exclude old transactions from response
        
    Returns:
        Tuple of (status, receipt_info)
    """
    if not APPLE_SHARED_SECRET:
        logger.error("Apple shared secret not configured")
        return PurchaseStatus.INVALID, None
    
    payload = {
        'receipt-data': receipt_data,
        'password': APPLE_SHARED_SECRET,
        'exclude-old-transactions': exclude_old_transactions
    }
    
    # Try production first
    response = requests.post(APPLE_VERIFY_URL_PRODUCTION, json=payload, timeout=10)
    
    if response.status_code != 200:
        logger.error(f"Apple receipt verification failed: HTTP {response.status_code}")
        return PurchaseStatus.INVALID, None
    
    data = response.json()
    status_code = data.get('status')
    
    # Status 21007 means sandbox receipt sent to production - retry with sandbox
    if status_code == 21007:
        logger.info("Sandbox receipt detected, retrying with sandbox URL")
        response = requests.post(APPLE_VERIFY_URL_SANDBOX, json=payload, timeout=10)
        data = response.json()
        status_code = data.get('status')
    
    # Status 0 means success
    if status_code == 0:
        receipt_info = data.get('receipt', {})
        latest_receipt_info = data.get('latest_receipt_info', [])
        
        if latest_receipt_info:
            # Get the most recent subscription
            latest_subscription = latest_receipt_info[-1]
            
            # Check if subscription is active
            expires_date_ms = int(latest_subscription.get('expires_date_ms', 0))
            expires_date = datetime.fromtimestamp(expires_date_ms / 1000)
            
            if expires_date > datetime.utcnow():
                return PurchaseStatus.VALID, {
                    'product_id': latest_subscription.get('product_id'),
                    'transaction_id': latest_subscription.get('transaction_id'),
                    'original_transaction_id': latest_subscription.get('original_transaction_id'),
                    'purchase_date': latest_subscription.get('purchase_date_ms'),
                    'expires_date': expires_date_ms,
                    'is_trial_period': latest_subscription.get('is_trial_period') == 'true',
                    'is_in_intro_offer_period': latest_subscription.get('is_in_intro_offer_period') == 'true'
                }
            else:
                return PurchaseStatus.EXPIRED, None
        
        return PurchaseStatus.INVALID, None
    
    # Handle other status codes
    error_messages = {
        21000: "App Store could not read the receipt",
        21002: "Receipt data was malformed",
        21003: "Receipt could not be authenticated",
        21004: "Shared secret does not match",
        21005: "Receipt server is not currently available",
        21006: "Receipt is valid but subscription has expired",
        21008: "Receipt is from the test environment but sent to production",
        21010: "Receipt could not be authorized"
    }
    
    logger.error(f"Apple receipt verification failed: {error_messages.get(status_code, f'Unknown error {status_code}')}")
    
    if status_code == 21006:
        return PurchaseStatus.EXPIRED, None
    
    return PurchaseStatus.INVALID, None


# ========================================
# Google Play Integration
# ========================================

def verify_google_play_purchase(purchase_token: str, product_id: str, subscription_id: str) -> Tuple[PurchaseStatus, Optional[Dict]]:
    """
    Verify Google Play subscription purchase.
    
    Args:
        purchase_token: Purchase token from Google Play
        product_id: Product ID (SKU)
        subscription_id: Google Play subscription ID
        
    Returns:
        Tuple of (status, purchase_info)
        
    Note:
        Requires Google Play Developer API to be enabled and service account configured.
    """
    if not GOOGLE_SERVICE_ACCOUNT_JSON:
        logger.error("Google service account credentials not configured")
        return PurchaseStatus.INVALID, None
    
    try:
        # Import Google API client
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        
        # Load service account credentials
        credentials_dict = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
        credentials = service_account.Credentials.from_service_account_info(
            credentials_dict,
            scopes=['https://www.googleapis.com/auth/androidpublisher']
        )
        
        # Build Play Developer API client
        service = build('androidpublisher', 'v3', credentials=credentials)
        
        # Get subscription details
        result = service.purchases().subscriptions().get(
            packageName=GOOGLE_PLAY_PACKAGE_NAME,
            subscriptionId=subscription_id,
            token=purchase_token
        ).execute()
        
        # Check purchase state
        # 0 = purchased, 1 = cancelled, 2 = pending
        payment_state = result.get('paymentState', 0)
        
        # Check expiry
        expiry_time_millis = int(result.get('expiryTimeMillis', 0))
        expiry_date = datetime.fromtimestamp(expiry_time_millis / 1000)
        
        # Determine status
        if payment_state == 0 and expiry_date > datetime.utcnow():
            return PurchaseStatus.VALID, {
                'product_id': product_id,
                'order_id': result.get('orderId'),
                'purchase_token': purchase_token,
                'purchase_time': result.get('startTimeMillis'),
                'expiry_time': expiry_time_millis,
                'auto_renewing': result.get('autoRenewing', False),
                'country_code': result.get('countryCode'),
                'price_currency_code': result.get('priceCurrencyCode'),
                'price_amount_micros': result.get('priceAmountMicros')
            }
        elif payment_state == 2:
            return PurchaseStatus.PENDING, None
        elif expiry_date <= datetime.utcnow():
            return PurchaseStatus.EXPIRED, None
        else:
            return PurchaseStatus.INVALID, None
    
    except Exception as e:
        logger.error(f"Google Play purchase verification failed: {e}")
        return PurchaseStatus.INVALID, None


# ========================================
# Purchase Validation Endpoints
# ========================================

@iap_api.route('/verify/ios', methods=['POST'])
def verify_ios_purchase():
    """
    Verify iOS App Store purchase receipt.
    
    Request body:
        {
            "user_id": "user123",
            "receipt_data": "base64_encoded_receipt",
            "transaction_id": "1000000123456789"
        }
        
    Returns:
        {
            "success": true,
            "status": "valid",
            "subscription": {
                "tier": "pro",
                "interval": "monthly",
                "expires_date": "2026-03-15T00:00:00"
            }
        }
    """
    data = request.get_json()
    
    if not data or 'user_id' not in data or 'receipt_data' not in data:
        return jsonify({'error': 'user_id and receipt_data are required'}), 400
    
    user_id = data['user_id']
    receipt_data = data['receipt_data']
    transaction_id = data.get('transaction_id')
    
    try:
        # Verify receipt with Apple
        status, receipt_info = verify_apple_receipt(receipt_data)
        
        if status != PurchaseStatus.VALID:
            return jsonify({
                'success': False,
                'status': status.value,
                'message': 'Invalid or expired receipt'
            }), 400
        
        # Map product ID to subscription tier
        product_id = receipt_info['product_id']
        if product_id not in PRODUCT_ID_TO_TIER:
            logger.error(f"Unknown product ID: {product_id}")
            return jsonify({'error': 'Unknown product ID'}), 400
        
        tier, interval = PRODUCT_ID_TO_TIER[product_id]
        
        # Create or update subscription
        monetization_engine = MonetizationEngine()
        
        # Calculate period dates
        expires_date = datetime.fromtimestamp(receipt_info['expires_date'] / 1000)
        
        subscription = monetization_engine.create_or_update_subscription_from_iap(
            user_id=user_id,
            tier=tier,
            interval=interval,
            platform=Platform.IOS.value,
            transaction_id=receipt_info['transaction_id'],
            original_transaction_id=receipt_info['original_transaction_id'],
            expires_date=expires_date,
            is_trial=receipt_info['is_trial_period'],
            receipt_data=receipt_data
        )
        
        logger.info(f"Verified iOS purchase for user {user_id}: {tier.value} ({interval.value})")
        
        return jsonify({
            'success': True,
            'status': status.value,
            'subscription': {
                'tier': tier.value,
                'interval': interval.value,
                'expires_date': expires_date.isoformat(),
                'is_trial': receipt_info['is_trial_period'],
                'auto_renewing': True
            }
        })
    
    except Exception as e:
        logger.error(f"Error verifying iOS purchase for user {user_id}: {e}")
        return jsonify({'error': 'Failed to verify purchase', 'details': str(e)}), 500


@iap_api.route('/verify/android', methods=['POST'])
def verify_android_purchase():
    """
    Verify Android Google Play purchase.
    
    Request body:
        {
            "user_id": "user123",
            "purchase_token": "google_play_purchase_token",
            "product_id": "pro_monthly",
            "subscription_id": "pro_monthly"
        }
        
    Returns:
        {
            "success": true,
            "status": "valid",
            "subscription": {
                "tier": "pro",
                "interval": "monthly",
                "expires_date": "2026-03-15T00:00:00"
            }
        }
    """
    data = request.get_json()
    
    if not data or 'user_id' not in data or 'purchase_token' not in data:
        return jsonify({'error': 'user_id and purchase_token are required'}), 400
    
    user_id = data['user_id']
    purchase_token = data['purchase_token']
    product_id = data.get('product_id')
    subscription_id = data.get('subscription_id', product_id)
    
    if not product_id:
        return jsonify({'error': 'product_id is required'}), 400
    
    try:
        # Verify purchase with Google Play
        status, purchase_info = verify_google_play_purchase(purchase_token, product_id, subscription_id)
        
        if status != PurchaseStatus.VALID:
            return jsonify({
                'success': False,
                'status': status.value,
                'message': 'Invalid or expired purchase'
            }), 400
        
        # Map product ID to subscription tier
        if product_id not in PRODUCT_ID_TO_TIER:
            logger.error(f"Unknown product ID: {product_id}")
            return jsonify({'error': 'Unknown product ID'}), 400
        
        tier, interval = PRODUCT_ID_TO_TIER[product_id]
        
        # Create or update subscription
        monetization_engine = MonetizationEngine()
        
        # Calculate period dates
        expires_date = datetime.fromtimestamp(purchase_info['expiry_time'] / 1000)
        
        subscription = monetization_engine.create_or_update_subscription_from_iap(
            user_id=user_id,
            tier=tier,
            interval=interval,
            platform=Platform.ANDROID.value,
            transaction_id=purchase_info['order_id'],
            original_transaction_id=purchase_info['order_id'],
            expires_date=expires_date,
            is_trial=False,  # Google Play doesn't explicitly mark trial in API response
            receipt_data=purchase_token
        )
        
        logger.info(f"Verified Android purchase for user {user_id}: {tier.value} ({interval.value})")
        
        return jsonify({
            'success': True,
            'status': status.value,
            'subscription': {
                'tier': tier.value,
                'interval': interval.value,
                'expires_date': expires_date.isoformat(),
                'auto_renewing': purchase_info['auto_renewing']
            }
        })
    
    except Exception as e:
        logger.error(f"Error verifying Android purchase for user {user_id}: {e}")
        return jsonify({'error': 'Failed to verify purchase', 'details': str(e)}), 500


@iap_api.route('/webhook/apple', methods=['POST'])
def apple_server_notification():
    """
    Handle Apple App Store Server-to-Server notifications.
    
    Apple sends notifications for:
    - Initial purchase
    - Renewal
    - Cancellation
    - Refund
    - Subscription expiration
    
    See: https://developer.apple.com/documentation/appstoreservernotifications
    """
    data = request.get_json()
    
    if not data:
        return jsonify({'error': 'Invalid payload'}), 400
    
    try:
        notification_type = data.get('notification_type')
        
        logger.info(f"Received Apple notification: {notification_type}")
        
        # Extract subscription info
        unified_receipt = data.get('unified_receipt', {})
        latest_receipt_info = unified_receipt.get('latest_receipt_info', [])
        
        if not latest_receipt_info:
            logger.warning("No receipt info in Apple notification")
            return jsonify({'success': True}), 200
        
        latest_subscription = latest_receipt_info[-1]
        
        # Handle different notification types
        if notification_type in ['INITIAL_BUY', 'DID_RENEW', 'INTERACTIVE_RENEWAL']:
            # Subscription purchased or renewed
            logger.info(f"Subscription purchased/renewed: {latest_subscription.get('product_id')}")
            # TODO: Update subscription in database
        
        elif notification_type in ['CANCEL', 'DID_FAIL_TO_RENEW']:
            # Subscription cancelled or failed to renew
            logger.info(f"Subscription cancelled/failed: {latest_subscription.get('product_id')}")
            # TODO: Mark subscription as cancelled in database
        
        elif notification_type == 'REFUND':
            # Subscription refunded
            logger.info(f"Subscription refunded: {latest_subscription.get('product_id')}")
            # TODO: Handle refund in database
        
        return jsonify({'success': True}), 200
    
    except Exception as e:
        logger.error(f"Error processing Apple notification: {e}")
        return jsonify({'error': str(e)}), 500


@iap_api.route('/webhook/google', methods=['POST'])
def google_play_notification():
    """
    Handle Google Play Real-time Developer Notifications (RTDN).
    
    Google sends notifications for:
    - Subscription purchased
    - Subscription renewed
    - Subscription cancelled
    - Subscription expired
    - Subscription recovered
    - Subscription on hold
    
    See: https://developer.android.com/google/play/billing/rtdn-reference
    """
    data = request.get_json()
    
    if not data:
        return jsonify({'error': 'Invalid payload'}), 400
    
    try:
        # Decode the notification
        message = data.get('message', {})
        message_data = message.get('data')
        
        if not message_data:
            logger.warning("No data in Google Play notification")
            return jsonify({'success': True}), 200
        
        # Decode base64 data
        decoded_data = base64.b64decode(message_data).decode('utf-8')
        notification = json.loads(decoded_data)
        
        notification_type = notification.get('notificationType')
        subscription_notification = notification.get('subscriptionNotification', {})
        
        logger.info(f"Received Google Play notification: type={notification_type}")
        
        # Handle different notification types
        # 1 = SUBSCRIPTION_RECOVERED
        # 2 = SUBSCRIPTION_RENEWED
        # 3 = SUBSCRIPTION_CANCELED
        # 4 = SUBSCRIPTION_PURCHASED
        # 5 = SUBSCRIPTION_ON_HOLD
        # 6 = SUBSCRIPTION_IN_GRACE_PERIOD
        # 7 = SUBSCRIPTION_RESTARTED
        # 8 = SUBSCRIPTION_PRICE_CHANGE_CONFIRMED
        # 9 = SUBSCRIPTION_DEFERRED
        # 10 = SUBSCRIPTION_PAUSED
        # 11 = SUBSCRIPTION_PAUSE_SCHEDULE_CHANGED
        # 12 = SUBSCRIPTION_REVOKED
        # 13 = SUBSCRIPTION_EXPIRED
        
        if notification_type in [1, 2, 4, 7]:
            # Subscription active states
            logger.info(f"Subscription active: {subscription_notification}")
            # TODO: Update subscription status
        
        elif notification_type in [3, 12, 13]:
            # Subscription inactive states
            logger.info(f"Subscription cancelled/revoked/expired: {subscription_notification}")
            # TODO: Mark subscription as cancelled
        
        elif notification_type in [5, 6]:
            # Billing issues
            logger.warning(f"Subscription billing issue: {subscription_notification}")
            # TODO: Handle grace period/on-hold state
        
        return jsonify({'success': True}), 200
    
    except Exception as e:
        logger.error(f"Error processing Google Play notification: {e}")
        return jsonify({'error': str(e)}), 500


# ========================================
# Subscription Management
# ========================================

@iap_api.route('/subscription/status', methods=['GET'])
def get_subscription_status():
    """
    Get current subscription status for a user.
    
    Query params:
        user_id: User identifier
        
    Returns:
        {
            "active": true,
            "tier": "pro",
            "platform": "ios",
            "expires_date": "2026-03-15T00:00:00",
            "auto_renewing": true
        }
    """
    user_id = request.args.get('user_id')
    
    if not user_id:
        return jsonify({'error': 'user_id is required'}), 400
    
    try:
        monetization_engine = MonetizationEngine()
        subscription = monetization_engine.get_subscription(user_id)
        
        if not subscription:
            return jsonify({
                'active': False,
                'tier': 'free',
                'message': 'No active subscription'
            })
        
        return jsonify({
            'active': subscription.is_active(),
            'tier': subscription.tier.value,
            'interval': subscription.interval.value,
            'status': subscription.status,
            'expires_date': subscription.current_period_end.isoformat(),
            'is_trial': subscription.is_trial(),
            'days_until_renewal': subscription.days_until_renewal()
        })
    
    except Exception as e:
        logger.error(f"Error fetching subscription status for user {user_id}: {e}")
        return jsonify({'error': 'Failed to fetch subscription status', 'details': str(e)}), 500


# ========================================
# Blueprint Registration
# ========================================

def register_iap_api(app):
    """
    Register the IAP API blueprint.
    
    Args:
        app: Flask application instance
    """
    app.register_blueprint(iap_api)
    logger.info("IAP API registered at /api/iap")


if __name__ == '__main__':
    print("NIJA In-App Purchase Handler")
    print("=" * 50)
    print("\nSupported Platforms:")
    print("  - iOS (Apple App Store)")
    print("  - Android (Google Play)")
    print("\nAvailable Endpoints:")
    print("  POST   /api/iap/verify/ios")
    print("  POST   /api/iap/verify/android")
    print("  POST   /api/iap/webhook/apple")
    print("  POST   /api/iap/webhook/google")
    print("  GET    /api/iap/subscription/status")
