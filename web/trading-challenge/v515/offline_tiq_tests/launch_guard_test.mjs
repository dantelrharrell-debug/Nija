import fs from "node:fs";
let pass = 0, fail = 0;
const ok = (c, n) => { if (c) pass++; else { fail++; console.log("FAIL", n); } };
const files = ["src/pages/TradingIQChallenge.jsx","src/components/TiqLab.jsx","src/components/TiqReport.jsx","src/components/TiqCoach.jsx","src/components/TiqAchievements.jsx","src/lib/tiqProgress.js","src/lib/tiqBackendClient.js","src/lib/tiqReportClient.js","src/lib/tiqReportReopen.js"];
const src = Object.fromEntries(files.map(f => [f, fs.readFileSync(f, "utf8")]));
for (const f of files) {
  const s = src[f];
  ok(!/\bfetch\s*\(|XMLHttpRequest|sendBeacon|WebSocket|EventSource/.test(s), f + " no network calls");
  ok(!/pocketbase|from ["'].*lib\/pb/i.test(s), f + " no data-store import");
  ok(!/stripe|buy\.stripe|checkout\.session|sk_live|pk_live|api[_-]?key|secret/i.test(s.replace(/\/\/.*$/gm, "").replace(/No payment[^.]*\./g, "")) || f.endsWith("TradingIQChallenge.jsx") === false && false, f + " no payment/credential strings");
  ok(!/broker.*connect\(|placeOrder|submitOrder/i.test(s), f + " no order code");
}
const g = src["src/pages/TradingIQChallenge.jsx"];
ok(g.includes("Adults 18+ Only — $1 — Coming Soon"), "report marked Coming Soon");
ok(/REOPEN_AVAILABLE = false/.test(src["src/lib/tiqReportReopen.js"]), "reopen disabled");
ok(/disabled=\{!adultOk\}/.test(g) && /previewSimulationAllowed/.test(g), "sample report gated to preview hosts");
ok(/BrandMark/.test(g), "logo present");
ok(!/(login|signIn|authWithPassword|requireAuth)/i.test(g), "no registration gate");
const css = fs.readFileSync("src/index.css", "utf8");
ok(/overflow-x: clip/.test(css) && /prefers-reduced-motion/.test(css), "overflow + reduced motion rules");
console.log(`PASS: ${pass}, FAIL: ${fail}`); process.exit(fail ? 1 : 0);
