// UPGRADE 6B — PROPOSED protected storage for the optional $1 Trading IQ report.
// PROPOSAL ONLY. Nothing in this file creates, alters or deletes any collection.
// It is the machine-readable form of STORAGE_APPROVAL_REQUEST_6B.md and is checked by
// storage_payment_6b_test.mjs. Run from app/:  node offline_tiq_premium/storage_spec_6b.mjs

export const SPEC_VERSION = "6b-proposal-2026-11-04";

// Names that already exist in the live or dev schema. The proposal must never reuse them.
export const EXISTING_NAMES = Object.freeze([
  "users", "nija_applications", "nija_crm_leads", "nija_leads", "nija_starter_kit_leads",
  "nija_payments", "nija_entitlements", "nija_access_tokens", "nija_broker_vault",
  "nija_settings", "nija_reviews", "nija_lead_events", "nija_lead_delivery",
  "nija_consent_events", "nija_visitor_events", "nija_finance_entries", "nija_public_config",
  "nija_notification_outbox", "nija_ai_voice_consents", "nija_follow_up_templates",
]);

// Fields that must never appear: birthdates, identity documents, contact and card data.
export const FORBIDDEN_FIELD_PATTERN = /(birth|dob|date_of_birth|^age$|passport|id_number|national|ssn|tax|email|phone|name|address|card|customer|last4|(^|_)ip(_|$))/i;

const NULL_RULES = Object.freeze({ list: null, view: null, create: null, update: null, delete: null });

// Every collection is server-only: browsers never read or write these rules directly.
export const COLLECTIONS = Object.freeze([
  {
    name: "tiq_runs",
    purpose: "Game runs: secure id, challenge version, validated decisions, server-calculated result, completion.",
    rules: NULL_RULES,
    fields: [
      { name: "run_id", type: "text", required: true, pattern: "^[a-f0-9]{32}$" },
      { name: "owner_hash", type: "text", required: true, note: "HMAC-SHA256 of the ownership credential; the credential itself is never stored" },
      { name: "mode", type: "select", values: ["fictional"], required: true },
      { name: "level", type: "select", values: ["beginner", "intermediate", "advanced"], required: true },
      { name: "day_num", type: "number", required: true, min: 1, max: 6 },
      { name: "challenge_version", type: "text", required: true },
      { name: "total_score", type: "number", required: true, min: 0 },
      { name: "decisions_json", type: "text", required: true, max: 8000 },
      { name: "status", type: "select", values: ["open", "completed", "expired"], required: true },
      { name: "created_at", type: "number", required: true },
      { name: "completed_at", type: "number", required: false },
      { name: "expires_at", type: "number", required: true },
    ],
    indexes: [
      { name: "idx_tiq_runs_run_id_unique", unique: true, columns: ["run_id"] },
      { name: "idx_tiq_runs_status_expires", unique: false, columns: ["status", "expires_at"] },
    ],
    retention: "Unpaid runs deleted 90 days after expiry. Runs with an entitlement kept until the entitlement is retained or deleted per the owner's retention decision (section 6).",
  },
  {
    name: "tiq_checkouts",
    purpose: "Checkout attempts: run association, test session reference, idempotency key, status, and minimal age-declaration evidence.",
    rules: NULL_RULES,
    fields: [
      { name: "checkout_id", type: "text", required: true },
      { name: "run_id", type: "text", required: true, relation: "tiq_runs.run_id" },
      { name: "idempotency_key", type: "text", required: true, note: "tiq-report-<run_id>-<attempt id>; a new key per attempt so an expired attempt never returns a stale session" },
      { name: "stripe_session_id", type: "text", required: false, note: "Set only after the test session is created" },
      { name: "amount_cents", type: "number", required: true, equals: 100 },
      { name: "currency", type: "text", required: true, equals: "usd" },
      { name: "status", type: "select", values: ["created", "paid", "expired", "failed"], required: true },
      { name: "age_gate_version", type: "text", required: true },
      { name: "age_evidence_kind", type: "select", values: ["self_attestation"], required: true },
      { name: "age_confirmed_at", type: "number", required: true },
      { name: "created_at", type: "number", required: true },
      { name: "closed_at", type: "number", required: false },
    ],
    indexes: [
      { name: "idx_tiq_checkouts_idempotency_unique", unique: true, columns: ["idempotency_key"] },
      { name: "idx_tiq_checkouts_session_unique", unique: true, columns: ["stripe_session_id"], partial: "stripe_session_id IS NOT NULL AND stripe_session_id != ''" },
      { name: "idx_tiq_checkouts_one_open_per_run", unique: true, columns: ["run_id"], partial: "status = 'created'" },
      { name: "idx_tiq_checkouts_run_status", unique: false, columns: ["run_id", "status"] },
    ],
    retention: "Expired and failed attempts deleted 90 days after closing. Paid attempts follow the entitlement's retention.",
  },
  {
    name: "tiq_payments",
    purpose: "Verified payment and webhook event records (one row per processed Stripe event that changes state).",
    rules: NULL_RULES,
    fields: [
      { name: "stripe_event_id", type: "text", required: true },
      { name: "event_type", type: "text", required: true },
      { name: "record_kind", type: "select", values: ["grant", "event"], required: true, note: "grant = the single payment row for a paid checkout; event = every other processed event" },
      { name: "checkout_id", type: "text", required: false, relation: "tiq_checkouts.checkout_id" },
      { name: "payment_intent_id", type: "text", required: false },
      { name: "amount_cents", type: "number", required: false },
      { name: "currency", type: "text", required: false },
      { name: "livemode", type: "bool", required: true, equals: false, note: "Test mode only in this proposal" },
      { name: "refund_status", type: "select", values: ["none", "refunded"], required: true },
      { name: "dispute_status", type: "select", values: ["none", "open"], required: true },
      { name: "received_at", type: "number", required: true },
    ],
    indexes: [
      { name: "idx_tiq_payments_event_unique", unique: true, columns: ["stripe_event_id"] },
      { name: "idx_tiq_payments_grant_intent_unique", unique: true, columns: ["payment_intent_id"], partial: "record_kind = 'grant' AND payment_intent_id IS NOT NULL" },
    ],
    retention: "Kept for the period set by the owner's accounting decision (section 6). Contains no card or customer details.",
  },
  {
    name: "tiq_entitlements",
    purpose: "Report access: run ownership link, authorized report access, revocation status.",
    rules: NULL_RULES,
    fields: [
      { name: "run_id", type: "text", required: true, relation: "tiq_runs.run_id" },
      { name: "checkout_id", type: "text", required: true, relation: "tiq_checkouts.checkout_id" },
      { name: "payment_intent_id", type: "text", required: true },
      { name: "status", type: "select", values: ["active", "revoked"], required: true },
      { name: "revoke_reason", type: "select", values: ["", "refunded", "disputed"], required: false },
      { name: "granted_at", type: "number", required: true },
      { name: "revoked_at", type: "number", required: false },
    ],
    indexes: [
      { name: "idx_tiq_entitlements_run_unique", unique: true, columns: ["run_id"] },
      { name: "idx_tiq_entitlements_intent_unique", unique: true, columns: ["payment_intent_id"] },
    ],
    retention: "Same as tiq_payments. Revoked entitlements are kept, never deleted, so a refund cannot be replayed into access.",
  },
]);

// Rollback: additive creation only. Rollback = delete these four collections, and only when each has zero records
// or the owner has approved deletion. No existing collection is altered by this proposal.
export const ROLLBACK = Object.freeze({
  steps: [
    "Confirm the four tiq_* collections contain only test records (or none).",
    "Take a full export of the four collections before any change.",
    "Delete tiq_entitlements, tiq_payments, tiq_checkouts, tiq_runs in that order (children first).",
    "Confirm no existing NIJA collection changed (compare against the pre-apply snapshot).",
  ],
  touches_existing: false,
});

export function validateSpec(spec = COLLECTIONS) {
  const problems = [];
  const seen = new Set();
  for (const c of spec) {
    if (!/^tiq_[a-z_]+$/.test(c.name)) problems.push(`bad_name:${c.name}`);
    if (EXISTING_NAMES.includes(c.name)) problems.push(`collides_existing:${c.name}`);
    if (seen.has(c.name)) problems.push(`duplicate:${c.name}`);
    seen.add(c.name);
    if (JSON.stringify(c.rules) !== JSON.stringify(NULL_RULES)) problems.push(`rules_not_null:${c.name}`);
    for (const f of c.fields) {
      if (FORBIDDEN_FIELD_PATTERN.test(f.name)) {
        problems.push(`forbidden_field:${c.name}.${f.name}`);
      }
    }
    const idxNames = new Set();
    for (const ix of c.indexes) {
      if (idxNames.has(ix.name)) problems.push(`dup_index:${ix.name}`);
      idxNames.add(ix.name);
    }
  }
  return problems;
}
