/**
 * NIJA Capacitor initialization and native features.
 *
 * Native integrations are deliberately thin: authentication remains server-side,
 * push tokens are sent only over authenticated HTTPS, and deep links are restricted
 * to NIJA-owned/configured origins before navigation.
 */

const isNativeApp = typeof window.Capacitor !== 'undefined';

const NativeApp = {
    isNative: isNativeApp,
    platform: null,
    deviceInfo: null,
    initialized: false
};

const NIJA_DEEP_LINK_HOSTS = new Set([
    'nija.app',
    'nijaaitrading.com',
    'www.nijaaitrading.com'
]);

function getAuthToken() {
    return localStorage.getItem('nija_token');
}

async function initializeCapacitor() {
    if (!isNativeApp) {
        console.log('Running as web app (not native)');
        return;
    }

    try {
        const { Capacitor } = window;
        const { Device, StatusBar, SplashScreen, App, Keyboard, Network } = Capacitor.Plugins;

        if (Device) {
            NativeApp.deviceInfo = await Device.getInfo();
            NativeApp.platform = NativeApp.deviceInfo.platform || Capacitor.getPlatform();
        }

        if (StatusBar) {
            await StatusBar.setStyle({ style: 'DARK' });
            await StatusBar.setBackgroundColor({ color: '#0f172a' });
        }

        if (SplashScreen) {
            window.addEventListener('load', async () => {
                setTimeout(async () => { await SplashScreen.hide(); }, 2000);
            });
        }

        if (Keyboard) {
            await Keyboard.setAccessoryBarVisible({ isVisible: true });
            await Keyboard.setScroll({ isDisabled: false });
        }

        if (App) {
            App.addListener('appStateChange', ({ isActive }) => {
                if (isActive && window.refreshDashboard) window.refreshDashboard();
            });
            App.addListener('backButton', () => {
                if (window.handleBackButton) window.handleBackButton();
            });
            App.addListener('appUrlOpen', ({ url }) => handleNijaDeepLink(url));
        }

        if (Network) {
            Network.addListener('networkStatusChange', (status) => {
                if (window.handleNetworkChange) window.handleNetworkChange(status);
            });
        }

        NativeApp.initialized = true;
        window.dispatchEvent(new CustomEvent('capacitor-ready'));
    } catch (error) {
        console.error('Error initializing Capacitor:', error);
    }
}

function handleNijaDeepLink(rawUrl) {
    if (!rawUrl || typeof rawUrl !== 'string') return false;
    try {
        const parsed = new URL(rawUrl);
        const isHttpsNija = parsed.protocol === 'https:' && NIJA_DEEP_LINK_HOSTS.has(parsed.hostname);
        const isCustomScheme = parsed.protocol === 'nija:';
        if (!isHttpsNija && !isCustomScheme) {
            console.warn('Blocked untrusted deep link origin');
            return false;
        }

        let path = parsed.pathname || '/';
        if (isCustomScheme && parsed.hostname) {
            path = `/${parsed.hostname}${parsed.pathname || ''}`;
        }
        const destination = `${path}${parsed.search || ''}${parsed.hash || ''}`;
        window.history.pushState({}, '', destination);
        window.dispatchEvent(new CustomEvent('nija-deep-link', { detail: { path: destination } }));
        if (window.handleNijaRoute) window.handleNijaRoute(destination);
        return true;
    } catch (error) {
        console.warn('Rejected malformed deep link');
        return false;
    }
}

async function registerPushToken(pushToken) {
    if (!pushToken || !isNativeApp) return false;
    const token = getAuthToken();
    if (!token) {
        console.log('Deferring push-token registration until the user signs in');
        return false;
    }

    try {
        const { Capacitor } = window;
        const { Device } = Capacitor.Plugins;
        const deviceIdentity = Device && Device.getId ? await Device.getId() : null;
        const info = Device && Device.getInfo ? await Device.getInfo() : (NativeApp.deviceInfo || {});
        const deviceId = deviceIdentity && deviceIdentity.identifier
            ? deviceIdentity.identifier
            : `${Capacitor.getPlatform()}-unknown`;
        const platform = Capacitor.getPlatform();

        const response = await fetch(`${window.location.origin}/api/mobile/device/register`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${token}`
            },
            body: JSON.stringify({
                push_token: pushToken,
                platform,
                device_id: deviceId,
                device_info: {
                    model: info.model || null,
                    operating_system: info.operatingSystem || null,
                    os_version: info.osVersion || null,
                    manufacturer: info.manufacturer || null,
                    app_version: document.documentElement.dataset.appVersion || '1.0.0'
                }
            })
        });

        if (!response.ok) {
            const data = await response.json().catch(() => ({}));
            throw new Error(data.error || `HTTP ${response.status}`);
        }
        return true;
    } catch (error) {
        console.error('Push-token registration failed:', error.message);
        return false;
    }
}

async function unregisterPushToken() {
    if (!isNativeApp) return false;
    const token = getAuthToken();
    if (!token) return false;

    try {
        const { Device } = window.Capacitor.Plugins;
        const deviceIdentity = Device && Device.getId ? await Device.getId() : null;
        if (!deviceIdentity || !deviceIdentity.identifier) return false;
        const response = await fetch(`${window.location.origin}/api/mobile/device/unregister`, {
            method: 'DELETE',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${token}`
            },
            body: JSON.stringify({ device_id: deviceIdentity.identifier })
        });
        return response.ok;
    } catch (error) {
        console.error('Push-token unregister failed:', error.message);
        return false;
    }
}

async function initializePushNotifications() {
    if (!isNativeApp) return;

    try {
        const { PushNotifications } = window.Capacitor.Plugins;
        if (!PushNotifications) return;

        PushNotifications.addListener('registration', async (token) => {
            await registerPushToken(token.value);
        });
        PushNotifications.addListener('registrationError', (error) => {
            console.error('Push registration error:', error);
        });
        PushNotifications.addListener('pushNotificationReceived', (notification) => {
            if (window.handlePushNotification) window.handlePushNotification(notification);
        });
        PushNotifications.addListener('pushNotificationActionPerformed', (notification) => {
            if (window.handlePushAction) window.handlePushAction(notification);
        });

        let permStatus = await PushNotifications.checkPermissions();
        if (permStatus.receive === 'prompt') {
            permStatus = await PushNotifications.requestPermissions();
        }
        if (permStatus.receive !== 'granted') return;
        await PushNotifications.register();
    } catch (error) {
        console.error('Error initializing push notifications:', error);
    }
}

async function showNativeToast(message, duration = 'short') {
    if (!isNativeApp) {
        console.log('Toast (web):', message);
        return;
    }
    try {
        const { Toast } = window.Capacitor.Plugins;
        if (Toast) await Toast.show({ text: message, duration, position: 'bottom' });
    } catch (error) {
        console.error('Error showing toast:', error);
    }
}

async function triggerHaptic(style = 'medium') {
    if (!isNativeApp) return;
    try {
        const { Haptics } = window.Capacitor.Plugins;
        if (Haptics) await Haptics.impact({ style });
    } catch (error) {
        console.error('Error triggering haptic:', error);
    }
}

async function openExternalUrl(url) {
    if (!isNativeApp) {
        window.open(url, '_blank', 'noopener,noreferrer');
        return;
    }
    try {
        const { Browser } = window.Capacitor.Plugins;
        if (Browser) await Browser.open({ url });
    } catch (error) {
        console.error('Error opening URL:', error);
    }
}

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
            <p>Permanently remove your NIJA account, active sessions, NIJA-held broker credentials, registered device tokens, permissions, and saved trading rules. This does not delete accounts held directly with your broker, Apple, Google, or other third parties.</p>
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

    const confirmation = window.prompt('Type DELETE MY NIJA ACCOUNT to confirm permanent deletion.');
    if (confirmation !== 'DELETE MY NIJA ACCOUNT') {
        window.alert('Account deletion cancelled. The confirmation phrase did not match.');
        return;
    }

    const token = getAuthToken();
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
        window.alert('Your NIJA account deletion completed successfully. Third-party brokerage accounts were not deleted.');
        if (typeof window.handleLogout === 'function') window.handleLogout();
        else window.location.reload();
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

function renderBetaOfferCard(beta) {
    const select = document.getElementById('register-tier');
    if (!select) return;

    // Preserve the internal BASIC capability tier expected by the legacy form,
    // but remove that implementation detail from customer-facing registration.
    select.value = 'basic';
    const legacyGroup = select.closest('.form-group');
    if (!legacyGroup) return;

    legacyGroup.style.display = 'none';
    let card = document.getElementById('nija-commercial-offer-card');
    if (!card) {
        card = document.createElement('div');
        card.id = 'nija-commercial-offer-card';
        card.className = 'status-card';
        legacyGroup.insertAdjacentElement('afterend', card);
    }

    const current = beta && beta.current_offer ? beta.current_offer : null;
    const founding = current && current.code === 'founding_beta';
    const amount = current && Number.isFinite(Number(current.amount_usd))
        ? Number(current.amount_usd)
        : (founding ? 50 : 75);
    const remaining = beta && Number.isFinite(Number(beta.founding_remaining))
        ? Number(beta.founding_remaining)
        : null;

    if (founding || !current) {
        const remainingText = remaining === null ? '' : `<p><strong>${remaining}</strong> founding beta spots currently remain.</p>`;
        card.innerHTML = `
            <h3>NIJA Founding Beta</h3>
            <p><strong>14 days free, then $${amount.toFixed(0)}/month.</strong></p>
            <p>Available to the first 100 eligible beta users. Your assigned founding offer is preserved with your account.</p>
            ${remainingText}
            <p><small>NIJA Lessons are a separate $99 one-time educational purchase. Trading involves risk; no profit or performance is guaranteed.</small></p>
        `;
    } else {
        card.innerHTML = `
            <h3>NIJA Beta</h3>
            <p><strong>$${amount.toFixed(0)}/month.</strong></p>
            <p>The first 100 founding beta spots have been claimed. New beta registrations use the current $75/month offer.</p>
            <p><small>NIJA Lessons are a separate $99 one-time educational purchase. Planned full mobile paid release price is $99/month. Trading involves risk; no profit or performance is guaranteed.</small></p>
        `;
    }
}

async function ensureCommercialPricingControls() {
    const select = document.getElementById('register-tier');
    if (!select) return;

    // Hide stale access-tier marketing immediately, even if the pricing API is
    // temporarily unavailable. Server-side registration still enforces BASIC.
    renderBetaOfferCard({
        current_offer: { code: 'founding_beta', amount_usd: 50 },
        founding_remaining: null
    });

    try {
        const response = await fetch(`${window.location.origin}/api/commercial/pricing`, {
            headers: { 'Accept': 'application/json' }
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();
        renderBetaOfferCard(data.beta || null);
    } catch (error) {
        console.warn('Using safe beta pricing fallback until pricing API is reachable:', error.message);
    }
}

function scheduleCommercialPricingControls() {
    ensureCommercialPricingControls();
    const observer = new MutationObserver(() => {
        if (!document.getElementById('nija-commercial-offer-card')) {
            ensureCommercialPricingControls();
        }
    });
    observer.observe(document.documentElement, { childList: true, subtree: true });
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        initializeCapacitor();
        scheduleAccountDeletionControls();
        scheduleCommercialPricingControls();
    });
} else {
    initializeCapacitor();
    scheduleAccountDeletionControls();
    scheduleCommercialPricingControls();
}

window.NativeApp = NativeApp;
window.initializePushNotifications = initializePushNotifications;
window.registerPushToken = registerPushToken;
window.unregisterPushToken = unregisterPushToken;
window.handleNijaDeepLink = handleNijaDeepLink;
window.showNativeToast = showNativeToast;
window.triggerHaptic = triggerHaptic;
window.openExternalUrl = openExternalUrl;
window.requestNijaAccountDeletion = requestNijaAccountDeletion;
window.ensureCommercialPricingControls = ensureCommercialPricingControls;
