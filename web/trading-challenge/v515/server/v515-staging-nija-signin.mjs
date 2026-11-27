// TEST composition only. No listener, login endpoint, cookie minting or live mode.
// Open a browser session only through the separately authenticated NIJA staging
// sign-in; this adapter never trusts browser-supplied ownership or age.
import {timingSafeEqual} from "node:crypto";
import {createManualAdultReview} from "./v515-manual-adult-review.mjs";
import {createTiq72CustomerTestBridge} from "./v515-customer-test-bridge.mjs";

const ORIGIN="https://nija-trading-challenge-staging.vercel.app";
const ID=/^[A-Za-z0-9_.-]{1,160}$/;
const CSRF=/^[A-Za-z0-9_-]{32,96}$/;
const BEARER=/^[A-Za-z0-9_-]{4,4096}\.[A-Za-z0-9_-]{4,4096}\.[A-Za-z0-9_-]{16,1024}$/;
const status=(res,code,body)=>{
  res.writeHead(code,{"Content-Type":"application/json; charset=utf-8","Cache-Control":"private, no-store",
    "X-Content-Type-Options":"nosniff","Referrer-Policy":"no-referrer"});
  res.end(JSON.stringify(body));
};
function equalCsrf(a,b){
  if(typeof a!=="string"||typeof b!=="string"||!CSRF.test(a)||!CSRF.test(b)||a.length!==b.length) return false;
  return timingSafeEqual(Buffer.from(a),Buffer.from(b));
}

// This origin is injected at deploy time only after verifying the actual
// isolated gateway and account store; never derive it from request metadata.
export function createNijaStagingProfileLookup({issuerOrigin,bridgeProof,request=fetch}={}){
  if(typeof issuerOrigin!=="string"||typeof bridgeProof!=="string"||
     !/^[A-Za-z0-9_-]{43,128}$/.test(bridgeProof)||typeof request!=="function")
    throw new TypeError("staging_identity_origin_required");
  const issuer=new URL(issuerOrigin);
  if(issuer.href!==issuerOrigin+"/"||issuer.protocol!=="https:"||issuer.port||
     !/^[a-z0-9]+(?:-[a-z0-9]+)*-(?:staging|test|sandbox)\.onrender\.com$/.test(issuer.hostname))
    throw new TypeError("staging_identity_origin_required");
  const endpoint=new URL("/api/user/profile",issuer);
  return async accessToken=>{
    if(typeof accessToken!=="string"||!BEARER.test(accessToken)) return null;
    const result=await request(endpoint,{
      method:"GET",headers:{Authorization:"Bearer "+accessToken,Accept:"application/json",
        "X-NIJA-Staging-Bridge":bridgeProof},
      redirect:"error",cache:"no-store",signal:AbortSignal.timeout(3500)
    });
    if(result.status>=400&&result.status<500) return null;
    if(result.status!==200||!result.headers.get("content-type")?.startsWith("application/json"))
      throw new Error("staging_identity_unavailable");
    const profile=await result.json();
    if(profile?.enabled!==true||typeof profile.user_id!=="string"||!ID.test(profile.user_id)) return null;
    return {ownerId:profile.user_id,active:true};
  };
}

export function createTiq72StagingSignIn({
  enabled=false,reviewerId,readPrivateSession,lookupActiveProfile,takeRateLimit,
  reviewStore,checkoutStore,stripe,webhookSecret
}={}){
  if(enabled!==true) return (_req,res)=>status(res,503,{error:"staging_sign_in_unavailable"});
  if(typeof readPrivateSession!=="function"||typeof lookupActiveProfile!=="function"||
     typeof takeRateLimit!=="function"||typeof reviewerId!=="string"||!ID.test(reviewerId))
    throw new TypeError("private_staging_identity_required");
  const verifySession=async req=>{
    // Host must supply a server-side lookup behind a Secure, HttpOnly,
    // same-origin session cookie. No bearer token from URL/body/JS storage.
    const session=await readPrivateSession(req);
    if(session?.active!==true||typeof session.subject!=="string"||!ID.test(session.subject)||
       typeof session.accessToken!=="string"||!BEARER.test(session.accessToken)||
       typeof session.csrfToken!=="string"||!CSRF.test(session.csrfToken)) return null;
    const profile=await lookupActiveProfile(session.accessToken);
    if(profile?.active!==true||profile.ownerId!==session.subject) return null;
    return {ownerId:profile.ownerId,csrfToken:session.csrfToken,active:true};
  };
  const review=createManualAdultReview({
    reviewedTestOnly:true,reviewerId,verifyCustomerSession:verifySession,
    verifyReviewerMutation:async req=>{
      const active=await verifySession(req);
      if(active?.ownerId!==reviewerId||!equalCsrf(req.headers?.["x-csrf-token"],active.csrfToken)) return null;
      return {...active,csrfVerified:true,isOwner:true};
    },
    store:reviewStore
  });
  const commerce=createTiq72CustomerTestBridge({enabled:true,previewOrigin:ORIGIN,
    verifyBuyer:review.verifyBuyer,takeRateLimit,store:checkoutStore,stripe,webhookSecret});
  return async (req,res)=>{
    if(req.url!=="/sandbox/owner/adult-review") return commerce(req,res);
    try{
      if(req.method!=="POST") return status(res,405,{error:"method_not_allowed"});
      if(req.headers?.origin!==ORIGIN||req.headers?.["sec-fetch-site"]==="cross-site") return status(res,403,{error:"request_not_authorized"});
      if(!await takeRateLimit(req,"owner_review"))return status(res,429,{error:"rate_limited"});
      if(req.body!==undefined||req.headers?.["content-type"]!=="application/json")
        return status(res,400,{error:"invalid_review"});
      const chunks=[];let size=0;
      for await(const part of req){
        const b=Buffer.from(part);size+=b.length;
        if(size>1024) return status(res,400,{error:"invalid_review"});
        chunks.push(b);
      }
      let input;try{input=JSON.parse(Buffer.concat(chunks).toString("utf8"));}catch{
        return status(res,400,{error:"invalid_review"});
      }
      const result=await review.recordDecision(req,input);
      return status(res,result.ok?200:result.reason==="reviewer_required"?403:400,result);
    }catch{
      return status(res,503,{error:"staging_sign_in_unavailable"});
    }
  };
}
