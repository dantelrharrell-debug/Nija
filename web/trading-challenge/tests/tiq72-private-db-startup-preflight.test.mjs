import test from 'node:test';
import assert from 'node:assert/strict';
import {runTiq72PrivateDbPreflight} from '../server/tiq72-private-db-startup-preflight.mjs';

const syntheticMarker = 'NEVER_DISPLAY_THIS_SYNTHETIC_ONLY';
const url = 'postgresql://nija_tiq72_upgrade6_isolated_test_user:' + syntheticMarker +
  '@dpg-dbqeq90ae00c7386p970-a/nija_tiq72_upgrade6_isolated_test?sslmode=require';
const allTables = [
  'tiq72_v515_runs', 'tiq72_v515_reservations',
  'tiq72_v515_reports', 'tiq72_v515_verified_events'
];
const valid = {status: 'identity_verified_read_only',
  expected_tables_present: ['tiq72_v515_runs'],
  expected_tables_missing: allTables.filter(x => x !== 'tiq72_v515_runs'),
  migration_applied: false};
function fake(payload, status = 0) {
  return (_bin, _args, opts) => {
    assert.equal(opts.shell, false);
    assert.ok(opts.timeout <= 12000);
    assert.deepEqual(opts.stdio, ['ignore', 'pipe', 'ignore']);
    return {status, stdout: JSON.stringify(payload)};
  };
}

test('invalid target never launches a subprocess', () => {
  const result = runTiq72PrivateDbPreflight({env: {TIQ72_TEST_DATABASE_URL: url.replace('dpg-dbqeq90ae00c7386p970-a','other')},
    invoke: () => {throw Error('must not launch');}});
  assert.equal(result.status, 'blocked');
  assert.equal(result.connected_database_identity_verified, false);
});

test('reports authenticated table presence only, not schema or payment certification', () => {
  const report = runTiq72PrivateDbPreflight({env: {TIQ72_TEST_DATABASE_URL: url}, invoke: fake(valid)});
  assert.equal(report.connected_database_identity_verified, true);
  assert.equal(report.expected_tables_present.length, 1);
  assert.equal(report.expected_tables_missing.length, 3);
  assert.equal(report.schema_certified, false);
  assert.equal(report.payment_certified, false);
  assert.ok(!JSON.stringify(report).includes(syntheticMarker));
});

test('all tables still does not certify columns, backup, or payments', () => {
  const report = runTiq72PrivateDbPreflight({env: {TIQ72_TEST_DATABASE_URL: url},
    invoke: fake({...valid, expected_tables_present: allTables, expected_tables_missing: [], migration_applied: true})});
  assert.equal(report.connected_database_identity_verified, true);
  assert.equal(report.schema_certified, false);
  assert.equal(report.payment_certified, false);
});

test('redacts unexpected stdout, injection and syntheticMarker-containing errors', () => {
  for (const p of [
    {...valid, expected_tables_present: [...allTables, 'wrong_table'], expected_tables_missing: []},
    {...valid, expected_tables_present: [...allTables, allTables[0]], expected_tables_missing: []},
    {...valid, migration_applied: true},
    {...valid, syntheticMarker: syntheticMarker, expected_tables_present: [syntheticMarker]},
    {status: 'error', reason: syntheticMarker},
  ]) {
    const report = runTiq72PrivateDbPreflight({env: {TIQ72_TEST_DATABASE_URL: url}, invoke: fake(p)});
    assert.equal(report.status, 'blocked');
    assert.ok(!JSON.stringify(report).includes(syntheticMarker));
  }
});

test('failed read-only result cannot become a certification', () => {
  const result = runTiq72PrivateDbPreflight({env: {TIQ72_TEST_DATABASE_URL: url},
    invoke: fake({status: 'blocked', reason: 'private_read_only_preflight_failed', detail: syntheticMarker}, 3)});
  assert.deepEqual([result.status, result.reason, result.payment_certified],
    ['blocked','private_read_only_preflight_failed',false]);
});

test('throws, timeouts and malformed output fail closed', () => {
  const env = {TIQ72_TEST_DATABASE_URL: url};
  for (const invoke of [
    () => {throw Error(syntheticMarker);},
    () => ({status: null, error: new Error(syntheticMarker), stdout: ''}),
    () => ({status: 0, signal: 'SIGTERM', stdout: JSON.stringify(valid)}),
    () => ({status: 0, stdout: syntheticMarker}),
    () => ({status: 0, stdout: JSON.stringify(valid) + '\n' + syntheticMarker})
  ]) {
    const report = runTiq72PrivateDbPreflight({env, invoke});
    assert.equal(report.status, 'blocked');
    assert.ok(!JSON.stringify(report).includes(syntheticMarker));
  }
});
