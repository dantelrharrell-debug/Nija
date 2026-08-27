/**
 * Capacitor Initialization and Native Features
 *
 * This file handles:
 * - Capacitor plugin initialization
 * - Status bar configuration
 * - Splash screen handling
 * - Push notifications setup
 * - Native device features
 * - Store-required in-app account deletion access
 */

// Check if running in Capacitor (native app)
const isNativeApp = typeof window.Capacitor !== 'undefined';

// Native app state
const NativeApp = {
    isNative: isNativeApp,
    platform: null,
    deviceInfo: null,
    initialized: false
};

/**
 * Initialize Capacitor and native features
 */
async function initializeCapacitor() {
    if (!isNativeApp) {
        console.log('Running as web app (not native)');
        return;
    }

    try {
        const { Capacitor } = window;
        const { Device } = Capacitor.Plugins;
        const { StatusBar } = Capacitor.Plugins;
        const { SplashScreen } = Capacitor.Plugins;
        const { App } = Capacitor.Plugins;
        const { Keyboard } = Capacitor.Plugins;
        const { Network } = Capacitor.Plugins;

        if (Device) {
            NativeApp.deviceInfo = await Device.getInfo();
            NativeApp.platform = NativeApp.deviceInfo.platform;
            console.log('Device info:', NativeApp.deviceInfo);
        }

        if (StatusBar) {
            await StatusBar.setStyle({ style: 'DARK' });
            await StatusBar.setBackgroundColor({ color: '#0f172a' });
            console.log('Status bar configured');
        }

        if (SplashScreen) {
            window.addEventListener('load', async () => {
                setTimeout(async () => {
                    await SplashScreen.hide();
                }, 2000);
            });
        }

        if (Keyboard) {
            await Keyboard.setAccessoryBarVisible({ isVisible: true });
            await Keyboard.setScroll({ isDisabled: false });
        }

        if (App) {
            App.addListener('appStateChange', ({ isActive }) => {
                console.log('App state changed. Is active:', isActive);
                if (isActive && window.refreshDashboard) {
                    window.refreshDashboard();
                }
            });

            App.addListener('backButton', () => {
                console.log('Back button pressed');
                if (window.handleBackButton) {
                    window.handleBackButton();
                }
            });
        }

        if (Network) {
            Network.addListener('networkStatusChange', (status) => {
                console.log('Network status changed', status);
                if (window.handleNetworkChange) {
                    window.handleNetworkChange(status);
                }
            });
        }

        NativeApp.initialized = true;
        console.log('Capacitor initialized successfully');
        window.dispatchEvent(new CustomEvent('capacitor-ready'));

    } catch (error) {
        console.error('Error initializing Capacitor:', error);
    }
}

/**
 * Initialize push notifications
 */
async function initializePushNotifications() {
    if (!isNativeApp) return;

    try {
        const { PushNotifications } = window.Capacitor.Plugins;
        let permStatus = await PushNotifications.checkPermissions();

        if (permStatus.receive === 'prompt') {
            permStatus = await PushNotifications.requestPermissions();
        }

        if (permStatus.receive !== 'granted') {
            console.log('Push notification permission not granted');
            return;
        }

        await PushNotifications.register();

        PushNotifications.addListener('registration', (token) => {
            console.log('Push registration success');
            if (window.registerPushToken) {
                window.registerPushToken(token.value);
            }
        });

        PushNotifications.addListener('registrationError', (error) => {
            console.error('Push registration error:', error);
        });

        PushNotifications.addListener('pushNotificationReceived', (notification) => {
            console.log('Push notification received');
            if (window.handlePushNotification) {
                window.handlePushNotification(notification);
            }
        });

        PushNotifications.addListener('pushNotificationActionPerformed', (notification) => {
            console.log('Push notification action performed');
            if (window.handlePushAction) {
                window.handlePushAction(notification);
            }
        });

        console.log('Push notifications initialized');

    } catch (error) {
        console.error('Error initializing push notifications:', error);
    }
}

/**
 * Show a native toast/alert
 */
async function showNativeToast(message, duration = 'short') {
    if (!isNativeApp) {
        console.log('Toast (web):', message);
        return;
    }

    try {
        const { Toast } = window.Capacitor.Plugins;
        if (Toast) {
            await Toast.show({
                text: message,
                duration: duration,
                position: 'bottom'
            });
        }
    } catch (error) {
        console.error('Error showing toast:', error);
    }
}

/**
 * Trigger haptic feedback
 */
async function triggerHaptic(style = 'medium') {
    if (!isNativeApp) return;

    try {
        const { Haptics } = window.Capacitor.Plugins;
        if (Haptics) {
            await Haptics.impact({ style });
        }
    } catch (error) {
        console.error('Error triggering haptic:', error);
    }
}

/**
 * Open external URL in system browser
 */
async function openExternalUrl(url) {
    if (!isNativeApp) {
        window.open(url, '_blank');
        return;
    }

    try {
        const { Browser } = window.Capacitor.Plugins;
        if (Browser) {
            await Browser.open({ url });
        }
    } catch (error) {
        console.error('Error opening URL:', error);
        window.open(url, '_blank');
    }
}

// ========================================
// Account deletion — App Store / Play readiness
// ========================================

function ensureAccountDeletionControls() {
    const settings = document.getElementById('settings-content');
    if (!settings || document.getElementById('nija-account-deletion-section')) return;

    const section = document.createElement('div');
    section.className = 'section';
    section.id = 'nija-account-deletion-section';
    section.innerHTML = `
        <h3>Privacy & Account</h3>
        <div class="status-card">
            <p><strong>Delete NIJA Account</strong></p>
            <p>Permanently remove your NIJA account, active sessions, NIJA-held broker credentials, and registered device tokens where applicable. This does not delete accounts held directly with your broker, Apple, Google, or other third parties.</p>
            <p>Limited records may be retained only where required for legal, tax, accounting, security, fraud-prevention, dispute-resolution, or regulatory obligations.</p>
            <button id="delete-nija-account-btn" class="btn btn-danger" type="button">Delete Account</button>
        </div>
    `;
    settings.appendChild(section);

    const button = document.getElementById('delete-nija-account-btn');
    if (button) button.addEventListener('click', requestNijaAccountDeletion);
}

async function requestNijaAccountDeletion() {
    const first = window.confirm(
        'Delete your NIJA account? This is permanent. Stop live trading and review any open broker positions before continuing.'
    );
    if (!first) return;

    const confirmation = window.prompt(
        'Type DELETE MY NIJA ACCOUNT to confirm permanent deletion.'
    );
    if (confirmation !== 'DELETE MY NIJA ACCOUNT') {
        window.alert('Account deletion cancelled. The confirmation phrase did not match.');
        return;
    }

    const token = localStorage.getItem('nija_token');
    if (!token) {
        window.alert('Please sign in again before deleting your account.');
        return;
    }

    try {
        const response = await fetch(`${window.location.origin}/api/account/deletion`, {
            method: 'DELETE',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${token}`
            },
            body: JSON.stringify({ confirmation })
        });
        const data = await response.json().catch(() => ({}));

        if (!response.ok || !data.success) {
            throw new Error(data.message || data.error || 'Deletion could not be confirmed');
        }

        localStorage.removeItem('nija_token');
        localStorage.removeItem('nija_risk_acknowledged');
        window.alert('Your NIJA account deletion request completed successfully. Third-party brokerage accounts were not deleted.');

        if (typeof window.handleLogout === 'function') {
            window.handleLogout();
        } else {
            window.location.reload();
        }
    } catch (error) {
        console.error('NIJA account deletion failed:', error);
        window.alert(`Account deletion was not confirmed: ${error.message}`);
    }
}

function scheduleAccountDeletionControls() {
    ensureAccountDeletionControls();
    const observer = new MutationObserver(() => ensureAccountDeletionControls());
    observer.observe(document.documentElement, { childList: true, subtree: true });
}

// Initialize on DOMContentLoaded
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        initializeCapacitor();
        scheduleAccountDeletionControls();
    });
} else {
    initializeCapacitor();
    scheduleAccountDeletionControls();
}

// Export for use in other scripts
window.NativeApp = NativeApp;
window.initializePushNotifications = initializePushNotifications;
window.showNativeToast = showNativeToast;
window.triggerHaptic = triggerHaptic;
window.openExternalUrl = openExternalUrl;
window.requestNijaAccountDeletion = requestNijaAccountDeletion;
