#!/usr/bin/env bash
# Build-only bootstrap for isolated 72-decision TEST holding service.
# Does not authorize payments, trades, migrations, or public routes.
set -euo pipefail

if [[ "${TIQ72_ISOLATED_BUILD_SCOPE:-}" != "holding-test-only" ]]; then
  echo "TIQ72_BUILD blocked: isolated_build_scope_missing" >&2
  exit 64
fi

# Render may expose a service identity; when present it must match the exact
# existing isolated TEST instance rather than the trading or billing service.
if [[ -n "${RENDER_SERVICE_ID:-}" && "${RENDER_SERVICE_ID}" != "srv-dbqeqgqfngtc73fcphhg" ]]; then
  echo "TIQ72_BUILD blocked: wrong_render_service" >&2
  exit 64
fi

root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
server="$root/web/trading-challenge/server"
if [[ ! -s "$server/package-lock.json" || ! -s "$server/package.json" ||
      ! -s "$server/requirements-tiq72-preflight.txt" ]]; then
  echo "TIQ72_BUILD blocked: reviewed_dependencies_missing" >&2
  exit 65
fi

major="$(node -p 'Number(process.versions.node.split(".")[0])')"
if [[ ! "$major" =~ ^[0-9]+$ ]] || ((major < 22 || major > 26)); then
  echo "TIQ72_BUILD blocked: unsupported_node_runtime" >&2
  exit 65
fi

(
  cd "$server"
  npm ci --omit=dev --ignore-scripts --no-fund --no-audit
  npm audit --omit=dev --audit-level=high
  node --input-type=module -e '
    import Stripe from "stripe";
    import pg from "pg";
    if (typeof Stripe !== "function" || typeof pg.Pool !== "function")
      process.exit(1);
  '
)

# Separate from global Python and from protected trading runtime.
python3 -m venv "$root/.venv"
"$root/.venv/bin/python" -m pip install --disable-pip-version-check \
  --only-binary=:all: -r "$server/requirements-tiq72-preflight.txt"
"$root/.venv/bin/python" -c 'import psycopg2; assert psycopg2.__version__.startswith("2.9.13")'

echo "TIQ72_BUILD verified: pinned_node_and_python_dependencies_installed"
