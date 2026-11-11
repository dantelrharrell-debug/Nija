// Finish-pass checks: 6 scenarios x 12 decisions, news for every decision, scorecard from real decisions,
// resume keeps the decision log. Run: node offline_tiq_tests/finish_pass_test.mjs
import { readFileSync } from "node:fs";
import { scoreRun as _scoreRun, challengeAreas as _challengeAreas } from "../offline_tiq_premium/tiq_scoring.mjs";
const news = await import("../src/lib/tiqNews.js");
const page = readFileSync(new URL("../src/pages/TradingIQChallenge.jsx", import.meta.url), "utf8");
const prog = await import("data:text/javascript," + encodeURIComponent(readFileSync(new URL("../src/lib/tiqProgress.js", import.meta.url), "utf8")));
const store = new Map();
globalThis.window = { localStorage: { getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)), removeItem: (k) => store.delete(k) } };
const src = page.slice(page.indexOf("const START_CASH"), page.indexOf("const money ="));
const E = new Function("readProgress", "hasProgress", "scoreRun", "challengeAreas", src + "return { SCENARIOS, ROUNDS, reducer, initial, snapshotOf, dailyList };")(
  (c) => prog.readProgress({ ...c, today: 20000 }), prog.hasProgress, _scoreRun, _challengeAreas);
let pass = 0, fail = 0;
const ok = (n, c) => { if (c) pass++; else { fail++; console.log("FAIL " + n); } };

ok("six scenarios", E.SCENARIOS.length === 6);
ok("twelve rounds", E.ROUNDS === 12);
const names = ["Quiet Opening", "Earnings Surprise", "Sideways Chop", "Sudden Sell-Off", "Breakout Test", "Volatility Storm"];
ok("scenario names in order", names.every((n, i) => E.SCENARIOS[i].name === n));
let count = 0;
for (const sc of [...E.SCENARIOS, ...[707, 808, 909].map((_, i) => ({ name: ["Rate Cut Rally", "Slow Bleed", "Double Top Trap"][i] }))]) {
  for (let r = 0; r < 12; r++) {
    const n = news.newsFor(sc.name, r);
    ok(`news ${sc.name} ${r + 1}`, n && n.headline.length > 10 && n.lesson.length > 10 && ["confirmed", "unverified", "routine"].includes(n.kind));
    if (E.SCENARIOS.includes(sc) && n) count++;
  }
  ok("no 13th news " + sc.name, news.newsFor(sc.name, 12) === null);
}
ok("72 decisions have news", count === 72);

let s = E.reducer(E.initial, { type: "start", dayNum: 20000 });
let decisions = 0;
const acts = ["buy", "hold", "sell", "hold"];
while (s.screen === "play") {
  s = E.reducer(s, { type: "trade", action: acts[decisions % 4] });
  ok("feedback every decision", s.feedback && s.feedback.text.length > 5);
  s = E.reducer(s, { type: "next" });
  decisions++;
}
ok("72 decisions played", decisions === 72);
ok("results screen", s.screen === "done" && s.results.length === 6);
const sr = _scoreRun(s.results);
ok("run score equals scorecard iq", sr.iq === s.runs[0].avg);
ok("five areas present", Object.keys(sr.assessments).length === 5);

// resume mid-run keeps decision log of real decisions
let m = E.reducer(E.initial, { type: "start", dayNum: 20000 });
for (let i = 0; i < 30; i++) { m = E.reducer(m, { type: "trade", action: acts[i % 4] }); m = E.reducer(m, { type: "next" }); }
const log30 = m.decLog.map((d) => d.action + d.stop).join();
const saved = prog.writeProgress({ ...m, inRun: E.snapshotOf(m) });
ok("progress saved", saved === true);
const back = { ...E.initial, ...prog.readProgress({ badgeIds: [], today: 20000, scenes: 6, rounds: 12 }) };
const resumed = E.reducer(back, { type: "resume" });
ok("resume restores 30 logged decisions", resumed.decLog.length === 30 && resumed.decLog.map((d) => d.action + d.stop).join() === log30);
console.log(`PASS: ${pass}, FAIL: ${fail}`);
process.exit(fail ? 1 : 0);
