/**
 * NIJA In-App Purchase Service
 * Handles subscription purchases for iOS and Android
 */

import { Capacitor } from '@capacitor/core';
import { InAppPurchase } from '@capacitor-community/in-app-purchases';

// Subscription product IDs (must match App Store Connect and Play Console)
const PRODUCT_IDS = {
    BASIC_MONTHLY: 'com.nija.trading.basic.monthly',
    BASIC_YEARLY: 'com.nija.trading.basic.yearly',
    PRO_MONTHLY: 'com.nija.trading.pro.monthly',
    PRO_YEARLY: 'com.nija.trading.pro.yearly',
    ENTERPRISE_MONTHLY: 'com.nija.trading.enterprise.monthly',
    ENTERPRISE_YEARLY: 'com.nija.trading.enterprise.yearly'
};

// Subscription tier information
const SUBSCRIPTION_TIERS = {
    free: {
        id: 'free',
        name: 'Free',
        description: 'Paper trading only',
        monthlyPrice: 0,
        yearlyPrice: 0,
        features: [
            'Paper trading only',
            'APEX V7.2 strategy',
            '1 exchange connection',
            'Community support',
            'Basic analytics'
        ]
    },
    basic: {
        id: 'basic',
        name: 'Basic',
        description: 'Live trading basics',
        monthlyPrice: 49,
        yearlyPrice: 470,
        monthlyProductId: PRODUCT_IDS.BASIC_MONTHLY,
        yearlyProductId: PRODUCT_IDS.BASIC_YEARLY,
        features: [
            'Live trading',
            'APEX V7.2 strategy',
            '2 exchange connections',
            'Email support (48h)',
            'Standard analytics'
        ]
    },
    pro: {
        id: 'pro',
        name: 'Pro',
        description: 'Advanced AI features',
        monthlyPrice: 149,
        yearlyPrice: 1430,
        monthlyProductId: PRODUCT_IDS.PRO_MONTHLY,
        yearlyProductId: PRODUCT_IDS.PRO_YEARLY,
        popular: true,
        features: [
            'All Basic features',
            'Meta-AI optimization',
            'MMIN multi-market intelligence',
            '5 exchange connections',
            'Priority support (24h)',
            'Advanced analytics'
        ]
    },
    enterprise: {
        id: 'enterprise',
        name: 'Enterprise',
        description: 'Full feature set',
        monthlyPrice: 499,
        yearlyPrice: 4790,
        monthlyProductId: PRODUCT_IDS.ENTERPRISE_MONTHLY,
        yearlyProductId: PRODUCT_IDS.ENTERPRISE_YEARLY,
        features: [
            'All Pro features',
            'GMIG global macro intelligence',
            'Unlimited connections',
            'Dedicated account manager',
            'Custom strategy tuning',
            'Full API access'
        ]
    }
};

class IAPService {
    constructor() {
        this.initialized = false;
        this.products = [];
        this.currentSubscription = null;
        this.isNativePlatform = Capacitor.isNativePlatform();
    }

    /**
     * Initialize the IAP service
     */
    async initialize() {
        if (!this.isNativePlatform) {
            console.log('Not a native platform, IAP unavailable');
            return false;
        }

        try {
            // Connect to the store
            await InAppPurchase.connectToStore();
            console.log('✅ Connected to app store');

            // Register products
            const productIds = Object.values(PRODUCT_IDS);
            await InAppPurchase.registerProducts({ productIdentifiers: productIds });
            console.log('✅ Registered products:', productIds);

            // Get product information
            const result = await InAppPurchase.getProducts({ productIdentifiers: productIds });
            this.products = result.products;
            console.log('✅ Loaded products:', this.products);

            // Set up purchase listener
            this.setupPurchaseListener();

            // Check for existing subscriptions
            await this.restorePurchases();

            this.initialized = true;
            return true;
        } catch (error) {
            console.error('❌ IAP initialization failed:', error);
            return false;
        }
    }

    /**
     * Set up listener for purchase updates
     */
    setupPurchaseListener() {
        InAppPurchase.addListener('purchaseUpdated', async (purchase) => {
            console.log('Purchase updated:', purchase);

            if (purchase.state === 'PURCHASED') {
                await this.handlePurchaseSuccess(purchase);
            } else if (purchase.state === 'FAILED') {
                await this.handlePurchaseFailure(purchase);
            }
        });

        InAppPurchase.addListener('purchaseRestored', async (purchase) => {
            console.log('Purchase restored:', purchase);
            await this.handlePurchaseSuccess(purchase);
        });
    }

    /**
     * Get available subscription products
     */
    getAvailableProducts() {
        if (!this.initialized) {
            return [];
        }
        return this.products;
    }

    /**
     * Get subscription tier information
     */
    getSubscriptionTiers() {
        return SUBSCRIPTION_TIERS;
    }

    /**
     * Purchase a subscription
     * @param {string} productId - Product identifier
     */
    async purchaseSubscription(productId) {
        if (!this.initialized) {
            throw new Error('IAP service not initialized');
        }

        try {
            console.log('Initiating purchase for:', productId);
            
            const result = await InAppPurchase.purchase({ productIdentifier: productId });
            console.log('Purchase initiated:', result);
            
            return result;
        } catch (error) {
            console.error('Purchase failed:', error);
            throw error;
        }
    }

    /**
     * Handle successful purchase
     */
    async handlePurchaseSuccess(purchase) {
        try {
            console.log('Processing successful purchase:', purchase);

            // Verify purchase with backend
            const verified = await this.verifyPurchaseWithBackend(purchase);

            if (verified) {
                // Finish the transaction
                await InAppPurchase.finishTransaction({ 
                    productIdentifier: purchase.productIdentifier,
                    transactionIdentifier: purchase.transactionIdentifier 
                });

                // Update current subscription
                this.currentSubscription = purchase;

                // Notify UI
                this.notifyPurchaseSuccess(purchase);

                console.log('✅ Purchase completed successfully');
            } else {
                console.error('❌ Purchase verification failed');
                throw new Error('Purchase verification failed');
            }
        } catch (error) {
            console.error('Error handling purchase success:', error);
            throw error;
        }
    }

    /**
     * Handle failed purchase
     */
    async handlePurchaseFailure(purchase) {
        console.error('Purchase failed:', purchase);
        this.notifyPurchaseFailure(purchase);
    }

    /**
     * Verify purchase with backend server
     */
    async verifyPurchaseWithBackend(purchase) {
        try {
            const response = await fetch('/api/subscriptions/verify', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${localStorage.getItem('nija_token')}`
                },
                body: JSON.stringify({
                    productId: purchase.productIdentifier,
                    transactionId: purchase.transactionIdentifier,
                    receipt: purchase.receipt,
                    platform: Capacitor.getPlatform()
                })
            });

            if (!response.ok) {
                throw new Error('Verification failed');
            }

            const data = await response.json();
            return data.verified === true;
        } catch (error) {
            console.error('Backend verification error:', error);
            return false;
        }
    }

    /**
     * Restore previous purchases
     */
    async restorePurchases() {
        if (!this.initialized) {
            throw new Error('IAP service not initialized');
        }

        try {
            console.log('Restoring purchases...');
            await InAppPurchase.restorePurchases();
            console.log('✅ Purchases restored');
        } catch (error) {
            console.error('Error restoring purchases:', error);
            throw error;
        }
    }

    /**
     * Get current active subscription
     */
    async getCurrentSubscription() {
        if (!this.initialized) {
            return null;
        }

        try {
            const result = await InAppPurchase.getAvailablePurchases();
            const activePurchases = result.purchases.filter(p => p.state === 'PURCHASED');
            
            if (activePurchases.length > 0) {
                this.currentSubscription = activePurchases[0];
                return activePurchases[0];
            }
            
            return null;
        } catch (error) {
            console.error('Error getting current subscription:', error);
            return null;
        }
    }

    /**
     * Check if user has active subscription
     */
    async hasActiveSubscription() {
        const subscription = await this.getCurrentSubscription();
        return subscription !== null;
    }

    /**
     * Get subscription tier from product ID
     */
    getTierFromProductId(productId) {
        for (const [tierId, tier] of Object.entries(SUBSCRIPTION_TIERS)) {
            if (tier.monthlyProductId === productId || tier.yearlyProductId === productId) {
                return tier;
            }
        }
        return null;
    }

    /**
     * Notify UI of successful purchase
     */
    notifyPurchaseSuccess(purchase) {
        const event = new CustomEvent('iap:purchase:success', { 
            detail: purchase 
        });
        window.dispatchEvent(event);
    }

    /**
     * Notify UI of failed purchase
     */
    notifyPurchaseFailure(purchase) {
        const event = new CustomEvent('iap:purchase:failure', { 
            detail: purchase 
        });
        window.dispatchEvent(event);
    }

    /**
     * Disconnect from store (cleanup)
     */
    async disconnect() {
        if (this.initialized) {
            await InAppPurchase.disconnectFromStore();
            this.initialized = false;
            console.log('Disconnected from store');
        }
    }
}

// Export singleton instance
export const iapService = new IAPService();

// Export for non-module usage
if (typeof window !== 'undefined') {
    window.IAPService = iapService;
}
