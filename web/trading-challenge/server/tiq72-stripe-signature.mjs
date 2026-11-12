// Verify Stripe's signed raw webhook payload before parsing JSON.
// This helper does not grant entitlements or enable checkout.
import { createHmac, timingSafeEqual } from 'node:crypto';

export function verifyStripeWebhook(rawBody, signatureHeader, secret, nowSeconds = Math.floor(Date.now()/1000)) {
  if (!Buffer.isBuffer(rawBody) || rawBody.length === 0 || rawBody.length > 1024*1024) throw new TypeError('invalid_raw_body');
  if (typeof signatureHeader !== 'string' || signatureHeader.length > 4096 ||
      typeof secret !== 'string' || !secret.startsWith('whsec_')) throw new TypeError('invalid_signature_configuration');
  const fields = signatureHeader.split(',').map(s => s.trim());
  const timestamps = fields.filter(s => /^t=\d+$/.test(s));
  const signatures = fields.filter(s => /^v1=[a-f0-9]{64}$/i.test(s));
  if (timestamps.length !== 1 || signatures.length === 0) throw new Error('invalid_stripe_signature');
  const timestamp = Number(timestamps[0].slice(2));
  if (!Number.isSafeInteger(timestamp) || Math.abs(nowSeconds-timestamp)>300) throw new Error('stale_stripe_signature');
  const expected = createHmac('sha256',secret).update(String(timestamp)).update('.').update(rawBody).digest();
  const valid = signatures.some(s => timingSafeEqual(expected,Buffer.from(s.slice(3),'hex')));
  if (!valid) throw new Error('invalid_stripe_signature');
  const event = JSON.parse(rawBody.toString('utf8'));
  if (!event || typeof event !== 'object' || typeof event.id !== 'string' ||
      !/^evt_[A-Za-z0-9]+$/.test(event.id) || typeof event.type !== 'string' || event.livemode !== false ||
      !event.data || typeof event.data !== 'object' || !event.data.object ||
      typeof event.data.object !== 'object' || Array.isArray(event.data.object)) throw new Error('invalid_stripe_event');
  return event;
}
