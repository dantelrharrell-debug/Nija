import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const html = readFileSync(new URL("../public/index.html", import.meta.url), "utf8");
const app = readFileSync(new URL("../public/app.js", import.meta.url), "utf8");

test("legacy short game is explicitly identified as separate from canonical 72-decision challenge", () => {
  assert.match(html, /six-moment fictional-market practice experience/i);
  assert.match(html, /72-decision Trading IQ Challenge/i);
  assert.match(html, /separate from NIJA/i);
});

test("progressbar has accessible semantics and its value is updated during play", () => {
  assert.match(html, /role="progressbar" aria-label="Challenge completion" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0"/);
  const updates = app.match(/parentElement\.setAttribute\("aria-valuenow", String\(progress\)\)/g) || [];
  assert.equal(updates.length, 2);
});

test("checkout availability remains runtime gated and is not silently activated", () => {
  assert.match(app, /checkoutReady = data\.checkoutConfigured === true/);
  assert.match(app, /el\("unlock"\)\.disabled = !ready/);
});
