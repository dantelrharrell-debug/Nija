// NIJA TIQ72 isolated test-mode configuration preflight.
// Never prints secret values, never opens a network connection or enables checkout.
// A passing result is NOT payment/fulfillment certification.
import { pathToFileURL } from 'node:url';

export function inspectTiq72TestConfig(env = process.env) {
  const errors = [];
  const has = (key) => typeof env[key] === 'string' && env[key].trim().length > 0;
  const fail = (code, condition) => { if (condition) errors.push(code); };
  fail('test_secret_missing_or_wrong_mode',
    !has('STRIPE_TEST_SECRET_KEY') || !/^(sk_test_|rk_test_)/.test(env.STRIPE_TEST_SECRET_KEY || ''));
  fail('webhook_secret_missing', !has('STRIPE_TEST_WEBHOOK_SECRET') ||
    !/^whsec_/.test(env.STRIPE_TEST_WEBHOOK_SECRET || ''));
  fail('test_price_missing', !/^price_[A-Za-z0-9]+$/.test(env.TIQ72_STRIPE_TEST_PRICE_ID || ''));
  fail('test_product_missing', !/^prod_[A-Za-z0-9_]+$/.test(env.TIQ72_STRIPE_TEST_PRODUCT_ID || ''));
  fail('database_url_missing', !has('DATABASE_URL'));
  fail('legacy_checkout_must_be_disabled',
    env.NIJA_GAME_REPORTS_ENABLED === 'true' ||
    env.NIJA_GAME_BROWSER_CHECKOUT_ENABLED === 'true');
  fail('live_mode_must_be_disabled',
    env.TIQ72_LIVE_PAYMENTS_ENABLED === 'true' ||
    env.STRIPE_LIVE_MODE === 'true');
  for (const key of ['TIQ72_TEST_RETURN_ORIGIN', 'TIQ_ALLOWED_ORIGIN']) {
    const value = env[key];
    let valid = false;
    if (typeof value === 'string' && !/[\\\s]/.test(value)) {
      try {
        const u = new URL(value);
        valid = u.protocol === 'https:' && !!u.hostname && !u.username && !u.password &&
          !u.pathname.replace(/\//g, '') && !u.search && !u.hash &&
          (u.port === '' || u.port === '443') &&
          u.origin === value;
      } catch { /* reject malformed origins */ }
    }
    fail(key.toLowerCase() + '_invalid', !valid);
  }
  // Distinct test and live secrets must never be accidentally interchanged.
  fail('test_secret_equals_live_secret',
    has('STRIPE_LIVE_SECRET_KEY') && env.STRIPE_LIVE_SECRET_KEY === env.STRIPE_TEST_SECRET_KEY);
  return { config_ready: errors.length === 0, errors,
    migration_verified: false, fulfillment_verified: false,
    ionos_preview_approved: false, sandbox_e2e_verified: false,
    checkout_activation_authorized: false };
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const result = inspectTiq72TestConfig();
  process.stdout.write(JSON.stringify(result) + '\n');
  process.exitCode = result.config_ready ? 0 : 1;
}
