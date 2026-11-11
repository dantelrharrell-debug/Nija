// This education-only release has no payment authority. Environment flags cannot enable it.
export const releaseStatus = Object.freeze({
  source: "nija-tiq-gameonly-4a64f74c", sourceSha256: "77079538953000d0ebbd741665c081820de3a8c6f60debc0cb6c72502f99d224",
  roundsPerScenario: 12, scenariosPerRun: 6, decisionsPerRun: 72,
  freeGameplay: true, checkout_available: false, live_payments: false,
  report_fulfillment_verified: false, trading_enabled: false,
  release: "education-only-preview", blockers: ["durable_payment_storage", "sandbox_end_to_end", "secure_receipt_recovery", "release_security_checks"]
});
export function respond(res, code, body) {
  res.statusCode = code;
  res.setHeader("Content-Type", "application/json; charset=utf-8");
  res.setHeader("Cache-Control", "no-store");
  res.setHeader("X-Content-Type-Options", "nosniff");
  return res.end(JSON.stringify(body));
}
