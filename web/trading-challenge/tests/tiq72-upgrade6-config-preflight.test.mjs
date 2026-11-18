import test from 'node:test';
import assert from 'node:assert/strict';
import { randomBytes } from 'node:crypto';
import { inspectTiq72TestConfig } from '../server/tiq72-upgrade6-config-preflight.mjs';
// Generated fixtures exercise credential shape without retaining reusable values.
// inspectTiq72TestConfig is pure; no provider or database requests are made.
const credential = prefix => prefix + randomBytes(24).toString('hex');
const databaseUrl = new URL('postgres://localhost/test');
databaseUrl.username = 'fixture';
databaseUrl.password = credential('');
const good = {
 STRIPE_TEST_SECRET_KEY:credential('sk_test_'), STRIPE_TEST_WEBHOOK_SECRET:credential('whsec_'),
 TIQ72_STRIPE_TEST_PRICE_ID:'price_test123',TIQ72_STRIPE_TEST_PRODUCT_ID:'prod_test123',
 DATABASE_URL:databaseUrl.href,
 TIQ72_TEST_RETURN_ORIGIN:'https://nija.example',
 TIQ_ALLOWED_ORIGIN:'https://nija.example',
 NIJA_GAME_REPORTS_ENABLED:'false',NIJA_GAME_BROWSER_CHECKOUT_ENABLED:'false'
};
test('valid synthetic config never claims payment certification', () => {
 const r=inspectTiq72TestConfig(good);
 assert.equal(r.config_ready,true);
 assert.equal(r.checkout_activation_authorized,false);
 assert.equal(r.migration_verified,false);
 assert.equal(r.sandbox_e2e_verified,false);
});
test('missing secrets fail without exposing secret values', () => {
 const wrongMode = credential('sk_live_');
 const r=inspectTiq72TestConfig({...good,STRIPE_TEST_SECRET_KEY:wrongMode,
 STRIPE_TEST_WEBHOOK_SECRET:''});
 assert.equal(r.config_ready,false);
 assert.ok(r.errors.includes('test_secret_missing_or_wrong_mode'));
 assert.ok(!JSON.stringify(r).includes(wrongMode));
});
test('unsafe return origins and live flags fail closed', () => {
 for(const origin of ['http://nija.example','https://nija.example.evil.test/path',
  'https://nija.example/path','https://user@nija.example','https://nija.example:8443']) {
  const r=inspectTiq72TestConfig({...good,TIQ72_TEST_RETURN_ORIGIN:origin});
  assert.equal(r.config_ready,false);
 }
 const r=inspectTiq72TestConfig({...good,TIQ72_LIVE_PAYMENTS_ENABLED:'true'});
 assert.ok(r.errors.includes('live_mode_must_be_disabled'));
});
test('legacy checkout cannot be enabled',()=>{
 const r=inspectTiq72TestConfig({...good,NIJA_GAME_BROWSER_CHECKOUT_ENABLED:'true'});
 assert.ok(r.errors.includes('legacy_checkout_must_be_disabled'));
});

test('verified NIJA sandbox product identifier is valid without accepting a malformed ID', () => {
 const match = inspectTiq72TestConfig({
  ...good,
  TIQ72_STRIPE_TEST_PRICE_ID:'price_1UYToJRS5Ezp77RQVkx96eS5',
  TIQ72_STRIPE_TEST_PRODUCT_ID:'prod_nija_iq72_sandbox_v1'
 });
 assert.equal(match.config_ready,true);
 assert.ok(!match.errors.includes('test_product_missing'));
 for (const invalid of ['prod_nija iQ72', 'prod_nija/iQ72', 'prod_', 'prod_abc\\nX']) {
  const failed=inspectTiq72TestConfig({...good,TIQ72_STRIPE_TEST_PRODUCT_ID:invalid});
  assert.equal(failed.config_ready,false);
  assert.ok(failed.errors.includes('test_product_missing'));
 }
});
