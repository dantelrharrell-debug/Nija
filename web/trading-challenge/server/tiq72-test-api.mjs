// NIJA Trading IQ 72-decision staging API.
// Scoring only. Checkout intentionally fails closed until DB, Stripe signature verification,
// and report entitlement persistence are implemented and certified.
import http from 'node:http';
import { randomUUID } from 'node:crypto';
import { scoreTiq72ServerSide, TIQ72_DECISIONS, TIQ72_VERSION } from './tiq72-authoritative-adapter.mjs';

const port = Number(process.env.PORT || 10000);
const maxBodyBytes = 32 * 1024;
const allowedOrigin = process.env.TIQ_ALLOWED_ORIGIN || '';
const respond = (res, status, value) => {
  res.writeHead(status, { 'Content-Type':'application/json; charset=utf-8',
    'Cache-Control':'no-store', 'X-Content-Type-Options':'nosniff' });
  res.end(JSON.stringify(value));
};
const server = http.createServer(async (req,res) => {
  const requestId = randomUUID();
  if (req.method === 'OPTIONS') {
    if (allowedOrigin && req.headers.origin === allowedOrigin) {
      res.setHeader('Access-Control-Allow-Origin', allowedOrigin);
      res.setHeader('Access-Control-Allow-Methods','POST, GET, OPTIONS');
      res.setHeader('Access-Control-Allow-Headers','Content-Type');
      res.setHeader('Vary','Origin');
      res.writeHead(204); return res.end();
    }
    return respond(res,403,{error:'origin_not_allowed',requestId});
  }
  if (allowedOrigin && req.headers.origin === allowedOrigin) {
    res.setHeader('Access-Control-Allow-Origin', allowedOrigin);
    res.setHeader('Vary','Origin');
  }
  if (req.url === '/healthz' && req.method === 'GET') {
    return respond(res,200,{status:'scoring_only',version:TIQ72_VERSION,decisions:TIQ72_DECISIONS,
      checkout_available:false,storage_migrated:false,report_fulfillment_verified:false});
  }
  if (req.url === '/api/tiq72/score' && req.method === 'POST') {
    if (!allowedOrigin || req.headers.origin !== allowedOrigin)
      return respond(res,403,{error:'origin_not_allowed',requestId});
    if (req.headers['content-type']?.split(';')[0]?.trim() !== 'application/json')
      return respond(res,415,{error:'content_type',requestId});
    let raw = '';
    try {
      for await (const chunk of req) {
        raw += chunk;
        if (Buffer.byteLength(raw) > maxBodyBytes)
          return respond(res,413,{error:'too_large',requestId});
      }
      const result = scoreTiq72ServerSide(JSON.parse(raw));
      return respond(res,200,{version:result.version,runDigest:result.runDigest,
        validatedDecisions:result.validatedDecisions,score:result.score,
        summary:result.summary,disclaimer:result.disclaimer});
    } catch {
      return respond(res,400,{error:'invalid_run',requestId});
    }
  }
  if (req.url === '/api/tiq72/checkout' || req.url === '/api/tiq72/webhook' ||
      req.url === '/api/tiq72/report') {
    return respond(res,503,{error:'payment_not_certified',requestId});
  }
  return respond(res,404,{error:'not_found',requestId});
});
server.requestTimeout = 10000;
server.headersTimeout = 10000;
server.listen(port,'0.0.0.0');
