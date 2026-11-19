import test from 'node:test';
import assert from 'node:assert/strict';
import {inspectTiq72StripeTestPrice} from '../server/tiq72-stripe-test-readonly-preflight.mjs';

const key=['sk','test','syntheticNoNetwork012345'].join('_');
const fixture={
  STRIPE_TEST_SECRET_KEY:key,
  STRIPE_TEST_WEBHOOK_SECRET:['whsec','fixtureForOfflineTests'].join('_'),
  TIQ72_STRIPE_TEST_PRICE_ID:'price_1UddqtI0gfJjTf3EksOST6m3',
  TIQ72_STRIPE_TEST_PRODUCT_ID:'prod_VexmVpVMZjIj6Y',
  STRIPE_LIVE_MODE:'false',TIQ72_LIVE_PAYMENTS_ENABLED:'false'
};
const price={id:fixture.TIQ72_STRIPE_TEST_PRICE_ID,
  product:fixture.TIQ72_STRIPE_TEST_PRODUCT_ID,
  active:true,livemode:false,unit_amount:100,currency:'usd',type:'one_time'};
const goodResponse=x=>({status:200,ok:true,
  headers:{get:()=>null},text:async()=>JSON.stringify(x)});

test('does not call network when sandbox secret is absent or live-mode credentials are used',async()=>{
  let attempts=0;
  const call=async()=>{attempts+=1;throw Error('network should never execute')};
  const missing=await inspectTiq72StripeTestPrice({},call);
  const live=await inspectTiq72StripeTestPrice({
    ...fixture,STRIPE_TEST_SECRET_KEY:['sk','live','shouldFail123456'].join('_')
  },call);
  const switchOn=await inspectTiq72StripeTestPrice({
    ...fixture,TIQ72_LIVE_PAYMENTS_ENABLED:'true'
  },call);
  assert.equal(attempts,0);
  assert.deepEqual([missing.status,live.status,switchOn.status],['blocked','blocked','blocked']);
});

test('uses read-only GET to verify exact sandbox account price without printing key',async()=>{
  let callCount=0;
  const result=await inspectTiq72StripeTestPrice(fixture,async(url,opts)=>{
    callCount+=1;
    assert.equal(url,'https://api.stripe.com/v1/prices/'+fixture.TIQ72_STRIPE_TEST_PRICE_ID);
    assert.equal(opts.method,'GET');
    assert.equal(opts.headers.Authorization,'Bearer '+key);
    return goodResponse(price);
  });
  assert.equal(callCount,1);
  assert.equal(result.stripe_test_price_verified,true);
  assert.equal(result.checkout_available,false);
  assert.ok(!JSON.stringify(result).includes(key));
});

test('wrong amount, product, live flag, or price rejects otherwise valid response',async()=>{
  for(const variant of [
    {...price,unit_amount:200},
    {...price,product:'prod_other'},
    {...price,livemode:true},
    {...price,id:'price_unexpected'},
    {...price,type:'recurring'}
  ]){
    const result=await inspectTiq72StripeTestPrice(fixture,async()=>goodResponse(variant));
    assert.equal(result.status,'blocked');
    assert.equal(result.checkout_available,false);
    assert.equal(result.reason,'stripe_test_price_identity_mismatch');
  }
});

test('invalid configured offer and unavailable credentials fail closed without remote calls',async()=>{
  let calls=0;
  const result=await inspectTiq72StripeTestPrice({
    ...fixture,TIQ72_STRIPE_TEST_PRODUCT_ID:'prod_other'
  },async()=>{calls+=1;return goodResponse(price)});
  assert.equal(calls,0);
  assert.equal(result.stripe_test_price_verified,false);
  assert.equal(result.reason,'stripe_test_offer_config_mismatch');
});

test('HTTP denial, excessive response size, malformed data and transport errors are sanitized',async()=>{
  for(const request of [
    async()=>({status:401,ok:false}),
    async()=>({status:503,ok:false}),
    async()=>({status:200,ok:true,headers:{get:()=>9000},text:async()=>'{malformed'}),
    async()=>({status:200,ok:true,headers:{get:()=>null},text:async()=>'{malformed'}),
    async()=>{throw Error('secret-sensitive-system-error')}
  ]){
    const result=await inspectTiq72StripeTestPrice(fixture,request);
    assert.equal(result.status,'blocked');
    assert.equal(result.checkout_available,false);
    assert.equal(result.stripe_test_price_verified,false);
    assert.ok(!JSON.stringify(result).includes(key));
    assert.ok(!JSON.stringify(result).includes('secret-sensitive-system-error'));
  }
});
