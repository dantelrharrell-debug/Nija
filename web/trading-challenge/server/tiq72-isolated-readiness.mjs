// Value-free, read-only diagnostic for the isolated TIQ72 Render sandbox.
// A matching private URL format does NOT establish connected database identity.
// This must never enable Stripe, checkout, report, webhook, or production routes.
import {inspectTiq72TestConfig} from './tiq72-upgrade6-config-preflight.mjs';

const DB = 'nija_tiq72_upgrade6_isolated_test';
const USER = 'nija_tiq72_upgrade6_isolated_test_user';
const HOST = 'dpg-dbqeq90ae00c7386p970-a';

export function inspectTiq72IsolatedPrivateUrl(raw) {
  if (typeof raw !== 'string' || raw.length === 0 || raw.length > 2048)
    return false;
  try {
    const u = new URL(raw);
    return ['postgres:', 'postgresql:'].includes(u.protocol) &&
      u.hostname === HOST &&
      decodeURIComponent(u.username) === USER &&
      decodeURIComponent(u.pathname.slice(1)) === DB &&
      u.password.length > 0 &&
      (u.port === '' || u.port === '5432') &&
      (u.search === '' || u.search === '?sslmode=require') &&
      !u.hash;
  } catch {
    return false;
  }
}

export function safeTiq72IsolatedReadiness(env = process.env) {
  const dbFormatMatched = inspectTiq72IsolatedPrivateUrl(env.TIQ72_TEST_DATABASE_URL);
  // Existing generic preflight checks DATABASE_URL. For this isolated service,
  // bind only its explicitly named private URL to the generic presence check.
  const checks = inspectTiq72TestConfig({
    ...env,
    DATABASE_URL: dbFormatMatched ? 'private_url_format_checked' : ''
  });
  const failures = [...checks.errors];
  if (!dbFormatMatched) failures.push('isolated_private_db_identity_format_unconfirmed');
  return {
    status: 'holding',
    test_configuration: failures.length === 0 ? 'present_unverified' : 'incomplete',
    check_codes: failures,
    isolated_private_url_format_matches: dbFormatMatched,
    stripe_test_permissions_verified: false,
    isolated_database_identity_verified: false,
    migration_verified: false,
    signed_webhook_verified: false,
    ionos_preview_approved: false,
    checkout_available: false,
    report_fulfillment_verified: false
  };
}
