import test from "node:test";
import assert from "node:assert/strict";

process.env.NODE_ENV = "test";
process.env.PUBLIC_BASE_URL = "http://localhost:8787";
process.env.STRIPE_SECRET_KEY = "sk_test_unit_not_real";
process.env.NIJA_REPORT_CHECKOUT_ENABLED = "true";
process.env.NIJA_GAME_TEST_PRICE_ID = "price_1UY9YmI0gfJjTf3E1h6mYC2S"; // mocked only
process.env.NIJA_GAME_TEST_PRODUCT_ID = "prod_VZI9N8jDpFrQMt"; // mocked only
const { handle, server } = await import("../server/index.mjs");

const realFetch = globalThis.fetch;
const priceId = "price_1UY9YmI0gfJjTf3E1h6mYC2S";
const productId = "prod_VZI9N8jDpFrQMt";
const sessionId = "cs_test_abcdefgh12345678";
let stripePaymentStatus = "unpaid";
let stripeRefunded = false;
let metadataAnswers = "2,2,1,0,1,1";
let receiptHash = "";
let receiptCookie = "";
let stripeCalls = [];
globalThis.fetch = async (input, options = {}) => {
  const url = String(input);
  if (url.startsWith("https://api.stripe.com/v1/")) {
    stripeCalls.push({ url, options });
    if (url.endsWith("/prices/" + priceId)) {
      return Response.json({ id: priceId, product: productId, active: true,
        livemode: false, type: "one_time", currency: "usd", unit_amount: 100 });
    }
    if (url.endsWith("/checkout/sessions") && options.method === "POST") {
      const body = new URLSearchParams(options.body);
      receiptHash = body.get("metadata[proof_sha256]");
      return Response.json({ id: sessionId, livemode: false, mode: "payment",
        url: "https://checkout.stripe.com/c/pay/fictional_unit_test" });
    }
    if (url.includes("/line_items")) {
      return Response.json({ data: [{ quantity: 1,
        price: { id: priceId, product: productId },
        amount_total: 100, currency: "usd" }] });
    }
    return Response.json({
      id: sessionId, livemode: false, status: "complete",
      payment_status: stripePaymentStatus, mode: "payment", currency: "usd",
      amount_total: 100,
      metadata: { version: "nija-trading-iq-v1", answers: metadataAnswers,
        offer: "nija-trading-iq-results-v1", product: productId,
        price: priceId, proof_sha256: receiptHash },
      payment_intent: { status: "succeeded", amount_received: 100, currency: "usd",
        latest_charge: { paid: true, status: "succeeded", refunded: stripeRefunded,
          disputed: false, amount_refunded: stripeRefunded ? 100 : 0 } }
    });
  }
  return realFetch(input, options);
};
const start = await new Promise((resolve) => server.listen(0, "127.0.0.1", () => resolve(server.address().port)));
const origin = "http://127.0.0.1:" + start;
const post = (body, requestOrigin = "http://localhost:8787", extraHeaders = {}) => realFetch(origin + "/api/checkout", {
  method: "POST",
  headers: { "Content-Type": "application/json", Origin: requestOrigin, ...extraHeaders },
  body: JSON.stringify(body)
});
const postParsedBody = async (body) => {
  let status;
  let content;
  const response = {
    setHeader() {},
    writeHead(code) { status = code; },
    end(value) { content = value; }
  };
  await handle({
    method: "POST",
    url: "/api/checkout",
    headers: { origin: "http://localhost:8787" },
    socket: { remoteAddress: "192.0.2.50" },
    body
  }, response);
  return { status, body: JSON.parse(content) };
};

async function freshReceiptCookie() {
  const response = await post({ version: "nija-trading-iq-v1", answers: [2,2,1,0,1,1] });
  assert.equal(response.status, 200);
  const cookie = response.headers.get("set-cookie")?.split(";")[0] || "";
  assert.match(cookie, /^nija-iq-report-local=[a-f0-9]{64}$/);
  return cookie;
}

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
  receiptCookie = response.headers.get("set-cookie")?.split(";")[0] || "";
  assert.match(receiptCookie, /^nija-iq-report-local=[a-f0-9]{64}$/);
  const last = stripeCalls.at(-1);
  const params = new URLSearchParams(last.options.body);
  assert.equal(params.get("mode"), "payment");
  assert.equal(params.get("line_items[0][price]"), priceId);
  assert.match(params.get("metadata[proof_sha256]"), /^[a-f0-9]{64}$/);
  assert.equal(params.get("metadata[offer]"), "nija-trading-iq-results-v1");
  assert.equal(params.get("metadata[answers]"), "2,2,1,0,1,1");
  assert.equal(params.get("metadata[version]"), "nija-trading-iq-v1");
});
test("checkout accepts parsed request bodies and retains the size limit", async () => {
  const accepted = await postParsedBody({ version: "nija-trading-iq-v1", answers: [2,2,1,0,1,1] });
  assert.equal(accepted.status, 200);
  const oversized = await postParsedBody({
    version: "nija-trading-iq-v1", answers: [2,2,1,0,1,1], extra: "x".repeat(4096)
  });
  assert.equal(oversized.status, 400);
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
  const cookie = await freshReceiptCookie();
  const response = await realFetch(origin + "/api/results?session_id=" + sessionId,
    { headers: { Cookie: cookie } });
  assert.equal(response.status, 403);
  assert.equal((await response.json()).report, undefined);
});
test("the paid result is computed from Stripe's server-side metadata", async () => {
  stripePaymentStatus = "paid";
  metadataAnswers = "2,2,1,0,1,1";
  const cookie = await freshReceiptCookie();
  const response = await realFetch(origin + "/api/results?session_id=" + sessionId,
    { headers: { Cookie: cookie } });
  assert.equal(response.status, 200);
  const data = await response.json();
  assert.equal(data.report.score, 100);
  assert.equal(data.report.decisions.length, 6);
  assert.equal(response.headers.get("cache-control"), "no-store");
});
test("invalid metadata cannot be converted into a paid report", async () => {
  stripePaymentStatus = "paid";
  metadataAnswers = "2,2,1,0,1,9";
  const cookie = await freshReceiptCookie();
  const response = await realFetch(origin + "/api/results?session_id=" + sessionId,
    { headers: { Cookie: cookie } });
  assert.equal(response.status, 422);
});
test("a shared Stripe receipt URL cannot unlock reports in another browser", async () => {
  stripePaymentStatus = "paid";
  metadataAnswers = "2,2,1,0,1,1";
  const missing = await realFetch(origin + "/api/results?session_id=" + sessionId);
  assert.equal(missing.status, 403);
  const wrong = await realFetch(origin + "/api/results?session_id=" + sessionId,
    { headers: { Cookie: "nija-iq-report-local=" + "f".repeat(64) } });
  assert.equal(wrong.status, 403);
});
test("a refunded purchase loses report access even if its browser proof matches", async () => {
  stripePaymentStatus = "paid";
  stripeRefunded = true;
  const cookie = await freshReceiptCookie();
  const response = await realFetch(origin + "/api/results?session_id=" + sessionId,
    { headers: { Cookie: cookie } });
  assert.equal(response.status, 403);
  stripeRefunded = false;
});
test.after(async () => {
  globalThis.fetch = realFetch;
  await new Promise((resolve) => server.close(resolve));
});
