import test from "node:test";
import assert from "node:assert/strict";
import {verifyAndBuildPaidReport,recoverFreshPaidReport,PaidReportDenied,TEST_PRICE,TEST_PRODUCT,ISOLATED_TEST_PRICE,ISOLATED_TEST_PRODUCT} from "../server/verified-report-service.mjs";
const ownerId="test-owner",runId="test-run",reservationId="test-reservation",sessionId="cs_test_fixture";
const canonicalRun={mode:"standard",level:"beginner",dayNum:0,challenges:Array.from({length:6},()=>Array.from({length:12},()=>({action:"hold",stop:false})))};
function fixture(testOffer){
  const session={id:sessionId,livemode:false,mode:"payment",status:"complete",payment_status:"paid",client_reference_id:reservationId,metadata:{tiq72_reservation_id:reservationId},amount_subtotal:100,amount_total:100,currency:"usd",payment_intent:"pi_test_fixture"};
  const lines={data:[{quantity:1,price:{id:testOffer?.price??TEST_PRICE,product:testOffer?.product??TEST_PRODUCT,unit_amount:100,currency:"usd"}}],has_more:false};
  const intent={id:"pi_test_fixture",livemode:false,status:"succeeded",amount_received:100,currency:"usd",latest_charge:"ch_test_fixture"};
  const charge={id:"ch_test_fixture",livemode:false,status:"succeeded",paid:true,amount:100,currency:"usd",payment_intent:intent.id,refunded:false,disputed:false,amount_refunded:0};
  let writes=0;
  const store={getOwnedPurchase:async()=>({ownerId,runId,reservationId,sessionId,canonicalRun,state:"paid"}),storeVerifiedReport:async()=>{writes++;}};
  const stripe={checkout:{sessions:{retrieve:async()=>session,listLineItems:async()=>lines}},paymentIntents:{retrieve:async()=>intent},charges:{retrieve:async()=>charge}};
  return {session,lines,intent,charge,store,stripe,get writes(){return writes;}};
}
const call=(f,o={})=>verifyAndBuildPaidReport({ownerId,runId,store:f.store,stripe:f.stripe,...o});
const deny=async(f,code,o={})=>assert.rejects(call(f,o),e=>e instanceof PaidReportDenied&&e.message===code);
test("generates report only after verifying canonical test payment",async()=>{
  const f=fixture();const report=await call(f);assert.ok(report);assert.equal(f.writes,1);
});
test("other owner has no access",async()=>{const f=fixture();await deny(f,"owned_paid_run_required",{ownerId:"other"});assert.equal(f.writes,0);});
test("rejects browser score injection",async()=>{
  const f=fixture();f.store.getOwnedPurchase=async()=>({ownerId,runId,reservationId,sessionId,canonicalRun:{...canonicalRun,score:100},state:"paid"});
  await deny(f,"canonical_run_invalid");assert.equal(f.writes,0);
});
for(const [field,value] of [["livemode",true],["status","open"],["payment_status","unpaid"],["amount_total",99],["client_reference_id","wrong"]])
  test("rejects checkout "+field,async()=>{const f=fixture();f.session[field]=value;await deny(f,"checkout_not_verified");assert.equal(f.writes,0);});
test("rejects wrong product",async()=>{const f=fixture();f.lines.data[0].price.id="price_wrong";await deny(f,"test_product_mismatch");assert.equal(f.writes,0);});
test("rejects unpaid intent",async()=>{const f=fixture();f.intent.status="processing";await deny(f,"payment_not_verified");assert.equal(f.writes,0);});
for(const field of ["refunded","disputed"])test("rejects "+field,async()=>{const f=fixture();f.charge[field]=true;await deny(f,"charge_not_verified");assert.equal(f.writes,0);});
test("rejects partial refund",async()=>{const f=fixture();f.charge.amount_refunded=1;await deny(f,"charge_not_verified");assert.equal(f.writes,0);});

test("recovery first re-verifies provider then reads owner-only paid report",async()=>{
 const f=fixture();let reads=0;
 f.store.getOwnedPaidReport=async(owner,run)=>{reads++;assert.equal(owner,ownerId);
   assert.equal(run,runId);assert.equal(f.writes,1);return {iq:93};};
 const report=await recoverFreshPaidReport({ownerId,runId,store:f.store,stripe:f.stripe});
 assert.equal(report.iq,93);assert.equal(reads,1);
});
test("recovery never reads stored report after provider refund",async()=>{
 const f=fixture();f.charge.refunded=true;let reads=0;
 f.store.getOwnedPaidReport=async()=>{reads++;return {iq:93};};
 await assert.rejects(recoverFreshPaidReport({ownerId,runId,store:f.store,stripe:f.stripe}),/charge_not_verified/);
 assert.equal(reads,0);assert.equal(f.writes,0);
});
test("recovery rejects missing entitlement after fresh verification",async()=>{
 const f=fixture();f.store.getOwnedPaidReport=async()=>null;
 await assert.rejects(recoverFreshPaidReport({ownerId,runId,store:f.store,stripe:f.stripe}),/paid_report_not_available/);
});
test("recovery rejects unprotected store interface",async()=>{
 const f=fixture();
 await assert.rejects(recoverFreshPaidReport({ownerId,runId,store:f.store,stripe:f.stripe}),/protected_report_store_required/);
});

test("cross-account TEST receipts never generate or reopen a paid report",async()=>{
 const unverified={price:ISOLATED_TEST_PRICE,product:ISOLATED_TEST_PRODUCT};
 const f=fixture(unverified);
 await deny(f,"test_product_mismatch",{testOffer:unverified});
 assert.equal(f.writes,0);
 const old=fixture();
 await deny(old,"test_product_mismatch",{testOffer:unverified});
 assert.equal(old.writes,0);
 let reportReads=0;
 f.store.getOwnedPaidReport=async()=>{reportReads++;return {iq:93};};
 await assert.rejects(recoverFreshPaidReport({
   ownerId,runId,store:f.store,stripe:f.stripe,testOffer:unverified
 }),/test_product_mismatch/);
 assert.equal(reportReads,0);
 assert.equal(f.writes,0);
});
test("trusted canonical selection rejects cross-account Stripe receipt proof",async()=>{
 const f=fixture({price:ISOLATED_TEST_PRICE,product:ISOLATED_TEST_PRODUCT});
 await deny(f,"test_product_mismatch",{
   testOffer:{price:TEST_PRICE,product:TEST_PRODUCT}
 });
 assert.equal(f.writes,0);
});
test("verified NIJA TEST receipts still support owner-scoped report recovery",async()=>{
 const testOffer={price:TEST_PRICE,product:TEST_PRODUCT};
 const f=fixture(testOffer);
 f.store.getOwnedPaidReport=async()=>({iq:93});
 const report=await recoverFreshPaidReport({
   ownerId,runId,store:f.store,stripe:f.stripe,testOffer
 });
 assert.equal(report.iq,93);
 assert.equal(f.writes,1);
});
