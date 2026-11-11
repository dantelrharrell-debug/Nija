// Personalized Trading IQ report (preview). Pure functions, no storage, no network.
// The Trading IQ score and every per-round result come from the official game rules in
// offline_tiq_premium/tiq_engine.mjs (replayRun). Browser-sent scores are never used.
// The scorecard areas are transparent summaries of that same replay; formulas are listed in
// ASSESSMENT_METHOD and printed inside the report.
import { clamp, band, fitsLastMove, signalOf, scoreDiversification, scoreConsistency, scoreRun, challengeAreas, IQ_METHOD } from "./tiq_scoring.mjs";
export { scoreDiversification, scoreConsistency, signalOf, scoreRun, challengeAreas };
import { replayRun, TARGET, STOP_PCT, BUY_FRACTION, START_CASH, ROUNDS } from "./tiq_engine.mjs";

export const REPORT_DISCLAIMER =
  "Educational report based on fictional prices and virtual money. It is not financial advice, not a prediction, and not a guarantee of results. " +
  "Membership does not guarantee trading profits. Features and broker connectivity depend on availability, eligibility, and applicable terms.";

export const ASSESSMENT_METHOD = {
  risk: "Starts at 100. Minus 3 points per 1% of average largest portfolio drop, plus 15 points times the share of challenges where you used a stop-loss, capped 0–100.",
  research: "Share of rounds (after the first) where your action fit the last price move you could already see: buying after a flat or rising price, or selling or staying out after a falling price.",
  discipline: "Starts at 100. Minus 6 points per trade above 6 in a challenge, minus 6 per time you stayed in a position through a drop with no stop-loss, minus 5 per attempt to sell with nothing held.",
  diversification:
    "Multi-asset rounds are not yet available: every challenge has one fictional asset and its own $10,000, so this score does NOT measure owning different assets at once. " +
    "It only uses what the game can show: (1) 60% weight on how evenly you spread invested capital across the six separate challenges (average share of the portfolio invested in each; evenness = (1 ÷ sum of squared shares − 1) ÷ 5), " +
    "and (2) 40% weight on position size: full marks while your invested share never passed 40% of the portfolio in any round, falling to zero at 100%. " +
    "If you never invested, nothing can be measured and it is shown as not scored.",
  consistency:
    "Each decision from round 2 on is grouped by the price signal you could already see (last move up, down or flat — a move beyond 0.5% counts) and whether you held a position. " +
    "For every group with at least 2 decisions, we take the share that used your most common action; the score is the average of those shares, weighted by group size, times 100. " +
    "It measures sameness of response, not whether the response was wise, and needs at least 6 decisions in repeated groups or it is shown as not scored.",
};

export const SCORECARD_KEYS = ["risk", "research", "discipline", "diversification", "consistency"];
export const SCORECARD_LABEL = {
  risk: "Risk management",
  research: "Research and verification",
  discipline: "Patience and discipline",
  diversification: "Diversification",
  consistency: "Consistency",
};

// Same wording as the in-game feedback (judge in TradingIQChallenge.jsx); a test keeps them identical.
export function judgeRound(action, held, p0, p1, stopFired) {
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

// Existing Academy lessons (ids and titles match src/pages/academy/lessonData.js; a test checks that).
export const REPORT_LESSONS = {
  risk: [
    { id: "18-25-5", ageGroup: "ages-18-25", title: "Renting vs. Buying and Risk Management" },
    { id: "46-65-5", ageGroup: "ages-46-65", title: "Protecting and Diversifying Wealth" },
  ],
  research: [
    { id: "18-25-6", ageGroup: "ages-18-25", title: "AI-Assisted Investing Fundamentals" },
    { id: "18-25-4", ageGroup: "ages-18-25", title: "Retirement Accounts and Investing" },
  ],
  discipline: [
    { id: "26-45-4", ageGroup: "ages-26-45", title: "Advanced Investing and Passive Income" },
    { id: "46-65-5", ageGroup: "ages-46-65", title: "Protecting and Diversifying Wealth" },
  ],
  diversification: [
    { id: "46-65-5", ageGroup: "ages-46-65", title: "Protecting and Diversifying Wealth" },
    { id: "18-25-4", ageGroup: "ages-18-25", title: "Retirement Accounts and Investing" },
  ],
  consistency: [
    { id: "26-45-4", ageGroup: "ages-26-45", title: "Advanced Investing and Passive Income" },
    { id: "18-25-5", ageGroup: "ages-18-25", title: "Renting vs. Buying and Risk Management" },
  ],
};

function decisionRows(result, decisions) {
  return result.rounds.map((r, i) => {
    const fb = judgeRound(r.action, r.held, r.p0, r.p1, r.stopFired);
    const prior = i === 0 ? r.p0 : result.rounds[i - 1].p0;
    return {
      round: r.round,
      action: r.action,
      stopArmed: decisions[i].stop === true,
      held: r.held,
      priceBefore: r.p0,
      priceAfter: r.p1,
      movePct: Math.round(((r.p1 - r.p0) / r.p0) * 1000) / 10,
      lastMovePct: Math.round(((r.p0 - prior) / prior) * 1000) / 10,
      portfolio: r.value,
      invested: r.invested,
      stopFired: r.stopFired,
      tone: fb.tone,
      head: fb.head,
      text: fb.text,
    };
  });
}

// input: { mode, level, dayNum, challenges: [[{action, stop} x12] x6] } — decisions only.
export function buildReport(input) {
  const replay = replayRun(input);
  if (!replay || replay.ok !== true) return null;
  const { summary, results } = replay;
  const sc0 = scoreRun(results.map((res, ci) => ({ maxDD: res.maxDD, trades: res.trades, stopUsed: res.stopUsed, decisions: decisionRows(res, input.challenges[ci]) }))).challengeScores;
  const challenges = results.map((res, ci) => {
    const rows = decisionRows(res, input.challenges[ci]);
    return {
      name: res.name, score: sc0[ci], final: res.final, ret: res.ret, maxDD: res.maxDD,
      trades: res.trades, stopUsed: res.stopUsed, decisions: rows,
    };
  });
  const all = challenges.flatMap((c) => c.decisions);
  const sc = scoreRun(challenges);
  const { assessments } = sc;
  const { avgDD, stopCount, overTrades, unprotectedDrops, emptySells } = sc.counts;
  const stopShare = stopCount / challenges.length;
  const risk = assessments.risk.score, research = assessments.research.score, discipline = assessments.discipline.score;
  const div = assessments.diversification, con = assessments.consistency;

  const strengths = [];
  const weaknesses = [];
  if (summary.avg >= TARGET[summary.level]) strengths.push(`Your Trading IQ of ${summary.avg} met the ${summary.level} target of ${TARGET[summary.level]}.`);
  else weaknesses.push(`Your Trading IQ of ${summary.avg} is below the ${summary.level} target of ${TARGET[summary.level]}.`);
  if (risk >= 75) strengths.push("You kept losses contained: drops stayed small and exits were planned.");
  if (risk < 55) weaknesses.push("Portfolio drops were large. A planned exit would have limited them.");
  if (stopShare === 0) weaknesses.push("You never used a stop-loss, so no loss was capped in advance.");
  else if (stopShare >= 0.5) strengths.push("You used a stop-loss in at least half of the challenges.");
  if (research >= 75) strengths.push("Most decisions matched what the chart was already showing.");
  if (research < 55) weaknesses.push("Many decisions went against the last visible price move. Check the trend before you act.");
  if (discipline >= 75) strengths.push("You traded calmly without over-trading or sitting through unprotected drops.");
  if (overTrades > 0) weaknesses.push(`You made ${overTrades} trades above the 6-per-challenge level where scoring starts to subtract points.`);
  if (unprotectedDrops > 0) weaknesses.push(`You stayed in a position through ${unprotectedDrops} drops without a stop-loss.`);
  if (emptySells > 0) weaknesses.push(`You tried to sell ${emptySells} times with nothing held.`);
  if (div.score !== null && div.score >= 75) strengths.push("You spread invested capital fairly evenly across the challenges and kept positions moderate.");
  if (div.score !== null && div.score < 55) weaknesses.push("Your invested capital was concentrated in a few challenges or grew large in one round.");
  if (con.score !== null && con.score >= 75) strengths.push("You responded to the same price situation in the same way most of the time.");
  if (con.score !== null && con.score < 55) weaknesses.push("Your actions changed a lot when the same price signal appeared again. A written rule helps.");
  if (summary.allLight) strengths.push("You finished every challenge with two or fewer trades — patient hands.");
  const best = [...challenges].sort((a, b) => b.score - a.score)[0];
  const worst = [...challenges].sort((a, b) => a.score - b.score)[0];
  strengths.push(`Best challenge: ${best.name} (${best.score}).`);
  weaknesses.push(`Hardest challenge: ${worst.name} (${worst.score}).`);

  const recommendations = [];
  if (stopShare < 0.5) recommendations.push(`Before each buy, switch on the ${Math.round(STOP_PCT * 100)}% stop-loss so the worst case is decided before the price moves.`);
  if (unprotectedDrops > 0) recommendations.push("When you hold a position, decide in advance the price at which you will sell, and write it down before you press Hold.");
  if (overTrades > 0) recommendations.push("Aim for six or fewer trades per challenge. Each extra trade above six lowers your discipline score.");
  if (research < 75) recommendations.push("Look at the last price move before each decision. Avoid buying straight after a fall unless you have a reason.");
  if (emptySells > 0) recommendations.push("Check whether you hold anything before choosing Sell.");
  if (div.score !== null && div.score < 75) recommendations.push("Keep any single position moderate and avoid putting all your attention on one situation. Multi-asset practice is not yet available in this game.");
  if (con.score !== null && con.score < 75) recommendations.push("Write one rule per situation (for example: price falling and in cash — wait) and follow it every time before judging it.");
  recommendations.push(`Buying only ${Math.round(BUY_FRACTION * 100)}% of cash at a time keeps one bad round from erasing a run. Keep that habit.`);
  recommendations.push(`Practice ${worst.name} again at the same level and try to beat ${worst.score}.`);

  const weakest = Object.entries(assessments).filter(([, a]) => a.score !== null).sort((a, b) => a[1].score - b[1].score)[0][0];
  const seen = new Set();
  const lessons = [weakest, ...Object.keys(assessments).filter((k) => k !== weakest)]
    .flatMap((k) => REPORT_LESSONS[k].map((l) => ({ ...l, focus: k })))
    .filter((l) => (seen.has(l.id) ? false : (seen.add(l.id), true)))
    .slice(0, 4);

  return {
    version: 1,
    generated_for: "fictional_data_only",
    mode: summary.mode,
    level: summary.level,
    dayNum: summary.dayNum,
    startCash: START_CASH,
    rounds: ROUNDS,
    tradingIQ: summary.avg,
    iqMethod: IQ_METHOD,
    target: TARGET[summary.level],
    targetMet: summary.targetMet,
    assessments,
    strengths,
    weaknesses,
    challenges,
    recommendations,
    lessons,
    method: ASSESSMENT_METHOD,
    disclaimer: REPORT_DISCLAIMER,
  };
}

const esc = (v) => String(v).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const ACTION_LABEL = { buy: "Buy 25%", sell: "Sell all", hold: "Hold" };
export const actionLabel = (a) => ACTION_LABEL[a] ?? a;

// Self-contained, mobile-friendly HTML file (no scripts, no external requests).
export function reportToHtml(r, { preview = false } = {}) {
  const list = (items) => `<ul>${items.map((i) => `<li>${esc(i)}</li>`).join("")}</ul>`;
  const ass = SCORECARD_KEYS.map((k) => {
    const a = r.assessments[k];
    const name = SCORECARD_LABEL[k];
    return `<tr><th scope="row">${name}</th><td>${a.score === null ? "Not scored" : a.score + "/100"}</td><td>${esc(a.band)}</td><td>${esc(a.detail)}</td></tr>`;
  }).join("");
  const chal = r.challenges.map((c) => `
<h3>${esc(c.name)} — score ${c.score}</h3>
<table><thead><tr><th scope="col">Round</th><th scope="col">Action</th><th scope="col">Price</th><th scope="col">What happened</th></tr></thead><tbody>
${c.decisions.map((d) => `<tr><th scope="row">${d.round}</th><td>${esc(actionLabel(d.action))}${d.stopArmed ? " + stop-loss" : ""}</td><td>${d.priceBefore} → ${d.priceAfter}</td><td><strong>${esc(d.head)}.</strong> ${esc(d.text)}</td></tr>`).join("\n")}
</tbody></table>`).join("\n");
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>My Trading IQ report</title>
<style>body{font:16px/1.55 system-ui,sans-serif;margin:0 auto;padding:16px;max-width:860px;color:#111;background:#fff}table{border-collapse:collapse;width:100%;display:block;overflow-x:auto}th,td{border:1px solid #bbb;padding:6px 8px;text-align:left;vertical-align:top}.banner{background:#fff3cd;border:1px solid #8a6d00;padding:10px;font-weight:600}.score{font-size:2.4rem;font-weight:700}small{color:#333}</style></head><body>
<h1>My Trading IQ report</h1>
${preview ? '<p class="banner">Preview test — no payment was made. This sample is not a purchase and is not counted as revenue.</p>' : ""}
<p class="score">${r.tradingIQ}/100</p>
<p>Level: ${esc(r.level)} · target ${r.target} · ${r.targetMet ? "target met" : "target not yet met"} · ${r.mode === "daily" ? "daily challenge" : "standard run"}</p>
<h2>Assessments</h2><table><thead><tr><th scope="col">Area</th><th scope="col">Score</th><th scope="col">Rating</th><th scope="col">Detail</th></tr></thead><tbody>${ass}</tbody></table>
<h2>Strengths</h2>${list(r.strengths)}
<h2>Weaknesses</h2>${list(r.weaknesses)}
<h2>All decisions</h2>${chal}
<h2>Improvement steps</h2>${list(r.recommendations)}
<h2>Academy lessons to review</h2>${list(r.lessons.map((l) => `${l.title} (Academy, ${l.ageGroup.replace("ages-", "ages ")})`))}
<h2>How the five scorecard areas are calculated</h2>${list(SCORECARD_KEYS.map((k) => `${SCORECARD_LABEL[k]}: ${r.method[k]}`))}
<p><small>${esc(r.disclaimer)}</small></p></body></html>`;
}
