import test from "node:test";
import assert from "node:assert/strict";
import {Readable} from "node:stream";
import {createTiq72CustomerTestBridge} from "../server/v515-customer-test-bridge.mjs";
import {V515PgReportStore} from "../server/v515-pg-report-store.mjs";
import {TEST_PRICE,TEST_PRODUCT} from "../server/tiq72-test-offer.mjs";

const origin="https://nija-trading-challenge-staging.vercel.app";
const sid="cs_test_SyntheticReturnFixture", csrf="x".repeat(43);
const active={active:true,adultVerified:true,ownerId:"qa-owner",csrfToken:csrf};
const canonicalRun={mode:"standard",level:"beginner",dayNum:0,
  challenges:Array.from({length:6},()=>Array.from({length:12},()=>({action:"hold",stop:false})))};

async function invoke(handler,{path="/sandbox/report/return?session_id="+sid,method="GET",headers={},body}={}){
  const req=Object.assign(Readable.from(body?[Buffer.from(JSON.stringify(body))]:[]),{url:path,method,headers});
  const res={writeHead(status,h){this.status=status;this.headers=h;this.headersSent=true;},
    setHeader(k,v){(this.headers??={})[k]=v;},
    end(s){this.status??=this.statusCode;this.body=JSON.parse(s);}};
  await handler(req,res);
  return res;
}
function fixture(overrides={}){
  let reads=0, builds=0, created;
  const session={id:sid,livemode:false,mode:"payment",status:"complete",payment_status:"paid",
    client_reference_id:"res-one",metadata:{tiq72_reservation_id:"res-one"},
    amount_total:100,amount_subtotal:100,currency:"usd",payment_intent:"pi_fixture123"};
  const price={id:TEST_PRICE,product:TEST_PRODUCT,active:true,livemode:false,unit_amount:100,currency:"usd",type:"one_time"};
  const stripe={prices:{retrieve:async()=>price},checkout:{sessions:{
    retrieve:async()=>session,
    listLineItems:async()=>({data:[{quantity:1,price}],has_more:false}),
    create:async payload=>{created=payload;return {...session,payment_status:"unpaid",status:"open",
      url:"https://checkout.stripe.com/g/pay/"+sid};}
  }},paymentIntents:{retrieve:async()=>({id:"pi_fixture123",livemode:false,status:"succeeded",
    amount_received:100,currency:"usd",latest_charge:"ch_fixture123"})},
  charges:{retrieve:async()=>({id:"ch_fixture123",livemode:false,status:"succeeded",paid:true,
    amount:100,currency:"usd",payment_intent:"pi_fixture123",refunded:false,disputed:false,amount_refunded:0})}};
  const store={
    findOwnedTestReturn:async(owner,id)=>{reads++;return owner===active.ownerId&&id===sid?
      {runId:"run-one",state:"paid"}:null;},
    getOwnedPurchase:async(owner,runId)=>({ownerId:owner,runId,reservationId:"res-one",sessionId:sid,canonicalRun,state:"paid"}),
    storeVerifiedReport:async()=>{builds++;},
    getOwnedPaidReport:async()=>({tradingIQ:70}),
    reserveAuthenticatedRun:async()=>({runId:"run-one",reservationId:"res-one",state:"reserved"}),
    attachVerifiedTestCheckout:async()=>{},
  };
  const config={enabled:true,previewOrigin:origin,verifyBuyer:async()=>active,takeRateLimit:async()=>true,store,stripe,
    webhookSecret:["whsec","SyntheticFixture0123456789"].join("_")};
  return {config:{...config,...overrides},store,stripe,get reads(){return reads;},get builds(){return builds;},get created(){return created;}};
}
const hand=f=>createTiq72CustomerTestBridge(f.config);

test("default off, only exact verified staging origin may opt in",async()=>{
  assert.equal((await invoke(createTiq72CustomerTestBridge())).status,503);
  for(const previewOrigin of ["https://game.nijaaitrading.com",origin+":1234",origin+"/","https://example.com"])
    assert.throws(()=>hand(fixture({previewOrigin})),/protected_test_preview_dependencies_required/);
});
test("anonymous, inactive and unverified-adult buyers cannot look up a report",async()=>{
  for(const value of [null,{...active,active:false},{...active,adultVerified:false},{...active,csrfToken:null}]){
    const f=fixture({verifyBuyer:async()=>value});
    assert.equal((await invoke(hand(f))).status,401);
    assert.equal(f.reads,0);
  }
});
test("cross-site, spoofed owner and live checkout IDs cannot read the ledger",async()=>{
  const f=fixture();
  for(const [request,status] of [
    [{headers:{origin:"https://example.com"}},403],
    [{headers:{"sec-fetch-site":"cross-site"}},403],
    [{path:"/sandbox/report/return?session_id="+sid+"&ownerId=qa-owner"},400],
    [{path:"/sandbox/report/return?session_id=cs_live_notallowed"},400],
    [{path:"/sandbox/report/return?session_id="+sid+"&session_id="+sid},400],
  ]) assert.equal((await invoke(hand(f),request)).status,status);
  assert.equal(f.reads,0);
});
test("rate limit is fail-closed before identity and storage",async()=>{
  const f=fixture({takeRateLimit:async()=>false});
  assert.equal((await invoke(hand(f))).status,429);
  assert.equal(f.reads,0);
});
test("different authenticated buyer gets no report",async()=>{
  const f=fixture({verifyBuyer:async()=>({...active,ownerId:"another-adult"})});
  assert.equal((await invoke(hand(f))).status,404);
  assert.equal(f.builds,0);
});
test("pending and reversed reservations stay inaccessible",async()=>{
  for(const [state,status] of [["checkout_created",409],["refunded",403],["disputed",403]]){
    const f=fixture();
    f.store.findOwnedTestReturn=async()=>({runId:"run-one",state});
    assert.equal((await invoke(hand(f))).status,status);
    assert.equal(f.builds,0);
  }
});
test("checkout uses existing 72-decision validation, strict CSRF and staging return",async()=>{
  const f=fixture();
  const request={path:"/sandbox/checkout",method:"POST",
    headers:{origin,"x-csrf-token":csrf},
    body:{attemptKey:"synthetic-attempt-001",adultAttested:true,canonicalRun}};
  assert.equal((await invoke(hand(f),{...request,headers:{origin,"x-csrf-token":"y".repeat(43)}})).status,403);
  assert.equal(f.created,undefined);
  const r=await invoke(hand(f),request);
  assert.equal(r.status,200);
  assert.equal(f.created.success_url,origin+"/trading-iq-challenge/payment-return?session_id={CHECKOUT_SESSION_ID}");
  assert.deepEqual(f.created.line_items,[{price:TEST_PRICE,quantity:1}]);
});
test("verified paid session still requires fresh Stripe evidence and sends no-store report",async()=>{
  const f=fixture();
  const r=await invoke(hand(f));
  assert.equal(r.status,200);
  assert.equal(r.body.report.tradingIQ,70);
  assert.equal(r.headers["Cache-Control"],"private, no-store");
  assert.equal(r.headers["Referrer-Policy"],"no-referrer");
  f.stripe.charges.retrieve=async()=>({refunded:true});
  assert.equal((await invoke(hand(f))).status,403);
});
test("database lookup is parameterized, scoped to buyer and exact TEST session",async()=>{
  const queries=[];
  const store=new V515PgReportStore({connect(){},async query(sql,params){
    queries.push({sql,params});return {rows:[{run_id:"run-one",state:"paid"}]};
  }});
  assert.equal(await store.findOwnedTestReturn(active.ownerId,"cs_live_notallowed"),null);
  assert.deepEqual(await store.findOwnedTestReturn(active.ownerId,sid),{runId:"run-one",state:"paid"});
  assert.equal(queries.length,1);
  assert.match(queries[0].sql,/owner_id=\$1 AND stripe_session=\$2/);
  assert.deepEqual(queries[0].params,[active.ownerId,sid]);
});
