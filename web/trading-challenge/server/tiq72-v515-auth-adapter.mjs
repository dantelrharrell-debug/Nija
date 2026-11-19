// Isolated V515 commerce boundary. This is a factory, not a public route.
// An independently authenticated adult server-side issuer must sign owner proofs.
// No browser-provided user ID, self-attested age, or unsigned header is trusted.
import {createV515SandboxHttpAdapter} from '../v515/server/v515-sandbox-http-adapter.mjs';
import {authenticateTiq72OwnerRequest} from './tiq72-signed-owner-proof.mjs';

export function createTiq72SignedV515Handler({
  signingKey, rateLimit, store, stripe, webhookSecret, trustedOrigin,testOffer
}) {
  if (!Buffer.isBuffer(signingKey) || signingKey.length < 32 ||
      signingKey.length > 128 || typeof rateLimit !== 'function' ||
      !store || !stripe || typeof webhookSecret !== 'string' ||
      !/^whsec_[A-Za-z0-9]+$/.test(webhookSecret) ||
      trustedOrigin !== 'https://game.nijaaitrading.com')
    throw new TypeError('signed_isolated_v515_dependencies_required');
  return createV515SandboxHttpAdapter({
    authenticate: req => authenticateTiq72OwnerRequest(req, signingKey),
    rateLimit, store, stripe, webhookSecret, trustedOrigin,testOffer
  });
}
