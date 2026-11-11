// Server-side adult confirmation gate for the future $1 Trading IQ report checkout (preview).
// Self-attestation only: this is NOT independent age verification. No birthdate, identity
// document or other personal data is accepted. Pure functions. The checkout creator is
// injected and is called only after every check passes. Not wired to any live route.
import { planCheckout } from "./tiq_premium_core.mjs";

export const AGE_GATE_VERSION = "2026-11-04-v1";
export const AGE_GATE_TEXT =
  "I confirm that I am 18 years of age or older. I understand this is a self-declaration and is not independently verified.";
const ALLOWED_KEYS = Object.freeze(["version", "text", "declared"]);
const REQUIRED_KEYS = Object.freeze(["version", "text", "declared"]);

function fail(reason) {
  return { ok: false, reason };
}

function isPlainObject(v) {
  if (v === null || typeof v !== "object" || Array.isArray(v)) return false;
  const proto = Object.getPrototypeOf(v);
  return proto === Object.prototype || proto === null;
}

// Returns { ok: true, reason: "ok" } or { ok: false, reason }.
// Fail-closed: anything not exactly the approved shape is refused.
export function validateAgeConfirmation(body) {
  if (body === undefined || body === null) return fail("missing");
  if (!isPlainObject(body)) return fail("malformed");
  if (Object.keys(body).some((k) => !ALLOWED_KEYS.includes(k))) return fail("unexpected_fields");
  if (REQUIRED_KEYS.some((k) => !Object.prototype.hasOwnProperty.call(body, k))) return fail("missing");
  if (typeof body.version !== "string" || typeof body.text !== "string" || typeof body.declared !== "boolean") {
    return fail("malformed");
  }
  if (body.version !== AGE_GATE_VERSION) return fail("outdated_version");
  if (body.text !== AGE_GATE_TEXT) return fail("text_mismatch");
  if (body.declared !== true) return fail("not_declared");
  return { ok: true, reason: "ok" };
}

// Minimum evidence kept with a purchase: the approved version and the time. No wording
// copy, no personal data.
export function evidenceRecord(now) {
  return { kind: "self_attestation", age_gate_version: AGE_GATE_VERSION, confirmed_at: now };
}

// Order matters: the declaration is validated FIRST. An invalid request never reaches
// planCheckout or createSession, so it cannot create a checkout session.
export function planAgeGatedCheckout({ confirmation, run, existingCheckouts = [], mode, now, createSession }) {
  const gate = validateAgeConfirmation(confirmation);
  if (!gate.ok) return { ok: false, reason: gate.reason, session: null };

  const plan = planCheckout({ run, existingCheckouts, mode, now });
  if (!plan.ok) return { ok: false, reason: plan.reason, session: null };
  if (plan.reuse) return { ok: true, reason: "reuse_open_checkout", reuse: plan.reuse, session: null };

  if (typeof createSession !== "function") return { ok: false, reason: "no_session_creator", session: null };

  let session;
  try {
    session = createSession({ ...plan.create, age_gate_version: AGE_GATE_VERSION });
  } catch (_e) {
    return { ok: false, reason: "session_failed", session: null };
  }
  if (!session || typeof session.id !== "string" || session.id === "") {
    return { ok: false, reason: "session_failed", session: null };
  }
  return { ok: true, reason: "created", session, evidence: evidenceRecord(now) };
}
