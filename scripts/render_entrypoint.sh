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

# Apply every startup-order repair before any normal Python interpreter can load
# NIJA runtime hooks. All patchers are idempotent and fail closed.
export NIJA_DEFER_RUNTIME_SITE_HOOKS=1
python3 -S scripts/apply_startup_handoff_fix.py
python3 -S scripts/apply_canonical_launcher_v26.py
python3 -S scripts/apply_writer_generation_handoff_v45.py
python3 -S scripts/apply_render_signal_forwarding_v262.py
python3 -S scripts/apply_render_outreach_frontdoor.py
bash -n start.sh
python3 -S -m py_compile \
    main.py \
    bot/bot.py \
    bot/bot_main.py \
    bot/entrypoint_writer_authority.py \
    bot/broker_manager.py \
    bot/canonical_broker_prebootstrap_v22.py \
    bot/canonical_broker_startup_convergence_v24.py \
    bot/live_broker_profit_exit_convergence_v25.py \
    bot/live_engine_profit_exit_convergence_v25.py \
    bot/live_exit_reconciliation_safety_v25.py \
    bot/kraken_connection_convergence_v44_patch.py \
    bot/kraken_all_account_supervision_v86.py \
    bot/writer_authority_reconstitution_v77_patch.py \
    bot/writer_single_owner_convergence_v82_patch.py \
    bot/stalled_writer_release_guard_v22.py \
    bot/writer_generation_handoff_v45_patch.py \
    bot/tests/test_writer_generation_handoff_v45.py \
    bot/tests/test_canonical_writer_first_v59.py \
    render_liveness_server.py \
    render_outreach_routes.py \
    scripts/canonical_runtime_launcher_v26.py \
    scripts/render_memory_pressure_guard.py \
    scripts/apply_canonical_launcher_v26.py \
    scripts/apply_writer_generation_handoff_v45.py \
    scripts/apply_render_signal_forwarding_v262.py \
    scripts/apply_render_outreach_frontdoor.py \
    scripts/apply_direct_broker_prebootstrap_v27.py \
    scripts/runtime_entrypoint_attestation.py

grep -Fq '$PY -u scripts/canonical_runtime_launcher_v26.py &' start.sh
if grep -Fq '$PY -u main.py' start.sh; then
    echo "❌ Legacy direct main.py launch remains after v26 patch"
    exit 78
fi
grep -Fq 'RENDER_RUNTIME_SIGNAL_FORWARDED marker=20260828-render-signal-forwarding-v262' start.sh
grep -Fq '_RENDER_RUNTIME_CHILD_PID=$!' start.sh
grep -Fq 'kill -TERM "${_RENDER_RUNTIME_CHILD_PID}"' start.sh
grep -Fq 'DIRECT_CANONICAL_BROKER_PREBOOTSTRAP_V27_READY' bot/bot_main.py
grep -Fq 'V45_PATH = ROOT / "bot" / "writer_generation_handoff_v45_patch.py"' scripts/canonical_runtime_launcher_v26.py
grep -Fq '_install_writer_generation_handoff_v45()' scripts/canonical_runtime_launcher_v26.py
grep -Fq 'CANONICAL_EARLY_WRITER_BOOTSTRAP_VERIFIED' scripts/canonical_runtime_launcher_v26.py
grep -Fq 'CANONICAL_BOT_SINGLE_IDENTITY_HANDOFF' scripts/canonical_runtime_launcher_v26.py
grep -Fq 'NIJA_CANONICAL_WRITER_FIRST_V59_READY' scripts/canonical_runtime_launcher_v26.py
grep -Fq '_start_render_memory_pressure_guard()' scripts/canonical_runtime_launcher_v26.py
grep -Fq 'bind_entrypoint_writer_authority_aliases(runtime)' bot/bot_main.py
grep -Fq 'NIJA_ENTRYPOINT_WRITER_MODULE_IDENTITY_CONVERGED' bot/entrypoint_writer_authority.py
grep -Fq 'heartbeat_telemetry_mutation=false' bot/broker_manager.py
grep -Fq 'handle_outreach_get(self)' render_liveness_server.py
grep -Fq 'handle_outreach_post(self)' render_liveness_server.py

echo "🧭 RENDER_ENTRYPOINT_CANONICAL_HANDOFF_READY marker=20260828-render-signal-forwarding-v262 launcher=canonical_runtime_launcher_v26 writer_generation_handoff=v45 writer_first=v59 signal_forwarding=v262 single_identity=true singleton_alias_convergence=v91 kraken_nonce_authority_gate=v91 direct_broker_prebootstrap=v27 outreach_frontdoor=v1"
unset NIJA_DEFER_RUNTIME_SITE_HOOKS

exec bash scripts/production_bootstrap.sh "$@"
