/**
 * Capacitor Initialization and Native Features
 * 
 * This file handles:
 * - Capacitor plugin initialization
 * - Status bar configuration
 * - Splash screen handling
 * - Push notifications setup
 * - Native device features
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

        // Get device info
        if (Device) {
            NativeApp.deviceInfo = await Device.getInfo();
            NativeApp.platform = NativeApp.deviceInfo.platform;
            console.log('Device info:', NativeApp.deviceInfo);
        }

        // Configure status bar
        if (StatusBar) {
            await StatusBar.setStyle({ style: 'DARK' });
            await StatusBar.setBackgroundColor({ color: '#0f172a' });
            console.log('Status bar configured');
        }

        // Hide splash screen after app is ready
        if (SplashScreen) {
            // Will be hidden after data loads
            window.addEventListener('load', async () => {
                setTimeout(async () => {
                    await SplashScreen.hide();
                }, 2000);
            });
        }

        // Configure keyboard behavior
        if (Keyboard) {
            await Keyboard.setAccessoryBarVisible({ isVisible: true });
            await Keyboard.setScroll({ isDisabled: false });
        }

        // Listen for app state changes
        if (App) {
            App.addListener('appStateChange', ({ isActive }) => {
                console.log('App state changed. Is active:', isActive);
                if (isActive && window.refreshDashboard) {
                    window.refreshDashboard();
                }
            });

            App.addListener('backButton', () => {
                console.log('Back button pressed');
                // Handle back button navigation
                if (window.handleBackButton) {
                    window.handleBackButton();
                }
            });
        }

        // Monitor network status
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

        // Trigger custom event
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

        // Request permission
        let permStatus = await PushNotifications.checkPermissions();

        if (permStatus.receive === 'prompt') {
            permStatus = await PushNotifications.requestPermissions();
        }

        if (permStatus.receive !== 'granted') {
            console.log('Push notification permission not granted');
            return;
        }

        // Register for push notifications
        await PushNotifications.register();

        // Listeners for push events
        PushNotifications.addListener('registration', (token) => {
            console.log('Push registration success, token:', token.value);
            // Send token to backend
            if (window.registerPushToken) {
                window.registerPushToken(token.value);
            }
        });

        PushNotifications.addListener('registrationError', (error) => {
            console.error('Push registration error:', error);
        });

        PushNotifications.addListener('pushNotificationReceived', (notification) => {
            console.log('Push notification received:', notification);
            // Handle notification in foreground
            if (window.handlePushNotification) {
                window.handlePushNotification(notification);
            }
        });

        PushNotifications.addListener('pushNotificationActionPerformed', (notification) => {
            console.log('Push notification action performed:', notification);
            // Handle notification tap
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

// Initialize on DOMContentLoaded
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initializeCapacitor);
} else {
    initializeCapacitor();
}

// Export for use in other scripts
window.NativeApp = NativeApp;
window.initializePushNotifications = initializePushNotifications;
window.showNativeToast = showNativeToast;
window.triggerHaptic = triggerHaptic;
window.openExternalUrl = openExternalUrl;
