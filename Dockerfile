FROM python:3.11-slim

RUN apt-get update && apt-get install -y git redis-tools && rm -rf /var/lib/apt/lists/*
RUN groupadd -r nija && useradd -r -g nija -u 1000 nija
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY scripts/ scripts/
COPY . .
RUN bash -n /app/scripts/production_bootstrap.sh
RUN python -m py_compile \
        /app/main.py \
        /app/bot.py \
        /app/render_liveness_server.py \
        /app/render_readiness_state_bridge.py \
        /app/prebot_writer_authority_bootstrap.py \
        /app/prebot_writer_authority_fail_closed.py \
        /app/source_runtime_guard_bootstrap.py \
        /app/runtime_patch_idempotence_guard.py \
        /app/account_capital_isolation_v4_patch.py \
        /app/coinbase_authenticated_connect_recovery_patch.py \
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
        /app/bot/daily_gain_profit_harvest_patch.py \
        /app/bot/kraken_tpe_min_notional_allocation_patch.py \
        /app/bot/runtime_guard_audit_patch.py \
        /app/import_hook_recursion_shield_patch.py \
        /app/disconnected_broker_execution_guard_patch.py \
        /app/scripts/three_venue_config_check.py

RUN python -c "import pathlib, site; root = pathlib.Path(site.getsitepackages()[0]); prefix = '/app\n'; p0 = root / '000_nija_prebot_writer_authority.pth'; p0.write_text(prefix + 'import prebot_writer_authority_fail_closed as _nija_prebot_writer; _nija_prebot_writer.install(defer_if_render=True)\n', encoding='utf-8'); p1 = root / 'nija_import_hook_recursion_shield.pth'; p1.write_text(prefix + 'import import_hook_recursion_shield_patch as _nija_shield; _nija_shield.install_import_hook()\n', encoding='utf-8'); p2 = root / 'nija_disconnected_broker_execution_guard.pth'; p2.write_text(prefix + 'import disconnected_broker_execution_guard_patch as _nija_broker_guard; _nija_broker_guard.install_import_hook()\n', encoding='utf-8'); p3 = root / 'nija_secondary_venue_connect_semantics.pth'; p3.write_text(prefix + 'import secondary_venue_connect_semantics_repair as _nija_secondary_connect\n', encoding='utf-8'); p4 = root / '0001_nija_secondary_venue_runtime_diagnostics.pth'; p4.write_text(prefix + 'import secondary_venue_runtime_diagnostics as _nija_secondary_diag\n', encoding='utf-8'); p5 = root / '0002_nija_profit_first_loss_prevention.pth'; p5.write_text(prefix + 'import profit_first_loss_prevention_patch as _nija_profit_first; _nija_profit_first.install_import_hook()\n', encoding='utf-8'); p6 = root / '0003_nija_runtime_patch_idempotence.pth'; p6.write_text(prefix + 'import runtime_patch_idempotence_guard as _nija_patch_idempotence; _nija_patch_idempotence.install()\n', encoding='utf-8'); p7 = root / '0004_nija_account_capital_isolation.pth'; p7.write_text(prefix + 'import account_capital_isolation_v4_patch as _nija_account_isolation; _nija_account_isolation.install()\n', encoding='utf-8'); assert all(p.is_file() for p in (p0,p1,p2,p3,p4,p5,p6,p7))"
RUN cd /tmp && python -c "import prebot_writer_authority_fail_closed, import_hook_recursion_shield_patch, disconnected_broker_execution_guard_patch, secondary_venue_connect_semantics_repair, secondary_venue_runtime_diagnostics, profit_first_loss_prevention_patch, runtime_patch_idempotence_guard, account_capital_isolation_v4_patch, coinbase_authenticated_connect_recovery_patch; print('NIJA_PTH_IMPORT_SMOKE_OK')"

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
