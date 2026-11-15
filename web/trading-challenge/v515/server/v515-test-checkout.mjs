// Isolated, non-routed TEST-mode Checkout for the approved v515 game.
// The HTTP layer must authenticate the owner and protect CSRF before calling.
// No live API key, customer-facing Vercel handler or production deployment.
import {createHash} from "node:crypto";
import {validateRun} from "../offline_tiq_premium/tiq_engine.mjs";
import {PaidReportDenied,TEST_PRICE,TEST_PRODUCT} from "./verified-report-service.mjs";
const id=x=>typeof x==="string"?x:x?.id;
function allowedOrigin(value) {
  if(typeof value!=="string")throw new PaidReportDenied("trusted_return_origin_required");
  let url;
  try{url=new URL(value);}catch{throw new PaidReportDenied("trusted_return_origin_required");}
  if(url.protocol!=="https:"||url.origin!==value||
     url.username||url.password||url.search||url.hash||
     (url.hostname!=="game.nijaaitrading.com" &&
      url.hostname!=="nija-trading-challenge.vercel.app"))
    throw new PaidReportDenied("trusted_return_origin_required");
  return url.origin;
}
export async function startVerifiedTestCheckout({
  ownerId,attemptKey,adultAttested,canonicalRun,trustedOrigin,store,stripe
}){
  // Authentication and adult eligibility belong to the protected calling API.
  if(typeof ownerId!=="string"||ownerId.length<1||ownerId.length>160||
     typeof attemptKey!=="string"||
     !/^[A-Za-z0-9_-]{16,80}$/.test(attemptKey)||
     adultAttested!==true||!store?.reserveAuthenticatedRun||
     !store?.attachVerifiedTestCheckout||!stripe?.checkout?.sessions?.create)
    throw new PaidReportDenied("authenticated_adult_checkout_required");
  const valid=validateRun(canonicalRun);
  if(!valid.ok)throw new PaidReportDenied("canonical_72_decisions_required");
  const origin=allowedOrigin(trustedOrigin);
  const price=await stripe.prices.retrieve(TEST_PRICE);
  if(price?.id!==TEST_PRICE||price.livemode!==false||price.active!==true||
     id(price.product)!==TEST_PRODUCT||price.unit_amount!==100||
     price.currency!=="usd"||price.type!=="one_time")
    throw new PaidReportDenied("verified_test_price_required");
  const digest=createHash("sha256").update(JSON.stringify(valid.run)).digest("hex");
  const reservation=await store.reserveAuthenticatedRun({
    ownerId,attemptKey,canonicalRun:valid.run,canonicalDigest:digest});
  if(reservation.state==="paid"||reservation.state==="refunded"||
     reservation.state==="disputed")
    throw new PaidReportDenied("paid_or_revoked_attempt_not_repeatable");
  let session;
  if(reservation.sessionId){
    session=await stripe.checkout.sessions.retrieve(reservation.sessionId);
  }else{
    // A stable Stripe idempotency key is reused after a timeout or retry;
    // persist reservation first, then bind exactly one resulting TEST session.
    session=await stripe.checkout.sessions.create({
      mode:"payment",line_items:[{price:TEST_PRICE,quantity:1}],
      client_reference_id:reservation.reservationId,
      metadata:{tiq72_reservation_id:reservation.reservationId,
        tiq72_run_id:reservation.runId,tiq72_version:"v515-72-decisions"},
      success_url:origin+"/trading-iq-challenge/payment-return?session_id={CHECKOUT_SESSION_ID}",
      cancel_url:origin+"/trading-iq-challenge"
    },{idempotencyKey:"nija-tiq72-v515-"+reservation.reservationId});
  }
  if(session?.livemode!==false||session.mode!=="payment"||
     typeof session.id!=="string"||!session.id.startsWith("cs_test_")||
     session.client_reference_id!==reservation.reservationId||
     session.metadata?.tiq72_reservation_id!==reservation.reservationId||
     session.payment_status!=="unpaid"||session.status!=="open"||
     !session.url)
    throw new PaidReportDenied("test_checkout_session_required");
  let paymentUrl;
  try{paymentUrl=new URL(session.url);}catch{
    throw new PaidReportDenied("hosted_checkout_url_required");
  }
  if(paymentUrl.protocol!=="https:"||paymentUrl.hostname!=="checkout.stripe.com"||
     paymentUrl.username||paymentUrl.password)
    throw new PaidReportDenied("hosted_checkout_url_required");
  await store.attachVerifiedTestCheckout({
    reservationId:reservation.reservationId,ownerId,sessionId:session.id});
  return {checkoutUrl:session.url,runId:reservation.runId,
    reservationId:reservation.reservationId};
}
