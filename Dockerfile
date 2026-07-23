FROM python:3.11-slim

RUN apt-get update && apt-get install -y git redis-tools && rm -rf /var/lib/apt/lists/*
RUN groupadd -r nija && useradd -r -g nija -u 1000 nija
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY scripts/ scripts/
COPY . .
RUN python -S /app/scripts/install_sitecustomize_defer_guard.py && \
    python -S /app/apply_bot_package_defer_fix.py && \
    python -S /app/scripts/apply_startup_handoff_fix.py && \
    bash -n /app/start.sh && \
    bash -n /app/scripts/production_bootstrap.sh
RUN python -m py_compile \
        /app/main.py \
        /app/bot.py \
        /app/apply_bot_package_defer_fix.py \
        /app/scripts/install_sitecustomize_defer_guard.py \
        /app/render_liveness_server.py \
        /app/render_readiness_state_bridge.py \
        /app/prebot_writer_authority_bootstrap.py \
        /app/prebot_writer_authority_fail_closed.py \
        /app/source_runtime_guard_bootstrap.py \
        /app/runtime_patch_idempotence_guard.py \
        /app/account_capital_isolation_v4_patch.py \
        /app/coinbase_authenticated_connect_recovery_patch.py \
        /app/coinbase_connect_recursion_terminal_guard.py \
        /app/scan_symbol_sanitizer_patch.py \
        /app/kraken_equity_freshness_v3_patch.py \
        /app/critical_runtime_repairs_v6.py \
        /app/critical_runtime_repairs_v7.py \
        /app/critical_runtime_repairs_v8.py \
        /app/critical_runtime_repairs_v9.py \
        /app/critical_runtime_repairs_v10.py \
        /app/runtime_convergence_v15_patch.py \
        /app/preactivation_readiness_convergence_v16_patch.py \
        /app/exit_protection_assurance_patch.py \
        /app/venue_readiness_execution_repair_patch.py \
        /app/secondary_venue_activation_patch.py \
        /app/secondary_venue_connect_semantics_repair.py \
        /app/secondary_venue_runtime_diagnostics.py \
        /app/secondary_venue_strict_readiness_patch.py \
        /app/profit_first_loss_prevention_patch.py \
        /app/bot/activation_pending_commit_monitor_patch.py \
        /app/bot/writer_lock_release_guard.py \
        /app/bot/global_runtime_startup_guards.py \
        /app/bot/scan_wrapper_hard_clamp_patch.py \
        /app/bot/kraken_verified_cost_basis_recovery_patch.py \
        /app/bot/position_cost_basis_entry_lock_patch.py \
        /app/bot/phase3_execution_handoff_repair_patch.py \
        /app/bot/live_entry_completion_repair_patch.py \
        /app/bot/phase3_admission_trace_repair_patch.py \
        /app/bot/final_account_router_exit_convergence_patch.py \
        /app/bot/daily_gain_profit_harvest_patch.py \
        /app/bot/kraken_tpe_min_notional_allocation_patch.py \
        /app/bot/runtime_guard_audit_patch.py \
        /app/import_hook_recursion_shield_patch.py \
        /app/disconnected_broker_execution_guard_patch.py \
        /app/scripts/apply_startup_handoff_fix.py \
        /app/scripts/three_venue_config_check.py

RUN python -c "import pathlib, site; root = pathlib.Path(site.getsitepackages()[0]); prefix = '/app\n'; guard = 'import os; os.environ.get(\"NIJA_DEFER_RUNTIME_SITE_HOOKS\", \"0\") != \"1\" and '; p0 = root / '000_nija_prebot_writer_authority.pth'; p0.write_text(prefix + guard + '__import__(\"prebot_writer_authority_fail_closed\").install(defer_if_render=True)\n', encoding='utf-8'); p1 = root / 'nija_import_hook_recursion_shield.pth'; p1.write_text(prefix + guard + '__import__(\"import_hook_recursion_shield_patch\").install_import_hook()\n', encoding='utf-8'); p2 = root / 'nija_disconnected_broker_execution_guard.pth'; p2.write_text(prefix + guard + '__import__(\"disconnected_broker_execution_guard_patch\").install_import_hook()\n', encoding='utf-8'); p3 = root / 'nija_secondary_venue_connect_semantics.pth'; p3.write_text(prefix + guard + '__import__(\"secondary_venue_connect_semantics_repair\")\n', encoding='utf-8'); p4 = root / '0001_nija_secondary_venue_runtime_diagnostics.pth'; p4.write_text(prefix + guard + '__import__(\"secondary_venue_runtime_diagnostics\")\n', encoding='utf-8'); p5 = root / '0002_nija_profit_first_loss_prevention.pth'; p5.write_text(prefix + guard + '__import__(\"profit_first_loss_prevention_patch\").install_import_hook()\n', encoding='utf-8'); p6 = root / '0003_nija_runtime_patch_idempotence.pth'; p6.write_text(prefix + guard + '__import__(\"runtime_patch_idempotence_guard\").install()\n', encoding='utf-8'); p7 = root / '0004_nija_account_capital_isolation.pth'; p7.write_text(prefix + guard + '__import__(\"account_capital_isolation_v4_patch\").install()\n', encoding='utf-8'); p8 = root / '0005_nija_coinbase_connect_terminal.pth'; p8.write_text(prefix + guard + '__import__(\"coinbase_connect_recursion_terminal_guard\").install()\n', encoding='utf-8'); p9 = root / '0006_nija_scan_symbol_sanitizer.pth'; p9.write_text(prefix + guard + '__import__(\"scan_symbol_sanitizer_patch\").install()\n', encoding='utf-8'); p10 = root / '0007_nija_kraken_equity_freshness.pth'; p10.write_text(prefix + guard + '__import__(\"kraken_equity_freshness_v3_patch\").install()\n', encoding='utf-8'); p11 = root / '0008_nija_critical_runtime_repairs_v9.pth'; p11.write_text(prefix + guard + '__import__(\"critical_runtime_repairs_v9\").install()\n', encoding='utf-8'); p12 = root / '0009_nija_critical_runtime_repairs_v10.pth'; p12.write_text(prefix + guard + '__import__(\"critical_runtime_repairs_v10\").install()\n', encoding='utf-8'); p13 = root / '0010_nija_exit_protection_assurance.pth'; p13.write_text(prefix + guard + '__import__(\"exit_protection_assurance_patch\").install_import_hook()\n', encoding='utf-8'); p14 = root / '0011_nija_runtime_convergence_v15.pth'; p14.write_text(prefix + guard + '__import__(\"runtime_convergence_v15_patch\").install()\n', encoding='utf-8'); assert all(p.is_file() for p in (p0,p1,p2,p3,p4,p5,p6,p7,p8,p9,p10,p11,p12,p13,p14))"
RUN python -S -c "import pathlib; required = [pathlib.Path('/app/apply_bot_package_defer_fix.py'), pathlib.Path('/app/prebot_writer_authority_fail_closed.py'), pathlib.Path('/app/import_hook_recursion_shield_patch.py'), pathlib.Path('/app/disconnected_broker_execution_guard_patch.py'), pathlib.Path('/app/secondary_venue_connect_semantics_repair.py'), pathlib.Path('/app/secondary_venue_runtime_diagnostics.py'), pathlib.Path('/app/profit_first_loss_prevention_patch.py'), pathlib.Path('/app/runtime_patch_idempotence_guard.py'), pathlib.Path('/app/account_capital_isolation_v4_patch.py'), pathlib.Path('/app/coinbase_authenticated_connect_recovery_patch.py'), pathlib.Path('/app/coinbase_connect_recursion_terminal_guard.py'), pathlib.Path('/app/scan_symbol_sanitizer_patch.py'), pathlib.Path('/app/kraken_equity_freshness_v3_patch.py'), pathlib.Path('/app/critical_runtime_repairs_v6.py'), pathlib.Path('/app/critical_runtime_repairs_v7.py'), pathlib.Path('/app/critical_runtime_repairs_v8.py'), pathlib.Path('/app/critical_runtime_repairs_v9.py'), pathlib.Path('/app/critical_runtime_repairs_v10.py'), pathlib.Path('/app/runtime_convergence_v15_patch.py'), pathlib.Path('/app/preactivation_readiness_convergence_v16_patch.py'), pathlib.Path('/app/exit_protection_assurance_patch.py'), pathlib.Path('/app/bot/position_cost_basis_entry_lock_patch.py'), pathlib.Path('/app/bot/phase3_execution_handoff_repair_patch.py'), pathlib.Path('/app/bot/live_entry_completion_repair_patch.py'), pathlib.Path('/app/bot/phase3_admission_trace_repair_patch.py'), pathlib.Path('/app/bot/final_account_router_exit_convergence_patch.py')]; missing = [str(p) for p in required if not p.is_file()]; assert not missing, 'missing runtime modules: ' + ', '.join(missing); print('NIJA_BUILD_MODULE_PRESENCE_OK')"

RUN test -f /app/scripts/redis_connectivity_check.sh && \
    test -f /app/scripts/production_bootstrap.sh && \
    test -f /app/scripts/three_venue_config_check.py && \
    test -f /app/scripts/render_entrypoint.sh && \
    chmod +x /app/scripts/redis_connectivity_check.sh \
             /app/scripts/production_bootstrap.sh \
             /app/scripts/render_entrypoint.sh && \
    if [ -f /app/scripts/debug_startup_safe_mode.sh ]; then chmod +x /app/scripts/debug_startup_safe_mode.sh; fi
RUN if [ -d /app/scripts ]; then chmod +x /app/scripts/*.sh || true; fi

ARG GIT_BRANCH=""
ARG GIT_COMMIT=""
ARG RENDER_GIT_BRANCH=""
ARG RENDER_GIT_COMMIT=""
ARG RENDER_SERVICE_ID=""
ARG RENDER_SERVICE_NAME=""
ARG RAILWAY_GIT_BRANCH=""
ARG RAILWAY_GIT_COMMIT_SHA=""
ARG RAILWAY_DEPLOYMENT_ID=""
ARG RAILWAY_ENVIRONMENT_NAME=""
ARG BUILD_TIMESTAMP=""
ENV GIT_BRANCH=${GIT_BRANCH}
ENV GIT_COMMIT=${GIT_COMMIT}
ENV BUILD_TIMESTAMP=${BUILD_TIMESTAMP}
RUN ./inject_git_metadata.sh
ENV CANDLELITE_CONFIG_DIR=/tmp/candlelite
RUN mkdir -p /app/cache /app/data /app/logs /tmp/candlelite && \
    chown -R nija:nija /app /tmp/candlelite
USER nija
HEALTHCHECK --interval=30s --timeout=30s --start-period=300s --retries=5 \
    CMD python -S -c "import json,urllib.request; r=urllib.request.urlopen('http://127.0.0.1:5000/healthz',timeout=10); p=json.loads(r.read().decode('utf-8')); raise SystemExit(0 if r.status==200 and p.get('status')=='alive' else 1)"
CMD ["bash", "scripts/production_bootstrap.sh"]
