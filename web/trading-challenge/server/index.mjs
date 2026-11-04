import http from "node:http";
import fs from "node:fs/promises";
import path from "node:path";
import { isIP } from "node:net";
import { fileURLToPath } from "node:url";
import { randomUUID } from "node:crypto";
import { scoreReport, validAnswers, VERSION } from "./scoring.mjs";

const publicDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../public");
const PORT = Number(process.env.PORT || 8787);
const BASE_URL = (process.env.PUBLIC_BASE_URL || (process.env.VERCEL_URL ? "https://" + process.env.VERCEL_URL : "http://localhost:" + PORT)).replace(/\/$/, "");
const BASE_ORIGIN = new URL(BASE_URL).origin;
const STRIPE_SECRET_KEY = process.env.STRIPE_SECRET_KEY || "";
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
  if (!STRIPE_SECRET_KEY) return json(res, 503, { error: "Secure checkout is not configured yet." });
  if (req.headers.origin !== BASE_ORIGIN) return json(res, 403, { error: "Invalid request origin." });
  if (!rateLimit(req)) return json(res, 429, { error: "Too many attempts. Please try later." });
  let data;
  try { data = await bodyJSON(req); } catch { return json(res, 400, { error: "Invalid checkout request." }); }
  if (data.version !== VERSION || !validAnswers(data.answers)) return json(res, 400, { error: "Complete the six market decisions first." });
  const form = new URLSearchParams();
  form.set("mode", "payment");
  form.set("line_items[0][price_data][currency]", "usd");
  form.set("line_items[0][price_data][unit_amount]", "100");
  form.set("line_items[0][price_data][product_data][name]", "NIJA Trading IQ Personalized Report");
  form.set("line_items[0][quantity]", "1");
  form.set("client_reference_id", "nija_game_" + randomUUID());
  form.set("success_url", BASE_URL + "/?session_id={CHECKOUT_SESSION_ID}");
  form.set("cancel_url", BASE_URL + "/?cancelled=1");
  form.set("metadata[version]", VERSION);
  form.set("metadata[answers]", data.answers.join(","));
  try {
    const session = await stripeRequest("checkout/sessions", { body: form });
    if (!session.url || !session.url.startsWith("https://checkout.stripe.com/")) throw new Error("Unusable checkout URL");
    return json(res, 200, { url: session.url });
  } catch { return json(res, 502, { error: "Checkout unavailable. Please retry or play for free." }); }
}
async function results(url, res) {
  if (!STRIPE_SECRET_KEY) return json(res, 503, { error: "Results verification is unavailable." });
  const id = url.searchParams.get("session_id");
  if (!id || !/^cs_(test|live)_[A-Za-z0-9]{8,}$/.test(id)) return json(res, 400, { error: "Invalid checkout reference." });
  try {
    const session = await stripeRequest("checkout/sessions/" + encodeURIComponent(id));
    if (session.payment_status !== "paid" || session.mode !== "payment" ||
        session.currency !== "usd" || session.amount_total !== 100 ||
        session.metadata?.version !== VERSION) {
      return json(res, 403, { error: "A verified $1 purchase is required for this report." });
    }
    const raw = session.metadata?.answers;
    if (!/^([012],){5}[012]$/.test(raw || "")) return json(res, 422, { error: "Results data unavailable. Contact support with your receipt." });
    const answers = raw.split(",").map(Number);
    return json(res, 200, { report: scoreReport(answers) });
  } catch { return json(res, 502, { error: "Could not verify this payment. Retain your receipt and retry." }); }
}
async function handle(req, res) {
  setHeaders(res);
  const url = new URL(req.url || "/", "http://local");
  if (url.pathname === "/api/health" && req.method === "GET") {
    return json(res, 200, { status: "ready", checkoutConfigured: Boolean(STRIPE_SECRET_KEY) });
  }
  if (url.pathname === "/api/checkout" && req.method === "POST") return checkout(req, res);
  if (url.pathname === "/api/results" && req.method === "GET") return results(url, res);
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
