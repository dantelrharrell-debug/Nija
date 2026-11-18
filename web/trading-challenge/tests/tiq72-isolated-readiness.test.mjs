import test from 'node:test';
import assert from 'node:assert/strict';
import {safeTiq72IsolatedReadiness} from '../server/tiq72-isolated-readiness.mjs';

const stub = {
  STRIPE_TEST_SECRET_KEY: ['sk','test','synthetic'].join('_'),
  STRIPE_TEST_WEBHOOK_SECRET: ['whsec','synthetic'].join('_'),
  TIQ72_STRIPE_TEST_PRICE_ID: 'price_123456',
  TIQ72_STRIPE_TEST_PRODUCT_ID: 'prod_123456',
  DATABASE_URL: 'present_but_not_verified',
  TIQ72_TEST_RETURN_ORIGIN: 'https://game.nijaaitrading.com',
  TIQ_ALLOWED_ORIGIN: 'https://game.nijaaitrading.com',
  STRIPE_LIVE_MODE: 'false',
  TIQ72_LIVE_PAYMENTS_ENABLED: 'false',
  NIJA_GAME_REPORTS_ENABLED: 'false',
  NIJA_GAME_BROWSER_CHECKOUT_ENABLED: 'false'
};

test('missing secrets deny readiness without displaying environment values', () => {
  const result = safeTiq72IsolatedReadiness({});
  assert.equal(result.status, 'holding');
  assert.equal(result.checkout_available, false);
  assert.equal(result.report_fulfillment_verified, false);
  assert.equal(result.test_configuration, 'incomplete');
  assert.ok(result.check_codes.includes('test_secret_missing_or_wrong_mode'));
  assert.ok(result.check_codes.includes('webhook_secret_missing'));
});

test('plausible credentials never certify or activate checkout or database', () => {
  const result = safeTiq72IsolatedReadiness(stub);
  assert.equal(result.test_configuration, 'present_unverified');
  for (const value of [
    result.stripe_test_permissions_verified,
    result.isolated_database_identity_verified,
    result.migration_verified,
    result.signed_webhook_verified,
    result.ionos_preview_approved,
    result.checkout_available,
    result.report_fulfillment_verified
  ]) assert.equal(value, false);
  const serialized = JSON.stringify(result);
  for (const secret of Object.values(stub)) {
    assert.equal(serialized.includes(secret), false);
  }
});

test('live mode request is rejected and never enables commerce', () => {
  const result = safeTiq72IsolatedReadiness({...stub, STRIPE_LIVE_MODE: 'true'});
  assert.equal(result.test_configuration, 'incomplete');
  assert.ok(result.check_codes.includes('live_mode_must_be_disabled'));
  assert.equal(result.checkout_available, false);
});
