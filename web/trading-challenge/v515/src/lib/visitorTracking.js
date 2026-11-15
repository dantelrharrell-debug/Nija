// Standalone guest game: IONOS analytics are intentionally disconnected.
// No visitor, answer or customer data leaves the browser.
export function trackVisitorEvent() { return false; }
export function trackVisit() { return false; }
export function startCtaTracking() { return () => {}; }
export function getVisitorId() { return null; }
export function classifyCta() { return null; }
