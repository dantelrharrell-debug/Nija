/**
 * NIJA Trading Platform - Frontend Application
 * Handles authentication, API communication, and UI updates
 */

// API Configuration
const API_BASE_URL = window.location.origin;

// State management
let authToken = null;
let userProfile = null;
let latestCombinedTrailingSizePlan = null;

// Initialize app
document.addEventListener('DOMContentLoaded', () => {
    console.log('NIJA App initializing...');

    // Check for saved token
    authToken = localStorage.getItem('nija_token');

    if (authToken) {
        // Validate token and load dashboard
        loadDashboard();
    } else {
        // Show auth screen
        showAuthScreen();
    }
});

// ========================================
// Screen Navigation
// ========================================

function showAuthScreen() {
    hideElement('loading-screen');
    hideElement('dashboard-screen');
    showElement('auth-screen');
}

function showDashboardScreen() {
    hideElement('loading-screen');
    hideElement('auth-screen');
    showElement('dashboard-screen');
}

function showDashboard() {
    hideElement('brokers-content');
    hideElement('settings-content');
    showElement('dashboard-content');
    updateNavLinks('dashboard');
    ensureCombinedTrailingExecutionPanel();
}

function showBrokers() {
    hideElement('dashboard-content');
    hideElement('settings-content');
    showElement('brokers-content');
    updateNavLinks('brokers');
    loadBrokers();
}

function showSettings() {
    hideElement('dashboard-content');
    hideElement('brokers-content');
    showElement('settings-content');
    updateNavLinks('settings');
    loadSettings();
}

function updateNavLinks(active) {
    document.querySelectorAll('.nav-link').forEach(link => {
        link.classList.remove('active');
    });
}

function showLoginForm() {
    showElement('login-form');
    hideElement('register-form');
    hideElement('auth-error');
}

function showRegisterForm() {
    hideElement('login-form');
    showElement('register-form');
    hideElement('auth-error');
}

// ========================================
// Authentication Handlers
// ========================================

async function handleLogin(event) {
    event.preventDefault();

    const email = document.getElementById('login-email').value;
    const password = document.getElementById('login-password').value;

    try {
        const response = await fetch(`${API_BASE_URL}/api/auth/login`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ email, password })
        });

        const data = await response.json();

        if (response.ok) {
            // Save token
            authToken = data.access_token;
            localStorage.setItem('nija_token', authToken);

            // Load dashboard
            loadDashboard();
        } else {
            showError(data.detail || 'Login failed');
        }
    } catch (error) {
        console.error('Login error:', error);
        showError('Network error. Please check your connection.');
    }
}

async function handleRegister(event) {
    event.preventDefault();

    const email = document.getElementById('register-email').value;
    const password = document.getElementById('register-password').value;
    const subscription_tier = document.getElementById('register-tier').value;

    try {
        const response = await fetch(`${API_BASE_URL}/api/auth/register`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ email, password, subscription_tier })
        });

        const data = await response.json();

        if (response.ok) {
            // Save token
            authToken = data.access_token;
            localStorage.setItem('nija_token', authToken);

            // Load dashboard
            loadDashboard();
        } else {
            showError(data.detail || 'Registration failed');
        }
    } catch (error) {
        console.error('Registration error:', error);
        showError('Network error. Please check your connection.');
    }
}

function handleLogout() {
    // Clear token
    authToken = null;
    userProfile = null;
    localStorage.removeItem('nija_token');

    // Show auth screen
    showAuthScreen();
}

function showError(message) {
    const errorEl = document.getElementById('auth-error');
    errorEl.textContent = message;
    showElement('auth-error');
}

// ========================================
// Dashboard Loading
// ========================================

async function loadDashboard() {
    try {
        // Load user profile
        const profile = await apiRequest('/api/user/profile');
        userProfile = profile;

        // Update UI
        document.getElementById('user-email').textContent = profile.email;
        document.getElementById('user-tier').textContent = profile.subscription_tier;

        // Load stats
        await loadStats();

        // Load trading status
        await loadTradingStatus();

        // Show dashboard
        showDashboardScreen();
        showDashboard();

    } catch (error) {
        console.error('Failed to load dashboard:', error);
        // Token might be invalid, logout
        handleLogout();
    }
}

async function loadStats() {
    try {
        const stats = await apiRequest('/api/pnl');

        document.getElementById('stat-pnl').textContent = formatCurrency(stats.total_pnl);
        document.getElementById('stat-winrate').textContent = formatPercent(stats.win_rate / 100);
        document.getElementById('stat-trades').textContent = stats.total_trades;
        document.getElementById('stat-positions').textContent = stats.active_positions;

        // Update PnL color
        const pnlEl = document.getElementById('stat-pnl');
        if (stats.total_pnl > 0) {
            pnlEl.style.color = '#10b981';
        } else if (stats.total_pnl < 0) {
            pnlEl.style.color = '#ef4444';
        }
    } catch (error) {
        console.error('Failed to load stats:', error);
    }
}

async function loadTradingStatus() {
    try {
        const status = await apiRequest('/api/status');

        document.getElementById('status-text').textContent =
            status.trading_enabled ? 'Trading Active' : 'Trading Paused';
        document.getElementById('engine-status').textContent = status.engine_status;
        document.getElementById('last-trade').textContent =
            status.last_activity ? new Date(status.last_activity).toLocaleString() : 'Never';

        // Update status dot color
        const dotEl = document.getElementById('status-dot');
        dotEl.style.background = status.trading_enabled ? '#10b981' : '#f59e0b';
    } catch (error) {
        console.error('Failed to load trading status:', error);
    }
}

async function loadBrokers() {
    try {
        const data = await apiRequest('/api/user/brokers');

        const container = document.getElementById('brokers-list');

        if (data.brokers.length === 0) {
            container.innerHTML = '<p class="empty-state">No brokers configured</p>';
        } else {
            container.innerHTML = data.brokers.map(broker => `
                <div class="broker-item">
                    <span class="broker-name">${broker}</span>
                    <button class="btn btn-danger" onclick="removeBroker('${broker}')">Remove</button>
                </div>
            `).join('');
        }
    } catch (error) {
        console.error('Failed to load brokers:', error);
    }
}

async function loadSettings() {
    if (!userProfile) return;

    document.getElementById('setting-user-id').textContent = userProfile.user_id;
    document.getElementById('setting-email').textContent = userProfile.email;
    document.getElementById('setting-tier').textContent = userProfile.subscription_tier;

    if (userProfile.permissions) {
        document.getElementById('setting-max-position').textContent =
            formatCurrency(userProfile.permissions.max_position_size_usd);
    }
}

// ========================================
// Broker Management
// ========================================

async function handleAddBroker(event) {
    event.preventDefault();

    const broker = document.getElementById('broker-name').value;
    const apiKey = document.getElementById('broker-api-key').value;
    const apiSecret = document.getElementById('broker-api-secret').value;

    try {
        await apiRequest(`/api/user/brokers/${broker}`, {
            method: 'POST',
            body: JSON.stringify({
                api_key: apiKey,
                api_secret: apiSecret
            })
        });

        // Clear form
        document.getElementById('add-broker-form').reset();

        // Reload brokers list
        await loadBrokers();

        alert(`${broker} credentials added successfully!`);
    } catch (error) {
        console.error('Failed to add broker:', error);
        alert('Failed to add broker credentials. Please try again.');
    }
}

async function removeBroker(broker) {
    if (!confirm(`Remove ${broker} credentials?`)) {
        return;
    }

    try {
        await apiRequest(`/api/user/brokers/${broker}`, {
            method: 'DELETE'
        });

        // Reload brokers list
        await loadBrokers();

        alert(`${broker} credentials removed successfully!`);
    } catch (error) {
        console.error('Failed to remove broker:', error);
        alert('Failed to remove broker credentials. Please try again.');
    }
}

// ========================================
// API Request Helper
// ========================================

async function apiRequest(endpoint, options = {}) {
    const headers = {
        'Content-Type': 'application/json',
        ...options.headers
    };

    if (authToken) {
        headers['Authorization'] = `Bearer ${authToken}`;
    }

    const response = await fetch(`${API_BASE_URL}${endpoint}`, {
        ...options,
        headers
    });

    if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || 'API request failed');
    }

    return response.json();
}

// ========================================
// Utility Functions
// ========================================

function showElement(id) {
    const el = document.getElementById(id);
    if (el) el.classList.remove('hidden');
}

function hideElement(id) {
    const el = document.getElementById(id);
    if (el) el.classList.add('hidden');
}

function formatCurrency(value) {
    return new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: 'USD',
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
    }).format(value);
}

function formatPercent(value) {
    return `${(value * 100).toFixed(1)}%`;
}

function numberValue(id, fallback = 0) {
    const el = document.getElementById(id);
    if (!el) return fallback;
    const value = Number.parseFloat(el.value);
    return Number.isFinite(value) ? value : fallback;
}

function setValueIfPresent(id, value) {
    const el = document.getElementById(id);
    if (el) el.value = value;
}

// Auto-refresh dashboard data every 30 seconds
setInterval(() => {
    if (authToken && !document.getElementById('dashboard-screen').classList.contains('hidden')) {
        loadStats();
        loadTradingStatus();
    }
}, 30000);

// ========================================
// Trading Control
// ========================================

async function handleTradingToggle() {
    const toggle = document.getElementById('trading-toggle');
    const statusText = document.getElementById('status-text');
    const statusDot = document.getElementById('status-dot');

    const isEnabled = toggle.checked;
    const endpoint = isEnabled ? '/api/start_bot' : '/api/stop_bot';

    try {
        await apiRequest(endpoint, {
            method: 'POST'
        });

        // Update UI
        statusText.textContent = isEnabled ? 'Trading ON' : 'Trading OFF';
        statusDot.style.background = isEnabled ? '#10b981' : '#94a3b8';

        console.log(`✅ Trading ${isEnabled ? 'enabled' : 'disabled'}`);

        // Reload status after a delay
        setTimeout(loadTradingStatus, 1000);

    } catch (error) {
        console.error('Failed to toggle trading:', error);
        // Revert toggle state
        toggle.checked = !toggle.checked;
        alert('Failed to toggle trading. Please try again.');
    }
}

// Enhanced loadTradingStatus to sync toggle state
async function loadTradingStatus() {
    try {
        const status = await apiRequest('/api/status');

        // Update toggle
        const toggle = document.getElementById('trading-toggle');
        if (toggle) {
            toggle.checked = status.trading_enabled;
        }

        document.getElementById('status-text').textContent =
            status.trading_enabled ? 'Trading ON' : 'Trading OFF';
        document.getElementById('engine-status').textContent = status.engine_status;
        document.getElementById('last-trade').textContent =
            status.last_activity ? new Date(status.last_activity).toLocaleString() : 'Never';

        // Update status dot color
        const dotEl = document.getElementById('status-dot');
        dotEl.style.background = status.trading_enabled ? '#10b981' : '#94a3b8';
    } catch (error) {
        console.error('Failed to load trading status:', error);
    }
}

// ========================================
// Combined Trailing Execution Panel
// ========================================

function ensureCombinedTrailingExecutionPanel() {
    if (document.getElementById('combined-trailing-execution-panel')) return;
    const dashboardContent = document.getElementById('dashboard-content');
    if (!dashboardContent) return;

    const tradingControl = dashboardContent.querySelector('.section');
    const panel = document.createElement('div');
    panel.className = 'section';
    panel.id = 'combined-trailing-execution-panel';
    panel.innerHTML = `
        <h3>Trade Execution Panel</h3>
        <div class="status-card">
            <p class="idle-message"><strong>Combined trailing protection sizing.</strong> Calculate risk-based size, then one-click fill notional and quantity before execution.</p>
            <div class="settings-grid">
                <div class="setting-item"><label>Symbol</label><input id="ctp-symbol" value="BTC-USD" placeholder="BTC-USD"></div>
                <div class="setting-item"><label>Side</label><select id="ctp-side"><option value="buy">Buy / Long</option><option value="sell">Sell / Short</option></select></div>
                <div class="setting-item"><label>Entry Price</label><input id="ctp-entry-price" type="number" step="0.00000001" placeholder="Market or limit price"></div>
                <div class="setting-item"><label>Equity USD</label><input id="ctp-equity-usd" type="number" step="0.01" placeholder="Account equity"></div>
                <div class="setting-item"><label>Available Cash USD</label><input id="ctp-cash-usd" type="number" step="0.01" placeholder="Available cash"></div>
                <div class="setting-item"><label>Risk %</label><input id="ctp-risk-pct" type="number" step="0.0001" value="0.005"></div>
                <div class="setting-item"><label>Trailing SL Distance %</label><input id="ctp-stop-distance-pct" type="number" step="0.0001" value="0.006"></div>
                <div class="setting-item"><label>Min Notional USD</label><input id="ctp-min-notional" type="number" step="0.01" value="10"></div>
                <div class="setting-item"><label>Max Notional USD</label><input id="ctp-max-notional" type="number" step="0.01" placeholder="Optional cap"></div>
            </div>
            <div class="banner-actions" style="margin-top: 1rem; display: flex; gap: 0.75rem; flex-wrap: wrap;">
                <button class="btn btn-secondary" onclick="calculateCombinedTrailingSizeFromPanel()">Calculate Size</button>
                <button class="btn btn-primary" onclick="oneClickFillCombinedTrailingTrade()">One-Click Fill</button>
            </div>
            <div class="settings-grid" style="margin-top: 1rem;">
                <div class="setting-item"><label>Calculated Notional</label><input id="trade-notional-usd" readonly placeholder="$0.00"></div>
                <div class="setting-item"><label>Calculated Quantity</label><input id="trade-quantity" readonly placeholder="0.00000000"></div>
                <div class="setting-item"><label>Protection Stop Price</label><input id="trade-stop-price" readonly placeholder="0.00000000"></div>
                <div class="setting-item"><label>Risk Budget</label><input id="trade-risk-budget" readonly placeholder="$0.00"></div>
            </div>
            <pre id="ctp-size-result" class="empty-state" style="white-space: pre-wrap; margin-top: 1rem; text-align: left;">No size calculated yet.</pre>
        </div>
    `;
    if (tradingControl && tradingControl.nextSibling) {
        dashboardContent.insertBefore(panel, tradingControl.nextSibling);
    } else {
        dashboardContent.appendChild(panel);
    }
}

function calculateCombinedTrailingSizeFromPanel() {
    const symbol = (document.getElementById('ctp-symbol')?.value || '').trim().toUpperCase().replace('/', '-').replace('_', '-');
    const side = document.getElementById('ctp-side')?.value || 'buy';
    const entryPrice = numberValue('ctp-entry-price');
    const equityUsd = numberValue('ctp-equity-usd');
    const availableCashUsd = numberValue('ctp-cash-usd', equityUsd);
    const riskPct = numberValue('ctp-risk-pct', 0.005);
    const stopDistancePct = numberValue('ctp-stop-distance-pct', 0.006);
    const minNotionalUsd = numberValue('ctp-min-notional', 10);
    const maxNotionalInput = numberValue('ctp-max-notional', availableCashUsd || equityUsd);
    const maxNotionalUsd = Math.max(0, Math.min(maxNotionalInput || availableCashUsd || equityUsd, availableCashUsd || equityUsd));
    let reason = 'ok';
    let valid = true;

    if (!symbol) { valid = false; reason = 'missing_symbol'; }
    else if (!(entryPrice > 0)) { valid = false; reason = 'invalid_entry_price'; }
    else if (!(equityUsd > 0) || !(availableCashUsd > 0)) { valid = false; reason = 'no_equity_or_cash'; }
    else if (!(maxNotionalUsd > 0)) { valid = false; reason = 'max_notional_zero'; }

    const riskBudgetUsd = equityUsd * riskPct;
    const rawNotionalUsd = stopDistancePct > 0 ? riskBudgetUsd / stopDistancePct : 0;
    let finalNotionalUsd = Math.min(rawNotionalUsd, availableCashUsd, maxNotionalUsd);
    const clampedByCash = rawNotionalUsd > availableCashUsd;
    const clampedByMaxNotional = rawNotionalUsd > maxNotionalUsd;
    let liftedToMinNotional = false;

    if (valid && minNotionalUsd > 0 && finalNotionalUsd > 0 && finalNotionalUsd < minNotionalUsd && minNotionalUsd <= maxNotionalUsd) {
        finalNotionalUsd = minNotionalUsd;
        liftedToMinNotional = true;
    }
    if (valid && finalNotionalUsd < minNotionalUsd) {
        valid = false;
        reason = 'below_min_notional_after_clamps';
    }

    const quantity = valid ? finalNotionalUsd / entryPrice : 0;
    const stopPrice = side === 'buy' || side === 'long'
        ? entryPrice * (1 - stopDistancePct)
        : entryPrice * (1 + stopDistancePct);

    latestCombinedTrailingSizePlan = {
        symbol,
        side,
        entry_price: entryPrice,
        equity_usd: equityUsd,
        available_cash_usd: availableCashUsd,
        risk_pct: riskPct,
        risk_budget_usd: riskBudgetUsd,
        stop_distance_pct: stopDistancePct,
        stop_price: stopPrice,
        raw_notional_usd: rawNotionalUsd,
        max_notional_usd: maxNotionalUsd,
        min_notional_usd: minNotionalUsd,
        final_notional_usd: valid ? finalNotionalUsd : 0,
        quantity,
        clamped_by_cash: clampedByCash,
        clamped_by_max_notional: clampedByMaxNotional,
        lifted_to_min_notional: liftedToMinNotional,
        valid,
        reason
    };

    const resultEl = document.getElementById('ctp-size-result');
    if (resultEl) {
        resultEl.textContent = JSON.stringify(latestCombinedTrailingSizePlan, null, 2);
    }
    return latestCombinedTrailingSizePlan;
}

function oneClickFillCombinedTrailingTrade() {
    const plan = calculateCombinedTrailingSizeFromPanel();
    if (!plan.valid) {
        alert(`Cannot fill trade size: ${plan.reason}`);
        return;
    }

    setValueIfPresent('trade-notional-usd', plan.final_notional_usd.toFixed(2));
    setValueIfPresent('trade-quantity', plan.quantity.toFixed(8));
    setValueIfPresent('trade-stop-price', plan.stop_price.toFixed(8));
    setValueIfPresent('trade-risk-budget', plan.risk_budget_usd.toFixed(2));

    // Also fill common execution-form field ids if another panel exists.
    setValueIfPresent('order-symbol', plan.symbol);
    setValueIfPresent('order-side', plan.side);
    setValueIfPresent('order-notional-usd', plan.final_notional_usd.toFixed(2));
    setValueIfPresent('order-quantity', plan.quantity.toFixed(8));
    setValueIfPresent('order-stop-loss', plan.stop_price.toFixed(8));
    setValueIfPresent('position-size-usd', plan.final_notional_usd.toFixed(2));
    setValueIfPresent('position-quantity', plan.quantity.toFixed(8));

    console.log('COMBINED_TRAILING_PANEL_ONE_CLICK_FILL', plan);
}
