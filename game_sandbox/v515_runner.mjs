// Private adapter for the approved v515 report, called only after entitlement verification.
import { buildReport, reportToHtml } from '../web/trading-challenge/v515/offline_tiq_premium/tiq_report.mjs';
import { validateRun } from '../web/trading-challenge/v515/offline_tiq_premium/tiq_engine.mjs';
let raw = '';
for await (const chunk of process.stdin) {
  raw += chunk;
  if (raw.length > 32768) throw Error('oversize_run');
}
const payload = JSON.parse(raw);
if (!validateRun(payload).ok) throw Error('invalid_v515_run');
const report = buildReport(payload);
if (!report || report.challenges.length !== 6 ||
    report.challenges.some(challenge => challenge.decisions.length !== 12)) {
  throw Error('invalid_v515_report');
}
process.stdout.write(JSON.stringify({ report, download_html: reportToHtml(report) }));
