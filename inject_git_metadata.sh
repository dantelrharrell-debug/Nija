#!/usr/bin/env bash
# Git Metadata Injection for NIJA builds.
# Priority: explicit build args -> Railway build metadata -> local Git checkout
# -> Railway deployment identity. Unknown metadata remains fail-closed at runtime.

set -euo pipefail

echo "🔍 Injecting Git metadata..."

_is_placeholder() {
    local value="${1:-}"
    case "${value}" in
        ""|unknown|UNKNOWN|null|NULL|none|NONE|\$RAILWAY_*|\${RAILWAY_*}|\$\{\{*\}\})
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

_sanitize_branch() {
    printf '%s' "${1:-}" | tr -cd '[:alnum:]._/-'
}

_sanitize_revision() {
    printf '%s' "${1:-}" | tr -cd '[:alnum:]._:-'
}

_resolved_branch="${GIT_BRANCH:-}"
_resolved_commit="${GIT_COMMIT:-}"
_metadata_source="explicit-build-args"

if _is_placeholder "${_resolved_branch}" && ! _is_placeholder "${RAILWAY_GIT_BRANCH:-}"; then
    _resolved_branch="${RAILWAY_GIT_BRANCH}"
    _metadata_source="railway-git"
fi
if _is_placeholder "${_resolved_commit}" && ! _is_placeholder "${RAILWAY_GIT_COMMIT_SHA:-}"; then
    _resolved_commit="${RAILWAY_GIT_COMMIT_SHA}"
    _metadata_source="railway-git"
fi

if _is_placeholder "${_resolved_branch}" && command -v git >/dev/null 2>&1; then
    _resolved_branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
    _metadata_source="git-checkout"
fi
if _is_placeholder "${_resolved_commit}" && command -v git >/dev/null 2>&1; then
    _resolved_commit="$(git rev-parse HEAD 2>/dev/null || true)"
    _metadata_source="git-checkout"
fi

if _is_placeholder "${_resolved_branch}" && ! _is_placeholder "${RAILWAY_ENVIRONMENT_NAME:-}"; then
    _resolved_branch="railway/${RAILWAY_ENVIRONMENT_NAME}"
    _metadata_source="railway-deployment"
fi
if _is_placeholder "${_resolved_commit}" && ! _is_placeholder "${RAILWAY_DEPLOYMENT_ID:-}"; then
    _resolved_commit="railway:${RAILWAY_DEPLOYMENT_ID}"
    _metadata_source="railway-deployment"
fi

_resolved_branch="$(_sanitize_branch "${_resolved_branch}")"
_resolved_commit="$(_sanitize_revision "${_resolved_commit}")"

if _is_placeholder "${_resolved_branch}"; then
    _resolved_branch="unknown"
fi
if _is_placeholder "${_resolved_commit}"; then
    _resolved_commit="unknown"
fi

export GIT_BRANCH="${_resolved_branch}"
export GIT_COMMIT="${_resolved_commit}"
if [[ "${GIT_COMMIT}" == railway:* ]]; then
    export GIT_COMMIT_SHORT="${GIT_COMMIT}"
else
    export GIT_COMMIT_SHORT="${GIT_COMMIT:0:12}"
fi

if ! _is_placeholder "${BUILD_TIMESTAMP:-}"; then
    export BUILD_TIMESTAMP
else
    export BUILD_TIMESTAMP="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
fi

printf '📋 Metadata Source: %s\n' "${_metadata_source}"
printf '📋 Git Branch: %s\n' "${GIT_BRANCH}"
printf '📋 Git Commit: %s\n' "${GIT_COMMIT_SHORT}"
printf '📋 Build Time: %s\n' "${BUILD_TIMESTAMP}"

cat > bot/version_info.py <<EOF_VERSION
"""
NIJA Version Information
Auto-generated during build process - DO NOT EDIT MANUALLY
"""

GIT_BRANCH = "${GIT_BRANCH}"
GIT_COMMIT = "${GIT_COMMIT}"
GIT_COMMIT_SHORT = "${GIT_COMMIT_SHORT}"
BUILD_TIMESTAMP = "${BUILD_TIMESTAMP}"
METADATA_SOURCE = "${_metadata_source}"

VERSION = "7.3.0"
RELEASE_NAME = "Autonomous Scaling Engine"


def get_version_string() -> str:
    return f"NIJA v{VERSION} ({RELEASE_NAME}) - {GIT_BRANCH}@{GIT_COMMIT_SHORT}"


def get_full_version_info() -> dict:
    return {
        "version": VERSION,
        "release_name": RELEASE_NAME,
        "git_branch": GIT_BRANCH,
        "git_commit": GIT_COMMIT,
        "git_commit_short": GIT_COMMIT_SHORT,
        "build_timestamp": BUILD_TIMESTAMP,
        "metadata_source": METADATA_SOURCE,
    }
EOF_VERSION

echo "✅ Version info generated: bot/version_info.py"

# Replace rather than append so image rebuilds cannot retain stale duplicate exports.
{
    printf 'export GIT_BRANCH=%q\n' "${GIT_BRANCH}"
    printf 'export GIT_COMMIT=%q\n' "${GIT_COMMIT}"
    printf 'export GIT_COMMIT_SHORT=%q\n' "${GIT_COMMIT_SHORT}"
    printf 'export BUILD_TIMESTAMP=%q\n' "${BUILD_TIMESTAMP}"
    printf 'export NIJA_GIT_METADATA_SOURCE=%q\n' "${_metadata_source}"
} > .env.build

echo "✅ Build environment variables saved to .env.build"
echo "🚀 Git metadata injection complete!"
