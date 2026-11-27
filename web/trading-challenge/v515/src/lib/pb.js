import PocketBase from 'pocketbase';

// Initialize PocketBase safely — if it fails, app still mounts

let pb = null;

let pbLive = null;

let pbError = null;

try {
const base = window.location.hostname.endsWith('.preview.ai-builder.ionos.com')
  ? `${window.location.origin}/.sfs-dev/`
  : `${window.location.origin}/.sfs-be/`;
pb = new PocketBase(base);
} catch (e) {
pbError = e;
console.warn("[PocketBase] Failed to initialize default client:", e.message);
throw e;
}

try {
const liveBase = `${window.location.origin}/.sfs-be/`;
pbLive = new PocketBase(liveBase);
} catch (e) {
console.warn("[PocketBase] Failed to initialize live client:", e.message);
pbLive = pb; // Fallback to default client
}

// True when `pb` talks to the PREVIEW (test) store; false when it talks to the LIVE store.
// Public forms must write through `pb` (never `pbLive`) so a preview submission can never land in LIVE data.
const isPreviewStore = typeof window !== 'undefined' && window.location.hostname.endsWith('.preview.ai-builder.ionos.com');
const storeLabel = isPreviewStore ? 'PREVIEW (test) store' : 'LIVE store';

export { pb, pbLive, pbError, isPreviewStore, storeLabel };
