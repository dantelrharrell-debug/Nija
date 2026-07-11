FROM python:3.11-slim

# Install git and redis-cli for runtime diagnostics
RUN apt-get update && apt-get install -y git redis-tools && rm -rf /var/lib/apt/lists/*

# Create non-root user for security
RUN groupadd -r nija && useradd -r -g nija -u 1000 nija

# Set working directory
WORKDIR /app

# Copy requirements first for better Docker layer caching
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Explicitly copy runtime/preflight scripts into the image.
COPY scripts/ scripts/

# Copy application code
COPY . .

# The verifier is required by production_bootstrap.sh. Keep the source script
# fail-closed while preserving the verifier's real non-zero status in the image.
RUN python -S -c 'from pathlib import Path; p=Path("/app/scripts/production_bootstrap.sh"); s=p.read_text(encoding="utf-8"); old="if ! python3 -S \"${SCRIPT_DIR}/three_venue_config_check.py\"; then\n    _CHECK_EXIT=$?\n"; new="if python3 -S \"${SCRIPT_DIR}/three_venue_config_check.py\"; then\n    :\nelse\n    _CHECK_EXIT=$?\n"; assert s.count(old) == 1, "unexpected three-venue bootstrap block"; p.write_text(s.replace(old, new, 1), encoding="utf-8")' && \
    bash -n /app/scripts/production_bootstrap.sh

# Fail the image build immediately if entrypoint Python files or startup guards
# are syntactically invalid.
RUN python -m py_compile \
        /app/main.py \
        /app/bot.py \
        /app/render_liveness_server.py \
        /app/render_readiness_state_bridge.py \
        /app/prebot_writer_authority_bootstrap.py \
        /app/prebot_writer_authority_fail_closed.py \
        /app/source_runtime_guard_bootstrap.py \
        /app/venue_readiness_execution_repair_patch.py \
        /app/secondary_venue_activation_patch.py \
        /app/secondary_venue_strict_readiness_patch.py \
        /app/bot/activation_pending_commit_monitor_patch.py \
        /app/bot/writer_lock_release_guard.py \
        /app/bot/global_runtime_startup_guards.py \
        /app/import_hook_recursion_shield_patch.py \
        /app/disconnected_broker_execution_guard_patch.py \
        /app/scripts/three_venue_config_check.py

# Install startup guards before sitecustomize executes. Python processes .pth
# files before the entry script directory is reliably importable, so every hook
# first adds /app as a plain path line and only then imports its module.
#
# Render zero-downtime deployments expose /healthz before waiting for the active
# writer to release its lease. The .pth hook therefore leaves the replacement
# fail-closed on Render; source_runtime_guard_bootstrap acquires the same canonical
# Redis lease before any bot.* import. Other providers retain early acquisition.
RUN python -c "import pathlib, site; root = pathlib.Path(site.getsitepackages()[0]); prefix = '/app\n'; p0 = root / '000_nija_prebot_writer_authority.pth'; p0.write_text(prefix + 'import prebot_writer_authority_fail_closed as _nija_prebot_writer; _nija_prebot_writer.install(defer_if_render=True)\n', encoding='utf-8'); p1 = root / 'nija_import_hook_recursion_shield.pth'; p1.write_text(prefix + 'import import_hook_recursion_shield_patch as _nija_shield; _nija_shield.install_import_hook()\n', encoding='utf-8'); p2 = root / 'nija_disconnected_broker_execution_guard.pth'; p2.write_text(prefix + 'import disconnected_broker_execution_guard_patch as _nija_broker_guard; _nija_broker_guard.install_import_hook()\n', encoding='utf-8'); assert p0.is_file() and p1.is_file() and p2.is_file()"

# Reproduce provider startup from outside the repository. The hooks must be
# importable during Python site initialization without relying on cwd=/app.
RUN cd /tmp && python -c "import prebot_writer_authority_fail_closed, import_hook_recursion_shield_patch, disconnected_broker_execution_guard_patch; print('NIJA_PTH_IMPORT_SMOKE_OK')"

# Ensure Redis connectivity and production bootstrap scripts are present and executable.
RUN test -f /app/scripts/redis_connectivity_check.sh && \
    test -f /app/scripts/production_bootstrap.sh && \
    test -f /app/scripts/three_venue_config_check.py && \
    test -f /app/scripts/render_entrypoint.sh && \
    chmod +x /app/scripts/redis_connectivity_check.sh \
             /app/scripts/production_bootstrap.sh \
             /app/scripts/render_entrypoint.sh && \
    if [ -f /app/scripts/debug_startup_safe_mode.sh ]; then chmod +x /app/scripts/debug_startup_safe_mode.sh; fi

# Make other scripts executable when present in build context
RUN if [ -d /app/scripts ]; then chmod +x /app/scripts/*.sh || true; fi

# Render translates service environment variables into Docker build arguments.
# Declare Render's documented provenance variables so build-time version metadata
# can be generated without depending on a .git directory in the final image.
ARG GIT_BRANCH=""
ARG GIT_COMMIT=""
ARG RENDER_GIT_BRANCH=""
ARG RENDER_GIT_COMMIT=""
ARG RENDER_SERVICE_ID=""
ARG RENDER_SERVICE_NAME=""

# Provider-neutral portability fallbacks.
ARG RAILWAY_GIT_BRANCH=""
ARG RAILWAY_GIT_COMMIT_SHA=""
ARG RAILWAY_DEPLOYMENT_ID=""
ARG RAILWAY_ENVIRONMENT_NAME=""
ARG BUILD_TIMESTAMP=""

# Keep explicit values available at runtime; .env.build supplies the resolved
# Render/Git fallback generated by inject_git_metadata.sh.
ENV GIT_BRANCH=${GIT_BRANCH}
ENV GIT_COMMIT=${GIT_COMMIT}
ENV BUILD_TIMESTAMP=${BUILD_TIMESTAMP}

# Generate traceable version metadata and fail the image build if generation fails.
RUN ./inject_git_metadata.sh

# Redirect candlelite config to a writable /tmp path so the okx SDK never
# tries to write SETTINGS.config into the read-only site-packages directory.
# This must be an ENV directive (not set in Python) so the variable is present
# before any Python import runs.
ENV CANDLELITE_CONFIG_DIR=/tmp/candlelite

# Create necessary directories and set permissions
RUN mkdir -p /app/cache /app/data /app/logs /tmp/candlelite && \
    chown -R nija:nija /app /tmp/candlelite

# Switch to non-root user
USER nija

# Security: Drop all capabilities and run as non-root.
# Use isolated Python (-S) and stdlib-only HTTP so Docker health checks cannot
# execute .pth/sitecustomize/usercustomize trading hooks or release writer locks.
HEALTHCHECK --interval=30s --timeout=30s --start-period=300s --retries=5 \
    CMD python -S -c "import json,urllib.request; r=urllib.request.urlopen('http://127.0.0.1:5000/healthz',timeout=10); p=json.loads(r.read().decode('utf-8')); raise SystemExit(0 if r.status==200 and p.get('status')=='alive' else 1)"

# Default command: resolve Render deployment provenance and guards before start.sh.
CMD ["bash", "scripts/production_bootstrap.sh"]
