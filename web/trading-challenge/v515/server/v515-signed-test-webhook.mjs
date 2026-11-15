// Isolated v515 Stripe TEST-only orchestrator, not an HTTP handler.
// Authenticated Stripe SDK instance + raw request bytes must be supplied by
// a separately reviewed API adapter; this module never handles live payments.
import {PaidReportDenied,requireProof,TEST_PRICE,TEST_PRODUCT} from "./verified-report-service.mjs";
const id=x=>typeof x==="string"?x:x?.id;
const named=(x,p)=>typeof x==="string"&&x.startsWith(p)&&x.length>p.length&&x.length<=160;
const payTypes=new Set(["checkout.session.completed","checkout.session.async_payment_succeeded"]);
const reversalTypes=new Set(["charge.refunded","charge.dispute.created"]);
function assertLineItems(lines) {
  if (!Array.isArray(lines?.data)||lines.data.length!==1||lines.has_more ||
      lines.data[0].quantity!==1||lines.data[0].price?.id!==TEST_PRICE ||
      id(lines.data[0].price?.product)!==TEST_PRODUCT||
      lines.data[0].price?.unit_amount!==100||
      lines.data[0].price?.currency!=="usd")
    throw new PaidReportDenied("wrong_test_product");
}
function assertSession(session) {
  if (session?.livemode!==false||!named(session.id,"cs_test_")||
      session.mode!=="payment"||session.status!=="complete"||
      session.payment_status!=="paid"||session.currency!=="usd"||
      session.amount_total!==100||session.amount_subtotal!==100||
      !named(session.client_reference_id,"")||
      session.metadata?.tiq72_reservation_id!==session.client_reference_id||
      !named(id(session.payment_intent),"pi_"))
    throw new PaidReportDenied("wrong_test_checkout");
}
export async function processSignedTestWebhook({rawBody,signature,webhookSecret,stripe,store}) {
  if (!Buffer.isBuffer(rawBody)||rawBody.length===0||rawBody.length>65536||
      !named(signature,"t=")||!named(webhookSecret,"whsec_")||
      !stripe?.webhooks?.constructEvent||
      !store?.recordVerifiedProviderEvent)
    throw new PaidReportDenied("webhook_context_required");
  // DO NOT parse or modify the payload before Stripe verifies signature/time.
  const event=stripe.webhooks.constructEvent(rawBody,signature,webhookSecret);
  if (!named(event?.id,"evt_")||event.livemode!==false||
      !event.data?.object||typeof event.data.object!=="object"||
      Array.isArray(event.data.object))
    throw new PaidReportDenied("signed_test_event_required");
  if (!payTypes.has(event.type)&&!reversalTypes.has(event.type))
    return {ignored:true};
  let session,reservationId;
  if(payTypes.has(event.type)) {
    if (!named(event.data.object.id,"cs_test_"))
      throw new PaidReportDenied("checkout_event_identity_required");
    session=await stripe.checkout.Session.retrieve(event.data.object.id);
    if (session?.id!==event.data.object.id)
      throw new PaidReportDenied("session_identity_mismatch");
    assertSession(session);
    const [lines,intent]=await Promise.all([
      stripe.checkout.Session.listLineItems(session.id),
      stripe.PaymentIntent.retrieve(id(session.payment_intent))]);
    if(!named(id(intent?.latest_charge),"ch_"))
      throw new PaidReportDenied("charge_identity_missing");
    const charge=await stripe.Charge.retrieve(id(intent.latest_charge));
    requireProof({session,lines,intent,charge,reservationId:session.client_reference_id});
  } else {
    const disputeEvent=event.type==="charge.dispute.created";
    const chargeId=disputeEvent?id(event.data.object.charge):event.data.object.id;
    if (!named(chargeId,"ch_"))
      throw new PaidReportDenied("reversal_charge_required");
    const charge=await stripe.Charge.retrieve(chargeId);
    if (charge?.id!==chargeId||charge.livemode!==false||
        charge.status!=="succeeded"||charge.paid!==true||
        charge.amount!==100||charge.currency!=="usd"||
        !named(id(charge.payment_intent),"pi_"))
      throw new PaidReportDenied("reversal_not_verified");
    if(disputeEvent){
      const dispute=await stripe.Dispute.retrieve(event.data.object.id);
      if(dispute?.id!==event.data.object.id||dispute.livemode!==false||
         id(dispute.charge)!==chargeId)
        throw new PaidReportDenied("dispute_not_verified");
    } else if (charge.refunded!==true||!Number.isInteger(charge.amount_refunded)||charge.amount_refunded<=0) {
      throw new PaidReportDenied("refund_not_verified");
    }
    const intent=await stripe.PaymentIntent.retrieve(id(charge.payment_intent));
    if(intent?.id!==id(charge.payment_intent)||intent.livemode!==false||
       intent.amount_received!==100||intent.currency!=="usd"||
       id(intent.latest_charge)!==charge.id)
      throw new PaidReportDenied("reversal_intent_mismatch");
    const list=await stripe.checkout.Session.list({payment_intent:intent.id,limit:2});
    if(!Array.isArray(list?.data)||list.data.length!==1||list.has_more)
      throw new PaidReportDenied("unique_checkout_required");
    session=await stripe.checkout.Session.retrieve(list.data[0].id);
    if(session?.id!==list.data[0].id)
      throw new PaidReportDenied("reversal_session_mismatch");
    assertSession(session);
    if(id(session.payment_intent)!==intent.id)
      throw new PaidReportDenied("reversal_session_intent_mismatch");
    assertLineItems(await stripe.checkout.Session.listLineItems(session.id));
  }
  reservationId=session.client_reference_id;
  const result=await store.recordVerifiedProviderEvent({
    eventId:event.id,eventType:event.type,reservationId,sessionId:session.id
  });
  return {processed:true,...result};
}
