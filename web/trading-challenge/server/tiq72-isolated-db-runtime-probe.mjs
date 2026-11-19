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
const allowedFailureCodes = new Set([
  'private_database_identity_mismatch','private_db_driver_unavailable',
  'private_db_credentials_rejected','private_db_database_unavailable',
  'private_db_server_unavailable','private_db_dns_unavailable',
  'private_db_tcp_unavailable','private_db_tls_or_auth_rejected',
  'private_db_connection_failed','connected_database_identity_mismatch',
  'private_db_readonly_catalog_query_failed'
]);
export function runTiq72IsolatedDatabaseProbe(env=process.env, run=spawnSync) {
  if (!inspectTiq72IsolatedPrivateUrl(env.TIQ72_TEST_DATABASE_URL))
    return blocked('private_database_identity_mismatch');
  try {
    const result = run(path.resolve(process.cwd(), '.venv/bin/python'),
      [script], {
        env, encoding:'utf8', timeout:12000, maxBuffer:4096,
        stdio:['ignore','pipe','ignore']
      });
    if (result?.error || typeof result.stdout!=='string' ||
        result.stdout.length>4096)
      return blocked('private_read_only_preflight_failed');
    const found = JSON.parse(result.stdout);
    if (result.status!==0) {
      if (found?.status==='blocked' && allowedFailureCodes.has(found.reason))
        return blocked(found.reason);
      return blocked('private_read_only_preflight_failed');
    }
    if (found?.status!=='identity_verified_read_only' ||
        !Array.isArray(found.expected_tables_present) ||
        !Array.isArray(found.expected_tables_missing) ||
        typeof found.migration_applied!=='boolean' ||
        typeof found.schema_contract_verified!=='boolean' ||
        !Number.isSafeInteger(found.public_base_table_count) ||
        found.public_base_table_count<0 || found.public_base_table_count>1000000)
      return blocked('invalid_preflight_result');
    const present=found.expected_tables_present,missing=found.expected_tables_missing;
    if (present.some(x=>!tableNames.includes(x)) ||
        missing.some(x=>!tableNames.includes(x)) ||
        new Set([...present,...missing]).size!==tableNames.length ||
        present.length+missing.length!==tableNames.length ||
        present.some(x=>missing.includes(x)) ||
        found.migration_applied !== found.schema_contract_verified ||
        (found.schema_contract_verified && missing.length!==0))
      return blocked('invalid_preflight_result');
    if (found.public_base_table_count < present.length)
      return blocked('invalid_preflight_result');
    return {
      status:'identity_verified_read_only',
      public_base_table_count:found.public_base_table_count,
      expected_tables_present: [...present].sort(),
      expected_tables_missing: [...missing].sort(),
      expected_schema_present:missing.length===0 && found.schema_contract_verified,
      schema_contract_verified:found.schema_contract_verified,
      migration_verified:false,
      checkout_available:false
    };
  } catch {
    return blocked('private_read_only_preflight_failed');
  }
}
