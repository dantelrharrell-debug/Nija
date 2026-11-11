import test from "node:test";
import assert from "node:assert/strict";
import { createHmac } from "node:crypto";
import { verifyStripeWebhook } from "../server/stripe-webhook-verify.mjs";
const secret = "whsec_local_test_secret";
const now = 1794430000;
const payload = Buffer.from(JSON.stringify({ id: "evt_test_123", type: "checkout.session.completed", data: { object: { id: "cs_test_123" } } }));
const signed = (body, timestamp = now) => "t=" + timestamp + ",v1=" + createHmac("sha256", secret).update(String(timestamp)).update(".").update(body).digest("hex");
test("valid signed event is accepted", () => {
  assert.equal(verifyStripeWebhook(payload, signed(payload), secret, now).id, "evt_test_123");
});
test("tampered body is rejected", () => {
  assert.throws(() => verifyStripeWebhook(Buffer.concat([payload, Buffer.from(" ")]), signed(payload), secret, now));
});
test("stale and future events are rejected", () => {
  assert.throws(() => verifyStripeWebhook(payload, signed(payload, now - 301), secret, now));
  assert.throws(() => verifyStripeWebhook(payload, signed(payload, now + 301), secret, now));
});
test("missing or malformed signatures are rejected", () => {
  for (const header of ["", "t=" + now, "t=" + now + ",v1=bad"]) {
    assert.throws(() => verifyStripeWebhook(payload, header, secret, now));
  }
});
test("invalid signed JSON and event envelope are rejected", () => {
  for (const raw of [Buffer.from("not json"), Buffer.from("{}")]) {
    assert.throws(() => verifyStripeWebhook(raw, signed(raw), secret, now));
  }
});
test("payload limit enforced", () => {
  const large = Buffer.alloc(262145, 97);
  assert.throws(() => verifyStripeWebhook(large, signed(large), secret, now));
});
