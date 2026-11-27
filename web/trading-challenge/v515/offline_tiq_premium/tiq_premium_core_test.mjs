// Trading IQ premium report — offline tests for the server-side core (PREVIEW ONLY).
// No network, no real Stripe, no storage. Fixtures use a fake server key and a fake webhook secret.
import crypto from "node:crypto";
import * as core from "./tiq_premium_core.mjs";

let pass = 0, fail = 0;
function ok(name, cond) { if (cond) pass++; else { fail++; console.log("FAIL:", name); } }
function eq(name, got, want) { ok(`${name} (got ${JSON.stringify(got)}, want ${JSON.stringify(want)})`, JSON.stringify(got) === JSON.stringify(want)); }

const KEY = "k".repeat(40);          // fake server key
const SECRET = "whsec_fixture_" + "s".repeat(32); // fake webhook secret (test fixture only)
const NOW = 1_800_000_000_000;       // ms
const NOW_S = Math.floor(NOW / 1000);

const hold = { action: "hold", stop: false };
const decisions = Array.from({ length: 6 }, () => Array.from({ length: 12 }, () => ({ ...hold })));

function startedRun(extra = {}) {
  const s = core.startRun({ mode: "standard", level: "beginner", dayNum: 0, now: NOW, serverKey: KEY, ...extra });
  return s;
}
function completedRun() {
  const s = startedRun();
  const c = core.completeRun({ record: s.record, decisions, presentedCredential: s.credential, serverKey: KEY, now: NOW + 1000 });
  return { s, c, run: { ...s.record, ...c.update } };
}

// ---- Run start: server-issued identity, credential never stored in plain text ----
{
  const s = startedRun();
  ok("start ok", s.ok === true);
  ok("run id is 32 hex", /^[a-f0-9]{32}$/.test(s.record.id));
  ok("credential not in record", !JSON.stringify(s.record).includes(s.credential));
  ok("owner_hash is 64 hex", /^[a-f0-9]{64}$/.test(s.record.owner_hash));
  ok("credential length >= 40", s.credential.length >= 40);
  ok("no stray shell field", !("shell" in s));
  eq("bad mode rejected", core.startRun({ mode: "x", level: "beginner", dayNum: 0, now: NOW, serverKey: KEY }).reason, "bad_mode");
  eq("bad level rejected", core.startRun({ mode: "standard", level: "x", dayNum: 0, now: NOW, serverKey: KEY }).reason, "bad_level");
  eq("daily needs day", core.startRun({ mode: "daily", level: "beginner", dayNum: "2", now: NOW, serverKey: KEY }).reason, "bad_day");
  const a = startedRun(), b = startedRun();
  ok("ids unique", a.record.id !== b.record.id);
  ok("credentials unique", a.credential !== b.credential);
  let threw = false; try { core.hashOwnerCredential(s.credential, "short"); } catch { threw = true; }
  ok("short server key refused", threw);
}

// ---- Run completion: server-only scoring, ownership check, tamper rejection ----
{
  const { s, c, run } = completedRun();
  ok("complete ok", c.ok === true);
  ok("status completed", run.status === "completed");
  ok("score is 0..100 integer", Number.isInteger(run.total_score) && run.total_score >= 0 && run.total_score <= 100);
  eq("wrong credential forbidden", core.completeRun({ record: s.record, decisions, presentedCredential: "x".repeat(50), serverKey: KEY, now: NOW + 1 }).reason, "forbidden");
  eq("missing credential forbidden", core.completeRun({ record: s.record, decisions, presentedCredential: undefined, serverKey: KEY, now: NOW + 1 }).reason, "forbidden");
  const other = startedRun();
  eq("other run's credential forbidden", core.completeRun({ record: s.record, decisions, presentedCredential: other.credential, serverKey: KEY, now: NOW + 1 }).reason, "forbidden");
  eq("expired run refused", core.completeRun({ record: s.record, decisions, presentedCredential: s.credential, serverKey: KEY, now: s.record.expires_at + 1 }).reason, "expired");
  eq("already completed refused", core.completeRun({ record: run, decisions, presentedCredential: s.credential, serverKey: KEY, now: NOW + 2 }).reason, "not_open");
  const withScore = decisions.map((ch, i) => ch.map((d, j) => (i === 0 && j === 0 ? { ...d, score: 100 } : d)));
  eq("browser score field rejected", core.completeRun({ record: s.record, decisions: withScore, presentedCredential: s.credential, serverKey: KEY, now: NOW + 1 }).reason, "unexpected_field");
  const short = decisions.map((ch, i) => (i === 1 ? ch.slice(0, 11) : ch));
  eq("short challenge rejected", core.completeRun({ record: s.record, decisions: short, presentedCredential: s.credential, serverKey: KEY, now: NOW + 1 }).reason, "incomplete_challenge");
  const bad = decisions.map((ch, i) => (i === 0 ? ch.map((d, j) => (j === 0 ? { action: "moon", stop: false } : d)) : ch));
  eq("bad action rejected", core.completeRun({ record: s.record, decisions: bad, presentedCredential: s.credential, serverKey: KEY, now: NOW + 1 }).reason, "bad_action");
  // Same decisions always give the same score (server is deterministic).
  const again = core.completeRun({ record: s.record, decisions, presentedCredential: s.credential, serverKey: KEY, now: NOW + 5 });
  eq("score deterministic", again.update.total_score, run.total_score);
}

// ---- Stripe-style webhook signature ----
function sign(body, t = NOW_S, secret = SECRET) {
  const sig = crypto.createHmac("sha256", secret).update(`${t}.${body}`).digest("hex");
  return `t=${t},v1=${sig}`;
}
{
  const body = JSON.stringify({ id: "evt_1", type: "checkout.session.completed" });
  ok("valid signature accepted", core.verifyWebhookSignature({ rawBody: body, header: sign(body), secret: SECRET, nowSeconds: NOW_S }).ok === true);
  eq("tampered body rejected", core.verifyWebhookSignature({ rawBody: body + " ", header: sign(body), secret: SECRET, nowSeconds: NOW_S }).reason, "bad_signature");
  eq("wrong secret rejected", core.verifyWebhookSignature({ rawBody: body, header: sign(body, NOW_S, "whsec_other"), secret: SECRET, nowSeconds: NOW_S }).reason, "bad_signature");
  eq("stale timestamp rejected", core.verifyWebhookSignature({ rawBody: body, header: sign(body, NOW_S - 3600), secret: SECRET, nowSeconds: NOW_S }).reason, "stale");
  eq("missing header rejected", core.verifyWebhookSignature({ rawBody: body, header: undefined, secret: SECRET, nowSeconds: NOW_S }).reason, "bad_signature");
  eq("no secret rejected", core.verifyWebhookSignature({ rawBody: body, header: sign(body), secret: "", nowSeconds: NOW_S }).reason, "bad_signature");
  eq("non-numeric timestamp rejected", core.verifyWebhookSignature({ rawBody: body, header: `t=abc,v1=00`, secret: SECRET, nowSeconds: NOW_S }).reason, "bad_signature");
}

// ---- Checkout planning: one open checkout per run, no duplicate charge ----
{
  const { run } = completedRun();
  const open = { id: "chk_1", status: "created", created_at: NOW };
  const p = core.planCheckout({ run, existingCheckouts: [], mode: "test", now: NOW + 1000 });
  ok("test checkout created", p.ok && p.create && p.create.amount_cents === 100 && p.create.currency === "usd");
  eq("idempotency key from run id", p.create.idempotency_key, `tiq-report-${run.id}`);
  eq("reuses open checkout", core.planCheckout({ run, existingCheckouts: [open], mode: "test", now: NOW + 1000 }), { ok: true, reuse: "chk_1" });
  const stale = { id: "chk_old", status: "created", created_at: NOW - core.CHECKOUT_TTL_MS - 1 };
  ok("stale checkout not reused", core.planCheckout({ run, existingCheckouts: [stale], mode: "test", now: NOW + 1000 }).create !== undefined);
  eq("already paid blocks new checkout", core.planCheckout({ run, existingCheckouts: [{ status: "paid" }], mode: "test", now: NOW }).reason, "already_paid");
  eq("live mode disabled", core.planCheckout({ run, existingCheckouts: [], mode: "live", now: NOW }).reason, "payments_disabled");
  const { s } = completedRun();
  eq("open run cannot pay", core.planCheckout({ run: s.record, existingCheckouts: [], mode: "test", now: NOW }).reason, "run_not_completed");
  eq("expired run cannot pay", core.planCheckout({ run: { ...run, expires_at: NOW - 1 }, existingCheckouts: [], mode: "test", now: NOW }).reason, "expired");
  let threw = false; try { core.checkoutIdempotencyKey("../../etc"); } catch { threw = true; }
  ok("bad run id refused for idempotency key", threw);
}

// ---- Payment event interpretation: only signed-equivalent, matching, test-mode, correct-amount data counts ----
{
  const checkout = { id: "chk_1", stripe_session_id: "cs_test_1" };
  const ev = (type, o = {}) => ({ type, data: { object: { id: "cs_test_1", client_reference_id: "chk_1", livemode: false, amount_total: 100, currency: "usd", payment_status: "paid", payment_intent: "pi_1", ...o } } });
  eq("paid test session grants", core.interpretPaymentEvent({ event: ev("checkout.session.completed"), checkout, serverMode: "test" }).action, "grant");
  eq("unpaid session does not grant", core.interpretPaymentEvent({ event: ev("checkout.session.completed", { payment_status: "unpaid" }), checkout, serverMode: "test" }).action, "ignore");
  eq("live event in test server refused", core.interpretPaymentEvent({ event: ev("checkout.session.completed", { livemode: true }), checkout, serverMode: "test" }).reason, "mode_mismatch");
  eq("wrong amount refused", core.interpretPaymentEvent({ event: ev("checkout.session.completed", { amount_total: 1 }), checkout, serverMode: "test" }).reason, "amount_mismatch");
  eq("wrong currency refused", core.interpretPaymentEvent({ event: ev("checkout.session.completed", { currency: "eur" }), checkout, serverMode: "test" }).reason, "amount_mismatch");
  eq("different checkout refused", core.interpretPaymentEvent({ event: ev("checkout.session.completed", { client_reference_id: "chk_9" }), checkout, serverMode: "test" }).reason, "checkout_mismatch");
  eq("different session id refused", core.interpretPaymentEvent({ event: ev("checkout.session.completed", { id: "cs_test_other" }), checkout, serverMode: "test" }).reason, "checkout_mismatch");
  eq("session id alone is not enough (client ref must match)", core.interpretPaymentEvent({ event: ev("checkout.session.completed", { client_reference_id: null }), checkout, serverMode: "test" }).reason, "checkout_mismatch");
  eq("unknown checkout refused", core.interpretPaymentEvent({ event: ev("checkout.session.completed"), checkout: null, serverMode: "test" }).reason, "unknown_checkout");
  eq("expired session closes", core.interpretPaymentEvent({ event: ev("checkout.session.expired"), checkout, serverMode: "test" }).action, "close");
  eq("refund revokes", core.interpretPaymentEvent({ event: ev("charge.refunded"), checkout, serverMode: "test" }).reason, "refunded");
  eq("dispute revokes", core.interpretPaymentEvent({ event: ev("charge.dispute.created"), checkout, serverMode: "test" }).reason, "disputed");
  eq("unrelated event ignored", core.interpretPaymentEvent({ event: ev("customer.created"), checkout, serverMode: "test" }).action, "ignore");
}

// ---- Idempotent apply: duplicates write nothing ----
{
  const grant = { action: "grant", payment_intent_id: "pi_1" };
  const empty = { processedEvents: new Set(), entitlement: null, payments: [] };
  eq("first grant writes", core.applyPaymentAction({ action: grant, state: empty, eventId: "evt_1" }).write, "grant");
  eq("repeated event id writes nothing", core.applyPaymentAction({ action: grant, state: { ...empty, processedEvents: new Set(["evt_1"]) }, eventId: "evt_1" }).reason, "duplicate_event");
  eq("second event for granted report writes nothing", core.applyPaymentAction({ action: grant, state: { ...empty, entitlement: { status: "active" } }, eventId: "evt_2" }).reason, "already_granted");
  eq("same payment intent under new event writes nothing", core.applyPaymentAction({ action: grant, state: { ...empty, payments: [{ payment_intent_id: "pi_1" }] }, eventId: "evt_3" }).reason, "duplicate_payment");
  eq("refund writes revoke", core.applyPaymentAction({ action: { action: "revoke", reason: "refunded" }, state: empty, eventId: "evt_4" }).write, "revoke");
  eq("close writes nothing", core.applyPaymentAction({ action: { action: "close" }, state: empty, eventId: "evt_5" }).changed, false);
}

// ---- Report access: credential + completed run + active entitlement ----
{
  const { s, run } = completedRun();
  const active = { status: "active" };
  eq("owner with active report opens", core.canOpenReport({ run, entitlement: active, presentedCredential: s.credential, serverKey: KEY }).ok, true);
  eq("no credential: not found", core.canOpenReport({ run, entitlement: active, presentedCredential: undefined, serverKey: KEY }).reason, "not_found");
  eq("wrong credential: not found", core.canOpenReport({ run, entitlement: active, presentedCredential: "y".repeat(50), serverKey: KEY }).reason, "not_found");
  const other = startedRun();
  eq("other owner: not found", core.canOpenReport({ run, entitlement: active, presentedCredential: other.credential, serverKey: KEY }).reason, "not_found");
  eq("session id as credential refused", core.canOpenReport({ run, entitlement: active, presentedCredential: "cs_test_1234567890", serverKey: KEY }).reason, "not_found");
  eq("no purchase: not purchased", core.canOpenReport({ run, entitlement: null, presentedCredential: s.credential, serverKey: KEY }).reason, "not_purchased");
  eq("refunded: access revoked", core.canOpenReport({ run, entitlement: { status: "refunded" }, presentedCredential: s.credential, serverKey: KEY }).reason, "refunded");
  eq("disputed: access revoked", core.canOpenReport({ run, entitlement: { status: "revoked" }, presentedCredential: s.credential, serverKey: KEY }).reason, "revoked");
  eq("open run: not found", core.canOpenReport({ run: s.record, entitlement: active, presentedCredential: s.credential, serverKey: KEY }).reason, "not_found");
  const rep = core.reportFromRun(run);
  ok("report carries disclaimer", rep.disclaimer.includes("does not guarantee trading profits"));
  ok("report has no owner hash or credential", !JSON.stringify(rep).includes(run.owner_hash) && !JSON.stringify(rep).includes(s.credential));
  eq("report marked fictional", rep.generated_for, "fictional_data_only");
}

console.log(`PASS: ${pass}, FAIL: ${fail}`);
process.exit(fail ? 1 : 0);
