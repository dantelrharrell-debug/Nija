#!/usr/bin/env bash
# NIJA production bootstrap
# Resolves deployment provenance and normalizes monetary trading guards before
# the main startup script evaluates live-trading safety checks.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${ROOT_DIR}"

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
