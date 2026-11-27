// Reproducible development-only insertion into the reviewed existing game build.
// Run: node game_sandbox/install-preview.mjs INPUT_ASSET NEW_OUTPUT_ASSET
// Copy the result only into an isolated same-origin copy of the website.
import {createHash} from 'node:crypto';
import {readFile, writeFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';

const REVIEWED_SHA256 = 'b5bee76f60924997a2f33f85a36d78aa17544c4ddee85c680ec30f93f89bfccd'; // pragma: allowlist secret -- public website build checksum
const anchor = 'e.screen==="intro"&&t.jsxs("section",{className:"tiq-card tiq-rise","aria-labelledby":"tiq-title"';

export function installPreview(source) {
  if (createHash('sha256').update(source).digest('hex') !== REVIEWED_SHA256)
    throw Error('unreviewed_game_build');
  if (source.split(anchor).length !== 2 || !source.includes('function ze({report:e,preview:a,onClose:s})'))
    throw Error('game_integration_anchor_mismatch');
  // Same original reducer state and same original report renderer. Only the
  // additional preview panel is inserted. No pricing, scores or formulas copied.
  return 'import {makeSandboxReportPanel} from "/sandbox-ui/preview-panel.mjs";\n'
    + source.replace(anchor, 't.jsx(NijaSandboxPanel,{game:e,Report:ze}),' + anchor)
    + '\nconst NijaSandboxPanel = makeSandboxReportPanel(S);\n';
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  const [, , input, output] = process.argv;
  if (!input || !output || resolve(input) === resolve(output)) throw Error('distinct_input_and_output_required');
  const patched = installPreview(await readFile(input, 'utf8'));
  await writeFile(output, patched, {flag: 'wx'});
}
