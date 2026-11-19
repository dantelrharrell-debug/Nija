// Source-level fail-closed regression for the isolated holding service.
// This is NOT a hosted HTTP or payment certification test.
// Avoid launching the preflight server without its private Render runtime.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

test('isolated holding server has only health and denies every other request', () => {
  const source = readFileSync(
    new URL('../server/tiq72-upgrade6-holding-http.mjs', import.meta.url), 'utf8');
  assert.match(source, /http\.createServer\(/);
  assert.match(source, /req\.url===['"]\/healthz['"]&&req\.method===['"]GET['"]/);
  assert.match(source, /res\.writeHead\(200\)/);
  assert.match(source, /status:['"]holding['"]/);
  assert.match(source, /checkout_available:false/);
  assert.match(source, /report_fulfillment_verified:false/);
  assert.match(source, /storage_migrated:false/);
  assert.match(source, /res\.writeHead\(503\)/);
  assert.match(source, /Cache-Control['"],['"]no-store/);
  assert.match(source, /X-Content-Type-Options['"],['"]nosniff/);
  assert.doesNotMatch(source, /createCheckoutSession|stripe\.checkout|createPaymentIntent/);
});
