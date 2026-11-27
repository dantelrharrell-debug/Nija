import test from 'node:test';
import assert from 'node:assert/strict';
import {
  PRICE_ID, PRODUCT_ID, OFFER, checkoutEnabled, liveKey, issueProof, hashProof,
  matchesProof, cookieName, issueCookie, readProof, verifyPrice, verifyPurchase
} from '../server/checkout-security.mjs';

const price = { id: PRICE_ID, product: { id: PRODUCT_ID }, active: true,
  livemode: false, type: 'one_time', currency: 'usd', unit_amount: 100 };
const sessionId = 'cs_test_abcdefgh12345678';
function paid(proof) {
  return { id: sessionId, livemode: false, mode: 'payment', status: 'complete',
    payment_status: 'paid', amount_total: 100, currency: 'usd',
    metadata: { version: 'nija-trading-iq-v1', offer: OFFER, product: PRODUCT_ID,
      price: PRICE_ID, proof_sha256: hashProof(proof) },
    payment_intent: { status: 'succeeded', currency: 'usd', amount_received: 100,
      latest_charge: { paid: true, refunded: false, disputed: false,
        amount_refunded: 0, status: 'succeeded' } } };
}
const lines = { data: [{ quantity: 1, price: { id: PRICE_ID, product: PRODUCT_ID },
  amount_total: 100, currency: 'usd' }] };

test('feature gate is explicitly off unless configured', () => {
  assert.equal(checkoutEnabled('sk_test_mock', 'false'), false);
  assert.equal(checkoutEnabled('', 'true'), false);
  assert.equal(checkoutEnabled('sk_test_mock', 'true'), true);
});
test('restricted and standard Stripe credentials preserve mode and explicit gate', () => {
  for (const prefix of ['sk_test_', 'rk_test_', 'sk_live_', 'rk_live_']) {
    const key = prefix + 'mock123';
    assert.equal(checkoutEnabled(key, 'true'), true);
    assert.equal(checkoutEnabled(key, 'false'), false);
    assert.equal(checkoutEnabled(key, undefined), false);
    assert.equal(liveKey(key), prefix.includes('_live_'));
  }
  for (const key of ['', 'pk_live_mock123', 'rk_live_', 'rk_live_bad-value',
    'sk_test_bad value', 'rk_other_mock', 'sk_live_mock\\n', null, undefined, {}]) {
    assert.equal(checkoutEnabled(key, 'true'), false);
    assert.equal(liveKey(key), false);
  }
  assert.equal(checkoutEnabled('rk_live_mock123', 'TRUE'), false);
});

test('receipt proof is secret, random, hashed in Stripe, and cookie-bound', () => {
  const proof = issueProof();
  assert.match(proof, /^[a-f0-9]{64}$/);
  assert.notEqual(proof, issueProof());
  assert.equal(matchesProof(hashProof(proof), proof), true);
  assert.equal(matchesProof(hashProof(proof), issueProof()), false);
  assert.match(issueCookie(proof, true), /; Secure/);
  assert.match(issueCookie(proof, true), /HttpOnly/);
  assert.equal(readProof(cookieName(true) + '=' + proof, true), proof);
  assert.equal(readProof(cookieName(true) + '=' + proof + '; ' + cookieName(true) + '=' + proof, true), null);
  assert.equal(readProof(cookieName(true) + '=' + proof, false), null);
});
test('price identity refuses tampering', () => {
  assert.equal(verifyPrice(price, false), true);
  for (const [key, v] of [['unit_amount', 99], ['active', false], ['currency', 'eur'], ['livemode', true]]) {
    assert.equal(verifyPrice({ ...price, [key]: v }, false), false);
  }
  assert.equal(verifyPrice({ ...price, product: 'wrong' }, false), false);
});
test('only a complete, paid, unrefunded charge with matching browser proof unlocks report', () => {
  const proof = issueProof();
  const good = paid(proof);
  assert.equal(verifyPurchase(good, lines, proof, false, sessionId), true);
  assert.equal(verifyPurchase(good, lines, issueProof(), false, sessionId), false);
  assert.equal(verifyPurchase(good, lines, proof, true, sessionId), false);
  assert.equal(verifyPurchase(good, { data: [] }, proof, false, sessionId), false);
  for (const [k, v] of [['payment_status', 'unpaid'], ['status', 'open'], ['amount_total', 99]]) {
    assert.equal(verifyPurchase({ ...good, [k]: v }, lines, proof, false, sessionId), false);
  }
  for (const [k, v] of [['refunded', true], ['disputed', true], ['amount_refunded', 100], ['paid', false]]) {
    assert.equal(verifyPurchase({ ...good, payment_intent: { ...good.payment_intent,
      latest_charge: { ...good.payment_intent.latest_charge, [k]: v } } }, lines, proof, false, sessionId), false);
  }
  assert.equal(verifyPurchase(good, { data: [{ ...lines.data[0], quantity: 2 }] }, proof, false, sessionId), false);
});
