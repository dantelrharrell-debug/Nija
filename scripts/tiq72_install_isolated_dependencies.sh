#!/bin/sh
# Build-time installation only for the isolated NIJA TIQ72 Upgrade 6 Render service.
# This script does not migrate databases, read keys, register payment routes,
# enable Stripe webhooks, modify IONOS, or activate any financial activity.
set -eu

EXPECTED_SERVICE_ID='srv-dbqeqgqfngtc73fcphhg'
if [ "${RENDER_SERVICE_ID:-}" != "$EXPECTED_SERVICE_ID" ]; then
  echo 'TIQ72 isolated dependency installation denied: wrong Render service' >&2
  exit 2
fi

ROOT=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd -P)
SERVER="$ROOT/web/trading-challenge/server"
REQ="$SERVER/requirements-tiq72-preflight.txt"
[ -f "$SERVER/package.json" ] && [ -f "$SERVER/package-lock.json" ] && [ -f "$REQ" ] || {
  echo 'TIQ72 isolated dependency installation denied: reviewed files absent' >&2
  exit 2
}

# Fail closed if either package is changed or the lock disagrees with its manifest.
node - "$SERVER" <<'NODE'
const fs = require('node:fs');
const path = require('node:path');
const base = process.argv[2];
const pkg = JSON.parse(fs.readFileSync(path.join(base, 'package.json'), 'utf8'));
const lock = JSON.parse(fs.readFileSync(path.join(base, 'package-lock.json'), 'utf8'));
const expected = {stripe: '23.1.0', pg: '8.23.1'};
const names = Object.keys(pkg.dependencies || {}).sort();
if (names.join(',') !== ['pg','stripe'].join(',') ||
    !Object.entries(expected).every(([name, version]) =>
      pkg.dependencies[name] === version &&
      lock.packages?.['']?.dependencies?.[name] === version &&
      lock.packages?.['node_modules/' + name]?.version === version)) {
  process.stderr.write('TIQ72 isolated dependency installation denied: unreviewed version or lockfile\n');
  process.exit(2);
}
NODE

grep -Fqx 'psycopg2-binary==2.9.13' "$REQ" || {
  echo 'TIQ72 isolated dependency installation denied: unreviewed Python dependency' >&2
  exit 2
}

python3 -m venv "$ROOT/.venv"
"$ROOT/.venv/bin/python" -m pip install --disable-pip-version-check --requirement "$REQ"
npm --prefix "$SERVER" ci --ignore-scripts --omit=dev --no-fund --no-audit
npm --prefix "$SERVER" audit --omit=dev --audit-level=high
(
  cd "$SERVER"
  node --input-type=module -e "import Stripe from 'stripe'; import pg from 'pg'; if (typeof Stripe!=='function' || typeof pg.Pool!=='function') process.exit(2); console.log('TIQ72 isolated Stripe and Postgres imports verified; no provider connections');"
)
echo 'TIQ72 isolated TEST dependency build passed; payment endpoints remain disabled'
