#!/usr/bin/env bash
# NIJA production bootstrap
# Resolves deployment provenance and normalizes monetary trading guards before
# the main startup script evaluates live-trading safety checks.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
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
            echo "🔑 Secret alias normalized: ${canonical}<-${alias}"
            return 0
        fi
    done
    return 0
}

# Existing deployments may retain older Kraken variable names. Promote aliases
# before start.sh validates credentials; never print or persist secret values.
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

# Existing Render services created outside the current Blueprint can miss
# fromService environment injection. Restore only the known private Key Value
# endpoint supplied by the operator. This does not grant writer authority or
# weaken any distributed-lock requirement.
_RENDER_RUNTIME=false
case "${RENDER:-}" in
    1|true|TRUE|yes|YES|on|ON|enabled|ENABLED) _RENDER_RUNTIME=true ;;
esac
if [[ -n "${RENDER_SERVICE_ID:-}${RENDER_SERVICE_NAME:-}${RENDER_INSTANCE_ID:-}${RENDER_GIT_BRANCH:-}${RENDER_GIT_COMMIT:-}" ]]; then
    _RENDER_RUNTIME=true
fi
if [[ "${_RENDER_RUNTIME}" == "true" ]] \
    && [[ -z "${NIJA_REDIS_URL:-}${REDIS_PRIVATE_URL:-}${REDIS_PUBLIC_URL:-}${REDIS_URL:-}${REDIS_TLS_URL:-}" ]]; then
    _RENDER_REDIS_FALLBACK="${NIJA_RENDER_REDIS_FALLBACK_URL:-redis://red-d98dsl5aeets73fpb0hg:6379}"
    if [[ "${_RENDER_REDIS_FALLBACK}" =~ ^redis://red-[A-Za-z0-9-]+:6379/?$ ]]; then
        export NIJA_REDIS_URL="${_RENDER_REDIS_FALLBACK%/}"
        export REDIS_URL="${NIJA_REDIS_URL}"
        export NIJA_RENDER_REDIS_FALLBACK_APPLIED=1
        echo "🛟 Render private Redis fallback applied (${NIJA_REDIS_URL#redis://})"
    else
        echo "⚠️  Render Redis fallback rejected: expected redis://red-<service>:6379"
    fi
fi

# Render must be able to verify process liveness while Redis authority and broker
# hydration are still fail-closed. This endpoint never reports trading readiness
# and never changes execution state.
if [[ "${_RENDER_RUNTIME}" == "true" ]] && command -v python3 >/dev/null 2>&1 && [[ -f render_liveness_server.py ]]; then
    python3 -u render_liveness_server.py &
    _RENDER_LIVENESS_PID=$!
    export NIJA_RENDER_LIVENESS_PID="${_RENDER_LIVENESS_PID}"
    echo "🌐 Early Render liveness server started pid=${_RENDER_LIVENESS_PID} port=${PORT:-5000}"
fi

_is_placeholder() {
    local value="${1:-}"
    case "${value}" in
        ""|unknown|UNKNOWN|null|NULL|none|NONE|\$RENDER_*|\${RENDER_*}|\$RAILWAY_*|\${RAILWAY_*}|\$\{\{*\}\})
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

_first_valid() {
    local candidate
    for candidate in "$@"; do
        if ! _is_placeholder "${candidate}"; then
            printf '%s' "${candidate}"
            return 0
        fi
    done
    return 1
}

_sanitize_branch() {
    printf '%s' "${1:-}" | tr -cd '[:alnum:]._/-'
}

_sanitize_revision() {
    printf '%s' "${1:-}" | tr -cd '[:alnum:]._:-'
}

# Load build-time metadata, but never allow stale "unknown" values to outrank
# Render's runtime provenance variables.
_BUILD_GIT_BRANCH=""
_BUILD_GIT_COMMIT=""
_BUILD_GIT_COMMIT_SHORT=""
if [[ -f .env.build ]]; then
    # shellcheck disable=SC1091
    source .env.build
    _BUILD_GIT_BRANCH="${GIT_BRANCH:-}"
    _BUILD_GIT_COMMIT="${GIT_COMMIT:-}"
    _BUILD_GIT_COMMIT_SHORT="${GIT_COMMIT_SHORT:-}"
fi

# Render publishes these at build and runtime. Keep provider-neutral fallbacks
# so local CI and an emergency migration remain traceable.
_RUNTIME_GIT_BRANCH="${RENDER_GIT_BRANCH:-${RAILWAY_GIT_BRANCH:-${SOURCE_BRANCH:-${GITHUB_REF_NAME:-}}}}"
_RUNTIME_GIT_COMMIT="${RENDER_GIT_COMMIT:-${RAILWAY_GIT_COMMIT_SHA:-${SOURCE_VERSION:-${COMMIT_SHA:-${GITHUB_SHA:-}}}}}"

_RESOLVED_BRANCH="$(_first_valid "${_RUNTIME_GIT_BRANCH}" "${_BUILD_GIT_BRANCH}" "${GIT_BRANCH:-}" 2>/dev/null || true)"
_RESOLVED_COMMIT="$(_first_valid "${_RUNTIME_GIT_COMMIT}" "${_BUILD_GIT_COMMIT}" "${_BUILD_GIT_COMMIT_SHORT}" "${GIT_COMMIT:-}" 2>/dev/null || true)"
_METADATA_SOURCE="environment"
_PLATFORM="local"

if ! _is_placeholder "${RENDER:-}" || ! _is_placeholder "${RENDER_GIT_BRANCH:-}" || ! _is_placeholder "${RENDER_GIT_COMMIT:-}"; then
    _METADATA_SOURCE="render-git"
    _PLATFORM="Render"
elif ! _is_placeholder "${RAILWAY_GIT_BRANCH:-}" || ! _is_placeholder "${RAILWAY_GIT_COMMIT_SHA:-}"; then
    _METADATA_SOURCE="railway-git"
    _PLATFORM="Railway"
fi

if _is_placeholder "${_RESOLVED_BRANCH}" && command -v git >/dev/null 2>&1; then
    _RESOLVED_BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
    _METADATA_SOURCE="git"
fi
if _is_placeholder "${_RESOLVED_COMMIT}" && command -v git >/dev/null 2>&1; then
    _RESOLVED_COMMIT="$(git rev-parse HEAD 2>/dev/null || true)"
    _METADATA_SOURCE="git"
fi

# Render service/instance identity is auditable in the Render dashboard and API.
# Use it only when Git metadata is unavailable; live mode still fails closed if
# no traceable provider identity exists.
if _is_placeholder "${_RESOLVED_BRANCH}" && ! _is_placeholder "${RENDER_SERVICE_NAME:-}"; then
    _RESOLVED_BRANCH="render/${RENDER_SERVICE_NAME}"
    _METADATA_SOURCE="render-service"
    _PLATFORM="Render"
fi
if _is_placeholder "${_RESOLVED_COMMIT}" && ! _is_placeholder "${RENDER_SERVICE_ID:-}"; then
    _RESOLVED_COMMIT="render:${RENDER_SERVICE_ID}"
    _METADATA_SOURCE="render-service"
    _PLATFORM="Render"
fi
if _is_placeholder "${_RESOLVED_COMMIT}" && ! _is_placeholder "${RENDER_INSTANCE_ID:-}"; then
    _RESOLVED_COMMIT="render-instance:${RENDER_INSTANCE_ID}"
    _METADATA_SOURCE="render-instance"
    _PLATFORM="Render"
fi

# Retain Railway identity fallbacks only for portability; Render always wins.
if _is_placeholder "${_RESOLVED_BRANCH}" && ! _is_placeholder "${RAILWAY_SERVICE_NAME:-}"; then
    _RESOLVED_BRANCH="railway/${RAILWAY_SERVICE_NAME}"
    _METADATA_SOURCE="railway-service"
    _PLATFORM="Railway"
fi
if _is_placeholder "${_RESOLVED_COMMIT}" && ! _is_placeholder "${RAILWAY_DEPLOYMENT_ID:-}"; then
    _RESOLVED_COMMIT="railway:${RAILWAY_DEPLOYMENT_ID}"
    _METADATA_SOURCE="railway-deployment"
    _PLATFORM="Railway"
fi

_RESOLVED_BRANCH="$(_sanitize_branch "${_RESOLVED_BRANCH}")"
_RESOLVED_COMMIT="$(_sanitize_revision "${_RESOLVED_COMMIT}")"

if _is_placeholder "${_RESOLVED_BRANCH}"; then
    _RESOLVED_BRANCH="unknown"
fi
if _is_placeholder "${_RESOLVED_COMMIT}"; then
    _RESOLVED_COMMIT="unknown"
fi

export GIT_BRANCH="${_RESOLVED_BRANCH}"
export GIT_COMMIT="${_RESOLVED_COMMIT}"
case "${GIT_COMMIT}" in
    render:*|render-instance:*|railway:*) export GIT_COMMIT_SHORT="${GIT_COMMIT}" ;;
    *) export GIT_COMMIT_SHORT="${GIT_COMMIT:0:12}" ;;
esac
export NIJA_GIT_METADATA_SOURCE="${_METADATA_SOURCE}"
if _is_placeholder "${BUILD_TIMESTAMP:-}"; then
    export BUILD_TIMESTAMP="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
else
    export BUILD_TIMESTAMP
fi

# start.sh sources .env.build again. Persist the resolved runtime values
# atomically so stale build-time metadata cannot overwrite Render's values.
_METADATA_TMP=".env.build.runtime.$$"
trap 'rm -f "${_METADATA_TMP}"' EXIT
{
    printf 'export GIT_BRANCH=%q\n' "${GIT_BRANCH}"
    printf 'export GIT_COMMIT=%q\n' "${GIT_COMMIT}"
    printf 'export GIT_COMMIT_SHORT=%q\n' "${GIT_COMMIT_SHORT}"
    printf 'export BUILD_TIMESTAMP=%q\n' "${BUILD_TIMESTAMP}"
    printf 'export NIJA_GIT_METADATA_SOURCE=%q\n' "${NIJA_GIT_METADATA_SOURCE}"
} > "${_METADATA_TMP}"
mv "${_METADATA_TMP}" .env.build
trap - EXIT

echo "🔎 Deployment provenance resolved"
echo "   Platform: ${_PLATFORM}"
echo "   Source: ${NIJA_GIT_METADATA_SOURCE}"
echo "   Branch: ${GIT_BRANCH}"
echo "   Commit: ${GIT_COMMIT_SHORT}"

# Runtime authority, trading state, fencing tokens, and heartbeat state are
# process-derived facts. Render dashboard variables must never pre-grant them to
# a new process. Reset stale values before Python acquires the current writer
# lease; the normal lock/capital/state-machine path will set them again only
# after proof succeeds.
_PREVIOUS_RUNTIME_AUTHORITY="${NIJA_RUNTIME_EXECUTION_AUTHORITY:-unset}"
_PREVIOUS_RUNTIME_STATE="${NIJA_RUNTIME_TRADING_STATE:-unset}"
export NIJA_RUNTIME_EXECUTION_AUTHORITY="0"
export NIJA_RUNTIME_TRADING_STATE="OFF"
export NIJA_WRITER_LEASE_ACQUIRED="0"
export NIJA_WRITER_HEARTBEAT_ACTIVE="0"
unset NIJA_WRITER_FENCING_TOKEN
unset NIJA_WRITER_LEASE_GENERATION
unset NIJA_WRITER_HEARTBEAT_ALIVE_TS
unset NIJA_WRITER_LOCK_ACQUIRED_AT

# Kraken is the required primary platform broker. Coinbase is optional/isolated,
# so one fresh positive authoritative broker is sufficient by default. Operators
# can explicitly configure a stricter requirement.
export NIJA_RUNTIME_AUTHORITY_CONVERGENCE_MIN_BROKERS="${NIJA_RUNTIME_AUTHORITY_CONVERGENCE_MIN_BROKERS:-1}"
export NIJA_RENDER_STARTUP_RECOVERY_ENABLED="${NIJA_RENDER_STARTUP_RECOVERY_ENABLED:-true}"
export NIJA_RENDER_STARTUP_RECOVERY_INTERVAL_S="${NIJA_RENDER_STARTUP_RECOVERY_INTERVAL_S:-5}"
export NIJA_RENDER_STARTUP_RECOVERY_MAX_ATTEMPTS="${NIJA_RENDER_STARTUP_RECOVERY_MAX_ATTEMPTS:-60}"

echo "🧭 Derived runtime state reset for current process"
echo "   Previous authority: ${_PREVIOUS_RUNTIME_AUTHORITY} → 0"
echo "   Previous state: ${_PREVIOUS_RUNTIME_STATE} → OFF"
echo "   Required valid brokers for convergence: ${NIJA_RUNTIME_AUTHORITY_CONVERGENCE_MIN_BROKERS}"
echo ""

_is_positive_money() {
    python - "$1" <<'PY'
from decimal import Decimal, InvalidOperation
import sys
try:
    value = Decimal(sys.argv[1])
except (InvalidOperation, IndexError):
    raise SystemExit(1)
raise SystemExit(0 if value > 0 else 1)
PY
}

_max_money() {
    python - "$@" <<'PY'
from decimal import Decimal
import sys
values = [Decimal(value) for value in sys.argv[1:]]
print(f"{max(values):.2f}")
PY
}

_MIN_TRADE="${MIN_TRADE_USD:-3.50}"
_MIN_CASH="${MIN_CASH_TO_BUY:-5.00}"
_MIN_BALANCE="${MINIMUM_TRADING_BALANCE:-5.00}"
_MIN_RESERVE="${NIJA_MIN_CASH_RESERVE_USD:-5.00}"

for value_name in _MIN_TRADE _MIN_CASH _MIN_BALANCE _MIN_RESERVE; do
    value="${!value_name}"
    if ! _is_positive_money "${value}"; then
        echo "❌ Invalid monetary guard ${value_name#_}=${value}; expected a positive number"
        exit 1
    fi
done

# Never lower an operator's stricter value. Ensure an account that qualifies
# can fund at least one minimum order and meets the configured cash reserve floor.
export MIN_TRADE_USD="$(_max_money "${_MIN_TRADE}" "3.50")"
export MIN_CASH_TO_BUY="$(_max_money "${_MIN_CASH}" "${MIN_TRADE_USD}" "${_MIN_RESERVE}")"
export MINIMUM_TRADING_BALANCE="$(_max_money "${_MIN_BALANCE}" "${MIN_CASH_TO_BUY}")"
export MIN_NOTIONAL_USD="${MIN_NOTIONAL_USD:-${MIN_TRADE_USD}}"
export MIN_POSITION_USD="${MIN_POSITION_USD:-${MIN_TRADE_USD}}"

echo "🛡️  Normalized trading guards"
echo "   MIN_TRADE_USD=${MIN_TRADE_USD}"
echo "   MIN_CASH_TO_BUY=${MIN_CASH_TO_BUY}"
echo "   MINIMUM_TRADING_BALANCE=${MINIMUM_TRADING_BALANCE}"
echo "   MIN_NOTIONAL_USD=${MIN_NOTIONAL_USD}"
echo ""

exec bash "${ROOT_DIR}/start.sh" "$@"
