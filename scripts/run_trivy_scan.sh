#!/usr/bin/env bash
# Only scan after a fresh database download from an explicit trusted registry.
set -euo pipefail

if [[ "${1:-}" != "fs" && "${1:-}" != "image" ]]; then
    echo "Usage: run_trivy_scan.sh {fs|image} [scan arguments...]" >&2
    exit 2
fi

acquired=false
for repository in \
    mirror.gcr.io/aquasec/trivy-db:2 \
    ghcr.io/aquasecurity/trivy-db:2 \
    public.ecr.aws/aquasecurity/trivy-db:2; do
    for attempt in 1 2 3; do
        if trivy image --download-db-only --db-repository "${repository}" --timeout 5m; then
            acquired=true
            break 2
        fi
        echo "::warning::Trivy DB acquisition failed: ${repository} (attempt ${attempt}/3)" >&2
        if [[ "${attempt}" != 3 ]]; then
            sleep "$((attempt * 5))"
        fi
    done
done

if [[ "${acquired}" != true ]]; then
    echo "::error::No trusted Trivy vulnerability database available; scan denied" >&2
    exit 1
fi

# No stale-cache fallback. Propagate both scanner errors and HIGH/CRITICAL findings.
exec trivy "$@" --skip-db-update --exit-code 1
