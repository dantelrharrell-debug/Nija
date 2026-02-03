/**
 * NIJA App Store UI Integration
 * Implements all 6 GO CONDITIONS for Apple App Store compliance
 */

// ========================================
// Safety Status Management (GO CONDITIONS #1, #2, #3)
// ========================================

let safetyStatusInterval = null;

/**
 * Load safety status from backend and update UI
 * This is called frequently to keep UI in sync with backend state
 */
async function loadSafetyStatus() {
    try {
        const response = await fetch(`${API_BASE_URL}/api/safety/status`);
        if (!response.ok) {
            console.error('Failed to load safety status:', response.status);
            return;
        }

        const status = await response.json();
        updateSafetyUI(status);

    } catch (error) {
        console.error('Error loading safety status:', error);
        // Show error state
        updateSafetyUIError();
    }
}

/**
 * Update all UI elements based on safety status
 */
function updateSafetyUI(status) {
    // Update main status banner (GO CONDITION #2)
    const statusDot = document.getElementById('status-indicator-dot');
    const statusText = document.getElementById('status-indicator-text');
    const stopSwitch = document.getElementById('stop-switch-state');
    const lastAction = document.getElementById('last-action-time');

    if (statusDot && statusText) {
        // Update dot color based on mode
        statusDot.className = 'status-indicator-dot';
        const color = status.ui_indicators?.status_dot || 'gray';
        statusDot.classList.add(color);

        // Update status text
        statusText.textContent = status.mode_display || 'Unknown Status';
    }

    // Update emergency stop state (GO CONDITION #5)
    if (stopSwitch) {
        stopSwitch.textContent = status.emergency_stop_active ? 'ACTIVE' : 'Inactive';
        stopSwitch.style.color = status.emergency_stop_active ? '#ef4444' : '#10b981';
    }

    // Update last action timestamp
    if (lastAction && status.last_state_change) {
        const timestamp = new Date(status.last_state_change);
        lastAction.textContent = timestamp.toLocaleString();
    } else if (lastAction) {
        lastAction.textContent = 'Never';
    }

    // Update idle message (GO CONDITION #3)
    const idleMessage = document.getElementById('idle-message');
    if (idleMessage && status.idle_message) {
        idleMessage.querySelector('p').textContent = status.idle_message;
    }

    // Show/hide conditional banners
    updateConditionalBanners(status);

    // Update emergency stop button state
    const emergencyBtn = document.getElementById('emergency-stop-btn');
    if (emergencyBtn) {
        emergencyBtn.disabled = status.emergency_stop_active;
        emergencyBtn.textContent = status.emergency_stop_active ? 
            '🚨 EMERGENCY STOP ACTIVE' : '🚨 EMERGENCY STOP';
    }

    // Update trading toggle if present
    const tradingToggle = document.getElementById('trading-toggle');
    if (tradingToggle) {
        tradingToggle.disabled = !status.ui_indicators?.allow_toggle;
        tradingToggle.checked = status.trading_allowed;
    }
}

/**
 * Show/hide conditional banners based on status
 */
function updateConditionalBanners(status) {
    const indicators = status.ui_indicators || {};

    // Simulation banner (GO CONDITION #6 - DRY RUN)
    const simulationBanner = document.getElementById('simulation-banner');
    if (simulationBanner) {
        if (indicators.show_simulation_banner) {
            simulationBanner.classList.remove('hidden');
        } else {
            simulationBanner.classList.add('hidden');
        }
    }

    // Emergency banner
    const emergencyBanner = document.getElementById('emergency-banner');
    if (emergencyBanner) {
        if (indicators.show_emergency_banner) {
            emergencyBanner.classList.remove('hidden');
        } else {
            emergencyBanner.classList.add('hidden');
        }
    }

    // Setup required banner (GO CONDITION #1)
    const setupBanner = document.getElementById('setup-banner');
    if (setupBanner) {
        // Show setup banner if no credentials configured and mode is disabled
        if (status.mode === 'disabled' && !status.credentials_configured) {
            setupBanner.classList.remove('hidden');
        } else {
            setupBanner.classList.add('hidden');
        }
    }
}

/**
 * Update UI to show error state
 */
function updateSafetyUIError() {
    const statusText = document.getElementById('status-indicator-text');
    if (statusText) {
        statusText.textContent = 'Status Error - Check Connection';
    }
    
    const statusDot = document.getElementById('status-indicator-dot');
    if (statusDot) {
        statusDot.className = 'status-indicator-dot red';
    }
}

/**
 * Start periodic safety status updates
 */
function startSafetyStatusUpdates() {
    // Load immediately
    loadSafetyStatus();

    // Then update every 5 seconds
    if (safetyStatusInterval) {
        clearInterval(safetyStatusInterval);
    }
    safetyStatusInterval = setInterval(loadSafetyStatus, 5000);
}

/**
 * Stop safety status updates
 */
function stopSafetyStatusUpdates() {
    if (safetyStatusInterval) {
        clearInterval(safetyStatusInterval);
        safetyStatusInterval = null;
    }
}

// ========================================
// Emergency Stop (GO CONDITION #5)
// ========================================

/**
 * Handle emergency stop button click
 */
async function handleEmergencyStop() {
    // Show confirmation modal
    const modal = document.getElementById('emergency-stop-modal');
    if (modal) {
        modal.classList.remove('hidden');
    }
}

/**
 * Confirm and execute emergency stop
 */
async function confirmEmergencyStop() {
    try {
        const response = await fetch(`${API_BASE_URL}/api/safety/emergency-stop`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                reason: 'User activated emergency stop via UI'
            })
        });

        const data = await response.json();

        if (response.ok && data.success) {
            console.log('✅ Emergency stop activated');
            
            // Close modal
            closeEmergencyModal();
            
            // Show success message
            alert('Emergency Stop Activated!\n\nAll trading has been halted. The system will need to be restarted to resume trading.');
            
            // Refresh safety status
            await loadSafetyStatus();
        } else {
            throw new Error(data.error || 'Failed to activate emergency stop');
        }

    } catch (error) {
        console.error('Error activating emergency stop:', error);
        alert(`Failed to activate emergency stop: ${error.message}`);
    }
}

/**
 * Close emergency stop modal
 */
function closeEmergencyModal() {
    const modal = document.getElementById('emergency-stop-modal');
    if (modal) {
        modal.classList.add('hidden');
    }
}

// ========================================
// Risk Acknowledgment (GO CONDITION #4)
// ========================================

let riskAcknowledgmentTimestamp = null;

/**
 * Show risk acknowledgment modal
 * This should be called before allowing LIVE trading mode
 */
function showRiskAcknowledgment() {
    const modal = document.getElementById('risk-acknowledgment-modal');
    if (modal) {
        modal.classList.remove('hidden');
    }

    // Enable/disable acknowledge button based on checkbox
    const checkbox = document.getElementById('risk-acknowledgment-checkbox');
    const acknowledgeBtn = document.getElementById('acknowledge-risk-btn');
    
    if (checkbox && acknowledgeBtn) {
        checkbox.checked = false;
        acknowledgeBtn.disabled = true;

        checkbox.addEventListener('change', function() {
            acknowledgeBtn.disabled = !this.checked;
        });
    }
}

/**
 * Close risk acknowledgment modal
 */
function closeRiskModal() {
    const modal = document.getElementById('risk-acknowledgment-modal');
    if (modal) {
        modal.classList.add('hidden');
    }
}

/**
 * User has acknowledged the risks
 */
async function acknowledgeRisk() {
    const checkbox = document.getElementById('risk-acknowledgment-checkbox');
    
    if (!checkbox || !checkbox.checked) {
        alert('Please check the acknowledgment checkbox to proceed.');
        return;
    }

    try {
        const response = await fetch(`${API_BASE_URL}/api/safety/acknowledge-risk`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                acknowledged: true,
                timestamp: new Date().toISOString()
            })
        });

        const data = await response.json();

        if (response.ok && data.success) {
            console.log('✅ Risk acknowledged');
            
            // Store timestamp
            riskAcknowledgmentTimestamp = new Date().toISOString();
            localStorage.setItem('nija_risk_acknowledged', riskAcknowledgmentTimestamp);
            
            // Update UI
            const timestampEl = document.getElementById('acknowledgment-timestamp');
            if (timestampEl) {
                timestampEl.textContent = `Acknowledged on ${new Date().toLocaleString()}`;
            }
            
            // Show next steps
            alert(`Risk Acknowledgment Recorded!\n\n${data.next_steps || 'You can now proceed with configuration.'}`);
            
            // Close modal
            closeRiskModal();
        } else {
            throw new Error(data.error || 'Failed to record acknowledgment');
        }

    } catch (error) {
        console.error('Error recording risk acknowledgment:', error);
        alert(`Failed to record risk acknowledgment: ${error.message}`);
    }
}

/**
 * Check if user has acknowledged risks
 */
function hasAcknowledgedRisk() {
    const stored = localStorage.getItem('nija_risk_acknowledged');
    return stored !== null;
}

/**
 * Before enabling LIVE mode, check risk acknowledgment
 */
function checkRiskAcknowledgmentBeforeLive(currentMode) {
    // If trying to enable LIVE mode, ensure risk is acknowledged
    if (currentMode === 'live' && !hasAcknowledgedRisk()) {
        showRiskAcknowledgment();
        return false;
    }
    return true;
}

// ========================================
// Integration with main app.js
// ========================================

// Override or extend loadDashboard to start safety updates
const originalLoadDashboard = window.loadDashboard;
window.loadDashboard = async function() {
    if (originalLoadDashboard) {
        await originalLoadDashboard();
    }
    // Start safety status updates when dashboard loads
    startSafetyStatusUpdates();
};

// Stop safety updates on logout
const originalHandleLogout = window.handleLogout;
window.handleLogout = function() {
    stopSafetyStatusUpdates();
    if (originalHandleLogout) {
        originalHandleLogout();
    }
};

// Export functions to global scope for use in HTML onclick handlers
window.handleEmergencyStop = handleEmergencyStop;
window.confirmEmergencyStop = confirmEmergencyStop;
window.closeEmergencyModal = closeEmergencyModal;
window.showRiskAcknowledgment = showRiskAcknowledgment;
window.closeRiskModal = closeRiskModal;
window.acknowledgeRisk = acknowledgeRisk;
window.loadSafetyStatus = loadSafetyStatus;

console.log('✅ App Store UI integration loaded');
