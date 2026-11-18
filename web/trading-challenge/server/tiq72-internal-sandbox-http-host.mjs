// NIJA TIQ72 v515: isolated, explicitly authorized sandbox-only HTTP host.
// This is not imported by the current Render holding server. It cannot
// generate adult owner proofs, mutate schemas, or enable live payment routes.
// A trusted independently authenticated adult issuer is required for checkout.
import http from 'node:http';
import {pathToFileURL} from 'node:url';
import {TIQ72_VERSION,TIQ72_DECISIONS} from './tiq72-authoritative-adapter.mjs';
import {createNonRoutedTiq72SandboxDependencies} from './tiq72-isolated-v515-runtime.mjs';
import {runTiq72IsolatedDatabaseProbe} from './tiq72-isolated-db-runtime-probe.mjs';
import {inspectTiq72StripeTestPrice} from './tiq72-stripe-test-readonly-preflight.mjs';

const SERVICE_ID='srv-dbqeqgqfngtc73fcphhg';
const ORIGIN='https://game.nijaaitrading.com';
const allowed=new Map([
  ['/sandbox/checkout','POST'],
  ['/sandbox/report','GET'],
  ['/sandbox/stripe/webhook','POST']
]);
const response=(res,status,data)=>{
  res.writeHead(status,{'Content-Type':'application/json; charset=utf-8'});
  res.end(JSON.stringify(data));
};

// An intentionally conservative *single-instance* limit for isolated internal
// sandbox rehearsals only. Replace with durable/shared abuse controls before any
// customer-facing launch. Every unknown category is rejected.
export function makeInternalSandboxRateLimiter(now=Date.now) {
  const limits={stripe_webhook:120,authenticated_commerce:30};
  const windows=new Map();
  return async (_req,category)=>{
    const max=limits[category];
    if(!max)return false;
    const time=now();
    if(!Number.isSafeInteger(time)||time<0)return false;
    const existing=windows.get(category);
    if(!existing||time-existing.from>=60000) {
      windows.set(category,{from:time,count:1});return true;
    }
    if(time<existing.from||existing.count>=max)return false;
    existing.count++;
    return true;
  };
}

export function requireIsolatedSandboxHostScope(env) {
  if(!env||env.RENDER_SERVICE_ID!==SERVICE_ID ||
     env.TIQ72_ISOLATED_BUILD_SCOPE!=='holding-test-only' ||
     env.TIQ72_INTERNAL_SANDBOX_ROUTE_REVIEW!=='APPROVED_INTERNAL_TEST_ONLY' ||
     env.TIQ72_LIVE_PAYMENTS_ENABLED!=='false' ||
     env.STRIPE_LIVE_MODE!=='false' ||
     env.NIJA_GAME_REPORTS_ENABLED!=='false' ||
     env.NIJA_GAME_BROWSER_CHECKOUT_ENABLED!=='false' ||
     env.TIQ_ALLOWED_ORIGIN!==ORIGIN ||
     env.TIQ72_TEST_RETURN_ORIGIN!==ORIGIN)
    throw new TypeError('isolated_sandbox_host_scope_denied');
}

export async function createTiq72InternalSandboxHttpHost({
  env=process.env,
  databaseProbe=runTiq72IsolatedDatabaseProbe,
  priceProbe=inspectTiq72StripeTestPrice,
  dependenciesFactory=createNonRoutedTiq72SandboxDependencies,
  rateLimit=makeInternalSandboxRateLimiter()
}={}) {
  // Never access provider services unless the dedicated internal test-only
  // deployment has first been explicitly authorized by its operator.
  requireIsolatedSandboxHostScope(env);
  const db=databaseProbe(env);
  if(db?.status!=='identity_verified_read_only' ||
     db.expected_schema_present!==true ||
     !Array.isArray(db.expected_tables_missing) ||
     db.expected_tables_missing.length!==0)
    throw new TypeError('isolated_sandbox_schema_unavailable');
  const price=await priceProbe(env);
  if(price?.status!=='price_verified_test_mode_read_only' ||
     price.stripe_test_price_verified!==true)
    throw new TypeError('isolated_sandbox_stripe_price_unavailable');
  const dependencies=dependenciesFactory({env,rateLimit});
  if(typeof dependencies?.handler!=='function' ||
     typeof dependencies?.close!=='function')
    throw new TypeError('isolated_sandbox_dependencies_unavailable');

  const server=http.createServer((req,res)=>{
    res.setHeader('Cache-Control','no-store');
    res.setHeader('X-Content-Type-Options','nosniff');
    res.setHeader('Referrer-Policy','no-referrer');
    let path;
    try{path=new URL(req.url,'https://internal.invalid').pathname;}catch{
      return response(res,400,{error:'invalid_request'});
    }
    if(req.headers.origin===ORIGIN) {
      res.setHeader('Access-Control-Allow-Origin',ORIGIN);
      res.setHeader('Vary','Origin');
    }
    if(path==='/healthz'&&req.method==='GET')
      return response(res,200,{status:'internal_test_only',version:TIQ72_VERSION,
        decisions:TIQ72_DECISIONS,customer_checkout_available:false,
        sandbox_e2e_certified:false,live_payments_enabled:false});
    if(req.method==='OPTIONS') {
      if(req.headers.origin!==ORIGIN||!allowed.has(path)||path==='/sandbox/stripe/webhook')
        return response(res,403,{error:'origin_not_allowed'});
      res.setHeader('Access-Control-Allow-Methods',allowed.get(path)+', OPTIONS');
      res.setHeader('Access-Control-Allow-Headers','Authorization, Content-Type, X-CSRF-Token');
      res.setHeader('Access-Control-Max-Age','300');
      res.statusCode=204;return res.end();
    }
    if(!allowed.has(path))return response(res,404,{error:'not_found'});
    // All browser-supplied identities must still pass the signed owner-proof
    // adapter; the host never exposes a token-issuing endpoint.
    if(req.headers.origin && req.headers.origin!==ORIGIN)
      return response(res,403,{error:'origin_not_allowed'});
    void Promise.resolve().then(()=>dependencies.handler(req,res)).catch(()=>{
      if(!res.headersSent)return response(res,503,{error:'internal_test_unavailable'});
      if(!res.writableEnded)res.destroy();
    });
  });
  return {server,close:()=>dependencies.close()};
}

// Not Render's startup command. Deliberately independent of the holding server.
// Starting this file requires configured keys, reviewed storage, verified TEST
// price and explicit operator-scope authorization, otherwise it exits closed.
if(process.argv[1]&&import.meta.url===pathToFileURL(process.argv[1]).href){
  createTiq72InternalSandboxHttpHost().then(({server})=>{
    const port=Number(process.env.PORT||10000);
    if(!Number.isSafeInteger(port)||port<1||port>65535)
      throw new TypeError('invalid_sandbox_port');
    server.listen(port,'0.0.0.0');
  }).catch(()=>{
    console.error('TIQ72_INTERNAL_TEST_HTTP blocked: release_requirements_unverified');
    process.exitCode=2;
  });
}
