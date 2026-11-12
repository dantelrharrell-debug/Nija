import test from 'node:test';
import assert from 'node:assert/strict';
import { createHmac } from 'node:crypto';
import { verifyStripeWebhook } from '../server/tiq72-stripe-signature.mjs';
const secret='whsec_test_secret';
const now=1800000000;
const payload=Buffer.from(JSON.stringify({id:'evt_test123',type:'checkout.session.completed',data:{object:{id:'cs_test_123'}}}));
function signed(body=payload,t=now){return 't='+t+',v1='+createHmac('sha256',secret).update(String(t)).update('.').update(body).digest('hex');}
test('accepts valid raw signed event',()=>assert.equal(verifyStripeWebhook(payload,signed(),secret,now).id,'evt_test123'));
test('rejects modified payload',()=>assert.throws(()=>verifyStripeWebhook(Buffer.from(payload.toString().replace('completed','expired')),signed(),secret,now)));
test('rejects stale timestamp',()=>assert.throws(()=>verifyStripeWebhook(payload,signed(payload,now-301),secret,now)));
test('rejects missing signature and wrong secret',()=>{
 assert.throws(()=>verifyStripeWebhook(payload,'t='+now,secret,now));
 assert.throws(()=>verifyStripeWebhook(payload,signed(),'whsec_wrong',now));
});
test('rejects parsed body rather than raw bytes',()=>assert.throws(()=>verifyStripeWebhook(JSON.parse(payload.toString()),signed(),secret,now)));
test('rejects invalid signed event shape',()=>{
 const body=Buffer.from('{}');assert.throws(()=>verifyStripeWebhook(body,signed(body),secret,now));
});
