// Same-origin adapter for the EXISTING IONOS report UI. Does not implement a new game/report.
// Install only in isolated staging after canonical source and proxy verification.
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
    this.runId = run.run_id; this.csrf = run.csrf;
    return run.run_id; // Opaque identifier only; never a payment/ownership proof.
  }
  async resume(runId) {
    if (!/^[a-f0-9]{48}$/.test(runId)) throw new Error('invalid_run');
    const run = await this.request(`runs/${runId}/resume`, 'POST', {});
    this.runId = run.run_id; this.csrf = run.csrf;
  }
  async complete(answers) {
    return this.request(`runs/${this.runId}/complete`, 'POST', { answers });
  }
  async completePublishedGame({mode, level, dayNum, decisions}) {
    if (!Array.isArray(decisions) || decisions.length !== 72) throw new Error('complete_72_decisions_first');
    // Existing game decLog entries are {action: buy|sell|hold, stop: boolean}.
    // Copy exactly those fields; no client scores, labels or report data sent.
    const challenges = Array.from({length: 6}, (_, index) => decisions.slice(index * 12, (index + 1) * 12)
      .map(({action, stop}) => ({action, stop})));
    return this.complete({mode, level, dayNum: mode === 'standard' ? 0 : dayNum, challenges});
  }
  async checkout() {
    return this.request(`runs/${this.runId}/checkout`, 'POST', {});
  }
  async downloadHtml() {
    const result = (await this.request(`runs/${this.runId}/report`)).report;
    if (typeof result?.download_html !== 'string') throw new Error('download_unavailable');
    return result.download_html;
  }
  async report() {
    // A return URL cannot unlock the report. Pending webhook => retry visibly; never charge again.
    const result = (await this.request(`runs/${this.runId}/report`)).report;
    return result?.report ?? result;
  }
}
