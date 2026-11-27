// UPGRADE 6B — checkout and webhook flow for the optional $1 report, TEST MODE ONLY.
// Pure logic with an injected store and injected Stripe call. Nothing here is wired to a live route.
// Checkout stays disabled (checkoutGate returns ok:false) until storage is approved AND test keys are configured.
import { PRICE_CENTS, CURRENCY, planCheckout, newId, hashOwnerCredential, safeEqualHex,
  verifyWebhookSignature, interpretPaymentEvent, applyPaymentAction, checkoutIdempotencyKey } from "./tiq_premium_core.mjs";
import { planAgeGatedCheckout, AGE_GATE_VERSION } from "./age_gate_core.mjs";

const ID_RE = /^[a-f0-9]{32}$/;

// Flags default to closed. Any missing or false flag keeps checkout off.
export function checkoutGate(flags = {}) {
  if (flags.mode !== "test") return { ok: false, reason: "live_refused" };
  if (flags.storageApproved !== true) return { ok: false, reason: "storage_not_approved" };
  if (flags.testKeyConfigured !== true) return { ok: false, reason: "test_key_missing" };
  if (flags.webhookSecretConfigured !== true) return { ok: false, reason: "webhook_secret_missing" };
  return { ok: true, reason: "enabled" };
}

function ownsRun(run, credential, serverKey) {
  let got = null;
  try { got = hashOwnerCredential(credential, serverKey); } catch (_e) { return false; }
  return got !== null && run.owner_hash !== undefined && safeEqualHex(got, run.owner_hash);
}

const AGE_STATUS = { missing: 400, malformed: 400, unexpected_fields: 400, outdated_version: 400,
  text_mismatch: 400, not_declared: 400, not_found: 404, bad_run_id: 400, forbidden: 403 };

// POST checkout. Order: gate -> run id shape -> ownership -> age declaration -> plan -> session -> record.
export async function handleCheckout({ body, store, flags, serverKey, now, createSession }) {
  const gate = checkoutGate(flags);
  if (!gate.ok) return { status: 403, reason: gate.reason };
  const b = body && typeof body === "object" ? body : {};
  if (typeof b.run_id !== "string" || !ID_RE.test(b.run_id)) return { status: 400, reason: "bad_run_id" };
  const run = await store.getRun(b.run_id);
  if (!run || !ownsRun(run, b.credential, serverKey)) return { status: 404, reason: "not_found" };

  const attemptId = newId();
  const attemptKey = `${checkoutIdempotencyKey(run.run_id)}-${attemptId}`;
  const existing = (await store.listCheckouts(run.run_id)).map((c) => ({ ...c, id: c.checkout_id }));
  const res = await planAgeGatedCheckout({
    confirmation: b.age_confirmation,
    run: { id: run.run_id, status: run.status, expires_at: run.expires_at },
    existingCheckouts: existing,
    mode: "test",
    now,
    createSession: createSession && ((params) => createSession({ ...params, idempotency_key: attemptKey })),
  });
  if (!res.ok) {
    const status = AGE_STATUS[res.reason] ?? (res.reason === "session_failed" || res.reason === "no_session_creator" ? 503 : 409);
    return { status, reason: res.reason };
  }
  if (res.reuse) return { status: 200, reason: "reuse_open_checkout", checkout_id: res.reuse };

  const row = {
    checkout_id: attemptId, run_id: run.run_id, idempotency_key: attemptKey,
    stripe_session_id: res.session.id, amount_cents: PRICE_CENTS, currency: CURRENCY, status: "created",
    age_gate_version: AGE_GATE_VERSION, age_evidence_kind: "self_attestation",
    age_confirmed_at: now, created_at: now,
  };
  const saved = await store.insertCheckout(row);
  if (!saved.ok) {
    // Another request won the race for this run: hand back the open checkout instead of a second one.
    const again = (await store.listCheckouts(run.run_id)).find((c) => c.status === "created");
    return again ? { status: 200, reason: "reuse_open_checkout", checkout_id: again.checkout_id } : { status: 409, reason: "duplicate_checkout" };
  }
  return { status: 201, reason: "created", checkout_id: row.checkout_id, session_id: row.stripe_session_id };
}

// POST webhook. Signature first, then event shape, then duplicate check, then one atomic write.
export async function handleStripeEvent({ rawBody, header, secret, flags, store, nowSeconds, now }) {
  if (flags?.webhookSecretConfigured !== true || !secret) return { status: 503, reason: "not_configured" };
  const sig = verifyWebhookSignature({ rawBody, header, secret, nowSeconds });
  if (!sig.ok) return { status: 400, reason: sig.reason };

  let event;
  try { event = JSON.parse(rawBody); } catch (_e) { return { status: 400, reason: "bad_payload" }; }
  const o = event?.data?.object;
  if (typeof event?.id !== "string" || typeof event?.type !== "string" || !o || typeof o !== "object") {
    return { status: 400, reason: "bad_payload" };
  }
  if (event.livemode !== false) return { status: 400, reason: "mode_mismatch" };
  if (await store.hasEvent(event.id)) return { status: 200, reason: "duplicate_event", changed: false };

  let checkout = null;
  let action;
  if (event.type.startsWith("checkout.session.")) {
    checkout = (await store.getCheckoutBySession(o.id)) ?? (await store.getCheckout(o.client_reference_id));
    action = interpretPaymentEvent({ event, checkout: checkout && { ...checkout, id: checkout.checkout_id }, serverMode: "test" });
  } else if (event.type.startsWith("charge.")) {
    const payment = typeof o.payment_intent === "string" ? await store.getPaymentByIntent(o.payment_intent) : null;
    checkout = payment ? await store.getCheckout(payment.checkout_id) : null;
    if (!checkout) action = { ok: false, reason: "unknown_checkout" };
    else if (o.livemode !== false) action = { ok: false, reason: "mode_mismatch" };
    else if (o.amount !== PRICE_CENTS || o.currency !== CURRENCY) action = { ok: false, reason: "amount_mismatch" };
    else if (event.type === "charge.refunded") action = { ok: true, action: "revoke", reason: "refunded", payment_intent_id: o.payment_intent };
    else if (event.type === "charge.dispute.created") action = { ok: true, action: "revoke", reason: "disputed", payment_intent_id: o.payment_intent };
    else action = { ok: true, action: "ignore" };
  } else {
    action = { ok: true, action: "ignore" };
  }
  if (!action.ok) return { status: 409, reason: action.reason, changed: false };

  try { return await store.transaction(async (tx) => {
    if (await tx.hasEvent(event.id)) return { status: 200, reason: "duplicate_event", changed: false };
    const entitlement = await tx.getEntitlementByRun(checkout.run_id);
    const payments = await tx.listPaymentsByCheckout(checkout.checkout_id);
    const state = { processedEvents: { has: () => false }, entitlement, payments };
    const applied = applyPaymentAction({ action, state, eventId: event.id });
    if (!applied.changed && applied.reason !== "no_change") return { status: 200, reason: applied.reason, changed: false };

    const base = { record_kind: "event", stripe_event_id: event.id, event_type: event.type, checkout_id: checkout.checkout_id,
      livemode: false, refund_status: "none", dispute_status: "none", received_at: now };

    if (applied.write === "grant") {
      const pi = action.payment_intent_id;
      const p = await tx.insertPayment({ ...base, record_kind: "grant", payment_intent_id: pi, amount_cents: PRICE_CENTS, currency: CURRENCY });
      if (!p.ok) throw Object.assign(new Error("tx_abort"), { txReason: "duplicate_payment" });
      const e = await tx.insertEntitlement({ run_id: checkout.run_id, checkout_id: checkout.checkout_id,
        payment_intent_id: pi, status: "active", granted_at: now });
      if (!e.ok) throw Object.assign(new Error("tx_abort"), { txReason: "already_granted" });
      await tx.updateCheckout(checkout.checkout_id, { status: "paid", closed_at: now });
      return { status: 200, reason: "granted", changed: true };
    }
    if (applied.write === "revoke") {
      const pi = action.payment_intent_id ?? checkout.payment_intent_id ?? null;
      const refund = action.reason === "refunded" ? "refunded" : "none";
      const dispute = action.reason === "disputed" ? "open" : "none";
      await tx.insertPayment({ ...base, payment_intent_id: pi, refund_status: refund, dispute_status: dispute, amount_cents: PRICE_CENTS, currency: CURRENCY });
      if (entitlement) await tx.updateEntitlement(checkout.run_id, { status: "revoked", revoke_reason: action.reason, revoked_at: now });
      return { status: 200, reason: entitlement ? "revoked" : "no_entitlement", changed: true };
    }
    if (action.action === "close") {
      await tx.insertPayment({ ...base });
      if (checkout.status === "created") await tx.updateCheckout(checkout.checkout_id, { status: "expired", closed_at: now });
      return { status: 200, reason: "closed", changed: true };
    }
    await tx.insertPayment({ ...base });
    return { status: 200, reason: "ignored", changed: false };
  }); } catch (err) { if (err && err.txReason) return { status: 409, reason: err.txReason, changed: false }; throw err; }
}

// Report access: browser proves ownership with its credential; entitlement must be active.
export async function openReport({ run_id, credential, serverKey, store }) {
  if (typeof run_id !== "string" || !ID_RE.test(run_id)) return { status: 404, reason: "not_found" };
  const run = await store.getRun(run_id);
  if (!run || run.status !== "completed" || !ownsRun(run, credential, serverKey)) return { status: 404, reason: "not_found" };
  const e = await store.getEntitlementByRun(run_id);
  if (!e) return { status: 402, reason: "not_purchased" };
  if (e.status !== "active") return { status: 403, reason: e.status };
  return { status: 200, reason: "ok" };
}

export { planCheckout };
