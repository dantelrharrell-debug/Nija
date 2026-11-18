// Read-only private PostgreSQL preflight for the isolated NIJA TIQ72 Render service.
// Runs the reviewed Python script; never logs DB URLs, credentials, rows, stderr,
// stdout verbatim, process errors, or a success claim about payments.
import {spawnSync} from 'node:child_process';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {inspectTiq72IsolatedPrivateUrl} from './tiq72-isolated-readiness.mjs';

const tableNames = Object.freeze([
  'tiq72_v515_runs',
  'tiq72_v515_reservations',
  'tiq72_v515_reports',
  'tiq72_v515_verified_events'
]);
const script = fileURLToPath(new URL('../../../scripts/tiq72_isolated_db_readonly_preflight.py', import.meta.url));
const blocked = reason => ({status:'blocked', reason, migration_verified:false});
export function runTiq72IsolatedDatabaseProbe(env=process.env, run=spawnSync) {
  if (!inspectTiq72IsolatedPrivateUrl(env.TIQ72_TEST_DATABASE_URL))
    return blocked('private_database_identity_mismatch');
  try {
    const result = run(path.resolve(process.cwd(), '.venv/bin/python'),
      [script], {
        env, encoding:'utf8', timeout:12000, maxBuffer:4096,
        stdio:['ignore','pipe','ignore']
      });
    if (result?.error || result?.status!==0 || typeof result.stdout!=='string' ||
        result.stdout.length>4096)
      return blocked('private_read_only_preflight_failed');
    const found = JSON.parse(result.stdout);
    if (found?.status!=='identity_verified_read_only' ||
        !Array.isArray(found.expected_tables_present) ||
        !Array.isArray(found.expected_tables_missing) ||
        typeof found.migration_applied!=='boolean')
      return blocked('invalid_preflight_result');
    const present=found.expected_tables_present,missing=found.expected_tables_missing;
    if (present.some(x=>!tableNames.includes(x)) ||
        missing.some(x=>!tableNames.includes(x)) ||
        new Set([...present,...missing]).size!==tableNames.length ||
        present.length+missing.length!==tableNames.length ||
        present.some(x=>missing.includes(x)) ||
        found.migration_applied !== (missing.length===0))
      return blocked('invalid_preflight_result');
    return {
      status:'identity_verified_read_only',
      expected_tables_present: [...present].sort(),
      expected_tables_missing: [...missing].sort(),
      expected_schema_present:missing.length===0,
      migration_verified:false,
      checkout_available:false
    };
  } catch {
    return blocked('private_read_only_preflight_failed');
  }
}
