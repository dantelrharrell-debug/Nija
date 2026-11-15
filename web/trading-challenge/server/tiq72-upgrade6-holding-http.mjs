// Deliberately non-payment staging bootstrap. Does not read secrets or access databases.
// This HTTP process exists solely to validate isolated Render deployment wiring.
import http from 'node:http';
import { TIQ72_DECISIONS, TIQ72_VERSION } from './tiq72-authoritative-adapter.mjs';
const port=Number(process.env.PORT||10000);
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
