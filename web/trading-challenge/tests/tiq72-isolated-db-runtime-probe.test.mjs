import test from 'node:test';
import assert from 'node:assert/strict';
import {runTiq72IsolatedDatabaseProbe} from '../server/tiq72-isolated-db-runtime-probe.mjs';

const tables=[
  'tiq72_v515_runs','tiq72_v515_reservations',
  'tiq72_v515_reports','tiq72_v515_verified_events'
];
function env() {
  const u=new URL('postgresql://synthetic.invalid');
  u.hostname='dpg-dbqeq90ae00c7386p970-a';
  u.username='nija_tiq72_upgrade6_isolated_test_user';
  u.password='synthetic_only';
  u.pathname='/nija_tiq72_upgrade6_isolated_test';
  u.searchParams.set('sslmode','require');
  return {TIQ72_TEST_DATABASE_URL:u.href};
}
const withProbeResult = (value, status=0) => (file,args,opts)=>{
  assert.ok(file.endsWith('/.venv/bin/python'));
  assert.ok(args[0].endsWith('scripts/tiq72_isolated_db_readonly_preflight.py'));
  assert.equal(opts.timeout,12000);
  assert.deepEqual(opts.stdio,['ignore','pipe','ignore']);
  return {status,stdout:JSON.stringify(value)};
};

test('rejected cross-workspace URL never launches Python or logs its value',()=>{
  const wrong=env();
  wrong.TIQ72_TEST_DATABASE_URL=wrong.TIQ72_TEST_DATABASE_URL.replace(
    'dpg-dbqeq90ae00c7386p970-a','dpg-dbsuhuc9v7es73bmteeg-a');
  let ran=false;
  const got=runTiq72IsolatedDatabaseProbe(wrong,()=>{ran=true;throw Error('must not run')});
  assert.equal(ran,false);
  assert.equal(got.status,'blocked');
  assert.equal(got.migration_verified,false);
  assert.ok(!JSON.stringify(got).includes(wrong.TIQ72_TEST_DATABASE_URL));
});

test('read-only identity with all tables still never certifies migration or payments',()=>{
  const got=runTiq72IsolatedDatabaseProbe(env(),withProbeResult({
    status:'identity_verified_read_only', expected_tables_present:tables,
    expected_tables_missing:[], migration_applied:true
  }));
  assert.equal(got.status,'identity_verified_read_only');
  assert.equal(got.expected_schema_present,true);
  assert.equal(got.checkout_available,false);
  assert.equal(got.migration_verified,false);
});

test('missing tables are reported without changing database or granting entitlements',()=>{
  const got=runTiq72IsolatedDatabaseProbe(env(),withProbeResult({
    status:'identity_verified_read_only',expected_tables_present:[tables[0]],
    expected_tables_missing:tables.slice(1),migration_applied:false
  }));
  assert.deepEqual(got.expected_tables_missing,[...tables.slice(1)].sort());
  assert.equal(got.expected_schema_present,false);
  assert.equal(got.migration_verified,false);
  assert.equal(got.checkout_available,false);
});

test('inconsistent table inventory and failed child process fail closed',()=>{
  const bad=[
    {status:'identity_verified_read_only',expected_tables_present:[tables[0]],
     expected_tables_missing:tables.slice(1),migration_applied:true},
    {status:'identity_verified_read_only',expected_tables_present:tables,
     expected_tables_missing:[],migration_applied:false},
    {status:'identity_verified_read_only',expected_tables_present:[tables[0]],
     expected_tables_missing:[],migration_applied:false},
    {status:'identity_verified_read_only',expected_tables_present:['nija_users'],
     expected_tables_missing:tables.slice(1),migration_applied:false}
  ];
  for(const obj of bad)
    assert.equal(runTiq72IsolatedDatabaseProbe(env(),withProbeResult(obj)).status,'blocked');
  assert.equal(runTiq72IsolatedDatabaseProbe(env(),withProbeResult({},2)).status,'blocked');
  assert.equal(runTiq72IsolatedDatabaseProbe(env(),()=>({status:0,stdout:'not json'})).status,'blocked');
});

test('known failure codes may be shown without sensitive Python or driver text',()=>{
  const classified=runTiq72IsolatedDatabaseProbe(env(),withProbeResult({
    status:'blocked',reason:'private_db_dns_unavailable'
  },3));
  assert.equal(classified.reason,'private_db_dns_unavailable');
  assert.equal(classified.migration_verified,false);
  const unexpected=runTiq72IsolatedDatabaseProbe(env(),withProbeResult({
    status:'blocked',reason:'postgresql://synthetic@wrong-host'
  },3));
  assert.equal(unexpected.reason,'private_read_only_preflight_failed');
  assert.ok(!JSON.stringify(unexpected).includes('synthetic@wrong-host'));
});
