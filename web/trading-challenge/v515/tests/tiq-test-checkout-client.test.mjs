import assert from "node:assert/strict";
import test from "node:test";
import {prepareTiqTestCheckout} from "../src/lib/tiqTestCheckoutClient.mjs";

const origin="https://nija-trading-challenge-staging.vercel.app";
const token="Q".repeat(43), nextToken="R".repeat(43);
const hostUrl="https://checkout.stripe.com/c/pay/cs_test_SyntheticForUnitTest#fixture";
const csrfKey=["x","csrf","token"].join("-");
const game=()=>({screen:"done",mode:"daily",level:"intermediate",dayNum:19001,
  list:Array.from({length:6},()=>({name:"fixture"})),
  decLog:Array.from({length:72},(_,n)=>({action:["buy","hold","sell"][n%3],stop:n%4===0})),
  ownerId:"must-not-send",tradingIQ:100});
const random={getRandomValues(bytes){bytes.fill(42);return bytes;}};
const yes={adultAttested:true};
const method=(request)=>({flag:"true",origin,request,crypto:random});
const fake=(checkoutUrl=hostUrl,runId="run-fixture")=>async(path)=>{
  return path.endsWith("/session")?Response.json({csrfToken:token}):Response.json({checkoutUrl,runId});
};

test("no network or random attempt outside exact opt-in staging or after an invalid run",async()=>{
  const state=game(),request=()=>assert.fail("not allowed to request");
  const crypto={getRandomValues(){assert.fail("not allowed to create attempt");}};
  for(const flags of [
    {flag:"false"}, {flag:true}, {origin:"https://nija-trading-challenge.vercel.app"},
    {origin:"https://game.nijaaitrading.com"}, {origin:origin+"/"}, {origin:origin+":444"}
  ])assert.equal(prepareTiqTestCheckout(state,{...method(request),crypto,...flags}),null);
  for(const candidate of [
    {...state,screen:"round"}, {...state,list:state.list.slice(0,5)},
    {...state,decLog:state.decLog.slice(0,71)}, {...state,decLog:new Array(72)},
    {...state,decLog:[{action:"buy",stop:1},...state.decLog.slice(1)]},
    {...state,decLog:[{action:"invented",stop:false},...state.decLog.slice(1)]}
  ])assert.equal(prepareTiqTestCheckout(candidate,{...method(request),crypto}),null);
});

test("same-origin request sends the exact completed 72 decisions with CSRF and no client scoring",async()=>{
  const bodyExpected=game().decLog;
  const state=game(), calls=[];
  const h=prepareTiqTestCheckout(state,method(async(path,options)=>{
    calls.push([path,options]);
    if(options.method==="GET")return Response.json({csrfToken:token,ownerId:"ignore"});
    return Response.json({checkoutUrl:hostUrl,runId:"run-fixture"});
  }));
  // Prepared run stays stable independently of any later browser UI state.
  state.decLog[0]={action:"sell",stop:false};
  assert.deepEqual(await h.start(),{state:"not_eligible"});
  assert.deepEqual(await h.start(yes),{state:"ready",checkoutUrl:hostUrl,runId:"run-fixture"});
  assert.deepEqual(calls.map(x=>[x[0],x[1].method]),[
    ["/sandbox/checkout/session","GET"],["/sandbox/checkout","POST"]
  ]);
  for(const [,v] of calls){
    assert.equal(v.credentials,"same-origin");
    assert.equal(v.mode,"same-origin");
    assert.equal(v.cache,"no-store");
    assert.equal(v.redirect,"error");
    assert.equal(v.referrerPolicy,"no-referrer");
  }
  assert.equal(calls[0][1].headers[csrfKey],undefined);
  assert.equal(calls[1][1].headers[csrfKey],token);
  const body=JSON.parse(calls[1][1].body);
  assert.deepEqual(Object.keys(body),["attemptKey","adultAttested","canonicalRun"]);
  assert.equal(body.adultAttested,true);
  assert.match(body.attemptKey,/^[0-9a-f]{48}$/);
  assert.deepEqual(Object.keys(body.canonicalRun),["mode","level","dayNum","challenges"]);
  assert.deepEqual(body.canonicalRun.challenges.map(x=>x.length),[12,12,12,12,12,12]);
  assert.deepEqual(body.canonicalRun.challenges.flat(),bodyExpected);
});

test("in-flight calls coalesce; uncertain retries keep key but fetch fresh session CSRF",async()=>{
  const keys=[],seenTokens=[];let getCount=0;
  const checkout=prepareTiqTestCheckout(game(),method(async(path,options)=>{
    if(path.endsWith("/session"))return Response.json({csrfToken:getCount++?nextToken:token});
    const body=JSON.parse(options.body);keys.push(body.attemptKey);seenTokens.push(options.headers[csrfKey]);
    if(keys.length===1)throw Error("simulated response loss");
    return Response.json({checkoutUrl:hostUrl,runId:"run-fixture"});
  }));
  const first=checkout.start(yes), second=checkout.start(yes);
  assert.strictEqual(first,second);
  assert.deepEqual(await first,{state:"retry"});
  assert.equal((await checkout.start(yes)).state,"ready");
  assert.equal(keys.length,2);
  assert.equal(keys[0],keys[1]);
  assert.deepEqual(seenTokens,[token,nextToken]);
});

test("fail closed on missing eligible bootstrap, bad media, abort, or malformed CSRF",async()=>{
  for(const [response,status] of [
    [new Response(null,{status:401}),"sign_in"], [new Response(null,{status:403}),"not_eligible"],
    [new Response(null,{status:429}),"retry"], [new Response(null,{status:503}),"retry"],
    [new Response("<html>wrong origin response</html>",{status:200}),"unavailable"],
    [Response.json({csrfToken:[token]}),"unavailable"]
  ]){
    const h=prepareTiqTestCheckout(game(),method(async path=>{
      assert.equal(path,"/sandbox/checkout/session");return response;
    }));
    assert.deepEqual(await h.start(yes),{state:status});
  }
  const controller=new AbortController();controller.abort();
  const h=prepareTiqTestCheckout(game(),method(()=>assert.fail("already aborted")));
  assert.deepEqual(await h.start({...yes,signal:controller.signal}),{state:"retry"});
});

test("only an exact Stripe TEST Checkout URL is accepted, no live, unrelated or unsafe redirect",async()=>{
  for(const url of [
    "https://checkout.stripe.com/c/pay/cs_live_NotAllowed",
    "http://checkout.stripe.com/c/pay/cs_test_SyntheticForUnitTest",
    "https://checkout.stripe.com.evil.invalid/c/pay/cs_test_SyntheticForUnitTest",
    "https://checkout.stripe.com:444/c/pay/cs_test_SyntheticForUnitTest",
    "https://foo@checkout.stripe.com/c/pay/cs_test_SyntheticForUnitTest",
    "https://checkout.stripe.com/c/pay/cs_test_SyntheticForUnitTest?other=1",
    "https://checkout.stripe.com/redirect/cs_test_SyntheticForUnitTest",
    "/c/pay/cs_test_SyntheticForUnitTest"
  ])assert.deepEqual(await prepareTiqTestCheckout(game(),method(fake(url))).start(yes),{state:"unavailable"});
  assert.deepEqual(await prepareTiqTestCheckout(game(),method(fake(hostUrl,["run-fixture"]))).start(yes),
    {state:"unavailable"});
});
