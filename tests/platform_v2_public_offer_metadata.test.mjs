import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const seo = readFileSync(new URL("../web/trading-challenge/v515/src/lib/seo.js", import.meta.url), "utf8");

function routeMetadata(route) {
  const key = JSON.stringify(route) + ": { title: ";
  const line = seo.split("\\n").find((entry) => entry.includes(key));
  assert.ok(line, "route metadata exists: " + route);
  return line;
}

test("free pilot metadata does not advertise starting a paid membership", () => {
  const entry = routeMetadata("/apply");
  assert.match(entry, /free early-access feedback pilot/i);
  assert.match(entry, /starts no trial or subscription/i);
  assert.doesNotMatch(entry, /Start with a 14-day free trial/i);
});

test("pricing describes Founding 100 as planned and identifies the free waitlist", () => {
  const entry = routeMetadata("/pricing");
  assert.match(entry, /planned Founding 100/i);
  assert.match(entry, /free waitlist does not charge/i);
});

test("start-beta metadata cannot imply enrollment is open", () => {
  const entry = routeMetadata("/start-beta");
  assert.match(entry, /Paid enrollment is not open/i);
  assert.match(entry, /without starting a subscription/i);
});
