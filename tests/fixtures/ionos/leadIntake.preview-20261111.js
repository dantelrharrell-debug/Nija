/**
 * NIJA AI Trading — single lead-intake pipeline (browser side).
 *
 * Every lead-generating form calls submitLead() ONCE per submission. It:
 *   1. validates the email,
 *   2. gives the submission one stable identity (event_id + original submitted_at + consent time),
 *      reused on every retry of the same submission,
 *   3. writes the event to NIJA's own durable intake store (nija_lead_events, unique on
 *      event_id) — this is the ONLY thing that counts as "accepted". A visitor is only shown
 *      a success message after this resolves; on failure it throws LeadIntakeError and the
 *      form keeps what the visitor typed so they can retry safely,
 *   4. asks the same-origin server to record any consent the visitor ticked, and writes pending
 *      delivery receipts. The browser sends NOTHING to Zapier, FormSubmit or any other outside
 *      service and never holds a webhook address, mail address or secret. Delivery is owned by the
 *      server dispatcher, which is switched off until the owner activates it; receipts therefore
 *      read "pending / not active", never "sent".
 *
 * SUBMISSION IDENTITY. A new user intent is identified by an explicit, validated submission_id
 * (see newSubmissionId()). The id is part of the in-flight, pending and done identity:
 *   - same id + same content (repeat, double click, concurrent, lost-response retry) → ONE event;
 *   - different ids, even with identical content → separate events (separate intentional submissions);
 *   - same id but different content or consent → rejected as "submission_conflict"; the original
 *     pending/done record is left untouched and nothing is stored.
 * Callers that pass no submission_id (older callers) keep content-based de-duplication: the same
 * form + email + content within five minutes is treated as one submission. That cannot tell a
 * deliberate second submission with identical content from an accidental repeat, so new code must
 * pass a submission_id.
 *
 * Nothing here enables marketing, SMS or AI calling: consent is passed through exactly as the
 * visitor gave it (unticked = "false"); AI-call eligibility is decided server-side elsewhere.
 */
import { pb } from "./pb.js";
import { trackVisitorEvent } from "./visitorTracking.js";

export const INTAKE_COLLECTION = "nija_lead_events";

export class LeadIntakeError extends Error {
  constructor(code, userMessage) {
    super(code);
    this.code = code;
    this.userMessage = userMessage;
  }
}

export const INTAKE_ERROR_TEXT =
  "We couldn't save your details just now, so nothing was sent. Your answers are still here — please try again in a moment.";
export const INVALID_EMAIL_TEXT = "Please enter a valid email address.";

export function normalizeEmail(v) {
  return String(v || "").trim().toLowerCase();
}
export function isValidEmail(v) {
  const e = normalizeEmail(v);
  return e.length <= 254 && /^[^\s@,;<>()]+@[^\s@,;<>()]+\.[^\s@,;<>()]{2,}$/.test(e);
}

const FAKE_DOMAIN = /@([a-z0-9-]+\.)*(example\.(com|org|net)|[a-z0-9-]+\.(invalid|test|example))$/i;
const isFakeDomain = (e) => FAKE_DOMAIN.test(e);
const isQa = (e) => isFakeDomain(e) || /\+qa[+@]/i.test(e);

// ── identity ────────────────────────────────────────────────────────────────
function uuid() {
  try { if (crypto?.randomUUID) return crypto.randomUUID(); } catch (_) {}
  const b = new Uint8Array(16);
  try { crypto.getRandomValues(b); } catch (_) { for (let i = 0; i < 16; i++) b[i] = Math.floor(Math.random() * 256); }
  return Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");
}
/** Stable JSON: object keys sorted, so equal content always gives equal text. */
function canon(v) {
  if (v === null || typeof v !== "object") return JSON.stringify(v === undefined ? null : v);
  if (Array.isArray(v)) return "[" + v.map(canon).join(",") + "]";
  return "{" + Object.keys(v).sort().map((k) => JSON.stringify(k) + ":" + canon(v[k])).join(",") + "}";
}
/** SHA-256 hex of the text; if the browser cannot hash, two independent 32-bit hashes (never an empty value). */
async function fingerprint(text) {
  try {
    const d = new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text)));
    return "s" + Array.from(d, (x) => x.toString(16).padStart(2, "0")).join("");
  } catch (_) {
    let a = 5381, b = 52711;
    for (let i = 0; i < text.length; i++) { const c = text.charCodeAt(i); a = ((a << 5) + a + c) | 0; b = ((b << 5) ^ (b >>> 27) ^ c) | 0; }
    return "h" + (a >>> 0).toString(16) + "-" + (b >>> 0).toString(16) + "-" + text.length;
  }
}
// Session storage first; if it is unavailable or full the value is kept in memory for the life of this page, so a
// lost-response retry in the same page still reuses the same event id instead of creating a second event.
const memStore = new Map();
const store = {
  get(k) {
    try { const raw = sessionStorage.getItem(k); if (raw) return JSON.parse(raw); } catch (_) {}
    return memStore.has(k) ? memStore.get(k) : null;
  },
  set(k, v) {
    try { sessionStorage.setItem(k, JSON.stringify(v)); memStore.delete(k); } catch (_) { memStore.set(k, v); }
  },
  del(k) { memStore.delete(k); try { sessionStorage.removeItem(k); } catch (_) {} },
};
const inflight = new Map();

/** A submission id is 8–64 characters from A–Z a–z 0–9 _ - (no spaces, no personal data). */
const SUBMISSION_ID_RE = /^[A-Za-z0-9_-]{8,64}$/;
export const isValidSubmissionId = (v) => typeof v === "string" && SUBMISSION_ID_RE.test(v);
/** One new id per user intent. Keep it for failed or lost-response retries; make a new one only for a new submission. */
export function newSubmissionId() { return "sub_" + uuid().replace(/[^A-Za-z0-9]/g, ""); }
export const CONFLICT_TEXT =
  "This submission was already started with different details, so nothing was changed or sent. Please reload the page to send a new submission.";
const DONE_WINDOW_MS = 5 * 60 * 1000;


// Must equal CONSENT_NOTICE_VERSION in pb_hooks/nija_consent_helpers.js (the offline tests compare the two).
export const CONSENT_NOTICE_VERSION = "2026-11-03-v1";
const CONSENT_API = "/api/nija-consent";
const DISPATCH_API = "/api/nija-lead-dispatch";

/**
 * Asks the SERVER to record each consent the visitor ticked. A tick is a request, never proof: the server stamps
 * the decision, time, notice version and sequence, and refuses a grant the saved enquiry does not carry.
 * Returns { status: "not_requested" | "recorded" | "failed" }. "failed" means no marketing or SMS permission exists
 * for this enquiry; the enquiry itself is already saved and is not affected.
 */
export async function recordConsentDecisions(event_id, consent, form_name) {
  const channels = [];
  if (consent.marketing_email === true) channels.push("marketing_email");
  if (consent.sms === true) channels.push("sms");
  if (!channels.length) return { status: "not_requested" };
  let allRecorded = true;
  for (const channel of channels) {
    const body = { lead_id: event_id, channel, decision: "granted", notice_version: CONSENT_NOTICE_VERSION, source_form: String(form_name || "") };
    let recorded = false;
    for (let attempt = 0; attempt < 2 && !recorded; attempt++) {
      try {
        const res = await pb.send(CONSENT_API + "/record", { method: "POST", body, requestKey: null });
        recorded = res?.recorded === true && res?.decision === "granted";
        break; // a definite answer from the server is final; only a lost connection is retried
      } catch (err) {
        if (err?.status >= 400 && err?.status < 500) break; // refused by the server: retrying cannot help
      }
    }
    if (!recorded) allRecorded = false;
  }
  return { status: allRecorded ? "recorded" : "failed" };
}

/**
 * submitLead({
 *   submission_id,                                         // from newSubmissionId(); one per user intent (see header)
 *   form_name, email, name, phone, lead_type, page_source, lead_source, product_interest,
 *   consent: { marketing_email, sms, ai_voice_claimed },   // booleans, default false
 *   fields: { ...form-specific answers },                  // stored with the event
 *   extra: { ...extra flat flags stored with the event (e.g. aiVoiceFlags(), utm_*) },
 *   notify: ignored (kept so existing callers still compile; the browser sends no email)
 *   nurture: boolean,                                      // marketing-email enrolment requested (needs consent)
 *   next_step_url, next_step_label
 * }) → { ok:true, event_id, duplicate, delivery:{ zapier, email } }  |  throws LeadIntakeError
 */
export async function submitLead(input) {
  const email = normalizeEmail(input?.email);
  const form_name = String(input?.form_name || "").trim();
  if (!form_name) throw new LeadIntakeError("missing_form", INTAKE_ERROR_TEXT);
  if (!isValidEmail(email)) throw new LeadIntakeError("invalid_email", INVALID_EMAIL_TEXT);

  const fields = input.fields || {};
  const consent = input.consent || {};
  const explicit = input.submission_id !== undefined && input.submission_id !== null;
  if (explicit && !isValidSubmissionId(input.submission_id)) throw new LeadIntakeError("invalid_submission_id", INTAKE_ERROR_TEXT);

  // Content identity: everything the visitor typed, ticked or was shown as an answer. The consent TIMESTAMP is not part
  // of it (it is fixed by the first attempt), but every consent choice is.
  const fp = await fingerprint(canon([
    form_name, email, String(input.name || "").trim(), String(input.phone || "").trim(), fields, input.extra || {},
    String(input.lead_type || ""), String(input.product_interest || ""),
    [consent.marketing_email === true, consent.sms === true, consent.ai_voice_claimed === true],
  ]));
  // Explicit id: one identity per user intent (the id is scoped to the form; the email is part of the content, so
  // reusing an id with another address is a conflict). No id: legacy content-based identity.
  const key = explicit ? `sid:${form_name}:${input.submission_id}` : `legacy:${form_name}:${email}:${fp}`;
  const conflict = () => new LeadIntakeError("submission_conflict", CONFLICT_TEXT);

  // Double-click / overlapping call: share the in-flight attempt; the same id with other content is a conflict.
  const flying = inflight.get(key);
  if (flying) { if (flying.fp !== fp) throw conflict(); return flying.run; }

  const done = store.get("nija_evt_done:" + key);
  if (done) {
    if (explicit) {
      if (done.fp !== fp) throw conflict(); // the accepted original stays exactly as it is
      return { ok: true, event_id: done.event_id, duplicate: true, delivery: { zapier: "skipped_duplicate", email: "skipped_duplicate" } };
    }
    // Legacy: same content re-submitted moments after success (double click after re-render, back button).
    if (done.fp === fp && Date.now() - done.at < DONE_WINDOW_MS) {
      return { ok: true, event_id: done.event_id, duplicate: true, delivery: { zapier: "skipped_duplicate", email: "skipped_duplicate" } };
    }
  }
  if (explicit) {
    const earlier = store.get("nija_evt_pending:" + key);
    if (earlier && earlier.fp !== fp) throw conflict(); // an unfinished attempt with other details: do not fork it
  }

  const run = (async () => {
    await flushReceiptQueue();
    // Stable identity for this submission, reused across retries until it is accepted.
    let pending = store.get("nija_evt_pending:" + key);
    if (!pending || pending.fp !== fp) { // (an explicit id with other content was rejected above, so this only starts a first attempt)
      const at = new Date().toISOString();
      pending = { event_id: "evt_" + uuid(), submitted_at: at, consent_timestamp: input.consent_timestamp || at, fp, attempts: 0, delivery_started: false };
    }
    // The moment the visitor gave (or declined) permission is fixed with the first attempt; a retry never restamps it.
    if (!pending.consent_timestamp) pending.consent_timestamp = input.consent_timestamp || pending.submitted_at;
    pending.attempts += 1;
    store.set("nija_evt_pending:" + key, pending);

    const fullName = String(input.name || "").trim();
    const record = {
      event_id: pending.event_id,
      submitted_at: pending.submitted_at,
      form_name,
      email,
      name: fullName,
      phone: String(input.phone || "").trim(),
      lead_type: String(input.lead_type || "WEBSITE_LEAD"),
      page_source: String(input.page_source || (typeof location !== "undefined" ? location.pathname : "")),
      consent_marketing_email: consent.marketing_email === true,
      consent_sms: consent.sms === true,
      consent_ai_voice: false, // a browser can only CLAIM AI-call consent; never stored as permission
      consent_detail: {
        marketing_email: consent.marketing_email === true,
        sms: consent.sms === true,
        ai_voice_claimed: consent.ai_voice_claimed === true,
        ai_voice_verified: false,
        consent_timestamp: pending.consent_timestamp,
      },
      payload: { ...fields, ...(input.extra || {}), product_interest: input.product_interest || "" },
      attempt_count: pending.attempts,
      is_qa: isQa(email),
    };

    let duplicate = false;
    try {
      await pb.collection(INTAKE_COLLECTION).create(record, { requestKey: null });
    } catch (err) {
      const dupCode = err?.response?.data?.event_id?.code;
      if (err?.status === 400 && dupCode === "validation_not_unique") {
        duplicate = true; // exact retry of an event the store already holds
      } else if (err?.status === 400 && err?.response?.data?.email) {
        store.del("nija_evt_pending:" + key); // the store refused this address, nothing was saved: a corrected retry is not a fork
        throw new LeadIntakeError("invalid_email", INVALID_EMAIL_TEXT);
      } else {
        throw new LeadIntakeError("intake_unavailable", INTAKE_ERROR_TEXT);
      }
    }

    // Consent is requested from the server for a new enquiry only (an exact retry was already handled on its first attempt).
    // Nothing downstream treats a tick as permission; if this request fails, no permission exists for the enquiry.
    let consentRecording = "not_requested";
    if (!duplicate) consentRecording = (await recordConsentDecisions(record.event_id, consent, form_name)).status;

    // Duplicate whose earlier attempt never reached delivery (its response was lost): deliver now, once.
    const shouldDeliver = !pending.delivery_started && (!duplicate || pending.attempts > 1);
    const delivery = { zapier: "skipped_duplicate", email: "skipped_duplicate" };
    let receipts = "none";
    if (shouldDeliver) {
      pending.delivery_started = true;
      store.set("nija_evt_pending:" + key, pending);
      Object.assign(delivery, deliver({ record, email }));
      receipts = await recordReceipts(record.event_id, delivery, pending.attempts, email);
    }

    store.del("nija_evt_pending:" + key);
    store.set("nija_evt_done:" + key, { fp, event_id: pending.event_id, at: Date.now() });
    if (!(duplicate && !shouldDeliver) && !isFakeDomain(email)) {
      const formName = String(input.form_name || input.formName || "").slice(0, 80);
      trackVisitorEvent("lead_created", { value_ref: formName });
      // Dedicated funnel events (anonymous; one per visitor is counted when reported).
      if (formName === "free_trader_assessment") trackVisitorEvent("assessment_lead", { value_ref: formName });
      if (formName === "founding_100_waitlist") trackVisitorEvent("waitlist_registered", { value_ref: formName });
    }
    return { ok: true, event_id: pending.event_id, duplicate: duplicate && !shouldDeliver, delivery, receipts, consent_recording: consentRecording };
  })();

  inflight.set(key, { fp, run });
  try { return await run; } finally { inflight.delete(key); }
}

// Canonical funnels whose Zapier dispatch is owned by the server (pb_hooks/nija_lead_dispatch.pb.js).
// The browser never reads or calls any Zapier address; the saved event is the source of truth and the
// server dispatch stays disabled until the owner activates it.
export const SERVER_DISPATCH_FORMS = Object.freeze(["free_trader_assessment", "founding_100_waitlist", "pilot_application"]);
export const serverDispatchOwns = (formName) => SERVER_DISPATCH_FORMS.includes(String(formName || ""));

export const DELIVERY_COLLECTION = "nija_lead_delivery";
// Status words the receipt writer understands. The browser itself only ever produces the "server_*" and
// "skipped_*" / "no_template" words (see deliver()); the older words stay readable here only because
// recordReceipts() is a generic, exported receipt writer. Nothing in this file passes them any more.
const ZAP_STATUS = {
  sent_unconfirmed: ["dispatched_unconfirmed", ""],
  not_configured: ["pending", "Zapier address not set"],
  network_error: ["pending", "Zapier could not be reached"],
  skipped_qa_address: ["skipped", "test address"],
  server_pending: ["pending", "Waiting for server dispatch (not active yet)"],
  server_not_active: ["pending", "Waiting: server dispatch is not active for this form"],
};
const MAIL_STATUS = {
  sent: ["sent", ""],
  no_template: ["skipped", "no email for this form"],
  refused: ["failed", "mail service refused it (it may need one-time activation)"],
  service_down: ["failed", "mail service is down (server error)"],
  no_reply: ["failed", "mail service did not reply (no connection or timed out)"],
  no_answer: ["failed", "mail service gave no usable answer"],
  not_accepted_by_mail_service: ["failed", "mail service did not accept it"],
  error: ["failed", "mail service error"],
  skipped_qa_address: ["skipped", "test address"],
  server_not_active: ["pending", "Not sent: no website email is active (the enquiry is saved and waiting)"],
};
// Delivery receipts that could not be saved are kept in this browser tab and retried. They hold no personal data
// (event id, destination, status, reason, attempt, time). The enquiry itself was already saved before any of this.
const RECEIPT_QUEUE_KEY = "nija_receipt_queue";
const RECEIPT_CONFLICT_KEY = "nija_receipt_conflicts";
const RECEIPT_QUEUE_MAX = 50;
const RECEIPT_CONFLICT_MAX = 50;
// A receipt that keeps failing for a temporary reason (no connection, server busy) is given up after this many tries.
const RECEIPT_MAX_TRIES = 5;
/** A receipt's attempt number must be a positive whole number. New receipts are never written without one. */
export function isValidReceiptAttempt(a) { return Number.isSafeInteger(a) && a >= 1; }
const receiptKey = (row) => [row.event_id, row.destination, row.attempt].join("|");

/**
 * Writes receipt rows. Returns { transient, rejected }:
 *  - transient: temporary failure (no connection, server busy). Kept and retried, up to RECEIPT_MAX_TRIES.
 *  - rejected: the store refused the row (HTTP 400/409, e.g. a duplicate on the unique rule), the row has no valid
 *    attempt number, or it was given up. These are never retried. The browser cannot read existing receipts (they
 *    are admin-only), so it cannot prove a refused row matches one already saved; it is kept visible for review instead.
 * Never throws.
 */
/** Asks the server whether an identical receipt already exists. Returns ALREADY_RECORDED | CONFLICT | NOT_FOUND | INVALID | RETRYABLE. Never throws. */
/** SHA-256 hex of the normalised enquiry email. Only this hash is kept for receipt retries, never the address. "" if unavailable. */
async function emailProof(email) {
  const norm = String(email || "").trim().toLowerCase();
  if (!norm) return "";
  try {
    const bytes = new TextEncoder().encode(norm);
    const d = new Uint8Array(await crypto.subtle.digest("SHA-256", bytes));
    return Array.from(d, (x) => x.toString(16).padStart(2, "0")).join("");
  } catch (_) { return ""; }
}
async function verifyExistingReceipt(row, emailHash) {
  if (!/^[0-9a-f]{64}$/.test(emailHash || "")) return { verdict: "UNAUTHORIZED", retryAfterMs: 0 };
  const claims = { event_id: row.event_id, destination: row.destination, attempt: row.attempt, status: row.status, reason: row.reason || "" };
  try {
    // Step 1: the server issues a short-lived token only if this enquiry's own email matches. Refusals are final.
    const issued = await pb.send("/api/nija-receipt/token", { method: "POST", requestKey: null, body: { ...claims, email_hash: emailHash } });
    const token = issued && typeof issued.token === "string" ? issued.token : "";
    if (!token) return { verdict: "UNAUTHORIZED", retryAfterMs: 0 };
    // Step 2: the token is bound to this exact receipt and can be spent once.
    const res = await pb.send("/api/nija-receipt/verify", { method: "POST", requestKey: null, body: { ...claims, token } });
    const r = res && typeof res.result === "string" ? res.result : "";
    return { verdict: ["ALREADY_RECORDED", "CONFLICT", "NOT_FOUND"].includes(r) ? r : "RETRYABLE", retryAfterMs: 0 };
  } catch (err) {
    const s = Number(err?.status || 0);
    if (s === 400) return { verdict: "INVALID", retryAfterMs: 0 };
    if (s === 401 || s === 403) return { verdict: "UNAUTHORIZED", retryAfterMs: 0 };
    if (s === 429) {
      const ms = Number(err?.response?.retry_after_ms || 0);
      return { verdict: "RETRYABLE", retryAfterMs: Number.isFinite(ms) && ms > 0 ? Math.min(ms, 600000) : 60000 };
    }
    return { verdict: "RETRYABLE", retryAfterMs: 0 };
  }
}
async function writeReceipts(entries) {
  const out = { transient: [], rejected: [], recorded: [] };
  for (const e of entries) {
    const row = e.row;
    if (!isValidReceiptAttempt(row.attempt)) { out.rejected.push({ ...e, reason: "invalid_attempt" }); continue; }
    try { await pb.collection(DELIVERY_COLLECTION).create(row, { requestKey: null }); }
    catch (err) {
      const status = Number(err?.status || 0);
      console.error("[NIJA] delivery record not saved:", row.event_id, row.destination, status || "error");
      let verdict = "RETRYABLE";
      let wait = 0;
      if (status === 400 || status === 409) ({ verdict, retryAfterMs: wait } = await verifyExistingReceipt(row, e.email_hash));
      if (verdict === "ALREADY_RECORDED") { out.recorded.push(e); continue; }
      if (verdict !== "RETRYABLE") { out.rejected.push({ ...e, status, reason: "store_rejected", verified: verdict }); continue; }
      const tries = (e.tries || 0) + 1;
      const not_before = wait > 0 ? Date.now() + wait : 0;
      if (tries >= RECEIPT_MAX_TRIES) out.rejected.push({ ...e, tries, status, reason: "gave_up" });
      else out.transient.push({ ...e, tries, status, not_before });
    }
  }
  return out;
}
/** Keeps refused receipts visible in this tab (no personal data; event id, destination, status, reason). */
function keepRejected(items) {
  if (!items.length) return;
  const at = new Date().toISOString();
  const kept = (store.get(RECEIPT_CONFLICT_KEY) || []).concat(items.map((i) => ({
    row: i.row, reason: i.reason, status: i.status || 0, tries: i.tries || 0, kept_at: at,
  })));
  store.set(RECEIPT_CONFLICT_KEY, kept.slice(-RECEIPT_CONFLICT_MAX));
}
/** Adds temporary failures to the retry queue; anything beyond the cap is kept visible instead of silently dropped. */
function enqueue(entries) {
  if (!entries.length) return;
  const merged = (store.get(RECEIPT_QUEUE_KEY) || []).concat(entries);
  const overflow = merged.slice(0, Math.max(0, merged.length - RECEIPT_QUEUE_MAX));
  keepRejected(overflow.map((i) => ({ ...i, reason: "queue_full" })));
  store.set(RECEIPT_QUEUE_KEY, merged.slice(-RECEIPT_QUEUE_MAX));
}
/**
 * Append-only delivery receipts. Returns "recorded" | "queued" | "conflict" | "invalid_attempt" | "none".
 * Never throws and never blocks the visitor. "queued" = retried later; "conflict" = refused and kept visible for review.
 */
export async function recordReceipts(event_id, delivery, attempt, email) {
  const email_hash = await emailProof(email);
  if (!isValidReceiptAttempt(attempt)) { console.error("[NIJA] delivery record skipped: invalid attempt number", event_id); return "invalid_attempt"; }
  const at = new Date().toISOString();
  const rows = [];
  const z = ZAP_STATUS[delivery.zapier]; if (z) rows.push({ event_id, destination: "zapier", status: z[0], reason: z[1], attempt, recorded_at: at });
  const m = MAIL_STATUS[delivery.email]; if (m) rows.push({ event_id, destination: "email", status: m[0], reason: m[1], attempt, recorded_at: at });
  if (!rows.length) return "none";
  const out = await writeReceipts(rows.map((row) => ({ row, tries: 0, email_hash })));
  keepRejected(out.rejected);
  if (out.transient.length) { enqueue(out.transient); return "queued"; }
  return out.rejected.length ? "conflict" : "recorded";
}
async function runReceiptFlush() {
  const all = store.get(RECEIPT_QUEUE_KEY) || [];
  if (!all.length) return { remaining: 0, rejected: 0 };
  // Entries the server asked us to wait for (rate limit) are left untouched until their time.
  const now = Date.now();
  const queue = all.filter((e) => !(e.not_before > now));
  if (!queue.length) return { remaining: all.length, rejected: 0 };
  const out = await writeReceipts(queue);
  const handled = new Set(queue.map((e) => receiptKey(e.row)));
  // Keep anything queued while this flush was running; drop only the entries this flush handled.
  const current = store.get(RECEIPT_QUEUE_KEY) || [];
  const keep = current.filter((e) => !handled.has(receiptKey(e.row)));
  keepRejected(out.rejected);
  store.set(RECEIPT_QUEUE_KEY, keep.concat(out.transient).slice(-RECEIPT_QUEUE_MAX));
  return { remaining: keep.length + out.transient.length, rejected: out.rejected.length };
}
let receiptFlushing = null;
/** Retries receipts that were not saved yet. Overlapping calls share one run. Returns { remaining, rejected }. */
export function flushReceiptQueue() {
  if (!receiptFlushing) receiptFlushing = runReceiptFlush().finally(() => { receiptFlushing = null; });
  return receiptFlushing;
}
if (typeof window !== "undefined" && !window.__nijaReceiptFlushBound) {
  window.__nijaReceiptFlushBound = true;
  window.addEventListener("online", () => { flushReceiptQueue(); });
}

/**
 * Admin-triggered, one lead at a time: passes a stored, still-pending lead to Zapier.
 * Uses the same stable event_id as dedup_key so the Zap can ignore a repeat. No email, no
 * acknowledgment, no nurture enrolment is ever started from here.
 */
export async function sendStoredLeadToZapier(ev) {
  // The browser never builds or sends this payload. The server sends it through the same gates as automatic
  // dispatch (saved consent ledger, suppression lookup, activation time, one delivery record per enquiry).
  // Historical checkbox flags on the stored enquiry are not used for any permission.
  if (!ev || !ev.event_id || ev.is_qa || isFakeDomain(ev.email || "")) return { ok: false, reason: "test_or_missing" };
  let res;
  try {
    res = await pb.send(DISPATCH_API + "/send-one", { method: "POST", body: { event_id: ev.event_id }, requestKey: null });
  } catch (_) { return { ok: false, reason: "server_unavailable" }; }
  const outcome = String(res?.outcome || "");
  // "provider_accepted" means the request was accepted, not that the lead was delivered. Anything else is reported as is.
  return { ok: outcome === "provider_accepted", outcome, reason: outcome };
}

/**
 * Reports the delivery state of a saved enquiry. It makes NO outside request: nothing is read from a store,
 * nothing is sent to Zapier and nothing is emailed from the browser.
 *  - canonical funnels: "server_pending" (the server owns dispatch; it is switched off until reviewed activation)
 *  - other forms: "server_not_active" (no server dispatch covers them yet; the enquiry is saved and waiting)
 *  - email: always "server_not_active" (no browser mail, and no server mail route is active)
 * These are pending states. They are never presented as "sent".
 */
function deliver({ record, email }) {
  if (isFakeDomain(email)) return { zapier: "skipped_qa_address", email: "skipped_qa_address" };
  return {
    zapier: serverDispatchOwns(record.form_name) ? "server_pending" : "server_not_active",
    email: "server_not_active",
  };
}
