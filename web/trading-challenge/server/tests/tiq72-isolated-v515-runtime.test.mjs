import test from 'node:test';
import assert from 'node:assert/strict';
import {randomBytes} from 'node:crypto';
import {createNonRoutedTiq72SandboxDependencies} from '../tiq72-isolated-v515-runtime.mjs';

const key=['sk','test',randomBytes(24).toString('hex')].join('_');
const hook=['whsec',randomBytes(24).toString('hex')].join('_');
function privateUrl() {
  // Build only an inert synthetic credential; no test opens a DB connection.
  const u=new URL('postgresql://synthetic.invalid');
  u.hostname='dpg-dbqeq90ae00c7386p970-a';
  u.username='nija_tiq72_upgrade6_isolated_test_user';
  u.password=['CI','synthetic','not_real'].join('_');
  u.pathname='/nija_tiq72_upgrade6_isolated_test';
  u.search='?sslmode=require';
  return u.href;
}
const valid={
  STRIPE_TEST_SECRET_KEY:key,
  STRIPE_TEST_WEBHOOK_SECRET:hook,
  TIQ72_STRIPE_TEST_PRICE_ID:'price_1UYToJRS5Ezp77RQVkx96eS5',
  TIQ72_STRIPE_TEST_PRODUCT_ID:'prod_nija_iq72_sandbox_v1',
  TIQ72_TEST_DATABASE_URL:privateUrl(),
  TIQ72_TEST_RETURN_ORIGIN:'https://game.nijaaitrading.com',
  TIQ_ALLOWED_ORIGIN:'https://game.nijaaitrading.com',
  STRIPE_LIVE_MODE:'false',
  TIQ72_LIVE_PAYMENTS_ENABLED:'false',
  NIJA_GAME_REPORTS_ENABLED:'false',
  NIJA_GAME_BROWSER_CHECKOUT_ENABLED:'false',
  TIQ72_TEST_OWNER_SIGNING_KEY_B64URL:randomBytes(48).toString('base64url')
};
function harness(env=valid) {
  let stripes=0,pools=0,closings=0,dbQueries=0;
  const pool={connect(){dbQueries++;throw Error('no database connections');},
    query(){dbQueries++;throw Error('no database queries');},
    async end(){closings++;}};
  const runtime = createNonRoutedTiq72SandboxDependencies({
    env,rateLimit:async()=>true,
    stripeFactory:provided=>{stripes++;assert.equal(provided,key);return {};},
    poolFactory:options=>{
      pools++;assert.equal(options.connectionString,valid.TIQ72_TEST_DATABASE_URL);
      assert.equal(options.max,2);
      return pool;
    }
  });
  return {runtime,get counts(){return {stripes,pools,closings,dbQueries}}};
}

test('building dependencies constructs no live API calls, DB queries or HTTP listener',async()=>{
  const h=harness();
  assert.equal(typeof h.runtime.handler,'function');
  assert.deepEqual(h.counts,{stripes:1,pools:1,closings:0,dbQueries:0});
  assert.deepEqual(Object.keys(h.runtime).sort(),['close','handler']);
  assert.equal(JSON.stringify(h.runtime).includes(key),false);
  await h.runtime.close();
  assert.deepEqual(h.counts,{stripes:1,pools:1,closings:1,dbQueries:0});
});

test('rejects missing keys, live flags, wrong DB/price/origin and absent rate limit before clients',()=>{
  for (const [name,env] of [
    ['missing_api_key',{...valid,STRIPE_TEST_SECRET_KEY:''}],
    ['live_api_key',{...valid,STRIPE_TEST_SECRET_KEY:['sk','live','fixture12345678901234567'].join('_')}],
    ['wrong_postgres_workspace',{...valid,TIQ72_TEST_DATABASE_URL:valid.TIQ72_TEST_DATABASE_URL.replace(
      'dpg-dbqeq90ae00c7386p970-a','dpg-dbsuhuc9v7es73bmteeg-a')}],
    ['wrong_price',{...valid,TIQ72_STRIPE_TEST_PRICE_ID:'price_incorrect'}],
    ['wrong_product',{...valid,TIQ72_STRIPE_TEST_PRODUCT_ID:'prod_incorrect'}],
    ['unsafe_origin',{...valid,TIQ_ALLOWED_ORIGIN:'https://malicious.invalid'}],
    ['live_switch',{...valid,STRIPE_LIVE_MODE:'true'}],
    ['browser_checkout_switch',{...valid,NIJA_GAME_BROWSER_CHECKOUT_ENABLED:'true'}],
    ['short_issuer_key',{...valid,TIQ72_TEST_OWNER_SIGNING_KEY_B64URL:randomBytes(8).toString('base64url')}]
  ]) {
    let created=0;
    assert.throws(()=>createNonRoutedTiq72SandboxDependencies({
      env,rateLimit:async()=>true,
      stripeFactory:()=>{created++;return {};},
      poolFactory:()=>{created++;return {connect(){},query(){},end(){}};}
    }),{name:'TypeError'},name);
    assert.equal(created,0,name);
  }
  assert.throws(()=>createNonRoutedTiq72SandboxDependencies({
    env:valid,rateLimit:null,
    stripeFactory:()=>{throw Error('MUST_NOT_OPEN_STRIPE')},
    poolFactory:()=>{throw Error('MUST_NOT_OPEN_DB')}
  }),{name:'TypeError'});
});

function fakeRes() {
  const headers={};
  return {headers,setHeader:(name,value)=>{headers[name]=value;},
    end(data){this.data=JSON.parse(data);}};
}

test('signed handler denies unsigned checkout and report before any Stripe/DB call',async()=>{
  const h=harness();
  for(const [method,url] of [
    ['POST','/sandbox/checkout'],['GET','/sandbox/report?run_id=random']
  ]){
    const res=fakeRes();
    await h.runtime.handler({
      method,url,headers:{origin:valid.TIQ_ALLOWED_ORIGIN}
    },res);
    assert.equal(res.statusCode,401);
    assert.equal(res.data.error,'authentication_required');
    assert.equal(res.data.checkoutUrl,undefined);
    assert.equal(h.counts.dbQueries,0);
  }
  await h.runtime.close();
});
