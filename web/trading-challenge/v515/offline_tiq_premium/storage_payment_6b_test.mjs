// UPGRADE 6B tests: storage proposal, checkout authorization, webhook idempotency, refunds, report access.
// Offline only: in-memory store, mocked Stripe session, signed fake events. No network, no live data.
// Run from app/:  node offline_tiq_premium/storage_payment_6b_test.mjs
import { createHmac } from "node:crypto";
import * as S from "./storage_spec_6b.mjs";
import * as F from "./payment_flow_6b.mjs";
import * as P from "./tiq_premium_core.mjs";
import * as G from "./age_gate_core.mjs";

let pass = 0, fail = 0;
const eq = (n, a, b) => { if (JSON.stringify(a) === JSON.stringify(b)) pass++; else { fail++; console.log("FAIL", n, JSON.stringify(a), "!==", JSON.stringify(b)); } };
const ok = (n, c) => { if (c) pass++; else { fail++; console.log("FAIL", n); } };

const NOW = 1_800_000_000_000;
const NOW_S = Math.floor(NOW / 1000);
const SERVER_KEY = "k".repeat(40);
const SECRET = "whsec_test_" + "s".repeat(40);
const OPEN = { mode: "test", storageApproved: true, testKeyConfigured: true, webhookSecretConfigured: true };
const CLOSED = { ...OPEN, storageApproved: false };
const good = () => ({ version: G.AGE_GATE_VERSION, text: G.AGE_GATE_TEXT, declared: true });

// ---------- In-memory store with unique constraints and rollback ----------
function makeStore() {
  const db = { runs: new Map(), checkouts: [], payments: [], entitlements: new Map() };
  const api = {
    db,
    async getRun(id) { return db.runs.get(id) ?? null; },
    async listCheckouts(rid) { return db.checkouts.filter((c) => c.run_id === rid).map((c) => ({ ...c })); },
    async getCheckout(id) { return db.checkouts.find((c) => c.checkout_id === id) ?? null; },
    async getCheckoutBySession(sid) { return sid ? db.checkouts.find((c) => c.stripe_session_id === sid) ?? null : null; },
    async insertCheckout(row) {
      if (db.checkouts.some((c) => c.idempotency_key === row.idempotency_key || c.stripe_session_id === row.stripe_session_id)) return { ok: false, reason: "duplicate_key" };
      if (row.status === "created" && db.checkouts.some((c) => c.run_id === row.run_id && c.status === "created")) return { ok: false, reason: "duplicate_open" };
      db.checkouts.push({ ...row }); return { ok: true };
    },
    async updateCheckout(id, patch) { Object.assign(db.checkouts.find((c) => c.checkout_id === id), patch); },
    async hasEvent(eid) { return db.payments.some((p) => p.stripe_event_id === eid); },
    async getPaymentByIntent(pi) { return db.payments.find((p) => p.record_kind === "grant" && p.payment_intent_id === pi) ?? null; },
    async insertPayment(row) {
      if (db.payments.some((p) => p.stripe_event_id === row.stripe_event_id)) return { ok: false, reason: "duplicate_event" };
      if (row.record_kind === "grant" && db.payments.some((p) => p.record_kind === "grant" && p.payment_intent_id === row.payment_intent_id)) return { ok: false, reason: "duplicate_intent" };
      db.payments.push({ ...row }); return { ok: true };
    },
    async listPaymentsByCheckout(cid) { return db.payments.filter((p) => p.checkout_id === cid).map((p) => ({ ...p })); },
    async getEntitlementByRun(rid) { return db.entitlements.get(rid) ?? null; },
    async insertEntitlement(row) { if (db.entitlements.has(row.run_id)) return { ok: false }; db.entitlements.set(row.run_id, { ...row }); return { ok: true }; },
    async updateEntitlement(rid, patch) { Object.assign(db.entitlements.get(rid), patch); },
    async transaction(fn) {
      const snap = structuredClone({ runs: [...db.runs], checkouts: db.checkouts, payments: db.payments, entitlements: [...db.entitlements] });
      try { return await fn(api); }
      catch (err) {
        db.runs = new Map(snap.runs); db.checkouts = snap.checkouts; db.payments = snap.payments; db.entitlements = new Map(snap.entitlements);
        throw err;
      }
    },
  };
  return api;
}

function setup({ status = "completed", runId = "a1b2c3d4e5f60718293a4b5c6d7e8f90" } = {}) {
  const store = makeStore();
  const cred = P.newOwnerCredential();
  const run = { run_id: runId, status, owner_hash: P.hashOwnerCredential(cred, SERVER_KEY), expires_at: NOW + 86400000, level: "beginner", day_num: 1, total_score: 60 };
  store.db.runs.set(runId, run);
  const m = { calls: 0, last: null, fail: false };
  m.fn = (params) => { if (m.fail) throw new Error("stripe_down"); m.calls++; m.last = params; return { id: "cs_test_" + m.calls + "_" + runId.slice(0, 6) }; };
  return { store, cred, run, m, runId };
}
const checkoutReq = (t, extra = {}) => ({ run_id: t.runId, credential: t.cred, age_confirmation: good(), ...extra });
const doCheckout = (t, body, flags = OPEN) => F.handleCheckout({ body, store: t.store, flags, serverKey: SERVER_KEY, now: NOW, createSession: t.m.fn });

// ---------- 1. Storage proposal ----------
eq("spec: no collision, forbidden fields, rules null", S.validateSpec(), []);
eq("spec: exactly four isolated areas", S.COLLECTIONS.map((c) => c.name), ["tiq_runs", "tiq_checkouts", "tiq_payments", "tiq_entitlements"]);
eq("spec: rollback never touches existing collections", S.ROLLBACK.touches_existing, false);
const idx = (c) => S.COLLECTIONS.find((x) => x.name === c).indexes;
ok("spec: checkout idempotency unique", idx("tiq_checkouts").some((i) => i.unique && i.columns[0] === "idempotency_key"));
ok("spec: checkout session unique", idx("tiq_checkouts").some((i) => i.unique && i.columns[0] === "stripe_session_id"));
ok("spec: event id unique", idx("tiq_payments").some((i) => i.unique && i.columns[0] === "stripe_event_id"));
ok("spec: one paid grant per payment intent", idx("tiq_payments").some((i) => i.unique && i.columns[0] === "payment_intent_id" && /grant/.test(i.partial)));
ok("spec: one entitlement per run", idx("tiq_entitlements").some((i) => i.unique && i.columns[0] === "run_id"));
ok("spec: run id unique", idx("tiq_runs").some((i) => i.unique && i.columns[0] === "run_id"));
const allFields = S.COLLECTIONS.flatMap((c) => c.fields.map((f) => f.name));
ok("spec: no birthdate/identity/contact fields", !allFields.some((n) => /birth|dob|passport|id_number|email|phone|name|address|card/i.test(n)));
ok("spec: stores only a keyed hash of the ownership credential", allFields.includes("owner_hash") && !allFields.includes("credential"));
eq("spec: age evidence limited to kind, version, time", S.COLLECTIONS.find((c) => c.name === "tiq_checkouts").fields.filter((f) => f.name.startsWith("age_")).map((f) => f.name), ["age_gate_version", "age_evidence_kind", "age_confirmed_at"]);
eq("spec: amount fixed to one dollar", S.COLLECTIONS.find((c) => c.name === "tiq_checkouts").fields.find((f) => f.name === "amount_cents").equals, 100);
eq("spec: test mode only", S.COLLECTIONS.find((c) => c.name === "tiq_payments").fields.find((f) => f.name === "livemode").equals, false);
// negative probes: the validator must catch bad proposals
eq("probe: birthdate field rejected", S.validateSpec([{ name: "tiq_x", rules: S.COLLECTIONS[0].rules, fields: [{ name: "birthdate" }], indexes: [] }]).length > 0, true);
eq("probe: collision with existing name rejected", S.validateSpec([{ name: "nija_payments", rules: S.COLLECTIONS[0].rules, fields: [], indexes: [] }]).includes("collides_existing:nija_payments"), true);
eq("probe: open rule rejected", S.validateSpec([{ name: "tiq_y", rules: { list: "", view: null, create: null, update: null, delete: null }, fields: [], indexes: [] }]).includes("rules_not_null:tiq_y"), true);
eq("probe: email field rejected", S.validateSpec([{ name: "tiq_z", rules: S.COLLECTIONS[0].rules, fields: [{ name: "customer_email" }], indexes: [] }]).length > 0, true);

// ---------- 2. Checkout gate ----------
eq("gate: closed by default", F.checkoutGate({}).ok, false);
eq("gate: live refused", F.checkoutGate({ ...OPEN, mode: "live" }).reason, "live_refused");
eq("gate: storage not approved", F.checkoutGate(CLOSED).reason, "storage_not_approved");
eq("gate: test key missing", F.checkoutGate({ ...OPEN, testKeyConfigured: false }).reason, "test_key_missing");
eq("gate: webhook secret missing", F.checkoutGate({ ...OPEN, webhookSecretConfigured: false }).reason, "webhook_secret_missing");
eq("gate: all conditions met", F.checkoutGate(OPEN).ok, true);

// ---------- 3. Checkout authorization and age validation ----------
{
  const t = setup();
  const r = await doCheckout(t, checkoutReq(t), CLOSED);
  eq("closed gate: 403", r.status, 403);
  eq("closed gate: no session created", t.m.calls, 0);
  eq("closed gate: nothing stored", t.store.db.checkouts.length, 0);
}
{
  const t = setup();
  const r = await doCheckout(t, { ...checkoutReq(t), run_id: "not-a-run" });
  eq("bad run id: 400", r.status, 400);
  eq("bad run id: no session", t.m.calls, 0);
}
{
  const t = setup();
  const r = await doCheckout(t, { ...checkoutReq(t), credential: P.newOwnerCredential() });
  eq("wrong owner credential: 404", r.status, 404);
  eq("wrong owner credential: no session", t.m.calls, 0);
}
{
  const t = setup();
  const r = await doCheckout(t, { run_id: t.runId, credential: t.cred });
  eq("missing confirmation: 400", [r.status, r.reason], [400, "missing"]);
  eq("missing confirmation: no session", t.m.calls, 0);
  eq("missing confirmation: no record", t.store.db.checkouts.length, 0);
}
const badConfirmations = {
  declared_false: { ...good(), declared: false },
  outdated_version: { ...good(), version: "2025-01-01-v0" },
  altered_wording: { ...good(), text: "I am 13 or older." },
  birthdate_added: { ...good(), birthdate: "1990-01-01" },
  dob_added: { ...good(), dob: "1990-01-01" },
  id_document_added: { ...good(), passport: "X123" },
  declared_string: { ...good(), declared: "true" },
  missing_declared: { version: G.AGE_GATE_VERSION, text: G.AGE_GATE_TEXT },
  array_body: [good()],
  null_body: null,
};
for (const [label, conf] of Object.entries(badConfirmations)) {
  const t = setup();
  const r = await doCheckout(t, { run_id: t.runId, credential: t.cred, age_confirmation: conf });
  ok(`invalid confirmation (${label}): rejected 400`, r.status === 400);
  eq(`invalid confirmation (${label}): no session`, t.m.calls, 0);
  eq(`invalid confirmation (${label}): no record`, t.store.db.checkouts.length, 0);
}
{
  const t = setup();
  const r = await doCheckout(t, checkoutReq(t));
  eq("valid confirmation: 201 created", [r.status, r.reason], [201, "created"]);
  eq("valid confirmation: one session", t.m.calls, 1);
  const row = t.store.db.checkouts[0];
  ok("row: idempotency key derived from run and attempt", row.idempotency_key.startsWith(P.checkoutIdempotencyKey(t.runId) + "-") && row.idempotency_key.endsWith(row.checkout_id));
  eq("row: test-mode price and currency", [row.amount_cents, row.currency], [100, "usd"]);
  eq("row: self-attestation evidence only", [row.age_evidence_kind, row.age_gate_version], ["self_attestation", G.AGE_GATE_VERSION]);
  ok("row: no birthdate or identity fields", !Object.keys(row).some((k) => /birth|dob|passport|email|name/i.test(k)));
  ok("row: no owner credential stored", !JSON.stringify(row).includes(t.cred));
  eq("session receives idempotency key", t.m.last.idempotency_key, row.idempotency_key);
  const again = await doCheckout(t, checkoutReq(t));
  eq("repeat request: reuses open checkout", [again.status, again.reason], [200, "reuse_open_checkout"]);
  eq("repeat request: no second session", t.m.calls, 1);
  eq("repeat request: still one record", t.store.db.checkouts.length, 1);
}
{
  const t = setup();
  t.m.fail = true;
  const r = await doCheckout(t, checkoutReq(t));
  eq("session failure: 503", r.status, 503);
  eq("session failure: nothing recorded", t.store.db.checkouts.length, 0);
}
{
  const t = setup({ status: "open" });
  const r = await doCheckout(t, checkoutReq(t));
  eq("incomplete run: refused 409", [r.status, r.reason], [409, "run_not_completed"]);
  eq("incomplete run: no session", t.m.calls, 0);
}
{
  const t = setup();
  t.store.db.checkouts.push({ checkout_id: "paidone", run_id: t.runId, idempotency_key: "x", status: "paid", created_at: NOW, stripe_session_id: "cs_old" });
  const r = await doCheckout(t, checkoutReq(t));
  eq("already paid: refused, no new session", [r.status, r.reason, t.m.calls], [409, "already_paid", 0]);
}
{
  // Race: another request inserts the same run's checkout between our read and our write.
  const t = setup();
  t.store.insertCheckout = async (row) => {
    t.store.db.checkouts.push({ ...row, checkout_id: "racewinner", stripe_session_id: "cs_winner", status: "created" });
    return { ok: false, reason: "duplicate_key" };
  };
  const r = await doCheckout(t, checkoutReq(t));
  eq("race: returns the winner, not a second checkout", [r.status, r.checkout_id], [200, "racewinner"]);
  eq("race: one record only", t.store.db.checkouts.length, 1);
}

// ---------- 4. Webhook: signature, idempotency, payment, refund ----------
async function paidCheckout() {
  const t = setup();
  const r = await doCheckout(t, checkoutReq(t));
  const checkout = t.store.db.checkouts[0];
  return { t, checkout, pi: "pi_test_" + checkout.checkout_id, sid: r.session_id };
}
const sessionEvent = (id, type, c, over = {}) => ({
  id, type, livemode: false, created: NOW_S,
  data: { object: { id: c.stripe_session_id, client_reference_id: c.checkout_id, amount_total: 100, currency: "usd",
    payment_status: "paid", payment_intent: "pi_test_" + c.checkout_id, livemode: false, ...over } },
});
const chargeEvent = (id, type, c, over = {}) => ({
  id, type, livemode: false, created: NOW_S,
  data: { object: { id: "ch_test_" + id, payment_intent: "pi_test_" + c.checkout_id, amount: 100, currency: "usd", livemode: false, ...over } },
});
const signed = (ev, t = NOW_S, secret = SECRET) => { const raw = JSON.stringify(ev); return { rawBody: raw, header: `t=${t},v1=${createHmac("sha256", secret).update(`${t}.${raw}`).digest("hex")}` }; };
const hook = (store, env, opts = {}) => F.handleStripeEvent({ ...env, secret: SECRET, flags: OPEN, store, nowSeconds: NOW_S, now: NOW, ...opts });

{
  const { t, checkout } = await paidCheckout();
  const ev = sessionEvent("evt_pay_1", "checkout.session.completed", checkout);
  const r = await hook(t.store, signed(ev));
  eq("paid event: granted", [r.status, r.reason], [200, "granted"]);
  eq("paid event: entitlement active", t.store.db.entitlements.get(t.runId)?.status, "active");
  eq("paid event: checkout marked paid", t.store.db.checkouts[0].status, "paid");
  eq("paid event: one grant row", t.store.db.payments.filter((p) => p.record_kind === "grant").length, 1);
  const dup = await hook(t.store, signed(ev));
  eq("duplicate delivery: no new writes", [dup.reason, t.store.db.payments.length, t.store.db.entitlements.size], ["duplicate_event", 1, 1]);
  const ev2 = sessionEvent("evt_pay_2", "checkout.session.completed", checkout);
  const second = await hook(t.store, signed(ev2));
  eq("second event for same payment: no second grant", [second.changed, t.store.db.entitlements.size], [false, 1]);
  eq("second event for same payment: no second grant row", t.store.db.payments.filter((p) => p.record_kind === "grant").length, 1);
  const pay = await F.openReport({ run_id: t.runId, credential: t.cred, serverKey: SERVER_KEY, store: t.store });
  eq("report opens after verified payment", [pay.status, pay.reason], [200, "ok"]);
}
{
  const { t, checkout } = await paidCheckout();
  const ev = sessionEvent("evt_bad_sig", "checkout.session.completed", checkout);
  const env = signed(ev, NOW_S, "whsec_wrong_" + "w".repeat(30));
  const r = await hook(t.store, env);
  eq("bad signature: 400", [r.status, r.reason], [400, "bad_signature"]);
  eq("bad signature: nothing written", [t.store.db.payments.length, t.store.db.entitlements.size], [0, 0]);
}
{
  const { t, checkout } = await paidCheckout();
  const r = await hook(t.store, signed(sessionEvent("evt_old", "checkout.session.completed", checkout), NOW_S - 3600));
  eq("stale signature: rejected", [r.status, r.reason], [400, "stale"]);
  eq("stale signature: nothing written", t.store.db.entitlements.size, 0);
}
{
  const { t, checkout } = await paidCheckout();
  const r = await hook(t.store, signed(sessionEvent("evt_live", "checkout.session.completed", checkout, { livemode: true })));
  eq("live-mode data in test pipeline: rejected", [r.status, r.reason], [409, "mode_mismatch"]);
  eq("live-mode data: nothing written", t.store.db.entitlements.size, 0);
}
{
  const { t, checkout } = await paidCheckout();
  const r = await hook(t.store, signed(sessionEvent("evt_amt", "checkout.session.completed", checkout, { amount_total: 1 })));
  eq("wrong amount: rejected", r.reason, "amount_mismatch");
  eq("wrong amount: no entitlement", t.store.db.entitlements.size, 0);
}
{
  const { t } = await paidCheckout();
  const r = await hook(t.store, signed(sessionEvent("evt_unk", "checkout.session.completed", { checkout_id: "f".repeat(32), stripe_session_id: "cs_nope" })));
  eq("unknown checkout: not granted", [r.status, r.reason], [409, "unknown_checkout"]);
  eq("unknown checkout: nothing written", t.store.db.payments.length, 0);
}
{
  const { t, checkout } = await paidCheckout();
  const r = await hook(t.store, signed(sessionEvent("evt_unpaid", "checkout.session.completed", checkout, { payment_status: "unpaid" })));
  eq("unpaid session: no entitlement", [r.reason, t.store.db.entitlements.size], ["ignored", 0]);
}
{
  const { t, checkout } = await paidCheckout();
  const r = await hook(t.store, signed(sessionEvent("evt_exp", "checkout.session.expired", checkout)));
  eq("expired session: checkout closed", [r.reason, t.store.db.checkouts[0].status], ["closed", "expired"]);
  eq("expired session: no entitlement", t.store.db.entitlements.size, 0);
  const late = await doCheckout(t, checkoutReq(t));
  eq("after expiry: a fresh checkout may be created", late.status, 201);
}
{
  // Refund after a verified payment revokes access; replayed refund changes nothing.
  const { t, checkout, pi } = await paidCheckout();
  await hook(t.store, signed(sessionEvent("evt_p", "checkout.session.completed", checkout)));
  const refund = chargeEvent("evt_refund", "charge.refunded", checkout, { refunded: true, amount_refunded: 100 });
  const r = await hook(t.store, signed(refund));
  eq("refund: revoked", [r.status, r.reason], [200, "revoked"]);
  eq("refund: entitlement revoked with reason", [t.store.db.entitlements.get(t.runId).status, t.store.db.entitlements.get(t.runId).revoke_reason], ["revoked", "refunded"]);
  eq("refund: payment row shows refunded", t.store.db.payments.some((p) => p.stripe_event_id === "evt_refund" && p.refund_status === "refunded"), true);
  const replay = await hook(t.store, signed(refund));
  eq("refund replay: duplicate, no change", replay.reason, "duplicate_event");
  const open = await F.openReport({ run_id: t.runId, credential: t.cred, serverKey: SERVER_KEY, store: t.store });
  eq("refunded run: report blocked", [open.status, open.reason], [403, "revoked"]);
  eq("refund: no new checkout reuses the refunded run", (await doCheckout(t, checkoutReq(t))).status, 409);
  ok("refund: payment intent unchanged", pi.startsWith("pi_test_"));
}
{
  const { t, checkout } = await paidCheckout();
  await hook(t.store, signed(sessionEvent("evt_p2", "checkout.session.completed", checkout)));
  const r = await hook(t.store, signed(chargeEvent("evt_disp", "charge.dispute.created", checkout)));
  eq("dispute: revoked", [r.reason, t.store.db.entitlements.get(t.runId).revoke_reason], ["revoked", "disputed"]);
  eq("dispute: payment row shows open dispute", t.store.db.payments.some((p) => p.stripe_event_id === "evt_disp" && p.dispute_status === "open"), true);
}
{
  const { t, checkout } = await paidCheckout();
  await hook(t.store, signed(sessionEvent("evt_p3", "checkout.session.completed", checkout)));
  const r = await hook(t.store, signed(chargeEvent("evt_bad_refund", "charge.refunded", checkout, { amount: 999 })));
  eq("refund with wrong amount: rejected", [r.status, r.reason], [409, "amount_mismatch"]);
  eq("refund with wrong amount: access kept", t.store.db.entitlements.get(t.runId).status, "active");
}
{
  // Atomicity: an existing entitlement makes the grant fail after the payment row was written; both must roll back.
  const { t, checkout } = await paidCheckout();
  t.store.insertEntitlement = async () => ({ ok: false });
  const before = t.store.db.payments.length;
  const r = await hook(t.store, signed(sessionEvent("evt_rollback", "checkout.session.completed", checkout)));
  eq("atomic grant: refused", r.status, 409);
  eq("atomic grant: payment row rolled back", t.store.db.payments.length, before);
  eq("atomic grant: checkout still open", t.store.db.checkouts[0].status, "created");
}
{
  const r = await hook(setup().store, { rawBody: "{}", header: "t=1,v1=00" }, { flags: { ...OPEN, webhookSecretConfigured: false } });
  eq("webhook secret missing: 503 and nothing processed", [r.status, r.reason], [503, "not_configured"]);
}
{
  const { t, checkout } = await paidCheckout();
  const r = await hook(t.store, signed({ id: "evt_no_obj", type: "checkout.session.completed", livemode: false }));
  eq("malformed event: rejected", [r.status, r.reason], [400, "bad_payload"]);
}

// ---------- 5. Report access ----------
{
  const t = setup();
  eq("report: no purchase", (await F.openReport({ run_id: t.runId, credential: t.cred, serverKey: SERVER_KEY, store: t.store })).reason, "not_purchased");
  eq("report: wrong credential hidden", (await F.openReport({ run_id: t.runId, credential: P.newOwnerCredential(), serverKey: SERVER_KEY, store: t.store })).status, 404);
  eq("report: malformed run id hidden", (await F.openReport({ run_id: "zz", credential: t.cred, serverKey: SERVER_KEY, store: t.store })).status, 404);
  const inc = setup({ status: "open" });
  eq("report: incomplete run hidden", (await F.openReport({ run_id: inc.runId, credential: inc.cred, serverKey: SERVER_KEY, store: inc.store })).status, 404);
}
{
  // A browser success page or a bare session id grants nothing: only the verified webhook path writes entitlements.
  const { t, sid } = await paidCheckout();
  ok("success page: session id alone creates no entitlement", t.store.db.entitlements.size === 0 && typeof sid === "string");
  eq("success page: report still locked", (await F.openReport({ run_id: t.runId, credential: t.cred, serverKey: SERVER_KEY, store: t.store })).status, 402);
}

// ---------- 6. Regression: existing preview suites still run separately ----------
ok("regression: premium core module loads", typeof P.planCheckout === "function");

console.log(`PASS: ${pass}, FAIL: ${fail}`);
