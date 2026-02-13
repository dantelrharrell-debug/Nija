/**
 * NIJA Subscription UI
 * Handles subscription selection and upgrade/downgrade flows
 */

/**
 * Show subscription selection modal
 */
function showSubscriptionModal(currentTier = 'free') {
    const modal = createSubscriptionModal(currentTier);
    document.body.appendChild(modal);
    modal.classList.add('active');
}

/**
 * Create subscription modal
 */
function createSubscriptionModal(currentTier) {
    const modal = document.createElement('div');
    modal.className = 'subscription-modal';
    modal.id = 'subscription-modal';

    const tiers = window.IAPService ? window.IAPService.getSubscriptionTiers() : getDefaultTiers();

    modal.innerHTML = `
        <div class="subscription-modal-overlay" onclick="closeSubscriptionModal()"></div>
        <div class="subscription-modal-content">
            <div class="subscription-modal-header">
                <h2>Choose Your Plan</h2>
                <button class="close-btn" onclick="closeSubscriptionModal()">×</button>
            </div>

            <div class="subscription-interval-toggle">
                <button class="interval-btn active" data-interval="monthly" onclick="toggleInterval('monthly')">
                    Monthly
                </button>
                <button class="interval-btn" data-interval="yearly" onclick="toggleInterval('yearly')">
                    Yearly <span class="save-badge">Save 20%</span>
                </button>
            </div>

            <div class="subscription-tiers">
                ${renderSubscriptionTier('free', tiers.free, currentTier)}
                ${renderSubscriptionTier('basic', tiers.basic, currentTier)}
                ${renderSubscriptionTier('pro', tiers.pro, currentTier)}
                ${renderSubscriptionTier('enterprise', tiers.enterprise, currentTier)}
            </div>

            <div class="subscription-disclaimer">
                <p>💡 All subscriptions include 14-day free trial</p>
                <p>🔒 Cancel anytime. Managed through App Store/Play Store.</p>
            </div>
        </div>
    `;

    return modal;
}

/**
 * Render individual subscription tier
 */
function renderSubscriptionTier(tierId, tier, currentTier) {
    const isCurrent = tierId === currentTier;
    const isUpgrade = getTierLevel(tierId) > getTierLevel(currentTier);
    const isDowngrade = getTierLevel(tierId) < getTierLevel(currentTier);

    return `
        <div class="subscription-tier ${tier.popular ? 'popular' : ''} ${isCurrent ? 'current' : ''}" 
             data-tier="${tierId}">
            ${tier.popular ? '<div class="popular-badge">Most Popular</div>' : ''}
            ${isCurrent ? '<div class="current-badge">Current Plan</div>' : ''}
            
            <div class="tier-header">
                <h3>${tier.name}</h3>
                <p class="tier-description">${tier.description}</p>
            </div>

            <div class="tier-pricing">
                <div class="price-container">
                    <div class="price monthly-price active">
                        <span class="currency">$</span>
                        <span class="amount">${tier.monthlyPrice}</span>
                        <span class="period">/month</span>
                    </div>
                    <div class="price yearly-price">
                        <span class="currency">$</span>
                        <span class="amount">${Math.round(tier.yearlyPrice / 12)}</span>
                        <span class="period">/month</span>
                        <div class="yearly-total">($${tier.yearlyPrice}/year)</div>
                    </div>
                </div>
            </div>

            <div class="tier-features">
                ${tier.features.map(feature => `
                    <div class="feature-item">
                        <span class="checkmark">✓</span>
                        <span>${feature}</span>
                    </div>
                `).join('')}
            </div>

            <div class="tier-action">
                ${renderTierButton(tierId, isCurrent, isUpgrade, isDowngrade)}
            </div>
        </div>
    `;
}

/**
 * Render subscription button based on tier status
 */
function renderTierButton(tierId, isCurrent, isUpgrade, isDowngrade) {
    if (tierId === 'free') {
        if (isCurrent) {
            return '<button class="tier-btn current" disabled>Current Plan</button>';
        } else {
            return '<button class="tier-btn downgrade" onclick="handleDowngrade(\'free\')">Downgrade</button>';
        }
    }

    if (isCurrent) {
        return '<button class="tier-btn current" disabled>Current Plan</button>';
    }

    if (isUpgrade) {
        return `<button class="tier-btn upgrade" onclick="handleSubscribe('${tierId}')">Upgrade Now</button>`;
    }

    if (isDowngrade) {
        return `<button class="tier-btn downgrade" onclick="handleDowngrade('${tierId}')">Downgrade</button>`;
    }

    return `<button class="tier-btn subscribe" onclick="handleSubscribe('${tierId}')">Subscribe</button>`;
}

/**
 * Toggle between monthly and yearly pricing
 */
function toggleInterval(interval) {
    // Update button states
    document.querySelectorAll('.interval-btn').forEach(btn => {
        btn.classList.remove('active');
        if (btn.dataset.interval === interval) {
            btn.classList.add('active');
        }
    });

    // Update pricing display
    document.querySelectorAll('.price').forEach(price => {
        price.classList.remove('active');
    });

    const selector = interval === 'monthly' ? '.monthly-price' : '.yearly-price';
    document.querySelectorAll(selector).forEach(price => {
        price.classList.add('active');
    });
}

/**
 * Handle subscription purchase
 */
async function handleSubscribe(tierId) {
    try {
        // Show loading
        showLoadingOverlay('Processing subscription...');

        // Get current interval
        const interval = document.querySelector('.interval-btn.active').dataset.interval;

        // Get product ID
        const productId = getProductId(tierId, interval);

        if (!window.IAPService || !window.IAPService.isNativePlatform) {
            // Redirect to web checkout for non-native platforms
            await handleWebCheckout(tierId, interval);
            return;
        }

        // Initialize IAP if needed
        if (!window.IAPService.initialized) {
            await window.IAPService.initialize();
        }

        // Purchase subscription
        await window.IAPService.purchaseSubscription(productId);

        // Success handled by IAP service listener
        hideLoadingOverlay();
        closeSubscriptionModal();
        showSuccessMessage('Subscription activated! 🎉');

    } catch (error) {
        console.error('Subscription error:', error);
        hideLoadingOverlay();
        showErrorMessage('Subscription failed. Please try again.');
    }
}

/**
 * Handle downgrade
 */
async function handleDowngrade(tierId) {
    const confirmed = await showConfirmDialog(
        'Downgrade Subscription',
        `Are you sure you want to downgrade to ${tierId === 'free' ? 'Free' : tierId.charAt(0).toUpperCase() + tierId.slice(1)}? This will take effect at the end of your current billing period.`
    );

    if (confirmed) {
        try {
            showLoadingOverlay('Processing downgrade...');

            // Call backend to schedule downgrade
            const response = await fetch('/api/subscriptions/downgrade', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${localStorage.getItem('nija_token')}`
                },
                body: JSON.stringify({ tier: tierId })
            });

            if (!response.ok) {
                throw new Error('Downgrade failed');
            }

            hideLoadingOverlay();
            closeSubscriptionModal();
            showSuccessMessage('Downgrade scheduled for end of billing period');
        } catch (error) {
            console.error('Downgrade error:', error);
            hideLoadingOverlay();
            showErrorMessage('Downgrade failed. Please try again.');
        }
    }
}

/**
 * Handle web checkout (for non-native platforms)
 */
async function handleWebCheckout(tierId, interval) {
    try {
        const response = await fetch('/api/subscriptions/create-checkout', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${localStorage.getItem('nija_token')}`
            },
            body: JSON.stringify({ 
                tier: tierId,
                interval: interval
            })
        });

        if (!response.ok) {
            throw new Error('Checkout creation failed');
        }

        const data = await response.json();
        
        // Redirect to checkout URL (Stripe)
        window.location.href = data.checkout_url;
    } catch (error) {
        console.error('Web checkout error:', error);
        throw error;
    }
}

/**
 * Get product ID for tier and interval
 */
function getProductId(tierId, interval) {
    const tiers = window.IAPService.getSubscriptionTiers();
    const tier = tiers[tierId];
    
    if (!tier) {
        throw new Error(`Invalid tier: ${tierId}`);
    }

    return interval === 'monthly' ? tier.monthlyProductId : tier.yearlyProductId;
}

/**
 * Get tier level (for comparison)
 */
function getTierLevel(tierId) {
    const levels = {
        'free': 0,
        'basic': 1,
        'pro': 2,
        'enterprise': 3
    };
    return levels[tierId] || 0;
}

/**
 * Close subscription modal
 */
function closeSubscriptionModal() {
    const modal = document.getElementById('subscription-modal');
    if (modal) {
        modal.classList.remove('active');
        setTimeout(() => modal.remove(), 300);
    }
}

/**
 * Get default tiers (fallback if IAP service not available)
 */
function getDefaultTiers() {
    return {
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
            popular: true,
            features: [
                'All Basic features',
                'Meta-AI optimization',
                'MMIN intelligence',
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
            features: [
                'All Pro features',
                'GMIG macro intelligence',
                'Unlimited connections',
                'Dedicated manager',
                'Custom strategies',
                'Full API access'
            ]
        }
    };
}

/**
 * Show loading overlay
 */
function showLoadingOverlay(message) {
    let overlay = document.getElementById('loading-overlay');
    if (!overlay) {
        overlay = document.createElement('div');
        overlay.id = 'loading-overlay';
        overlay.className = 'loading-overlay';
        document.body.appendChild(overlay);
    }
    overlay.innerHTML = `
        <div class="loading-spinner"></div>
        <p>${message}</p>
    `;
    overlay.classList.add('active');
}

/**
 * Hide loading overlay
 */
function hideLoadingOverlay() {
    const overlay = document.getElementById('loading-overlay');
    if (overlay) {
        overlay.classList.remove('active');
        setTimeout(() => overlay.remove(), 300);
    }
}

/**
 * Show success message
 */
function showSuccessMessage(message) {
    showToast(message, 'success');
}

/**
 * Show error message
 */
function showErrorMessage(message) {
    showToast(message, 'error');
}

/**
 * Show toast notification
 */
function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    document.body.appendChild(toast);

    setTimeout(() => toast.classList.add('active'), 100);
    setTimeout(() => {
        toast.classList.remove('active');
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

/**
 * Show confirm dialog
 */
function showConfirmDialog(title, message) {
    return new Promise((resolve) => {
        const dialog = document.createElement('div');
        dialog.className = 'confirm-dialog';
        dialog.innerHTML = `
            <div class="confirm-overlay"></div>
            <div class="confirm-content">
                <h3>${title}</h3>
                <p>${message}</p>
                <div class="confirm-actions">
                    <button class="btn-cancel" onclick="this.closest('.confirm-dialog').remove(); window._confirmResolve(false)">
                        Cancel
                    </button>
                    <button class="btn-confirm" onclick="this.closest('.confirm-dialog').remove(); window._confirmResolve(true)">
                        Confirm
                    </button>
                </div>
            </div>
        `;
        document.body.appendChild(dialog);
        
        window._confirmResolve = resolve;
    });
}

// Listen for IAP purchase events
window.addEventListener('iap:purchase:success', (event) => {
    console.log('Purchase successful:', event.detail);
    showSuccessMessage('Subscription activated successfully! 🎉');
    
    // Refresh user profile to get updated tier
    if (typeof loadUserProfile === 'function') {
        loadUserProfile();
    }
});

window.addEventListener('iap:purchase:failure', (event) => {
    console.error('Purchase failed:', event.detail);
    showErrorMessage('Purchase failed. Please try again.');
});
