import test from 'node:test';
import assert from 'node:assert/strict';
import {
  safeTiq72IsolatedReadiness, inspectTiq72IsolatedPrivateUrl
} from '../server/tiq72-isolated-readiness.mjs';

function syntheticIsolatedPrivateUrl() {
  // This URL is assembled entirely from offline fixture parts. Never connect.
  const role = 'nija_tiq72_upgrade6_isolated_test_user';
  const fixtureMarker = ['synthetic', 'only'].join('_');
  const host = 'dpg-dbqeq90ae00c7386p970-a';
  const database = 'nija_tiq72_upgrade6_isolated_test';
  return new URL([
    'postgresql://', role, ':', fixtureMarker, '@', host, '/', database,
    '?sslmode=require'
  ].join('')).href;
}
const stub = {
  STRIPE_TEST_SECRET_KEY: ['sk','test','synthetic'].join('_'),
  STRIPE_TEST_WEBHOOK_SECRET: ['whsec','synthetic'].join('_'),
  TIQ72_STRIPE_TEST_PRICE_ID: 'price_123456',
  TIQ72_STRIPE_TEST_PRODUCT_ID: 'prod_123456',
  TIQ72_TEST_DATABASE_URL: syntheticIsolatedPrivateUrl(),
  TIQ72_TEST_RETURN_ORIGIN: 'https://game.nijaaitrading.com',
  TIQ_ALLOWED_ORIGIN: 'https://game.nijaaitrading.com',
  STRIPE_LIVE_MODE: 'false',
  TIQ72_LIVE_PAYMENTS_ENABLED: 'false',
  NIJA_GAME_REPORTS_ENABLED: 'false',
  NIJA_GAME_BROWSER_CHECKOUT_ENABLED: 'false'
};

test('missing secrets and isolated DB deny readiness without displaying values', () => {
  const result = safeTiq72IsolatedReadiness({});
  assert.equal(result.status, 'holding');
  assert.equal(result.checkout_available, false);
  assert.equal(result.report_fulfillment_verified, false);
  assert.equal(result.test_configuration, 'incomplete');
  assert.ok(result.check_codes.includes('test_secret_missing_or_wrong_mode'));
  assert.ok(result.check_codes.includes('webhook_secret_missing'));
  assert.ok(result.check_codes.includes('isolated_private_db_identity_format_unconfirmed'));
});

test('plausible credentials never certify or activate checkout or database', () => {
  const result = safeTiq72IsolatedReadiness(stub);
  assert.equal(result.test_configuration, 'present_unverified');
  assert.equal(result.isolated_private_url_format_matches, true);
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
  for (const secret of [stub.STRIPE_TEST_SECRET_KEY, stub.STRIPE_TEST_WEBHOOK_SECRET, stub.TIQ72_TEST_DATABASE_URL]) {
    assert.equal(serialized.includes(secret), false);
  }
});

test('wrong database or host is never accepted, even when all other settings exist', () => {
  const badHost = new URL(stub.TIQ72_TEST_DATABASE_URL);
  badHost.hostname = 'dpg-dbsuhuc9v7es73bmteeg-a';
  const badDb = new URL(stub.TIQ72_TEST_DATABASE_URL);
  badDb.pathname = '/nija_tiq72_test_ledger_20261115';
  const badUser = new URL(stub.TIQ72_TEST_DATABASE_URL);
  badUser.username = 'other_user';
  for (const url of [badHost.href, badDb.href, badUser.href, '', 'not_a_url']) {
    assert.equal(inspectTiq72IsolatedPrivateUrl(url), false);
    const check = safeTiq72IsolatedReadiness({...stub, TIQ72_TEST_DATABASE_URL: url});
    assert.equal(check.test_configuration, 'incomplete');
    assert.equal(check.checkout_available, false);
  }
});

test('live mode request is rejected and never enables commerce', () => {
  const result = safeTiq72IsolatedReadiness({...stub, STRIPE_LIVE_MODE: 'true'});
  assert.equal(result.test_configuration, 'incomplete');
  assert.ok(result.check_codes.includes('live_mode_must_be_disabled'));
  assert.equal(result.checkout_available, false);
});
