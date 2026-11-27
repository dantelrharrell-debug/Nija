import test from 'node:test';
import { randomUUID } from 'node:crypto';
import assert from 'node:assert/strict';
import { inspectTiq72TestConfig } from '../server/tiq72-upgrade6-config-preflight.mjs';

// Synthetic credentials only: no production or sandbox secrets are read here.
const disposableToken = prefix => prefix + randomUUID();
const valid = () => ({
  STRIPE_TEST_SECRET_KEY: disposableToken('sk_test_'),
  STRIPE_TEST_WEBHOOK_SECRET: disposableToken('whsec_'),
  TIQ72_TEST_OWNER_SIGNING_KEY_B64URL: Buffer.alloc(32, 7).toString('base64url'),
  TIQ72_STRIPE_TEST_PRICE_ID: 'price_123',
  TIQ72_STRIPE_TEST_PRODUCT_ID: 'prod_123',
  DATABASE_URL: 'postgresql://example.invalid/test',
  TIQ72_TEST_RETURN_ORIGIN: 'https://example.test',
  TIQ_ALLOWED_ORIGIN: 'https://example.test'
});
test('synthetic complete configuration passes presence checks but never authorizes checkout', () => {
  const result = inspectTiq72TestConfig(valid());
  assert.equal(result.config_ready, true);
  assert.equal(result.checkout_activation_authorized, false);
  assert.equal(result.migration_verified, false);
  assert.equal(result.fulfillment_verified, false);
  assert.equal(result.sandbox_e2e_verified, false);
});
test('missing sandbox API key is distinguished from wrong-mode credential', () => {
  const missing = valid();
  delete missing.STRIPE_TEST_SECRET_KEY;
  assert.deepEqual(inspectTiq72TestConfig(missing).errors, ['test_secret_missing']);
  const wrong = { ...valid(), STRIPE_TEST_SECRET_KEY: disposableToken('sk_live_') };
  assert.deepEqual(inspectTiq72TestConfig(wrong).errors, ['test_secret_wrong_mode']);
});
test('missing and invalid owner signing keys fail closed', () => {
  const missing = valid();
  delete missing.TIQ72_TEST_OWNER_SIGNING_KEY_B64URL;
  assert.ok(inspectTiq72TestConfig(missing).errors.includes('owner_signing_key_missing'));
  const invalid = { ...valid(), TIQ72_TEST_OWNER_SIGNING_KEY_B64URL: 'short' };
  assert.ok(inspectTiq72TestConfig(invalid).errors.includes('owner_signing_key_invalid'));
});
test('live payments and legacy checkout cannot be enabled through configuration', () => {
  for (const patch of [
    { STRIPE_LIVE_MODE: 'true' },
    { TIQ72_LIVE_PAYMENTS_ENABLED: 'true' },
    { NIJA_GAME_REPORTS_ENABLED: 'true' },
    { NIJA_GAME_BROWSER_CHECKOUT_ENABLED: 'true' }
  ]) {
    const result = inspectTiq72TestConfig({ ...valid(), ...patch });
    assert.equal(result.config_ready, false);
    assert.equal(result.checkout_activation_authorized, false);
  }
});
test('sandbox key cannot equal live key', () => {
  const env = valid();
  env.STRIPE_LIVE_SECRET_KEY = env.STRIPE_TEST_SECRET_KEY;
  assert.ok(inspectTiq72TestConfig(env).errors.includes('test_secret_equals_live_secret'));
});
test('untrusted return origins are rejected', () => {
  const withUserInfo = new URL('https://example.test');
  withUserInfo.username = 'fixture';
  withUserInfo.password = randomUUID();
  for (const origin of ['http://example.test', 'https://example.test/path', withUserInfo.href, 'https://example.test?x=1']) {
    assert.ok(inspectTiq72TestConfig({ ...valid(), TIQ72_TEST_RETURN_ORIGIN: origin }).errors.includes('tiq72_test_return_origin_invalid'));
  }
});
