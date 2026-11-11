import { useEffect, useMemo, useReducer, useRef, useState } from "react";
import { GAME_EVENTS, newRunId, recordGameEvent } from "../lib/gameAnalytics.js";
import { Link } from "react-router";
import { setPageSEO } from "../lib/seo.js";
import BrandMark from "../components/BrandMark.jsx";
import TiqReport from "../components/TiqReport.jsx";
import TiqCoach from "../components/TiqCoach.jsx";
import TiqAchievements from "../components/TiqAchievements.jsx";
import { ScoreRing, Recommendations, ScoreCard } from "../components/TiqResults.jsx";
import { newsFor } from "../lib/tiqNews.js";
import TiqLab, { TiqLabScorecard, useLabController } from "../components/TiqLab.jsx";
import { buildReport, scoreRun, challengeAreas } from "../lib/tiqReportClient.js";
import { requestReopen, previewSimulationAllowed } from "../lib/tiqReportReopen.js";
import { DECLARATION_TEXT, buildAdultDeclaration, validateAdultDeclaration } from "../lib/adultDeclaration.js";
import { readProgress, writeProgress, clearProgress, hasProgress, effectiveStreak } from "../lib/tiqProgress.js";

// Educational game. Every price, asset and scenario here is fictional.
// No game decision is sent anywhere, placed with a broker, or connected to real trading.
// Guest progress (XP, badges, streaks, practice history, unfinished challenge) is saved only in this browser.
const START_CASH = 10000;
const ROUNDS = 12;
const STOP_PCT = 0.05;
const BUY_FRACTION = 0.25;
const TARGET = { beginner: 50, intermediate: 60, advanced: 70 };

const LEVELS = {
  beginner: { label: "Beginner", vol: 0.7, tips: true, blurb: "Gentler moves and a 'what to notice' tip every round." },
  intermediate: { label: "Intermediate", vol: 1, tips: false, blurb: "Realistic moves. Scenario briefs are your only guide." },
  advanced: { label: "Advanced", vol: 1.5, tips: false, blurb: "Sharper swings, no tips. Discipline counts for more." },
};

const SCENARIOS = [
  { name: "Quiet Opening", asset: "NVA-1", seed: 101, drift: 0.012, vol: 0.012,
    brief: "A calm market drifting upward. Learn when patience pays.",
    tip: "Trends can be slow. Compare each move with the last few before reacting." },
  { name: "Earnings Surprise", asset: "QTR-7", seed: 202, drift: 0, vol: 0.02, shock: { at: 6, size: 0.09 },
    brief: "A strong report sends the price jumping. Does the excitement last?",
    tip: "Big one-day jumps often partly reverse. Position size decides how much that costs you." },
  { name: "Sideways Chop", asset: "LKR-3", seed: 303, drift: 0, vol: 0.015, mean: true,
    brief: "Prices bounce inside a range. Frequent trades can cost more than they earn.",
    tip: "In a range, buying high and selling low is easy to do. Waiting is a position too." },
  { name: "Sudden Sell-Off", asset: "DRX-9", seed: 404, drift: -0.01, vol: 0.018, shock: { at: 9, size: -0.12 },
    brief: "Fear spreads fast. Watch how your limits protect your capital.",
    tip: "A stop-loss turns a possible large loss into a planned, smaller one." },
  { name: "Breakout Test", asset: "HZN-5", seed: 505, drift: 0.005, vol: 0.015, shock: { at: 5, size: 0.05 }, fake: true,
    brief: "Price breaks out of its range. Is this a real move or a false start?",
    tip: "A breakout that fades quickly is a common trap. Wait for confirmation before committing." },
  { name: "Volatility Storm", asset: "VOL-2", seed: 606, drift: 0, vol: 0.035,
    brief: "Large swings in both directions test your discipline.",
    tip: "When swings are large, a fixed plan matters more than your mood in the moment." },
];

// Extra fictional scenarios used only in Today's Challenge rotation.
const MORE_SCENARIOS = [
  { name: "Rate Cut Rally", asset: "ABC-4", seed: 707, drift: 0.008, vol: 0.016, shock: { at: 4, size: 0.06 },
    brief: "Cheaper borrowing lifts prices. Chase the rally, or wait for it to settle?",
    tip: "Rallies driven by one news event can fade. Decide your exit before you enter." },
  { name: "Slow Bleed", asset: "SLW-8", seed: 808, drift: -0.008, vol: 0.01,
    brief: "No single crash, just steady losses. Small losses add up.",
    tip: "A slow decline is easy to ignore. Check your whole portfolio, not only the last move." },
  { name: "Double Top Trap", asset: "TOP-6", seed: 909, drift: 0, vol: 0.02, shock: { at: 7, size: 0.04 }, fake: true,
    brief: "Price peaks twice and then slips. Is the top real, or a temporary pause?",
    tip: "Repeated failures at the same price can signal weakness. Follow your plan, not hope." },
];

const ALL_SCENARIOS = [...SCENARIOS, ...MORE_SCENARIOS];

const BADGES = [
  { id: "first_run", name: "First Challenge", how: "Finish any run.", test: () => true },
  { id: "stop_believer", name: "Stop-Loss Believer", how: "Use the stop-loss during a run.", test: ({ run }) => run.anyStop },
  { id: "patient_hands", name: "Patient Hands", how: "Finish a run with two or fewer trades in every challenge.", test: ({ run }) => run.allLight },
  { id: "steady_hand", name: "Steady Hand", how: "Keep every challenge's largest drop under 12%.", test: ({ run }) => run.worstDD < 0.12 },
  { id: "level_clear", name: "Level Cleared", how: "Reach your level's target average in one run.", test: ({ run }) => run.avg >= TARGET[run.level] },
  { id: "advanced_clear", name: "Advanced Ready", how: "Reach the Advanced target average.", test: ({ run }) => run.level === "advanced" && run.avg >= TARGET.advanced },
  { id: "improver", name: "Improver", how: "Beat your previous best average on the same level by 5 points.", test: ({ run, prevBest }) => prevBest !== null && run.avg >= prevBest + 5 },
  { id: "daily_regular", name: "Daily Regular", how: "Finish a Today's Challenge run.", test: ({ isDaily }) => isDaily },
];

const RANKS = [
  { min: 0, name: "Rookie" },
  { min: 150, name: "Analyst" },
  { min: 400, name: "Strategist" },
  { min: 800, name: "Veteran" },
];

function rankOf(xp) {
  return RANKS.filter((r) => r.min <= xp).pop();
}

function dayNumberOf(date) {
  return Math.floor(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate()) / 86400000);
}

// Same six challenges for everyone on the same UTC day; the rotation and prices change daily.
function dailyList(dayNum) {
  const start = dayNum % ALL_SCENARIOS.length;
  return Array.from({ length: SCENARIOS.length }, (_, k) => {
    const sc = ALL_SCENARIOS[(start + k) % ALL_SCENARIOS.length];
    return { ...sc, seed: sc.seed + (dayNum % 997) * 13 };
  });
}

function bestAvg(runs, level) {
  // Only runs scored with the current method (sv 2) are compared; earlier runs used a different formula.
  const same = runs.filter((r) => r.level === level && r.sv === 2);
  return same.length ? Math.max(...same.map((r) => r.avg)) : null;
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

function buildPrices(sc, level) {
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

function judge(action, held, p0, p1, stopFired) {
  const move = (p1 - p0) / p0;
  const up = move > 0.005;
  const down = move < -0.005;
  const pct = Math.abs(move * 100).toFixed(1);
  let fb;
  if (action === "buy") {
    fb = up
      ? { tone: "good", head: "Good outcome", text: `The price rose ${pct}% after you bought. One move does not prove a pattern, though.` }
      : down
      ? { tone: "caution", head: "Caution", text: `The price fell ${pct}% after you bought. Risking only 25% of your cash limited the damage.` }
      : { tone: "note", head: "Little change", text: "The price barely moved. Small moves are normal; avoid reading meaning into them." };
  } else if (action === "sell") {
    fb = !held
      ? { tone: "note", head: "Nothing to sell", text: "You had no position. Check what you own before you act." }
      : up
      ? { tone: "note", head: "Sold early", text: `You sold before a ${pct}% rise. Selling is valid; the habit to build is deciding your exit in advance.` }
      : down
      ? { tone: "good", head: "Good exit", text: `You sold before a ${pct}% drop. Acting before losses grow protects capital.` }
      : { tone: "note", head: "Sold", text: "You closed the position. Small moves are normal either way." };
  } else if (!held) {
    fb = up
      ? { tone: "note", head: "Stayed in cash", text: `You stayed in cash while the price rose ${pct}%. Staying out is a valid decision.` }
      : { tone: "good", head: "Patience", text: "You stayed in cash while the price fell. Doing nothing can be strong when there is no clear edge." };
  } else {
    fb = down
      ? { tone: "caution", head: "Held through a drop", text: `You held through a ${pct}% drop. Without an exit plan, one move can do a lot of damage.` }
      : { tone: "good", head: "Steady", text: "You held through normal movement. Patience works while your plan still holds." };
  }
  if (stopFired) fb = { tone: "good", head: "Stop-loss triggered", text: "Your stop-loss closed the position at a planned loss, so it could not grow further." };
  return fb;
}

// Educational score of one challenge. Simulated return is NOT an input: only risk, research and discipline behaviour.
function challengeScore(c) {
  const a = challengeAreas(c);
  return Math.min(100, Math.max(0, Math.round((a.risk + a.research + a.discipline) / 3)));
}

function roundState(list, level, sIdx, results) {
  return {
    sIdx, round: 0, phase: "decide", prices: buildPrices(list[sIdx], level),
    cash: START_CASH, units: 0, cost: 0, trades: 0, peak: START_CASH, maxDD: 0,
    stopOn: false, stopUsed: false, history: [START_CASH], feedback: null, results,
  };
}

function startRun(s, dayNum) {
  const list = s.mode === "daily" ? dailyList(dayNum) : SCENARIOS;
  return { ...s, screen: "play", dayNum, list, decLog: [], rows: [], ...roundState(list, s.level, 0, []) };
}

function finishRun(s, results) {
  const scored = scoreRun(results);
  const avg = scored.iq;
  const isDaily = s.mode === "daily";
  const run = {
    mode: s.mode, level: s.level, dayNum: s.dayNum, avg, sv: 2,
    worstDD: Math.max(...results.map((r) => r.maxDD)),
    anyStop: results.some((r) => r.stopUsed),
    allLight: results.every((r) => r.trades <= 2),
  };
  const prevBest = bestAvg(s.runs, s.level);
  const repeatDaily = isDaily && s.doneDays.includes(s.dayNum);
  const doneDays = isDaily && !repeatDaily ? [...s.doneDays, s.dayNum] : s.doneDays;
  const streak = !isDaily ? s.streak
    : s.lastDaily === s.dayNum - 1 ? s.streak + 1
    : s.lastDaily === s.dayNum ? s.streak
    : 1;
  const lastDaily = isDaily ? s.dayNum : s.lastDaily;
  const earned = BADGES
    .filter((b) => b.test({ run, prevBest, isDaily }))
    .map((b) => b.id)
    .filter((id) => !s.badges.includes(id));
  const newlyEarned = repeatDaily ? [] : earned;
  const runXp = repeatDaily ? 0 : avg + (isDaily ? 15 : 10) + 20 * newlyEarned.length;
  return {
    ...s, inRun: null, restored: false, screen: "done", results, streak, lastDaily, doneDays,
    runs: [...s.runs, { ...run, xp: runXp }],
    badges: [...s.badges, ...newlyEarned], lastEarned: newlyEarned,
    xp: s.xp + runXp, lastXp: runXp,
  };
}

const initial = {
  screen: "intro", mode: "standard", level: "beginner", dayNum: 0, list: SCENARIOS,
  sIdx: 0, round: 0, phase: "decide", prices: [], cash: START_CASH, units: 0, cost: 0, trades: 0,
  peak: START_CASH, maxDD: 0, stopOn: false, stopUsed: false, history: [START_CASH], feedback: null,
  results: [], runs: [], badges: [], xp: 0, streak: 0, lastDaily: -1, doneDays: [], lastEarned: [], lastXp: 0,
  restored: false, inRun: null, decLog: [],
};

function initialWithSaved() {
  const saved = readProgress({ badgeIds: BADGES.map((b) => b.id), today: dayNumberOf(new Date()), scenes: SCENARIOS.length, rounds: ROUNDS });
  if (!saved) return initial;
  const next = { ...initial, ...saved };
  return { ...next, restored: hasProgress(next) };
}

// What is written to the browser for an unfinished challenge (prices are rebuilt from the seeds on resume).
function snapshotOf(s) {
  return {
    mode: s.mode, level: s.level, dayNum: s.dayNum, sIdx: s.sIdx, round: s.round, phase: s.phase,
    cash: s.cash, units: s.units, cost: s.cost, trades: s.trades, peak: s.peak, maxDD: s.maxDD,
    stopOn: s.stopOn, stopUsed: s.stopUsed, history: s.history, results: s.results, feedback: s.feedback,
    rows: s.rows || [],
  };
}

function reducer(s, a) {
  switch (a.type) {
    case "setLevel":
      return s.screen === "intro" ? { ...s, level: a.level } : s;
    case "setMode":
      return s.screen === "intro" ? { ...s, mode: a.mode } : s;
    case "start":
      return startRun({ ...s, inRun: null, restored: false }, a.dayNum);
    case "resume": {
      if (!s.inRun) return s;
      const r = s.inRun;
      const list = r.mode === "daily" ? dailyList(r.dayNum) : SCENARIOS;
      const savedRows = [...r.results.flatMap((x) => x.decisions || []), ...(r.rows || [])];
      const decLog = savedRows.map((d) => ({ action: d.action, stop: d.stopArmed === true }));
      return { ...s, ...r, decLog, screen: "play", list, prices: buildPrices(list[r.sIdx], r.level), inRun: null, restored: false };
    }
    case "stop":
      return s.phase === "decide" ? { ...s, stopOn: a.on } : s;
    case "trade": {
      if (s.phase !== "decide") return s;
      const p0 = s.prices[s.round];
      const p1 = s.prices[s.round + 1];
      const held = s.units > 0;
      let { cash, units, cost, trades } = s;
      if (a.action === "buy") {
        const amt = cash * BUY_FRACTION;
        if (amt >= 1) { units += amt / p0; cost += amt; cash -= amt; trades += 1; }
      }
      if (a.action === "sell" && units > 0) {
        cash += units * p0; units = 0; cost = 0; trades += 1;
      }
      let stopFired = false;
      const armedWithPosition = s.stopOn && units > 0;
      const avg = units > 0 ? cost / units : 0;
      if (s.stopOn && units > 0 && p1 <= avg * (1 - STOP_PCT)) {
        cash += units * p1; units = 0; cost = 0; trades += 1; stopFired = true;
      }
      const value = cash + units * p1;
      const peak = Math.max(s.peak, value);
      const maxDD = Math.max(s.maxDD, (peak - value) / peak);
      return {
        ...s, phase: "reveal", cash, units, cost, trades, peak, maxDD,
        decLog: [...(s.decLog || []), { action: a.action, stop: s.stopOn }],
        rows: [...(s.rows || []), { round: s.round + 1, action: a.action, held, stopArmed: s.stopOn, movePct: Math.round(((p1 - p0) / p0) * 1000) / 10, lastMovePct: Math.round(((p0 - (s.round === 0 ? p0 : s.prices[s.round - 1])) / (s.round === 0 ? p0 : s.prices[s.round - 1])) * 1000) / 10, invested: Math.round(((units * p1) / value) * 10000) / 10000 }],
        stopUsed: s.stopUsed || armedWithPosition || stopFired,
        history: [...s.history, value],
        feedback: judge(a.action, held, p0, p1, stopFired),
      };
    }
    case "next": {
      if (s.phase !== "reveal") return s;
      const nr = s.round + 1;
      if (nr < ROUNDS) return { ...s, round: nr, phase: "decide", feedback: null };
      const final = s.history[s.history.length - 1];
      const rows = s.rows || [];
      const result = {
        name: s.list[s.sIdx].name, final,
        ret: (final - START_CASH) / START_CASH, maxDD: s.maxDD, trades: s.trades,
        stopUsed: s.stopUsed, decisions: rows,
      };
      result.score = challengeScore(result);
      const results = [...s.results, result];
      if (s.sIdx + 1 >= s.list.length) return finishRun(s, results);
      return { ...s, rows: [], ...roundState(s.list, s.level, s.sIdx + 1, results) };
    }
    case "restart":
      return { ...s, screen: "intro", results: [], feedback: null };
    case "reset":
      return { ...initial, level: s.level, mode: s.mode };
    default:
      return s;
  }
}

const money = (n) => "$" + Math.round(n).toLocaleString("en-US");
const pct = (n) => (n >= 0 ? "+" : "") + (n * 100).toFixed(1) + "%";

function PriceChart({ prices, round, phase, avgCost, scenarioKey, decisions = [], stopOn = false }) {
  const visibleCount = phase === "reveal" ? round + 2 : round + 1;
  const pts = prices.slice(0, visibleCount);
  const stopLevel = stopOn && avgCost > 0 ? avgCost * (1 - STOP_PCT) : 0;
  const lo = Math.min(...pts, avgCost || Infinity, stopLevel || Infinity) - 2;
  const hi = Math.max(...pts, avgCost || -Infinity) + 2;
  const W = 600, H = 260, P = 24;
  const x = (i) => P + (i / ROUNDS) * (W - P * 2);
  const y = (v) => P + (1 - (v - lo) / (hi - lo || 1)) * (H - P * 2);
  const line = pts.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const area = `${x(0).toFixed(1)},${H - P} ${line} ${x(pts.length - 1).toFixed(1)},${H - P}`;
  const last = pts.length - 1;
  const prev = pts[Math.max(0, last - 1)];
  const rising = pts[last] >= prev;
  const moves = pts.slice(1).map((v, i) => Math.abs(v - pts[i]));
  const vol = moves.length ? moves.reduce((a, b) => a + b, 0) / moves.length : 0;
  const volLabel = vol > 3 ? "High swings" : vol > 1.5 ? "Moderate swings" : "Calm";
  const trendLabel = pts.length < 3 ? "Trend forming" : pts[last] > pts[0] ? "Trending up" : pts[last] < pts[0] ? "Trending down" : "Sideways";
  const markers = decisions.slice(0, Math.min(decisions.length, pts.length));
  const segStart = last > 0 ? `${x(last - 1).toFixed(1)},${y(pts[last - 1]).toFixed(1)} ${x(last).toFixed(1)},${y(pts[last]).toFixed(1)}` : "";
  return (
    <figure className="tiq-chart" aria-label="Fictional market chart" style={{ margin: 0 }} data-trend={rising ? "up" : "down"}>
      <div className="tiq-chart-tags" aria-hidden="true">
        <span className="tiq-tag">{trendLabel}</span>
        <span className="tiq-tag">{volLabel}</span>
        <span className="tiq-tag tiq-tag--warn">Fictional data</span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-labelledby="tiq-chart-title" width="100%">
        <title id="tiq-chart-title">Fictional price chart showing {pts.length} of {ROUNDS + 1} price points so far. {trendLabel}. {volLabel}.</title>
        <desc>{pts.length < 2 ? "Only the starting price is shown. Each decision you make reveals the next price." : `Price moved from ${pts[0].toFixed(1)} to ${pts[last].toFixed(1)}; the latest move was ${rising ? "up" : "down"} by ${Math.abs(pts[last] - prev).toFixed(1)}.${avgCost > 0 ? ` Your average entry is ${avgCost.toFixed(1)}.` : ""}${stopLevel > 0 ? ` Stop-loss level is ${stopLevel.toFixed(1)}.` : ""}`}</desc>
        <defs>
          <linearGradient id="tiq-area" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#D4AF37" stopOpacity="0.38" />
            <stop offset="100%" stopColor="#D4AF37" stopOpacity="0" />
          </linearGradient>
        </defs>
        {[0.25, 0.5, 0.75].map((f) => (
          <line key={f} x1={P} x2={W - P} y1={P + f * (H - P * 2)} y2={P + f * (H - P * 2)} stroke="#2a3550" strokeDasharray="4 6" />
        ))}
        <polygon key={"a" + scenarioKey + round} className="tiq-area" points={area} fill="url(#tiq-area)" />
        {avgCost > 0 && (
          <g>
            <line x1={P} x2={W - P} y1={y(avgCost)} y2={y(avgCost)} stroke="#F0D78C" strokeDasharray="8 6" strokeWidth="1.5" />
            <text x={W - P - 4} y={y(avgCost) - 5} textAnchor="end" fill="#F0D78C" fontSize="11">Your entry</text>
          </g>
        )}
        {stopLevel > 0 && (
          <g className="tiq-stopline">
            <line x1={P} x2={W - P} y1={y(stopLevel)} y2={y(stopLevel)} stroke="#FF8A7A" strokeDasharray="3 4" strokeWidth="1.8" />
            <text x={W - P - 4} y={y(stopLevel) + 13} textAnchor="end" fill="#FF8A7A" fontSize="11">Stop-loss</text>
          </g>
        )}
        <polyline className="tiq-line-base" points={line} fill="none" stroke="#B8902C" strokeWidth="3" strokeLinejoin="round" strokeLinecap="round" />
        {segStart && (
          <polyline key={scenarioKey + "-" + visibleCount} className="tiq-draw" pathLength="1" points={segStart}
            fill="none" stroke={rising ? "#F0D78C" : "#FF8A7A"} strokeWidth="4.5" strokeLinecap="round" />
        )}
        {markers.map((d, i) => d && d.action !== "hold" && (
          <g key={"m" + i} className="tiq-marker" transform={`translate(${x(i).toFixed(1)} ${y(pts[i]).toFixed(1)})`}>
            <circle r="9" fill="#0B1220" stroke={d.action === "buy" ? "#7CE0A3" : "#FF8A7A"} strokeWidth="2" />
            <text y="4" textAnchor="middle" fontSize="11" fontWeight="700" fill={d.action === "buy" ? "#7CE0A3" : "#FF8A7A"}>{d.action === "buy" ? "B" : "S"}</text>
          </g>
        ))}
        <circle key={"p" + visibleCount} className="tiq-pulse" cx={x(last)} cy={y(pts[last])} r="6" fill="#F0D78C" />
      </svg>
      {pts.length < 2 && <p className="tiq-chart-hint">Start of the chart: your first choice reveals the next price.</p>}
      <figcaption style={{ color: "#D9D9D9", fontSize: "0.9rem", marginTop: 6 }}>
        Fictional index for practice, not live market prices. Dashed gold line = your average entry. B and S mark your buys and sells.
      </figcaption>
    </figure>
  );
}

function SaveStatus({ s, saveOk }) {
  if (!hasProgress(s)) return null;
  if (saveOk === false) {
    return <p className="tiq-small" role="status">Progress cannot be saved in this browser right now. You can keep playing, but it will not be kept after you leave.</p>;
  }
  if (saveOk !== true) return null;
  return (
    <p className="tiq-small" role="status">
      <strong>Saved on This Device.</strong> Your XP, badges, streak and any unfinished challenge stay in this browser.
    </p>
  );
}

function ProgressPanel({ s, saveOk, onReset }) {
  const [confirming, setConfirming] = useState(false);
  const anyProgress = hasProgress(s);
  const streakNow = effectiveStreak(s.streak, s.lastDaily, dayNumberOf(new Date()));
  const rank = rankOf(s.xp);
  const next = RANKS.find((r) => r.min > s.xp);
  const span = next ? next.min - rank.min : 1;
  const fill = next ? Math.min(100, ((s.xp - rank.min) / span) * 100) : 100;
  const best = bestAvg(s.runs, s.level);
  const goal = best === null
    ? `Reach an average of ${TARGET[s.level]} on ${LEVELS[s.level].label}.`
    : `Beat your best of ${best} on ${LEVELS[s.level].label} by 5 points: aim for ${best + 5}.`;
  const recent = s.runs.slice(-5).reverse();
  return (
    <section className="tiq-card tiq-card--inner" aria-labelledby="tiq-progress-title">
      <h2 id="tiq-progress-title" className="tiq-fb-head">Your progress</h2>
      <SaveStatus s={s} saveOk={saveOk} />
      <p className="tiq-small">Rank: <strong>{rank.name}</strong> · {s.xp} XP{next ? ` · ${next.min - s.xp} XP to ${next.name}` : ""}</p>
      <div className="tiq-bar" role="progressbar" aria-label="XP toward next rank"
        aria-valuemin={rank.min} aria-valuemax={next ? next.min : s.xp} aria-valuenow={s.xp}>
        <span style={{ width: `${fill}%` }} />
      </div>
      <p className="tiq-small">Daily streak: {streakNow} {streakNow === 1 ? "day" : "days"}.</p>
      <p className="tiq-small">Improvement goal: {goal}</p>
      <h3 className="tiq-small"><strong>Badges</strong> ({s.badges.length} of {BADGES.length} earned)</h3>
      <ul className="tiq-badges">
        {BADGES.map((b) => {
          const on = s.badges.includes(b.id);
          return (
            <li key={b.id} className="tiq-badge" data-earned={on ? "true" : "false"}>
              <span className="tiq-badge-name">{on ? "Earned: " : "Not yet: "}{b.name}</span>
              <span className="tiq-small">{b.how}</span>
            </li>
          );
        })}
      </ul>
      {recent.length > 0 && (
        <div className="tiq-table-wrap">
          <table className="tiq-table">
            <caption className="tiq-small">Recent practice history (fictional)</caption>
            <thead>
              <tr><th scope="col">Run</th><th scope="col">Level</th><th scope="col">Score</th><th scope="col">XP</th></tr>
            </thead>
            <tbody>
              {recent.map((r, i) => (
                <tr key={s.runs.length - i}>
                  <th scope="row">{r.mode === "daily" ? "Today's" : "Standard"}</th>
                  <td>{LEVELS[r.level].label}</td>
                  <td>{r.avg}{r.sv === 2 ? "" : " (earlier scoring)"}</td>
                  <td>{r.xp}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="tiq-small">
        Your progress is kept in this browser only, so it is still here when you come back on this device.
        Clearing your browser data (history, site data or cookies) will erase guest progress.
        Saving to a member account across devices is not available yet. Public leaderboards are not switched on.
      </p>
      {anyProgress && (confirming ? (
        <div className="tiq-card tiq-card--inner" role="group" aria-labelledby="tiq-reset-q">
          <p id="tiq-reset-q" className="tiq-fb-head">Reset all progress?</p>
          <p className="tiq-small">This clears your XP, rank, badges, streak, practice history and any unfinished challenge saved on this device. It cannot be undone.</p>
          <div className="tiq-actions">
            <button type="button" className="tiq-btn" onClick={() => { setConfirming(false); clearProgress(); onReset(); }}>Yes, reset progress</button>
            <button type="button" className="tiq-btn tiq-btn--ghost" onClick={() => setConfirming(false)}>Cancel</button>
          </div>
        </div>
      ) : (
        <button type="button" className="tiq-btn tiq-btn--ghost" onClick={() => setConfirming(true)}>Reset progress</button>
      ))}
    </section>
  );
}

export default function TradingIQChallenge() {
  const [s, dispatch] = useReducer(reducer, null, initialWithSaved);
  const [saveOk, setSaveOk] = useState(null);
  const [adultOk, setAdultOk] = useState(false);
  const [report, setReport] = useState(null);
  const [reopenMsg, setReopenMsg] = useState("");
  const [reopenCode, setReopenCode] = useState("");
  const [labOpen, setLabOpen] = useState(() => { try { return new URLSearchParams(window.location.search).get("lab") === "1"; } catch { return false; } });
  const labCtl = useLabController();
  useEffect(() => { if (s.screen !== "done") setReport(null); }, [s.screen]);
  // Coach, achievements and attempt comparison use only this tab's decisions, held in memory (never saved or sent).
  const [attempts, setAttempts] = useState([]);
  const lastRun = s.runs[s.runs.length - 1];
  const coachReport = useMemo(() => {
    if (s.screen !== "done" || !lastRun) return null;
    const log = s.decLog || [];
    if (log.length !== s.list.length * ROUNDS) return null;
    const challenges = s.list.map((_, i) => log.slice(i * ROUNDS, (i + 1) * ROUNDS));
    const r = buildReport({ mode: s.mode, level: s.level, dayNum: s.mode === "daily" ? s.dayNum : 0, challenges });
    return r && r.tradingIQ === lastRun.avg ? r : null;
  }, [s.screen, s.decLog, s.list, s.mode, s.level, s.dayNum, lastRun]);
  useEffect(() => {
    if (!coachReport) return;
    setAttempts((prev) => (prev.some((a) => a.run === lastRun) ? prev : [...prev, { run: lastRun, label: `Attempt ${prev.length + 1}`, report: coachReport }]));
  }, [coachReport, lastRun]);
  // Scorecard comes straight from the decisions recorded in every finished challenge (never fabricated).
  const finalScore = useMemo(() => (s.screen === "done" && s.results.length ? scoreRun(s.results) : null), [s.screen, s.results]);
  const adultLessons = adultOk && validateAdultDeclaration(buildAdultDeclaration(adultOk)).ok;
  const canPreviewReport = typeof window !== "undefined" && previewSimulationAllowed(window.location.hostname);
  const showPreviewReport = () => {
    if (!validateAdultDeclaration(buildAdultDeclaration(adultOk)).ok) return;
    const log = s.decLog || [];
    const last = s.runs[s.runs.length - 1];
    if (!last || log.length !== s.list.length * ROUNDS) { setReopenMsg("This report needs a run played from the start in this tab. Replay the game to see a sample report."); return; }
    const challenges = s.list.map((_, i) => log.slice(i * ROUNDS, (i + 1) * ROUNDS));
    const r = buildReport({ mode: s.mode, level: s.level, dayNum: s.mode === "daily" ? s.dayNum : 0, challenges });
    if (!r || r.tradingIQ !== last.avg) { setReopenMsg("The sample report could not be matched to your score, so it was not shown."); return; }
    setReopenMsg("");
    setReport(r);
  };
  const today = dayNumberOf(new Date());

  useEffect(() => {
    document.title = "Trading IQ Challenge | NIJA AI Trading";
    setPageSEO({ path: "/trading-iq-challenge" });
  }, []);

  const runRef = useRef(null);
  useEffect(() => {
    if (s.screen === "play") {
      if (!runRef.current) {
        runRef.current = newRunId();
        if (!s.restored) recordGameEvent(GAME_EVENTS.start, runRef.current);
      }
    } else if (s.screen === "done") {
      if (runRef.current) recordGameEvent(GAME_EVENTS.complete, runRef.current);
      runRef.current = null;
    } else {
      runRef.current = null;
    }
  }, [s.screen, s.restored]);

  useEffect(() => {
    const next = s.screen === "play" ? { ...s, inRun: snapshotOf(s) } : s;
    setSaveOk(hasProgress(next) ? writeProgress(next) : clearProgress());
  }, [s]);

  const sc = s.list[s.sIdx] ?? SCENARIOS[0];
  const level = LEVELS[s.level];
  const price = s.prices[s.round + (s.phase === "reveal" ? 1 : 0)] ?? 100;
  const value = s.history[s.history.length - 1];
  const ret = (value - START_CASH) / START_CASH;
  const avgCost = s.units > 0 ? s.cost / s.units : 0;
  const introList = s.mode === "daily" ? dailyList(today) : SCENARIOS;
  const doneToday = s.lastDaily === today;
  const news = s.screen === "play" ? newsFor(sc.name, s.round) : null;
  const positionValue = s.units * price;
  const buyAmt = s.cash * BUY_FRACTION;
  const exposureNow = value > 0 ? Math.min(100, Math.max(0, (positionValue / value) * 100)) : 0;
  const exposureAfter = value > 0 ? Math.min(100, ((positionValue + buyAmt) / value) * 100) : 0;

  if (labOpen) {
    const lastAttempt = attempts[attempts.length - 1];
    return (
      <main className="tiq-page">
        <div className="tiq-wrap">
          <p className="tiq-eyebrow">Free Educational Trading Game — Practice Lab · NIJA AI Trading</p>
          <TiqLab ctl={labCtl} base={lastAttempt ? lastAttempt.report.assessments : null} onClose={() => setLabOpen(false)} />
          <p className="tiq-disclaimer">
            Educational exercises using fictional assets, news and virtual money. No real trades are placed, no brokerage is connected,
            and no signup or payment is needed. Membership does not guarantee trading profits. Features and broker connectivity depend on availability, eligibility, and applicable terms.
          </p>
        </div>
      </main>
    );
  }

  return (
    <main className="tiq-page">
      <div className="tiq-wrap">
        <header className="tiq-brand">
          <BrandMark size={56} alt="NIJA AI Trading" />
          <p className="tiq-eyebrow">Free Educational Trading Game — Ages 13+ · NIJA AI Trading</p>
        </header>

        {s.screen === "intro" && (
          <section className="tiq-card tiq-rise" aria-labelledby="tiq-title">
            <h1 id="tiq-title" className="tiq-h1">CAN YOU BEAT THE MARKET PRESSURE?</h1>
            <p className="tiq-lead">
              Six market challenges. $10,000 in virtual capital. Real lessons without risking real money.
            </p>
            <details className="tiq-how">
              <summary>How your Trading IQ is scored</summary>
              <p className="tiq-small">Your score rewards good process, never lucky profit. It is the average of five areas: risk management, research and verification, patience and discipline, diversification and decision consistency.</p>
              <p className="tiq-small">The fictional portfolio value is shown only to illustrate what happened. It is not part of any score, in this game or in the Practice Lab.</p>
            </details>
            {s.restored && (
              <section className="tiq-card tiq-card--inner" aria-labelledby="tiq-welcome">
                <h2 id="tiq-welcome" className="tiq-fb-head">Welcome back</h2>
                <p className="tiq-small">
                  Your progress is saved on this device: {rankOf(s.xp).name} rank, {s.xp} XP, {s.badges.length} of {BADGES.length} badges.
                </p>
                {s.inRun && (
                  <p className="tiq-small">
                    You have an unfinished challenge: challenge {s.inRun.sIdx + 1} of {SCENARIOS.length}, round {s.inRun.round + 1} of {ROUNDS}.
                    Starting a new challenge replaces it.
                  </p>
                )}
                <button type="button" className="tiq-btn"
                  onClick={() => dispatch(s.inRun ? { type: "resume" } : { type: "start", dayNum: today })}>
                  Continue Playing
                </button>
              </section>
            )}
            <fieldset className="tiq-levels">
              <legend className="tiq-legend">Choose your challenge</legend>
              <div className="tiq-level-grid">
                <button type="button" className="tiq-level" aria-pressed={s.mode === "standard"}
                  onClick={() => dispatch({ type: "setMode", mode: "standard" })}>
                  <span className="tiq-level-name">Standard run</span>
                  <span className="tiq-level-blurb">Six fictional challenges, any time you like.</span>
                </button>
                <button type="button" className="tiq-level" aria-pressed={s.mode === "daily"}
                  onClick={() => dispatch({ type: "setMode", mode: "daily" })}>
                  <span className="tiq-level-name">Today's challenge</span>
                  <span className="tiq-level-blurb">A new mix of fictional markets each UTC day. Same for everyone.</span>
                </button>
              </div>
            </fieldset>
            <fieldset className="tiq-levels">
              <legend className="tiq-legend">Choose your level</legend>
              <div className="tiq-level-grid">
                {Object.entries(LEVELS).map(([key, l]) => (
                  <button key={key} type="button" className="tiq-level"
                    aria-pressed={s.level === key}
                    onClick={() => dispatch({ type: "setLevel", level: key })}>
                    <span className="tiq-level-name">{l.label}</span>
                    <span className="tiq-level-blurb">{l.blurb}</span>
                  </button>
                ))}
              </div>
            </fieldset>
            {s.mode === "daily" && doneToday && (
              <p className="tiq-small">You have finished today's challenge. You can replay it for practice.</p>
            )}
            <ol className="tiq-scenario-list">
              {introList.map((x) => <li key={x.name}>{x.name}</li>)}
            </ol>
            <button type="button" className="tiq-btn" onClick={() => dispatch({ type: "start", dayNum: today })}>
              {s.mode === "daily" ? "PLAY TODAY'S CHALLENGE" : "PLAY FREE NOW"}
            </button>
            <section className="tiq-card tiq-card--inner tiq-lab-card" aria-labelledby="tiq-lab-promo-h">
              <h2 id="tiq-lab-promo-h" className="tiq-fb-head">Practice Lab: spread, check, size, stay calm</h2>
              <p className="tiq-small">
                Short fictional exercises on diversification, financial news, position size, stop-loss plans and emotional discipline.
                No trading and no scoring on simulated results. Free, with no signup.
              </p>
              <button type="button" className="tiq-btn tiq-btn--gold" onClick={() => setLabOpen(true)}>Open the Free Practice Lab</button>
            </section>
            <div style={{ height: 24 }} />
            <ProgressPanel s={s} saveOk={saveOk} onReset={() => dispatch({ type: "reset" })} />
          </section>
        )}

        {s.screen === "play" && (
          <section className="tiq-card tiq-rise" aria-labelledby="tiq-scn" data-round={s.round + 1}>
            <div className="tiq-progress-row">
              <div className="tiq-progress-block">
                <p className="tiq-small">Challenge {s.sIdx + 1} of {s.list.length}</p>
                <div className="tiq-bar" role="progressbar" aria-label="Challenges completed"
                  aria-valuemin={0} aria-valuemax={s.list.length} aria-valuenow={s.sIdx}>
                  <span style={{ width: `${(s.sIdx / s.list.length) * 100}%` }} />
                </div>
              </div>
              <div className="tiq-progress-block">
                <p className="tiq-small">Round {s.round + 1} of {ROUNDS}</p>
                <div className="tiq-bar" role="progressbar" aria-label="Rounds in this challenge"
                  aria-valuemin={0} aria-valuemax={ROUNDS} aria-valuenow={s.round + (s.phase === "reveal" ? 1 : 0)}>
                  <span style={{ width: `${((s.round + (s.phase === "reveal" ? 1 : 0)) / ROUNDS) * 100}%` }} />
                </div>
              </div>
            </div>

            {saveOk === true && (
              <p className="tiq-small tiq-saved-note"><span aria-hidden="true">● </span>Saved on This Device. Clearing your browser data can erase guest progress.</p>
            )}
            {saveOk === false && (
              <p className="tiq-small tiq-saved-note">Not saved in this browser right now. You can keep playing.</p>
            )}

            <h2 id="tiq-scn" key={"scn" + s.sIdx} className="tiq-h2 tiq-rise">{sc.name} <span className="tiq-asset">· {sc.asset}</span></h2>

            <p className="tiq-where"><strong>Challenge {s.sIdx + 1} of {s.list.length}</strong> · <strong>Decision {s.round + 1} of {ROUNDS}</strong></p>
            <ol className="tiq-stepper" aria-label="Your six challenges">
              {s.list.map((x, i) => (
                <li key={x.name} className="tiq-step" data-state={i < s.sIdx ? "done" : i === s.sIdx ? "now" : "next"} aria-current={i === s.sIdx ? "step" : undefined}>
                  <span className="tiq-step-n">{i < s.sIdx ? "✓" : i + 1}</span><span className="tiq-step-name">{x.name}</span>
                </li>
              ))}
            </ol>
            <PriceChart prices={s.prices} round={s.round} phase={s.phase} avgCost={avgCost} scenarioKey={s.sIdx} decisions={s.decLog || []} stopOn={s.stopOn} />
            {s.round === 0 && s.phase === "decide" && <p className="tiq-intro-chip tiq-rise">New scenario: study the chart, then decide.</p>}
            <p className="tiq-lead">{sc.brief}</p>
            {s.level === "beginner" && s.phase === "decide" && <p className="tiq-tip"><strong>What to notice:</strong> {sc.tip}</p>}

            {news && (
              <aside className={"tiq-news tiq-news--" + news.kind} aria-labelledby="tiq-news-h" key={"news" + s.sIdx + "-" + s.round}>
                <p id="tiq-news-h" className="tiq-news-top"><span className="tiq-news-badge">Market news · decision {s.round + 1} of {ROUNDS}</span><span className="tiq-news-kind">{news.label}</span></p>
                <p className="tiq-news-head">{news.headline}</p>
                <p className="tiq-small">{news.check}</p>
                <p className="tiq-small tiq-news-fict">Fictional headline written for practice. It is not real news.</p>
              </aside>
            )}
            <ol className="tiq-dots" aria-label="Decisions in this challenge">
              {Array.from({ length: ROUNDS }, (_, i) => {
                const d = (s.rows || [])[i];
                const state = i < (s.rows || []).length ? "done" : i === s.round ? "now" : "next";
                return <li key={i} className="tiq-dot" data-state={state} data-action={d ? d.action : undefined}><span className="tiq-dot-n">{i + 1}</span><span className="tiq-dot-a">{d ? d.action[0].toUpperCase() : ""}</span></li>;
              })}
            </ol>
            <div className="tiq-roundbar" role="progressbar" aria-label="Round progress" aria-valuemin="1" aria-valuemax={ROUNDS} aria-valuenow={s.round + 1}>
              <span style={{ width: ((s.round + (s.phase === "reveal" ? 1 : 0)) / ROUNDS) * 100 + "%" }} />
              <em>Round {s.round + 1} of {ROUNDS}</em>
            </div>
            <div key={"st" + s.sIdx + "-" + s.round + s.phase} className="tiq-stats tiq-round-in">
              <div><span className="tiq-small">Price</span><strong className="tiq-num">{price.toFixed(2)}</strong></div>
              <div><span className="tiq-small">Cash</span><strong className="tiq-num">{money(s.cash)}</strong></div>
              <div><span className="tiq-small">Portfolio</span><strong className="tiq-num">{money(value)}</strong></div>
              <div><span className="tiq-small">Change (illustration only)</span><strong className="tiq-num">{pct(ret)}</strong></div>
            </div>
            <div className="tiq-alloc" aria-label="Fictional portfolio split, illustration only">
              <span className="tiq-alloc-inv" style={{ width: Math.max(0, Math.min(100, value > 0 ? ((value - s.cash) / value) * 100 : 0)) + "%" }} />
              <span className="tiq-alloc-cash" />
              <em>Invested {Math.round(Math.max(0, value > 0 ? ((value - s.cash) / value) * 100 : 0))}% · Cash {Math.round(Math.min(100, value > 0 ? (s.cash / value) * 100 : 100))}% (illustration only)</em>
            </div>
            <p className="tiq-small">Virtual money only. Level: {level.label}.</p>

            {s.phase === "decide" && (
              <>
                <div className="tiq-actions" role="group" aria-label="Your decision this round">
                  <button type="button" className="tiq-btn tiq-btn--gold" onClick={() => dispatch({ type: "trade", action: "buy" })}>Buy 25% of cash</button>
                  <button type="button" className="tiq-btn" onClick={() => dispatch({ type: "trade", action: "sell" })}>Sell all</button>
                  <button type="button" className="tiq-btn tiq-btn--ghost" onClick={() => dispatch({ type: "trade", action: "hold" })}>Hold</button>
                </div>
                <div className="tiq-risk" aria-labelledby="tiq-risk-h">
                  <p id="tiq-risk-h" className="tiq-fb-head">Risk check before you decide</p>
                  <ul className="tiq-risk-list">
                    <li className="tiq-small">Buying uses 25% of your cash: {money(buyAmt)}. Your invested share would go from {Math.round(exposureNow)}% to about {Math.round(exposureAfter)}%.</li>
                    <li className="tiq-small">{s.units > 0 ? `A 5% stop-loss would limit a fall on your current position (${money(positionValue)}) to about ${money(positionValue * STOP_PCT)}.` : `A 5% stop-loss would limit a fall on a new ${money(buyAmt)} purchase to about ${money(buyAmt * STOP_PCT)}.`}</li>
                    <li className="tiq-small">Staying in cash keeps your risk at zero for this round. Holding or selling are choices too.</li>
                  </ul>
                </div>
                <label className="tiq-check">
                  <input type="checkbox" checked={s.stopOn}
                    onChange={(e) => dispatch({ type: "stop", on: e.target.checked })} />
                  <span>Use a 5% stop-loss (automatically sell if the price falls 5% below your average entry)</span>
                </label>
              </>
            )}

            {s.phase === "reveal" && s.feedback && (
              <div key={"fb" + s.round} className={`tiq-feedback tiq-feedback--${s.feedback.tone} tiq-pop`} role="status" aria-live="polite">
                <p className="tiq-fb-head">{s.feedback.head}</p>
                <p className="tiq-outcome-chip">Round {s.round + 1} of {ROUNDS} · fictional change {pct(ret)} (illustration only)</p>
                <p>{s.feedback.text}</p>
                {news && <p className="tiq-lesson"><strong>Why the news matters:</strong> {news.lesson}</p>}
              </div>
            )}

            {s.phase === "reveal" && (
              <button type="button" className="tiq-btn" onClick={() => dispatch({ type: "next" })}>
                {s.round + 1 < ROUNDS ? "Next round" : "Finish challenge"}
              </button>
            )}
          </section>
        )}

        {s.screen === "done" && (() => {
          const last = s.runs[s.runs.length - 1];
          const avgScore = last.avg;
          const target = TARGET[s.level];
          const met = avgScore >= target;
          const verdict = avgScore >= target + 15 ? "Strong discipline" : met ? "On track" : "Keep practising";
          const nextLevel = Object.keys(LEVELS)[Object.keys(LEVELS).indexOf(s.level) + 1];
          const newBadges = BADGES.filter((b) => s.lastEarned.includes(b.id));
          return (
            <>
              <section className="tiq-card tiq-rise" aria-labelledby="tiq-done">
                <div className="tiq-hero-score"><ScoreRing score={avgScore} target={target} /><div><h2 id="tiq-done" className="tiq-h1">Your Trading IQ: {avgScore}</h2><p className="tiq-small">Out of 100. A process score: it never counts simulated profit.</p></div></div>
                <p className="tiq-lead">{verdict}. Level target for {level.label}: {target}.</p>
                <p className="tiq-feedback tiq-feedback--good" role="status">
                  {s.mode === "daily" && s.lastXp === 0
                    ? "Daily challenge completed! You've already earned today's XP. Keep practicing to improve your trading skills."
                    : `You earned ${s.lastXp} XP${newBadges.length > 0 ? ` and ${newBadges.length} new ${newBadges.length === 1 ? "badge" : "badges"}` : ""}.`}
                </p>
                {newBadges.length > 0 && (
                  <ul className="tiq-scenario-list">
                    {newBadges.map((b) => <li key={b.id}>{b.name}</li>)}
                  </ul>
                )}
                <ScoreCard assessments={finalScore ? finalScore.assessments : null} iq={avgScore} />
                <Recommendations assessments={finalScore ? finalScore.assessments : null} />
                <p className="tiq-small">Scored on process only: risk management, research, discipline, diversification and consistency. Portfolio changes are for illustration only.</p>
                <p className="tiq-small">
                  {met && nextLevel
                    ? `Ready for ${LEVELS[nextLevel].label}? Try it whenever you like.`
                    : `Next goal: ${goalAfter(s)}`}
                </p>
                <p className="tiq-fb-head tiq-illus-head">Fictional portfolio — illustration only</p>
                <div className="tiq-table-wrap tiq-illus">
                  <table className="tiq-table">
                    <caption className="tiq-small">Fictional results by challenge. The portfolio change is shown for illustration only and is never part of your score.</caption>
                    <thead>
                      <tr><th scope="col">Challenge</th><th scope="col">Fictional portfolio (illustration only)</th><th scope="col">Largest drop</th><th scope="col">Challenge score</th></tr>
                    </thead>
                    <tbody>
                      {s.results.map((r) => (
                        <tr key={r.name}>
                          <th scope="row">{r.name}</th>
                          <td>{money(r.final)} ({pct(r.ret)})</td>
                          <td>{(r.maxDD * 100).toFixed(1)}%</td>
                          <td>{r.score}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="tiq-card tiq-card--inner">
                  <p className="tiq-fb-head">Personalized Trading IQ report (locked)</p>
                  <p className="tiq-small"><strong>Adults 18+ Only — $1 — Coming Soon</strong></p>
                  <p className="tiq-small">
                    A planned $1 one-time report would include your Trading IQ score out of 100, risk-management,
                    trading-discipline and research scores, strengths and weaknesses, feedback on each decision,
                    improvement steps and a downloadable copy. It will unlock only after a payment is confirmed on our
                    secure server. No payment is requested and no purchase is available yet.
                  </p>
                </div>
                {canPreviewReport && !report && (
                  <div className="tiq-card tiq-card--inner">
                    <p className="tiq-fb-head">Preview test: sample personalized report</p>
                    <p className="tiq-small"><strong>Preview only — no payment is taken and nothing is purchased.</strong> The real $1 report stays Coming Soon.</p>
                    <label className="tiq-small" style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
                      <input type="checkbox" checked={adultOk} onChange={(e) => setAdultOk(e.target.checked)} style={{ width: 24, height: 24, flexShrink: 0 }} />
                      <span>{DECLARATION_TEXT}</span>
                    </label>
                    <div className="tiq-actions">
                      <button type="button" className="tiq-btn tiq-btn--gold" disabled={!adultOk} onClick={showPreviewReport}>Show sample report (preview test)</button>
                    </div>
                    {reopenMsg && <p className="tiq-small" role="status">{reopenMsg}</p>}
                  </div>
                )}
                {report && <TiqReport report={report} preview onClose={() => setReport(null)} />}
                {coachReport ? (
                  <>
                    <TiqCoach report={coachReport} adult={adultLessons} declared={adultOk} onDeclare={setAdultOk} />
                    <TiqAchievements attempts={attempts.filter((a) => a.report.level === s.level && a.report.mode === s.mode)} onReplay={() => dispatch({ type: "start", dayNum: today })} />
                  </>
                ) : (
                  <p className="tiq-small">Coach notes and session achievements appear after a run played from the start in this tab.</p>
                )}
                <TiqLabScorecard lab={labCtl.lab} base={coachReport ? coachReport.assessments : null} />
                <div className="tiq-actions">
                  <button type="button" className="tiq-btn tiq-btn--gold" onClick={() => setLabOpen(true)}>Open the Free Practice Lab</button>
                </div>
                <div className="tiq-card tiq-card--inner">
                  <p className="tiq-fb-head">Re-open a purchased report</p>
                  <p className="tiq-small">Not available yet. Once real purchases are switched on, you will enter the report code you were given and the report opens only after your payment is confirmed.</p>
                  <label className="tiq-small" htmlFor="tiq-reopen-code">Report code</label>
                  <input id="tiq-reopen-code" className="tiq-input" type="password" autoComplete="off" value={reopenCode} onChange={(e) => setReopenCode(e.target.value)} style={{ width: "100%", minHeight: 44, color: "#111", background: "#fff", padding: "0 10px" }} />
                  <div className="tiq-actions">
                    <button type="button" className="tiq-btn tiq-btn--ghost" onClick={async () => { const r = await requestReopen({ runId: "", code: reopenCode }); setReopenCode(""); setReopenMsg(r.reason === "not_available" ? "Re-opening purchased reports is not available yet." : "Could not open a report."); }}>Re-open report</button>
                  </div>
                </div>
                <div className="tiq-actions">
                  <button type="button" className="tiq-btn" onClick={() => dispatch({ type: "start", dayNum: today })}>Replay Game</button>
                  <button type="button" className="tiq-btn tiq-btn--ghost" onClick={() => dispatch({ type: "restart" })}>Back to menu</button>
                </div>
              </section>
              <ProgressPanel s={s} saveOk={saveOk} onReset={() => dispatch({ type: "reset" })} />
            </>
          );
        })()}

        <p className="tiq-disclaimer">
          Educational game using fictional market data and virtual money. No real trades are placed, no brokerage is connected,
          and no signup or payment is needed to play. Badges, XP and streaks are practice markers only; they have no cash value.
          Membership does not guarantee trading profits. Features and broker connectivity depend on availability, eligibility, and applicable terms.
        </p>
        <p className="tiq-small"><Link to="/" className="tiq-link">Back to home</Link></p>
      </div>
    </main>
  );
}

function goalAfter(s) {
  const best = bestAvg(s.runs, s.level);
  return best === null ? `an average of ${TARGET[s.level]} or more.` : `an average of ${best + 5} or more on ${LEVELS[s.level].label}.`;
}
