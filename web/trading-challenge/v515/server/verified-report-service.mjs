// Test-only v515 paid report boundary. Never register as a live payment route.
import {buildReport} from "../offline_tiq_premium/tiq_report.mjs";
import {validateRun} from "../offline_tiq_premium/tiq_engine.mjs";
import {TEST_PRICE,TEST_PRODUCT} from "./tiq72-test-offer.mjs";
export {TEST_PRICE,TEST_PRODUCT};
// Historical isolated TEST identifiers are retained for negative regression
// fixtures only. The connected NIJA sandbox account does not own this offer.
// No checkout, webhook, report or receipt validation may authorize it.
export const ISOLATED_TEST_PRICE="price_1UddqtI0gfJjTf3EksOST6m3";
export const ISOLATED_TEST_PRODUCT="prod_VexmVpVMZjIj6Y";
export class PaidReportDenied extends Error {constructor(code){super(code);this.name="PaidReportDenied";}}
// Only the independently verified NIJA TEST-account offer is authorized.
// The trusted server selects this pair, not the browser or a stale account.
export function resolveTestOffer(offer) {
  if(offer===undefined)return Object.freeze({price:TEST_PRICE,product:TEST_PRODUCT});
  if(offer!==null && typeof offer==='object' && !Array.isArray(offer) &&
     Object.getPrototypeOf(offer)===Object.prototype &&
     Object.keys(offer).length===2 &&
     offer.price===TEST_PRICE && offer.product===TEST_PRODUCT)
    return Object.freeze({price:TEST_PRICE,product:TEST_PRODUCT});
  throw new PaidReportDenied('test_product_mismatch');
}
const idOf=x=>typeof x==="string"?x:x?.id;
const ident=(v,p="")=>typeof v==="string"&&v.length>p.length&&v.length<=160&&v.startsWith(p);
export function requireProof({session,lines,intent,charge,reservationId,testOffer}) {
  const {price:expectedPrice,product:expectedProduct}=resolveTestOffer(testOffer);
  if(session?.livemode!==false||session.mode!=="payment"||
     session.status!=="complete"||session.payment_status!=="paid"||
     session.client_reference_id!==reservationId||
     session.metadata?.tiq72_reservation_id!==reservationId||
     session.amount_total!==100||session.amount_subtotal!==100||
     session.currency!=="usd"||!ident(session.id,"cs_test_"))
    throw new PaidReportDenied("checkout_not_verified");
  if(!Array.isArray(lines?.data)||lines.data.length!==1||lines.has_more||
     lines.data[0].quantity!==1||lines.data[0].price?.id!==expectedPrice||
     idOf(lines.data[0].price?.product)!==expectedProduct||
     lines.data[0].price?.unit_amount!==100||lines.data[0].price?.currency!=="usd")
    throw new PaidReportDenied("test_product_mismatch");
  if(intent?.id!==idOf(session.payment_intent)||intent.livemode!==false||
     intent.status!=="succeeded"||intent.amount_received!==100||
     intent.currency!=="usd"||!ident(intent.id,"pi_"))
    throw new PaidReportDenied("payment_not_verified");
  if(charge?.id!==idOf(intent.latest_charge)||charge.livemode!==false||
     charge.status!=="succeeded"||charge.paid!==true||
     charge.amount!==100||charge.currency!=="usd"||
     charge.payment_intent!==intent.id||charge.refunded!==false||
     charge.disputed!==false||charge.amount_refunded!==0)
    throw new PaidReportDenied("charge_not_verified");
}
// Caller MUST authenticate ownerId. Store MUST use durable owner-scoped queries:
// getOwnedPurchase(ownerId,runId) returns {ownerId,runId,reservationId,
//   sessionId,canonicalRun,state:"paid"}.
// storeVerifiedReport atomically upserts one immutable report for the same
// owner/run/session and never grants or extends a revoked entitlement.
// stripe MUST use isolated test-mode credentials; do not expose this via HTTP.
export async function verifyAndBuildPaidReport({ownerId,runId,store,stripe,testOffer}) {
  if(!ident(ownerId)||!ident(runId)||!store||!stripe)
    throw new PaidReportDenied("authenticated_context_required");
  const row=await store.getOwnedPurchase(ownerId,runId);
  if(!row||row.ownerId!==ownerId||row.runId!==runId||
     row.state!=="paid"||!ident(row.reservationId)||
     !ident(row.sessionId,"cs_test_"))
    throw new PaidReportDenied("owned_paid_run_required");
  if(!validateRun(row.canonicalRun).ok)
    throw new PaidReportDenied("canonical_run_invalid");
  const [session,lines]=await Promise.all([
    stripe.checkout.sessions.retrieve(row.sessionId),
    stripe.checkout.sessions.listLineItems(row.sessionId)]);
  if(session?.id!==row.sessionId||!ident(idOf(session.payment_intent),"pi_"))
    throw new PaidReportDenied("session_identity_mismatch");
  const intent=await stripe.paymentIntents.retrieve(idOf(session.payment_intent));
  if(!ident(idOf(intent?.latest_charge),"ch_"))
    throw new PaidReportDenied("charge_identity_missing");
  const charge=await stripe.charges.retrieve(idOf(intent.latest_charge));
  requireProof({session,lines,intent,charge,reservationId:row.reservationId,testOffer});
  const report=buildReport(row.canonicalRun);
  if(!report)throw new PaidReportDenied("report_generation_failed");
  await store.storeVerifiedReport({ownerId,runId,sessionId:row.sessionId,report});
  return report;
}

/**
 * Test-only paid report recovery with fresh provider proof on every request.
 * The HTTP adapter MUST supply an independently authenticated owner, never
 * trust ownerId from query/body or infer ownership from a Stripe session URL.
 * Running verifyAndBuildPaidReport also guards concurrent local revocations.
 */
export async function recoverFreshPaidReport({ownerId,runId,store,stripe,testOffer}) {
  if (!store || typeof store.getOwnedPaidReport!=="function")
    throw new PaidReportDenied("protected_report_store_required");
  await verifyAndBuildPaidReport({ownerId,runId,store,stripe,testOffer});
  const report=await store.getOwnedPaidReport(ownerId,runId);
  if(!report)throw new PaidReportDenied("paid_report_not_available");
  return report;
}
