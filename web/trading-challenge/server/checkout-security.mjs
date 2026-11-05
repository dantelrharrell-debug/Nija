import { createHash, randomBytes, timingSafeEqual } from 'node:crypto';

export const PRICE_ID = 'price_1UY9YmI0gfJjTf3E1h6mYC2S';
export const PRODUCT_ID = 'prod_VZI9N8jDpFrQMt';
export const OFFER = 'nija-trading-iq-results-v1';
export const SESSION_ID = /^cs_(?:test|live)_[A-Za-z0-9_]{8,250}$/;
const PROOF = /^[a-f0-9]{64}$/;

function prop(value, key) {
  return value && typeof value === 'object' ? value[key] : undefined;
}
function id(value) {
  return typeof value === 'string' ? value : prop(value, 'id');
}
export function checkoutEnabled(key, flag) {
  return flag === 'true' && typeof key === 'string' && /^sk_(?:test|live)_[A-Za-z0-9_]+$/.test(key);
}
export function liveKey(key) { return key.startsWith('sk_live_'); }
export function issueProof() { return randomBytes(32).toString('hex'); }
export function hashProof(proof) { return createHash('sha256').update(proof, 'utf8').digest('hex'); }
export function matchesProof(storedHash, proof) {
  if (typeof storedHash !== 'string' || !PROOF.test(storedHash) ||
      typeof proof !== 'string' || !PROOF.test(proof)) return false;
  return timingSafeEqual(Buffer.from(storedHash, 'hex'), Buffer.from(hashProof(proof), 'hex'));
}
export function cookieName(secure) { return secure ? '__Host-nija-iq-report' : 'nija-iq-report-local'; }
export function issueCookie(proof, secure) {
  if (!PROOF.test(proof)) throw new Error('Invalid receipt proof');
  return `${cookieName(secure)}=${proof}; Path=/; HttpOnly; SameSite=Lax; Max-Age=604800${secure ? '; Secure' : ''}`;
}
export function readProof(raw, secure) {
  if (typeof raw !== 'string' || raw.length > 8192) return null;
  const matches = raw.split(';').map(chunk => chunk.trim()).filter(chunk => chunk.startsWith(cookieName(secure) + '='));
  if (matches.length !== 1) return null;
  const value = matches[0].slice(cookieName(secure).length + 1);
  return PROOF.test(value) ? value : null;
}
export function verifyPrice(price, isLive) {
  return Boolean(price && price.id === PRICE_ID && price.active === true &&
    price.livemode === isLive && price.type === 'one_time' &&
    price.currency === 'usd' && price.unit_amount === 100 && id(price.product) === PRODUCT_ID);
}
export function verifyPurchase(session, lines, proof, isLive, expectedId) {
  if (!SESSION_ID.test(expectedId || '') || !matchesProof(session?.metadata?.proof_sha256, proof)) return false;
  if (session.id !== expectedId || session.livemode !== isLive ||
      session.mode !== 'payment' || session.status !== 'complete' ||
      session.payment_status !== 'paid' || session.amount_total !== 100 ||
      session.currency !== 'usd' || session.metadata?.version !== 'nija-trading-iq-v1' ||
      session.metadata?.offer !== OFFER || session.metadata?.product !== PRODUCT_ID ||
      session.metadata?.price !== PRICE_ID) return false;
  const intent = session.payment_intent;
  const charge = intent && intent.latest_charge;
  if (!intent || intent.status !== 'succeeded' || intent.currency !== 'usd' ||
      intent.amount_received !== 100 || !charge || charge.paid !== true ||
      charge.refunded !== false || charge.disputed !== false ||
      charge.amount_refunded !== 0 || charge.status !== 'succeeded') return false;
  const lineItems = lines?.data;
  if (!Array.isArray(lineItems) || lineItems.length !== 1) return false;
  const line = lineItems[0];
  return line.quantity === 1 && id(line.price) === PRICE_ID &&
    id(line.price?.product) === PRODUCT_ID && line.amount_total === 100 &&
    line.currency === 'usd';
}
