// Drop into the EXISTING React game completion UI. No engine or scoring copy.
import {PreviewReportController, reportMessage} from './preview-controller.mjs';

export function makeSandboxReportPanel(React) {
  const h = React.createElement;
  return function SandboxReportPanel({game, Report}) {
    const controller = React.useRef(null);
    if (!controller.current) controller.current = new PreviewReportController();
    const [adult, setAdult] = React.useState(false);
    const [busy, setBusy] = React.useState(false);
    const [message, setMessage] = React.useState('');
    const [report, setReport] = React.useState(null);
    React.useEffect(() => { setReport(null); setAdult(false); }, [game.screen, game.decLog]);
    const perform = async operation => {
      setBusy(true); setMessage(''); setReport(null);
      try { await operation(); }
      catch (error) { setMessage(reportMessage(error)); }
      finally { setBusy(false); }
    };
    // Report is the original game's report component. It receives only a freshly
    // server-authorized result. No sample report or return URL can populate it.
    if (report) return h(Report, {report, preview: false, onClose: () => setReport(null)});
    return h('section', {'aria-label': 'Optional personalized results', className: 'tiq-card'},
      h('p', null, 'Test preview — optional $1 one-time personalized results. Adults 18+ only. Use Stripe test details. Gameplay stays free.'),
      game.screen === 'done' && !game.restored && game.decLog?.length === 72 && h('div', null,
        h('label', null, h('input', {type: 'checkbox', checked: adult, disabled: busy,
          onChange: event => setAdult(event.target.checked)}), ' I confirm I am 18 or older.'),
        h('button', {type: 'button', disabled: busy || !adult,
          onClick: () => perform(async () => {
            const url = await controller.current.purchase(game, adult);
            globalThis.location.assign(url);
          })}, 'Continue to $1 test checkout')),
      h('button', {type: 'button', disabled: busy, onClick: () => perform(async () => {
        const result = await controller.current.reopen();
        setReport(result.report.report);
      })}, 'Reopen / retry saved report'),
      h('p', {role: 'status', 'aria-live': 'polite'}, busy ? 'Checking securely…' : message));
  };
}
