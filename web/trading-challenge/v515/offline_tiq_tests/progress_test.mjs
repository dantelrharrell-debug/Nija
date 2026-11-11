// Offline tests for guest progress saving (no network, no browser). Run: node offline_tiq_tests/progress_test.mjs
import { readFileSync } from "node:fs";

const src = readFileSync(new URL("../src/lib/tiqProgress.js", import.meta.url), "utf8");
const m = await import("data:text/javascript," + encodeURIComponent(src));
const { parseProgress, effectiveStreak, writeProgress, readProgress, clearProgress, hasProgress, TIQ_KEY } = m;

let pass = 0;
let fail = 0;
const ok = (name, cond) => { if (cond) pass++; else { fail++; console.log("FAIL " + name); } };

const ctx = { badgeIds: ["first_run", "daily_regular"], today: 100, scenes: 6, rounds: 12 };
const base = {
  v: 1, level: "beginner", mode: "standard", xp: 120, streak: 2, lastDaily: 99,
  badges: ["first_run", "bogus"], doneDays: [98, 99, 99],
  runs: [{ level: "beginner", mode: "standard", avg: 55, xp: 65, dayNum: 99, extra: "x" }],
};
const result = { name: "Quiet Opening", final: 10100, ret: 0.01, maxDD: 0.02, trades: 2, stopUsed: false, score: 60 };
const goodRun = {
  mode: "daily", level: "intermediate", dayNum: 100, sIdx: 1, round: 2, phase: "reveal",
  cash: 2500, units: 10, cost: 2400, trades: 3, peak: 10000, maxDD: 0.05, stopOn: true, stopUsed: false,
  history: [10000, 9900, 9950, 10010], results: [result], feedback: { tone: "good", head: "Steady", text: "ok" },
};
const parse = (obj) => parseProgress(typeof obj === "string" ? obj : JSON.stringify(obj), ctx);

// Valid data and cleanup
let p = parse({ ...base, inRun: goodRun });
ok("valid parses", p !== null);
ok("unknown badge dropped", p && p.badges.length === 1 && p.badges[0] === "first_run");
ok("doneDays deduplicated", p && p.doneDays.join() === "98,99");
ok("valid unfinished run kept", p && p.inRun && p.inRun.round === 2 && p.inRun.phase === "reveal");
ok("run keeps feedback", p && p.inRun && p.inRun.feedback.head === "Steady");
ok("run has no stored prices", p && p.inRun && !("prices" in p.inRun));
ok("runs trimmed to safe fields", p && p.runs.length === 1 && !("extra" in p.runs[0]));

// Invalid whole progress
ok("empty string rejected", parse("") === null);
ok("non-JSON rejected", parse("{nope") === null);
ok("wrong version rejected", parse({ ...base, v: 2 }) === null);
ok("bad level rejected", parse({ ...base, level: "expert" }) === null);
ok("negative xp rejected", parse({ ...base, xp: -5 }) === null);
ok("fractional xp rejected", parse({ ...base, xp: 1.5 }) === null);
ok("oversized text rejected", parse("x".repeat(200001)) === null);
ok("non-array badges rejected", parse({ ...base, badges: "first_run" }) === null);

// Invalid unfinished run: progress is kept, only the run is discarded
const keepsProgress = (run) => {
  const r = parse({ ...base, inRun: run });
  return r !== null && r.inRun === null && r.xp === 120;
};
ok("yesterday's daily run discarded", keepsProgress({ ...goodRun, dayNum: 99 }));
ok("history length mismatch discarded", keepsProgress({ ...goodRun, history: [10000, 9900] }));
ok("reveal without feedback discarded", keepsProgress({ ...goodRun, feedback: null }));
ok("decide with feedback discarded", keepsProgress({ ...goodRun, phase: "decide", history: [10000, 9900] }));
ok("results length mismatch discarded", keepsProgress({ ...goodRun, results: [] }));
ok("bad feedback tone discarded", keepsProgress({ ...goodRun, feedback: { tone: "red", head: "a", text: "b" } }));
ok("round out of range discarded", keepsProgress({ ...goodRun, round: 12, history: new Array(14).fill(10000) }));
ok("scenario out of range discarded", keepsProgress({ ...goodRun, sIdx: 6, results: new Array(6).fill(result), history: [10000, 9900, 9950, 10010] }));
ok("NaN cash discarded", keepsProgress({ ...goodRun, cash: NaN }));
ok("bad result score discarded", keepsProgress({ ...goodRun, results: [{ ...result, score: 101 }] }));
ok("standard run from any day kept", (() => {
  const r = parse({ ...base, inRun: { ...goodRun, mode: "standard", dayNum: 3 } });
  return r && r.inRun && r.inRun.mode === "standard";
})());

// Runs capped
const many = Array.from({ length: 60 }, (_, i) => ({ level: "beginner", mode: "standard", avg: 50, xp: 10, dayNum: i }));
ok("runs capped at 50", parse({ ...base, runs: many }).runs.length === 50);

// Streak across calendar days (UTC day numbers, today = 100)
ok("streak kept when last daily today", effectiveStreak(3, 100, 100) === 3);
ok("streak kept when last daily yesterday", effectiveStreak(3, 99, 100) === 3);
ok("streak lost after a gap day", effectiveStreak(3, 98, 100) === 0);
ok("streak zero when never played", effectiveStreak(0, -1, 100) === 0);

// Storage behaviour with a mock localStorage
const store = new Map();
const good = { level: "beginner", mode: "standard", xp: 40, streak: 1, lastDaily: 100, badges: ["first_run"], doneDays: [100], runs: [], inRun: null };
globalThis.window = { localStorage: { getItem: (k) => store.get(k) ?? null, setItem: (k, v) => store.set(k, String(v)), removeItem: (k) => store.delete(k) } };
ok("write succeeds", writeProgress(good) === true);
ok("saved under expected key", store.has(TIQ_KEY));
const back = readProgress(ctx);
ok("reload restores xp", back && back.xp === 40 && back.badges[0] === "first_run");
ok("reload restores level", back && back.level === "beginner");
ok("hasProgress true with xp", hasProgress(good) === true);
ok("hasProgress true with only unfinished run", hasProgress({ ...good, xp: 0, runs: [], badges: [], inRun: goodRun }) === true);
ok("hasProgress false when empty", hasProgress({ ...good, xp: 0, badges: [], runs: [], inRun: null }) === false);
ok("clear removes save", clearProgress() === true && readProgress(ctx) === null);

// Full or blocked storage never throws
globalThis.window = { localStorage: { setItem: () => { throw new Error("QuotaExceeded"); }, getItem: () => { throw new Error("blocked"); }, removeItem: () => { throw new Error("blocked"); } } };
ok("full storage: write returns false", writeProgress(good) === false);
ok("blocked storage: read returns null", readProgress(ctx) === null);
ok("blocked storage: clear returns false", clearProgress() === false);

// No browser storage at all
delete globalThis.window;
ok("no window: read returns null", readProgress(ctx) === null);
ok("no window: write returns false", writeProgress(good) === false);

console.log(`PASS: ${pass}, FAIL: ${fail}`);
process.exit(fail === 0 ? 0 : 1);
