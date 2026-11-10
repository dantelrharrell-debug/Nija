import test from 'node:test';
import assert from 'node:assert/strict';
import { Tiq12Upgrade6Store } from '../server/tiq12-upgrade6-store.mjs';
const stored=()=>new Tiq12Upgrade6Store(':memory:',{initialize:true});
const manifest={digest:'a'.repeat(64)};
const answers=Array.from({length:12},(_,i)=>({roundId:'round_'+(i+1),choice:0}));
const setup=()=>{
 const store=stored(),run=store.createRun({manifest,answers,ownerProofHash:'b'.repeat(64)});
 const reservation=store.reserveCheckout({runId:run.id,priceId:'price_test_123',productId:'prod_test_123'});
 return {store,run,reservation};
};
test('creates durable adult-only completed run and one persistent checkout reservation',()=>{
 const {store,run,reservation}=setup();
 assert.equal(store.getRun(run.id).answers.length,12);
 assert.equal(store.reserveCheckout({runId:run.id,priceId:'price_test_123',productId:'prod_test_123'}).stripe_idempotency_key,reservation.stripe_idempotency_key);
 assert.equal(store.db.prepare('SELECT count(*) as n FROM tiq12_checkout_reservations').get().n,1);
 store.close();
});
test('checkout sessions cannot be rebound after first assignment',()=>{
 const {store,reservation}=setup();
 store.attachSession(reservation.reservation_id,'cs_test_abcdefgh12345');
 assert.equal(store.attachSession(reservation.reservation_id,'cs_test_abcdefgh12345').state,'created');
 assert.throws(()=>store.attachSession(reservation.reservation_id,'cs_test_other12345678'));
 store.close();
});
test('signature-reconciled grant persists exactly once and duplicate webhook cannot regrant',()=>{
 const {store,run,reservation}=setup();
 const attached=store.attachSession(reservation.reservation_id,'cs_test_abcdefgh12345');
 const event={id:'evt_test_abcd123',type:'checkout.session.completed'};
 const args={event,rawBody:'{}',reservation:attached,paymentIntentId:'pi_test_12345',chargeId:'ch_test_12345',
  expiresAt:new Date(Date.now()+86400000).toISOString()};
 assert.equal(store.recordPaid(args),'granted');
 assert.equal(store.recordPaid(args),'duplicate');
 const grant=store.getGrant(run.id);
 assert.equal(grant.amountPaid,100); assert.equal(grant.status,'granted');
 assert.equal(store.db.prepare('SELECT count(*) n FROM tiq12_verified_payments').get().n,1);
 store.close();
});
test('refund revokes and repeated payment cannot restore access',()=>{
 const {store,run,reservation}=setup();
 const attached=store.attachSession(reservation.reservation_id,'cs_test_abcdefgh12345');
 store.recordPaid({event:{id:'evt_paid_1234',type:'checkout.session.completed'},rawBody:'{}',reservation:attached,
  paymentIntentId:'pi_test_12345',chargeId:'ch_test_12345',expiresAt:new Date(Date.now()+86400000).toISOString()});
 assert.equal(store.recordReversal({event:{id:'evt_refund_1234',type:'charge.refunded'},
  rawBody:'{}',sessionId:'cs_test_abcdefgh12345',reason:'refund'}),'revoked');
 assert.equal(store.getGrant(run.id),null);
 assert.equal(store.db.prepare('SELECT status FROM tiq12_report_entitlements').get().status,'revoked');
 store.close();
});
test('out-of-order dispute blocks later paid entitlement',()=>{
 const {store,run,reservation}=setup();
 const attached=store.attachSession(reservation.reservation_id,'cs_test_abcdefgh12345');
 assert.equal(store.recordReversal({event:{id:'evt_dispute_1234',type:'charge.dispute.created'},
  rawBody:'{}',sessionId:'cs_test_abcdefgh12345',reason:'dispute'}),'revoked');
 assert.equal(store.recordPaid({event:{id:'evt_paid_1234',type:'checkout.session.completed'},
  rawBody:'{}',reservation:attached,paymentIntentId:'pi_test_12345',chargeId:'ch_test_12345',
  expiresAt:new Date(Date.now()+86400000).toISOString()}),'reversed');
 assert.equal(store.getGrant(run.id),null);
 store.close();
});
test('missing isolated schema cannot be created without migration approval',()=>{
 assert.throws(()=>new Tiq12Upgrade6Store(':memory:'),/not installed/);
});
