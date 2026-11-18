// Isolated Upgrade 6 startup diagnostic: one authenticated, read-only DB query.
// Never exposes a public route, edits the database, or authorizes a payment.
import {spawnSync} from 'node:child_process';
import path from 'node:path';
import {inspectTiq72IsolatedPrivateUrl} from './tiq72-isolated-readiness.mjs';

const TABLES = Object.freeze([
  'tiq72_v515_runs',
  'tiq72_v515_reservations',
  'tiq72_v515_reports',
  'tiq72_v515_verified_events'
]);
const REASONS = new Set([
  'private_database_identity_mismatch',
  'private_read_only_preflight_failed'
]);

function blocked(reason) {
  return {
    status: 'blocked',
    reason,
    connected_database_identity_verified: false,
    expected_tables_present: [],
    expected_tables_missing: [],
    schema_certified: false,
    payment_certified: false
  };
}

export function runTiq72PrivateDbPreflight({
  env = process.env,
  root = process.cwd(),
  invoke = spawnSync
} = {}) {
  if (!inspectTiq72IsolatedPrivateUrl(env.TIQ72_TEST_DATABASE_URL)) {
    return blocked('private_database_identity_mismatch');
  }
  // The interpreter and psycopg2 are installed into this isolated service's
  // virtualenv by its reviewed Render build command, not the trading service.
  const python = path.join(root, '.venv', 'bin', 'python');
  const script = path.join(root, 'scripts', 'tiq72_isolated_db_readonly_preflight.py');
  let response;
  try {
    response = invoke(python, [script], {
      cwd: root,
      env,
      encoding: 'utf8',
      timeout: 12000,
      maxBuffer: 4096,
      stdio: ['ignore', 'pipe', 'ignore'],
      windowsHide: true,
      shell: false
    });
  } catch {
    return blocked('read_only_preflight_process_unavailable');
  }
  if (response.error || response.signal || !Number.isInteger(response.status) ||
      typeof response.stdout !== 'string' || response.stdout.length > 2048 ||
      response.stdout.trim().includes('\n')) {
    return blocked('read_only_preflight_process_unavailable');
  }
  let payload;
  try {
    payload = JSON.parse(response.stdout);
  } catch {
    return blocked('invalid_preflight_output');
  }
  if (response.status !== 0) {
    return blocked(payload?.status === 'blocked' && REASONS.has(payload.reason)
      ? payload.reason : 'invalid_preflight_output');
  }
  if (payload?.status !== 'identity_verified_read_only' ||
      !Array.isArray(payload.expected_tables_present) ||
      !Array.isArray(payload.expected_tables_missing)) {
    return blocked('invalid_preflight_output');
  }
  const found = payload.expected_tables_present;
  const missing = payload.expected_tables_missing;
  const combined = [...found, ...missing].sort();
  if (combined.length !== TABLES.length ||
      combined.some((table, i) => table !== [...TABLES].sort()[i]) ||
      payload.migration_applied !== (missing.length === 0)) {
    return blocked('invalid_preflight_output');
  }
  return {
    status: 'identity_verified_read_only',
    connected_database_identity_verified: true,
    expected_tables_present: [...found].sort(),
    expected_tables_missing: [...missing].sort(),
    schema_certified: false,
    payment_certified: false
  };
}
