// NIJA TIQ72: read-only, value-free Stripe TEST price preflight.
// Safe to run only in the isolated Render holding service. This never creates
// Checkout Sessions, reads customer records, grants entitlements, or enables payment.
import {TEST_PRICE,TEST_PRODUCT} from '../v515/server/tiq72-test-offer.mjs';
const blocked=reason=>({status:'blocked',reason,stripe_test_price_verified:false,checkout_available:false});

export async function inspectTiq72StripeTestPrice(env=process.env, request=fetch) {
  const key=env.STRIPE_TEST_SECRET_KEY;
  if(typeof key!=='string' || !/^(?:sk_test_|rk_test_)[A-Za-z0-9]{8,}$/.test(key))
    return blocked('stripe_test_key_unavailable');
  if(key===env.STRIPE_LIVE_SECRET_KEY || env.STRIPE_LIVE_MODE==='true' ||
     env.TIQ72_LIVE_PAYMENTS_ENABLED==='true')
    return blocked('test_only_boundary_not_confirmed');
  if(env.TIQ72_STRIPE_TEST_PRICE_ID!==TEST_PRICE ||
     env.TIQ72_STRIPE_TEST_PRODUCT_ID!==TEST_PRODUCT)
    return blocked('stripe_test_offer_config_mismatch');
  try {
    const response=await request('https://api.stripe.com/v1/prices/'+TEST_PRICE,{
      method:'GET',
      headers:{Authorization:'Bearer '+key,Accept:'application/json'},
      signal:AbortSignal.timeout(5000)
    });
    if(response?.status===401 || response?.status===403)
      return blocked('stripe_test_key_rejected_or_insufficient_scope');
    if(!response?.ok || typeof response.text!=='function')
      return blocked('stripe_test_price_unavailable');
    const length=Number(response.headers?.get?.('content-length') ?? 0);
    if(!Number.isFinite(length) || length>8192)
      return blocked('stripe_test_price_response_invalid');
    const raw=await response.text();
    if(raw.length>8192)
      return blocked('stripe_test_price_response_invalid');
    const price=JSON.parse(raw);
    const product=typeof price?.product==='string'?price.product:price?.product?.id;
    if(price?.id!==TEST_PRICE || product!==TEST_PRODUCT ||
       price?.active!==true || price?.livemode!==false ||
       price?.unit_amount!==100 || price?.currency!=='usd' ||
       price?.type!=='one_time')
      return blocked('stripe_test_price_identity_mismatch');
    return {status:'price_verified_test_mode_read_only',
      stripe_test_price_verified:true,checkout_available:false};
  }catch {
    // Do not reveal provider body, network errors, URLs with credentials, or keys.
    return blocked('stripe_test_price_verification_failed');
  }
}
