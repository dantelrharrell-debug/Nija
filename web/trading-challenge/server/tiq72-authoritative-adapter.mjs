// Authoritative, offline-only Upgrade 6 adapter for the verified v515 72-decision game.
// NOT a route, migration, checkout integration, or permission to enable payments.
// Always import the approved server-side engine; never accept browser-supplied scores.
import { createHash } from 'node:crypto';
import { validateRun, replayRun, CHALLENGES, ROUNDS } from '../v515/offline_tiq_premium/tiq_engine.mjs';

export const TIQ72_DECISIONS = CHALLENGES * ROUNDS;
export const TIQ72_VERSION = 'v515-72-decisions';

export function validateTiq72Submission(input) {
  const checked = validateRun(input);
  if (!checked.ok) throw new TypeError('Invalid 72-decision run: ' + checked.reason);
  // Pin the exact input contract and prohibit caller-controlled score fields.
  const clean = {
    mode: checked.run.mode,
    level: checked.run.level,
    dayNum: checked.run.dayNum,
    challenges: checked.run.challenges.map(ch => ch.map(d => ({ action:d.action, stop:d.stop }))),
  };
  if (clean.challenges.length !== 6 || clean.challenges.some(ch => ch.length !== 12)) {
    throw new TypeError('Exactly 72 decisions required');
  }
  return clean;
}

export function scoreTiq72ServerSide(input) {
  const run = validateTiq72Submission(input);
  const result = replayRun(run);
  if (!result.ok || result.results?.length !== CHALLENGES ||
      result.results.some(ch => ch.rounds?.length !== ROUNDS)) {
    throw new TypeError('Authoritative 72-decision replay failed');
  }
  const runDigest = createHash('sha256').update(JSON.stringify(run)).digest('hex');
  return {
    version: TIQ72_VERSION,
    runDigest,
    validatedDecisions: TIQ72_DECISIONS,
    run,
    score: result.summary.avg,
    summary: result.summary,
    results: result.results,
    disclaimer: 'Educational simulation only; not investment advice or a prediction of returns.',
  };
}
