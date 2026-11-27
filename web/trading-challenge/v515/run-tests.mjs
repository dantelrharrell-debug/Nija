// Added for this export (not part of v515). Runs every *_test.mjs in offline_tiq_premium/ and offline_tiq_tests/
// from the export root and prints the pass/fail line each one reports. Needs Node 20+. No network, no packages.
import { readdirSync } from "node:fs";
import { spawnSync } from "node:child_process";
let bad = 0;
for (const d of ["offline_tiq_premium", "offline_tiq_tests"])
  for (const f of readdirSync(d).filter((x) => x.endsWith("_test.mjs")).sort()) {
    const r = spawnSync(process.execPath, [`${d}/${f}`], { encoding: "utf8" });
    const last = (r.stdout + r.stderr).trim().split("\n").slice(-1)[0];
    console.log(`${r.status === 0 ? "ok  " : "FAIL"} ${d}/${f}  ${last}`);
    if (r.status !== 0) bad++;
  }
console.log(bad ? `${bad} file(s) failed` : "all files exited 0");
process.exit(bad ? 1 : 0);
