// NON-ROUTED isolated TEST commerce HTTP adapter for the approved v515 game.
// Requires the host to install an independently reviewed signed-session
// authenticator, a rate-limiter, a dedicated TEST Stripe client and isolated
// durable PostgreSQL store. No deployment or public Vercel endpoint here.
import {timingSafeEqual} from "node:crypto";
import {startVerifiedTestCheckout} from "./v515-test-checkout.mjs";
import {processSignedTestWebhook} from "./v515-signed-test-webhook.mjs";
import {recoverFreshPaidReport,PaidReportDenied,resolveTestOffer} from "./verified-report-service.mjs";

function send(res,status,data){
  res.statusCode=status;
  res.setHeader("Content-Type","application/json; charset=utf-8");
  res.setHeader("Cache-Control","no-store");
  res.setHeader("X-Content-Type-Options","nosniff");
  res.setHeader("Referrer-Policy","no-referrer");
  res.end(JSON.stringify(data));
}
async function readRaw(req) {
  if(req.body!==undefined) throw new PaidReportDenied("preparsed_body_forbidden");
  let size=0;const chunks=[];
  for await(const chunk of req) {
    size+=chunk.length;
    if(size>65536)throw new PaidReportDenied("request_too_large");
    chunks.push(Buffer.from(chunk));
  }
  if(size===0)throw new PaidReportDenied("empty_body");
  return Buffer.concat(chunks);
}
function fixedToken(a,b) {
  if(typeof a!=="string"||typeof b!=="string"||
     a.length<16||a.length>256||b.length<16||b.length>256)return false;
  const x=Buffer.from(a),y=Buffer.from(b);
  return x.length===y.length&&timingSafeEqual(x,y);
}
function plainObject(x){
  return x!==null&&typeof x==="object"&&!Array.isArray(x) &&
    Object.getPrototypeOf(x)===Object.prototype;
}
function responseError(res,error){
  // No secrets, Stripe details, owner identifiers or session cookies in HTTP.
  if(error instanceof PaidReportDenied) {
    const invalid=["preparsed_body_forbidden","request_too_large",
      "empty_body","invalid_body","invalid_checkout_request"];
    return send(res,invalid.includes(error.message)?400:403,{error:"request_not_authorized"});
  }
  return send(res,503,{error:"sandbox_service_unavailable"});
}
export function createV515SandboxHttpAdapter({
  authenticate,rateLimit,store,stripe,webhookSecret,trustedOrigin,testOffer
}){
  if(typeof authenticate!=="function"||typeof rateLimit!=="function"||
     !store||!stripe||typeof webhookSecret!=="string"||
     !trustedOrigin||typeof trustedOrigin!=="string")
    throw new TypeError("isolated_sandbox_dependencies_required");
  // The offer is supplied only by the trusted server factory, not HTTP input.
  const selectedOffer=resolveTestOffer(testOffer);
  return async function handle(req,res){
    try{
      // No permissive CORS, URL-supplied session secrets or session IDs.
      const pathname=new URL(req.url,"https://internal.invalid").pathname;
      const method=req.method;
      if(pathname==="/sandbox/stripe/webhook" && method==="POST"){
        if(!(await rateLimit(req,"stripe_webhook")))return send(res,429,{error:"rate_limited"});
        const rawBody=await readRaw(req);
        const sig=req.headers?.["stripe-signature"];
        const result=await processSignedTestWebhook({
          rawBody,signature:sig,webhookSecret,stripe,store,testOffer:selectedOffer});
        return send(res,200,{ok:true,processed:result.processed===true,
          duplicate:result.duplicate===true});
      }
      if(!["/sandbox/report","/sandbox/checkout"].includes(pathname))
        return send(res,404,{error:"not_found"});
      if((pathname==="/sandbox/checkout"&&method!=="POST")||
         (pathname==="/sandbox/report"&&method!=="GET"))
        return send(res,405,{error:"method_not_allowed"});
      if(!(await rateLimit(req,"authenticated_commerce")))
        return send(res,429,{error:"rate_limited"});
      // Host must verify server-side, signed session and age eligibility,
      // never trust a body-provided ownerId or a Stripe checkout URL.
      const identity=await authenticate(req);
      if(!identity||typeof identity.ownerId!=="string"||
         identity.ownerId.length<1||identity.ownerId.length>160)
        return send(res,401,{error:"authentication_required"});
      if(pathname==="/sandbox/report"){
        const query=new URL(req.url,"https://internal.invalid").searchParams;
        const ids=query.getAll("run_id");
        if(ids.length!==1||!ids[0]||ids[0].length>160||query.size!==1)
          return send(res,400,{error:"invalid_report_request"});
        const report=await recoverFreshPaidReport({
          ownerId:identity.ownerId,runId:ids[0],store,stripe,testOffer:selectedOffer});
        return send(res,200,{report});
      }
      if(req.headers?.origin!==trustedOrigin||
         !fixedToken(req.headers?.["x-csrf-token"],identity.csrfToken))
        return send(res,403,{error:"request_not_authorized"});
      const raw=await readRaw(req);
      let body;
      try{body=JSON.parse(raw.toString("utf8"))}catch{
        throw new PaidReportDenied("invalid_body");
      }
      if(!plainObject(body)||
         Object.keys(body).some(x=>!["attemptKey","adultAttested","canonicalRun"].includes(x))||
         Object.keys(body).length!==3)
        throw new PaidReportDenied("invalid_checkout_request");
      const result=await startVerifiedTestCheckout({
        ownerId:identity.ownerId,adultAttested:body.adultAttested,
        attemptKey:body.attemptKey,canonicalRun:body.canonicalRun,
        trustedOrigin,store,stripe,testOffer:selectedOffer});
      return send(res,200,{checkoutUrl:result.checkoutUrl,runId:result.runId});
    }catch(e){return responseError(res,e);}
  };
}
