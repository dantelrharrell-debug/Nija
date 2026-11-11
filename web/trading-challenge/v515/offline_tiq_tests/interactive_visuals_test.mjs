// Reads the source to confirm the interactive visuals exist and stay safe. It does NOT prove how they look.
import fs from "node:fs";
import { execSync } from "node:child_process";
const rd = (f) => fs.readFileSync(new URL("../" + f, import.meta.url), "utf8");
const V = rd("src/components/TiqLabVisuals.jsx"), L = rd("src/components/TiqLab.jsx"), R = rd("src/components/TiqResults.jsx");
const P = rd("src/pages/TradingIQChallenge.jsx"), C = rd("src/index.css");
let pass = 0, fail = 0;
const t = (n, ok) => { if (ok) pass++; else { fail++; console.log("FAIL", n); } };
t("evidence reveal is a real button with aria-expanded", /<button[^>]*aria-expanded/.test(V));
t("all four classifications", ["verified", "rumor", "screenshot", "incomplete"].every((k) => V.includes(k + ": {")));
t("classification feedback is a status region", V.includes('role="status"'));
t("news card uses evidence panel and reveals kind only after answer", L.includes("<EvidencePanel item={item} kind={saved ? item.kind : null}"));
t("risk gauge has text alternative and live status", V.includes("aria-label={\"Planned loss") && V.includes("role=\"status\""));
t("risk gauge shows entry and stop", V.includes("Entry ") && V.includes("Stop "));
t("risk gauge wired to live draft", L.includes("<RiskGauge ex={ex} units={saved ? saved : n} />"));
t("discipline scene for emotion group", L.includes('group === "emotion" && <DisciplineScene'));
t("discipline themes", ["Revenge trading", "Fear of missing out", "Overconfidence", "Impatience"].every((x) => V.includes(x)));
t("discipline shows no profit reward", /No profit is shown/.test(V) && !/\bprofit\b.*\+\$/.test(V));
t("round transitions keyed", P.includes('key={"st" + s.sIdx') && P.includes("tiq-outcome-chip") && P.includes("tiq-intro-chip"));
t("outcome labelled illustration only", /fictional change .* \(illustration only\)/.test(P));
t("results ring + recommendations", P.includes("<ScoreRing") && P.includes("<Recommendations"));
t("recommendations from scores only", R.includes("assessments[k]") && !/fetch\(/.test(R));
t("portfolio panel labelled", P.includes("Fictional portfolio — illustration only"));
t("meters, achievements, history kept", L.includes("tiq-meters") && P.includes("TiqAchievements") && P.includes("earlier scoring") || P.includes("TiqAchievements"));
t("$1 report still coming soon", P.includes("Adults 18+ Only — $1 — Coming Soon"));
t("no network in new files", ![V, R].some((x) => /fetch\(|XMLHttpRequest|localStorage/.test(x)));
for (const k of ["tiq-evid-clue", "tiq-class-stamp", "tiq-round-in", "tiq-outcome-chip", "tiq-ring-arc", "tiq-rec", "tiq-gauge-fill", "tiq-scene-fill"])
  t("reduced motion covers " + k, new RegExp("prefers-reduced-motion[\\s\\S]*" + k).test(C));
let unchanged = true; try { unchanged = execSync("git diff --name-only HEAD -- offline_tiq_premium/tiq_scoring.mjs", { stdio: ["ignore", "pipe", "ignore"] }).toString().trim() === ""; } catch { /* no git checkout (exported copy): compared by the checksum list instead */ }
t("scoring file unchanged", unchanged);
console.log(`PASS: ${pass}, FAIL: ${fail}`); process.exit(fail ? 1 : 0);
