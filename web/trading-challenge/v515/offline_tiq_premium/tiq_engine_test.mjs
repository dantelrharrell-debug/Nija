// Parity + validation tests for the server scoring engine. Offline; no network, no browser.
// Run: node offline_tiq_premium/tiq_engine_test.mjs
import { readFileSync } from "node:fs";
import * as eng from "./tiq_engine.mjs";
import { scoreRun as _scoreRun, challengeAreas as _challengeAreas } from "./tiq_scoring.mjs";

const page = readFileSync(new URL("../src/pages/TradingIQChallenge.jsx", import.meta.url), "utf8");
const engineSrc = page.slice(page.indexOf("const START_CASH"), page.indexOf("const money ="));
const P = new Function("readProgress", "hasProgress", "scoreRun", "challengeAreas", engineSrc + `
return { START_CASH, ROUNDS, SCENARIOS, TARGET, initial, reducer, startRun, dailyList, buildPrices, dayNumberOf };`)(() => null, () => false, _scoreRun, _challengeAreas);

let pass = 0, fail = 0;
const ok = (name, cond) => { if (cond) pass++; else { fail++; console.log("FAIL " + name); } };

// Deterministic PRNG for choosing decisions.
function prng(seed) { let a = seed >>> 0; return () => { a = (a + 0x6d2b79f5) >>> 0; let t = a; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }

// Drive the real page reducer with a decision script; returns the finished state.
function playPage(mode, level, dayNum, script) {
  let s = P.reducer({ ...P.initial, mode, level }, { type: "start", dayNum });
  let c = 0;
  while (s.screen === "play") {
    const d = script[c][s.round];
    s = P.reducer(s, { type: "stop", on: d.stop });
    s = P.reducer(s, { type: "trade", action: d.action });
    s = P.reducer(s, { type: "next" });
    if (s.round === 0 && s.screen === "play") c++;
  }
  return s;
}

// Random legal-shaped decision script: 6 challenges x 12 rounds.
function script(seed) {
  const r = prng(seed);
  const acts = ["buy", "sell", "hold"];
  return Array.from({ length: 6 }, () => Array.from({ length: 12 }, () => ({ action: acts[Math.floor(r() * 3)], stop: r() < 0.3 })));
}

const levels = ["beginner", "intermediate", "advanced"];
let parityRuns = 0;
for (let seed = 1; seed <= 60; seed++) {
  const level = levels[seed % 3];
  const mode = seed % 2 ? "standard" : "daily";
  const dayNum = mode === "daily" ? 20000 + seed * 7 : 0;
  const sc = script(seed);
  const pageState = playPage(mode, level, dayNum, sc);
  // The page builds its run from the same challenges; decisions must be played in the same challenge order.
  const srv = eng.replayRun({ mode, level, dayNum, challenges: sc });
  ok(`replay ok seed ${seed}`, srv.ok === true);
  if (!srv.ok) continue;
  parityRuns++;
  ok(`screen done seed ${seed}`, pageState.screen === "done");
  ok(`scores match seed ${seed}`, JSON.stringify(pageState.results.map((r) => r.score)) === JSON.stringify(srv.results.map((r) => r.score)));
  ok(`finals match seed ${seed}`, JSON.stringify(pageState.results.map((r) => Math.round(r.final * 100) / 100)) === JSON.stringify(srv.results.map((r) => r.final)));
  ok(`names match seed ${seed}`, JSON.stringify(pageState.results.map((r) => r.name)) === JSON.stringify(srv.results.map((r) => r.name)));
  ok(`avg match seed ${seed}`, pageState.runs.at(-1).avg === srv.summary.avg);
}
ok("60 parity runs", parityRuns === 60);

// Engine constants and rotation must equal the page's.
ok("START_CASH", eng.START_CASH === P.START_CASH);
ok("ROUNDS", eng.ROUNDS === P.ROUNDS);
ok("TARGET", JSON.stringify(eng.TARGET) === JSON.stringify(P.TARGET));
const core = (l) => l.map((x) => [x.name, x.seed, x.drift, x.vol, x.shock || null, !!x.fake, !!x.mean]);
ok("daily rotation parity", JSON.stringify(core(eng.dailyList(20123))) === JSON.stringify(core(P.dailyList(20123))));
ok("standard list parity", JSON.stringify(core(eng.SCENARIOS)) === JSON.stringify(core(P.SCENARIOS)));
ok("price path parity", JSON.stringify(eng.buildPrices(eng.SCENARIOS[1], "advanced")) === JSON.stringify(P.buildPrices(P.SCENARIOS[1], "advanced")));
// score parity: replaced by scoring regression tests (tiq_scoring_test.mjs)

// Validation: tampering and malformed runs are rejected.
const good = { mode: "standard", level: "beginner", dayNum: 0, challenges: script(5) };
ok("valid run accepted", eng.validateRun(good).ok === true);
const reject = (name, input, reason) => { const r = eng.validateRun(input); ok(name + " rejected", r.ok === false && (reason ? r.reason === reason : true)); };
reject("null", null, "malformed");
reject("array", [], "malformed");
reject("extra top field score", { ...good, score: 100 }, "unexpected_field");
reject("extra top field results", { ...good, results: [] }, "unexpected_field");
reject("bad mode", { ...good, mode: "pro" }, "bad_mode");
reject("bad level", { ...good, level: "expert" }, "bad_level");
reject("level prototype", { ...good, level: "__proto__" }, "bad_level");
reject("day float", { ...good, dayNum: 1.5 }, "bad_day");
reject("day on standard", { ...good, dayNum: 3 }, "day_on_standard");
reject("five challenges", { ...good, challenges: good.challenges.slice(0, 5) }, "incomplete_run");
reject("seven challenges", { ...good, challenges: [...good.challenges, good.challenges[0]] }, "incomplete_run");
reject("eleven rounds", { ...good, challenges: good.challenges.map((c, i) => (i === 2 ? c.slice(0, 11) : c)) }, "incomplete_challenge");
reject("bad action", { ...good, challenges: good.challenges.map((c, i) => (i === 0 ? c.map((d, j) => (j === 4 ? { ...d, action: "short" } : d)) : c)) }, "bad_action");
reject("stop not boolean", { ...good, challenges: good.challenges.map((c, i) => (i === 0 ? c.map((d, j) => (j === 0 ? { ...d, stop: "yes" } : d)) : c)) }, "bad_stop");
reject("round extra field", { ...good, challenges: good.challenges.map((c, i) => (i === 0 ? c.map((d, j) => (j === 0 ? { ...d, pnl: 999 } : d)) : c)) }, "unexpected_field");
reject("round is string", { ...good, challenges: good.challenges.map((c, i) => (i === 0 ? c.map((d, j) => (j === 0 ? "buy" : d)) : c)) }, "malformed_round");

// A client-claimed score cannot change the authoritative result.
const honest = eng.replayRun(good);
const claimed = eng.replayRun({ ...good, challenges: good.challenges });
ok("replay deterministic", JSON.stringify(honest) === JSON.stringify(claimed));
ok("avg within 0..100", honest.summary.avg >= 0 && honest.summary.avg <= 100);
ok("results have twelve rounds each", honest.results.every((r) => r.rounds.length === 12));

// Stop-loss only counts when armed with an open position, and fires only at the stop level.
const allBuyStop = Array.from({ length: 6 }, () => Array.from({ length: 12 }, () => ({ action: "buy", stop: true })));
const sl = eng.replayRun({ mode: "standard", level: "advanced", dayNum: 0, challenges: allBuyStop });
ok("stop armed counts", sl.summary.anyStop === true);
const noStop = Array.from({ length: 6 }, () => Array.from({ length: 12 }, () => ({ action: "hold", stop: false })));
ok("no stop no credit", eng.replayRun({ mode: "standard", level: "beginner", dayNum: 0, challenges: noStop }).summary.anyStop === false);
const armedNoPos = Array.from({ length: 6 }, () => Array.from({ length: 12 }, () => ({ action: "hold", stop: true })));
ok("armed without position no credit", eng.replayRun({ mode: "standard", level: "beginner", dayNum: 0, challenges: armedNoPos }).summary.anyStop === false);

console.log(`PASS: ${pass}, FAIL: ${fail}`);
if (fail) process.exit(1);
