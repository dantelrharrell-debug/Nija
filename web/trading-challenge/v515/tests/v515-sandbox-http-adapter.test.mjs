import test from "node:test";
import assert from "node:assert/strict";
import {Readable} from "node:stream";
import {createV515SandboxHttpAdapter} from "../server/v515-sandbox-http-adapter.mjs";
import {TEST_PRICE,TEST_PRODUCT} from "../server/verified-report-service.mjs";
const origin="https://game.nijaaitrading.com";
const csrf=["0123456789abcdef","0123456789abcdef"].join("");
const run={mode:"standard",level:"beginner",dayNum:0,
  challenges:Array.from({length:6},()=>Array.from({length:12},()=>({action:"hold",stop:false})))};
const body={attemptKey:"abcdefghijklmnopqrst",adultAttested:true,canonicalRun:run};
function req(method,path,headers={},payload=null){
 const r=Readable.from(payload===null?[]:[Buffer.from(typeof payload==="string"?payload:JSON.stringify(payload))]);
 r.method=method;r.url=path;r.headers=headers;return r;
}
function response(){let statusCode=0,headers={},text="";
 return {setHeader:(k,v)=>{headers[k]=v},end:(v)=>{text=v},
  get statusCode(){return statusCode},set statusCode(v){statusCode=v},
  get headers(){return headers},get value(){return JSON.parse(text)}};
}
function fixture({auth=true,limit=true}={}){
 let stripeCalls=0,storeCalls=0;
 const session={id:"cs_test_fixture",livemode:false,mode:"payment",status:"open",
   payment_status:"unpaid",client_reference_id:"reservation-test",
   metadata:{tiq72_reservation_id:"reservation-test"},
   url:"https://checkout.stripe.com/c/pay/cs_test_fixture"};
 const stripe={prices:{retrieve:async()=>{stripeCalls++;return {
   id:TEST_PRICE,livemode:false,active:true,product:TEST_PRODUCT,
   unit_amount:100,currency:"usd",type:"one_time"}}},
   checkout:{sessions:{create:async()=>{stripeCalls++;return session},
     retrieve:async()=>session}}};
 const store={reserveAuthenticatedRun:async()=>{storeCalls++;
    return {runId:"run-test",reservationId:"reservation-test",sessionId:null,state:"reserved"};},
    attachVerifiedTestCheckout:async()=>{storeCalls++;}};
 const handle=createV515SandboxHttpAdapter({
   authenticate:async()=>auth?{ownerId:"signed-user",csrfToken:csrf}:null,
   rateLimit:async()=>limit,store,stripe,webhookSecret:"whsec_test_placeholder",
   trustedOrigin:origin});
 const call=async(request)=>{const res=response();await handle(request,res);return res};
 return {call,get stripeCalls(){return stripeCalls},get storeCalls(){return storeCalls}};
}
test("authenticated adult can request only a TEST hosted checkout",async()=>{
 const f=fixture();const res=await f.call(req("POST","/sandbox/checkout",
  {origin,"x-csrf-token":csrf},body));
 assert.equal(res.statusCode,200);assert.equal(res.value.runId,"run-test");
 assert.equal(f.storeCalls,2);assert.equal(f.stripeCalls,2);
 assert.equal(res.headers["Cache-Control"],"no-store");
});
test("checkout cannot trust a body-provided identity",async()=>{
 const f=fixture();const res=await f.call(req("POST","/sandbox/checkout",
  {origin,"x-csrf-token":csrf},{...body,ownerId:"attacker"}));
 assert.equal(res.statusCode,400);assert.equal(f.storeCalls,0);
});
test("checkout denies unauthenticated owner before provider use",async()=>{
 const f=fixture({auth:false});const res=await f.call(req("POST","/sandbox/checkout",
  {origin,"x-csrf-token":csrf},body));
 assert.equal(res.statusCode,401);assert.equal(f.stripeCalls,0);
});
test("checkout denies forged origin and CSRF",async()=>{
 const f=fixture();let res=await f.call(req("POST","/sandbox/checkout",
  {origin:"https://evil.example","x-csrf-token":csrf},body));
 assert.equal(res.statusCode,403);
 res=await f.call(req("POST","/sandbox/checkout",
  {origin,"x-csrf-token":"forged"},body));
 assert.equal(res.statusCode,403);assert.equal(f.storeCalls,0);
});
test("wrong HTTP method never reaches provider",async()=>{
 const f=fixture();const res=await f.call(req("GET","/sandbox/checkout"));
 assert.equal(res.statusCode,405);assert.equal(f.stripeCalls,0);
});
test("endpoint has request-rate gate",async()=>{
 const f=fixture({limit:false});const res=await f.call(req("POST","/sandbox/checkout",
  {origin,"x-csrf-token":csrf},body));
 assert.equal(res.statusCode,429);assert.equal(f.storeCalls,0);
});
test("report access requires an authenticated owner",async()=>{
 const f=fixture({auth:false});const res=await f.call(req("GET","/sandbox/report?run_id=run-test"));
 assert.equal(res.statusCode,401);
});
test("report recovery rejects missing or duplicate run identity",async()=>{
 const f=fixture();
 for(const route of ["/sandbox/report","/sandbox/report?run_id=x&run_id=y",
   "/sandbox/report?run_id=x&session_id=cs_test_stolen"]){
   const res=await f.call(req("GET",route));assert.equal(res.statusCode,400);
 }
});
test("webhook never accepts a pre-parsed body",async()=>{
 const f=fixture();const r=req("POST","/sandbox/stripe/webhook",
   {"stripe-signature":"t=123,v1=fixture"},'{"id":"evt_fixture"}');
 r.body={id:"evt_fixture"};
 const res=await f.call(r);
 assert.equal(res.statusCode,400);
});
test("unknown path remains private and not routed",async()=>{
 const f=fixture();const res=await f.call(req("POST","/api/checkout"));
 assert.equal(res.statusCode,404);assert.equal(f.stripeCalls,0);
});
