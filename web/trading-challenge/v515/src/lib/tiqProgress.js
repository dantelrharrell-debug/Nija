// Guest progress for the Trading IQ Challenge. Stored only in this browser (localStorage).
// Fictional practice data only. Never used as proof of payment or to unlock any paid report.
export const TIQ_KEY = "nija_tiq_progress";
export const TIQ_VERSION = 1;
const LEVELS = ["beginner", "intermediate", "advanced"];
const MODES = ["standard", "daily"];
const TONES = ["good", "caution", "note"];
const MAX_RUNS = 50;
const MAX_DAYS = 400;
const MAX_TEXT = 400;

const isInt = (v, min, max) => Number.isInteger(v) && v >= min && v <= max;
const isNum = (v, min, max) => typeof v === "number" && Number.isFinite(v) && v >= min && v <= max;
const isStr = (v, max) => typeof v === "string" && v.length <= max;

// Calendar-day streak: it continues only if the last daily was today or yesterday (UTC day numbers).
export function effectiveStreak(streak, lastDaily, today) {
  return lastDaily >= today - 1 ? streak : 0;
}

const ACTIONS = ["buy", "sell", "hold"];
// Decision rows (what the player chose and the visible price signal). No personal data, no payment data.
function cleanRows(rows, max) {
  if (rows === undefined || rows === null) return [];
  if (!Array.isArray(rows) || rows.length > max) return null;
  const out = [];
  for (const d of rows) {
    if (!d || typeof d !== "object" || !isInt(d.round, 1, 12) || !ACTIONS.includes(d.action)) return null;
    if (typeof d.held !== "boolean" || typeof d.stopArmed !== "boolean") return null;
    if (!isNum(d.movePct, -100, 1000) || !isNum(d.lastMovePct, -100, 1000) || !isNum(d.invested, 0, 1)) return null;
    out.push({ round: d.round, action: d.action, held: d.held, stopArmed: d.stopArmed, movePct: d.movePct, lastMovePct: d.lastMovePct, invested: d.invested });
  }
  return out;
}

function cleanResult(r) {
  if (!r || typeof r !== "object") return null;
  if (!isStr(r.name, 80) || !isNum(r.final, 0, 1e9) || !isNum(r.ret, -1, 1000) || !isNum(r.maxDD, 0, 1)) return null;
  if (!isInt(r.trades, 0, 100000) || typeof r.stopUsed !== "boolean" || !isInt(r.score, 0, 100)) return null;
  const decisions = cleanRows(r.decisions, 12);
  if (decisions === null) return null;
  return { name: r.name, final: r.final, ret: r.ret, maxDD: r.maxDD, trades: r.trades, stopUsed: r.stopUsed, score: r.score, decisions };
}

function cleanFeedback(f) {
  if (!f || typeof f !== "object") return undefined;
  if (!TONES.includes(f.tone) || !isStr(f.head, 80) || !isStr(f.text, MAX_TEXT)) return undefined;
  return { tone: f.tone, head: f.head, text: f.text };
}

// The unfinished challenge. Prices are not stored: they are rebuilt from the fixed scenario seeds.
// Returns null unless every field is consistent. A daily challenge from another day is discarded.
function cleanRun(r, ctx) {
  if (!r || typeof r !== "object") return null;
  if (!LEVELS.includes(r.level) || !MODES.includes(r.mode)) return null;
  if (!isInt(r.dayNum, 0, 1000000)) return null;
  if (r.mode === "daily" && r.dayNum !== ctx.today) return null;
  if (!isInt(r.sIdx, 0, ctx.scenes - 1) || !isInt(r.round, 0, ctx.rounds - 1)) return null;
  if (r.phase !== "decide" && r.phase !== "reveal") return null;
  if (!isNum(r.cash, 0, 1e9) || !isNum(r.units, 0, 1e9) || !isNum(r.cost, 0, 1e9) || !isNum(r.peak, 0, 1e9)) return null;
  if (!isNum(r.maxDD, 0, 1) || !isInt(r.trades, 0, 100000)) return null;
  if (typeof r.stopOn !== "boolean" || typeof r.stopUsed !== "boolean") return null;
  if (!Array.isArray(r.history) || r.history.length !== r.round + (r.phase === "reveal" ? 2 : 1)) return null;
  if (!r.history.every((v) => isNum(v, 0, 1e9))) return null;
  if (!Array.isArray(r.results) || r.results.length !== r.sIdx) return null;
  const results = r.results.map(cleanResult);
  if (results.some((x) => x === null)) return null;
  let feedback = null;
  if (r.feedback !== null && r.feedback !== undefined) {
    feedback = cleanFeedback(r.feedback);
    if (feedback === undefined) return null;
  }
  if ((r.phase === "reveal") !== (feedback !== null)) return null;
  const rows = cleanRows(r.rows, 12);
  if (rows === null) return null;
  return {
    rows,
    mode: r.mode, level: r.level, dayNum: r.dayNum, sIdx: r.sIdx, round: r.round, phase: r.phase,
    cash: r.cash, units: r.units, cost: r.cost, trades: r.trades, peak: r.peak, maxDD: r.maxDD,
    stopOn: r.stopOn, stopUsed: r.stopUsed, history: r.history, results, feedback,
  };
}

// ctx = { badgeIds, today, scenes, rounds }. Returns a clean progress object, or null when anything is wrong.
export function parseProgress(raw, ctx) {
  try {
    if (typeof raw !== "string" || raw.length > 200000) return null;
    const d = JSON.parse(raw);
    if (!d || typeof d !== "object" || d.v !== TIQ_VERSION) return null;
    if (!LEVELS.includes(d.level) || !MODES.includes(d.mode)) return null;
    if (!isInt(d.xp, 0, 1000000) || !isInt(d.streak, 0, 100000) || !isInt(d.lastDaily, -1, 1000000)) return null;
    if (!Array.isArray(d.badges) || !Array.isArray(d.doneDays) || !Array.isArray(d.runs)) return null;
    const badges = [...new Set(d.badges.filter((b) => ctx.badgeIds.includes(b)))];
    const doneDays = [...new Set(d.doneDays.filter((n) => isInt(n, 0, 1000000)))].slice(-MAX_DAYS);
    const runs = d.runs
      .filter((r) => r && LEVELS.includes(r.level) && MODES.includes(r.mode)
        && isInt(r.avg, 0, 100) && isInt(r.xp, 0, 100000) && isInt(r.dayNum, 0, 1000000))
      .slice(-MAX_RUNS)
      .map((r) => ({ level: r.level, mode: r.mode, avg: r.avg, xp: r.xp, dayNum: r.dayNum, sv: r.sv === 2 ? 2 : 1 }));
    const inRun = d.inRun ? cleanRun(d.inRun, ctx) : null;
    return { level: d.level, mode: d.mode, xp: d.xp, streak: d.streak, lastDaily: d.lastDaily, badges, doneDays, runs, inRun };
  } catch (e) {
    return null;
  }
}

export function readProgress(ctx) {
  try {
    if (typeof window === "undefined" || !window.localStorage) return null;
    return parseProgress(window.localStorage.getItem(TIQ_KEY), ctx);
  } catch (e) {
    return null;
  }
}

// Returns true when the save worked. Storage may be full or blocked; the game keeps working either way.
export function writeProgress(s) {
  try {
    const data = {
      v: TIQ_VERSION, level: s.level, mode: s.mode, xp: s.xp, streak: s.streak, lastDaily: s.lastDaily,
      badges: s.badges, doneDays: s.doneDays.slice(-MAX_DAYS), runs: s.runs.slice(-MAX_RUNS), inRun: s.inRun ?? null,
    };
    window.localStorage.setItem(TIQ_KEY, JSON.stringify(data));
    return true;
  } catch (e) {
    return false;
  }
}

export function clearProgress() {
  try {
    window.localStorage.removeItem(TIQ_KEY);
    return true;
  } catch (e) {
    return false;
  }
}

export function hasProgress(s) {
  return s.xp > 0 || s.runs.length > 0 || s.badges.length > 0 || !!s.inRun;
}
