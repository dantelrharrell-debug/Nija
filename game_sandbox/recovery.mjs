import {PreviewReportController, returnRunId, reportMessage} from './preview-controller.mjs';
const controller = new PreviewReportController();
const status = document.getElementById('status');
const retry = document.getElementById('retry');
const download = document.getElementById('download');
const frame = document.getElementById('report');
let html = null;
let runId = null;
let validLink = true;
try { runId = returnRunId(location.search); }
catch { validLink = false; status.textContent = 'Invalid report return link. Use Reopen saved report in the game.'; retry.disabled = true; }
// Strip opaque identifiers promptly; they confer no entitlement, even before removal.
history.replaceState(null, '', '/report');
async function openReport() {
  retry.disabled = true; html = null; download.hidden = true;
  frame.hidden = true; frame.removeAttribute('srcdoc');
  try {
    const result = await controller.reopen(runId);
    if (typeof result.report?.download_html !== 'string') throw Error('report_unavailable');
    html = result.report.download_html;
    // Reuse the original server-generated script-free report. Isolate its HTML
    // in an empty-sandbox iframe; never inject it into the application's DOM.
    frame.srcdoc = html; frame.hidden = false; download.hidden = false;
    status.textContent = 'Payment verified. Your report is ready.';
  } catch (error) { status.textContent = reportMessage(error); }
  finally { retry.disabled = false; }
}
retry.addEventListener('click', openReport);
download.addEventListener('click', async () => {
  // Recheck revocation even when a previously rendered report remains in memory.
  html = null; download.hidden = true; frame.hidden = true; frame.removeAttribute('srcdoc');
  await openReport();
  if (!html) return;
  const url = URL.createObjectURL(new Blob([html], {type: 'text/html'}));
  const link = document.createElement('a'); link.href = url;
  link.download = 'my-trading-iq-report.html'; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
if (validLink) await openReport();
