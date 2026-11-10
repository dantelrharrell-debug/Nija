import test from 'node:test';import assert from 'node:assert/strict';
import {createHmac} from 'node:crypto';
import {Tiq12Upgrade6Store} from '../server/tiq12-upgrade6-store.mjs';
import {createUpgrade6Service} from '../server/tiq12-upgrade6-service.mjs';
import {validateTiq12Manifest} from '../server/tiq12-contract.mjs';
const now=new Date('2026-11-10T22:00:00.000Z');
const config={mode:'test',enabled:true,stripeSecret:'sk_test_abcdefgh1234',webhookSecret:'whsec_abcdefgh1234',priceId:'price_test_123',productId:'prod_test_123',allowedOrigin:'https://nijaaitrading.com'};
const sourceManifest={version:'nija-trading-iq-12-v1',rounds:Array.from({length:12},(_,i)=>({id:'round_'+(i+1),category:'risk',title:'Synthetic '+i,choices:[{label:'No',points:0,feedback:'Review downside',lesson:'Risk first'},{label:'Yes',points:5,feedback:'Study context',lesson:'Measure risk'}]}))};
const manifest=validateTiq12Manifest(sourceManifest);
const answers=manifest.rounds.map(r=>({roundId:r.id,choice:1}));
function setup({tamperCheckout}={}){
 const store=new Tiq12Upgrade6Store(':memory:',{initialize:true});
 let sessionId='cs_test_abcdefgh12345', session;
 const provider={
  verifyPrice:async()=>true,
  createCheckout:async(intent,idempotencyKey)=>{
   if(!session){session={id:sessionId,livemode:false,mode:'payment',amount_total:100,currency:'usd',url:'https://checkout.stripe.com/test123',
    status:'open',payment_status:'unpaid',metadata:intent.metadata,client_reference_id:intent.metadata.run_id,
    payment_intent:{id:'pi_test_1234',status:'succeeded',amount_received:100,currency:'usd',latest_charge:{id:'ch_test_1234',status:'succeeded',paid:true,refunded:false,disputed:false,amount_refunded:0}}};}
   if (tamperCheckout) tamperCheckout(session);
   return session;
  },
  reconcileCheckout:async()=>({session:{...session,status:session.status==='open'?'complete':session.status,payment_status:session.mockPending===true?'unpaid':session.payment_status==='unpaid'?'paid':session.payment_status},lineItems:{has_more:false,data:[{quantity:1,amount_total:100,currency:'usd',price:{id:config.priceId,product:config.productId}}]}}),
  resolveReversalSession:async()=>sessionId,
  get session(){return session;},
 };
 const service=createUpgrade6Service({sourceManifest,approvedManifestDigest:manifest.digest,
  store,provider,config,now:()=>now});
 return {service,store,provider};
}
function event(type,id,sessionId='cs_test_abcdefgh12345'){
 const raw=JSON.stringify({id,type,livemode:false,data:{object:{id:sessionId}}});
 const ts=Math.floor(now.getTime()/1000);
 return {raw,signature:`t=${ts},v1=${createHmac('sha256',config.webhookSecret).update(ts+'.'+raw).digest('hex')}`};
}
test('unapproved source fails closed without a canonical manifest digest',()=>{
 assert.throws(()=>createUpgrade6Service({sourceManifest,store:{},provider:{},config}),/independently approved/);
});
test('creates one private adult-owned run and rejects youth or score tampering',async()=>{
 const {service,store}=setup();
 for(const change of [{confirmedAdult:false,paidReportOptIn:true,answers},
  {confirmedAdult:true,paidReportOptIn:false,answers},
  {confirmedAdult:true,paidReportOptIn:true,answers:answers.slice(1)}]){
  await assert.rejects(service.completeRun(change,config.allowedOrigin));
 }
 const run=await service.completeRun({confirmedAdult:true,paidReportOptIn:true,answers},config.allowedOrigin);
 assert.equal(store.getRun(run.runId).answers.length,12);
 assert.equal('ownerProof' in store.getRun(run.runId),false);
 await assert.rejects(service.completeRun({confirmedAdult:true,paidReportOptIn:true,answers},'https://evil.example'));
 store.close();
});
test('owner proof required; one real test checkout reservation only',async()=>{
 const {service,store}=setup();
 const run=await service.completeRun({confirmedAdult:true,paidReportOptIn:true,answers},config.allowedOrigin);
 await assert.rejects(service.checkout({runId:run.runId,ownerProof:'a'.repeat(64)},config.allowedOrigin));
 const result=await service.checkout({runId:run.runId,ownerProof:run.ownerProof},config.allowedOrigin);
 assert.match(result.checkoutUrl,/^https:\/\/checkout\.stripe\.com/);
 await assert.rejects(service.checkout({runId:run.runId,ownerProof:run.ownerProof},config.allowedOrigin),/already exists/);
 assert.equal(store.db.prepare('SELECT count(*) n FROM tiq12_checkout_reservations').get().n,1);
 store.close();
});
test('signed reconciled paid webhook grants exactly once, report requires matching owner',async()=>{
 const {service,store}=setup();
 const run=await service.completeRun({confirmedAdult:true,paidReportOptIn:true,answers},config.allowedOrigin);
 await service.checkout({runId:run.runId,ownerProof:run.ownerProof},config.allowedOrigin);
 await assert.rejects(service.report({runId:run.runId,ownerProof:run.ownerProof},config.allowedOrigin));
 const e=event('checkout.session.completed','evt_test_1234567');
 assert.deepEqual(await service.webhook(e.raw,e.signature),{status:'granted'});
 assert.deepEqual(await service.webhook(e.raw,e.signature),{status:'duplicate'});
 const report=await service.report({runId:run.runId,ownerProof:run.ownerProof},config.allowedOrigin);
 assert.equal(report.score,100);
 await assert.rejects(service.report({runId:run.runId,ownerProof:'b'.repeat(64)},config.allowedOrigin));
 store.close();
});
test('unreconciled charge and refund both deny access',async()=>{
 const {service,store,provider}=setup();
 const run=await service.completeRun({confirmedAdult:true,paidReportOptIn:true,answers},config.allowedOrigin);
 await service.checkout({runId:run.runId,ownerProof:run.ownerProof},config.allowedOrigin);
 provider.session.payment_intent.latest_charge.refunded=true;
 const paid=event('checkout.session.completed','evt_test_1234567');
 await assert.rejects(service.webhook(paid.raw,paid.signature),/not verified/);
 provider.session.payment_intent.latest_charge.refunded=false;
 await service.webhook(paid.raw,paid.signature);
 provider.session.payment_intent.latest_charge.refunded=true;
 await assert.rejects(service.report({runId:run.runId,ownerProof:run.ownerProof},config.allowedOrigin),/not verified/);
 const refund=event('charge.refunded','evt_test_refund');
 assert.deepEqual(await service.webhook(refund.raw,refund.signature),{status:'revoked'});
 assert.equal(store.getGrant(run.runId),null);
 store.close();
});
test('out of order reversal stays revoked before delayed paid webhook',async()=>{
 const {service,store}=setup();
 const run=await service.completeRun({confirmedAdult:true,paidReportOptIn:true,answers},config.allowedOrigin);
 await service.checkout({runId:run.runId,ownerProof:run.ownerProof},config.allowedOrigin);
 const refund=event('charge.dispute.created','evt_test_dispute');
 assert.deepEqual(await service.webhook(refund.raw,refund.signature),{status:'revoked'});
 const paid=event('checkout.session.completed','evt_test_1234567');
 assert.deepEqual(await service.webhook(paid.raw,paid.signature),{status:'reversed'});
 await assert.rejects(service.report({runId:run.runId,ownerProof:run.ownerProof},config.allowedOrigin));
 store.close();
});

test('signed asynchronous pending completion records no entitlement until separately verified paid event',async()=>{
 const {service,store,provider}=setup();
 const run=await service.completeRun({confirmedAdult:true,paidReportOptIn:true,answers},config.allowedOrigin);
 await service.checkout({runId:run.runId,ownerProof:run.ownerProof},config.allowedOrigin);
 provider.session.mockPending=true;
 const pending=event('checkout.session.completed','evt_pending_123456');
 assert.deepEqual(await service.webhook(pending.raw,pending.signature),{status:'pending'});
 assert.equal(store.getGrant(run.runId),null);
 assert.equal(store.getCheckoutBySession(provider.session.id).state,'pending');
 await assert.rejects(service.report({runId:run.runId,ownerProof:run.ownerProof},config.allowedOrigin));
 provider.session.mockPending=false;
 const success=event('checkout.session.async_payment_succeeded','evt_success_123456');
 assert.deepEqual(await service.webhook(success.raw,success.signature),{status:'granted'});
 assert.equal((await service.report({runId:run.runId,ownerProof:run.ownerProof},config.allowedOrigin)).score,100);
 store.close();
});
test('asynchronous failed payment blocks checkout and rejects any later completion',async()=>{
 const {service,store,provider}=setup();
 const run=await service.completeRun({confirmedAdult:true,paidReportOptIn:true,answers},config.allowedOrigin);
 await service.checkout({runId:run.runId,ownerProof:run.ownerProof},config.allowedOrigin);
 provider.session.mockPending=true;
 const failed=event('checkout.session.async_payment_failed','evt_failed_123456');
 assert.deepEqual(await service.webhook(failed.raw,failed.signature),{status:'blocked'});
 assert.equal(store.getCheckoutBySession(provider.session.id).state,'blocked');
 provider.session.mockPending=false;
 const pay=event('checkout.session.async_payment_succeeded','evt_success_123456');
 assert.deepEqual(await service.webhook(pay.raw,pay.signature),{status:'blocked'});
 assert.equal(store.getGrant(run.runId),null);
 store.close();
});
test('verified expired checkout fails closed without granting or second session',async()=>{
 const {service,store,provider}=setup();
 const run=await service.completeRun({confirmedAdult:true,paidReportOptIn:true,answers},config.allowedOrigin);
 await service.checkout({runId:run.runId,ownerProof:run.ownerProof},config.allowedOrigin);
 provider.session.status='expired';provider.session.mockPending=true;
 const expired=event('checkout.session.expired','evt_expired_123456');
 assert.deepEqual(await service.webhook(expired.raw,expired.signature),{status:'blocked'});
 await assert.rejects(service.checkout({runId:run.runId,ownerProof:run.ownerProof},config.allowedOrigin));
 assert.equal(store.getGrant(run.runId),null);
 store.close();
});
test('Checkout creation must bind the exact private run metadata before exposing the payment URL',async()=>{
 for(const tamperCheckout of [s=>s.metadata.owner_proof_hash='f'.repeat(64),s=>s.metadata.manifest_digest='f'.repeat(64),
   s=>s.client_reference_id='run_wrong',s=>s.status='complete',s=>s.url='https://checkout.stripe.com.evil.example/test']){
   const {service,store}=setup({tamperCheckout});
   const run=await service.completeRun({confirmedAdult:true,paidReportOptIn:true,answers},config.allowedOrigin);
   await assert.rejects(service.checkout({runId:run.runId,ownerProof:run.ownerProof},config.allowedOrigin),/Untrusted/);
   const rows=store.db.prepare('SELECT checkout_session_id FROM tiq12_checkout_reservations WHERE run_id=?').all(run.runId);
   assert.equal(rows.length,1);assert.equal(rows[0].checkout_session_id,null);
   store.close();
 }
});
test('unpaid Checkout with mismatched stored price cannot become pending',async()=>{
 const {service,store,provider}=setup();
 const run=await service.completeRun({confirmedAdult:true,paidReportOptIn:true,answers},config.allowedOrigin);
 await service.checkout({runId:run.runId,ownerProof:run.ownerProof},config.allowedOrigin);
 provider.session.mockPending=true;provider.session.metadata.owner_proof_hash='f'.repeat(64);
 const e=event('checkout.session.completed','evt_badpending_12345');
 await assert.rejects(service.webhook(e.raw,e.signature),/not verified/);
 assert.equal(store.getGrant(run.runId),null);
 assert.equal(store.hasEvent('evt_badpending_12345'),false);
 store.close();
});
