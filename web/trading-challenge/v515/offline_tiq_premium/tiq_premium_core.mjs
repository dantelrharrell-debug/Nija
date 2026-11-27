// Trading IQ premium report — server-side core logic (PREVIEW ONLY).
// Pure functions: no network, no storage, no secrets in this file.
// Storage adapters and Stripe calls are injected by the caller.
import crypto from "node:crypto";
import { validateRun, replayRun } from "./tiq_engine.mjs";

export const PRICE_CENTS = 100;
export const CURRENCY = "usd";
export const CHECKOUT_TTL_MS = 30 * 60 * 1000;      // unpaid checkout closes after 30 min
export const RUN_TTL_MS = 30 * 24 * 60 * 60 * 1000; // open run expires after 30 days
export const WEBHOOK_TOLERANCE_S = 300;

const ID_RE = /^[a-f0-9]{32}$/;

export function newId() {
  return crypto.randomBytes(16).toString("hex");
}

// Ownership credential: 256-bit random, returned to the browser once.
// Only a keyed HMAC is stored server-side.
export function newOwnerCredential() {
  return crypto.randomBytes(32).toString("base64url");
}

export function hashOwnerCredential(credential, serverKey) {
  if (typeof credential !== "string" || credential.length < 40 || credential.length > 80) return null;
  if (typeof serverKey !== "string" || serverKey.length < 32) throw new Error("server_key_missing");
  return crypto.createHmac("sha256", serverKey).update(credential).digest("hex");
}

export function safeEqualHex(a, b) {
  if (typeof a !== "string" || typeof b !== "string" || a.length !== b.length || a.length === 0) return false;
  return crypto.timingSafeEqual(Buffer.from(a, "hex"), Buffer.from(b, "hex"));
}

// Start a run: server issues the id, expiry and credential. Decisions are not accepted yet.
export function startRun({ mode, level, dayNum, now, serverKey }) {
  if (!["standard", "daily"].includes(mode)) return { ok: false, reason: "bad_mode" };
  if (!["beginner", "intermediate", "advanced"].includes(level)) return { ok: false, reason: "bad_level" };
  if (mode === "daily" && !Number.isInteger(dayNum)) return { ok: false, reason: "bad_day" };
  const credential = newOwnerCredential();
  return {
    ok: true,
    credential, // shown to the browser once; never stored
    record: {
      id: newId(),
      owner_hash: hashOwnerCredential(credential, serverKey),
      mode, level, day_num: mode === "daily" ? dayNum : null,
      status: "open",
      created_at: now, expires_at: now + RUN_TTL_MS,
      total_score: null, completed_at: null,
    },
  };
}

// Complete a run: validate the decisions, then calculate the score on the server only.
// Browser-sent scores and totals are rejected (unexpected_field) by validateRun.
export function completeRun({ record, decisions, presentedCredential, serverKey, now }) {
  if (!record || record.status !== "open") return { ok: false, reason: "not_open" };
  if (now > record.expires_at) return { ok: false, reason: "expired" };
  const expected = record.owner_hash;
  const got = hashOwnerCredential(presentedCredential, serverKey);
  if (!safeEqualHex(got, expected)) return { ok: false, reason: "forbidden" };
  const input = { mode: record.mode, level: record.level, dayNum: record.mode === "daily" ? record.day_num : 0, challenges: decisions };
  const v = validateRun(input);
  if (!v.ok) return { ok: false, reason: v.reason };
  const r = replayRun(input);
  if (!r || r.ok !== true) return { ok: false, reason: "replay_failed" };
  const total = r.summary.avg;
  return {
    ok: true,
    update: { status: "completed", total_score: total, completed_at: now, score_json: JSON.stringify(r.summary) },
  };
}

// Verify a Stripe-style signature header: "t=<unix>,v1=<hex>[,v1=...]" over "<t>.<rawBody>".
export function verifyWebhookSignature({ rawBody, header, secret, nowSeconds }) {
  if (typeof header !== "string" || typeof rawBody !== "string" || !secret) return { ok: false, reason: "bad_signature" };
  const parts = header.split(",").map((p) => p.trim());
  const t = parts.find((p) => p.startsWith("t="))?.slice(2);
  const sigs = parts.filter((p) => p.startsWith("v1=")).map((p) => p.slice(3));
  if (!t || !/^\d+$/.test(t) || sigs.length === 0) return { ok: false, reason: "bad_signature" };
  if (Math.abs(nowSeconds - Number(t)) > WEBHOOK_TOLERANCE_S) return { ok: false, reason: "stale" };
  const expected = crypto.createHmac("sha256", secret).update(`${t}.${rawBody}`).digest("hex");
  const ok = sigs.some((s) => safeEqualHex(s, expected));
  return ok ? { ok: true } : { ok: false, reason: "bad_signature" };
}

// Checkout: one open checkout per run. Idempotency key is derived from the run id.
export function checkoutIdempotencyKey(runId) {
  if (!ID_RE.test(runId)) throw new Error("bad_run_id");
  return `tiq-report-${runId}`;
}

export function planCheckout({ run, existingCheckouts, mode, now }) {
  if (!run || run.status !== "completed") return { ok: false, reason: "run_not_completed" };
  if (run.expires_at && now > run.expires_at) return { ok: false, reason: "expired" };
  if (existingCheckouts.some((c) => c.status === "paid")) return { ok: false, reason: "already_paid" };
  const open = existingCheckouts.find((c) => c.status === "created" && now - c.created_at < CHECKOUT_TTL_MS);
  if (open) return { ok: true, reuse: open.id };
  if (mode !== "test") return { ok: false, reason: "payments_disabled" };
  return {
    ok: true,
    create: {
      run_id: run.id,
      amount_cents: PRICE_CENTS,
      currency: CURRENCY,
      status: "created",
      idempotency_key: checkoutIdempotencyKey(run.id),
      created_at: now,
    },
  };
}

// Interpret a verified payment event. Only signed + matching + test-mode data counts.
export function interpretPaymentEvent({ event, checkout, serverMode }) {
  const o = event?.data?.object;
  if (!o || !checkout) return { ok: false, reason: "unknown_checkout" };
  if (o.livemode !== (serverMode === "live")) return { ok: false, reason: "mode_mismatch" };
  if (o.client_reference_id !== checkout.id) return { ok: false, reason: "checkout_mismatch" };
  if (checkout.stripe_session_id && o.id !== checkout.stripe_session_id) return { ok: false, reason: "checkout_mismatch" };
  if (o.amount_total !== PRICE_CENTS || o.currency !== CURRENCY) return { ok: false, reason: "amount_mismatch" };
  if (event.type === "checkout.session.completed" && o.payment_status === "paid") {
    return { ok: true, action: "grant", payment_intent_id: o.payment_intent };
  }
  if (event.type === "checkout.session.expired") return { ok: true, action: "close" };
  if (event.type === "charge.refunded") return { ok: true, action: "revoke", reason: "refunded" };
  if (event.type === "charge.dispute.created") return { ok: true, action: "revoke", reason: "disputed" };
  return { ok: true, action: "ignore" };
}

// Idempotent apply: a repeated event id, or an already-granted report, writes nothing new.
export function applyPaymentAction({ action, state, eventId }) {
  if (state.processedEvents.has(eventId)) return { changed: false, reason: "duplicate_event" };
  if (action.action === "grant") {
    if (state.entitlement) return { changed: false, reason: "already_granted" };
    if (state.payments.some((p) => p.payment_intent_id === action.payment_intent_id)) return { changed: false, reason: "duplicate_payment" };
    return { changed: true, write: "grant" };
  }
  if (action.action === "revoke") return { changed: true, write: "revoke", reason: action.reason };
  return { changed: false, reason: "no_change" };
}

// Report access: needs run id + matching credential + active entitlement + completed run.
export function canOpenReport({ run, entitlement, presentedCredential, serverKey }) {
  if (!run || run.status !== "completed") return { ok: false, reason: "not_found" };
  const got = hashOwnerCredential(presentedCredential, serverKey);
  if (!safeEqualHex(got, run.owner_hash)) return { ok: false, reason: "not_found" };
  if (!entitlement) return { ok: false, reason: "not_purchased" };
  if (entitlement.status !== "active") return { ok: false, reason: entitlement.status };
  return { ok: true };
}

// Failed/canceled/expired checkouts never create an entitlement; browser success pages grant nothing.
export function reportFromRun(run) {
  return {
    run_id: run.id,
    mode: run.mode,
    level: run.level,
    day_num: run.day_num,
    total_score: run.total_score,
    generated_for: "fictional_data_only",
    disclaimer: "Membership does not guarantee trading profits. Features and broker connectivity depend on availability, eligibility, and applicable terms.",
  };
}
