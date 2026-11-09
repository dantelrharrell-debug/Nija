// NIJA 12-round Trading IQ: isolated education-only HOLDING service.
// Deliberately does not import any trading, billing, Stripe, or game source.
// The authoritative 12-round IONOS source is not yet independently certified.
import { createServer } from "node:http";

const health = Object.freeze({
  status: "holding",
  product: "nija-trading-iq-12",
  environment: "isolated-education-staging",
  canonical_source_verified: false,
  storage_certified: false,
  checkout_available: false,
  live_payments: false,
  trading_enabled: false
});

function writeJSON(res, code, value) {
  res.writeHead(code, {
    "Content-Type": "application/json; charset=utf-8",
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'; base-uri 'none'",
    "Access-Control-Allow-Origin": "null"
  });
  res.end(JSON.stringify(value));
}

function handle(req, res) {
  let pathname;
  try {
    pathname = new URL(req.url ?? "/", "http://localhost").pathname;
  } catch {
    return writeJSON(res, 400, { error: "invalid_request" });
  }
  if (pathname === "/healthz" && req.method === "GET") return writeJSON(res, 200, health);
  if (pathname === "/healthz") return writeJSON(res, 405, { error: "method_not_allowed" });
  if (pathname === "/readyz" && req.method === "GET") {
    return writeJSON(res, 503, { status: "blocked", reason: "source_storage_and_payment_uncertified" });
  }
  if (/^\/(api|game|stripe|checkout|report|admin)(\/|$)/.test(pathname)) {
    return writeJSON(res, 503, { error: "not_configured", checkout_available: false });
  }
  return writeJSON(res, 404, { error: "not_found" });
}

// The only allowed runtime configuration is HOLDING/DISABLED.
// Even a mistaken environment flag or deploy cannot activate customer payment.
export function createEducationStagingServer(env = process.env) {
  if ((env.NIJA_TIQ12_ENABLED ?? "false") !== "false" ||
      (env.NIJA_TIQ12_MODE ?? "holding") !== "holding") {
    throw new Error("TIQ12 education staging cannot be enabled before independent certification");
  }
  return createServer(handle);
}
