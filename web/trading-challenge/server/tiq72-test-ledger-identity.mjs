// Pure, read-only preflight for the isolated TIQ72 test ledger identity.
// Never logs or returns a connection URL, password, or other credential.
export const EXPECTED_TEST_LEDGER = Object.freeze({
  hostname: 'dpg-dbsuhuc9v7es73bmteeg-a',
  database: 'nija_tiq72_test_ledger_20261115',
  username: 'nija_tiq72_test_ledger_20261115_user',
});

export function checkTestLedgerIdentity(value) {
  if (typeof value !== 'string' || !value || value.length > 2048)
    return {ready:false,reason:'private_test_database_url_missing'};
  try {
    const u = new URL(value);
    const expected = EXPECTED_TEST_LEDGER;
    const ready = ['postgres:', 'postgresql:'].includes(u.protocol) &&
      u.hostname === expected.hostname &&
      decodeURIComponent(u.pathname.slice(1)) === expected.database &&
      decodeURIComponent(u.username) === expected.username &&
      !!u.password && (!u.port || u.port === '5432') &&
      (!u.search || u.search === '?sslmode=require') &&
      !u.hash;
    return {ready,reason:ready ? 'identity_matches_test_ledger' : 'test_ledger_identity_mismatch'};
  } catch {
    return {ready:false,reason:'invalid_private_test_database_url'};
  }
}
