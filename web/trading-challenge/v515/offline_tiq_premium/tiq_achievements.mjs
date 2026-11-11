// Educational session achievements for the Trading IQ Challenge (preview).
// Pure functions. Computed from a finished run's report and held in page memory only:
// nothing is stored, sent, redeemed or counted. No prizes, no cash value, and nothing here
// rewards trading more often (the only trade-count rule rewards trading LESS).

export const ACHIEVEMENTS = [
  { id: "exit_planner", name: "Exit Planner", how: "Switch on the stop-loss every time you buy (at least 3 buys).",
    test: ({ report }) => {
      const buys = report.challenges.flatMap((c) => c.decisions.filter((d) => d.action === "buy"));
      return buys.length >= 3 && buys.every((d) => d.stopArmed);
    } },
  { id: "small_positions", name: "Small Positions", how: "Never let more than half of a portfolio be invested at any round, and invest at least once.",
    test: ({ report }) => {
      const all = report.challenges.flatMap((c) => c.decisions.map((d) => d.invested));
      return Math.max(...all) > 0 && Math.max(...all) <= 0.5;
    } },
  { id: "calm_hands", name: "Calm Hands", how: "Make 6 or fewer trades in every challenge.",
    test: ({ report }) => report.challenges.every((c) => c.trades <= 6) },
  { id: "chart_reader", name: "Chart Reader", how: "Reach 75 or more on the Research area.",
    test: ({ report }) => report.assessments.research.score >= 75 },
  { id: "checked_first", name: "Checked First", how: "Never try to sell with nothing held.",
    test: ({ report }) => report.challenges.every((c) => c.decisions.every((d) => !(d.action === "sell" && !d.held))) },
  { id: "steady_pattern", name: "Steady Pattern", how: "Reach 75 or more on Consistency (when it can be scored).",
    test: ({ report }) => report.assessments.consistency.score !== null && report.assessments.consistency.score >= 75 },
  { id: "spread_out", name: "Spread Out", how: "Reach 75 or more on Diversification (when it can be scored).",
    test: ({ report }) => report.assessments.diversification.score !== null && report.assessments.diversification.score >= 75 },
  { id: "replay_learner", name: "Replay Learner", how: "In this visit, improve a scorecard area by 10 points or more compared with your previous attempt.",
    test: ({ report, previous }) => {
      if (!previous) return false;
      return Object.keys(report.assessments).some((k) => {
        const a = report.assessments[k].score, b = previous.assessments[k]?.score;
        return a !== null && b !== null && b !== undefined && a - b >= 10;
      });
    } },
];

import { cleanLabResults, scoreAllocation, scoreNews, scorePosition, scoreChoice } from "./tiq_lab.mjs";

// Practice Lab achievements: process markers only (never based on simulated results, never for doing more).
export const LAB_ACHIEVEMENTS = [
  { id: "spread_builder", name: "Spread Builder", how: "Complete an allocation exercise with no asset above 35% of what you invest and no group of assets that move together above 60%.",
    test: (lab) => Object.entries(lab.allocation).some(([id, w]) => { const r = scoreAllocation(id, w); return r.ok && r.score !== null && r.conc === 100 && r.clus === 100; }) },
  { id: "source_checker", name: "Source Checker", how: "Name the true type of report correctly for at least 4 news items.",
    test: (lab) => Object.entries(lab.news).filter(([id, a]) => scoreNews(id, a).correct === true).length >= 4 },
  { id: "verify_first", name: "Check Before Acting", how: "Answer at least 2 news items and never choose to trade on one right away.",
    test: (lab) => { const a = Object.values(lab.news); return a.length >= 2 && a.every((x) => x.response !== "trade_now"); } },
  { id: "sized_to_limit", name: "Sized to the Limit", how: "Give at least 2 position-size answers that all keep the possible loss within your stated limit.",
    test: (lab) => { const r = Object.entries(lab.position).map(([id, u]) => scorePosition(id, u)); return r.length >= 2 && r.every((x) => x.ok && x.ratio <= 1 && !x.tooBig); } },
  { id: "exit_before_entry", name: "Exit Before Entry", how: "Choose the sensible stop-loss plan in at least 2 stop-loss exercises.",
    test: (lab) => Object.entries(lab.stop).filter(([id, o]) => scoreChoice("stop", id, o).score === 100).length >= 2 },
  { id: "steady_nerves", name: "Steady Nerves", how: "Answer at least 3 emotional-discipline exercises and choose a fully planned response in each.",
    test: (lab) => { const e = Object.entries(lab.emotion); return e.length >= 3 && e.every(([id, o]) => scoreChoice("emotion", id, o).score === 100); } },
];

export function evaluateLabAchievements(labRaw) {
  const lab = cleanLabResults(labRaw);
  return LAB_ACHIEVEMENTS.map((a) => ({ id: a.id, name: a.name, how: a.how, earned: a.test(lab) === true }));
}

export const ACHIEVEMENT_NOTICE =
  "Session achievements are shown for this visit only and are not saved. They are learning markers: no prizes, no cash value, and none is given for trading more.";

// Returns [{ id, name, how, earned }] for one finished run. previous: the report of the previous attempt in this visit, or null.
// lab (optional): Practice Lab answers. When given, the Practice Lab achievements are appended to the list.
export function evaluateAchievements(report, previous = null, lab = null) {
  const base = report ? ACHIEVEMENTS.map((a) => ({ id: a.id, name: a.name, how: a.how, earned: a.test({ report, previous }) === true })) : [];
  return lab ? [...base, ...evaluateLabAchievements(lab)] : base;
}

// Compares attempts held in memory. attempts: [{ label, report }]. Returns rows for display.
export function compareAttempts(attempts) {
  const keys = ["risk", "research", "discipline", "diversification", "consistency"];
  return attempts.map((a, i) => ({
    attempt: i + 1,
    label: a.label,
    tradingIQ: a.report.tradingIQ,
    deltaIQ: i === 0 ? null : a.report.tradingIQ - attempts[i - 1].report.tradingIQ,
    areas: Object.fromEntries(keys.map((k) => [k, a.report.assessments[k].score])),
  }));
}
