import http from "node:http";
import fs from "node:fs/promises";
import path from "node:path";
import { isIP } from "node:net";
import { fileURLToPath } from "node:url";
import { randomUUID } from "node:crypto";
import { PRICE_ID, PRODUCT_ID, OFFER, SESSION_ID, checkoutEnabled, liveKey, issueProof, hashProof,
  issueCookie, readProof, verifyPrice, verifyPurchase } from "./checkout-security.mjs";
import { scoreReport, validAnswers, VERSION } from "./scoring.mjs";

const publicDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../public");
const PORT = Number(process.env.PORT || 8787);
const BASE_URL = (process.env.PUBLIC_BASE_URL || (process.env.VERCEL_URL ? "https://" + process.env.VERCEL_URL : "http://localhost:" + PORT)).replace(/\/$/, "");
const BASE_ORIGIN = new URL(BASE_URL).origin;
const STRIPE_SECRET_KEY = process.env.STRIPE_SECRET_KEY || "";
const STRIPE_LIVE = liveKey(STRIPE_SECRET_KEY);
// Real Stripe test-mode resources live in a separate namespace. Never use
// the live price ID with a test-mode key or vice versa.
const STRIPE_PRICE_ID = STRIPE_LIVE ? PRICE_ID : (process.env.NIJA_GAME_TEST_PRICE_ID || "");
const STRIPE_PRODUCT_ID = STRIPE_LIVE ? PRODUCT_ID : (process.env.NIJA_GAME_TEST_PRODUCT_ID || "");
const TEST_IDENTITIES_VALID = /^price_[A-Za-z0-9_]+$/.test(STRIPE_PRICE_ID) &&
  /^prod_[A-Za-z0-9_]+$/.test(STRIPE_PRODUCT_ID);
const SECURE_COOKIE = BASE_ORIGIN.startsWith("https://");
// Production checkout remains disabled until a reviewed release explicitly enables it.
const CHECKOUT_READY = checkoutEnabled(STRIPE_SECRET_KEY, process.env.NIJA_REPORT_CHECKOUT_ENABLED) &&
  TEST_IDENTITIES_VALID && (process.env.VERCEL_ENV !== "production" || STRIPE_LIVE);
const approvedFiles = {
  "/": ["index.html", "text/html; charset=utf-8"],
  "/index.html": ["index.html", "text/html; charset=utf-8"],
  "/app.js": ["app.js", "text/javascript; charset=utf-8"],
  "/scenarios.js": ["scenarios.js", "text/javascript; charset=utf-8"],
  "/styles.css": ["styles.css", "text/css; charset=utf-8"]
};
const traffic = new Map();

if (process.env.NODE_ENV === "production" && (!process.env.PUBLIC_BASE_URL && !process.env.VERCEL_URL || !BASE_URL.startsWith("https://"))) {
  throw new Error("Production requires an explicit HTTPS PUBLIC_BASE_URL");
}

function setHeaders(res) {
  res.setHeader("X-Content-Type-Options", "nosniff");
  res.setHeader("Referrer-Policy", "no-referrer");
  res.setHeader("X-Frame-Options", "DENY");
  res.setHeader("Permissions-Policy", "camera=(), microphone=(), geolocation=()");
  res.setHeader("Content-Security-Policy",
    "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'");
  res.setHeader("Cache-Control", "no-store");
}
function json(res, code, object) {
  res.writeHead(code, { "Content-Type": "application/json; charset=utf-8" });
  res.end(JSON.stringify(object));
}
async function bodyJSON(req) {
  if (req.body !== undefined) {
    const supplied = req.body;
    const content = Buffer.isBuffer(supplied) ? supplied.toString("utf8")
      : typeof supplied === "string" ? supplied : JSON.stringify(supplied);
    if (Buffer.byteLength(content, "utf8") > 4096) throw new Error("Request too large");
    return JSON.parse(content);
  }
  let bytes = 0, content = "";
  for await (const chunk of req) {
    bytes += chunk.length;
    if (bytes > 4096) throw new Error("Request too large");
    content += chunk.toString("utf8");
  }
  return JSON.parse(content);
}
async function stripeRequest(route, options = {}) {
  const response = await fetch("https://api.stripe.com/v1/" + route, {
    method: options.body ? "POST" : "GET",
    headers: {
      "Authorization": "Bearer " + STRIPE_SECRET_KEY,
      ...(options.body ? {
        "Content-Type": "application/x-www-form-urlencoded",
        "Idempotency-Key": randomUUID()
      } : {})
    },
    body: options.body ? options.body.toString() : undefined,
    signal: AbortSignal.timeout(12000)
  });
  if (!response.ok) {
    console.error("Stripe request rejected with status", response.status);
    throw new Error("Payment provider unavailable");
  }
  return response.json();
}
function rateLimit(req) {
  const now = Date.now();
  const vercelIp = req.headers["x-vercel-forwarded-for"];
  const trustedProxyHops = Number(process.env.TRUSTED_PROXY_HOPS || 0);
  const forwardedFor = req.headers["x-forwarded-for"];
  const forwardedAddresses = typeof forwardedFor === "string"
    ? forwardedFor.split(",").map(address => address.trim())
    : [];
  const forwardedIp = Number.isSafeInteger(trustedProxyHops) && trustedProxyHops > 0
    ? forwardedAddresses[forwardedAddresses.length - trustedProxyHops]
    : "";
  const ip = process.env.VERCEL && typeof vercelIp === "string" && isIP(vercelIp.trim())
    ? vercelIp.trim()
    : isIP(forwardedIp || "") ? forwardedIp : req.socket.remoteAddress || "unknown";
  const prior = traffic.get(ip) || [];
  const active = prior.filter(time => now - time < 3600000);
  if (traffic.size > 5000) traffic.clear();
  if (active.length >= 30) return false;
  active.push(now); traffic.set(ip, active); return true;
}
async function checkout(req, res) {
  if (!CHECKOUT_READY) return json(res, 503, { error: "Secure checkout is not configured yet." });
  if (req.headers.origin !== BASE_ORIGIN) return json(res, 403, { error: "Invalid request origin." });
  if (!rateLimit(req)) return json(res, 429, { error: "Too many attempts. Please try later." });
  let data;
  try { data = await bodyJSON(req); } catch { return json(res, 400, { error: "Invalid checkout request." }); }
  if (data.version !== VERSION || !validAnswers(data.answers)) {
    return json(res, 400, { error: "Complete the six market decisions first." });
  }
  try {
    // Verify the immutable configured one-dollar Stripe price and product before
    // asking Stripe to accept any customer payment.
    const price = await stripeRequest("prices/" + encodeURIComponent(STRIPE_PRICE_ID));
    if (!verifyPrice(price, STRIPE_LIVE, STRIPE_PRICE_ID, STRIPE_PRODUCT_ID)) throw new Error("Stripe offer identity mismatch");
    const proof = issueProof();
    const form = new URLSearchParams();
    form.set("mode", "payment");
    form.set("line_items[0][price]", STRIPE_PRICE_ID);
    form.set("line_items[0][quantity]", "1");
    form.set("client_reference_id", "nija_game_" + randomUUID());
    form.set("success_url", BASE_URL + "/?session_id={CHECKOUT_SESSION_ID}");
    form.set("cancel_url", BASE_URL + "/?cancelled=1");
    form.set("metadata[version]", VERSION);
    form.set("metadata[answers]", data.answers.join(","));
    form.set("metadata[offer]", OFFER);
    form.set("metadata[product]", STRIPE_PRODUCT_ID);
    form.set("metadata[price]", STRIPE_PRICE_ID);
    form.set("metadata[proof_sha256]", hashProof(proof));
    const session = await stripeRequest("checkout/sessions", { body: form });
    const target = new URL(session.url || "https://invalid.example");
    if (!SESSION_ID.test(session.id || "") || session.livemode !== STRIPE_LIVE ||
        session.mode !== "payment" || target.protocol !== "https:" ||
        (target.hostname !== "checkout.stripe.com" && !target.hostname.endsWith(".checkout.stripe.com"))) {
      throw new Error("Unexpected checkout response");
    }
    // No proof in URLs, response bodies, logs, or browser-accessible JS.
    res.setHeader("Set-Cookie", issueCookie(proof, SECURE_COOKIE));
    return json(res, 200, { url: session.url });
  } catch {
    return json(res, 502, { error: "Checkout unavailable. Please retry or play for free." });
  }
}
async function results(url, req, res) {
  if (!CHECKOUT_READY) return json(res, 503, { error: "Results verification is unavailable." });
  const id = url.searchParams.get("session_id");
  if (!SESSION_ID.test(id || "")) return json(res, 400, { error: "Invalid checkout reference." });
  const proof = readProof(req.headers.cookie, SECURE_COOKIE);
  if (!proof) return json(res, 403, { error: "Use the original purchasing browser to access this report." });
  try {
    const session = await stripeRequest("checkout/sessions/" + encodeURIComponent(id) +
      "?expand%5B%5D=payment_intent.latest_charge");
    const lines = await stripeRequest("checkout/sessions/" + encodeURIComponent(id) + "/line_items?limit=5");
    if (!verifyPurchase(session, lines, proof, STRIPE_LIVE, id, STRIPE_PRICE_ID, STRIPE_PRODUCT_ID)) {
      return json(res, 403, { error: "A verified, unreversed $1 purchase from this browser is required." });
    }
    const raw = session.metadata?.answers;
    if (!/^([012],){5}[012]$/.test(raw || "")) {
      return json(res, 422, { error: "Results data unavailable. Contact support with your receipt." });
    }
    return json(res, 200, { report: scoreReport(raw.split(",").map(Number)) });
  } catch {
    return json(res, 502, { error: "Could not verify this payment. Retain your receipt and retry." });
  }
}
async function handle(req, res) {
  setHeaders(res);
  const url = new URL(req.url || "/", "http://local");
  if (url.pathname === "/api/health" && req.method === "GET") {
    return json(res, 200, { status: "ready", checkoutConfigured: CHECKOUT_READY });
  }
  if (url.pathname === "/api/checkout" && req.method === "POST") return checkout(req, res);
  if (url.pathname === "/api/results" && req.method === "GET") return results(url, req, res);
  if (req.method !== "GET" && req.method !== "HEAD") return json(res, 405, { error: "Method not allowed." });
  const file = approvedFiles[url.pathname];
  if (!file) return json(res, 404, { error: "Not found." });
  try {
    const buffer = await fs.readFile(path.join(publicDir, file[0]));
    res.writeHead(200, { "Content-Type": file[1] });
    res.end(req.method === "HEAD" ? undefined : buffer);
  } catch { json(res, 500, { error: "Asset unavailable." }); }
}
const server = http.createServer((req, res) => {
  handle(req, res).catch(() => { if (!res.headersSent) json(res, 500, { error: "Internal server error." }); else res.end(); });
});
if (process.env.NODE_ENV !== "test" && !process.env.VERCEL) {
  server.listen(PORT, "0.0.0.0", () => console.log("NIJA Trading IQ listening on port", PORT));
}
export { server, handle };
