// Scoring regression tests: simulated returns must never change an educational score.
// Run: node offline_tiq_premium/tiq_scoring_test.mjs
import { readFileSync } from "node:fs";
import { scoreRun, challengeAreas, IQ_METHOD } from "./tiq_scoring.mjs";
import { replayRun, SCENARIOS, ROUNDS } from "./tiq_engine.mjs";
import { buildReport, ASSESSMENT_METHOD } from "./tiq_report.mjs";
import { scoreLab, scoreAllocation } from "./tiq_lab.mjs";

let pass = 0, fail = 0;
const ok = (n, c) => { if (c) pass++; else { fail++; console.log("FAIL:", n); } };

const mkRows = (acts) => acts.map((a, i) => ({ round: i + 1, action: a, held: i % 3 === 1, stopArmed: i % 4 === 0, movePct: [2, -1.5, 0.2, -3][i % 4], lastMovePct: [-1, 1, 2, -2][i % 4], invested: 0.2 }));
const acts = (f) => Array.from({ length: ROUNDS }, (_, i) => f(i));
const mk = (rows, extra = {}) => ({ maxDD: 0.08, trades: 4, stopUsed: true, decisions: rows, ...extra });
const base = [mk(mkRows(acts((i) => ["buy", "hold", "sell"][i % 3]))), mk(mkRows(acts(() => "hold"))), mk(mkRows(acts((i) => (i % 2 ? "buy" : "hold"))))];

// 1. Identical decisions, wildly different simulated results -> identical scores.
const boom = base.map((c) => ({ ...c, final: 99999, ret: 8.9999, profit: 1e9 }));
const bust = base.map((c) => ({ ...c, final: 1, ret: -0.9999, profit: -1e9 }));
const a = scoreRun(boom), b = scoreRun(bust);
ok("identical decisions, +900% vs -99.99%: same Trading IQ", a.iq === b.iq);
ok("identical decisions: same five areas", JSON.stringify(a.assessments) === JSON.stringify(b.assessments));
ok("identical decisions: same per-challenge scores", JSON.stringify(a.challengeScores) === JSON.stringify(b.challengeScores));
ok("per-challenge area ignores ret/final", JSON.stringify(challengeAreas({ ...base[0], ret: 5, final: 9e9 })) === JSON.stringify(challengeAreas({ ...base[0], ret: -1, final: 0 })));

// 2. Behaviour DOES move the score (so the test is not vacuous).
const reckless = base.map((c) => ({ ...c, maxDD: 0.45, trades: 14, stopUsed: false }));
ok("larger drawdowns, over-trading, no stop lower the IQ", scoreRun(reckless).iq < a.iq);
const careful = base.map((c) => ({ ...c, maxDD: 0.01, trades: 2, stopUsed: true }));
ok("small drawdown, few trades, stops raise risk", scoreRun(careful).assessments.risk.score > scoreRun(reckless).assessments.risk.score);

// 3. Source guard: scoring module never reads return / profit / final value.
const src = readFileSync(new URL("./tiq_scoring.mjs", import.meta.url), "utf8").replace(/^\s*\/\/.*$/gm, "").replace(/`[^`]*`/g, "");
ok("tiq_scoring.mjs has no ret/profit/final/gain/pnl", !/\b(ret|profit|pnl|gain|final|START_CASH)\b/i.test(src.replace(/IQ_METHOD[\s\S]*$/, "")));
const eng = readFileSync(new URL("./tiq_engine.mjs", import.meta.url), "utf8");
ok("engine no longer defines a return-based scoreOf", !/ret \* 200|export function scoreOf/.test(eng));
const page = readFileSync(new URL("../src/pages/TradingIQChallenge.jsx", import.meta.url), "utf8");
ok("game page has no return-based score formula", !/ret \* 200/.test(page) && !/function scoreOf/.test(page));

// 4. Full replay: same decisions at different levels (different price paths and returns) keep decision-only areas stable
//    when the decisions are mirrored in the rows; and the final IQ never depends on r.ret.
const decs = (k) => Array.from({ length: 6 }, () => Array.from({ length: ROUNDS }, (_, i) => ({ action: ["buy", "hold", "hold", "sell"][(i + k) % 4], stop: i % 2 === 0 })));
const run = { mode: "standard", level: "intermediate", dayNum: 0, challenges: decs(0) };
const rp = replayRun(run);
ok("replay ok", rp.ok === true);
const rets = rp.results.map((r) => r.ret);
ok("replay returns still computed for illustration", rets.every((x) => Number.isFinite(x)) && rp.results.every((r) => Number.isFinite(r.final)));
const tampered = JSON.parse(JSON.stringify(rp));
const re = scoreRun(tampered.results.map((r, i) => ({ maxDD: r.maxDD, trades: r.trades, stopUsed: r.stopUsed, decisions: r.rounds.map((x) => ({ ...x, ret: 7, final: 1 })), ret: i * 100, final: i })));
ok("replay IQ equals scoreRun IQ regardless of returns", re.iq === rp.summary.avg);
ok("replay per-challenge scores come from scoreRun", JSON.stringify(re.challengeScores) === JSON.stringify(rp.results.map((r) => r.score)));
ok("replay summary carries the five areas", ["risk", "research", "discipline", "diversification", "consistency"].every((k) => k in rp.summary.assessments));
ok("score in 0..100", rp.summary.avg >= 0 && rp.summary.avg <= 100);

// 5. Report: Trading IQ is the mean of scored areas; method text says returns are excluded.
const rep = buildReport(run);
const areas = Object.values(rep.assessments).map((x) => x.score).filter((s) => s !== null);
ok("report IQ = mean of scored areas", rep.tradingIQ === Math.min(100, Math.max(0, Math.round(areas.reduce((t, s) => t + s, 0) / areas.length))));
ok("report IQ = replay IQ", rep.tradingIQ === rp.summary.avg);
ok("method text excludes returns", /not part of any score/.test(IQ_METHOD) && /not part of any score/.test(rep.iqMethod));
ok("area methods never use returns", Object.values(ASSESSMENT_METHOD).every((t) => !/\b(profit|return|gain)\b/i.test(t)));

// 6. Practice Lab uses the same principle and the same five area names.
ok("lab scoring has no return reference", [scoreLab, scoreAllocation].every((f) => !/profit|pnl|\.ret\b|gain/i.test(f.toString())));
const labKeys = Object.keys(scoreLab({ allocation: {}, news: {}, position: {}, loss: {}, stop: {}, emotion: {} }).areas ?? {});
ok("lab reports on the same area names (subset)", labKeys.every((k) => ["risk", "research", "discipline", "diversification", "consistency"].includes(k)));

// 7. Illustration still shown on the results screen, labelled as illustration.
ok("results screen labels simulated change as illustration", /illustration only/i.test(page));
console.log(`PASS: ${pass}, FAIL: ${fail}`);
process.exit(fail ? 1 : 0);
