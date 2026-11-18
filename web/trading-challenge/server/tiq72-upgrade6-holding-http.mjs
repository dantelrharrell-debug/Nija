// Deliberately non-payment staging bootstrap. Never connects to Stripe.
// Startup checks the isolated database read-only; HTTP payment routes stay disabled.
import http from 'node:http';
import { TIQ72_DECISIONS, TIQ72_VERSION } from './tiq72-authoritative-adapter.mjs';
import { safeTiq72IsolatedReadiness } from './tiq72-isolated-readiness.mjs';
import { runTiq72PrivateDbPreflight } from './tiq72-private-db-startup-preflight.mjs';

const port=Number(process.env.PORT||10000);
// This value-free diagnostic appears only in private Render application logs.
// It is not a payment-authorizing gate and is deliberately absent from HTTP.
console.info('TIQ72_ISOLATED_PREFLIGHT '+JSON.stringify(safeTiq72IsolatedReadiness()));
// One non-mutating, private-network identity/table check; output is strictly allowlisted.
// Missing tables, network failures, or unexpected output are reported as blocked.
console.info('TIQ72_PRIVATE_DB_PREFLIGHT '+JSON.stringify(runTiq72PrivateDbPreflight()));
const server=http.createServer((req,res)=>{
 res.setHeader('Content-Type','application/json; charset=utf-8');
 res.setHeader('Cache-Control','no-store');
 res.setHeader('X-Content-Type-Options','nosniff');
 if(req.url==='/healthz'&&req.method==='GET'){
  res.writeHead(200);
  return res.end(JSON.stringify({status:'holding',version:TIQ72_VERSION,decisions:TIQ72_DECISIONS,
   checkout_available:false,report_fulfillment_verified:false,storage_migrated:false}));
 }
 res.writeHead(503);
 res.end(JSON.stringify({error:'Upgrade 6 payment integration not certified',checkout_available:false}));
});
server.listen(port,'0.0.0.0');
