// Value-free, read-only Render startup diagnostic for the isolated TIQ72 sandbox.
// This never verifies Stripe permissions, private DB contents, or purchase fulfillment.
// Do not use these checks to unlock routes or report payment readiness.
import {inspectTiq72TestConfig} from './tiq72-upgrade6-config-preflight.mjs';

export function safeTiq72IsolatedReadiness(env = process.env) {
  const checks = inspectTiq72TestConfig(env);
  // These fields come only from fixed local checks; never echo environment values.
  return {
    status: 'holding',
    test_configuration: checks.config_ready ? 'present_unverified' : 'incomplete',
    check_codes: [...checks.errors],
    stripe_test_permissions_verified: false,
    isolated_database_identity_verified: false,
    migration_verified: false,
    signed_webhook_verified: false,
    ionos_preview_approved: false,
    checkout_available: false,
    report_fulfillment_verified: false
  };
}
