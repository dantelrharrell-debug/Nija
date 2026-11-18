// Isolated TIQ72 V515 TEST-only dependency composition.
// This module is NOT imported by the Render holding HTTP server or public Vercel
// game. It never issues owner tokens, runs migrations, or installs HTTP routes.
// A separately reviewed server must supply an authenticated adult issuer,
// fail-closed rate limiter, operator approval, and backed-up migrated schema.
import Stripe from 'stripe';
import pg from 'pg';
import {inspectTiq72IsolatedPrivateUrl} from './tiq72-isolated-readiness.mjs';
import {inspectTiq72TestConfig} from './tiq72-upgrade6-config-preflight.mjs';
import {createTiq72SignedV515Handler} from './tiq72-v515-auth-adapter.mjs';
import {V515PgReportStore} from '../v515/server/v515-pg-report-store.mjs';
import {TEST_PRICE as PRICE, TEST_PRODUCT as PRODUCT} from '../v515/server/verified-report-service.mjs';
const ORIGIN='https://game.nijaaitrading.com';
const TEST_SECRET=/^(?:sk_test_|rk_test_)[a-zA-Z0-9]{16,}$/;
const WEBHOOK_SECRET=/^whsec_[a-zA-Z0-9]{16,}$/;
const KEY_B64URL=/^[A-Za-z0-9_-]{43,171}$/;

function signingKeyFromBase64Url(value) {
  if (typeof value!=='string'||!KEY_B64URL.test(value))
    throw new TypeError('test_only_owner_signing_key_unavailable');
  const key=Buffer.from(value,'base64url');
  if(key.length<32||key.length>128||key.toString('base64url')!==value)
    throw new TypeError('test_only_owner_signing_key_unavailable');
  return key;
}

export function createNonRoutedTiq72SandboxDependencies({
  env=process.env,rateLimit,
  stripeFactory=secret=>new Stripe(secret,{maxNetworkRetries:0,timeout:8000}),
  poolFactory=options=>new pg.Pool(options)
}={}) {
  // Never infer a money-moving approval from the presence of a credential.
  // A trusted future server must separately gate mounting of payment routes.
  if(!env||typeof env!=='object'||env.STRIPE_LIVE_MODE==='true'||
     env.TIQ72_LIVE_PAYMENTS_ENABLED==='true'||
     env.NIJA_GAME_BROWSER_CHECKOUT_ENABLED==='true'||
     env.NIJA_GAME_REPORTS_ENABLED==='true'||
     env.TIQ72_STRIPE_TEST_PRICE_ID!==PRICE||
     env.TIQ72_STRIPE_TEST_PRODUCT_ID!==PRODUCT||
     env.TIQ72_TEST_RETURN_ORIGIN!==ORIGIN||
     env.TIQ_ALLOWED_ORIGIN!==ORIGIN||
     !inspectTiq72IsolatedPrivateUrl(env.TIQ72_TEST_DATABASE_URL)||
     !TEST_SECRET.test(env.STRIPE_TEST_SECRET_KEY||'')||
     !WEBHOOK_SECRET.test(env.STRIPE_TEST_WEBHOOK_SECRET||'')||
     env.STRIPE_TEST_SECRET_KEY===env.STRIPE_LIVE_SECRET_KEY||
     typeof rateLimit!=='function'||
     typeof stripeFactory!=='function'||typeof poolFactory!=='function')
    throw new TypeError('isolated_test_runtime_requirements_not_met');
  // Keep the generic preflight aligned with the *exact* private TEST ledger,
  // without ever changing DATABASE_URL or applying a schema mutation.
  const check=inspectTiq72TestConfig({
    ...env,DATABASE_URL:'isolated_private_database_format_verified'
  });
  if(!check.config_ready)
    throw new TypeError('isolated_test_runtime_requirements_not_met');
  const signingKey=signingKeyFromBase64Url(
    env.TIQ72_TEST_OWNER_SIGNING_KEY_B64URL);
  // Construct clients lazily; no calls to Stripe or PostgreSQL occur here.
  // SSL is REQUIRED by the private URL; do not override with insecure modes.
  const stripe=stripeFactory(env.STRIPE_TEST_SECRET_KEY);
  const pool=poolFactory({
    connectionString:env.TIQ72_TEST_DATABASE_URL,
    max:2,
    connectionTimeoutMillis:8000,
    idleTimeoutMillis:10000
  });
  if(!stripe||!pool||typeof pool.connect!=='function'||
     typeof pool.query!=='function'||typeof pool.end!=='function')
    throw new TypeError('isolated_test_adapters_unavailable');
  const store=new V515PgReportStore(pool);
  const handler=createTiq72SignedV515Handler({
    signingKey,rateLimit,store,stripe,
    webhookSecret:env.STRIPE_TEST_WEBHOOK_SECRET,
    trustedOrigin:ORIGIN
  });
  // This is a library return value ONLY, not a server or HTTP listener.
  // Never expose internal credentials, metadata, clients, or this object publicly.
  return Object.freeze({
    handler,
    close:()=>pool.end()
  });
}
