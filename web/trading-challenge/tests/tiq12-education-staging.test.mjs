// Synthetic HTTP safety tests; no Stripe, IONOS or brokerage connectivity.
import test from "node:test";
import assert from "node:assert/strict";
import { createEducationStagingServer } from "../server/tiq12-education-staging.mjs";

async function withServer(check) {
  const server = createEducationStagingServer({
    NIJA_TIQ12_ENABLED: "false",
    NIJA_TIQ12_MODE: "holding"
  });
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  const address = server.address();
  try {
    await check("http://127.0.0.1:" + address.port);
  } finally {
    await new Promise((resolve, reject) =>
      server.close(error => error ? reject(error) : resolve()));
  }
}

test("TIQ12 education staging stays disabled even with a valid HTTP request", async () => {
  await withServer(async origin => {
    const response = await fetch(origin + "/healthz");
    assert.equal(response.status, 200);
    assert.equal(response.headers.get("cache-control"), "no-store");
    assert.equal(response.headers.get("access-control-allow-origin"), null);
    const status = await response.json();
    assert.equal(status.product, "nija-trading-iq-12");
    assert.equal(status.status, "holding");
    assert.equal(status.canonical_source_verified, false);
    assert.equal(status.storage_certified, false);
    assert.equal(status.checkout_available, false);
    assert.equal(status.live_payments, false);
    assert.equal(status.trading_enabled, false);
  });
});

test("readiness and every payment/game route fail closed", async () => {
  await withServer(async origin => {
    const paths = ["/readyz", "/api/game/runs", "/game/checkout",
                   "/stripe/webhook", "/checkout", "/report", "/admin/analytics"];
    for (const path of paths) {
      const result = await fetch(origin + path);
      assert.equal(result.status, 503, "Expected 503 for " + path);
    }
    const post = await fetch(origin + "/game/checkout", { method: "POST",
      headers: { "Content-Type": "application/json" }, body: "{}" });
    assert.equal(post.status, 503);
    const ordinary = await fetch(origin + "/favicon.ico");
    assert.equal(ordinary.status, 404);
  });
});

test("an attempted flag/config activation is rejected at startup", () => {
  const blocked = [
    { NIJA_TIQ12_ENABLED: "true", NIJA_TIQ12_MODE: "holding" },
    { NIJA_TIQ12_ENABLED: "1", NIJA_TIQ12_MODE: "holding" },
    { NIJA_TIQ12_ENABLED: "false", NIJA_TIQ12_MODE: "test" },
    { NIJA_TIQ12_ENABLED: "false", NIJA_TIQ12_MODE: "live" }
  ];
  for (const config of blocked) {
    assert.throws(() => createEducationStagingServer(config), /cannot be enabled/);
  }
  const server = createEducationStagingServer({});
  assert.ok(server); // never started; no socket or external provider connection
});
