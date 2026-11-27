import test from "node:test";
import assert from "node:assert/strict";
import {createManualAdultReview,createPgManualAdultReviewStore} from "../server/v515-manual-adult-review.mjs";

const reviewerId="operator-fixture";
const buyerId="buyer-fixture";
const approval={buyerId,decision:"approve"};
const buyer={active:true,ownerId:buyerId,csrfToken:"a".repeat(43)};
const operator={active:true,ownerId:reviewerId,isOwner:true,csrfVerified:true};

function fixture(){
  const records=[];
  let time=1000;
  const options={reviewedTestOnly:true,reviewerId,ttlMs:500,now:()=>time,
    verifyCustomerSession:async()=>buyer,verifyReviewerMutation:async()=>operator,
    store:{record:async r=>records.push(r),getLatest:async id=>records.findLast(r=>r.buyerId===id)}};
  return {records,options,advance:ms=>{time+=ms;}};
}
test("manual authority is explicitly TEST-only and requires private dependencies",()=>{
  const f=fixture();
  assert.throws(()=>createManualAdultReview({...f.options,reviewedTestOnly:false}),/isolated_manual_reviewer_required/);
  assert.throws(()=>createManualAdultReview({...f.options,verifyReviewerMutation:undefined}),/isolated_manual_reviewer_required/);
});
test("customer/browser attributes cannot replace the owner's recorded decision",async()=>{
  const f=fixture();
  const service=createManualAdultReview(f.options);
  assert.equal(await service.verifyBuyer({body:{adultVerified:true,ownerId:buyerId}}),null);
  for(const actor of [{...operator,ownerId:"other-operator"},{...operator,isOwner:false},
    {...operator,active:false},{...operator,csrfVerified:false},null]){
    const blocked=createManualAdultReview({...f.options,verifyReviewerMutation:async()=>actor});
    assert.equal((await blocked.recordDecision({},approval)).ok,false);
  }
  assert.equal(f.records.length,0);
});
test("operator approval is per-account, refuses own account and does not take identity material",async()=>{
  const f=fixture(), service=createManualAdultReview(f.options);
  for(const input of [{buyerId:reviewerId,decision:"approve"},
    {...approval,birthDate:"2000-01-01"},{...approval,decision:"allow_everyone"},
    {...approval,buyerId:"name@example.com"},{...approval,buyerId:4}]){
    assert.equal((await service.recordDecision({},input)).ok,false);
  }
  assert.deepEqual(await service.recordDecision({},approval),{ok:true});
  assert.deepEqual(Object.keys(f.records[0]).sort(),["buyerId","decidedAt","decision","expiresAt","reviewerId"]);
  assert.equal((await service.verifyBuyer({})).adultVerified,true);
  for(const session of [{...buyer,ownerId:"other-buyer"},{...buyer,active:false},null]){
    const other=createManualAdultReview({...f.options,verifyCustomerSession:async()=>session});
    assert.equal(await other.verifyBuyer({}),null);
  }
});
test("revocation, expiration, future timestamps and wrong reviewer fail closed",async()=>{
  const f=fixture(), service=createManualAdultReview(f.options);
  await service.recordDecision({},approval);
  await service.recordDecision({},{buyerId,decision:"revoke"});
  assert.equal(await service.verifyBuyer({}),null);
  await service.recordDecision({},approval);
  f.advance(500);
  assert.equal(await service.verifyBuyer({}),null);
  const getLatest=async()=>({buyerId,reviewerId:"not-owner",decision:"approve",decidedAt:1500,expiresAt:1700});
  assert.equal(await createManualAdultReview({...f.options,store:{...f.options.store,getLatest}}).verifyBuyer({}),null);
  f.records.push({buyerId,reviewerId,decision:"approve",decidedAt:1501,expiresAt:1700});
  assert.equal(await service.verifyBuyer({}),null);
});
test("storage errors do not produce an approval and queries are owner scoped and parameterized",async()=>{
  const f=fixture(), calls=[];
  const pg=createPgManualAdultReviewStore({query:async(sql,params)=>{calls.push({sql,params});return {rows:[]};}});
  const service=createManualAdultReview({...f.options,store:pg});
  assert.deepEqual(await service.recordDecision({},approval),{ok:true});
  assert.equal(await service.verifyBuyer({}),null);
  assert.match(calls[0].sql,/^INSERT/);
  assert.deepEqual(calls[0].params,[buyerId,reviewerId,"approve",1000,1500]);
  assert.match(calls[1].sql,/WHERE buyer_id=\$1 ORDER BY review_id DESC LIMIT 1/);
  assert.deepEqual(calls[1].params,[buyerId]);
  const offline=createManualAdultReview({...f.options,store:{...pg,getLatest:async()=>{throw Error("offline");}}});
  await assert.rejects(()=>offline.verifyBuyer({}),/offline/);
});
