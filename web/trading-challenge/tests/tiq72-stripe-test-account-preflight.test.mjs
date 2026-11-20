import test from 'node:test';
import assert from 'node:assert/strict';
import {inspectTiq72StripeTestAccount} from '../server/tiq72-stripe-test-account-preflight.mjs';

const key=['sk','test','offlineSyntheticValue012345'].join('_');
const fixture={STRIPE_TEST_SECRET_KEY:key,STRIPE_LIVE_MODE:'false',
  TIQ72_LIVE_PAYMENTS_ENABLED:'false'};
const response=data=>({status:200,ok:true,
  headers:{get:()=>null},text:async()=>JSON.stringify(data)});

test('current account matches authenticated NIJA sandbox without leaking its ID or secret',async()=>{
  let calls=0;
  const result=await inspectTiq72StripeTestAccount(fixture,async(url,options)=>{
    calls+=1;
    assert.equal(url,'https://api.stripe.com/v1/account');
    assert.equal(options.method,'GET');
    assert.equal(options.headers.Authorization,'Bearer '+key);
    return response({object:'account',id:'acct_1Tzy1CRS5Ezp77RQ'});
  });
  assert.equal(calls,1);
  assert.deepEqual(result,{status:'sandbox_account_verified_read_only',
    stripe_test_account_verified:true,checkout_available:false});
  assert.ok(!JSON.stringify(result).includes(key));
  assert.ok(!JSON.stringify(result).includes('acct_'));
});

test('a TEST key owned by a different Stripe account fails closed and does not expose its ID',async()=>{
  const other='acct_wrongDifferentAccount9999';
  const result=await inspectTiq72StripeTestAccount(fixture,async()=>response({
    object:'account',id:other
  }));
  assert.deepEqual(result,{status:'blocked',reason:'stripe_test_account_mismatch',
    stripe_test_account_verified:false,checkout_available:false});
  assert.ok(!JSON.stringify(result).includes(other));
});

test('missing or live-mode keys and live switches make zero provider calls',async()=>{
  let calls=0;
  const request=async()=>{calls++;throw Error('network_fails_closed')};
  for(const env of [{}, {...fixture,STRIPE_TEST_SECRET_KEY:['sk','live','fixture123456'].join('_')},
    {...fixture,STRIPE_LIVE_MODE:'true'},
    {...fixture,TIQ72_LIVE_PAYMENTS_ENABLED:'true'},
    {...fixture,STRIPE_LIVE_SECRET_KEY:key}]) {
    const got=await inspectTiq72StripeTestAccount(env,request);
    assert.equal(got.status,'blocked');
    assert.equal(got.checkout_available,false);
  }
  assert.equal(calls,0);
});

test('missing permissions, provider errors and oversized or malformed response fail closed',async()=>{
  const other='acct_wrongDifferentAccount9999';
  const cases=[
    async()=>({status:401,ok:false}),
    async()=>({status:403,ok:false}),
    async()=>({status:503,ok:false}),
    async()=>({status:200,ok:true,headers:{get:()=>70000}}),
    async()=>response({id:other}),
    async()=>({status:200,ok:true,headers:{get:()=>null},text:async()=>'{invalid'}),
    async()=>{throw Error('private-provider-error-should-not-leak')}
  ];
  for(const request of cases) {
    const result=await inspectTiq72StripeTestAccount(fixture,request);
    assert.equal(result.status,'blocked');
    assert.equal(result.stripe_test_account_verified,false);
    assert.equal(result.checkout_available,false);
    assert.ok(!JSON.stringify(result).includes(other));
    assert.ok(!JSON.stringify(result).includes('private-provider-error'));
  }
});
