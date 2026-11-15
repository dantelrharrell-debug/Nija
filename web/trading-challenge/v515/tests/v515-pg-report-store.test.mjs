import test from "node:test";
import assert from "node:assert/strict";
import {V515PgReportStore} from "../server/v515-pg-report-store.mjs";
import {PaidReportDenied} from "../server/verified-report-service.mjs";
function fixture({state="paid",stripeSession="cs_test_example",owner="test-owner",existing=null}={}){
 const calls=[];let released=0;
 const purchase={reservation_id:"reservation-test",state,stripe_session:stripeSession};
 const client={query:async(sql,params)=>{
  calls.push({sql,params});
  if(sql.includes("FOR UPDATE OF p"))return {rows:owner==="test-owner"?[purchase]:[]};
  if(sql.includes("INSERT INTO tiq72_v515_reports"))return {rowCount:existing===null?1:0,rows:[]};
  if(sql.includes("SELECT stripe_session, owner_id, reservation_id"))return {rows:existing?[existing]:[]};
  return {rows:[]};
 },release:()=>released++};
 const pool={query:async(sql,params)=>({rows:owner==="test-owner"?[{
  owner_id:"test-owner",run_id:"test-run",canonical_run:{mode:"standard"},
  reservation_id:"reservation-test",stripe_session:stripeSession,state
 }]:[]}),connect:async()=>client};
 const store=new V515PgReportStore(pool);
 const write=()=>store.storeVerifiedReport({ownerId:"test-owner",runId:"test-run",sessionId:"cs_test_example",report:{iq:93}});
 return {store,calls,write,get released(){return released}};
}
test("owner scoped read never broadens query",async()=>{
 const f=fixture();assert.equal((await f.store.getOwnedPurchase("test-owner","test-run")).reservationId,"reservation-test");
 assert.equal(await f.store.getOwnedPurchase("","test-run"),null);
});
test("single verified report commits with row lock",async()=>{
 const f=fixture();assert.deepEqual(await f.write(),{stored:true});
 assert.ok(f.calls.some(x=>x.sql.includes("FOR UPDATE OF p")));
 assert.ok(f.calls.some(x=>x.sql==="COMMIT"));
 assert.equal(f.released,1);
});
test("replay is idempotent and cannot mutate immutable report",async()=>{
 const f=fixture({existing:{owner_id:"test-owner",stripe_session:"cs_test_example",reservation_id:"reservation-test"}});
 assert.deepEqual(await f.write(),{stored:false});
 assert.ok(f.calls.some(x=>x.sql.includes("ON CONFLICT (run_id) DO NOTHING")));
});
test("revoked paid grant fails closed",async()=>{
 const f=fixture({state:"refunded"});await assert.rejects(f.write(),e=>e instanceof PaidReportDenied&&e.message==="purchase_revoked_or_changed");
 assert.ok(f.calls.some(x=>x.sql==="ROLLBACK"));assert.equal(f.released,1);
});
test("wrong purchase session fails closed",async()=>{
 const f=fixture({stripeSession:"cs_test_someone_else"});await assert.rejects(f.write(),/purchase_revoked_or_changed/);
 assert.equal(f.released,1);
});
test("conflicting immutable report refuses replacement",async()=>{
 const f=fixture({existing:{owner_id:"other",stripe_session:"cs_test_wrong",reservation_id:"other"}});
 await assert.rejects(f.write(),/conflicting_paid_report/);
 assert.ok(f.calls.some(x=>x.sql==="ROLLBACK"));
});
test("inappropriate session rejected before DB connect",async()=>{
 const f=fixture();await assert.rejects(f.store.storeVerifiedReport({ownerId:"test-owner",runId:"test-run",sessionId:"cs_live_wrong",report:{iq:93}}),/invalid_report_transaction/);
 assert.equal(f.calls.length,0);
});
