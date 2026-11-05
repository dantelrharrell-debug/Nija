// Cross-check the already-committed served IONOS billing adapter against the
// original preview-export engine/report supplied by the owner on 2026-11-05.
// These fingerprints are derived offline from tiq_engine.mjs and tiq_report.mjs
// in the private 219900-byte source-only ZIP. No customer records are present.
// This test is NOT proof that the latest preview is published or that payments work.
import test from "node:test";
import assert from "node:assert/strict";
import {createHash} from "node:crypto";
import {buildReport} from "./ionos_published_report.mjs";

// Order: standard then daily; beginner/intermediate/advanced;
// hold, alternate, cautious, varied.
const expected = [
  "9143c2f3d8ff80cd8f319259d89b41e2df4f9e1b86af34bc4d243d150848cdfe",
  "d5a21123e7228bb8393017a4ea77da69d8f98640ae23e73d6dc8d7ec4805cbce",
  "6441eac2feab23b98c269fb594abe21a259c238a1aaac67e595344780d45b1bd",
  "7b29d7942b6baa10da8872b9a74bbf10936eec7c93c74cf3480331f5e7bbb043",
  "128c35f8738ecbe164e9b961e743a25538038df6e2758f23982b96616c904514",
  "aa811ad7c1dfb4b92b01a5f02b7df50f38999919dc75bbbc2000694b3adef5a4",
  "2d433f1a487e0edc34da5d50e29c83a50f9c9188878b68e4086a0015f9080420",
  "2ed24db4f4a6c8314f818c623629d3c2ea4923efa2d53c4e9479ef7e590e919f",
  "566b97d0d7605f4d6ab7fb7cf3a24c9019d6c4a22a527808ba36fbbf88ca8e6e",
  "8c0bf13cb37285aec5e774577c2b12f076fd51d47eea7037a659c9b29ef19e70",
  "e627efc5debfe87a815b01ce99e22c7fa76bc0f144ff218be43f88706647a122",
  "56250e48044a9d3a0f8edda9cc71df72df88c5ea77d70ec070871824cea9bed5",
  "44043be717da9c26d33df2dcd549ea5c5bbafaec148ac85b4b5fcc47d6741f65",
  "6d8027793700a5842f5a34f4d8d422ec1c0bd6b238527e31822f13782c5b1a51",
  "0e889b36aab0dd8157db5b995694c46f3d496d31361bbddee893ff68bdf76502",
  "f1547de740c16f4d82cfcabd8be7164ddf906811ad4b5315e364fc1db1b145f2",
  "bb2a3497c2eb60f5c9e2bb4103c23c2e1c6a7f05e235bd2e52a9c20caac31242",
  "6ec7d39d0d9123a093b653ba4a9fcfe8ef2fdeeedc34ba4e093444ba51368227",
  "70c991ce776107c1bb736a865a21569a5130f794bc91223a3aacce89a3b7feb8",
  "50ac1d8665537d1ca804831a23aca1c7debd146eee3b71114da0bbc585a2c28d",
  "58f3beb72878bf0e5f6d58f7abd8b902be2b0865dd2b513788a4228bea4ae82d",
  "8d90e5216a81dfa113dc71c79f0dab6f333f81f01d8d34b72f15a25c07ee92d6",
  "e031ef627a16bc4fde84ab805e9731c8f66de97d86b2a26b93e17d666e59c17c",
  "fa691dc0fa43911213c77104ceedd61c0d912cb295be0331a7db7d796c72ea86",
];
function decisions(pattern) {
  return Array.from({length: 6}, (_, c) => Array.from({length: 12}, (_, i) => {
    if (pattern === "hold") return {action: "hold", stop: false};
    if (pattern === "alternate") return {action: i % 2 ? "sell" : "buy", stop: i % 3 === 0};
    if (pattern === "cautious") return {action: i === 0 ? "buy" : "hold", stop: true};
    const action = ["buy", "hold", "sell", "hold"][(i + 2 * c) % 4];
    return {action, stop: (i + c) % 3 === 0};
  }));
}
function fingerprint(report) {
  const normalized = {
    iq: report.tradingIQ,
    assessment: ["risk", "research", "discipline"].map(k => report.assessments[k].score),
    scores: report.challenges.map(c => c.score),
    decisions: report.challenges.flatMap(c => c.decisions).map(d => [
      d.round, d.action, d.stopArmed, d.held,
      d.priceBefore, d.priceAfter, d.movePct, d.lastMovePct,
      d.portfolio, d.stopFired, d.tone, d.head, d.text
    ]),
    lessons: report.lessons.map(l => l.id),
  };
  return createHash("sha256").update(JSON.stringify(normalized)).digest("hex");
}
let index = 0;
for (const mode of ["standard", "daily"]) {
  for (const level of ["beginner", "intermediate", "advanced"]) {
    for (const pattern of ["hold", "alternate", "cautious", "varied"]) {
      const digest = expected[index++];
      test("actual IONOS preview scoring/report parity: " + [mode, level, pattern].join("/"), () => {
        const payload = {
          mode, level, dayNum: mode === "daily" ? 20762 : 0,
          challenges: decisions(pattern),
        };
        const report = buildReport(payload);
        assert.ok(report, "report must be generated from the complete game");
        assert.equal(report.challenges.length, 6);
        assert.equal(report.challenges.flatMap(c => c.decisions).length, 72);
        assert.ok(report.lessons.every(l => /^ages-(18-25|26-45|46-65)$/.test(l.ageGroup)));
        assert.equal(fingerprint(report), digest, "preview-source score/feedback changed; halt checkout until reviewed");
      });
    }
  }
}
assert.equal(index, 24);
