/**
 * Native purchases are intentionally unavailable until a supported Capacitor
 * adapter, store products and server-side verification are certified.
 * Do not grant entitlements based on client-side store responses.
 */
const unavailable = () => {
    throw new Error('Native in-app purchases are not yet available');
};
class IAPService {
    constructor() {
        this.initialized = false;
        this.isNativePlatform = false;
        this.currentSubscription = null;
    }
    async initialize() { return false; }
    getAvailableProducts() { return []; }
    getSubscriptionTiers() { return { free: {
        id: 'free', name: 'Free', description: 'Educational preview',
        monthlyPrice: 0, yearlyPrice: 0, features: ['Educational preview']
    } }; }
    async purchaseSubscription() { unavailable(); }
    async restorePurchases() { unavailable(); }
    async getCurrentSubscription() { return null; }
    async hasActiveSubscription() { return false; }
    getTierFromProductId() { return null; }
    async disconnect() { this.initialized = false; }
}
export const iapService = new IAPService();
if (typeof window !== 'undefined') window.IAPService = iapService;
