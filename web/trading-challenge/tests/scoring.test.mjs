import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { validAnswers, scoreReport, VERSION } from "../server/scoring.mjs";

test("every assessment requires exactly six valid selections", () => {
  assert.equal(validAnswers([2,2,1,0,1,1]), true);
  for (const invalid of [[], [0,0,0,0,0], [0,0,0,0,0,3], [0,0,0,0,0,-1], [0,0,0,0,0,"2"], null]) {
    assert.equal(validAnswers(invalid), false);
    assert.throws(() => scoreReport(invalid), TypeError);
  }
});
test("ideal choices score a perfect 100 with a full narrative", () => {
  const report = scoreReport([2,2,1,0,1,1]);
  assert.equal(report.score, 100);
  assert.equal(report.version, VERSION);
  assert.equal(report.decisions.length, 6);
  assert.equal(report.dimensions.length, 3);
  assert.equal(report.dimensions.every((v) => v.score === 100), true);
  assert.ok(report.nextStep);
});
test("worst choices cannot score or overflow and are bounded", () => {
  const report = scoreReport([0,0,0,1,0,0]);
  assert.equal(report.score, 0);
  assert.equal(report.decisions.reduce((sum, d) => sum + d.points, 0), 0);
  assert.ok(report.dimensions.every(d => Number.isInteger(d.score) && d.score >= 0 && d.score <= 100));
});
test("the public game bundle does not contain paid scoring formulas", async () => {
  const root = path.dirname(fileURLToPath(import.meta.url));
  const source = await fs.readFile(path.resolve(root, "../public/scenarios.js"), "utf8");
  assert.doesNotMatch(source, /points\s*:/);
  assert.doesNotMatch(source, /lesson\s*:/);
  assert.doesNotMatch(source, /scoreReport/);
});
test("live trading APIs and broker integrations are not imported by the new game", async () => {
  const root = path.dirname(fileURLToPath(import.meta.url));
  const source = await fs.readFile(path.resolve(root, "../server/index.mjs"), "utf8");
  assert.doesNotMatch(source, /KRAKEN_API_KEY|COINBASE_API_KEY|OKX_API_KEY|FORCE_TRADE/);
  assert.doesNotMatch(source, /bot\/|api_server\.py|\bbroker\b/);
});
