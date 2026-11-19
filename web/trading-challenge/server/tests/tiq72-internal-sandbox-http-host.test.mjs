// Regression tests for isolated internal TEST host, using only inert fixtures.
// These tests never create a Stripe charge, open a database, or issue owner proofs.
import test from 'node:test';
import assert from 'node:assert/strict';
import {once} from 'node:events';
import {
  makeInternalSandboxRateLimiter,
  requireIsolatedSandboxHostScope,
  createTiq72InternalSandboxHttpHost
} from '../tiq72-internal-sandbox-http-host.mjs';

const ORIGIN='https://game.nijaaitrading.com';
const scope=Object.freeze({
  RENDER_SERVICE_ID:'srv-dbqeqgqfngtc73fcphhg',
  TIQ72_ISOLATED_BUILD_SCOPE:'holding-test-only',
  TIQ72_INTERNAL_SANDBOX_ROUTE_REVIEW:'APPROVED_INTERNAL_TEST_ONLY',
  TIQ72_LIVE_PAYMENTS_ENABLED:'false',
  STRIPE_LIVE_MODE:'false',
  NIJA_GAME_REPORTS_ENABLED:'false',
  NIJA_GAME_BROWSER_CHECKOUT_ENABLED:'false',
  TIQ_ALLOWED_ORIGIN:ORIGIN,
  TIQ72_TEST_RETURN_ORIGIN:ORIGIN
});
const fakeDb=()=>({status:'identity_verified_read_only',
  expected_schema_present:true,schema_contract_verified:true,expected_tables_missing:[]});
const fakePrice=async()=>({status:'price_verified_test_mode_read_only',
  stripe_test_price_verified:true});

test('scope validation fails before provider use for wrong or missing flags',async()=>{
  for(const [name,env] of [
    ['wrong_service',{...scope,RENDER_SERVICE_ID:'srv-production'}],
    ['missing_explicit_review',{...scope,TIQ72_INTERNAL_SANDBOX_ROUTE_REVIEW:''}],
    ['missing_build_scope',{...scope,TIQ72_ISOLATED_BUILD_SCOPE:''}],
    ['browser_checkout_enabled',{...scope,NIJA_GAME_BROWSER_CHECKOUT_ENABLED:'true'}],
    ['reports_enabled',{...scope,NIJA_GAME_REPORTS_ENABLED:'true'}],
    ['live_enabled',{...scope,TIQ72_LIVE_PAYMENTS_ENABLED:'true'}],
    ['stripe_live_enabled',{...scope,STRIPE_LIVE_MODE:'true'}],
    ['wrong_origin',{...scope,TIQ_ALLOWED_ORIGIN:'https://unsafe.example'}]
  ]){
    let calls=0;
    await assert.rejects(()=>createTiq72InternalSandboxHttpHost({
      env,
      databaseProbe:()=>{calls++;return fakeDb();},
      priceProbe:()=>{calls++;return fakePrice();},
      dependenciesFactory:()=>{calls++;throw Error('unexpected_provider_access');}
    }),{name:'TypeError',message:'isolated_sandbox_host_scope_denied'},name);
    assert.equal(calls,0,name);
  }
});

test('missing reviewed schema or validated Stripe TEST price rejects before dependency construction',async()=>{
  let dependencies=0;
  await assert.rejects(()=>createTiq72InternalSandboxHttpHost({
    env:scope,databaseProbe:()=>({...fakeDb(),expected_schema_present:false,
      expected_tables_missing:['tiq72_v515_runs']}),
    priceProbe:()=>{throw Error('price_must_not_be_checked_after_missing_db');},
    dependenciesFactory:()=>{dependencies++;throw Error('no');}
  }),{message:'isolated_sandbox_schema_unavailable'});
  await assert.rejects(()=>createTiq72InternalSandboxHttpHost({
    env:scope,databaseProbe:fakeDb,priceProbe:async()=>({
      status:'blocked',stripe_test_price_verified:false}),
    dependenciesFactory:()=>{dependencies++;throw Error('no');}
  }),{message:'isolated_sandbox_stripe_price_unavailable'});
  await assert.rejects(()=>createTiq72InternalSandboxHttpHost({
    env:scope,databaseProbe:()=>({...fakeDb(),schema_contract_verified:false}),
    priceProbe:()=>{throw Error('price_must_not_be_checked_after_invalid_contract');},
    dependenciesFactory:()=>{dependencies++;throw Error('no');}
  }),{message:'isolated_sandbox_schema_unavailable'});
  assert.equal(dependencies,0);
});

test('internal host serves only health and explicitly permitted TEST routes',async t=>{
  let handled=0,closed=0,constructed=0;
  const host=await createTiq72InternalSandboxHttpHost({
    env:scope,databaseProbe:fakeDb,priceProbe:fakePrice,
    dependenciesFactory:()=>{
      constructed++;
      return {
        handler:async (_req,res)=>{
          handled++;res.statusCode=401;
          res.setHeader('Content-Type','application/json');
          res.end(JSON.stringify({error:'authentication_required'}));
        },
        close:async()=>{closed++;}
      };
    }
  });
  host.server.listen(0,'127.0.0.1');
  await once(host.server,'listening');
  t.after(async()=>{
    await new Promise((resolve,reject)=>host.server.close(e=>e?reject(e):resolve()));
    await host.close();
    assert.equal(closed,1);
  });
  const base='http://127.0.0.1:'+host.server.address().port;
  const health=await fetch(base+'/healthz');
  assert.equal(health.status,200);
  const state=await health.json();
  assert.equal(state.status,'internal_test_only');
  assert.equal(state.decisions,72);
  assert.equal(state.customer_checkout_available,false);
  assert.equal(state.sandbox_e2e_certified,false);
  assert.equal(state.live_payments_enabled,false);
  assert.equal(health.headers.get('cache-control'),'no-store');
  assert.equal(health.headers.get('x-content-type-options'),'nosniff');

  const unknown=await fetch(base+'/api/tiq72/checkout',{method:'POST'});
  assert.equal(unknown.status,404);
  const wrongMethod=await fetch(base+'/sandbox/checkout');
  assert.equal(wrongMethod.status,405);
  const query=await fetch(base+'/sandbox/checkout?force=true',{method:'POST'});
  assert.equal(query.status,400);
  const badOrigin=await fetch(base+'/sandbox/checkout',{method:'POST',headers:{Origin:'https://evil.invalid'}});
  assert.equal(badOrigin.status,403);
  const denied=await fetch(base+'/sandbox/checkout',{method:'POST',headers:{Origin:ORIGIN}});
  assert.equal(denied.status,401);
  assert.equal((await denied.json()).error,'authentication_required');
  const report=await fetch(base+'/sandbox/report?run_id=unpaid',{headers:{Origin:ORIGIN}});
  assert.equal(report.status,401);
  const webhook=await fetch(base+'/sandbox/stripe/webhook',{method:'POST'});
  assert.equal(webhook.status,401);
  assert.equal(handled,3);
  assert.equal(constructed,1);

  const preflight=await fetch(base+'/sandbox/checkout',{
    method:'OPTIONS',headers:{Origin:ORIGIN}});
  assert.equal(preflight.status,204);
  assert.equal(preflight.headers.get('access-control-allow-origin'),ORIGIN);
  const webhookPreflight=await fetch(base+'/sandbox/stripe/webhook',{
    method:'OPTIONS',headers:{Origin:ORIGIN}});
  assert.equal(webhookPreflight.status,403);
});

test('single-instance internal rate gate denies unknown categories and bursts',async()=>{
  let tick=10000;
  const limit=makeInternalSandboxRateLimiter(()=>tick);
  assert.equal(await limit({},'unsupported'),false);
  for(let i=0;i<30;i++)assert.equal(await limit({},'authenticated_commerce'),true);
  assert.equal(await limit({},'authenticated_commerce'),false);
  tick+=60000;
  assert.equal(await limit({},'authenticated_commerce'),true);
});
