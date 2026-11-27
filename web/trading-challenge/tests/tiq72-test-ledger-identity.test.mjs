import test from 'node:test';
import assert from 'node:assert/strict';
import {randomBytes} from 'node:crypto';
import {checkTestLedgerIdentity,EXPECTED_TEST_LEDGER} from '../server/tiq72-test-ledger-identity.mjs';
const make = () => {
 const u = new URL('postgresql://localhost/test');
 u.hostname = EXPECTED_TEST_LEDGER.hostname;
 u.username = EXPECTED_TEST_LEDGER.username;
 u.password = randomBytes(24).toString('hex');
 u.pathname = '/' + EXPECTED_TEST_LEDGER.database;
 return u;
};
test('matching private test ledger identity passes without claiming migration',()=>{
 const u=make(); const result=checkTestLedgerIdentity(u.href);
 assert.deepEqual(result,{ready:true,reason:'identity_matches_test_ledger'});
 assert.equal(JSON.stringify(result).includes(u.password),false);
});
test('other Render database, public host, and wrong role fail closed',()=>{
 for(const mutation of [u=>u.hostname='dpg-dbqeq90ae00c7386p970-a',
 u=>u.hostname='localhost',u=>u.username='other_user',u=>u.pathname='/billing',
 u=>u.port='5433',u=>u.search='?sslmode=disable',u=>u.hash='#fragment']){
  const u=make();mutation(u);assert.equal(checkTestLedgerIdentity(u.href).ready,false);
 }
});
test('malformed and missing values fail closed',()=>{
 for(const value of ['',null,'https://example.com','postgresql://untrusted@localhost/x']){
  assert.equal(checkTestLedgerIdentity(value).ready,false);
 }
});
