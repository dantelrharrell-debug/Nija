// Offline integration tests for the Trading IQ Challenge: real game logic (sliced from the page source),
// real guest-progress module, mock browser storage. No network, no browser. Run: node offline_tiq_tests/game_integration_test.mjs
import { readFileSync } from "node:fs";
import { scoreRun as _scoreRun, challengeAreas as _challengeAreas } from "../offline_tiq_premium/tiq_scoring.mjs";

const page = readFileSync(new URL("../src/pages/TradingIQChallenge.jsx", import.meta.url), "utf8");
const progSrc = readFileSync(new URL("../src/lib/tiqProgress.js", import.meta.url), "utf8");
const prog = await import("data:text/javascript," + encodeURIComponent(progSrc));
const engineSrc = page.slice(page.indexOf("const START_CASH"), page.indexOf("const money ="));

const TODAY = 20000;
const store = new Map();
const mockStorage = {
  getItem: (k) => (store.has(k) ? store.get(k) : null),
  setItem: (k, v) => store.set(k, String(v)),
  removeItem: (k) => store.delete(k),
};
globalThis.window = { localStorage: mockStorage };

const E = new Function("readProgress", "hasProgress", "scoreRun", "challengeAreas", engineSrc + `
return { START_CASH, ROUNDS, SCENARIOS, BADGES, TARGET, initial, reducer, initialWithSaved, snapshotOf,
  buildPrices, dailyList, judge, challengeScore, finishRun, startRun, dayNumberOf };`)(
  (ctx) => prog.readProgress({ ...ctx, today: TODAY }),
  prog.hasProgress,
  _scoreRun, _challengeAreas,
);
const { reducer, initial, initialWithSaved, snapshotOf, buildPrices, dailyList, judge, challengeScore } = E;

let pass = 0;
let fail = 0;
const ok = (name, cond) => { if (cond) pass++; else { fail++; console.log("FAIL " + name); } };
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

// Play rounds (trade then next). pick(s) returns "buy" | "sell" | "hold". Stops after maxRounds rounds.
const play = (s, pick, maxRounds = Infinity) => {
  let n = 0;
  while (s.screen === "play" && n < maxRounds) {
    s = reducer(s, { type: "trade", action: pick(s) });
    s = reducer(s, { type: "next" });
    n++;
  }
  return s;
};
const pickMix = (s) => (s.round % 3 === 0 ? "buy" : "hold");
const pickHold = () => "hold";
// What the page writes for an unfinished challenge (mirrors the save effect).
const saveState = (s) => prog.writeProgress(s.screen === "play" ? { ...s, inRun: snapshotOf(s) } : s);
const restoreState = () => initialWithSaved();
const freshStore = () => store.clear();

// 1. Fresh visitor
freshStore();
let s0 = restoreState();
ok("fresh visitor starts on intro, nothing restored", s0.screen === "intro" && s0.restored === false && s0.xp === 0);

// 2. Full standard run, then results are consistent
let s = reducer(s0, { type: "start", dayNum: TODAY });
s = play(s, pickMix);
ok("standard run ends on results screen", s.screen === "done");
ok("standard run records one run and six results", s.runs.length === 1 && s.results.length === 6);
ok("standard XP = average + 10 + 20 per new badge", s.lastXp === s.runs[0].avg + 10 + 20 * s.lastEarned.length && s.xp === s.lastXp);
ok("standard run does not change daily streak", s.streak === 0 && s.doneDays.length === 0);
saveState(s);
const afterRun = restoreState();
ok("finished run survives a refresh (XP, runs, badges)", afterRun.xp === s.xp && afterRun.runs.length === 1 && same(afterRun.badges, s.badges));
ok("finished run does not restore an unfinished challenge", afterRun.inRun === null && afterRun.restored === true);

// 3. Today's challenge: daily XP and streak
freshStore();
let d = reducer(initial, { type: "setMode", mode: "daily" });
d = reducer(d, { type: "start", dayNum: TODAY });
d = play(d, pickHold);
ok("daily run awards average + 15 + badges", d.lastXp === d.runs[0].avg + 15 + 20 * d.lastEarned.length);
ok("daily run records today and streak 1", same(d.doneDays, [TODAY]) && d.streak === 1 && d.lastDaily === TODAY);
ok("daily_regular badge earned", d.badges.includes("daily_regular"));

// 4. Replay the same day: no duplicate daily XP, no duplicate badges, no streak change
const xpBefore = d.xp;
let r2 = reducer(d, { type: "start", dayNum: TODAY });
r2 = play(r2, pickHold);
ok("replay of today's challenge awards 0 XP", r2.lastXp === 0 && r2.xp === xpBefore);
ok("replay keeps one done day and streak", r2.doneDays.length === 1 && r2.streak === 1);
ok("replay does not duplicate badges", new Set(r2.badges).size === r2.badges.length);
ok("replay still records the practice run", r2.runs.length === 2);

// 5. Streak continuity across calendar days
freshStore();
let t = reducer(initial, { type: "setMode", mode: "daily" });
t = play(reducer(t, { type: "start", dayNum: TODAY }), pickHold);
t = play(reducer(t, { type: "start", dayNum: TODAY + 1 }), pickHold);
ok("consecutive days build the streak", t.streak === 2 && prog.effectiveStreak(t.streak, t.lastDaily, TODAY + 1) === 2);
ok("streak shows 0 after a missed day", prog.effectiveStreak(t.streak, t.lastDaily, TODAY + 3) === 0);
t = play(reducer(t, { type: "start", dayNum: TODAY + 4 }), pickHold);
ok("streak restarts at 1 after a gap", t.streak === 1);

// 6. Interrupted challenge survives a refresh and resumes identically
freshStore();
let m = reducer(initial, { type: "start", dayNum: TODAY });
m = play(m, pickMix, 3);
ok("reached round 4 of challenge 1 before saving", m.screen === "play" && m.round === 3 && m.sIdx === 0);
saveState(m);
const back = restoreState();
ok("unfinished challenge detected after refresh", back.restored === true && back.inRun !== null && back.inRun.round === 3);
const res = reducer(back, { type: "resume" });
ok("resume returns to play at the same round", res.screen === "play" && res.round === m.round && res.sIdx === m.sIdx);
ok("resume rebuilds identical prices and history", same(res.prices, m.prices) && same(res.history, m.history) && res.cash === m.cash && res.units === m.units);
const fromResume = play(res, pickMix);
const fromOriginal = play(m, pickMix);
ok("resumed run finishes with the same score as uninterrupted run", fromResume.xp === fromOriginal.xp && fromResume.runs[0].avg === fromOriginal.runs[0].avg);

// 7. Saved during the feedback step (reveal phase)
freshStore();
let rv = reducer(initial, { type: "start", dayNum: TODAY });
rv = reducer(rv, { type: "trade", action: "buy" });
saveState(rv);
const rvBack = restoreState();
ok("reveal-phase feedback restored", rvBack.inRun && rvBack.inRun.phase === "reveal" && rvBack.inRun.feedback !== null);
const rvRes = reducer(rvBack, { type: "resume" });
ok("resumed reveal step can continue to next round", rvRes.phase === "reveal" && reducer(rvRes, { type: "next" }).round === 1);

// 8. Unfinished daily from another day is discarded
freshStore();
let old = reducer(reducer(initial, { type: "setMode", mode: "daily" }), { type: "start", dayNum: TODAY - 1 });
saveState(old);
const oldBack = restoreState();
ok("unfinished daily from yesterday is not resumed", oldBack.inRun === null);

// 9. Corrupt saved data falls back safely
freshStore();
store.set(prog.TIQ_KEY, "{not json");
const bad = restoreState();
ok("corrupt saved data starts a clean intro", bad.screen === "intro" && bad.restored === false && bad.xp === 0);

// 10. Reset and cancel
freshStore();
let rs = play(reducer(reducer(initial, { type: "setLevel", level: "advanced" }), { type: "start", dayNum: TODAY }), pickHold);
saveState(rs);
const cancelled = rs;
ok("cancel leaves progress untouched", restoreState().xp === rs.xp && cancelled.xp > 0);
prog.clearProgress();
const reset = reducer(rs, { type: "reset" });
ok("reset clears storage and XP but keeps chosen level", store.size === 0 && reset.xp === 0 && reset.runs.length === 0 && reset.badges.length === 0 && reset.level === "advanced");
ok("reset screen is intro", reset.screen === "intro");

// 11. Storage blocked: saving reports failure, clearing reports failure, game still works
const originalSet = mockStorage.setItem;
const originalRemove = mockStorage.removeItem;
mockStorage.setItem = () => { throw new Error("quota"); };
mockStorage.removeItem = () => { throw new Error("blocked"); };
ok("failed save is reported (no false 'Saved' status)", prog.writeProgress(rs) === false);
ok("failed clear is reported", prog.clearProgress() === false);
const playWhileBlocked = play(reducer(initial, { type: "start", dayNum: TODAY }), pickHold);
ok("game still completes while storage is blocked", playWhileBlocked.screen === "done");
mockStorage.setItem = originalSet;
mockStorage.removeItem = originalRemove;

// 12. Stop-loss: only counts when it is armed with a position, and fires at -5%
let sl = reducer(initial, { type: "start", dayNum: TODAY });
sl = reducer(sl, { type: "stop", on: true });
sl = reducer(sl, { type: "trade", action: "hold" });
ok("ticking stop-loss with no position does not earn stop-loss use", sl.stopUsed === false);
let sf = reducer(initial, { type: "start", dayNum: TODAY });
sf = { ...sf, prices: [100, 100, 90, ...Array(10).fill(90)] };
sf = reducer(sf, { type: "trade", action: "buy" });
sf = reducer(sf, { type: "next" });
sf = reducer(sf, { type: "stop", on: true });
sf = reducer(sf, { type: "trade", action: "hold" });
ok("stop-loss fires 5% below average and closes position", sf.units === 0 && sf.stopUsed === true && sf.feedback.head === "Stop-loss triggered");

// 13. Simulated calculations
const pA = buildPrices(E.SCENARIOS[5], "beginner");
ok("prices start at 100 with 13 points, 2 decimals", pA.length === 13 && pA[0] === 100 && pA.every((v) => Math.round(v * 100) / 100 === v));
ok("prices are deterministic for the same scenario and level", same(pA, buildPrices(E.SCENARIOS[5], "beginner")));
const range = (p) => Math.max(...p) - Math.min(...p);
ok("advanced swings are larger than beginner on the same scenario", range(buildPrices(E.SCENARIOS[5], "advanced")) > range(pA));
ok("challenge score ignores simulated return", challengeScore({ maxDD: 0.1, trades: 3, stopUsed: true, final: 1, ret: -0.99, decisions: [{ round: 2, action: "hold", held: false, stopArmed: false, movePct: 1, lastMovePct: 1, invested: 0 }] }) === challengeScore({ maxDD: 0.1, trades: 3, stopUsed: true, final: 1e9, ret: 99, decisions: [{ round: 2, action: "hold", held: false, stopArmed: false, movePct: 1, lastMovePct: 1, invested: 0 }] }));
ok("judge: buy then price rise is a good outcome", judge("buy", false, 100, 110, false).tone === "good");
ok("judge: stop-loss fired overrides feedback", judge("hold", true, 100, 90, true).head === "Stop-loss triggered");

// 14. Daily rotation
const dl1 = dailyList(TODAY).map((x) => x.name);
const dl2 = dailyList(TODAY + 1).map((x) => x.name);
ok("daily list has six unique challenges", new Set(dl1).size === 6 && dl1.length === 6);
ok("daily list is the same for everyone on one day and rotates next day", same(dl1, dailyList(TODAY).map((x) => x.name)) && !same(dl1, dl2));

console.log(`PASS: ${pass}, FAIL: ${fail}`);
process.exitCode = fail ? 1 : 0;
