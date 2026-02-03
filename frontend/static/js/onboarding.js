/**
 * NIJA Education Mode & Onboarding
 * 
 * Implements the three-layer onboarding UX:
 * 1. Education Mode (default) - Learn with simulated money
 * 2. Optional upgrade path - Explicit opt-in
 * 3. Live Trading Mode - After consent and broker connection
 */

// ========================================
// State Management
// ========================================

let onboardingState = {
    mode: 'education',  // 'education' or 'live_trading'
    isNewUser: true,
    showWelcome: true,
    progress: null,
    readyForUpgrade: false
};

// ========================================
// Onboarding Flow Functions
// ========================================

/**
 * Initialize onboarding on app start
 */
async function initializeOnboarding() {
    try {
        const response = await fetch(`${API_BASE_URL}/api/user/onboarding/status`, {
            method: 'GET',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${localStorage.getItem('auth_token')}`
            }
        });

        if (!response.ok) {
            console.error('Failed to load onboarding status');
            return;
        }

        const data = await response.json();
        onboardingState = data.onboarding;

        // Show appropriate screen
        if (onboardingState.show_welcome) {
            showOnboardingWelcome();
        } else {
            // Check if in education mode
            await loadUserMode();
            showDashboard();
        }

    } catch (error) {
        console.error('Error initializing onboarding:', error);
        showDashboard();  // Fallback to dashboard
    }
}

/**
 * Load current user mode
 */
async function loadUserMode() {
    try {
        const response = await fetch(`${API_BASE_URL}/api/user/mode`, {
            method: 'GET',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${localStorage.getItem('auth_token')}`
            }
        });

        if (!response.ok) {
            console.error('Failed to load user mode');
            return;
        }

        const data = await response.json();
        
        onboardingState.mode = data.mode;
        onboardingState.progress = data.progress;
        onboardingState.readyForUpgrade = data.ready_for_upgrade;

        // Update UI based on mode
        updateModeUI(data);

    } catch (error) {
        console.error('Error loading user mode:', error);
    }
}

/**
 * Update UI based on user mode
 */
function updateModeUI(modeData) {
    const educationBanner = document.getElementById('education-mode-banner');
    const upgradeBtn = document.getElementById('upgrade-btn');

    if (modeData.education_mode) {
        // Show education mode indicators
        if (educationBanner) {
            educationBanner.classList.remove('hidden');
        }

        // Show upgrade button if ready
        if (modeData.ready_for_upgrade && upgradeBtn) {
            upgradeBtn.style.display = 'inline-block';
        }

        // Update stat labels to indicate simulated money
        updateStatLabels(true);
    } else {
        // Hide education mode indicators
        if (educationBanner) {
            educationBanner.classList.add('hidden');
        }

        // Update stat labels to indicate real money
        updateStatLabels(false);
    }
}

/**
 * Update stat labels based on mode
 */
function updateStatLabels(isEducationMode) {
    const pnlCard = document.querySelector('#stat-pnl').parentElement;
    if (pnlCard) {
        const label = pnlCard.querySelector('.stat-label');
        if (label) {
            label.textContent = isEducationMode ? 'Total P&L (Simulated)' : 'Total P&L';
        }
    }
}

/**
 * Show onboarding welcome screen
 */
function showOnboardingWelcome() {
    hideAllScreens();
    document.getElementById('onboarding-screen').classList.remove('hidden');
    document.getElementById('onboarding-welcome').classList.remove('hidden');
    document.getElementById('onboarding-education').classList.add('hidden');
    document.getElementById('onboarding-upgrade').classList.add('hidden');
}

/**
 * Start education mode
 */
async function startEducationMode() {
    // Show education mode step
    document.getElementById('onboarding-welcome').classList.add('hidden');
    document.getElementById('onboarding-education').classList.remove('hidden');

    // Update progress
    await updateEducationProgress();
}

/**
 * Update education progress from backend
 */
async function updateEducationProgress() {
    try {
        const response = await fetch(`${API_BASE_URL}/api/user/mode/education/progress`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${localStorage.getItem('auth_token')}`
            }
        });

        if (!response.ok) {
            console.error('Failed to update education progress');
            return;
        }

        const data = await response.json();
        displayEducationProgress(data.progress);

    } catch (error) {
        console.error('Error updating education progress:', error);
    }
}

/**
 * Display education progress in UI
 */
function displayEducationProgress(progress) {
    if (!progress) return;

    // Update progress bar
    const progressBar = document.getElementById('education-progress-bar');
    const progressText = document.getElementById('education-progress-text');
    
    if (progressBar && progressText) {
        const percentage = progress.progress_percentage || 0;
        progressBar.style.width = `${percentage}%`;
        progressText.textContent = `${percentage}% Complete`;
    }

    // Update milestones
    updateMilestone('milestone-first-trade', progress.milestones?.completed_first_trade);
    updateMilestone('milestone-10-trades', progress.milestones?.reached_10_trades);
    updateMilestone('milestone-positive-pnl', progress.milestones?.achieved_positive_pnl);
    updateMilestone('milestone-ready', progress.ready_for_live_trading);
}

/**
 * Update milestone display
 */
function updateMilestone(milestoneId, completed) {
    const milestone = document.getElementById(milestoneId);
    if (!milestone) return;

    const icon = milestone.querySelector('.milestone-icon');
    if (completed) {
        icon.textContent = '✅';
        milestone.classList.add('completed');
    } else {
        icon.textContent = '⚪';
        milestone.classList.remove('completed');
    }
}

/**
 * Continue to dashboard from education screen
 */
function continueToDashboard() {
    hideAllScreens();
    document.getElementById('dashboard-screen').classList.remove('hidden');
    loadUserMode();
    loadDashboardData();
}

/**
 * Show education progress modal
 */
async function showEducationProgress() {
    await updateEducationProgress();
    
    // Re-show the education step with updated progress
    document.getElementById('onboarding-education').classList.remove('hidden');
    document.getElementById('onboarding-screen').classList.remove('hidden');
    document.getElementById('dashboard-screen').classList.add('hidden');
}

/**
 * Show upgrade option screen
 */
async function showUpgradeOption() {
    // Load latest progress
    await loadUserMode();

    if (!onboardingState.readyForUpgrade) {
        alert('Complete more trades in education mode before upgrading to live trading.');
        return;
    }

    // Show upgrade screen
    hideAllScreens();
    document.getElementById('onboarding-screen').classList.remove('hidden');
    document.getElementById('onboarding-upgrade').classList.remove('hidden');

    // Populate stats
    if (onboardingState.progress) {
        const p = onboardingState.progress;
        document.getElementById('upgrade-winrate').textContent = `${p.win_rate}%`;
        document.getElementById('upgrade-trades').textContent = p.total_trades;
        document.getElementById('upgrade-pnl').textContent = `$${p.total_pnl.toFixed(2)}`;
    }

    // Setup consent checkboxes
    setupConsentCheckboxes();
}

/**
 * Setup consent checkbox validation
 */
function setupConsentCheckboxes() {
    const checkboxes = [
        'consent-understand-risk',
        'consent-can-afford',
        'consent-broker-direct',
        'consent-in-control'
    ];

    const proceedBtn = document.getElementById('proceed-live-btn');

    function validateConsent() {
        const allChecked = checkboxes.every(id => {
            const checkbox = document.getElementById(id);
            return checkbox && checkbox.checked;
        });

        if (proceedBtn) {
            proceedBtn.disabled = !allChecked;
        }
    }

    // Add listeners to all checkboxes
    checkboxes.forEach(id => {
        const checkbox = document.getElementById(id);
        if (checkbox) {
            checkbox.addEventListener('change', validateConsent);
        }
    });

    validateConsent();
}

/**
 * Proceed to live trading after consent
 */
async function proceedToLiveTrading() {
    try {
        // First, record consent
        const consentResponse = await fetch(`${API_BASE_URL}/api/user/mode/live/consent`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${localStorage.getItem('auth_token')}`
            },
            body: JSON.stringify({
                consent_confirmed: true,
                risks_acknowledged: true
            })
        });

        if (!consentResponse.ok) {
            const error = await consentResponse.json();
            alert(`Error: ${error.error || 'Failed to record consent'}`);
            return;
        }

        // Show success and navigate to broker connection
        alert('Consent recorded successfully. Please connect your broker account to enable live trading.');
        
        // Navigate to broker setup
        hideAllScreens();
        document.getElementById('dashboard-screen').classList.remove('hidden');
        showBrokers();

    } catch (error) {
        console.error('Error proceeding to live trading:', error);
        alert('An error occurred. Please try again.');
    }
}

/**
 * Stay in education mode
 */
function stayInEducation() {
    hideAllScreens();
    document.getElementById('dashboard-screen').classList.remove('hidden');
    loadDashboardData();
}

/**
 * Hide all screens
 */
function hideAllScreens() {
    const screens = [
        'loading-screen',
        'auth-screen',
        'onboarding-screen',
        'dashboard-screen'
    ];

    screens.forEach(screenId => {
        const screen = document.getElementById(screenId);
        if (screen) {
            screen.classList.add('hidden');
        }
    });

    // Hide onboarding steps
    const steps = [
        'onboarding-welcome',
        'onboarding-education',
        'onboarding-upgrade'
    ];

    steps.forEach(stepId => {
        const step = document.getElementById(stepId);
        if (step) {
            step.classList.add('hidden');
        }
    });
}

// ========================================
// Initialize on Page Load
// ========================================

// Add to existing app initialization
if (typeof window !== 'undefined') {
    // Hook into existing authentication flow
    const originalHandleLogin = window.handleLogin;
    window.handleLogin = async function(event) {
        event.preventDefault();
        
        // Call original login
        if (originalHandleLogin) {
            await originalHandleLogin.call(this, event);
        }
        
        // Initialize onboarding after login
        setTimeout(() => {
            initializeOnboarding();
        }, 500);
    };

    const originalHandleRegister = window.handleRegister;
    window.handleRegister = async function(event) {
        event.preventDefault();
        
        // Call original register
        if (originalHandleRegister) {
            await originalHandleRegister.call(this, event);
        }
        
        // Initialize onboarding after registration
        setTimeout(() => {
            initializeOnboarding();
        }, 500);
    };
}

console.log('📚 Education Mode & Onboarding initialized');
