import { createHmac, timingSafeEqual } from "node:crypto";

/**
 * Verify Stripe's signed raw webhook payload without parsing or mutating bytes.
 * Return a parsed event only after signature and timestamp validation.
 * This is a verification primitive, not a fulfillment handler.
 */
export function verifyStripeWebhook(rawBody, signatureHeader, secret, nowSeconds = Math.floor(Date.now() / 1000)) {
  if (!Buffer.isBuffer(rawBody) || rawBody.length === 0 || rawBody.length > 262144) throw new Error("Invalid webhook body");
  if (typeof secret !== "string" || !secret.startsWith("whsec_") || secret.length < 12) throw new Error("Webhook secret unavailable");
  if (typeof signatureHeader !== "string" || signatureHeader.length > 4096) throw new Error("Missing signature");
  const parts = signatureHeader.split(",");
  let timestamp = null;
  const signatures = [];
  for (const part of parts) {
    const match = /^(t|v1)=([^,]+)$/.exec(part.trim());
    if (!match) continue;
    if (match[1] === "t" && timestamp === null && /^\d{1,16}$/.test(match[2])) timestamp = Number(match[2]);
    if (match[1] === "v1" && /^[a-f0-9]{64}$/.test(match[2])) signatures.push(Buffer.from(match[2], "hex"));
  }
  if (!Number.isSafeInteger(timestamp) || !Number.isSafeInteger(nowSeconds) ||
      Math.abs(nowSeconds - timestamp) > 300 || signatures.length === 0) throw new Error("Invalid webhook timestamp or signature");
  const expected = createHmac("sha256", secret).update(String(timestamp)).update(".").update(rawBody).digest();
  if (!signatures.some(sig => timingSafeEqual(sig, expected))) throw new Error("Webhook signature mismatch");
  let event;
  try { event = JSON.parse(rawBody.toString("utf8")); } catch { throw new Error("Malformed webhook JSON"); }
  if (!event || typeof event !== "object" || typeof event.id !== "string" ||
      !/^evt_[A-Za-z0-9_]+$/.test(event.id) || typeof event.type !== "string" ||
      !event.data || typeof event.data !== "object") throw new Error("Invalid webhook event");
  return event;
}
