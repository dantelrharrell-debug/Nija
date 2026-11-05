// Same-origin adapter for the EXISTING IONOS report UI. No fake game/report.
// Install only on isolated staging after canonical source/parity verification.
// A saved run ID is NOT an access credential: the server requires the private
// HttpOnly ownership cookie and a verified paid entitlement for report access.
const LAST_RUN = 'nija-iq-sandbox-last-run-v1';
const validId = value => typeof value === 'string' && /^[a-f0-9]{48}$/.test(value);

function remember(runId) {
  if (!validId(runId)) return;
  try { globalThis.localStorage?.setItem(LAST_RUN, runId); }
  catch { /* Storage blocked or private mode. The run remains usable in this tab. */ }
}
export class SandboxReportClient {
  constructor() { this.runId = null; this.csrf = null; }
  async request(path, method = 'GET', body) {
    const response = await fetch('/sandbox/' + path, {
      method, credentials: 'same-origin', cache: 'no-store', redirect: 'error',
      headers: { 'Content-Type': 'application/json', ...(this.csrf ? { 'X-NIJA-CSRF': this.csrf } : {}) },
      ...(body === undefined ? {} : { body: JSON.stringify(body) })
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'sandbox_unavailable');
    return data;
  }
  async start(adultConfirmed) {
    const run = await this.request('runs', 'POST', { adultConfirmed });
    if (!validId(run.run_id) || !/^[a-f0-9]{64}$/.test(run.csrf)) throw new Error('invalid_run_receipt');
    this.runId = run.run_id; this.csrf = run.csrf;
    remember(run.run_id);
    return run.run_id;
  }
  async resume(runId) {
    if (!validId(runId)) throw new Error('invalid_run');
    const run = await this.request('runs/' + runId + '/resume', 'POST', {});
    if (run.run_id !== runId || !/^[a-f0-9]{64}$/.test(run.csrf)) throw new Error('invalid_run_receipt');
    this.runId = run.run_id; this.csrf = run.csrf;
    remember(runId);
    return runId;
  }
  savedRunId() {
    try {
      const value = globalThis.localStorage?.getItem(LAST_RUN);
      return validId(value) ? value : null;
    } catch { return null; }
  }
  async resumeSaved() {
    const id = this.savedRunId();
    if (!id) return false;
    // Never bypass the server ownership check or create a replacement Checkout.
    await this.resume(id);
    return true;
  }
  clearSavedRun() {
    try { globalThis.localStorage?.removeItem(LAST_RUN); } catch { /* Unavailable storage */ }
    this.runId = null; this.csrf = null;
  }
  async complete(answers) {
    return this.request('runs/' + this.runId + '/complete', 'POST', { answers });
  }
  async checkout() {
    return this.request('runs/' + this.runId + '/checkout', 'POST', {});
  }
  async report() {
    // The return URL cannot unlock a report. Pending webhook => retry visibly;
    // never charge again. Server rechecks entitlement and refund/dispute state.
    return (await this.request('runs/' + this.runId + '/report')).report;
  }
}
