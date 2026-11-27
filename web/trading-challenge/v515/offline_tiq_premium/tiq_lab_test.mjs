// Offline tests for the Trading IQ Practice Lab: allocation, news, risk and discipline exercises, scorecard merge,
// lab coach, lab achievements, optional browser-local store, backend client stub, UI source guards.
// No network, no storage, no browser. Run: node offline_tiq_premium/tiq_lab_test.mjs
import { readFileSync, existsSync } from "node:fs";
import {
  ALLOCATION_EXERCISES, NEWS_ITEMS, NEWS_KINDS, NEWS_RESPONSES, POSITION_EXERCISES, LOSS_EXERCISES, STOP_EXERCISES, EMOTION_EXERCISES,
  scoreAllocation, stressImpact, validateWeights, scoreNews, newsSet, scorePosition, maxUnits, scoreChoice, cleanLabResults, emptyLab,
  scoreLab, mergeScorecard, labAnswerCount, LAB_METHOD, LAB_DISCLAIMER,
} from "./tiq_lab.mjs";
import { buildLabCoach, allLabCoachWording, allCoachWording, LAB_COACH_NOTICE } from "./tiq_coach.mjs";
import { evaluateAchievements, evaluateLabAchievements, ACHIEVEMENTS, LAB_ACHIEVEMENTS } from "./tiq_achievements.mjs";
import { createLabStore, LAB_STORE_KEY, LAB_STORAGE_DISCLOSURE } from "./tiq_lab_store.mjs";
import { buildReport, SCORECARD_KEYS } from "./tiq_report.mjs";
import { ROUNDS, CHALLENGES } from "./tiq_engine.mjs";

let pass = 0, fail = 0;
const ok = (n, c) => { if (c) pass++; else { fail++; console.log("FAIL:", n); } };
const read = (p) => readFileSync(new URL(p, import.meta.url), "utf8");
const banned = /\b(returns?|profits?|profitable|gains?|earn(s|ed|ings)?|yield|reward|beat the market|guarantee[sd]?|income|winnings?)\b/i;
const deepFreeze = (o) => { Object.values(o).forEach((v) => { if (v && typeof v === "object") deepFreeze(v); }); return Object.freeze(o); };
const allNull = (s) => Object.values(s.areas).every((v) => v === null);

const A1 = "alloc_1", A2 = "alloc_2", A3 = "alloc_3";
const balanced1 = { NVA: 15, QTR: 10, HZN: 5, UTL: 30, BND: 30 };
const allTech = { NVA: 34, QTR: 33, HZN: 33 };

// 1. Allocation
ok("three allocation exercises, each with 4-5 fictional assets and 3+ groups", ALLOCATION_EXERCISES.length === 3 && ALLOCATION_EXERCISES.every((e) => e.assets.length >= 4 && new Set(e.assets.map((a) => a.cluster)).size >= 3));
ok("every exercise stress table covers every group", ALLOCATION_EXERCISES.every((e) => e.assets.every((a) => typeof e.stress.shocks[a.cluster] === "number")));
const sBal = scoreAllocation(A1, balanced1);
ok("balanced portfolio scores 75+", sBal.ok && sBal.score >= 75);
ok("balanced portfolio: conc and cluster are full marks", sBal.conc === 100 && sBal.clus === 100);
const sTech = scoreAllocation(A1, allTech);
ok("all-technology portfolio is flagged on groups (cluster 0) and scores below 40", sTech.score < 40 && sTech.clus === 0);
ok("100% in one asset scores 0", scoreAllocation(A1, { HZN: 100 }).score === 0);
ok("three similar names is worse than a spread across groups", sTech.score < sBal.score);
ok("all cash is Not scored (null), not 0", scoreAllocation(A1, {}).score === null && /Not scored/.test(scoreAllocation(A1, {}).detail));
ok("19% invested is Not scored; 20% is scored", scoreAllocation(A1, { UTL: 19 }).score === null && scoreAllocation(A1, { UTL: 10, BND: 10 }).score !== null);
ok("cash is allowed and reported", scoreAllocation(A1, { NVA: 5, UTL: 10, BND: 10 }).cash === 75);
ok("over 100% rejected", scoreAllocation(A1, { NVA: 60, UTL: 60 }).ok === false);
ok("unknown asset, negative, fractional, string weights rejected", [{ XXX: 5 }, { NVA: -1 }, { NVA: 2.5 }, { NVA: "5" }, null, [], 5].every((w) => scoreAllocation(A1, w).ok === false));
ok("unknown exercise rejected", scoreAllocation("nope", {}).ok === false);
ok("weight above 100 for one asset rejected", validateWeights(ALLOCATION_EXERCISES[0], { NVA: 101 }).ok === false);
ok("score is integer 0..100 for a sweep of allocations", (() => { for (let i = 0; i <= 100; i += 5) for (let j = 0; j <= 100 - i; j += 5) { const r = scoreAllocation(A3, { HZN: i, GRW: j, CON: Math.min(100 - i - j, 20) }); if (r.score !== null && !(Number.isInteger(r.score) && r.score >= 0 && r.score <= 100)) return false; } return true; })());
ok("deterministic: same input same output", JSON.stringify(scoreAllocation(A2, { OLA: 20, AIR: 20, MED: 30 })) === JSON.stringify(scoreAllocation(A2, { OLA: 20, AIR: 20, MED: 30 })));
ok("two energy names stacked are flagged as one group", (() => { const r = scoreAllocation(A2, { OLA: 40, OLB: 40, MED: 20 }); return r.topCluster === "energy" && r.clus < 100; })());
const stress = stressImpact(A1, allTech);
ok("stress impact is shown as a number for display", stress && typeof stress.portfolioChangePct === "number" && stress.portfolioChangePct < 0);
ok("stress impact is never used by scoring (source guard)", !/stress/i.test(scoreAllocation.toString()) && !/stress/i.test(scoreLab.toString()) && !/stress/i.test(mergeScorecard.toString()));
ok("scoring functions never reference profit, pnl, return or gain", [scoreAllocation, scoreNews, scorePosition, scoreChoice, scoreLab, mergeScorecard].every((f) => !/profit|pnl|\.ret\b|gain|return on/i.test(f.toString())));
const savedShock = { ...ALLOCATION_EXERCISES[0].stress.shocks };
const before = scoreAllocation(A1, allTech).score;
ALLOCATION_EXERCISES[0].stress.shocks.tech = 50;
ok("score identical when the fictional stress shock is changed", scoreAllocation(A1, allTech).score === before);
Object.assign(ALLOCATION_EXERCISES[0].stress.shocks, savedShock);

// 2. News
ok("eight news items, two of each kind, all fictional-labelled with 3+ clues", NEWS_ITEMS.length === 8 && NEWS_KINDS.every((k) => NEWS_ITEMS.filter((n) => n.kind === k).length === 2) && NEWS_ITEMS.every((n) => /\(fictional\)/.test(n.headline) && n.clues.length >= 3));
ok("newsSet returns one item of each kind for any seed", [0, 1, 2, 3, 17, 99, -5, 1.9, "x", null].every((s) => { const set = newsSet(s); return set.length === 4 && NEWS_KINDS.every((k) => set.filter((n) => n.kind === k).length === 1); }));
ok("newsSet deterministic and covers all eight items across seeds 0 and 1", JSON.stringify(newsSet(4)) === JSON.stringify(newsSet(4)) && new Set([0, 1].flatMap((s) => newsSet(s).map((n) => n.id))).size === 8);
for (const it of NEWS_ITEMS) {
  const right = scoreNews(it.id, { kind: it.kind, response: "verify_first" });
  ok(`${it.id}: correct kind scores 100 for research`, right.ok && right.classification === 100 && right.correct);
  const wrongKind = NEWS_KINDS.find((k) => k !== it.kind);
  ok(`${it.id}: wrong kind scores 0 for research`, scoreNews(it.id, { kind: wrongKind, response: "verify_first" }).classification === 0);
  ok(`${it.id}: trade_now is the weakest response and never above 20`, NEWS_RESPONSES.every((r) => scoreNews(it.id, { kind: it.kind, response: r.id }).response >= scoreNews(it.id, { kind: it.kind, response: "trade_now" }).response) && scoreNews(it.id, { kind: it.kind, response: "trade_now" }).response <= 20);
  ok(`${it.id}: checking the source scores 90+`, scoreNews(it.id, { kind: it.kind, response: "verify_first" }).response >= 90);
}
ok("unverified items: small position never scores above 30", NEWS_ITEMS.filter((n) => n.kind !== "verified").every((n) => scoreNews(n.id, { kind: n.kind, response: "small_with_plan" }).response <= 30));
ok("news: bad inputs rejected", [null, {}, { kind: "x", response: "ignore" }, { kind: "rumor", response: "x" }].every((a) => scoreNews("n_rum_1", a).ok === false) && scoreNews("zzz", { kind: "rumor", response: "ignore" }).ok === false);

// 3. Risk exercises
ok("maxUnits: 25 and 66", maxUnits(POSITION_EXERCISES[0]) === 25 && maxUnits(POSITION_EXERCISES[1]) === 66);
const p = (id, u) => scorePosition(id, u);
ok("position: at the limit scores 100", p("pos_1", 25).score === 100 && p("pos_2", 66).score === 100);
ok("position: well under the limit scores 80 (safe but small)", p("pos_1", 10).score === 80);
ok("position: modestly over scores 55; far over scores lower", p("pos_1", 30).score === 55 && p("pos_1", 40).score === 25 && p("pos_1", 100).score === 0);
ok("position: bigger than the whole account scores 0", p("pos_1", 250).score === 0 && p("pos_1", 250).tooBig);
ok("position: invalid units rejected", [0, -1, 2.5, "5", null, NaN, 1e9].every((u) => p("pos_1", u).ok === false) && p("zzz", 5).ok === false);
ok("position: risk amount and ratio come from the exit, not from any result", p("pos_1", 25).riskAmount === 100 && p("pos_1", 25).ratio === 1);
ok("max loss: 0.5-2% full marks, 5% partial, 25% zero", ["p05", "p1", "p2"].every((o) => scoreChoice("loss", "loss_1", o).score === 100) && scoreChoice("loss", "loss_1", "p5").score === 55 && scoreChoice("loss", "loss_1", "p25").score === 0);
ok("stop plan: sensible 100, tight 55, wide 40, move/none 0", ["stop_1", "stop_2"].every((id) => scoreChoice("stop", id, "swing").score === 100 && scoreChoice("stop", id, "tight").score === 55 && scoreChoice("stop", id, "wide").score === 40 && scoreChoice("stop", id, "move").score === 0 && scoreChoice("stop", id, "none").score === 0));
ok("stop plan: five options in both exercises", STOP_EXERCISES.every((e) => e.options.length === 5));
ok("emotion: four exercises, each with a fully planned answer, an impulsive 0-score answer and an explanation per option", EMOTION_EXERCISES.length === 4 && EMOTION_EXERCISES.every((e) => e.options.some((o) => o.score === 100) && e.options.some((o) => o.score === 0) && e.options.every((o) => e.why[o.id])));
ok("choice: bad ids rejected", scoreChoice("emotion", "emo_1", "zzz").ok === false && scoreChoice("nope", "emo_1", "plan").ok === false && scoreChoice("emotion", "zzz", "plan").ok === false);
ok("loss exercise has an explanation for each option", LOSS_EXERCISES.every((e) => e.options.every((o) => e.why[o.id])));

// 4. Lab scores and scorecard merge
const full = {
  allocation: { alloc_1: balanced1, alloc_2: { OLA: 20, AIR: 20, MED: 30, OLB: 5 }, alloc_3: { HZN: 10, GRW: 10, CON: 25, INF: 25, SHB: 30 } },
  news: Object.fromEntries(newsSet(0).map((n) => [n.id, { kind: n.kind, response: "verify_first" }])),
  position: { pos_1: 25, pos_2: 60 }, loss: { loss_1: "p1" }, stop: { stop_1: "swing", stop_2: "swing" },
  emotion: { emo_1: "plan", emo_2: "wait", emo_3: "keep", emo_4: "exit" },
};
const none = scoreLab({});
ok("empty lab: every area null, zero evidence", allNull(none) && Object.values(none.evidence).every((n) => n === 0));
ok("scoreLab never throws on junk", [undefined, null, 5, "x", [], { allocation: 5 }, { news: { n_rum_1: 5 } }].every((j) => allNull(scoreLab(j))));
const sc = scoreLab(full);
ok("complete lab: all four areas scored 0..100 integers", ["risk", "research", "discipline", "diversification"].every((k) => Number.isInteger(sc.areas[k]) && sc.areas[k] >= 0 && sc.areas[k] <= 100));
ok("complete lab with careful answers: research 100, risk 90+, discipline 90+", sc.areas.research === 100 && sc.areas.risk >= 90 && sc.areas.discipline >= 90);
ok("no allocation: diversification null while others scored", (() => { const r = scoreLab({ ...full, allocation: {} }); return r.areas.diversification === null && r.areas.research === 100; })());
ok("only an all-cash allocation: diversification stays null", scoreLab({ allocation: { alloc_1: {} } }).areas.diversification === null);
ok("only news answers: risk and diversification null", (() => { const r = scoreLab({ news: full.news }); return r.areas.risk === null && r.areas.diversification === null && r.areas.research === 100 && r.areas.discipline !== null; })());
ok("extra profit/pnl fields are dropped and never change a score", (() => { const dirty = { ...full, profit: 99999, pnl: { alloc_1: 1e6 } }; return JSON.stringify(scoreLab(dirty)) === JSON.stringify(sc) && !("profit" in cleanLabResults(dirty)) && !("pnl" in cleanLabResults(dirty)); })());
ok("cleanLabResults drops invalid answers and keeps valid", (() => { const c = cleanLabResults({ allocation: { alloc_1: { NVA: 500 }, alloc_2: { OLA: 10 } }, position: { pos_1: 0, pos_2: 5 }, loss: { loss_1: "zz" }, emotion: { emo_1: "plan" } }); return !c.allocation.alloc_1 && c.allocation.alloc_2 && !c.position.pos_1 && c.position.pos_2 === 5 && !c.loss.loss_1 && c.emotion.emo_1 === "plan"; })());
ok("labAnswerCount counts valid answers only", labAnswerCount(full) === 3 + 4 + 2 + 1 + 2 + 4 && labAnswerCount({}) === 0 && labAnswerCount(null) === 0);
ok("every area has printed method text; diversification states Not scored and stress never used", ["risk", "research", "discipline", "diversification"].every((k) => LAB_METHOD[k].length > 80) && /Not scored/.test(LAB_METHOD.diversification) && /never used/.test(LAB_METHOD.diversification));

const mk = (fn) => Array.from({ length: CHALLENGES }, (_, c) => Array.from({ length: ROUNDS }, (_, r) => fn(c, r)));
const holdReport = buildReport({ mode: "standard", level: "intermediate", dayNum: 0, challenges: mk(() => ({ action: "hold", stop: false })) });
const carefulReport = buildReport({ mode: "standard", level: "intermediate", dayNum: 0, challenges: mk((c, r) => ({ action: r === 0 ? "buy" : "hold", stop: true })) });
ok("fixture: hold-only game has null diversification", holdReport.assessments.diversification.score === null);
const m0 = mergeScorecard(holdReport.assessments, scoreLab({}));
ok("merge: no evidence anywhere = Not scored for diversification", m0.diversification.score === null && m0.diversification.band === "Not scored" && /Not scored/.test(m0.diversification.detail));
ok("merge: five areas always returned", SCORECARD_KEYS.every((k) => k in m0 && "score" in m0[k] && "band" in m0[k] && "source" in m0[k]));
const m1 = mergeScorecard(holdReport.assessments, sc);
ok("merge: lab fills diversification when the game cannot", m1.diversification.score === sc.areas.diversification && m1.diversification.source === "lab");
ok("merge: lab diversification replaces the game's single-asset estimate", (() => { const m = mergeScorecard(carefulReport.assessments, sc); return carefulReport.assessments.diversification.score !== null && m.diversification.score === sc.areas.diversification && m.diversification.source === "lab"; })());
ok("merge: without lab, game's estimate is kept and labelled single-asset", (() => { const m = mergeScorecard(carefulReport.assessments, scoreLab({})); return m.diversification.source === "game" && /Single-asset/.test(m.diversification.detail); })());
ok("merge: risk/research/discipline average game and lab", (() => { const m = mergeScorecard(carefulReport.assessments, sc); return ["risk", "research", "discipline"].every((k) => { const b = carefulReport.assessments[k].score; return b === null ? m[k].source === "lab" : m[k].score === Math.round((b + sc.areas[k]) / 2) && m[k].source === "game+lab"; }); })());
ok("merge: consistency comes from the game only", mergeScorecard(carefulReport.assessments, sc).consistency.score === carefulReport.assessments.consistency.score && mergeScorecard(null, sc).consistency.score === null);
ok("merge: lab-only (no game yet) still works", (() => { const m = mergeScorecard(null, sc); return m.risk.source === "lab" && m.diversification.score !== null && m.consistency.band === "Not scored"; })());
ok("merge does not mutate its inputs", (() => { const a = deepFreeze(JSON.parse(JSON.stringify(carefulReport.assessments))); const l = deepFreeze(JSON.parse(JSON.stringify(sc))); try { mergeScorecard(a, l); return true; } catch (e) { return false; } })());
ok("merge reads only .score from game areas (profit-like fields ignored)", (() => { const a = JSON.parse(JSON.stringify(carefulReport.assessments)); a.risk.profit = 1e9; a.risk.ret = 5; return mergeScorecard(a, sc).risk.score === mergeScorecard(carefulReport.assessments, sc).risk.score; })());

// 5. Coach
const labCoach = buildLabCoach(full);
ok("lab coach notice says fixed rules, not AI-generated, not advice", /not generated by artificial intelligence/.test(LAB_COACH_NOTICE) && /not financial advice/.test(LAB_COACH_NOTICE));
ok("lab coach has one note per answered exercise", labCoach.items.length === labAnswerCount(full));
ok("lab coach wording never promises or discusses returns", allLabCoachWording().every((w) => !banned.test(w)));
ok("lab coach text of every produced item is clean", labCoach.items.every((i) => ![i.saw, i.explain, i.principle, i.alternative, ...i.extra].some((t) => banned.test(t))));
ok("existing coach wording list has no lab lines in it", allCoachWording().every((w) => !allLabCoachWording().includes(w)));
ok("lab coach for a risky allocation names the concentration problem", buildLabCoach({ allocation: { alloc_1: allTech } }).items[0].explain.includes("closer to one bet than several"));
ok("lab coach for allocation adds the not-a-prediction stress line", /not a prediction/.test(labCoach.items.find((i) => i.family === "allocation").extra[0]));
ok("lab coach for news lists the clues", labCoach.items.filter((i) => i.family === "news").every((i) => /^Clues: /.test(i.extra[0])));
ok("lab coach for wrong news type says so", buildLabCoach({ news: { n_rum_1: { kind: "verified", response: "trade_now" } } }).items[0].explain.includes("different from your choice"));
ok("lab coach for an over-limit position says to reduce size", /smaller number of units|far above/.test(buildLabCoach({ position: { pos_1: 40 } }).items[0].explain));
ok("lab coach focus is the weakest scored area", buildLabCoach({ emotion: { emo_1: "double" }, news: { n_rum_1: { kind: "rumor", response: "verify_first" } } }).focusArea === "discipline");
ok("lab coach with no answers gives a neutral prompt and no items", (() => { const c = buildLabCoach({}); return c.items.length === 0 && c.focusArea === null && /Answer a few/.test(c.focus); })());
ok("lab coach is deterministic", JSON.stringify(buildLabCoach(full)) === JSON.stringify(buildLabCoach(full)));
ok("lab coach never emits lesson links", !JSON.stringify(labCoach).includes("/academy/") && labCoach.items.every((i) => !("lesson" in i)));

// 6. Achievements
const ach = evaluateLabAchievements(full);
ok("lab achievements list every definition", ach.length === LAB_ACHIEVEMENTS.length && ach.every((a) => typeof a.earned === "boolean" && a.how));
ok("careful full lab earns all six", ach.length === 6 && ach.every((a) => a.earned));
ok("empty lab earns none", evaluateLabAchievements({}).every((a) => !a.earned));
ok("one answer is not enough for count-based achievements", evaluateLabAchievements({ news: { n_ver_1: { kind: "verified", response: "verify_first" } }, emotion: { emo_1: "plan" }, position: { pos_1: 25 }, stop: { stop_1: "swing" } }).every((a) => !a.earned));
ok("trading on news right away blocks Check Before Acting", !evaluateLabAchievements({ news: { n_rum_1: { kind: "rumor", response: "trade_now" }, n_ver_1: { kind: "verified", response: "verify_first" } } }).find((a) => a.id === "verify_first").earned);
ok("Spread Builder needs both limits", !evaluateLabAchievements({ allocation: { alloc_1: allTech } }).find((a) => a.id === "spread_builder").earned && evaluateLabAchievements({ allocation: { alloc_1: balanced1 } }).find((a) => a.id === "spread_builder").earned);
ok("an all-cash allocation never earns Spread Builder", !evaluateLabAchievements({ allocation: { alloc_1: {} } }).find((a) => a.id === "spread_builder").earned);
ok("Sized to the Limit fails when one answer is over", !evaluateLabAchievements({ position: { pos_1: 40, pos_2: 60 } }).find((a) => a.id === "sized_to_limit").earned);
ok("lab achievement wording: no prizes, money, profit; nothing rewards doing more", LAB_ACHIEVEMENTS.every((a) => !/prize|cash|\$|profit|return|gain|reward|most|more (exercises|answers)/i.test(a.name + a.how)));
ok("lab achievements use cleaned answers (profit fields ignored)", evaluateLabAchievements({ ...full, profit: 5 }).every((a) => a.earned));
ok("evaluateAchievements without lab is unchanged", evaluateAchievements(carefulReport).length === ACHIEVEMENTS.length && evaluateAchievements(null).length === 0);
ok("evaluateAchievements with lab appends the lab list", evaluateAchievements(carefulReport, null, full).length === ACHIEVEMENTS.length + LAB_ACHIEVEMENTS.length && evaluateAchievements(null, null, full).length === LAB_ACHIEVEMENTS.length);
ok("lab achievement tests never read profit, pnl or return", LAB_ACHIEVEMENTS.every((a) => !/profit|pnl|\bret\b/.test(a.test.toString())));

// 7. Browser-local store
const fake = () => { const m = new Map(); return { m, getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => { m.set(k, String(v)); }, removeItem: (k) => { m.delete(k); } }; };
const st = fake();
const store = createLabStore(st);
ok("load alone writes nothing", (() => { store.load(); return st.m.size === 0; })());
ok("fresh browser: not enabled, empty lab", (() => { const r = store.load(); return r.enabled === false && labAnswerCount(r.lab) === 0; })());
ok("save then load round-trips the answers", (() => { const saved = store.save(full); const r = store.load(); return saved === true && r.enabled && JSON.stringify(scoreLab(r.lab)) === JSON.stringify(sc); })());
ok("stored record has only version, opt-in flag and answers (no PII keys)", (() => { const d = JSON.parse(st.m.get(LAB_STORE_KEY)); return Object.keys(d).sort().join() === "lab,optIn,v" && Object.keys(d.lab).sort().join() === Object.keys(emptyLab()).sort().join() && !/email|name|phone|age|birth|card|stripe|token|password|payment/i.test(Object.keys(d).join() + Object.keys(d.lab).join()); })());
ok("save drops junk fields before writing", (() => { store.save({ ...full, email: "a@b.c", profit: 1 }); return !/a@b\.c|profit/.test(st.m.get(LAB_STORE_KEY)); })());
ok("clear removes the record", (() => { store.clear(); return st.m.size === 0 && store.load().enabled === false; })());
ok("corrupt, wrong-version, not-opted-in and oversized records are ignored", (() => {
  const bad = ["{", "null", "5", JSON.stringify({ v: 2, optIn: true, lab: full }), JSON.stringify({ v: 1, optIn: false, lab: full }), JSON.stringify({ v: 1, lab: full }), "x".repeat(60000)];
  return bad.every((b) => { const s = fake(); s.setItem(LAB_STORE_KEY, b); const r = createLabStore(s).load(); return r.enabled === false && labAnswerCount(r.lab) === 0; });
})());
ok("blocked or full storage never throws and reports failure", (() => {
  const boom = { getItem() { throw new Error("blocked"); }, setItem() { throw new Error("full"); }, removeItem() { throw new Error("blocked"); } };
  const s = createLabStore(boom);
  return s.load().enabled === false && s.save(full) === false && s.clear() === false && createLabStore(null).save(full) === false;
})());
ok("disclosure says optional, off by default, lost when browser data is cleared, no PII, never unlocks", ["optional", "off by default", "clear your browser data", "lost", "no name, email, age, payment or account", "never unlock"].every((t) => LAB_STORAGE_DISCLOSURE.includes(t)));

// 8. Backend client stub
const stub = read("../src/lib/tiqBackendClient.js");
const stubCode = stub.replace(/\/\/.*$/gm, "");
const stubMod = await import("data:text/javascript," + encodeURIComponent(stub));
const realFetch = globalThis.fetch;
let fetched = 0;
globalThis.fetch = () => { fetched++; throw new Error("network not allowed"); };
const d1 = await stubMod.fetchDaily();
const d2 = await stubMod.submitRun("abc", { mode: "standard" });
globalThis.fetch = realFetch;
ok("stub makes no network request", fetched === 0);
ok("stub returns the not_available shape", d1.ok === false && d1.reason === "not_available" && d2.ok === false && d2.reason === "not_available");
ok("stub is disabled with no origin", stubMod.BACKEND_ENABLED === false && stubMod.BACKEND_ORIGIN === null);
ok("stub exports only the two spec'd calls plus flags", Object.keys(stubMod).sort().join() === "BACKEND_ENABLED,BACKEND_ORIGIN,fetchDaily,submitRun");
ok("stub has no URLs, keys or tokens and never calls fetch", !/https?:\/\//.test(stubCode) && !/(sk_|pk_|whsec|Bearer|api[_-]?key\s*[:=]|secret\s*[:=]|password\s*[:=])/i.test(stubCode) && !/\bfetch\(/.test(stubCode));
const specText = read("./GAME_BACKEND_INTEGRATION_SPEC.md");
ok("stub names only endpoints that exist in the integration spec", /GET \/daily/.test(stub) && /POST \/runs\/:id\/submit/.test(stub) && specText.includes("GET /daily") && specText.includes("POST /runs/:id/submit"));
ok("interface doc exists and says nothing is connected", existsSync(new URL("./LAB_CLIENT_INTERFACE.md", import.meta.url)) && /not_available/.test(read("./LAB_CLIENT_INTERFACE.md")) && /no network request/i.test(read("./LAB_CLIENT_INTERFACE.md")));

// 9. UI and style guards (source level; no browser available)
const ui = read("../src/components/TiqLab.jsx");
const page = read("../src/pages/TradingIQChallenge.jsx");
const css = read("../src/index.css");
ok("lab UI imports the shared client", /tiqLabClient\.js/.test(ui));
ok("lab UI never touches browser storage directly (uses the injected store)", !/sessionStorage|document\.cookie/.test(ui) && /createLabStore/.test(ui));
ok("lab UI shows the storage disclosure; saving is off by default", /LAB_STORAGE_DISCLOSURE/.test(ui) && /useState\(false\)/.test(ui));
ok("lab UI has no payment, checkout, network or tracking code", !/stripe|checkout|fetch\(|XMLHttpRequest|WebSocket|sendBeacon|buy\.|\/api\/|recordGameEvent/i.test(ui));
ok("lab UI shows 'Not scored' for empty areas", /Not scored/.test(ui));
ok("lab UI uses native labelled controls", /<fieldset/.test(ui) && /type="radio"/.test(ui) && /<legend/.test(ui) && /<label/.test(ui) && /inputMode="numeric"/.test(ui));
ok("lab UI moves focus to feedback after a check and announces it", /\.focus\(\)/.test(ui) && /role="status"/.test(ui) && /tabIndex=\{-1\}/.test(ui));
ok("lab UI shows the lab disclaimer and says stress is not part of the score", /LAB_DISCLAIMER/.test(ui) && /not part of (your|the) score/i.test(ui));
ok("lab UI adds no logo image (BrandMark untouched)", !/<img|nija-logo|\.png|\.webp/.test(ui));
ok("page opens the lab from the intro and the finished screen", /<TiqLab/.test(page) && (page.match(/setLabOpen\(true\)/g) || []).length >= 2);
ok("$1 report stays Coming Soon and locked in the page", /Adults 18\+ Only — \$1 — Coming Soon/.test(page) && /No payment is requested and no purchase is available yet/.test(page));
ok("page adds no fetch call", (page.match(/fetch\(/g) || []).length === 0);
ok("css has navy lab styles", /\.tiq-lab/.test(css) && /#0B1220/i.test(css));
ok("css has a reduced-motion rule covering lab elements", /prefers-reduced-motion[\s\S]{0,300}\.tiq-lab/.test(css));
ok("css gives lab options 44px touch targets and a small-screen layout", /\.tiq-lab-opt[^}]*min-height:\s*44px/.test(css) && /@media \(max-width:\s*\d+px\)\s*\{[^@]*tiq-lab/.test(css));
ok("css has a visible focus style for lab controls", /\.tiq-lab[^{]*:focus-visible/.test(css));
ok("lab disclaimer carries the required legal sentences", /Membership does not guarantee trading profits/.test(LAB_DISCLAIMER) && /not financial advice/.test(LAB_DISCLAIMER));

console.log(`PASS: ${pass}, FAIL: ${fail}`);
process.exit(fail ? 1 : 0);
