import test from "node:test";
import assert from "node:assert/strict";
import {Readable} from "node:stream";
import {createTiq72StagingSignIn,createNijaStagingProfileLookup} from "../server/v515-staging-nija-signin.mjs";

const origin="https://nija-trading-challenge-staging.vercel.app";
const issuer="https://nija-auth-staging.onrender.com";
const testBearer=["stub","body","signaturefixture"].join(".");
const csrf="f".repeat(43);
const csrfHeader=["x","csrf","token"].join("-");
const owner="test-owner", buyer="test-buyer";
const webhookSecret=["whsec","SyntheticFixture0123456789"].join("_");
const returnPath="/sandbox/report/return?session_id=cs_test_SyntheticReturnFixture";

async function invoke(engine,{url="/sandbox/owner/adult-review",method="POST",headers={},input}={}){
  const req=Object.assign(Readable.from(input?[Buffer.from(JSON.stringify(input))]:[]),{url,method,headers});
  const res={writeHead(status,h){this.status=status;this.headers=h;this.headersSent=true;},
    end(s){this.body=JSON.parse(s);}};
  await engine(req,res);
  return res;
}
const accept=(who)=>({active:true,subject:who,accessToken:testBearer,csrfToken:csrf});
const mutation={headers:{origin,"content-type":"application/json",[csrfHeader]:csrf},input:{buyerId:buyer,decision:"approve"}};
function fixture(){
  let who=owner,subject=owner;
  const decisions=[];
  const engine=createTiq72StagingSignIn({enabled:true,reviewerId:owner,
    readPrivateSession:async()=>accept(who),
    lookupActiveProfile:async()=>({active:true,ownerId:subject}),
    takeRateLimit:async()=>true,
    reviewStore:{getLatest:async id=>decisions.findLast(x=>x.buyerId===id),record:async row=>decisions.push(row)},
    checkoutStore:{findOwnedTestReturn:async()=>({runId:"test-run",state:"checkout_created"})},
    stripe:{},webhookSecret});
  return {engine,decisions,as:(w,s=w)=>{who=w;subject=s;}};
}

test("only the server-pinned private TEST issuer is accepted",async()=>{
  for(const issuerOrigin of ["https://nija.onrender.com","https://localhost","https://other.example/path",
      issuer+"/path",issuer+"/","http://nija-auth-staging.onrender.com",issuer+":444"])
    assert.throws(()=>createNijaStagingProfileLookup({issuerOrigin}),/staging_identity_origin_required/);
  const lookup=createNijaStagingProfileLookup({issuerOrigin:issuer,request:async(url,options)=>{
    assert.equal(String(url),issuer+"/api/user/profile");
    assert.equal(options.redirect,"error");
    assert.equal(options.headers.Authorization,"Bearer "+testBearer);
    return Response.json({enabled:true,user_id:buyer,email:"ignored@example.com",permissions:{owner:true}});
  }});
  assert.deepEqual(await lookup(testBearer),{ownerId:buyer,active:true});
  assert.equal(await lookup("invalid"),null);
});
test("disabled, expired and unavailable profiles never authorize a buyer",async()=>{
  for(const [status,data] of [[200,{enabled:false,user_id:buyer}],[401,{error:"expired"}]]){
    const lookup=createNijaStagingProfileLookup({issuerOrigin:issuer,request:async()=>Response.json(data,{status})});
    assert.equal(await lookup(testBearer),null);
  }
  const failed=createNijaStagingProfileLookup({issuerOrigin:issuer,request:async()=>new Response(null,{status:503})});
  await assert.rejects(()=>failed(testBearer),/staging_identity_unavailable/);
});
test("review action is off by default and rejects origin, missing CSRF and profile mismatch",async()=>{
  assert.equal((await invoke(createTiq72StagingSignIn(),mutation)).status,503);
  const f=fixture();
  assert.equal((await invoke(f.engine,{...mutation,headers:{...mutation.headers,origin:"https://example.com"}})).status,403);
  assert.equal((await invoke(f.engine,{...mutation,headers:{...mutation.headers,[csrfHeader]:"z".repeat(43)}})).status,403);
  f.as(owner,buyer);
  assert.equal((await invoke(f.engine,mutation)).status,403);
  f.as(buyer);
  assert.equal((await invoke(f.engine,mutation)).status,403);
  assert.equal(f.decisions.length,0);
});
test("owner approval alone authorizes the signed-in matching buyer; review revocation closes access",async()=>{
  const f=fixture();
  f.as(buyer);
  assert.equal((await invoke(f.engine,{url:returnPath,method:"GET"})).status,401);
  f.as(owner);
  assert.equal((await invoke(f.engine,mutation)).status,200);
  f.as(buyer);
  assert.equal((await invoke(f.engine,{url:returnPath,method:"GET"})).status,409);
  f.as(owner);
  assert.equal((await invoke(f.engine,{...mutation,input:{buyerId:buyer,decision:"revoke"}})).status,200);
  f.as(buyer);
  assert.equal((await invoke(f.engine,{url:returnPath,method:"GET"})).status,401);
});
