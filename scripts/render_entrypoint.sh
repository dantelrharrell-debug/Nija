#!/usr/bin/env bash
# Render-specific front door for NIJA production startup.
# Promotes common dashboard secret aliases and applies the canonical startup
# handoff to source-based services before the production bootstrap begins.

set -euo pipefail

# Guarded live-trading policy after the 2026-09-07 Kraken repair verification.
# The temporary forced SAFE_MODE thresholds have been removed; all canonical
# broker/capital/risk/position-sync/protection/market-data gates remain active.
# Recovery/heartbeat orders and forced activation/trading remain prohibited.
export NIJA_ALLOW_LIVE_HEARTBEAT_ORDERS=false
export NIJA_FORCE_ACTIVATION=false
export FORCE_TRADE=false

# Bound the live scan to the number of symbols the current OHLC path can service
# inside the existing phase-3 deadline. This reduces data-insufficient cycles
# without weakening any risk, execution, position-sync, or protective-exit gate.
export NIJA_MAX_SCAN_SYMBOLS=20
export NIJA_MARKET_DATA_STABILITY_PATCH=true
export NIJA_PHASE3_FETCH_DEADLINE_SKIP_ENABLED=true

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
python3 -S scripts/apply_execution_proof_startup_isolation_v339.py
python3 -S scripts/apply_execution_proof_freshness_truth_v375.py
python3 -S scripts/apply_activation_publication_fast_path_v376.py
python3 -S scripts/apply_kraken_coverage_truth_fairness_v385.py
python3 -S scripts/apply_user_readiness_deadline_convergence_v390.py
python3 -S scripts/apply_kraken_authoritative_wait_v398.py
python3 -S scripts/apply_kraken_inflight_readiness_v399.py
python3 -S scripts/apply_kraken_margin_four_way_supervisor_v387.py
python3 -S scripts/apply_protection_binding_precision_v391.py
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
    bot/runtime_authoritative_position_coverage_v285_patch.py \
    bot/runtime_kraken_cost_basis_bulk_v288_patch.py \
    bot/runtime_kraken_margin_canonical_coverage_v366_patch.py \
    bot/runtime_kraken_margin_protection_truth_v367_patch.py \
    bot/runtime_kraken_margin_four_way_supervisor_v387_patch.py \
    bot/runtime_kraken_native_margin_backup_v380_patch.py \
    bot/runtime_kraken_position_refresh_liveness_v286_patch.py \
    bot/trailing_stop_loss_runtime_patch.py \
    bot/writer_authority_reconstitution_v77_patch.py \
    bot/writer_single_owner_convergence_v82_patch.py \
    bot/stalled_writer_release_guard_v22.py \
    bot/writer_generation_handoff_v45_patch.py \
    bot/runtime_execution_capital_integrity_v169_patch.py \
    bot/runtime_heartbeat_marker_convergence_v238_patch.py \
    bot/tests/test_writer_generation_handoff_v45.py \
    bot/tests/test_canonical_writer_first_v59.py \
    render_liveness_server.py \
    render_outreach_routes.py \
    render_outreach_extension.py \
    render_outreach_store.py \
    scripts/canonical_runtime_launcher_v26.py \
    scripts/render_memory_pressure_guard.py \
    scripts/apply_canonical_launcher_v26.py \
    scripts/apply_execution_proof_startup_isolation_v339.py \
    scripts/apply_execution_proof_freshness_truth_v375.py \
    scripts/apply_activation_publication_fast_path_v376.py \
    scripts/apply_kraken_coverage_truth_fairness_v385.py \
    scripts/apply_user_readiness_deadline_convergence_v390.py \
    scripts/apply_kraken_authoritative_wait_v398.py \
    scripts/apply_kraken_inflight_readiness_v399.py \
    scripts/apply_kraken_margin_four_way_supervisor_v387.py \
    scripts/apply_protection_binding_precision_v391.py \
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
grep -Fq '_prepare_execution_proof_startup_isolation_v339()' scripts/canonical_runtime_launcher_v26.py
grep -Fq 'NIJA_EXECUTION_MARKER_PATH' bot/runtime_execution_capital_integrity_v169_patch.py
grep -Fq '_quarantine_authority_execution_marker()' bot/runtime_execution_capital_integrity_v169_patch.py
grep -Fq 'v169_provenance_guard_not_ready' bot/runtime_heartbeat_marker_convergence_v238_patch.py
grep -Fq 'verified_v169_execution_probe' bot/runtime_heartbeat_marker_convergence_v238_patch.py
grep -Fq 'DIRECT_EXECUTION_FRESHNESS_V375_STALE' bot/runtime_heartbeat_marker_convergence_v238_patch.py
grep -Fq 'READINESS_PROOF_CONVERGENCE_V134' bot/bot.py
grep -Fq 'ACTIVATION_STOP_CAPITAL_FRESHNESS_V135' bot/bot.py
grep -Fq 'ACTIVATION_PUBLICATION_CONVERGENCE_V136' bot/bot.py
grep -Fq 'KRAKEN_MARGIN_POSITION_PROTECTION_PENDING_V385' bot/runtime_kraken_margin_canonical_coverage_v366_patch.py
grep -Fq 'AUTHORITATIVE_USER_POSITION_V390_DEADLINE_REFRESH' bot/runtime_authoritative_position_coverage_v285_patch.py
grep -Fq 'KRAKEN_COST_BASIS_V390_USER_RECONCILE_DUE' bot/runtime_kraken_cost_basis_bulk_v288_patch.py
grep -Fq 'KRAKEN_MARGIN_FOUR_WAY_SUPERVISOR_V387' bot/bot.py
grep -Fq 'KRAKEN_MARGIN_FOUR_WAY_SUPERVISOR_V387_READY' bot/runtime_kraken_margin_four_way_supervisor_v387_patch.py
grep -Fq 'TRAILING_STOP_ENGINE_DEFERRED_V391' bot/trailing_stop_loss_runtime_patch.py
grep -Fq 'KRAKEN_NATIVE_MARGIN_PRICE_PRECISION_V391' bot/runtime_kraken_native_margin_backup_v380_patch.py
grep -Fq '20260907-kraken-authoritative-wait-v398' scripts/apply_kraken_authoritative_wait_v398.py
grep -Fq '20260907-kraken-inflight-readiness-v399' scripts/apply_kraken_inflight_readiness_v399.py
grep -Fq 'bind_entrypoint_writer_authority_aliases(runtime)' bot/bot_main.py
grep -Fq 'NIJA_ENTRYPOINT_WRITER_MODULE_IDENTITY_CONVERGED' bot/entrypoint_writer_authority.py
grep -Fq 'heartbeat_telemetry_mutation=false' bot/broker_manager.py
grep -Fq 'handle_outreach_extension_get(self)' render_liveness_server.py
grep -Fq 'handle_outreach_get(self)' render_liveness_server.py
grep -Fq 'handle_outreach_extension_post(self)' render_liveness_server.py
grep -Fq 'handle_outreach_post(self)' render_liveness_server.py
grep -Fq 'start_justcall_webhook_autoconfig()' render_liveness_server.py

echo "🧭 RENDER_ENTRYPOINT_CANONICAL_HANDOFF_READY marker=20260907-kraken-inflight-readiness-v399 launcher=canonical_runtime_launcher_v26 writer_generation_handoff=v45 writer_first=v59 execution_proof_startup_isolation=v339 execution_proof_freshness_truth=v375 activation_publication_fast_path=v376 kraken_coverage_truth_fairness=v385 user_readiness_deadline_convergence=v390 kraken_authoritative_wait=v398 kraken_inflight_readiness=v399 kraken_margin_four_way_supervisor=v387 protection_binding_precision=v391 native_backup_started=false orders_submitted=false signal_forwarding=v262 single_identity=true singleton_alias_convergence=v91 kraken_nonce_authority_gate=v91 direct_broker_prebootstrap=v27 outreach_frontdoor=v3 signed_webhook=true webhook_autoconfig=true campaign_compliance_fail_closed=true"
unset NIJA_DEFER_RUNTIME_SITE_HOOKS

exec bash scripts/production_bootstrap.sh "$@"