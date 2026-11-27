import test from "node:test";
import assert from "node:assert/strict";
import {loadTiqTestReturn,testReturnPreviewEnabled} from "../src/lib/tiqTestPaymentReturn.mjs";

const search="?session_id=cs_test_SyntheticReturnFixture";
const json=(status,body)=>new Response(JSON.stringify(body),{status,headers:{"Content-Type":"application/json"}});

test("return view only activates at the exact protected staging hostname",()=>{
  assert.equal(testReturnPreviewEnabled("true","nija-trading-challenge-staging.vercel.app"),true);
  assert.equal(testReturnPreviewEnabled("true","game.nijaaitrading.com"),false);
  assert.equal(testReturnPreviewEnabled(undefined,"nija-trading-challenge-staging.vercel.app"),false);
});
test("only one valid TEST payment pointer is sent, same-origin with no redirect or cache",async()=>{
  let called=0;
  const request=async (url,options)=>{
    called++;
    assert.equal(url,"/sandbox/report/return"+search);
    assert.equal(options.credentials,"same-origin");
    assert.equal(options.cache,"no-store");
    assert.equal(options.redirect,"error");
    return json(200,{report:{tradingIQ:0,rounds:12,challenges:Array(6).fill({}),assessments:{}}});
  };
  for(const bad of ["",search+"&owner=other","?session_id=cs_live_secret",search+"&session_id=cs_test_ExtraPointer"])
    assert.deepEqual(await loadTiqTestReturn(bad,{request}),{state:"invalid"});
  assert.equal(called,0);
  assert.equal((await loadTiqTestReturn(search,{request})).state,"ready");
  assert.equal(called,1);
});
test("unverified, pending, malformed and revoked outcomes never display a report",async()=>{
  for(const [status,state] of [[401,"sign_in"],[403,"unavailable"],[404,"unavailable"],[409,"pending"],[503,"retry"]])
    assert.deepEqual(await loadTiqTestReturn(search,{request:async()=>json(status,{report:{tradingIQ:20}})}),{state});
  assert.deepEqual(await loadTiqTestReturn(search,{request:async()=>json(200,{report:{tradingIQ:20}})}),{state:"retry"});
});
