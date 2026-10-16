const { test } = require("node:test");
const assert = require("node:assert/strict");

const transport = import("../web/member/memberBrokerApi.mjs");

test("readiness distinguishes verification from new credential intake", async t => {
  const api = await transport;
  t.mock.method(globalThis, "fetch", async (url, options) => {
    assert.equal(url, "https://nija-member-broker-api.onrender.com/readyz");
    assert.equal(options.cache, "no-store");
    assert.equal(options.credentials, "omit");
    assert.equal(options.redirect, "error");
    return { ok: true, json: async () => ({
      status: "ready", credential_intake_enabled: false, verification_enabled: true,
    }) };
  });
  assert.deepEqual(await api.brokerReadiness(), { intake: false, verification: true });
});

test("verification sends only scope and an in-memory bearer, never keys or owner IDs", async t => {
  const api = await transport;
  let calls = 0;
  t.mock.method(globalThis, "fetch", async (url, options) => {
    calls++;
    assert.equal(url, "https://nija-member-broker-api.onrender.com/api/member/brokers/verify");
    assert.equal(options.method, "POST");
    assert.equal(options.headers.Authorization, "Bearer " + "synthetic-member-token");
    assert.deepEqual(JSON.parse(options.body), { broker: "kraken", environment: "live" });
    assert.equal(options.cache, "no-store");
    assert.equal(options.credentials, "omit");
    assert.equal(options.redirect, "error");
    return { ok: true, json: async () => ({
      broker: "kraken", environment: "live", credentials_stored: true,
      broker_verified: true, membership_access: true, trading_authorized: false,
    }) };
  });
  assert.equal(await api.verifyStoredKraken("synthetic-member-token", "live"), true);
  assert.equal(calls, 1);
});

test("missing authentication and paper scope never make network requests", async t => {
  const api = await transport;
  const fetch = t.mock.method(globalThis, "fetch", async () => { throw new Error("must not call"); });
  await assert.rejects(api.verifyStoredKraken("", "live"));
  await assert.rejects(api.storedBrokerConnections(""));
  await assert.rejects(api.verifyStoredKraken("synthetic-member-token", "paper"));
  assert.equal(fetch.mock.callCount(), 0);
});

test("storage, membership, and trading authorization cannot masquerade as verification", async t => {
  const api = await transport;
  let body = {};
  t.mock.method(globalThis, "fetch", async () => ({ ok: true, json: async () => body }));
  const success = {
    broker: "kraken", environment: "live", credentials_stored: true,
    broker_verified: true, membership_access: true, trading_authorized: false,
  };
  for (const change of [
    { broker_verified: false }, { broker_verified: "true" }, { credentials_stored: false },
    { membership_access: false }, { trading_authorized: true }, { broker: "alpaca" },
    { environment: "paper" },
  ]) {
    body = { ...success, ...change };
    await assert.rejects(api.verifyStoredKraken("synthetic-member-token", "live"));
  }
});

test("readiness and authentication/provider failures remain unavailable", async t => {
  const api = await transport;
  let status = 503;
  t.mock.method(globalThis, "fetch", async () => ({
    ok: false, status, json: async () => { throw new Error("must not inspect failed response"); },
  }));
  await assert.rejects(api.brokerReadiness());
  for (status of [401, 403, 502, 503]) {
    await assert.rejects(api.verifyStoredKraken("synthetic-member-token", "live"));
    await assert.rejects(api.storedBrokerConnections("synthetic-member-token"));
  }
});

test("metadata transport keeps only storage labels, never persisted verification or secrets", async t => {
  const api = await transport;
  t.mock.method(globalThis, "fetch", async () => ({
    ok: true, json: async () => ({ connections: [{
      broker: "kraken", environment: "live", credentials_stored: true,
      broker_verified: true, ciphertext: "synthetic-ciphertext", balances: { ZUSD: "sensitive" },
    }] }),
  }));
  assert.deepEqual(await api.storedBrokerConnections("synthetic-member-token"), [{
    broker: "kraken", environment: "live", credentials_stored: true,
  }]);
});
