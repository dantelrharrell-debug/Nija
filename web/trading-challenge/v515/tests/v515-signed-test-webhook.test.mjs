import test from "node:test";
import assert from "node:assert/strict";
import {processSignedTestWebhook} from "../server/v515-signed-test-webhook.mjs";
import {PaidReportDenied,TEST_PRICE,TEST_PRODUCT} from "../server/verified-report-service.mjs";
function fixture(eventType="checkout.session.completed") {
 const sid="cs_test_fixture",rid="reservation-fixture",pid="pi_fixture",cid="ch_fixture";
 const session={id:sid,livemode:false,mode:"payment",status:"complete",payment_status:"paid",
  client_reference_id:rid,metadata:{tiq72_reservation_id:rid},payment_intent:pid,
  amount_subtotal:100,amount_total:100,currency:"usd"};
 const lines={data:[{quantity:1,price:{id:TEST_PRICE,product:TEST_PRODUCT,unit_amount:100,currency:"usd"}}],has_more:false};
 const intent={id:pid,livemode:false,status:"succeeded",amount_received:100,currency:"usd",latest_charge:cid};
 const charge={id:cid,livemode:false,status:"succeeded",paid:true,amount:100,currency:"usd",
  payment_intent:pid,refunded:false,disputed:false,amount_refunded:0};
 const dispute={id:"dp_fixture",livemode:false,charge:cid};
 const obj=eventType==="charge.refunded"?{id:cid}:
   eventType==="charge.dispute.created"?{id:dispute.id,charge:cid}:{id:sid};
 const event={id:"evt_fixture",type:eventType,livemode:false,data:{object:obj}};
 let records=[],rawSeen=null,providerCalls=0;
 const stripe={
   webhooks:{constructEvent:(body,signature,secret)=>{
     rawSeen=body;
     if(signature!=="t=fixture,v1=valid"||secret!=="whsec_fixture")
       throw new Error("signature verification failed");
     return event;
   }},
   checkout:{Session:{
     retrieve:async()=>{providerCalls++;return session;},
     listLineItems:async()=>{providerCalls++;return lines;},
     list:async()=>({data:[{id:sid}],has_more:false})}},
   PaymentIntent:{retrieve:async()=>{providerCalls++;return intent;}},
   Charge:{retrieve:async()=>{providerCalls++;return charge;}},
   Dispute:{retrieve:async()=>{providerCalls++;return dispute;}}
 };
 const store={recordVerifiedProviderEvent:async(x)=>{records.push(x);return {duplicate:false,state:eventType.startsWith("checkout.")?"paid":"refunded"};}};
 const rawBody=Buffer.from('{"id":"evt_fixture"}');
 const run=(overrides={})=>processSignedTestWebhook({rawBody,signature:"t=fixture,v1=valid",webhookSecret:"whsec_fixture",stripe,store,...overrides});
 return {session,lines,intent,charge,event,dispute,store,stripe,rawBody,run,get records(){return records},get rawSeen(){return rawSeen},get providerCalls(){return providerCalls}};
}
test("signed checkout independently verifies payment before grant",async()=>{
 const f=fixture();assert.deepEqual(await f.run(),{processed:true,duplicate:false,state:"paid"});
 assert.equal(f.rawSeen,f.rawBody);assert.equal(f.records.length,1);
 assert.equal(f.records[0].reservationId,"reservation-fixture");
 assert.equal(f.providerCalls,4);
});
test("signature rejection never calls provider or store",async()=>{
 const f=fixture();await assert.rejects(f.run({signature:"t=bad"}),/signature verification failed/);
 assert.equal(f.providerCalls,0);assert.equal(f.records.length,0);
});
test("live event rejected",async()=>{
 const f=fixture();f.event.livemode=true;
 await assert.rejects(f.run(),/signed_test_event_required/);
 assert.equal(f.records.length,0);
});
for(const [field,value] of [["amount_total",101],["client_reference_id","other"],["livemode",true]]){
 test("wrong checkout identity "+field+" blocked",async()=>{
  const f=fixture();f.session[field]=value;
  await assert.rejects(f.run(),e=>e instanceof PaidReportDenied);
  assert.equal(f.records.length,0);
 });
}
test("wrong Stripe test product is rejected",async()=>{
 const f=fixture();f.lines.data[0].price.id="price_wrong";
 await assert.rejects(f.run(),/test_product_mismatch/);
 assert.equal(f.records.length,0);
});
test("refunded charge cannot be paid",async()=>{
 const f=fixture();f.charge.refunded=true;f.charge.amount_refunded=100;
 await assert.rejects(f.run(),/charge_not_verified/);assert.equal(f.records.length,0);
});
test("refund event requires independently confirmed provider refund",async()=>{
 const f=fixture("charge.refunded");
 await assert.rejects(f.run(),/refund_not_verified/);
 assert.equal(f.records.length,0);
 f.charge.refunded=true;f.charge.amount_refunded=100;
 assert.deepEqual(await f.run(),{processed:true,duplicate:false,state:"refunded"});
 assert.equal(f.records[0].eventType,"charge.refunded");
});
test("dispute event requires independently matching Stripe dispute",async()=>{
 const f=fixture("charge.dispute.created");
 f.dispute.charge="ch_other";
 await assert.rejects(f.run(),/dispute_not_verified/);
 assert.equal(f.records.length,0);
 f.dispute.charge=f.charge.id;
 assert.equal((await f.run()).processed,true);
 assert.equal(f.records[0].eventType,"charge.dispute.created");
});
test("reversal must map to exactly one test checkout",async()=>{
 const f=fixture("charge.refunded");f.charge.refunded=true;f.charge.amount_refunded=100;
 f.stripe.checkout.Session.list=async()=>({data:[{id:f.session.id},{id:"cs_test_other"}],has_more:false});
 await assert.rejects(f.run(),/unique_checkout_required/);
 assert.equal(f.records.length,0);
});
test("unsupported event safely ignored",async()=>{
 const f=fixture();f.event.type="ping";
 assert.deepEqual(await f.run(),{ignored:true});assert.equal(f.records.length,0);
});
test("nonraw or oversized body rejected before verification",async()=>{
 const f=fixture();await assert.rejects(f.run({rawBody:"body"}),/webhook_context_required/);
 await assert.rejects(f.run({rawBody:Buffer.alloc(65537)}),/webhook_context_required/);
 assert.equal(f.providerCalls,0);
});
