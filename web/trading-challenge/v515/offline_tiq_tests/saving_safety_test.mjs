// Progress saving safety: old saves keep working, blocked storage never breaks play, nothing sensitive is stored.
// Run: node offline_tiq_tests/saving_safety_test.mjs
import { readFileSync } from "node:fs";
import { parseProgress, writeProgress, readProgress, clearProgress, TIQ_KEY } from "../src/lib/tiqProgress.js";
import { createLabStore, LAB_STORE_KEY } from "../offline_tiq_premium/tiq_lab_store.mjs";

let pass = 0, fail = 0;
const ok = (n, c) => { if (c) pass++; else { fail++; console.log("FAIL:", n); } };
const ctx = { badgeIds: ["level_clear", "advanced_clear", "improver"], today: 20000, scenes: 6, rounds: 12 };

// 1. A save written by the previous version (no decision rows, no sv field) still loads.
const old = JSON.stringify({ v: 1, level: "intermediate", mode: "standard", xp: 120, streak: 2, lastDaily: 19999, badges: ["level_clear"], doneDays: [19999],
  runs: [{ level: "intermediate", mode: "standard", avg: 71, xp: 90, dayNum: 0 }],
  inRun: { mode: "standard", level: "intermediate", dayNum: 0, sIdx: 1, round: 0, phase: "decide", cash: 10000, units: 0, cost: 0, peak: 10000, maxDD: 0, trades: 0, stopOn: false, stopUsed: false, history: [10000],
    results: [{ name: "Quiet Opening", final: 10400, ret: 0.04, maxDD: 0.05, trades: 3, stopUsed: true, score: 70 }], feedback: null } });
const p = parseProgress(old, ctx);
ok("old save loads", p !== null);
ok("old XP, badges and streak kept", p.xp === 120 && p.badges.includes("level_clear") && p.streak === 2);
ok("old run kept and marked as earlier scoring", p.runs.length === 1 && p.runs[0].avg === 71 && p.runs[0].sv === 1);
ok("old unfinished challenge resumable", p.inRun && p.inRun.sIdx === 1 && p.inRun.results.length === 1 && Array.isArray(p.inRun.rows));

// 2. New saves round-trip with decision rows.
const store = new Map();
globalThis.window = { localStorage: { getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)), removeItem: (k) => store.delete(k) } };
const row = { round: 1, action: "buy", held: false, stopArmed: true, movePct: 1.2, lastMovePct: 0, invested: 0.25 };
const state = { level: "beginner", mode: "standard", xp: 50, streak: 0, lastDaily: -1, badges: [], doneDays: [], runs: [{ level: "beginner", mode: "standard", avg: 60, xp: 50, dayNum: 0, sv: 2 }],
  inRun: { mode: "standard", level: "beginner", dayNum: 0, sIdx: 0, round: 1, phase: "decide", cash: 7500, units: 25, cost: 2500, peak: 10000, maxDD: 0, trades: 1, stopOn: false, stopUsed: true, history: [10000, 10000], results: [], feedback: null, rows: [row] } };
ok("write succeeds", writeProgress(state) === true);
const back = readProgress(ctx);
ok("round-trip keeps decision rows and score version", back && back.inRun.rows.length === 1 && back.runs[0].sv === 2);

// 3. Tampered rows are rejected (the whole unfinished challenge is dropped, not the XP).
const bad = JSON.parse(store.get(TIQ_KEY)); bad.inRun.rows[0].action = "short"; 
ok("tampered rows rejected", parseProgress(JSON.stringify(bad), ctx).inRun === null);

// 4. Blocked or full storage never throws.
globalThis.window = { localStorage: { getItem() { throw new Error("SecurityError"); }, setItem() { throw new Error("QuotaExceededError"); }, removeItem() { throw new Error("SecurityError"); } } };
ok("blocked: read null", readProgress(ctx) === null);
ok("blocked: write false, no throw", writeProgress(state) === false);
ok("blocked: clear false, no throw", clearProgress() === false);
delete globalThis.window;
ok("no window at all: read null", readProgress(ctx) === null);
ok("no window at all: write false", writeProgress(state) === false);
const dead = createLabStore({ getItem() { throw new Error("x"); }, setItem() { throw new Error("x"); }, removeItem() { throw new Error("x"); } });
ok("lab store with blocked storage: load is off and empty", dead.load().enabled === false);
ok("lab store with no storage: load is off", createLabStore(null).load().enabled === false);

// 5. Lab saving is off by default: loading a fresh browser writes nothing.
const fresh = new Map();
const labStore = createLabStore({ getItem: (k) => (fresh.has(k) ? fresh.get(k) : null), setItem: (k, v) => fresh.set(k, v), removeItem: (k) => fresh.delete(k) });
ok("lab saving off by default", labStore.load().enabled === false && fresh.size === 0);

// 6. Nothing sensitive is stored: only these keys are ever written by the game code.
const files = ["../src/lib/tiqProgress.js", "../offline_tiq_premium/tiq_lab_store.mjs"].map((f) => readFileSync(new URL(f, import.meta.url), "utf8")).join("\n");
const page = readFileSync(new URL("../src/pages/TradingIQChallenge.jsx", import.meta.url), "utf8");
const lab = readFileSync(new URL("../src/components/TiqLab.jsx", import.meta.url), "utf8");
const comps = ["TiqReport", "TiqCoach", "TiqAchievements"].map((n) => readFileSync(new URL(`../src/components/${n}.jsx`, import.meta.url), "utf8")).join("\n");
ok("no cookie/sessionStorage/IndexedDB in game code", ![files, page, lab, comps].some((s) => /document\.cookie|sessionStorage|indexedDB/.test(s)));
ok("game page and components touch storage only through guarded stores", !/localStorage/.test(page + comps) && (lab.match(/localStorage/g) || []).length === 1 && /try \{ return typeof window/.test(lab));
ok("saved fields exclude payment and personal data", !/email|card|iban|password|stripe|credential|phone|birth|name:\s*s\./i.test(files.replace(/name: r\.name[^;]*;/g, "").replace(/\/\/.*$/gm, "").replace(/"[^"]*"/g, '""')));
ok("adult declaration never saved", !/adult|declaration/i.test(files.replace(/\/\/.*$/gm, "").replace(/"[^"]*"/g, '""')));
ok("only two storage keys exist", /nija_tiq_progress/.test(files) && LAB_STORE_KEY === "nija_tiq_lab_v1");
console.log(`PASS: ${pass}, FAIL: ${fail}`);
process.exit(fail ? 1 : 0);
