/**
 * NIJA Risk Disclaimers & Safety Notices
 * 
 * CRITICAL: These disclaimers MUST be shown to users before any trading functionality.
 * Required for App Store compliance (Apple §2.5.6, Google Financial Services Policy)
 * 
 * Include this file in index.html: <script src="/static/js/risk-disclaimers.js"></script>
 */

// ========================================
// Risk Disclaimer Content
// ========================================

const RISK_DISCLAIMERS = {
    // Main risk warning - shown on first launch
    MAIN_WARNING: `
        <div class="risk-disclaimer-container">
            <div class="risk-header">
                <span class="warning-icon">⚠️</span>
                <h2>IMPORTANT RISK DISCLOSURE</h2>
            </div>
            
            <div class="risk-content">
                <div class="risk-section">
                    <h3>⚠️ YOU CAN LOSE MONEY</h3>
                    <ul>
                        <li>Cryptocurrency markets are <strong>highly volatile</strong></li>
                        <li>Past performance does <strong>NOT</strong> indicate future results</li>
                        <li>You can lose <strong>some or ALL</strong> of your invested capital</li>
                        <li><strong>Only trade with money you can afford to lose</strong></li>
                    </ul>
                </div>
                
                <div class="risk-section">
                    <h3>🤖 ABOUT THIS SOFTWARE</h3>
                    <ul>
                        <li>NIJA is an independent trading tool - <strong>NOT investment advice</strong></li>
                        <li>You make all decisions about when and what to trade</li>
                        <li>This software executes trades based on <strong>YOUR configuration</strong></li>
                        <li><strong>NO GUARANTEES</strong> of profit or performance are made</li>
                    </ul>
                </div>
                
                <div class="risk-section">
                    <h3>📊 INDEPENDENT TRADING MODEL</h3>
                    <ul>
                        <li>Each account trades <strong>independently</strong> using algorithmic signals</li>
                        <li>No copy trading or signal distribution to other users</li>
                        <li>Each user controls their own trading strategy and risk</li>
                        <li>Your results are based on <strong>YOUR account's performance</strong></li>
                    </ul>
                </div>
                
                <div class="risk-section">
                    <h3>🛡️ YOUR RESPONSIBILITY</h3>
                    <ul>
                        <li>You are <strong>solely responsible</strong> for your trading decisions</li>
                        <li>You control when trading is enabled or disabled</li>
                        <li>You set your own risk parameters and position sizes</li>
                        <li><strong>Consult a licensed financial advisor</strong> before trading</li>
                    </ul>
                </div>
                
                <div class="risk-footer">
                    <p><strong>By continuing, you acknowledge that you understand and accept these risks.</strong></p>
                    <p>NIJA and its developers are not liable for any trading losses.</p>
                </div>
            </div>
        </div>
    `,
    
    // Short disclaimer for in-app display
    SHORT_WARNING: `
        ⚠️ RISK WARNING: Cryptocurrency trading involves substantial risk of loss. 
        Past performance does not indicate future results. 
        Only trade with money you can afford to lose.
    `,
    
    // Education mode explanation
    EDUCATION_MODE: `
        <div class="education-explanation">
            <h3>🎓 You're Starting in Education Mode</h3>
            <p>This is the safest way to learn trading:</p>
            <ul>
                <li>✅ $10,000 simulated balance (not real money)</li>
                <li>✅ Real market data with simulated execution</li>
                <li>✅ Track your progress and learn risk-free</li>
                <li>✅ Upgrade to live trading when you're ready</li>
            </ul>
            <p class="education-note">
                <strong>Remember:</strong> All trades in education mode are simulated. 
                No real money is used or at risk.
            </p>
        </div>
    `
};

// ========================================
// Required Consent Checkboxes
// ========================================

const REQUIRED_CONSENTS = [
    {
        id: 'consent-risk-loss',
        text: 'I understand that cryptocurrency trading involves substantial risk of loss, and I may lose some or all of my invested capital.'
    },
    {
        id: 'consent-no-guarantee',
        text: 'I understand that NIJA makes NO GUARANTEES of profit or performance, and past results do not indicate future returns.'
    },
    {
        id: 'consent-responsibility',
        text: 'I understand that I am solely responsible for my trading decisions and that NIJA is a tool I control.'
    },
    {
        id: 'consent-independent',
        text: 'I understand that my account trades independently and is not copying trades from other users.'
    },
    {
        id: 'consent-education-first',
        text: 'I will start in Education Mode and will only upgrade to live trading when I am ready and have demonstrated profitability.'
    },
    {
        id: 'consent-age-jurisdiction',
        text: 'I confirm that I am at least 18 years old and legally permitted to trade cryptocurrency in my jurisdiction.'
    }
];

// ========================================
// Display Functions
// ========================================

/**
 * Show risk disclaimer modal - MUST be called on first launch
 * @returns {Promise<boolean>} True if user acknowledged, false if dismissed
 */
function showRiskDisclaimer() {
    return new Promise((resolve) => {
        // Check if already acknowledged
        const acknowledged = localStorage.getItem('nija_risk_acknowledged');
        if (acknowledged === 'true') {
            resolve(true);
            return;
        }
        
        // Create modal
        const modal = document.createElement('div');
        modal.id = 'risk-disclaimer-modal';
        modal.className = 'modal risk-modal';
        modal.innerHTML = `
            <div class="modal-content risk-content">
                ${RISK_DISCLAIMERS.MAIN_WARNING}
                <div class="modal-actions">
                    <button id="acknowledge-risk-btn" class="btn btn-primary">
                        I Understand and Accept These Risks
                    </button>
                </div>
            </div>
        `;
        
        document.body.appendChild(modal);
        modal.style.display = 'block';
        
        // Handle acknowledgment
        document.getElementById('acknowledge-risk-btn').addEventListener('click', () => {
            localStorage.setItem('nija_risk_acknowledged', 'true');
            localStorage.setItem('nija_risk_acknowledged_date', new Date().toISOString());
            modal.remove();
            resolve(true);
        });
    });
}

/**
 * Show consent checkboxes - MUST all be checked before live trading
 * @returns {Promise<boolean>} True if all consents given, false otherwise
 */
function showConsentCheckboxes() {
    return new Promise((resolve) => {
        const modal = document.createElement('div');
        modal.id = 'consent-modal';
        modal.className = 'modal consent-modal';
        
        let checkboxesHTML = '<div class="consent-list">';
        REQUIRED_CONSENTS.forEach(consent => {
            checkboxesHTML += `
                <label class="consent-item">
                    <input type="checkbox" id="${consent.id}" class="consent-checkbox" required>
                    <span>${consent.text}</span>
                </label>
            `;
        });
        checkboxesHTML += '</div>';
        
        modal.innerHTML = `
            <div class="modal-content consent-content">
                <h2>Final Acknowledgment</h2>
                <p>Please confirm you understand the following:</p>
                ${checkboxesHTML}
                <div class="modal-actions">
                    <button id="cancel-consent-btn" class="btn btn-secondary">Cancel</button>
                    <button id="confirm-consent-btn" class="btn btn-primary" disabled>
                        Complete Setup
                    </button>
                </div>
                <p class="consent-footer">
                    By completing this setup, you agree to our 
                    <a href="/terms" target="_blank">Terms of Service</a> and 
                    <a href="/privacy" target="_blank">Privacy Policy</a>.
                </p>
            </div>
        `;
        
        document.body.appendChild(modal);
        modal.style.display = 'block';
        
        // Validate all checkboxes
        const confirmBtn = document.getElementById('confirm-consent-btn');
        const checkboxes = modal.querySelectorAll('.consent-checkbox');
        
        function validateConsents() {
            const allChecked = Array.from(checkboxes).every(cb => cb.checked);
            confirmBtn.disabled = !allChecked;
        }
        
        checkboxes.forEach(cb => {
            cb.addEventListener('change', validateConsents);
        });
        
        // Handle buttons
        document.getElementById('cancel-consent-btn').addEventListener('click', () => {
            modal.remove();
            resolve(false);
        });
        
        document.getElementById('confirm-consent-btn').addEventListener('click', () => {
            // Save consent
            const consents = {};
            checkboxes.forEach(cb => {
                consents[cb.id] = cb.checked;
            });
            localStorage.setItem('nija_consents', JSON.stringify(consents));
            localStorage.setItem('nija_consents_date', new Date().toISOString());
            
            modal.remove();
            resolve(true);
        });
    });
}

/**
 * Show education mode banner at top of app
 */
function showEducationModeBanner() {
    const existingBanner = document.getElementById('education-mode-banner');
    if (existingBanner) return; // Already shown
    
    const banner = document.createElement('div');
    banner.id = 'education-mode-banner';
    banner.className = 'education-banner';
    banner.innerHTML = `
        <div class="banner-content">
            <span class="banner-icon">🎓</span>
            <span class="banner-text">
                <strong>EDUCATION MODE</strong> - Not Real Money
            </span>
            <span class="banner-balance">
                Simulated Balance: $10,000
            </span>
        </div>
    `;
    
    // Insert at top of body
    document.body.insertBefore(banner, document.body.firstChild);
}

/**
 * Check if user has acknowledged risks
 * @returns {boolean} True if acknowledged, false otherwise
 */
function hasAcknowledgedRisks() {
    return localStorage.getItem('nija_risk_acknowledged') === 'true';
}

/**
 * Check if user has given all required consents
 * @returns {boolean} True if all consents given, false otherwise
 */
function hasGivenConsents() {
    const consents = localStorage.getItem('nija_consents');
    if (!consents) return false;
    
    try {
        const consentData = JSON.parse(consents);
        return REQUIRED_CONSENTS.every(c => consentData[c.id] === true);
    } catch {
        return false;
    }
}

/**
 * Initialize disclaimers on app load
 * Call this from your main app initialization
 */
async function initializeDisclaimers() {
    // Always show risk disclaimer on first launch
    if (!hasAcknowledgedRisks()) {
        const acknowledged = await showRiskDisclaimer();
        if (!acknowledged) {
            // User didn't acknowledge - show again or block app
            console.warn('User must acknowledge risks to use app');
            return false;
        }
    }
    
    // Show education mode banner (always in education mode by default)
    showEducationModeBanner();
    
    return true;
}

// ========================================
// Export for use in other modules
// ========================================

if (typeof window !== 'undefined') {
    window.NijaDisclaimers = {
        showRiskDisclaimer,
        showConsentCheckboxes,
        showEducationModeBanner,
        hasAcknowledgedRisks,
        hasGivenConsents,
        initializeDisclaimers,
        RISK_DISCLAIMERS,
        REQUIRED_CONSENTS
    };
}
