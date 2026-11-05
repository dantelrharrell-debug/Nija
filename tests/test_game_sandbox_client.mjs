import test from "node:test";
import assert from "node:assert/strict";
import { SandboxReportClient } from "../game_sandbox/client.mjs";

const RUN = "a".repeat(48);
const CSRF = "b".repeat(64);
const storageKey = "nija-iq-sandbox-last-run-v1";

function storageMock() {
  const entries = new Map();
  return {
    entries,
    getItem: key => entries.has(key) ? entries.get(key) : null,
    setItem: (key, value) => entries.set(key, value),
    removeItem: key => entries.delete(key),
  };
}
async function stubbed(storage, callback, response) {
  const oldFetch = globalThis.fetch;
  const oldStorage = Object.getOwnPropertyDescriptor(globalThis, "localStorage");
  const calls = [];
  try {
    Object.defineProperty(globalThis, "localStorage", {
      configurable: true, writable: true, value: storage
    });
    globalThis.fetch = async (url, options) => {
      calls.push({ url, options });
      return response(url, options);
    };
    await callback(calls);
  } finally {
    globalThis.fetch = oldFetch;
    if (oldStorage) Object.defineProperty(globalThis, "localStorage", oldStorage);
    else delete globalThis.localStorage;
  }
}
const json = (value, status = 200) => ({
  ok: status >= 200 && status < 300,
  status,
  json: async () => value,
});

test("starting sandbox run persists only an opaque ID, not CSRF or payment credentials", async () => {
  const storage = storageMock();
  await stubbed(storage, async calls => {
    const client = new SandboxReportClient();
    assert.equal(await client.start(true), RUN);
    assert.equal(storage.getItem(storageKey), RUN);
    assert.deepEqual([...storage.entries.keys()], [storageKey]);
    assert.equal(storage.getItem(storageKey).includes(CSRF), false);
    assert.equal(calls.length, 1);
    assert.equal(calls[0].url, "/sandbox/runs");
    assert.equal(calls[0].options.credentials, "same-origin");
    assert.equal(calls[0].options.method, "POST");
  }, () => json({ run_id: RUN, csrf: CSRF }));
});

test("returning buyer resumes owned run with server verification, without creating checkout", async () => {
  const storage = storageMock();
  storage.setItem(storageKey, RUN);
  await stubbed(storage, async calls => {
    const client = new SandboxReportClient();
    assert.equal(client.savedRunId(), RUN);
    assert.equal(await client.resumeSaved(), true);
    assert.equal(client.runId, RUN);
    assert.equal(client.csrf, CSRF);
    assert.deepEqual(calls.map(c => c.url), ["/sandbox/runs/" + RUN + "/resume"]);
    assert.equal(calls[0].options.method, "POST");
    assert.equal(calls[0].options.credentials, "same-origin");
  }, () => json({ run_id: RUN, csrf: CSRF }));
});

test("a different browser cannot use the saved run ID alone", async () => {
  const storage = storageMock();
  storage.setItem(storageKey, RUN);
  await stubbed(storage, async calls => {
    const client = new SandboxReportClient();
    await assert.rejects(client.resumeSaved(), /ownership_required/);
    assert.equal(client.runId, null);
    assert.equal(client.csrf, null);
    assert.deepEqual(calls.map(c => c.url), ["/sandbox/runs/" + RUN + "/resume"]);
  }, () => json({ error: "ownership_required" }, 403));
});

test("malformed local run IDs never touch the payment API", async () => {
  const storage = storageMock();
  storage.setItem(storageKey, "cs_test_should_not_be_a_run");
  await stubbed(storage, async calls => {
    const client = new SandboxReportClient();
    assert.equal(client.savedRunId(), null);
    assert.equal(await client.resumeSaved(), false);
    assert.equal(calls.length, 0);
  }, () => { throw Error("No API call expected"); });
});

test("storage-disabled clients can start without exposing a CSRF token", async () => {
  const storage = {
    getItem() { throw Error("storage denied"); },
    setItem() { throw Error("storage denied"); },
    removeItem() { throw Error("storage denied"); }
  };
  await stubbed(storage, async calls => {
    const client = new SandboxReportClient();
    assert.equal(await client.start(true), RUN);
    assert.equal(client.savedRunId(), null);
    assert.equal(await client.resumeSaved(), false);
    client.clearSavedRun();
    assert.equal(calls.length, 1);
  }, () => json({ run_id: RUN, csrf: CSRF }));
});

test("failed server report entitlement stays locked; no checkout fallback", async () => {
  const storage = storageMock();
  storage.setItem(storageKey, RUN);
  await stubbed(storage, async calls => {
    const client = new SandboxReportClient();
    assert.equal(await client.resumeSaved(), true);
    await assert.rejects(client.report(), /verified_webhook_required/);
    assert.deepEqual(calls.map(c => c.url), [
      "/sandbox/runs/" + RUN + "/resume",
      "/sandbox/runs/" + RUN + "/report",
    ]);
    assert.equal(calls[1].options.method, "GET");
  }, url => url.endsWith("/report")
    ? json({ error: "verified_webhook_required" }, 403)
    : json({ run_id: RUN, csrf: CSRF }));
});

test("unexpected server receipt does not authorize a run or persist it", async () => {
  const storage = storageMock();
  await stubbed(storage, async () => {
    const client = new SandboxReportClient();
    await assert.rejects(client.start(true), /invalid_run_receipt/);
    assert.equal(client.runId, null);
    assert.equal(storage.getItem(storageKey), null);
  }, () => json({ run_id: "bad", csrf: CSRF }));
});


test("published 72-decision bridge preserves ordered challenges without client scores", async () => {
  const storage = storageMock();
  // Distinct challenge histories: no 12-decision repeating pattern can hide
  // a dropped, duplicated, or reordered challenge in the browser bridge.
  const decisions = Array.from({length: 72}, (_, i) => ({
    action: ["buy", "sell", "hold"][(i * 7 + Math.floor(i / 12) + Math.floor(i / 5)) % 3],
    stop: (i * 11 + Math.floor(i / 12) * 3) % 7 < 3,
    portfolio: 10000 + i,
    clientScore: 99
  }));
  await stubbed(storage, async calls => {
    const client = new SandboxReportClient();
    await client.start(true);
    await client.completePublishedGame({ mode: "daily", level: "advanced", dayNum: 20762, decisions });
    const complete = calls.find(c => c.url.endsWith("/complete"));
    assert.ok(complete, "server completion request required");
    const {answers} = JSON.parse(complete.options.body);
    assert.deepEqual(Object.keys(answers).sort(), ["challenges", "dayNum", "level", "mode"]);
    assert.equal(answers.challenges.length, 6);
    assert.ok(answers.challenges.every(challenge => challenge.length === 12));
    // Every decision in every challenge must match the original sequence,
    // not only its endpoints or the number of decisions.
    const expected = decisions.map(({action, stop}) => ({action, stop}));
    assert.equal(new Set(answers.challenges.map(JSON.stringify)).size, 6);
    assert.deepEqual(answers.challenges.flat(), expected);
    assert.equal(JSON.stringify(answers).includes("clientScore"), false);
    assert.equal(JSON.stringify(answers).includes("portfolio"), false);
    assert.equal(answers.dayNum, 20762);

    await assert.rejects(
      client.completePublishedGame({mode: "daily", level: "advanced", dayNum: 20762, decisions: decisions.slice(0, 71)}),
      /complete_72_decisions_first/
    );
    assert.equal(calls.filter(c => c.url.endsWith("/complete")).length, 1);
  }, url => url.endsWith("/complete")
    ? json({completed: true})
    : json({run_id: RUN, csrf: CSRF}));
});
