// Review-only customer ingress for a protected Trading IQ TEST preview.
// Not mounted by the Render TEST host or Vercel. A trusted session adapter
// must supply an active, eligible NIJA account and its session-bound CSRF token.
import {createV515SandboxHttpAdapter} from "./v515-sandbox-http-adapter.mjs";
import {PaidReportDenied,recoverFreshPaidReport} from "./verified-report-service.mjs";
import {TEST_PRICE,TEST_PRODUCT} from "./tiq72-test-offer.mjs";

const PREVIEW_ORIGIN="https://nija-trading-challenge-staging.vercel.app";
const OFFER=Object.freeze({price:TEST_PRICE,product:TEST_PRODUCT});
const SESSION=/^cs_test_[A-Za-z0-9]{8,220}$/;
const OWNER=/^[A-Za-z0-9_.:@-]{1,160}$/;
const CSRF=/^[A-Za-z0-9_-]{32,96}$/;
const SEND=(res,status,body)=>{
  res.writeHead(status,{"Content-Type":"application/json; charset=utf-8",
    "Cache-Control":"private, no-store","Referrer-Policy":"no-referrer",
    "X-Content-Type-Options":"nosniff"});
  res.end(JSON.stringify(body));
};

export function createTiq72CustomerTestBridge({
  enabled=false,previewOrigin,verifyBuyer,takeRateLimit,store,stripe,webhookSecret
}={}){
  if(enabled!==true) return (_req,res)=>SEND(res,503,{error:"checkout_not_available"});
  if(previewOrigin!==PREVIEW_ORIGIN||
     typeof verifyBuyer!=="function"||typeof takeRateLimit!=="function"||
     typeof store?.findOwnedTestReturn!=="function"||!stripe||
     !/^whsec_[A-Za-z0-9]{16,}$/.test(webhookSecret??""))
    throw new TypeError("protected_test_preview_dependencies_required");
  const authenticate=async req=>{
    // The injection point is for verified server-side sessions, never for a
    // browser's submitted age, user ID, report ID, or payment session.
    const value=await verifyBuyer(req);
    if(value?.active!==true || value.adultVerified!==true ||
       typeof value.ownerId!=="string" || !OWNER.test(value.ownerId) ||
       typeof value.csrfToken!=="string" || !CSRF.test(value.csrfToken))
      return null;
    return {ownerId:value.ownerId,csrfToken:value.csrfToken};
  };
  const checkout=createV515SandboxHttpAdapter({
    authenticate,rateLimit:takeRateLimit,store,stripe,webhookSecret,
    trustedOrigin:previewOrigin,testOffer:OFFER
  });
  return async (req,res)=>{
    try{
      if(typeof req.url!=="string"||!req.url.startsWith("/")||req.url.startsWith("//"))
        return SEND(res,400,{error:"invalid_request"});
      const url=new URL(req.url,previewOrigin);
      if(url.origin!==previewOrigin || req.headers?.["sec-fetch-site"]==="cross-site" ||
         (req.headers?.origin && req.headers.origin!==previewOrigin))
        return SEND(res,403,{error:"request_not_authorized"});
      if(url.pathname==="/sandbox/checkout" && !url.search)
        return await checkout(req,res);
      if(url.pathname==="/sandbox/checkout/session"){
        if(req.method!=="GET") return SEND(res,405,{error:"method_not_allowed"});
        if(url.search) return SEND(res,400,{error:"invalid_checkout_session_request"});
        // Bootstrap only a browser-initiated same-origin JSON request. A
        // direct navigation or same-site sibling is not a token recipient.
        if(req.headers?.["sec-fetch-site"]!=="same-origin"||req.headers?.accept!=="application/json")
          return SEND(res,403,{error:"request_not_authorized"});
        if(!await takeRateLimit(req,"authenticated_commerce"))
          return SEND(res,429,{error:"rate_limited"});
        const buyer=await authenticate(req);
        if(!buyer) return SEND(res,401,{error:"eligible_sign_in_required"});
        return SEND(res,200,{csrfToken:buyer.csrfToken});
      }
      if(url.pathname!=="/sandbox/report/return")
        return SEND(res,404,{error:"not_found"});
      if(req.method!=="GET") return SEND(res,405,{error:"method_not_allowed"});
      if(!await takeRateLimit(req,"authenticated_commerce"))
        return SEND(res,429,{error:"rate_limited"});
      const buyer=await authenticate(req);
      if(!buyer) return SEND(res,401,{error:"eligible_sign_in_required"});
      const ids=url.searchParams.getAll("session_id");
      if(url.searchParams.size!==1||ids.length!==1||!SESSION.test(ids[0]))
        return SEND(res,400,{error:"invalid_report_return"});
      const owned=await store.findOwnedTestReturn(buyer.ownerId,ids[0]);
      if(!owned) return SEND(res,404,{error:"report_not_found"});
      if(owned.state==="reserved"||owned.state==="checkout_created")
        return SEND(res,409,{error:"payment_not_confirmed"});
      if(owned.state!=="paid"||typeof owned.runId!=="string")
        return SEND(res,403,{error:"paid_report_not_available"});
      const report=await recoverFreshPaidReport({
        ownerId:buyer.ownerId,runId:owned.runId,store,stripe,testOffer:OFFER
      });
      return SEND(res,200,{report});
    }catch(error){
      if(res.headersSent) return;
      if(error instanceof PaidReportDenied)
        return SEND(res,403,{error:"paid_report_not_available"});
      return SEND(res,503,{error:"report_temporarily_unavailable"});
    }
  };
}
