import assert from "node:assert/strict";
import test from "node:test";
import {createPgPreviewRateLimiter,TAKE_PREVIEW_RATE_LIMIT} from "../server/v515-pg-preview-rate-limit.mjs";
import {createTiq72StagingSignIn} from "../server/v515-staging-nija-signin.mjs";

test("requires the exact opt-in; unsupported lanes do not reach storage",async()=>{
  const disabled=createPgPreviewRateLimiter({pool:{query:()=>assert.fail("disabled query")}});
  assert.equal(await disabled({},"owner_review"),false);
  assert.throws(()=>createPgPreviewRateLimiter({reviewedTestOnly:true}),/exact_private_pg_pool_required/);
  const enabled=createPgPreviewRateLimiter({reviewedTestOnly:true,
    pool:{query:()=>assert.fail("unsupported lane query")}});
  for(const lane of ["__proto__","constructor","stripe_webhook","authenticated_commerce ",{},undefined]){
    assert.equal(await enabled({},lane),false);
  }
});

test("each request uses one atomic query with fixed lane policy and database/role identity",async()=>{
  const calls=[];
  const limiter=createPgPreviewRateLimiter({reviewedTestOnly:true,pool:{query:async(sql,args)=>{
    calls.push([sql,args]);return {rowCount:1,rows:[{allowed:1}]};
  }}});
  const request={headers:{cookie:"must-not-store","x-forwarded-for":"untrusted"}};
  assert.equal(await limiter(request,"authenticated_commerce"),true);
  assert.equal(await limiter(request,"owner_review"),true);
  assert.deepEqual(calls,[
    [TAKE_PREVIEW_RATE_LIMIT,["authenticated_commerce",30,"nija_tiq72_upgrade6_isolated_test","nija_tiq72_upgrade6_isolated_test_user"]],
    [TAKE_PREVIEW_RATE_LIMIT,["owner_review",8,"nija_tiq72_upgrade6_isolated_test","nija_tiq72_upgrade6_isolated_test_user"]]
  ]);
  assert.match(TAKE_PREVIEW_RATE_LIMIT,/ON CONFLICT \(lane\) DO UPDATE/);
  assert.match(TAKE_PREVIEW_RATE_LIMIT,/statement_timestamp\(\)/);
});

test("cap, identity mismatch, malformed result, and storage failure all deny",async()=>{
  for(const response of [
    {rowCount:0,rows:[]},{rowCount:1,rows:[]},{rowCount:1,rows:[{allowed:"1"}]},
    {rowCount:1,rows:[{allowed:1},{allowed:1}]},null
  ])assert.equal(await createPgPreviewRateLimiter({reviewedTestOnly:true,
    pool:{query:async()=>response}})({},"authenticated_commerce"),false);
  assert.equal(await createPgPreviewRateLimiter({reviewedTestOnly:true,
    pool:{query:async()=>{throw new Error("private DB unavailable");}}})({},"owner_review"),false);
});

test("the actual TEST sign-in bridge refuses bootstrap at database limit before identity or report lookup",async()=>{
  let reads=0;
  const handler=createTiq72StagingSignIn({
    enabled:true,reviewerId:"tiq-stage-reviewer",
    readPrivateSession:()=>assert.fail("limiter must run before private session"),
    lookupActiveProfile:()=>assert.fail("limiter must run before issuer"),
    takeRateLimit:createPgPreviewRateLimiter({reviewedTestOnly:true,
      pool:{query:async()=>{reads++;return {rowCount:0,rows:[]};}}}),
    reviewStore:{getLatest:()=>assert.fail("limiter must run before eligibility"),record:()=>{}},
    checkoutStore:{findOwnedTestReturn:()=>assert.fail("limiter must run before storage")},
    stripe:{},webhookSecret:["whsec","SyntheticFixture0123456789"].join("_")
  });
  const req={method:"GET",url:"/sandbox/checkout/session",
    headers:{accept:"application/json","sec-fetch-site":"same-origin"}};
  const res={writeHead(status){this.status=status;},end(data){this.body=JSON.parse(data);}};
  await handler(req,res);
  assert.equal(reads,1);
  assert.equal(res.status,429);
  assert.deepEqual(res.body,{error:"rate_limited"});
});
