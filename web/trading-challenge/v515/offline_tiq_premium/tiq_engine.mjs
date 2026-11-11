// Server-side Trading IQ scoring engine (preview/staging only, not deployed).
// Replays a submitted run against the official game rules and returns authoritative results.
// The browser's own scores are never read. Pure functions, no network, no storage.
// Rules must stay identical to src/pages/TradingIQChallenge.jsx; tiq_engine_test.mjs checks that.

export const START_CASH = 10000;
export const ROUNDS = 12;
export const CHALLENGES = 6;
export const STOP_PCT = 0.05;
export const BUY_FRACTION = 0.25;
export const TARGET = { beginner: 50, intermediate: 60, advanced: 70 };
export const LEVELS = {
  beginner: { vol: 0.7 },
  intermediate: { vol: 1 },
  advanced: { vol: 1.5 },
};
export const SCENARIOS = [
  { name: "Quiet Opening", seed: 101, drift: 0.012, vol: 0.012 },
  { name: "Earnings Surprise", seed: 202, drift: 0, vol: 0.02, shock: { at: 6, size: 0.09 } },
  { name: "Sideways Chop", seed: 303, drift: 0, vol: 0.015, mean: true },
  { name: "Sudden Sell-Off", seed: 404, drift: -0.01, vol: 0.018, shock: { at: 9, size: -0.12 } },
  { name: "Breakout Test", seed: 505, drift: 0.005, vol: 0.015, shock: { at: 5, size: 0.05 }, fake: true },
  { name: "Volatility Storm", seed: 606, drift: 0, vol: 0.035 },
];
export const MORE_SCENARIOS = [
  { name: "Rate Cut Rally", seed: 707, drift: 0.008, vol: 0.016, shock: { at: 4, size: 0.06 } },
  { name: "Slow Bleed", seed: 808, drift: -0.008, vol: 0.01 },
  { name: "Double Top Trap", seed: 909, drift: 0, vol: 0.02, shock: { at: 7, size: 0.04 }, fake: true },
];
const ALL_SCENARIOS = [...SCENARIOS, ...MORE_SCENARIOS];
const ACTIONS = ["buy", "sell", "hold"];
const MODES = ["standard", "daily"];

export function dailyList(dayNum) {
  const start = dayNum % ALL_SCENARIOS.length;
  return Array.from({ length: CHALLENGES }, (_, k) => {
    const sc = ALL_SCENARIOS[(start + k) % ALL_SCENARIOS.length];
    return { ...sc, seed: sc.seed + (dayNum % 997) * 13 };
  });
}

function rng(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function buildPrices(sc, level) {
  const rand = rng(sc.seed);
  const v = sc.vol * LEVELS[level].vol;
  const out = [100];
  for (let i = 1; i <= ROUNDS; i++) {
    const prev = out[i - 1];
    let drift = sc.drift;
    if (sc.fake && sc.shock && i > sc.shock.at) drift = -0.015;
    let next = prev * (1 + drift + v * (rand() * 2 - 1));
    if (sc.mean) next += (100 - next) * 0.35;
    if (sc.shock && sc.shock.at === i) next = prev * (1 + sc.shock.size * LEVELS[level].vol);
    out.push(Math.round(next * 100) / 100);
  }
  return out;
}

// Educational score of ONE challenge from its decisions only. Simulated return is deliberately not an input.
// (Kept for the in-game result card; the run's Trading IQ comes from scoreRun in tiq_scoring.mjs.)
import { scoreRun } from "./tiq_scoring.mjs";
export { scoreRun };

// Shape and range validation of a submitted run. Returns { ok: true, run } or { ok: false, reason }.
export function validateRun(input) {
  if (!input || typeof input !== "object" || Array.isArray(input)) return { ok: false, reason: "malformed" };
  const allowed = ["mode", "level", "dayNum", "challenges"];
  if (Object.keys(input).some((k) => !allowed.includes(k))) return { ok: false, reason: "unexpected_field" };
  if (!MODES.includes(input.mode)) return { ok: false, reason: "bad_mode" };
  if (!Object.prototype.hasOwnProperty.call(LEVELS, input.level)) return { ok: false, reason: "bad_level" };
  if (!Number.isInteger(input.dayNum) || input.dayNum < 0 || input.dayNum > 1e6) return { ok: false, reason: "bad_day" };
  if (input.mode === "standard" && input.dayNum !== 0) return { ok: false, reason: "day_on_standard" };
  if (!Array.isArray(input.challenges) || input.challenges.length !== CHALLENGES) return { ok: false, reason: "incomplete_run" };
  for (const ch of input.challenges) {
    if (!Array.isArray(ch) || ch.length !== ROUNDS) return { ok: false, reason: "incomplete_challenge" };
    for (const d of ch) {
      if (!d || typeof d !== "object" || Array.isArray(d)) return { ok: false, reason: "malformed_round" };
      if (Object.keys(d).some((k) => k !== "action" && k !== "stop")) return { ok: false, reason: "unexpected_field" };
      if (!ACTIONS.includes(d.action)) return { ok: false, reason: "bad_action" };
      if (typeof d.stop !== "boolean") return { ok: false, reason: "bad_stop" };
    }
  }
  return { ok: true, run: input };
}

// Replays one challenge round by round, mirroring the game's trade reducer exactly.
function playChallenge(sc, level, decisions) {
  const prices = buildPrices(sc, level);
  let cash = START_CASH, units = 0, cost = 0, trades = 0, peak = START_CASH, maxDD = 0, stopUsed = false;
  const history = [START_CASH];
  const rounds = [];
  for (let round = 0; round < ROUNDS; round++) {
    const d = decisions[round];
    const p0 = prices[round];
    const p1 = prices[round + 1];
    const held = units > 0;
    if (d.action === "buy") {
      const amt = cash * BUY_FRACTION;
      if (amt >= 1) { units += amt / p0; cost += amt; cash -= amt; trades += 1; }
    }
    if (d.action === "sell" && units > 0) { cash += units * p0; units = 0; cost = 0; trades += 1; }
    let stopFired = false;
    const armedWithPosition = d.stop && units > 0;
    const avg = units > 0 ? cost / units : 0;
    if (d.stop && units > 0 && p1 <= avg * (1 - STOP_PCT)) {
      cash += units * p1; units = 0; cost = 0; trades += 1; stopFired = true;
    }
    const value = cash + units * p1;
    peak = Math.max(peak, value);
    maxDD = Math.max(maxDD, (peak - value) / peak);
    stopUsed = stopUsed || armedWithPosition || stopFired;
    history.push(value);
    const prior = round === 0 ? p0 : prices[round - 1];
    rounds.push({ round: round + 1, action: d.action, held, p0, p1, stopArmed: d.stop === true, movePct: Math.round(((p1 - p0) / p0) * 1000) / 10, lastMovePct: Math.round(((p0 - prior) / prior) * 1000) / 10, stopFired, value: Math.round(value * 100) / 100, invested: Math.round(((units * p1) / value) * 10000) / 10000 });
  }
  const final = history[history.length - 1];
  return {
    final: Math.round(final * 100) / 100,
    ret: (final - START_CASH) / START_CASH,
    maxDD, trades, stopUsed,
    rounds,
  };
}

// Authoritative replay of a whole run. Browser-supplied scores are ignored.
export function replayRun(input) {
  const v = validateRun(input);
  if (!v.ok) return v;
  const list = input.mode === "daily" ? dailyList(input.dayNum) : SCENARIOS;
  const results = list.map((sc, i) => ({ name: sc.name, ...playChallenge(sc, input.level, input.challenges[i]) }));
  const scored = scoreRun(results.map((r) => ({ maxDD: r.maxDD, trades: r.trades, stopUsed: r.stopUsed, decisions: r.rounds })));
  results.forEach((r, i) => { r.score = scored.challengeScores[i]; });
  const avg = scored.iq;
  return {
    ok: true,
    summary: {
      mode: input.mode, level: input.level, dayNum: input.dayNum, avg,
      worstDD: Math.max(...results.map((r) => r.maxDD)),
      anyStop: results.some((r) => r.stopUsed),
      allLight: results.every((r) => r.trades <= 2),
      targetMet: avg >= TARGET[input.level],
      assessments: scored.assessments,
    },
    results,
  };
}
