import test from "node:test";
import assert from "node:assert/strict";

process.env.NODE_ENV = "test";
process.env.PUBLIC_BASE_URL = "http://localhost:8787";
process.env.STRIPE_SECRET_KEY = "sk_test_unit_not_real";
const { server } = await import("../server/index.mjs");

const realFetch = globalThis.fetch;
let stripePaymentStatus = "unpaid";
let metadataAnswers = "2,2,1,0,1,1";
let stripeCalls = [];
globalThis.fetch = async (input, options = {}) => {
  const url = String(input);
  if (url.startsWith("https://api.stripe.com/v1/")) {
    stripeCalls.push({ url, options });
    if (url.endsWith("/checkout/sessions") && options.method === "POST") {
      return Response.json({ url: "https://checkout.stripe.com/c/pay/fictional_unit_test" });
    }
    return Response.json({
      payment_status: stripePaymentStatus,
      mode: "payment",
      currency: "usd",
      amount_total: 100,
      metadata: { version: "nija-trading-iq-v1", answers: metadataAnswers }
    });
  }
  return realFetch(input, options);
};
const start = await new Promise((resolve) => server.listen(0, "127.0.0.1", () => resolve(server.address().port)));
const origin = "http://127.0.0.1:" + start;
const sessionId = "cs_test_abcdefgh12345678";
const post = (body, requestOrigin = "http://localhost:8787", extraHeaders = {}) => realFetch(origin + "/api/checkout", {
  method: "POST",
  headers: { "Content-Type": "application/json", Origin: requestOrigin, ...extraHeaders },
  body: JSON.stringify(body)
});

test("static game loads with protective headers and does not expose paid report", async () => {
  const response = await realFetch(origin + "/");
  assert.equal(response.status, 200);
  assert.match(await response.text(), /NIJA Trading IQ/);
  assert.match(response.headers.get("content-security-policy"), /frame-ancestors 'none'/);
  assert.equal((await realFetch(origin + "/server/scoring.mjs")).status, 404);
  assert.equal((await realFetch(origin + "/api/results")).status, 400);
});
test("cross-origin and invalid submissions are denied before Stripe", async () => {
  const before = stripeCalls.length;
  const denied = await post({ version: "nija-trading-iq-v1", answers: [2,2,1,0,1,1] }, "https://malicious.invalid");
  assert.equal(denied.status, 403);
  const incomplete = await post({ version: "nija-trading-iq-v1", answers: [2] });
  assert.equal(incomplete.status, 400);
  assert.equal(stripeCalls.length, before);
});
test("checkout is for one dollar with no subscription and metadata choices", async () => {
  const response = await post({ version: "nija-trading-iq-v1", answers: [2,2,1,0,1,1] });
  assert.equal(response.status, 200);
  assert.match((await response.json()).url, /^https:\/\/checkout\.stripe\.com\//);
  const last = stripeCalls.at(-1);
  const params = new URLSearchParams(last.options.body);
  assert.equal(params.get("mode"), "payment");
  assert.equal(params.get("line_items[0][price_data][unit_amount]"), "100");
  assert.equal(params.get("metadata[answers]"), "2,2,1,0,1,1");
  assert.equal(params.get("metadata[version]"), "nija-trading-iq-v1");
});
test("checkout rate limits by Vercel's trusted client IP", async () => {
  process.env.VERCEL = "1";
  const body = { version: "nija-trading-iq-v1", answers: [2,2,1,0,1,1] };
  for (let i = 0; i < 30; i++) {
    assert.equal((await post(body, undefined, { "x-vercel-forwarded-for": "198.51.100.10" })).status, 200);
  }
  assert.equal((await post(body, undefined, { "x-vercel-forwarded-for": "198.51.100.10" })).status, 429);
  assert.equal((await post(body, undefined, { "x-vercel-forwarded-for": "198.51.100.11" })).status, 200);
  delete process.env.VERCEL;
});
test("standalone deployments use forwarded IPs only with an explicit proxy-hop count", async () => {
  process.env.TRUSTED_PROXY_HOPS = "1";
  const body = { version: "nija-trading-iq-v1", answers: [2,2,1,0,1,1] };
  for (let i = 0; i < 30; i++) {
    assert.equal((await post(body, undefined, { "x-forwarded-for": "198.51.100.20" })).status, 200);
  }
  assert.equal((await post(body, undefined, { "x-forwarded-for": "198.51.100.20" })).status, 429);
  assert.equal((await post(body, undefined, { "x-forwarded-for": "198.51.100.21" })).status, 200);
  delete process.env.TRUSTED_PROXY_HOPS;
});
test("an unpaid Stripe session cannot unlock results", async () => {
  stripePaymentStatus = "unpaid";
  const response = await realFetch(origin + "/api/results?session_id=" + sessionId);
  assert.equal(response.status, 403);
  assert.equal((await response.json()).report, undefined);
});
test("the paid result is computed from Stripe's server-side metadata", async () => {
  stripePaymentStatus = "paid";
  metadataAnswers = "2,2,1,0,1,1";
  const response = await realFetch(origin + "/api/results?session_id=" + sessionId);
  assert.equal(response.status, 200);
  const data = await response.json();
  assert.equal(data.report.score, 100);
  assert.equal(data.report.decisions.length, 6);
  assert.equal(response.headers.get("cache-control"), "no-store");
});
test("invalid metadata cannot be converted into a paid report", async () => {
  stripePaymentStatus = "paid";
  metadataAnswers = "2,2,1,0,1,9";
  const response = await realFetch(origin + "/api/results?session_id=" + sessionId);
  assert.equal(response.status, 422);
});
test.after(async () => {
  globalThis.fetch = realFetch;
  await new Promise((resolve) => server.close(resolve));
});
