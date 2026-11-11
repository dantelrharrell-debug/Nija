// Trading IQ Practice Lab (preview). Pure, deterministic, no network, no storage, no randomness.
// Four exercise families: multi-asset allocation, financial-news judgement, risk exercises, emotional discipline.
// EVERY asset, company, headline and price is fictional. Scores here are about PROCESS (how you spread, check,
// size and plan). No score in this file reads any simulated profit, loss or return: stress-test figures are
// shown for learning only and never enter a score (a test proves it). Not financial advice.

export const LAB_DISCLAIMER =
  "Practice Lab exercises use fictional assets, companies and news. Scores measure how you spread, check, size and plan, never simulated results. " +
  "Educational only, not financial advice, no real trades. Membership does not guarantee trading profits. Features and broker connectivity depend on availability, eligibility, and applicable terms.";

export const LAB_AREAS = ["risk", "research", "discipline", "diversification"];

const clamp = (n) => Math.min(100, Math.max(0, Math.round(n)));
const avg = (xs) => (xs.length ? clamp(xs.reduce((t, x) => t + x, 0) / xs.length) : null);
const isInt = (v, lo, hi) => Number.isInteger(v) && v >= lo && v <= hi;
const has = (o, k) => Object.prototype.hasOwnProperty.call(o, k);

/* ------------------------------------------------------------------ 1. Multi-asset allocation */

export const CONCENTRATION_LIMIT = 0.35; // largest share of invested money in one asset
export const CLUSTER_LIMIT = 0.6; // largest share in one group of assets that tend to move together
export const MIN_INVESTED = 20; // percent of the portfolio that must be invested for the exercise to be scored

export const ALLOCATION_EXERCISES = [
  {
    id: "alloc_1",
    title: "Starter portfolio",
    brief: "You have $10,000 of virtual money and five fictional assets. Choose how much of the portfolio goes into each. Whatever you leave unassigned stays in cash.",
    assets: [
      { id: "NVA", name: "NVA Cloud Software", cluster: "tech", note: "Software company. Tends to move with other technology names." },
      { id: "QTR", name: "QTR Chip Maker", cluster: "tech", note: "Chip designer. Moves closely with software and online advertising." },
      { id: "HZN", name: "HZN Online Ads", cluster: "tech", note: "Advertising platform. Sensitive to the same news as the other technology names." },
      { id: "UTL", name: "UTL Regional Power", cluster: "defensive", note: "Electricity supplier. Demand is steady and less tied to technology news." },
      { id: "BND", name: "BND Short Bond Fund", cluster: "bonds", note: "Short-term bonds. Usually calmer than company shares." },
    ],
    stress: { name: "Fictional technology sell-off", shocks: { tech: -15, defensive: -3, bonds: 1 } },
  },
  {
    id: "alloc_2",
    title: "Energy and travel",
    brief: "Four fictional assets from different parts of the economy. Choose your split. Unassigned money stays in cash.",
    assets: [
      { id: "OLA", name: "OLA Oil Producer", cluster: "energy", note: "Oil producer. Rises and falls with fuel prices." },
      { id: "OLB", name: "OLB Pipeline Co", cluster: "energy", note: "Pipelines. Closely tied to the same fuel prices as OLA." },
      { id: "AIR", name: "AIR Regional Airline", cluster: "travel", note: "Airline. Higher fuel prices usually hurt it." },
      { id: "MED", name: "MED Health Supplies", cluster: "health", note: "Medical supplies. Demand does not follow fuel prices." },
    ],
    stress: { name: "Fictional fuel-price spike", shocks: { energy: 8, travel: -12, health: 0 } },
  },
  {
    id: "alloc_3",
    title: "The exciting favorite",
    brief: "HZN is all anyone is talking about. Five fictional assets are available. Decide your split before you look at any price.",
    assets: [
      { id: "HZN", name: "HZN Hot Startup", cluster: "growth", note: "Young company in the news. Large swings both ways." },
      { id: "GRW", name: "GRW Growth Fund", cluster: "growth", note: "Fund of similar young companies. Moves with HZN." },
      { id: "CON", name: "CON Consumer Staples", cluster: "staples", note: "Everyday products. Slow and steady." },
      { id: "INF", name: "INF Infrastructure Trust", cluster: "real", note: "Roads and pipes. Slow, income-style business." },
      { id: "SHB", name: "SHB Short Bond Fund", cluster: "bonds", note: "Short-term bonds. Calm." },
    ],
    stress: { name: "Fictional growth sell-off", shocks: { growth: -20, staples: -2, real: -3, bonds: 1 } },
  },
];

const allocById = Object.fromEntries(ALLOCATION_EXERCISES.map((e) => [e.id, e]));

// weights: { assetId: integer percent 0..100 }. The total may be below 100 (the rest is cash). Returns { ok, ... }.
export function validateWeights(ex, weights) {
  if (!ex || !weights || typeof weights !== "object" || Array.isArray(weights)) return { ok: false, reason: "malformed" };
  const ids = ex.assets.map((a) => a.id);
  if (Object.keys(weights).some((k) => !ids.includes(k))) return { ok: false, reason: "unknown_asset" };
  let total = 0;
  for (const id of ids) {
    const w = has(weights, id) ? weights[id] : 0;
    if (!isInt(w, 0, 100)) return { ok: false, reason: "bad_weight" };
    total += w;
  }
  if (total > 100) return { ok: false, reason: "over_100" };
  return { ok: true, total };
}

// Diversification score for one allocation. Needs evidence: at least MIN_INVESTED percent invested, else score is null.
export function scoreAllocation(exId, weights) {
  const ex = allocById[exId];
  const v = validateWeights(ex, weights);
  if (!v.ok) return { ok: false, reason: v.reason, score: null };
  const w = Object.fromEntries(ex.assets.map((a) => [a.id, weights[a.id] || 0]));
  const total = v.total;
  const cash = 100 - total;
  if (total < MIN_INVESTED) {
    return { ok: true, score: null, cash, invested: total, detail: `Not scored: only ${total}% is invested, so there is nothing to spread yet. Invest at least ${MIN_INVESTED}% to see a score.` };
  }
  const shares = ex.assets.map((a) => w[a.id] / total);
  const maxShare = Math.max(...shares);
  const clusterShare = {};
  ex.assets.forEach((a, i) => { clusterShare[a.cluster] = (clusterShare[a.cluster] || 0) + shares[i]; });
  const maxCluster = Math.max(...Object.values(clusterShare));
  const topCluster = Object.keys(clusterShare).sort((a, b) => clusterShare[b] - clusterShare[a] || (a < b ? -1 : 1))[0];
  const hhi = shares.reduce((t, x) => t + x * x, 0);
  const effective = 1 / hhi;
  const evenness = Math.min(1, Math.max(0, (effective - 1) / (ex.assets.length - 1)));
  const conc = clamp(100 * (1 - Math.max(0, maxShare - CONCENTRATION_LIMIT) / (1 - CONCENTRATION_LIMIT)));
  const clus = clamp(100 * (1 - Math.max(0, maxCluster - CLUSTER_LIMIT) / (1 - CLUSTER_LIMIT)));
  const score = clamp(0.25 * conc + 0.5 * clus + 25 * evenness);
  return {
    ok: true, score, cash, invested: total, conc, clus, even: clamp(100 * evenness),
    maxShare, maxCluster, topCluster,
    detail: `Largest single asset ${Math.round(maxShare * 100)}% of invested money; largest group that moves together (${topCluster}) ${Math.round(maxCluster * 100)}%; cash ${cash}%.`,
  };
}

// Display-only fictional stress impact. It is NEVER an input to any score.
export function stressImpact(exId, weights) {
  const ex = allocById[exId];
  const v = validateWeights(ex, weights);
  if (!v.ok) return null;
  let pct = 0;
  for (const a of ex.assets) pct += ((weights[a.id] || 0) / 100) * (ex.stress.shocks[a.cluster] || 0);
  return { name: ex.stress.name, portfolioChangePct: Math.round(pct * 10) / 10 };
}

/* ------------------------------------------------------------------ 2. Financial-news scenarios */

export const NEWS_KINDS = ["verified", "rumor", "screenshot", "incomplete"];
export const NEWS_KIND_LABEL = {
  verified: "Verified report",
  rumor: "Unconfirmed rumor",
  screenshot: "Misleading screenshot",
  incomplete: "Incomplete report",
};
export const NEWS_RESPONSES = [
  { id: "trade_now", label: "Trade on it right away" },
  { id: "small_with_plan", label: "Small position with a written exit" },
  { id: "verify_first", label: "Check the original source first" },
  { id: "wait_for_update", label: "Wait for a fuller update" },
  { id: "ignore", label: "Ignore it" },
];
// Process score for each response, by the true kind of the item.
const RESPONSE_SCORE = {
  verified: { small_with_plan: 100, verify_first: 90, wait_for_update: 60, ignore: 50, trade_now: 20 },
  rumor: { verify_first: 100, wait_for_update: 100, ignore: 70, small_with_plan: 30, trade_now: 0 },
  screenshot: { ignore: 100, verify_first: 100, wait_for_update: 70, small_with_plan: 10, trade_now: 0 },
  incomplete: { wait_for_update: 100, verify_first: 100, ignore: 70, small_with_plan: 30, trade_now: 0 },
};

export const NEWS_ITEMS = [
  { id: "n_ver_1", kind: "verified", source: "Filing posted on the company's investor page and repeated by two news desks",
    headline: "Orchard Foods Ltd (fictional) confirms it has signed a three-year supply agreement with a national grocer",
    body: "The filing includes the contract start date, the volumes covered and a contact for questions. Both news desks link to the filing itself.",
    clues: ["Original filing is linked", "Specific dates and volumes", "Independent outlets agree"] },
  { id: "n_ver_2", kind: "verified", source: "Regulator notice and company statement, both with reference numbers",
    headline: "Brightline Energy (fictional) receives approval to open a second plant",
    body: "The regulator notice carries a reference number and effective date. The company statement matches it and lists conditions attached to the approval.",
    clues: ["Official notice with reference number", "Company statement matches", "Conditions are stated, not hidden"] },
  { id: "n_rum_1", kind: "rumor", source: "Anonymous post in a chat group, reposted many times",
    headline: "\"Hearing Delta Motors (fictional) will announce a buyout tomorrow, get in now\"",
    body: "No name, no document, no link. Several reposts use identical wording. Nobody in the thread says how they know.",
    clues: ["No named source", "No document or link", "Identical reposts are not independent confirmation", "Pressure to act immediately"] },
  { id: "n_rum_2", kind: "rumor", source: "\"A friend who works there\" on a video comment",
    headline: "\"Insider says Nimbus Retail (fictional) will miss its next report\"",
    body: "The comment gives no role, no figures and no date. The company has said nothing and no outlet has reported it.",
    clues: ["Unverifiable insider claim", "No figures", "No company or outlet confirmation"] },
  { id: "n_scr_1", kind: "screenshot", source: "Image of a news page, shared without a link",
    headline: "Screenshot: \"Vertex Pharma (fictional) CEO resigns\"",
    body: "The image is cropped above the web address and below the date. The font on the headline does not match the rest of the page. The same image is posted by new accounts only.",
    clues: ["Address bar and date are cropped out", "Headline font differs from the page", "Only new accounts share it", "No link to the original page"] },
  { id: "n_scr_2", kind: "screenshot", source: "Image of a chart with a bold caption, posted by an unknown account",
    headline: "Screenshot: \"Sable Mining (fictional) guaranteed to double this month\"",
    body: "The chart has no axis dates and the caption promises a result. Real reports do not promise outcomes. The account has no history.",
    clues: ["No dates on the chart", "Promises a result", "Account has no history"] },
  { id: "n_inc_1", kind: "incomplete", source: "Real company report, but only the first page is shown",
    headline: "Lumen Devices (fictional): \"Sales up 12% this quarter\"",
    body: "The excerpt shows sales only. It does not show costs, debt, outlook or what the 12% is measured against. The report has 14 pages and only page 1 is shown.",
    clues: ["Only one figure shown", "Costs, debt and outlook missing", "Comparison period not stated", "1 of 14 pages"] },
  { id: "n_inc_2", kind: "incomplete", source: "Genuine press release with the second half cut off in a social post",
    headline: "Harbor Logistics (fictional) \"announces record shipments\" and the post stops mid-sentence",
    body: "The post ends before the company explains what the shipments cost or whether guidance changed. The link to the full release was removed.",
    clues: ["Text stops mid-sentence", "Link to full release removed", "Costs and guidance not shown"] },
];
const newsById = Object.fromEntries(NEWS_ITEMS.map((n) => [n.id, n]));

// One item of each kind. seed picks which of the two per kind (deterministic).
export function newsSet(seed = 0) {
  const s = Math.abs(Math.trunc(Number(seed) || 0));
  return NEWS_KINDS.map((k) => {
    const two = NEWS_ITEMS.filter((n) => n.kind === k);
    return two[(s + NEWS_KINDS.indexOf(k)) % two.length];
  });
}

export function scoreNews(itemId, answer) {
  const it = newsById[itemId];
  if (!it || !answer || typeof answer !== "object") return { ok: false, reason: "malformed" };
  if (!NEWS_KINDS.includes(answer.kind)) return { ok: false, reason: "bad_kind" };
  if (!NEWS_RESPONSES.some((r) => r.id === answer.response)) return { ok: false, reason: "bad_response" };
  return {
    ok: true,
    correct: answer.kind === it.kind,
    classification: answer.kind === it.kind ? 100 : 0, // feeds Research
    response: RESPONSE_SCORE[it.kind][answer.response], // feeds Trading discipline
  };
}

/* ------------------------------------------------------------------ 3. Risk exercises */

export const POSITION_EXERCISES = [
  { id: "pos_1", title: "Position size", account: 10000, maxLossPct: 1, entry: 50, stop: 46,
    brief: "Virtual account $10,000. Your rule: lose at most 1% of the account on this trade ($100). You plan to buy at 50.00 and exit if the price reaches 46.00. How many units can you buy?" },
  { id: "pos_2", title: "Position size, smaller account", account: 5000, maxLossPct: 2, entry: 20, stop: 18.5,
    brief: "Virtual account $5,000. Your rule: lose at most 2% of the account on this trade ($100). You plan to buy at 20.00 and exit at 18.50. How many units can you buy?" },
];
const posById = Object.fromEntries(POSITION_EXERCISES.map((p) => [p.id, p]));

export function maxUnits(ex) {
  const maxLoss = (ex.account * ex.maxLossPct) / 100;
  return Math.floor(maxLoss / (ex.entry - ex.stop) + 1e-9);
}

export function scorePosition(exId, units) {
  const ex = posById[exId];
  if (!ex || !isInt(units, 1, 1000000)) return { ok: false, reason: "bad_units" };
  const maxLoss = (ex.account * ex.maxLossPct) / 100;
  const risk = units * (ex.entry - ex.stop);
  const ratio = risk / maxLoss;
  const tooBig = units * ex.entry > ex.account;
  const score = tooBig ? 0 : ratio <= 1 ? (ratio >= 0.5 ? 100 : 80) : ratio <= 1.25 ? 55 : ratio <= 2 ? 25 : 0;
  return { ok: true, score, riskAmount: Math.round(risk * 100) / 100, maxLoss, ratio: Math.round(ratio * 100) / 100, units, limit: maxUnits(ex), tooBig };
}

export const LOSS_EXERCISES = [
  { id: "loss_1", title: "Maximum acceptable loss",
    brief: "Before any trade, a risk plan states the most you accept losing on one trade, as a share of the account. Your virtual account is $8,000. Which limit do you choose for a single trade?",
    options: [
      { id: "p05", label: "0.5% of the account", score: 100 },
      { id: "p1", label: "1% of the account", score: 100 },
      { id: "p2", label: "2% of the account", score: 100 },
      { id: "p5", label: "5% of the account", score: 55 },
      { id: "p10", label: "10% of the account", score: 25 },
      { id: "p25", label: "25% of the account", score: 0 },
    ],
    why: {
      p05: "A very small limit keeps each trade survivable. The cost is that positions end up small.",
      p1: "A limit near 1% is a common educational rule of thumb. A string of bad trades still leaves most of the account.",
      p2: "A limit near 2% is at the upper end of a common educational rule of thumb. Several losses in a row would still be survivable.",
      p5: "At 5% per trade, only a handful of bad trades in a row would take a large part of the account.",
      p10: "At 10% per trade, a short losing streak can do serious damage, and recovering from a large drop takes a much bigger rebound.",
      p25: "At 25% per trade, four bad trades in a row could end the account. A limit this large is not a plan.",
    } },
];

export const STOP_EXERCISES = [
  { id: "stop_1", title: "Stop-loss plan, steady asset",
    brief: "You will buy a fictional asset at 100.00. It usually moves about 2% in a normal day. The last visible low was at 95.00. Choose your exit plan BEFORE entering.",
    options: [
      { id: "tight", label: "Stop at 99.00 (1% below entry, inside a normal day's movement)", score: 55 },
      { id: "swing", label: "Stop at 94.50 (just under the last visible low)", score: 100 },
      { id: "wide", label: "Stop at 80.00 (20% below entry)", score: 40 },
      { id: "move", label: "Decide later, and lower the stop if the price falls", score: 0 },
      { id: "none", label: "No stop, I will watch it", score: 0 },
    ] },
  { id: "stop_2", title: "Stop-loss plan, jumpy asset",
    brief: "A different fictional asset at 40.00 normally swings about 6% a day. The last visible low was at 36.50. Choose your exit plan BEFORE entering.",
    options: [
      { id: "tight", label: "Stop at 39.00 (2.5% below entry, inside a normal day's movement)", score: 55 },
      { id: "swing", label: "Stop at 36.00 (just under the last visible low)", score: 100 },
      { id: "wide", label: "Stop at 30.00 (25% below entry)", score: 40 },
      { id: "move", label: "Decide later, and lower the stop if the price falls", score: 0 },
      { id: "none", label: "No stop, I will watch it", score: 0 },
    ] },
];
const STOP_WHY = {
  tight: "A stop inside normal daily movement is likely to be hit by noise, so the plan ends before the idea has been tested. A smaller position lets a wider stop fit your loss limit.",
  swing: "A stop just beyond the last visible low ties the exit to something the chart shows, and it is set before entry. Size the position so that hitting it stays within your loss limit.",
  wide: "A very wide stop is hard to use: if it is hit, the loss is large. If the position would be too big with a sensible stop, the position should be smaller.",
  move: "Lowering a stop after the price falls turns a plan into a hope. The exit has to be fixed before entry and left alone.",
  none: "With no exit decided in advance, the decision is made in the moment, when emotions are strongest.",
};

export const EMOTION_EXERCISES = [
  { id: "emo_1", title: "After a planned exit",
    brief: "Your stop-loss closed a position at the planned limit. You feel an urge to double the next position to make it back quickly. What do you do?",
    options: [
      { id: "plan", label: "Keep the usual size and follow the same plan", score: 100 },
      { id: "pause", label: "Pause, write down what happened, and trade again only when my plan says so", score: 100 },
      { id: "skip", label: "Skip the rules just this once", score: 10 },
      { id: "double", label: "Double the size to recover quickly", score: 0 },
    ],
    why: {
      plan: "Keeping size the same after a loss stops one result from steering the next decision.",
      pause: "A short pause and a written note separate the emotion from the next decision.",
      skip: "Rules that are skipped once are easier to skip again.",
      double: "Raising size to recover a loss makes the next loss larger. This is a well-known pattern called revenge trading.",
    } },
  { id: "emo_2", title: "Fear of missing out",
    brief: "A fictional asset jumped 12% in a day and everyone online is posting about it. You have no plan for it. What do you do?",
    options: [
      { id: "wait", label: "Stay out until it fits a plan I wrote beforehand", score: 100 },
      { id: "small", label: "Buy a small amount with the exit written first", score: 70 },
      { id: "full", label: "Buy a large amount now so I do not miss it", score: 0 },
    ],
    why: {
      wait: "Not acting is a decision. A move you missed is not a reason to break your plan.",
      small: "Keeping it small with a written exit limits the damage, though acting without an entry plan is still a weak habit.",
      full: "Buying a large amount because others are excited means the crowd is making your decision, at the point where the price has already moved.",
    } },
  { id: "emo_3", title: "After a good run",
    brief: "You have made three good decisions in a row and feel very sure of yourself. You consider tripling your usual size. What do you do?",
    options: [
      { id: "keep", label: "Keep my usual size", score: 100 },
      { id: "rule", label: "Raise size only by a rule I wrote beforehand, in small steps", score: 80 },
      { id: "triple", label: "Triple the size while I feel this sure", score: 0 },
    ],
    why: {
      keep: "Confidence after a few good decisions is not evidence. Keeping size steady keeps the plan in charge.",
      rule: "Changing size by a pre-written rule, in small steps, is far safer than changing it on a feeling.",
      triple: "Feeling sure is a poor guide to size. A larger size means the next surprise costs three times as much.",
    } },
  { id: "emo_4", title: "The plan says exit",
    brief: "Your price reaches the exit you set before entering. You hope it will bounce. What do you do?",
    options: [
      { id: "exit", label: "Exit as planned", score: 100 },
      { id: "wait", label: "Wait one more day and see", score: 20 },
      { id: "lower", label: "Lower the stop to give it room", score: 0 },
      { id: "remove", label: "Remove the stop completely", score: 0 },
    ],
    why: {
      exit: "The exit was chosen when you were calm. Following it is the whole point of having it.",
      wait: "One more day often becomes several. The plan was your own earlier judgement.",
      lower: "Moving the stop after it is threatened means there is no real limit.",
      remove: "Removing the stop leaves the size of the loss to chance.",
    } },
];

const byId = (arr) => Object.fromEntries(arr.map((x) => [x.id, x]));
export const CHOICE_FAMILIES = {
  loss: byId(LOSS_EXERCISES),
  stop: byId(STOP_EXERCISES),
  emotion: byId(EMOTION_EXERCISES),
};
export const STOP_REASON = STOP_WHY;

export function scoreChoice(family, exId, optionId) {
  const ex = CHOICE_FAMILIES[family] && CHOICE_FAMILIES[family][exId];
  if (!ex) return { ok: false, reason: "unknown_exercise" };
  const o = ex.options.find((x) => x.id === optionId);
  if (!o) return { ok: false, reason: "bad_option" };
  return { ok: true, score: o.score };
}

/* ------------------------------------------------------------------ results container */

export const emptyLab = () => ({ allocation: {}, news: {}, position: {}, loss: {}, stop: {}, emotion: {} });

// Keeps only valid answers. Anything unknown, malformed or out of range is dropped. Never throws.
export function cleanLabResults(raw) {
  const out = emptyLab();
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return out;
  const obj = (k) => (raw[k] && typeof raw[k] === "object" && !Array.isArray(raw[k]) ? raw[k] : {});
  for (const ex of ALLOCATION_EXERCISES) {
    const w = obj("allocation")[ex.id];
    if (w && validateWeights(ex, w).ok) out.allocation[ex.id] = Object.fromEntries(ex.assets.map((a) => [a.id, w[a.id] || 0]));
  }
  for (const it of NEWS_ITEMS) {
    const a = obj("news")[it.id];
    if (a && scoreNews(it.id, a).ok) out.news[it.id] = { kind: a.kind, response: a.response };
  }
  for (const ex of POSITION_EXERCISES) {
    const u = obj("position")[ex.id];
    if (isInt(u, 1, 1000000)) out.position[ex.id] = u;
  }
  for (const [fam, key] of [["loss", "loss"], ["stop", "stop"], ["emotion", "emotion"]]) {
    for (const exId of Object.keys(CHOICE_FAMILIES[fam])) {
      const o = obj(key)[exId];
      if (typeof o === "string" && scoreChoice(fam, exId, o).ok) out[key][exId] = o;
    }
  }
  return out;
}

export function labAnswerCount(lab) {
  return Object.values(cleanLabResults(lab)).reduce((t, g) => t + Object.keys(g).length, 0);
}

export const LAB_METHOD = {
  diversification:
    "From the allocation exercises only. For each one you invest at least 20% of the portfolio; the score is 25% how small your largest single asset is (full marks up to 35% of invested money), " +
    "50% how small your largest group of assets that move together is (full marks up to 60%), and 25% how evenly the money is spread across the assets offered. " +
    "Cash is allowed. If no allocation was completed with at least 20% invested, it is shown as Not scored. Stress-test figures are display only and are never used.",
  research:
    "From the news exercises: the share of items where you named the true kind of report (verified, rumor, misleading screenshot or incomplete report), times 100.",
  risk:
    "From the risk exercises: average of position-size answers (how close the possible loss is to your stated limit), maximum-loss limit and stop-loss plan answers. Fixed points per answer, written in advance.",
  discipline:
    "From the emotional-discipline exercises and from how you responded to each news item (checking and waiting score higher than acting on impulse). Fixed points per answer, written in advance.",
};

// Per-area lab scores. Each area is null (Not scored) unless at least one answer supports it.
export function scoreLab(labRaw) {
  const lab = cleanLabResults(labRaw);
  const alloc = Object.entries(lab.allocation).map(([id, w]) => scoreAllocation(id, w)).filter((r) => r.ok && r.score !== null);
  const news = Object.entries(lab.news).map(([id, a]) => scoreNews(id, a)).filter((r) => r.ok);
  const pos = Object.entries(lab.position).map(([id, u]) => scorePosition(id, u)).filter((r) => r.ok);
  const loss = Object.entries(lab.loss).map(([id, o]) => scoreChoice("loss", id, o)).filter((r) => r.ok);
  const stop = Object.entries(lab.stop).map(([id, o]) => scoreChoice("stop", id, o)).filter((r) => r.ok);
  const emo = Object.entries(lab.emotion).map(([id, o]) => scoreChoice("emotion", id, o)).filter((r) => r.ok);
  const riskParts = [...pos.map((r) => r.score), ...loss.map((r) => r.score), ...stop.map((r) => r.score)];
  const discParts = [...emo.map((r) => r.score), ...news.map((r) => r.response)];
  return {
    areas: {
      diversification: avg(alloc.map((r) => r.score)),
      research: avg(news.map((r) => r.classification)),
      risk: avg(riskParts),
      discipline: avg(discParts),
    },
    evidence: { allocation: alloc.length, news: news.length, risk: riskParts.length, discipline: discParts.length },
  };
}

const band = (n) => (n >= 75 ? "Strong" : n >= 55 ? "Developing" : "Needs work");

// Combines the game's five-area scorecard (may be null) with lab scores. Does not mutate its inputs.
// Rules: diversification uses the lab score when one exists (the game's single-asset estimate does not measure
// owning several assets); risk, research and discipline average game and lab when both exist; consistency is
// from the game only. No evidence in either source = score null, "Not scored".
export function mergeScorecard(base, labScores) {
  const keys = ["risk", "research", "discipline", "diversification", "consistency"];
  const out = {};
  for (const k of keys) {
    const b = base && base[k] && typeof base[k].score === "number" ? base[k].score : null;
    const l = labScores && typeof labScores.areas?.[k] === "number" ? labScores.areas[k] : null;
    let score = null, source = "none", detail = "Not scored: no evidence yet.";
    if (k === "diversification") {
      if (l !== null) { score = l; source = "lab"; detail = "From the Practice Lab allocation exercises (several fictional assets at once)."; }
      else if (b !== null) { score = b; source = "game"; detail = "Single-asset estimate from the game only. Complete a Practice Lab allocation exercise for a multi-asset score."; }
      else detail = "Not scored: complete a Practice Lab allocation exercise with at least 20% invested.";
    } else if (b !== null && l !== null) {
      score = clamp((b + l) / 2); source = "game+lab"; detail = `Average of the game (${b}) and the Practice Lab (${l}).`;
    } else if (l !== null) { score = l; source = "lab"; detail = "From the Practice Lab only."; }
    else if (b !== null) { score = b; source = "game"; detail = "From the game only."; }
    out[k] = { score, band: score === null ? "Not scored" : band(score), detail, source };
  }
  return out;
}
