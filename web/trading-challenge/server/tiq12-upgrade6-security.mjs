// Upgrade 6 test-mode security primitives. Private backend only; not an IONOS bundle.
import { createHash, createHmac, randomBytes, timingSafeEqual } from 'node:crypto';

const HEX64 = /^[0-9a-f]{64}$/;
const STRIPE_TEST_SECRET = /^sk_test_[A-Za-z0-9]{8,}$/;
const STRIPE_SIGNING_SECRET = /^whsec_[A-Za-z0-9]{8,}$/;
const STRIPE_PRICE = /^price_[A-Za-z0-9_]{3,250}$/;
const STRIPE_PRODUCT = /^prod_[A-Za-z0-9_]{3,250}$/;
const STRIPE_EVENT = /^evt_[A-Za-z0-9_]{3,250}$/;
const STRIPE_SESSION = /^cs_test_[A-Za-z0-9_]{8,250}$/;

export class Upgrade6Error extends Error {
  constructor(message, status = 400) {
    super(message);
    this.name = 'Upgrade6Error';
    this.status = status;
  }
}

export function requireTestConfiguration(config) {
  if (!config || config.mode !== 'test' || config.enabled !== true ||
      !STRIPE_TEST_SECRET.test(config.stripeSecret || '') ||
      !STRIPE_SIGNING_SECRET.test(config.webhookSecret || '') ||
      !STRIPE_PRICE.test(config.priceId || '') ||
      !STRIPE_PRODUCT.test(config.productId || '')) {
    throw new Upgrade6Error('Test-mode configuration unavailable', 503);
  }
  let origin;
  try {
    origin = new URL(config.allowedOrigin);
  } catch {
    throw new Upgrade6Error('Exact HTTPS origin required', 503);
  }
  if (origin.protocol !== 'https:' || origin.username || origin.password ||
      origin.pathname !== '/' || origin.search || origin.hash ||
      origin.origin !== config.allowedOrigin || origin.hostname.includes('*')) {
    throw new Upgrade6Error('Exact HTTPS origin required', 503);
  }
  return Object.freeze({
    mode: 'test', enabled: true, priceId: config.priceId,
    productId: config.productId, allowedOrigin: origin.origin,
  });
}

export function requireBrowserOrigin(actualOrigin, expectedOrigin) {
  if (typeof actualOrigin !== 'string' || actualOrigin !== expectedOrigin) {
    throw new Upgrade6Error('Origin denied', 403);
  }
  return true;
}

export function issueOwnerProof() {
  return randomBytes(32).toString('hex');
}

export function hashOwnerProof(proof) {
  if (typeof proof !== 'string' || !HEX64.test(proof)) {
    throw new Upgrade6Error('Invalid owner proof', 403);
  }
  return createHash('sha256').update(proof, 'ascii').digest('hex');
}

export function requireOwnerProof(proof, storedHash) {
  if (typeof storedHash !== 'string' || !HEX64.test(storedHash)) {
    throw new Upgrade6Error('Ownership denied', 403);
  }
  const candidate = hashOwnerProof(proof);
  if (!timingSafeEqual(Buffer.from(candidate, 'hex'), Buffer.from(storedHash, 'hex'))) {
    throw new Upgrade6Error('Ownership denied', 403);
  }
  return true;
}

export function fixedTiq12Checkout({ runId, manifestDigest, ownerProofHash, config }) {
  if (!/^run_[0-9a-f]{32}$/.test(runId || '') ||
      !HEX64.test(manifestDigest || '') || !HEX64.test(ownerProofHash || '') ||
      !STRIPE_PRICE.test(config?.priceId || '') || !STRIPE_PRODUCT.test(config?.productId || '')) {
    throw new Upgrade6Error('Invalid stored checkout identity', 422);
  }
  return Object.freeze({
    mode: 'payment', line_items: [{ price: config.priceId, quantity: 1 }],
    metadata: {
      run_id: runId, game_version: 'nija-trading-iq-12-v1',
      manifest_digest: manifestDigest, owner_proof_hash: ownerProofHash,
    },
  });
}

// Stripe signs t + '.' + the ORIGINAL raw UTF-8 body. Never parse first.
export function verifyTiq12StripeWebhook(rawBody, signatureHeader, signingSecret,
    { nowSeconds = Math.floor(Date.now() / 1000), toleranceSeconds = 300 } = {}) {
  const raw = Buffer.isBuffer(rawBody) ? rawBody :
    (typeof rawBody === 'string' ? Buffer.from(rawBody, 'utf8') : null);
  if (!raw || raw.length < 2 || raw.length > 262144 ||
      typeof signatureHeader !== 'string' || signatureHeader.length > 4096 ||
      !STRIPE_SIGNING_SECRET.test(signingSecret || '') ||
      !Number.isSafeInteger(nowSeconds) || !Number.isSafeInteger(toleranceSeconds) ||
      toleranceSeconds < 1 || toleranceSeconds > 300) {
    throw new Upgrade6Error('Webhook authentication failed', 400);
  }
  const parts = signatureHeader.split(',').map(x => x.trim());
  const ts = parts.filter(x => /^t=\d{1,15}$/.test(x));
  const sigs = parts.filter(x => /^v1=[a-fA-F0-9]{64}$/.test(x));
  if (ts.length !== 1 || sigs.length < 1 || sigs.length > 10) {
    throw new Upgrade6Error('Webhook authentication failed', 400);
  }
  const timestamp = Number(ts[0].slice(2));
  if (!Number.isSafeInteger(timestamp) || timestamp <= 0 ||
      Math.abs(nowSeconds - timestamp) > toleranceSeconds) {
    throw new Upgrade6Error('Webhook authentication failed', 400);
  }
  const mac = createHmac('sha256', signingSecret)
    .update(Buffer.from(`${timestamp}.`, 'utf8')).update(raw).digest();
  const valid = sigs.some(s => timingSafeEqual(mac, Buffer.from(s.slice(3), 'hex')));
  if (!valid) throw new Upgrade6Error('Webhook authentication failed', 400);
  let event;
  try { event = JSON.parse(raw.toString('utf8')); }
  catch { throw new Upgrade6Error('Invalid webhook JSON', 400); }
  if (!event || event.livemode !== false ||
      !STRIPE_EVENT.test(event.id || '') || typeof event.type !== 'string' ||
      !event.data || typeof event.data !== 'object') {
    throw new Upgrade6Error('Unsupported Stripe test event', 400);
  }
  return event;
}

export function requireStripeTestSession(sessionId) {
  if (!STRIPE_SESSION.test(sessionId || '')) {
    throw new Upgrade6Error('Invalid test Checkout session', 422);
  }
  return sessionId;
}

export function requireAdultOptIn(value) {
  if (!value || value.confirmedAdult !== true || value.paidReportOptIn !== true) {
    throw new Upgrade6Error('Adult consent and optional report opt-in required', 403);
  }
  return true;
}
