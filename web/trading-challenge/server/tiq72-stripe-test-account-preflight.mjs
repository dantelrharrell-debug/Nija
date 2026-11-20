// Isolated TIQ72 TEST-only Stripe account identity diagnostic.
// GET-only; never creates checkout, grants entitlements or logs the key,
// Stripe response, unexpected account identifier, or request exceptions.
// The expected account is the independently connected NIJA Stripe sandbox,
// which also owns the currently disabled TIQ72 TEST webhook destination.
const EXPECTED_SANDBOX_ACCOUNT='acct_1Tzy1CRS5Ezp77RQ';
const blocked=reason=>({status:'blocked',reason,
  stripe_test_account_verified:false,checkout_available:false});

export async function inspectTiq72StripeTestAccount(env=process.env, request=fetch) {
  const key=env?.STRIPE_TEST_SECRET_KEY;
  if(typeof key!=='string' || !/^(?:sk_test_|rk_test_)[A-Za-z0-9]{8,}$/.test(key))
    return blocked('stripe_test_key_unavailable');
  if(key===env.STRIPE_LIVE_SECRET_KEY || env.STRIPE_LIVE_MODE==='true' ||
     env.TIQ72_LIVE_PAYMENTS_ENABLED==='true')
    return blocked('test_only_boundary_not_confirmed');
  try {
    const response=await request('https://api.stripe.com/v1/account',{
      method:'GET',
      headers:{Authorization:'Bearer '+key,Accept:'application/json'},
      signal:AbortSignal.timeout(5000)
    });
    if(response?.status===401 || response?.status===403)
      return blocked('stripe_test_account_key_rejected_or_restricted');
    if(!response?.ok || typeof response.text!=='function')
      return blocked('stripe_test_account_unavailable');
    const length=Number(response.headers?.get?.('content-length')??0);
    if(!Number.isFinite(length)||length<0||length>65536)
      return blocked('stripe_test_account_response_invalid');
    const raw=await response.text();
    if(raw.length>65536)
      return blocked('stripe_test_account_response_invalid');
    const body=JSON.parse(raw);
    if(body?.object!=='account'||typeof body.id!=='string')
      return blocked('stripe_test_account_response_invalid');
    if(body.id!==EXPECTED_SANDBOX_ACCOUNT)
      return blocked('stripe_test_account_mismatch');
    return {status:'sandbox_account_verified_read_only',
      stripe_test_account_verified:true,checkout_available:false};
  } catch {
    return blocked('stripe_test_account_verification_failed');
  }
}
