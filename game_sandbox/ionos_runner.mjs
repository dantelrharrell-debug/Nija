// Private server process only. No network, browser globals or new scoring formulas.
import {buildReport, renderReportHtml, validateRun} from './ionos_published_report.mjs';
let raw = '';
for await (const chunk of process.stdin) {
  raw += chunk;
  if (raw.length > 32768) throw new Error('oversize_run');
}
const payload = JSON.parse(raw);
const checked = validateRun(payload);
if (!checked.ok) throw new Error('invalid_canonical_run');
const report = buildReport(payload);
if (!report) throw new Error('report_unavailable');
process.stdout.write(JSON.stringify({report, download_html: renderReportHtml(report)}));
