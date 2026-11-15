import test from 'node:test';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import { REQUIRED_COLLECTIONS, collectSnapshot, encryptSnapshot, verifyEncryptedExport } from '../scripts/ionos_lead_readonly_export.mjs';

const makeMock=(options={})=>{
  let count=0;const log=[];
  const fetchImpl=async (u,init)=>{
    log.push({u,init});
    const url=new URL(u);
    const c=url.pathname.split('/')[4];
    const schema=url.pathname.split('/')[5] !== 'records';
    if(options.deny===c) return {status:403,headers:{get:()=> 'application/json'},json:async()=>({error:'forbidden'})};
    if(options.redirect) return {status:302,headers:{get:()=> 'text/html'},json:async()=>({})};
    if(schema) return {status:200,headers:{get:()=> 'application/json'},json:async()=>({name:c,fields:[{name:'event_id',type:'text'}]})};
    const page=Number(url.searchParams.get('page'));
    const items=options.overlap?[{id:'i'}]: (page===1?[{id:'a',event_id:'evt_test',email:'test@invalid.test'}]:[]);
    count++;
    if(options.drift && count>REQUIRED_COLLECTIONS.length) items[0].event_id='changed';
    const total=options.omitted?2:1;
    const totalPages=options.badPages?0:1;
    const result={items,page,perPage:200,totalPages,totalItems:total};
    return {status:200,headers:{get:()=> 'application/json'},json:async()=>result};
  };
  return {fetchImpl,log};
};
const params=(mock)=>({baseUrl:'https://nijaaitrading.com/.sfs-be',token:'owner_provided_nonsecret_fake_read_token',fetchImpl:mock.fetchImpl});

test('read-only stable two-pass collection export with exact IDs',async()=>{
  const m=makeMock();const {snapshot}=await collectSnapshot(params(m));
  assert.equal(Object.keys(snapshot.collections).length,4);
  assert.equal(m.log.length,16); // schema + one page for 4 collections, repeated twice
  assert.ok(m.log.every(r=>r.init.method==='GET' && r.init.redirect==='manual'));
  assert.equal(snapshot.transactional_backup,false);
});
test('fails closed on read denial, not zero',async()=>{
  const m=makeMock({deny:'nija_consent_events'});
  await assert.rejects(collectSnapshot(params(m)),/Authorized API read unavailable/);
});
test('fails closed on redirects',async()=>{
  await assert.rejects(collectSnapshot(params(makeMock({redirect:true}))),/Authorized API read unavailable/);
});
test('fails closed on missing rows',async()=>{
  await assert.rejects(collectSnapshot(params(makeMock({omitted:true}))),/omitted rows/);
});
test('rejects inconsistent page metadata rather than silently certifying data',async()=>{
  await assert.rejects(collectSnapshot(params(makeMock({badPages:true}))),/Incomplete or malformed/);
});
test('fails closed if content drifts between passes',async()=>{
  await assert.rejects(collectSnapshot(params(makeMock({drift:true}))),/Collection drift/);
});
test('rejects external origin',async()=>{
  await assert.rejects(collectSnapshot({...params(makeMock()),baseUrl:'https://attacker.example/.sfs-be'}),/Origin must/);
});
test('rejects missing auth',async()=>{
  await assert.rejects(collectSnapshot({...params(makeMock()),token:''}),/token unavailable/);
});
test('rejects export of server secret settings',async()=>{
  await assert.rejects(collectSnapshot({...params(makeMock()),additional:['nija_settings']}),/allowlisted/);
});
test('encrypted archive round trips without plaintext values in stored JSON',async()=>{
  const {publicKey,privateKey}=crypto.generateKeyPairSync('rsa',{modulusLength:2048});
  const {plaintext}=await collectSnapshot(params(makeMock()));
  const enc=encryptSnapshot(plaintext,publicKey.export({type:'spki',format:'pem'}));
  assert.equal(JSON.stringify(enc).includes('test@invalid.test'),false);
  assert.deepEqual(verifyEncryptedExport(enc,privateKey.export({type:'pkcs8',format:'pem'})).record_counts,
                   Object.fromEntries(REQUIRED_COLLECTIONS.map(c=>[c,1])));
});
test('rejects archive ciphertext tampering',async()=>{
  const {publicKey,privateKey}=crypto.generateKeyPairSync('rsa',{modulusLength:2048});
  const p=Buffer.from('secret');const enc=encryptSnapshot(p,publicKey.export({type:'spki',format:'pem'}));
  enc.ciphertext='AAAA';
  assert.throws(()=>verifyEncryptedExport(enc,privateKey.export({type:'pkcs8',format:'pem'})));
});
test('rejects private key in place of encryption recipient public key',()=>{
  const {privateKey}=crypto.generateKeyPairSync('rsa',{modulusLength:2048});
  assert.throws(()=>encryptSnapshot(Buffer.from('x'),privateKey.export({type:'pkcs8',format:'pem'})),/not be a private key/);
});
test('rejects non-RSA cert',()=>{
  const {publicKey}=crypto.generateKeyPairSync('ec',{namedCurve:'prime256v1'});
  assert.throws(()=>encryptSnapshot(Buffer.from('x'),publicKey.export({type:'spki',format:'pem'})),/RSA certificate/);
});