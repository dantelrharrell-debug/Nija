// TIQ72 isolated TEST-only signed owner proof. No HTTP endpoint issues tokens.
// The trusted backend identity provider, after verifying an adult session, must
// generate these proofs. A browser's assertion of age or ownerId is insufficient.
import {createHmac, randomBytes, timingSafeEqual} from 'node:crypto';

const AUDIENCE = 'nija-tiq72-isolated-test';
const VERSION = 1;
const MAX_TTL_SECONDS = 10 * 60;
const TOKEN_RE = /^[A-Za-z0-9_-]{60,1400}\.[A-Za-z0-9_-]{43}$/;
const CSRF_RE = /^[A-Za-z0-9_-]{32,96}$/;
const OWNER_RE = /^[A-Za-z0-9_.:@-]{1,160}$/;
const HMAC_RE = /^[A-Za-z0-9_-]{43}$/;
const KEYS = ['v', 'aud', 'sub', 'adult', 'csrf', 'iat', 'exp'];

function requireKey(key) {
  if (!Buffer.isBuffer(key) || key.byteLength < 32 || key.byteLength > 128)
    throw new TypeError('isolated_signing_key_required');
  return key;
}
function validOwner(value) {
  return typeof value === 'string' && OWNER_RE.test(value);
}
function signature(payload, key) {
  return createHmac('sha256', key).update(payload, 'ascii').digest('base64url');
}
function fixedEqual(a, b) {
  if (!HMAC_RE.test(a) || !HMAC_RE.test(b)) return false;
  const ab = Buffer.from(a, 'ascii'), bb = Buffer.from(b, 'ascii');
  return ab.length === bb.length && timingSafeEqual(ab, bb);
}
export function createTiq72OwnerProof({ownerId, adultVerified}, key, options = {}) {
  requireKey(key);
  // This function is only for an independently authenticated server-side issuer.
  // Never expose an issuance endpoint that takes an owner/age claim from the browser.
  if (!validOwner(ownerId) || adultVerified !== true)
    throw new TypeError('authenticated_adult_issuer_required');
  const nowSec = options.nowSec ?? Math.floor(Date.now() / 1000);
  const ttlSec = options.ttlSec ?? MAX_TTL_SECONDS;
  if (!Number.isSafeInteger(nowSec) || nowSec <= 0 ||
      !Number.isSafeInteger(ttlSec) || ttlSec < 1 || ttlSec > MAX_TTL_SECONDS)
    throw new TypeError('invalid_test_proof_lifetime');
  const csrfToken = randomBytes(32).toString('base64url');
  const body = {v: VERSION, aud: AUDIENCE, sub: ownerId, adult: true,
    csrf: csrfToken, iat: nowSec, exp: nowSec + ttlSec};
  const payload = Buffer.from(JSON.stringify(body), 'utf8').toString('base64url');
  return {token: payload + '.' + signature(payload, key), csrfToken};
}
export function verifyTiq72OwnerProof(token, key, options = {}) {
  requireKey(key);
  if (typeof token !== 'string' || !TOKEN_RE.test(token)) return null;
  const [payload, mac] = token.split('.');
  if (!fixedEqual(signature(payload, key), mac)) return null;
  let claims;
  try {
    const decoded = Buffer.from(payload, 'base64url');
    if (decoded.length > 1024 || decoded.toString('base64url') !== payload)
      return null;
    claims = JSON.parse(decoded.toString('utf8'));
  } catch { return null; }
  if (!claims || typeof claims !== 'object' || Array.isArray(claims) ||
      Object.keys(claims).length !== KEYS.length ||
      !KEYS.every(k => Object.hasOwn(claims, k)) ||
      claims.v !== VERSION || claims.aud !== AUDIENCE ||
      !validOwner(claims.sub) || claims.adult !== true ||
      typeof claims.csrf !== 'string' || !CSRF_RE.test(claims.csrf) ||
      !Number.isSafeInteger(claims.iat) || !Number.isSafeInteger(claims.exp) ||
      claims.iat <= 0 || claims.exp <= claims.iat ||
      claims.exp - claims.iat > MAX_TTL_SECONDS) return null;
  const nowSec = options.nowSec ?? Math.floor(Date.now() / 1000);
  if (!Number.isSafeInteger(nowSec) || nowSec < claims.iat - 30 || nowSec >= claims.exp)
    return null;
  return {ownerId: claims.sub, csrfToken: claims.csrf};
}
export function authenticateTiq72OwnerRequest(req, key, options = {}) {
  const header = req?.headers?.authorization;
  if (typeof header !== 'string' || !header.startsWith('Bearer ') ||
      header.indexOf(' ', 7) !== -1) return null;
  return verifyTiq72OwnerProof(header.slice(7), key, options);
}
