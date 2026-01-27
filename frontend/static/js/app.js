/**
 * NIJA Trading Platform - Frontend Application
 * Handles authentication, API communication, and UI updates
 */

// API Configuration
const API_BASE_URL = window.location.origin;

// State management
let authToken = null;
let userProfile = null;

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
            authToken = data.token;
            localStorage.setItem('nija_token', authToken);
            
            // Load dashboard
            loadDashboard();
        } else {
            showError(data.error || 'Login failed');
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
            authToken = data.token;
            localStorage.setItem('nija_token', authToken);
            
            // Load dashboard
            loadDashboard();
        } else {
            showError(data.error || 'Registration failed');
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
        const stats = await apiRequest('/api/user/stats');
        
        document.getElementById('stat-pnl').textContent = formatCurrency(stats.total_pnl);
        document.getElementById('stat-winrate').textContent = formatPercent(stats.win_rate);
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
        const status = await apiRequest('/api/trading/status');
        
        document.getElementById('status-text').textContent = 
            status.trading_enabled ? 'Trading Active' : 'Trading Paused';
        document.getElementById('engine-status').textContent = status.engine_status;
        document.getElementById('last-trade').textContent = 
            status.last_trade_time ? new Date(status.last_trade_time).toLocaleString() : 'Never';
        
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
        throw new Error(error.error || 'API request failed');
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
    
    const action = toggle.checked ? 'start' : 'stop';
    
    try {
        await apiRequest('/api/trading/control', {
            method: 'POST',
            body: JSON.stringify({ action })
        });
        
        // Update UI
        statusText.textContent = toggle.checked ? 'Trading ON' : 'Trading OFF';
        statusDot.style.background = toggle.checked ? '#10b981' : '#94a3b8';
        
        console.log(`✅ Trading ${toggle.checked ? 'enabled' : 'disabled'}`);
        
        // Reload status after a delay
        setTimeout(loadTradingStatus, 1000);
        
    } catch (error) {
        console.error('Failed to toggle trading:', error);
        // Revert toggle state
        toggle.checked = !toggle.checked;
        alert('Failed to toggle trading. Please try again.');
    }
}

// Update loadTradingStatus to sync toggle state
const originalLoadTradingStatus = loadTradingStatus;
loadTradingStatus = async function() {
    try {
        const status = await apiRequest('/api/trading/status');
        
        // Update toggle
        const toggle = document.getElementById('trading-toggle');
        if (toggle) {
            toggle.checked = status.trading_enabled;
        }
        
        document.getElementById('status-text').textContent = 
            status.trading_enabled ? 'Trading ON' : 'Trading OFF';
        document.getElementById('engine-status').textContent = status.engine_status;
        document.getElementById('last-trade').textContent = 
            status.last_trade_time ? new Date(status.last_trade_time).toLocaleString() : 'Never';
        
        // Update status dot color
        const dotEl = document.getElementById('status-dot');
        dotEl.style.background = status.trading_enabled ? '#10b981' : '#94a3b8';
    } catch (error) {
        console.error('Failed to load trading status:', error);
    }
};
