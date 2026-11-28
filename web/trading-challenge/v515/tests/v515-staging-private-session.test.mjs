import assert from "node:assert/strict";
import {createHash} from "node:crypto";
import test from "node:test";
import {createTiq72StagingSignIn} from "../server/v515-staging-nija-signin.mjs";
import {createTiq72PrivateSessionReader,TIQ72_TEST_SESSION_COOKIE} from "../server/v515-staging-private-session.mjs";

const raw=Buffer.alloc(32,21).toString("base64url");
const digest=createHash("sha256").update(raw,"ascii").digest("hex");
const clock=1_796_000_000_000;
const row=Object.freeze({active:true,revokedAt:null,tokenDigest:digest,subject:"tiq-stage-fixture",
  csrfToken:"f".repeat(43),accessToken:"fragment.issuer.synthetic-not-a-real-jwt",
  issuedAt:clock-1000,expiresAt:clock+15000});
const cookie=name=>({headers:{cookie:name}});

test("uses only exact opaque cookie and looks up its digest, never the raw token",async()=>{
  const calls=[];
  const read=createTiq72PrivateSessionReader({enabled:true,now:()=>clock,lookupByDigest:async (key)=>{
    calls.push(key);return row;
  }});
  const result=await read(cookie("preferences=small; "+TIQ72_TEST_SESSION_COOKIE+"="+raw+"; theme=dark"));
  assert.deepEqual(calls,[digest]);
  assert.deepEqual(result,{active:true,subject:row.subject,csrfToken:row.csrfToken,accessToken:row.accessToken});
});

test("does not accept bearer/query/body credentials, ambiguous headers, or noncanonical cookies",async()=>{
  const read=createTiq72PrivateSessionReader({enabled:true,now:()=>clock,
    lookupByDigest:()=>assert.fail("untrusted credential reached private lookup")});
  assert.equal(await read({url:"/sandbox?session="+raw,
    body:{token:raw},headers:{authorization:"Bearer "+raw}}),null);
  for(const candidate of [
    "other="+raw, TIQ72_TEST_SESSION_COOKIE+"= "+raw,
    TIQ72_TEST_SESSION_COOKIE+"%3D"+raw,
    TIQ72_TEST_SESSION_COOKIE+"="+raw+"; "+TIQ72_TEST_SESSION_COOKIE+"="+raw,
    TIQ72_TEST_SESSION_COOKIE+" ="+raw,
    TIQ72_TEST_SESSION_COOKIE+"="+raw+"; padding="+"a".repeat(4100),
    TIQ72_TEST_SESSION_COOKIE+"="+raw.slice(0,-1)+"B",
  ]){
    assert.equal(await read(cookie(candidate)),null,candidate.slice(0,60));
  }
  assert.equal(await read(cookie([TIQ72_TEST_SESSION_COOKIE+"="+raw])),null);
});

test("rechecks active expiry, lookup binding, and synthetic subject per request",async()=>{
  let current=row;
  const request=cookie(TIQ72_TEST_SESSION_COOKIE+"="+raw);
  const read=createTiq72PrivateSessionReader({enabled:true,now:()=>clock,lookupByDigest:()=>current});
  assert.ok(await read(request));
  for(const bad of [
    null,{...row,revokedAt:clock},{...row,active:false},{...row,expiresAt:clock},
    {...row,issuedAt:clock+1},{...row,expiresAt:clock+900_000},
    {...row,tokenDigest:"0".repeat(64)},{...row,subject:"unrelated-user"},
    {...row,csrfToken:[]},{...row,accessToken:"z".repeat(4090)},
  ]) {
    current=bad;
    assert.equal(await read(request),null);
  }
});

test("default-off never queries and explicit unavailable storage does not authorize",async()=>{
  const lookup=()=>{throw new Error("private store unavailable");};
  const request=cookie(TIQ72_TEST_SESSION_COOKIE+"="+raw);
  assert.equal(await createTiq72PrivateSessionReader({lookupByDigest:lookup})(request),null);
  await assert.rejects(createTiq72PrivateSessionReader({enabled:true,lookupByDigest:lookup})(request));
});


test("protected browser return uses the real session seam; revoked sessions never reach report lookup",async()=>{
  let state=row,reads=0,profileCalls=0;
  const reviewerId="tiq-stage-reviewer";
  const preview=createTiq72StagingSignIn({
    enabled:true,reviewerId,
    readPrivateSession:createTiq72PrivateSessionReader({
      enabled:true,now:()=>clock,lookupByDigest:async key=>key===digest?state:null
    }),
    lookupActiveProfile:async value=>{
      assert.equal(value,row.accessToken);
      profileCalls++;
      return {ownerId:row.subject,active:true};
    },
    takeRateLimit:async()=>true,
    reviewStore:{getLatest:async id=>({buyerId:id,reviewerId,decision:"approve",
      decidedAt:Date.now()-1000,expiresAt:Date.now()+15000}),record:async()=>assert.fail("read must not write approval")},
    checkoutStore:{findOwnedTestReturn:async (ownerId)=>{
      assert.equal(ownerId,row.subject);
      reads++;
      return {runId:"fixture-run",state:"checkout_created"};
    }},
    stripe:{},webhookSecret:["whsec","SyntheticFixture0123456789"].join("_")
  });
  const invoke=async ()=>{
    const req={headers:{cookie:TIQ72_TEST_SESSION_COOKIE+"="+raw},method:"GET",
      url:"/sandbox/report/return?session_id=cs_test_SyntheticReturnFixture"};
    const res={writeHead(status,headers){this.status=status;this.headers=headers;this.headersSent=true;},
      end(body){this.body=JSON.parse(body);}};
    await preview(req,res);
    assert.equal(res.headers["Cache-Control"],"private, no-store");
    assert.equal(JSON.stringify(res.body).includes(row.accessToken),false);
    return res;
  };
  assert.equal((await invoke()).status,409);
  assert.equal(reads,1);
  state={...row,revokedAt:clock};
  assert.equal((await invoke()).status,401);
  assert.equal(reads,1);
  assert.equal(profileCalls,1);
});
