// Private test-mode REST adapter; never used by the current holding service.
// Network traffic occurs ONLY when a separately approved caller invokes it.
import { Upgrade6Error, requireStripeTestSession } from './tiq12-upgrade6-security.mjs';
const ID = /^[A-Za-z0-9_]{3,250}$/;
const REFUNDABLE = /^ch_[A-Za-z0-9_]{3,250}$/;
const INTENT = /^pi_[A-Za-z0-9_]{3,250}$/;

export function createStripeTestAdapter({ secretKey, allowedOrigin, fetchImpl = fetch }) {
  if (typeof secretKey !== 'string' || !/^sk_test_[A-Za-z0-9]{8,}$/.test(secretKey) ||
      typeof allowedOrigin !== 'string' || !/^https:\/\/[a-z0-9.-]+(?::443)?$/.test(allowedOrigin) ||
      typeof fetchImpl !== 'function') {
    throw new Upgrade6Error('Dedicated Stripe test-only backend unavailable',503);
  }
  async function stripeRequest(method, path, { params, idempotencyKey } = {}) {
    if (!/^\/[a-zA-Z0-9_/?=&.\[\]-]+$/.test(path) || path.includes('..') ||
        (idempotencyKey && !/^tiq12_[a-f0-9]{32}$/.test(idempotencyKey))) {
      throw new Upgrade6Error('Disallowed Stripe API request',422);
    }
    const headers={Authorization:`Bearer ${secretKey}`,Accept:'application/json'};
    if(idempotencyKey)headers['Idempotency-Key']=idempotencyKey;
    if(method==='POST')headers['Content-Type']='application/x-www-form-urlencoded';
    let response;
    try{
      response=await fetchImpl('https://api.stripe.com/v1'+path,{method,headers,
        body:params ? new URLSearchParams(params).toString() : undefined,
        signal:AbortSignal.timeout(8000)});
    }catch{throw new Upgrade6Error('Stripe test API unavailable',503);}
    if(!response.ok)throw new Upgrade6Error('Stripe test API rejected request',503);
    try {return await response.json();}
    catch {throw new Upgrade6Error('Invalid Stripe API response',503);}
  }
  async function verifyPrice({priceId,productId}) {
    if(!/^price_[A-Za-z0-9_]{3,250}$/.test(priceId||'') ||
       !/^prod_[A-Za-z0-9_]{3,250}$/.test(productId||''))return false;
    const p=await stripeRequest('GET','/prices/'+encodeURIComponent(priceId));
    const item=typeof p.product==='string'?p.product:p.product?.id;
    return p.id===priceId && p.active===true && p.livemode===false &&
      p.type==='one_time' && p.unit_amount===100 && p.currency==='usd' && item===productId;
  }
  async function createCheckout(intent,idempotencyKey){
    if(intent?.mode!=='payment'||intent?.line_items?.length!==1||
        intent.line_items[0].quantity!==1 || !ID.test(intent.line_items[0].price||'')){
      throw new Upgrade6Error('Invalid test Checkout intent',422);
    }
    const params={mode:'payment',
      'line_items[0][price]':intent.line_items[0].price,
      'line_items[0][quantity]':'1',
      success_url:allowedOrigin+'/trading-iq/results?session_id={CHECKOUT_SESSION_ID}',
      cancel_url:allowedOrigin+'/trading-iq',
      client_reference_id:intent.metadata.run_id,
    };
    for(const [k,v] of Object.entries(intent.metadata))params[`metadata[${k}]`]=v;
    return stripeRequest('POST','/checkout/sessions',{params,idempotencyKey});
  }
  async function reconcileCheckout(sessionId){
    requireStripeTestSession(sessionId);
    const session=await stripeRequest('GET',`/checkout/sessions/${sessionId}?expand[0]=payment_intent.latest_charge`);
    const lineItems=await stripeRequest('GET',`/checkout/sessions/${sessionId}/line_items?limit=10&expand[0]=data.price.product`);
    if (lineItems.has_more !== false)throw new Upgrade6Error('Incomplete Stripe line items',503);
    return {session,lineItems};
  }
  async function resolveReversalSession(event){
    const item=event?.data?.object;
    let chargeId;
    if (event.type==='charge.refunded')chargeId=item?.id;
    else if (event.type==='charge.dispute.created')chargeId=typeof item?.charge==='string'?item.charge:item?.charge?.id;
    else throw new Upgrade6Error('Unsupported reversal type',422);
    if(!REFUNDABLE.test(chargeId||''))throw new Upgrade6Error('Invalid Stripe charge reference',422);
    const charge=await stripeRequest('GET',`/charges/${chargeId}`);
    const intent=typeof charge?.payment_intent==='string'?charge.payment_intent:charge?.payment_intent?.id;
    if(charge?.id!==chargeId || charge?.livemode!==false || !INTENT.test(intent||''))
      throw new Upgrade6Error('Unverified Stripe reversal identity',422);
    const sessions=await stripeRequest('GET',`/checkout/sessions?payment_intent=${intent}&limit=10`);
    if(sessions?.has_more!==false || !Array.isArray(sessions?.data) || sessions.data.length!==1 ||
        sessions.data[0].livemode!==false || sessions.data[0].payment_intent!==intent)
      throw new Upgrade6Error('Ambiguous reversed Checkout session',422);
    return requireStripeTestSession(sessions.data[0].id);
  }
  return Object.freeze({verifyPrice,createCheckout,reconcileCheckout,resolveReversalSession});
}
