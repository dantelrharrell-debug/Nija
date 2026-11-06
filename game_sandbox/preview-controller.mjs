// Client orchestration only. Every report still requires server ownership,
// a signed paid entitlement, and a fresh provider refund/dispute readback.
import {SandboxReportClient} from './client.mjs';

export class PreviewReportController {
  constructor(client = new SandboxReportClient()) {
    this.client = client;
    this.pending = null;
  }
  exclusive(operation) {
    if (this.pending) return this.pending;
    this.pending = Promise.resolve().then(operation).finally(() => { this.pending = null; });
    return this.pending;
  }
  purchase(game, adultConfirmed) {
    return this.exclusive(async () => {
      // Validate before creating even an unpaid run. Never persist free youth play.
      if (adultConfirmed !== true) throw Error('adult_confirmation_required');
      if (game?.screen !== 'done' || game?.restored || game?.decLog?.length !== 72)
        throw Error('complete_72_decisions_first');
      // Freeze selections before awaiting network responses or a React update.
      const completed = {
        mode: game.mode, level: game.level, dayNum: game.dayNum,
        decisions: game.decLog.map(({action, stop}) => ({action, stop}))
      };
      if (!this.client.runId) {
        if (!await this.client.resumeSaved()) await this.client.start(true);
      }
      // Repeat only the exact immutable history. An older saved purchase must
      // be reopened; a mismatch must never cause a replacement run or charge.
      await this.client.completePublishedGame(completed);
      const checkout = await this.client.checkout();
      const target = new URL(checkout.url);
      if (target.protocol !== 'https:' || target.hostname !== 'checkout.stripe.com'
          || target.username || target.password || target.port)
        throw Error('unexpected_checkout');
      return target.href;
    });
  }
  reopen(runId) {
    return this.exclusive(async () => {
      if (runId) await this.client.resume(runId);
      else if (!this.client.runId && !await this.client.resumeSaved())
        throw Error('ownership_recovery_required');
      // Pending, cancelled, refunded and lost-session cases NEVER create Checkout.
      return this.client.request(`runs/${this.client.runId}/report`);
    });
  }
}

export function returnRunId(search) {
  const params = new URLSearchParams(search);
  const ids = params.getAll('run_id');
  if (ids.length === 0) return null;
  if (ids.length !== 1 || !/^[a-f0-9]{48}$/.test(ids[0])) throw Error('invalid_run');
  return ids[0];
}

export function reportMessage(error) {
  const code = error?.message;
  if (code === 'verified_webhook_required')
    return 'Payment confirmation is pending. Retry opening your report; do not pay again.';
  if (['ownership_required', 'ownership_recovery_required'].includes(code))
    return 'Use the original browser with its cookies. If access was lost, contact support; do not pay again.';
  if (code === 'run_is_immutable')
    return 'A previous report is saved in this browser. Reopen that report; no new payment was started.';
  return 'The report is locked or temporarily unavailable. Retry opening it or contact support; do not pay again.';
}
