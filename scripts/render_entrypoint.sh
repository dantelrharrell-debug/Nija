#!/usr/bin/env bash
# Render-specific front door for NIJA production startup.
# Promotes common dashboard secret aliases and applies the canonical startup
# handoff to source-based services before the production bootstrap begins.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

_promote_secret_alias() {
    local canonical="$1"
    shift

    if [[ -n "${!canonical:-}" ]]; then
        return 0
    fi

    local alias
    for alias in "$@"; do
        if [[ -n "${!alias:-}" ]]; then
            export "${canonical}=${!alias}"
            echo "🔑 Render secret alias normalized: ${canonical}<-${alias}"
            return 0
        fi
    done

    return 0
}

_promote_secret_alias KRAKEN_PLATFORM_API_KEY \
    KRAKEN_API_KEY \
    KRAKEN_MASTER_API_KEY \
    KRAKEN_MASTER_KEY \
    KRAKEN_PLATFORM_KEY

_promote_secret_alias KRAKEN_PLATFORM_API_SECRET \
    KRAKEN_API_SECRET \
    KRAKEN_PRIVATE_KEY \
    KRAKEN_SECRET_KEY \
    KRAKEN_MASTER_API_SECRET \
    KRAKEN_MASTER_SECRET \
    KRAKEN_PLATFORM_SECRET

# Docker builds already apply the legacy handoff patch. Running it again is
# intentionally idempotent and closes the source-runtime gap for an existing
# Render service that executes repository files without rebuilding the layer.
export NIJA_DEFER_RUNTIME_SITE_HOOKS=1
python3 -S scripts/apply_startup_handoff_fix.py
python3 -S scripts/apply_canonical_launcher_v26.py
bash -n start.sh
python3 -S -m py_compile \
    main.py \
    bot/bot.py \
    bot/bot_main.py \
    bot/canonical_broker_prebootstrap_v22.py \
    bot/canonical_broker_startup_convergence_v24.py \
    bot/live_broker_profit_exit_convergence_v25.py \
    bot/live_engine_profit_exit_convergence_v25.py \
    bot/live_exit_reconciliation_safety_v25.py \
    bot/stalled_writer_release_guard_v22.py \
    scripts/canonical_runtime_launcher_v26.py \
    scripts/apply_canonical_launcher_v26.py \
    scripts/runtime_entrypoint_attestation.py

grep -Fq '$PY -u scripts/canonical_runtime_launcher_v26.py' start.sh
if grep -Fq '$PY -u main.py' start.sh; then
    echo "❌ Legacy direct main.py launch remains after v26 patch"
    exit 78
fi

echo "🧭 RENDER_ENTRYPOINT_CANONICAL_HANDOFF_READY marker=20260724-render-entrypoint-v26 launcher=canonical_runtime_launcher_v26"
unset NIJA_DEFER_RUNTIME_SITE_HOOKS

exec bash scripts/production_bootstrap.sh "$@"
