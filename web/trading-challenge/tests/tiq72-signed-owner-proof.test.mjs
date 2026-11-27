import test from 'node:test';
import assert from 'node:assert/strict';
import {randomBytes} from 'node:crypto';
import {createTiq72OwnerProof, verifyTiq72OwnerProof,
  authenticateTiq72OwnerRequest} from '../server/tiq72-signed-owner-proof.mjs';

const key = randomBytes(32), alternateKey = randomBytes(32);
const nowSec = 1795010000;
const issue = (overrides = {}, opts = {}) => createTiq72OwnerProof({
  ownerId: 'isolated_test_owner', adultVerified: true, ...overrides
}, key, {nowSec, ...opts});

test('verified adult proof has bounded owner and CSRF identity', () => {
  const {token,csrfToken} = issue();
  assert.match(csrfToken, /^[A-Za-z0-9_-]{43}$/);
  assert.deepEqual(verifyTiq72OwnerProof(token, key, {nowSec: nowSec + 120}),
    {ownerId: 'isolated_test_owner', csrfToken});
  assert.deepEqual(authenticateTiq72OwnerRequest(
    {headers:{authorization:'Bearer '+token}}, key, {nowSec}),
    {ownerId:'isolated_test_owner', csrfToken});
});
test('browser-supplied adult claim cannot issue a proof', () => {
  for (const invalid of [undefined, false, 'true', 1])
    assert.throws(() => issue({adultVerified: invalid}), /authenticated_adult/);
  assert.throws(() => issue({ownerId: '../other_user'}), /authenticated_adult/);
});
test('tampering with signature, payload or key denies identity', () => {
  const {token}=issue(), [payload,mac]=token.split('.');
  const changed=mac.slice(0,3)+(mac[3]==='A'?'B':'A')+mac.slice(4);
  assert.equal(verifyTiq72OwnerProof(payload+'.'+changed,key,{nowSec}),null);
  assert.equal(verifyTiq72OwnerProof(payload+'A.'+mac,key,{nowSec}),null);
  assert.equal(verifyTiq72OwnerProof(token,alternateKey,{nowSec}),null);
  assert.equal(verifyTiq72OwnerProof('garbage',key,{nowSec}),null);
});
test('expired, early, invalid lifetimes and weak keys fail closed',()=>{
  const {token}=issue({}, {ttlSec:600});
  assert.equal(verifyTiq72OwnerProof(token,key,{nowSec:nowSec+600}),null);
  assert.equal(verifyTiq72OwnerProof(token,key,{nowSec:nowSec-31}),null);
  assert.throws(() => issue({}, {ttlSec:601}),/invalid_test_proof_lifetime/);
  assert.throws(() => createTiq72OwnerProof(
    {ownerId:'a',adultVerified:true},randomBytes(16)),/isolated_signing_key_required/);
});
test('invalid Authorization headers are never authenticated',()=>{
  const {token}=issue();
  for(const headers of [
    {}, {authorization:token}, {authorization:'Basic '+token},
    {authorization:'Bearer '+token+' extra'}, {authorization:'Bearer '}
  ]) assert.equal(authenticateTiq72OwnerRequest({headers},key,{nowSec}),null);
});
