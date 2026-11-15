import test from "node:test";
import assert from "node:assert/strict";
import {verifyAndBuildPaidReport,PaidReportDenied,TEST_PRICE,TEST_PRODUCT} from "../server/verified-report-service.mjs";
const ownerId="test-owner",runId="test-run",reservationId="test-reservation",sessionId="cs_test_fixture";
const canonicalRun={mode:"standard",level:"beginner",dayNum:0,challenges:Array.from({length:6},()=>Array.from({length:12},()=>({action:"hold",stop:false})))};
function fixture(){
  const session={id:sessionId,livemode:false,mode:"payment",status:"complete",payment_status:"paid",client_reference_id:reservationId,metadata:{tiq72_reservation_id:reservationId},amount_subtotal:100,amount_total:100,currency:"usd",payment_intent:"pi_test_fixture"};
  const lines={data:[{quantity:1,price:{id:TEST_PRICE,product:TEST_PRODUCT,unit_amount:100,currency:"usd"}}],has_more:false};
  const intent={id:"pi_test_fixture",livemode:false,status:"succeeded",amount_received:100,currency:"usd",latest_charge:"ch_test_fixture"};
  const charge={id:"ch_test_fixture",livemode:false,status:"succeeded",paid:true,amount:100,currency:"usd",payment_intent:intent.id,refunded:false,disputed:false,amount_refunded:0};
  let writes=0;
  const store={getOwnedPurchase:async()=>({ownerId,runId,reservationId,sessionId,canonicalRun,state:"paid"}),storeVerifiedReport:async()=>{writes++;}};
  const stripe={checkout:{Session:{retrieve:async()=>session,listLineItems:async()=>lines}},PaymentIntent:{retrieve:async()=>intent},Charge:{retrieve:async()=>charge}};
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
