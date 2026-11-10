import test from 'node:test';import assert from 'node:assert/strict';
import {createStripeTestAdapter} from '../server/tiq12-upgrade6-stripe.mjs';
const key='sk_test_abcdefgh1234';
test('Stripe test adapter refuses live keys before HTTP',()=>{
 assert.throws(()=>createStripeTestAdapter({secretKey:'sk_live_abcdefgh1234',allowedOrigin:'https://nijaaitrading.com'}));
});
test('test price verification requires 100-cent USD one-time price',async()=>{
 let calls=0;
 const fake=async()=>{calls++;return {ok:true,json:async()=>({id:'price_test_123',product:'prod_test_123',active:true,livemode:false,type:'one_time',unit_amount:100,currency:'usd'})};};
 const adapter=createStripeTestAdapter({secretKey:key,allowedOrigin:'https://nijaaitrading.com',fetchImpl:fake});
 assert.equal(await adapter.verifyPrice({priceId:'price_test_123',productId:'prod_test_123'}),true);
 assert.equal(await adapter.verifyPrice({priceId:'price_test_123',productId:'prod_wrong'}),false);
 assert.equal(calls,2);
});
test('checkout uses Stripe fixed price with durable idempotency and no browser score',async()=>{
 let req;
 const fake=async(url,options)=>{req={url,options};return {ok:true,json:async()=>({id:'cs_test_abcdefgh12345',mode:'payment',livemode:false,amount_total:100,currency:'usd',url:'https://checkout.stripe.com/mock'})};};
 const adapter=createStripeTestAdapter({secretKey:key,allowedOrigin:'https://nijaaitrading.com',fetchImpl:fake});
 const intent={mode:'payment',line_items:[{price:'price_test_123',quantity:1}],
  metadata:{run_id:'run_'+'a'.repeat(32),game_version:'nija-trading-iq-12-v1',manifest_digest:'b'.repeat(64),owner_proof_hash:'c'.repeat(64)}};
 await adapter.createCheckout(intent,'tiq12_'+'f'.repeat(32));
 assert.match(req.url,/^https:\/\/api\.stripe\.com\/v1\/checkout\/sessions/);
 const parsed=new URLSearchParams(req.options.body);
 assert.equal(parsed.get('line_items[0][quantity]'),'1');
 assert.equal(parsed.get('line_items[0][price]'),'price_test_123');
 assert.equal(parsed.get('metadata[score]'),null);
 assert.equal(req.options.headers['Idempotency-Key'],'tiq12_'+'f'.repeat(32));
 assert.equal(req.options.headers.Authorization.startsWith('Bearer sk_test_'),true);
});
test('unknown checkout session references denied without network',async()=>{
 const adapter=createStripeTestAdapter({secretKey:key,allowedOrigin:'https://nijaaitrading.com',fetchImpl:async()=>{throw Error('must not call')}});
 await assert.rejects(adapter.reconcileCheckout('cs_live_abcdefgh12345'));
});
