// Upgrade 6 test-mode orchestration; never imported by existing live game or
// Render holding service. Requires a separately approved canonical manifest,
// private initialized SQLite database, and a trusted Stripe TEST adapter.
import {
  validateTiq12Manifest, validateTiq12Answers, requireAdultCompletedRun,
  matchesTiq12WebhookPaymentSnapshot, scorePurchasedTiq12,
} from './tiq12-contract.mjs';
import {
  Upgrade6Error, requireTestConfiguration, requireBrowserOrigin,
  issueOwnerProof, hashOwnerProof, requireOwnerProof, requireAdultOptIn,
  fixedTiq12Checkout, verifyTiq12StripeWebhook, requireStripeTestSession,
} from './tiq12-upgrade6-security.mjs';

function requireRunId(id) {
  if (typeof id !== 'string' || !/^run_[0-9a-f]{32}$/.test(id)) {
    throw new Upgrade6Error('Invalid run identifier', 422);
  }
  return id;
}
function requireProvider(provider) {
  for (const method of ['verifyPrice','createCheckout','reconcileCheckout','resolveReversalSession']) {
    if (typeof provider?.[method] !== 'function') {
      throw new Upgrade6Error('Trusted Stripe adapter unavailable', 503);
    }
  }
  return provider;
}
export function createUpgrade6Service({ sourceManifest, approvedManifestDigest,
    store, provider, config, now = () => new Date() }) {
  const settings = requireTestConfiguration(config);
  const manifest = validateTiq12Manifest(sourceManifest);
  // This pin must come from independently authenticated IONOS source intake.
  // Never set it from the browser or derive it from unreviewed input.
  if (typeof approvedManifestDigest !== 'string' ||
      !/^[0-9a-f]{64}$/.test(approvedManifestDigest) ||
      manifest.digest !== approvedManifestDigest) {
    throw new Upgrade6Error('Canonical IONOS manifest not independently approved', 503);
  }
  if (!store || typeof store.createRun !== 'function' || typeof store.recordPaid !== 'function') {
    throw new Upgrade6Error('Private durable store unavailable', 503);
  }
  requireProvider(provider);
  const requireOrigin = origin => requireBrowserOrigin(origin, settings.allowedOrigin);
  const offer = Object.freeze({priceId:settings.priceId,productId:settings.productId});

  async function completeRun({answers,confirmedAdult,paidReportOptIn}, origin) {
    requireOrigin(origin);
    requireAdultOptIn({confirmedAdult,paidReportOptIn});
    const checked = validateTiq12Answers(manifest, answers);
    const ownerProof = issueOwnerProof();
    const saved = store.createRun({manifest,answers:checked,ownerProofHash:hashOwnerProof(ownerProof),
      completedAt:now().toISOString()});
    requireAdultCompletedRun(saved,manifest);
    return {runId:saved.id,ownerProof,manifestDigest:manifest.digest};
  }

  async function checkout({runId,ownerProof},origin) {
    requireOrigin(origin);requireRunId(runId);
    const run=store.getRun(runId);
    if (!run) throw new Upgrade6Error('Run not found',404);
    requireOwnerProof(ownerProof,run.ownerProofHash);
    requireAdultCompletedRun(run,manifest);
    if (store.getGrant(runId)) throw new Upgrade6Error('Already purchased',409);
    const priceValid=await provider.verifyPrice(offer);
    if (priceValid !== true) throw new Upgrade6Error('Stripe test price not verified',503);
    const reservation=store.reserveCheckout({runId,priceId:settings.priceId,
      productId:settings.productId,now:now().toISOString()});
    if (reservation.state==='paid' || reservation.state==='blocked' ||
        reservation.state==='canceled' || Date.parse(reservation.retry_deadline) < now().getTime()) {
      throw new Upgrade6Error('Existing checkout requires reconciliation',409);
    }
    if (reservation.checkout_session_id) {
      // Never mint a second session for the same run. A known session must
      // be independently inspected through Stripe and handled separately.
      throw new Upgrade6Error('Checkout already exists; resume existing session',409);
    }
    const intent=fixedTiq12Checkout({runId,manifestDigest:manifest.digest,
      ownerProofHash:run.ownerProofHash,config:settings});
    const session=await provider.createCheckout(intent,reservation.stripe_idempotency_key);
    requireStripeTestSession(session?.id);
    if (session?.livemode !== false || session?.mode !== 'payment' ||
        session?.amount_total !== 100 || session?.currency !== 'usd' ||
        typeof session?.url !== 'string' ||
        !session.url.startsWith('https://checkout.stripe.com/')) {
      throw new Upgrade6Error('Untrusted Stripe test checkout response',503);
    }
    store.attachSession(reservation.reservation_id,session.id);
    return {checkoutUrl:session.url,runId};
  }

  async function webhook(rawBody,signatureHeader) {
    const event=verifyTiq12StripeWebhook(rawBody,signatureHeader,config.webhookSecret,
      {nowSeconds:Math.floor(now().getTime()/1000)});
    if (store.hasEvent(event.id)) return {status:'duplicate'};
    if (event.type==='checkout.session.completed' ||
        event.type==='checkout.session.async_payment_succeeded') {
      const id=requireStripeTestSession(event.data?.object?.id);
      const reservation=store.getCheckoutBySession(id);
      if (!reservation) throw new Upgrade6Error('Unknown Checkout reservation',422);
      const storedRun=store.getRun(reservation.run_id);
      if (!storedRun) throw new Upgrade6Error('Missing run',422);
      const snapshot=await provider.reconcileCheckout(id);
      if (!matchesTiq12WebhookPaymentSnapshot({
        session:snapshot.session,lineItems:snapshot.lineItems,storedRun,manifest,
        expectedPriceId:offer.priceId,expectedProductId:offer.productId,livemode:false,
      })) {
        throw new Upgrade6Error('Current Stripe purchase not verified',422);
      }
      const intent=snapshot.session.payment_intent;
      const charge=intent.latest_charge;
      if (!/^pi_[A-Za-z0-9_]+$/.test(intent.id || '') ||
          !/^ch_[A-Za-z0-9_]+$/.test(charge.id || '')) {
        throw new Upgrade6Error('Payment identity unverified',422);
      }
      const when=now();
      const result=store.recordPaid({event,rawBody,reservation,
        paymentIntentId:intent.id,chargeId:charge.id,now:when.toISOString(),
        expiresAt:new Date(when.getTime()+365*86400000).toISOString()});
      return {status:result};
    }
    if (event.type==='charge.refunded' || event.type==='charge.dispute.created') {
      const sessionId=await provider.resolveReversalSession(event);
      requireStripeTestSession(sessionId);
      return {status:store.recordReversal({event,rawBody,sessionId,
        reason:event.type==='charge.refunded'?'refund':'dispute',now:now().toISOString()})};
    }
    return {status:store.recordIgnored(event,rawBody,now().toISOString())};
  }

  async function report({runId,ownerProof},origin) {
    requireOrigin(origin);requireRunId(runId);
    const run=store.getRun(runId);
    if (!run) throw new Upgrade6Error('Report not found',404);
    requireOwnerProof(ownerProof,run.ownerProofHash);
    const grant=store.getGrant(runId);
    if (!grant) throw new Upgrade6Error('Verified payment entitlement required',403);
    // Fail closed on provider outage, partial refund, or a reversal that has
    // not yet been delivered by a signed webhook.
    const snapshot=await provider.reconcileCheckout(grant.checkoutSessionId);
    if (!matchesTiq12WebhookPaymentSnapshot({
      session:snapshot.session,lineItems:snapshot.lineItems,storedRun:run,manifest,
      expectedPriceId:offer.priceId,expectedProductId:offer.productId,livemode:false,
    })) throw new Upgrade6Error('Current Stripe payment state not verified',403);
    return scorePurchasedTiq12(manifest,run,grant,offer);
  }
  return Object.freeze({completeRun,checkout,webhook,report});
}
