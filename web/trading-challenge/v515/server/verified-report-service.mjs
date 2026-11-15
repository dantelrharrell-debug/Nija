// Test-only v515 paid report boundary. Never register as a live payment route.
import {buildReport} from "../offline_tiq_premium/tiq_report.mjs";
import {validateRun} from "../offline_tiq_premium/tiq_engine.mjs";
export const TEST_PRICE="price_1UYToJRS5Ezp77RQVkx96eS5";
export const TEST_PRODUCT="prod_nija_iq72_sandbox_v1";
export class PaidReportDenied extends Error {constructor(code){super(code);this.name="PaidReportDenied";}}
const idOf=x=>typeof x==="string"?x:x?.id;
const ident=(v,p="")=>typeof v==="string"&&v.length>p.length&&v.length<=160&&v.startsWith(p);
export function requireProof({session,lines,intent,charge,reservationId}) {
  if(session?.livemode!==false||session.mode!=="payment"||
     session.status!=="complete"||session.payment_status!=="paid"||
     session.client_reference_id!==reservationId||
     session.metadata?.tiq72_reservation_id!==reservationId||
     session.amount_total!==100||session.amount_subtotal!==100||
     session.currency!=="usd"||!ident(session.id,"cs_test_"))
    throw new PaidReportDenied("checkout_not_verified");
  if(!Array.isArray(lines?.data)||lines.data.length!==1||lines.has_more||
     lines.data[0].quantity!==1||lines.data[0].price?.id!==TEST_PRICE||
     idOf(lines.data[0].price?.product)!==TEST_PRODUCT||
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
export async function verifyAndBuildPaidReport({ownerId,runId,store,stripe}) {
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
    stripe.checkout.Session.retrieve(row.sessionId),
    stripe.checkout.Session.listLineItems(row.sessionId)]);
  if(session?.id!==row.sessionId||!ident(idOf(session.payment_intent),"pi_"))
    throw new PaidReportDenied("session_identity_mismatch");
  const intent=await stripe.PaymentIntent.retrieve(idOf(session.payment_intent));
  if(!ident(idOf(intent?.latest_charge),"ch_"))
    throw new PaidReportDenied("charge_identity_missing");
  const charge=await stripe.Charge.retrieve(idOf(intent.latest_charge));
  requireProof({session,lines,intent,charge,reservationId:row.reservationId});
  const report=buildReport(row.canonicalRun);
  if(!report)throw new PaidReportDenied("report_generation_failed");
  await store.storeVerifiedReport({ownerId,runId,sessionId:row.sessionId,report});
  return report;
}
