/**
 * Trading IQ Challenge analytics — anonymous, duplicate-safe, and separated.
 *
 * Events are written to the existing visitor-event store (anonymous visitor id +
 * event name + random run id only). No names, emails, birthdates or answers are sent.
 *
 * Counting rules:
 *  - Every count is a Set of anonymous ids, so repeats never double-count.
 *  - Simulated/test events (variant or path marked "sim") are reported in a
 *    separate block and never reach real totals or revenue.
 *  - Revenue counts ONLY server-verified, live, non-QA report payments.
 *    Client redirects, test-mode rows and unverified rows are never revenue.
 */
export const GAME_EVENTS = {
  start: "tiq_game_start",
  complete: "tiq_game_complete",
  reportView: "tiq_report_view",
  checkout: "tiq_checkout_attempt",
};
const SENT_KEY = "nija_tiq_events_sent";
const SENT_CAP = 200;
const RUN_ID_RE = /^[a-f0-9]{32}$/;

/** A fresh anonymous run id (32 lowercase hex). Not linked to any person. */
export function newRunId() {
  const b = new Uint8Array(16);
  if (typeof crypto !== "undefined" && crypto.getRandomValues) crypto.getRandomValues(b);
  else for (let i = 0; i < 16; i++) b[i] = Math.floor(Math.random() * 256);
  return Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");
}

function readSent() {
  try { return new Set(JSON.parse(localStorage.getItem(SENT_KEY) || "[]")); } catch { return new Set(); }
}

/**
 * Record one game event once per run. Re-renders, refreshes and double
 * effects in the browser cannot send the same run/event pair twice.
 */
export function recordGameEvent(event, runId) {
  try {
    if (!RUN_ID_RE.test(String(runId || ""))) return false;
    const key = event + ":" + runId;
    const sent = readSent();
    if (sent.has(key)) return false;
    sent.add(key);
    localStorage.setItem(SENT_KEY, JSON.stringify([...sent].slice(-SENT_CAP)));
    import("./visitorTracking.js").then((m) => m.trackVisitorEvent(event, { value_ref: runId })).catch(() => {});
    return true;
  } catch { return false; }
}

/** Simulated/test rows are marked by variant or path and are never real. */
export function isSimulated(e) {
  const v = String(e.variant || "");
  const p = String(e.path || "");
  return v.startsWith("sim") || p.startsWith("/sim");
}

/** Only report-product payments that the server verified as live revenue. */
export function isVerifiedReportPayment(p) {
  return !!p
    && p.payment_verified_by === "stripe_webhook"
    && p.livemode === true
    && p.is_qa_record !== true
    && Number(p.amount_cents) > 0
    && /report|iq/i.test(String(p.product || ""));
}

const pct = (n, d) => (d > 0 ? Math.round((n / d) * 1000) / 10 : null);

/** Compute one block (real or simulated) from already-filtered events and payments. */
function block(events, payments) {
  const ev = (name) => events.filter((e) => e.event === name);
  const visitors = new Set(events.filter((e) => e.event === "visit").map((e) => e.visitor_id));
  const starts = ev(GAME_EVENTS.start);
  const completes = ev(GAME_EVENTS.complete);
  const reportViews = ev(GAME_EVENTS.reportView);
  const checkouts = ev(GAME_EVENTS.checkout);

  const uniq = (rows) => new Set(rows.map((e) => e.value_ref || e.visitor_id)).size;
  const startedBy = new Map();
  starts.forEach((e) => {
    const day = String(e.created || "").slice(0, 10);
    if (!startedBy.has(e.visitor_id)) startedBy.set(e.visitor_id, new Set());
    startedBy.get(e.visitor_id).add(day);
  });
  const returning = [...startedBy.values()].filter((d) => d.size >= 2).length;

  const verified = payments.filter(isVerifiedReportPayment);
  const refunded = payments.filter((p) => p.is_qa_record !== true && p.livemode === true && /report|iq/i.test(String(p.product || "")) && p.payment_status === "refunded");
  const disputed = payments.filter((p) => p.is_qa_record !== true && p.livemode === true && /report|iq/i.test(String(p.product || "")) && p.payment_status === "disputed");
  const grossCents = verified.reduce((t, p) => t + Number(p.amount_cents), 0);
  const refundCents = refunded.reduce((t, p) => t + Number(p.amount_cents || 0), 0);
  const disputeCents = disputed.reduce((t, p) => t + Number(p.amount_cents || 0), 0);
  const netCents = grossCents - refundCents - disputeCents;

  const uv = visitors.size;
  return {
    uniqueVisitors: uv,
    gameStarts: uniq(starts),
    completions: uniq(completes),
    returningPlayers: returning,
    reportViews: uniq(reportViews),
    checkoutAttempts: uniq(checkouts),
    verifiedPurchases: verified.length,
    refunds: refunded.length,
    disputes: disputed.length,
    startRate: pct(uniq(starts), uv),
    completionRate: pct(uniq(completes), uniq(starts)),
    checkoutRate: pct(uniq(checkouts), uniq(reportViews)),
    purchaseRate: pct(verified.length, uniq(checkouts)),
    grossCents,
    refundCents,
    disputeCents,
    netCents,
    perVisitorCents: uv > 0 ? Math.round(netCents / uv) : null,
  };
}

/**
 * Split events and payments into real and simulated blocks.
 * Returns { real, simulated, simulatedCount, status }.
 */
export function summarizeGame({ events = [], payments = [] } = {}) {
  const realEvents = events.filter((e) => !isSimulated(e));
  const simEvents = events.filter(isSimulated);
  const realPayments = payments.filter((p) => p.is_qa_record !== true);
  const real = block(realEvents, realPayments);
  const simulated = block(simEvents, []);
  const reasons = [];
  if (real.uniqueVisitors === 0) reasons.push("no_visitors");
  if (real.verifiedPurchases === 0) reasons.push("no_verified_report_purchases");
  return {
    real,
    simulated,
    simulatedCount: simEvents.length,
    status: reasons.length ? "PROVISIONAL" : "COMPLETE",
    reasons,
  };
}
