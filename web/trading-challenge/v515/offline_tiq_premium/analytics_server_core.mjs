/**
 * Trading IQ analytics — server-side rules (INACTIVE CANDIDATE, not wired to any route).
 * Injected store; no network. Wiring to real storage needs the protected-storage approval.
 */
const EVENTS = new Set(["visit", "tiq_game_start", "tiq_game_complete", "tiq_report_view", "tiq_checkout_attempt"]);
const ALLOWED = new Set(["event", "visitor_id", "run_id", "event_id", "variant", "consent"]);
const HEX32 = /^[a-f0-9]{32}$/;
const resp = (status, body) => ({ status, body });

/** 401 when not signed in, 403 when signed in but not an administrator of the users account type. */
export function requireAdmin(auth) {
  if (!auth || !auth.id) return resp(401, { error: "auth_required" });
  if (auth.collection !== "users" || auth.role !== "admin") return resp(403, { error: "forbidden" });
  return null;
}

export function validateEvent(body) {
  if (!body || typeof body !== "object" || Array.isArray(body)) return { ok: false, reason: "malformed" };
  if (Object.keys(body).some((k) => !ALLOWED.has(k))) return { ok: false, reason: "unexpected_fields" };
  if (body.consent !== true) return { ok: false, reason: "no_consent" };
  if (!EVENTS.has(body.event)) return { ok: false, reason: "bad_event" };
  if (!HEX32.test(String(body.visitor_id || ""))) return { ok: false, reason: "bad_visitor" };
  if (!HEX32.test(String(body.event_id || ""))) return { ok: false, reason: "bad_event_id" };
  if (body.event !== "visit" && !HEX32.test(String(body.run_id || ""))) return { ok: false, reason: "bad_run" };
  if (body.variant !== undefined && !/^(sim[a-z0-9_]{0,20}|live)$/.test(String(body.variant))) return { ok: false, reason: "bad_variant" };
  return { ok: true };
}

/** Duplicate-safe: the unique event_id means a replay changes nothing. */
export function recordEvent(store, body) {
  const v = validateEvent(body);
  if (!v.ok) return resp(v.reason === "no_consent" ? 204 : 400, { error: v.reason });
  if (store.events.has(body.event_id)) return resp(200, { recorded: false, duplicate: true });
  const { consent, ...row } = body;
  store.events.set(body.event_id, Object.freeze({ ...row, simulated: String(body.variant || "").startsWith("sim") }));
  return resp(200, { recorded: true });
}

const distinct = (rows, key) => new Set(rows.map((r) => r[key]).filter(Boolean)).size;

/** Visitors and runs are separate counts. */
export function counts(rows) {
  const starts = rows.filter((r) => r.event === "tiq_game_start");
  return { uniqueVisitors: distinct(rows, "visitor_id"), uniqueRuns: distinct(starts, "run_id") };
}

/** Real figures never include simulated rows. */
export function realSummary(store) {
  const rows = [...store.events.values()].filter((r) => !r.simulated);
  return { ...counts(rows), revenue: revenue(store.stripe) };
}

/** Simulated analytics: administrators only, enforced here. */
export function simulatedSummary(store, auth) {
  const deny = requireAdmin(auth);
  if (deny) return deny;
  return resp(200, counts([...store.events.values()].filter((r) => r.simulated)));
}

/** Authoritative Stripe server records only. Anything incomplete is UNVERIFIED, never invented. */
export function revenue(stripe) {
  if (!Array.isArray(stripe)) return { status: "UNVERIFIED", grossCents: null, refundCents: null, disputeCents: null, netCents: null };
  const ok = stripe.filter((p) => p && p.source === "stripe_server" && p.livemode === true && p.test !== true && p.simulated !== true
    && Number.isInteger(p.amount_cents) && p.amount_cents > 0 && /^pi_/.test(String(p.payment_ref || "")));
  const seen = new Set(); let gross = 0, refund = 0, dispute = 0;
  for (const p of ok) {
    if (seen.has(p.payment_ref)) continue; seen.add(p.payment_ref);
    gross += p.amount_cents;
    if (p.refunded_cents > 0) refund += Math.min(p.refunded_cents, p.amount_cents);
    if (p.disputed === true) dispute += p.amount_cents;
  }
  return { status: ok.length ? "VERIFIED" : "UNVERIFIED", grossCents: ok.length ? gross : null, refundCents: refund, disputeCents: dispute, netCents: ok.length ? gross - refund - dispute : null };
}
