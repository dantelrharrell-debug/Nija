#!/bin/bash
set -e  # Exit on error

echo "🔥 PYTHON ENTRYPOINT HIT (start.sh)"

echo "=============================="
echo "    STARTING NIJA TRADING BOT"
echo "=============================="

_INSTANCE_HOSTNAME="${HOSTNAME:-$(hostname 2>/dev/null || echo unknown-host)}"
_INSTANCE_DEPLOYMENT_ID="${RAILWAY_DEPLOYMENT_ID:-}"
_INSTANCE_REPLICA_ID="${RAILWAY_REPLICA_ID:-${RAILWAY_REPLICA_NAME:-}}"
_INSTANCE_SERVICE_ID="${RAILWAY_SERVICE_ID:-}"
_INSTANCE_ID="${_INSTANCE_DEPLOYMENT_ID:-${_INSTANCE_REPLICA_ID:-${_INSTANCE_HOSTNAME}}}"
echo "🆔 Instance: instance=${_INSTANCE_ID} host=${_INSTANCE_HOSTNAME} pid=$$ container=${HOSTNAME:-unknown} deployment=${_INSTANCE_DEPLOYMENT_ID:-n/a} replica=${_INSTANCE_REPLICA_ID:-n/a} service=${_INSTANCE_SERVICE_ID:-n/a}"
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# SINGLE-INSTANCE GUARD (shell level)
#
# Ensures only one bot.py process runs inside this container at any time.
# This fires before Python initialises, so it catches scenarios where
# start.sh is invoked a second time while a previous instance is still live.
#
# Cross-container / cross-deployment protection is handled separately by the
# distributed Redis lock inside bot.py (set NIJA_REDIS_URL, REDIS_URL,
# REDIS_PRIVATE_URL, or REDIS_PUBLIC_URL to enable it).
# ─────────────────────────────────────────────────────────────────────────────
_SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
_PID_FILE="${_SCRIPT_DIR}/data/nija.pid"

# Seconds to wait for a graceful shutdown before escalating to SIGKILL.
_GRACE_PERIOD_SECONDS=10

# Fail-fast singleton mode (default ON): if another NIJA process is active,
# exit immediately instead of waiting/killing in-place.
_FAIL_FAST_SINGLETON_RAW=$(printf "%s" "${NIJA_FAIL_FAST_SINGLETON:-true}" | tr '[:upper:]' '[:lower:]')
_FAIL_FAST_SINGLETON=true
if [ "${_FAIL_FAST_SINGLETON_RAW}" = "0" ] || [ "${_FAIL_FAST_SINGLETON_RAW}" = "false" ] || [ "${_FAIL_FAST_SINGLETON_RAW}" = "no" ] || [ "${_FAIL_FAST_SINGLETON_RAW}" = "off" ]; then
    _FAIL_FAST_SINGLETON=false
fi

# Patterns that identify a running NIJA bot process in /proc/<pid>/cmdline.
# These match the main entry-points of the bot so we never kill unrelated PIDs
# that happen to share the same numeric PID after a container restart.
_NIJA_PROCESS_PATTERN="bot\.py|trading_strategy|nija_core_loop|tradingview_webhook"

_terminate_duplicate_bot() {
    local _pid="$1"
    echo "⚠️  Duplicate NIJA bot detected (PID $_pid) — sending SIGTERM for graceful shutdown..."
    kill -TERM "$_pid" 2>/dev/null || true
    # Wait up to _GRACE_PERIOD_SECONDS for graceful exit
    local _waited=0
    while [ "$_waited" -lt "$_GRACE_PERIOD_SECONDS" ]; do
        sleep 1
        _waited=$((_waited + 1))
        kill -0 "$_pid" 2>/dev/null || { echo "   ✅ Process $_pid exited cleanly."; return; }
    done
    # Force-kill if still alive after grace period
    echo "   ⚠️  Process $_pid still running after ${_GRACE_PERIOD_SECONDS}s — sending SIGKILL..."
    kill -9 "$_pid" 2>/dev/null || true
    sleep 1
    echo "   ✅ Process $_pid killed."
}

if [ -f "$_PID_FILE" ]; then
    _OLD_PID=$(head -1 "$_PID_FILE" 2>/dev/null | tr -d '[:space:]' || echo "")
    if [ -n "$_OLD_PID" ] && echo "$_OLD_PID" | grep -qE '^[0-9]+$'; then
        if kill -0 "$_OLD_PID" 2>/dev/null; then
            # PID is alive — verify it belongs to a NIJA bot process
            _CMDLINE=""
            if [ -r "/proc/$_OLD_PID/cmdline" ]; then
                _CMDLINE=$(tr '\0' ' ' < "/proc/$_OLD_PID/cmdline" 2>/dev/null || echo "")
            fi
            if echo "$_CMDLINE" | grep -qE "$_NIJA_PROCESS_PATTERN"; then
                if [ "${_FAIL_FAST_SINGLETON}" = "true" ]; then
                    echo "❌ Another NIJA instance is active (PID $_OLD_PID) — exiting (fail-fast singleton mode)"
                    exit 1
                fi
                _terminate_duplicate_bot "$_OLD_PID"
                rm -f "$_PID_FILE"
            else
                echo "⚠️  PID $_OLD_PID in lock file is not a NIJA process (PID reused) — removing stale lock."
                rm -f "$_PID_FILE"
            fi
        else
            echo "⚠️  Stale lock file found (PID $_OLD_PID not running) — removing."
            rm -f "$_PID_FILE"
        fi
    else
        echo "⚠️  Lock file contains invalid PID — removing."
        rm -f "$_PID_FILE"
    fi
fi


# Parse command line arguments
WAIT_FOR_CONFIG="${WAIT_FOR_CONFIG:-false}"  # Default from environment
for arg in "$@"; do
    case $arg in
        --wait-for-config)
            WAIT_FOR_CONFIG="true"
            shift
            ;;
    esac
done

# Show wait-for-config mode status
if [ "$WAIT_FOR_CONFIG" = "true" ]; then
    echo "⏸️  Wait-for-config mode: ENABLED"
    echo ""
    echo "   Health endpoint will report one of three states:"
    echo "   • BLOCKED (503) - Missing config, waiting for credentials"
    echo "   • READY   (200) - Config complete, bot operational"
    echo "   • ERROR   (500) - Hard error detected, needs intervention"
    echo ""
    echo "   This prevents restart loops while providing clear status signals."
else
    echo "📋 Wait-for-config mode: DISABLED (use --wait-for-config or set WAIT_FOR_CONFIG=true)"
    echo "   If config is missing, container will exit with code 0"
fi
echo ""

# Optional platform replica guard (default expects singleton = 1).
# When a known replica-count environment variable is available and exceeds
# NIJA_EXPECTED_REPLICAS, fail fast to avoid overlapping trading instances.
_EXPECTED_REPLICAS="${NIJA_EXPECTED_REPLICAS:-1}"
_REPLICA_COUNT_RAW=""
if [ -n "${RAILWAY_REPLICA_COUNT:-}" ]; then
    _REPLICA_COUNT_RAW="${RAILWAY_REPLICA_COUNT}"
elif [ -n "${REPLICA_COUNT:-}" ]; then
    _REPLICA_COUNT_RAW="${REPLICA_COUNT}"
fi

if [ -n "${_REPLICA_COUNT_RAW}" ] && echo "${_REPLICA_COUNT_RAW}" | grep -qE '^[0-9]+$'; then
    if [ "${_REPLICA_COUNT_RAW}" -gt "${_EXPECTED_REPLICAS}" ]; then
        echo "❌ Replica guard violation: replica_count=${_REPLICA_COUNT_RAW} expected<=${_EXPECTED_REPLICAS}"
        echo "   Enforce singleton deployment (Replicas=1, autoscaling off) before starting NIJA"
        exit 1
    fi
    echo "✅ Replica guard: replica_count=${_REPLICA_COUNT_RAW} (expected<=${_EXPECTED_REPLICAS})"
else
    echo "ℹ️  Replica guard: replica count metadata unavailable; relying on singleton/lock guards"
fi
echo ""

# Explain expected cold-start behavior when strict Redis writer lease is active.
# This helps operators distinguish normal lease handoff waits from a hard failure.
_LIVE_MODE=false
if [ "${DRY_RUN_MODE:-false}" = "false" ] && [ "${PAPER_MODE:-false}" = "false" ]; then
    _LIVE_MODE=true
fi

_REDIS_CONFIGURED=false
if [ -n "${NIJA_REDIS_URL:-}" ] || [ -n "${REDIS_URL:-}" ] || [ -n "${REDIS_PRIVATE_URL:-}" ] || [ -n "${REDIS_PUBLIC_URL:-}" ]; then
    _REDIS_CONFIGURED=true
elif { [ -n "${RAILWAY_TCP_PROXY_DOMAIN:-}" ] && [ -n "${RAILWAY_TCP_PROXY_PORT:-}" ]; } \
    || { [ -n "${REDIS_HOST:-${REDISHOST:-}}" ] && [ -n "${REDIS_PORT:-${REDISPORT:-}}" ]; }; then
    _REDIS_CONFIGURED=true
fi

_STRICT_LEASE=true
_STRICT_LEASE_RAW=$(printf "%s" "${NIJA_STRICT_REDIS_LEASE:-1}" | tr '[:upper:]' '[:lower:]')
if [ "${_STRICT_LEASE_RAW}" = "0" ] || [ "${_STRICT_LEASE_RAW}" = "false" ] || [ "${_STRICT_LEASE_RAW}" = "no" ] || [ "${_STRICT_LEASE_RAW}" = "off" ]; then
    _STRICT_LEASE=false
fi

_UNSAFE_BYPASS=false
_UNSAFE_BYPASS_RAW=$(printf "%s" "${NIJA_UNSAFE_BYPASS_DISTRIBUTED_LOCK:-0}" | tr '[:upper:]' '[:lower:]')
if [ "${_UNSAFE_BYPASS_RAW}" = "1" ] || [ "${_UNSAFE_BYPASS_RAW}" = "true" ] || [ "${_UNSAFE_BYPASS_RAW}" = "yes" ] || [ "${_UNSAFE_BYPASS_RAW}" = "on" ]; then
    _UNSAFE_BYPASS=true
fi

_DISABLE_WRITER_LOCK_RAW=$(printf "%s" "${NIJA_DISABLE_WRITER_LOCK:-0}" | tr '[:upper:]' '[:lower:]')
if [ "${_DISABLE_WRITER_LOCK_RAW}" = "1" ] || [ "${_DISABLE_WRITER_LOCK_RAW}" = "true" ] || [ "${_DISABLE_WRITER_LOCK_RAW}" = "yes" ] || [ "${_DISABLE_WRITER_LOCK_RAW}" = "on" ]; then
    _UNSAFE_BYPASS=true
    export NIJA_UNSAFE_BYPASS_DISTRIBUTED_LOCK=true
    echo "⚠️  NIJA_DISABLE_WRITER_LOCK is enabled (alias) — forcing NIJA_UNSAFE_BYPASS_DISTRIBUTED_LOCK=true"
fi

# Operator explicitly enabled unsafe writer-lock bypass. Keep nonce authority
# behavior consistent by relaxing strict Redis lease as well.
if [ "${_UNSAFE_BYPASS}" = "true" ] && [ "${_STRICT_LEASE}" = "true" ]; then
    export NIJA_STRICT_REDIS_LEASE=0
    _STRICT_LEASE=false
    echo "⚠️  Unsafe distributed-lock bypass enabled; disabling strict Redis nonce lease (NIJA_STRICT_REDIS_LEASE=0)."
fi

if [ "${_LIVE_MODE}" = "true" ] && [ "${_REDIS_CONFIGURED}" = "true" ] && [ "${_STRICT_LEASE}" = "true" ]; then
    # Fail-fast defaults for trading safety (override via env if needed).
    export NIJA_REDIS_LEASE_TTL_MS="${NIJA_REDIS_LEASE_TTL_MS:-30000}"
    export NIJA_REDIS_LEASE_ACQUIRE_TIMEOUT_S="${NIJA_REDIS_LEASE_ACQUIRE_TIMEOUT_S:-5}"
    export NIJA_REDIS_LEASE_WAIT_LOG_INTERVAL_S="${NIJA_REDIS_LEASE_WAIT_LOG_INTERVAL_S:-5}"

    _LEASE_TTL_MS="${NIJA_REDIS_LEASE_TTL_MS}"
    _LEASE_TIMEOUT_S="${NIJA_REDIS_LEASE_ACQUIRE_TIMEOUT_S}"
    _LEASE_WAIT_LOG_INTERVAL_S="${NIJA_REDIS_LEASE_WAIT_LOG_INTERVAL_S}"
    _WRITER_HEARTBEAT_MAX_FAILURES="${NIJA_WRITER_LOCK_HEARTBEAT_MAX_FAILURES:-12}"
    echo "🔒 Strict Redis writer lease enabled (live mode)"
    echo "   Fail-fast singleton enabled: duplicate instances exit immediately"
    echo "   Lease TTL: ${_LEASE_TTL_MS} ms | Acquire timeout: ${_LEASE_TIMEOUT_S} s"
    echo "   Lease wait log interval: ${_LEASE_WAIT_LOG_INTERVAL_S} s"
    echo "   Writer lock heartbeat max transient failures: ${_WRITER_HEARTBEAT_MAX_FAILURES}"
    echo "   If lock is not acquired quickly, process exits to avoid overlap"
    echo ""
fi

if [ "${_LIVE_MODE}" = "true" ]; then
    _COINBASE_CASH_LOW_LOG_INTERVAL_S="${NIJA_COINBASE_CASH_LOW_LOG_INTERVAL_S:-300}"
    echo "💵 Coinbase low-cash alert interval: ${_COINBASE_CASH_LOW_LOG_INTERVAL_S} s"
    echo ""
fi

# Keep buy-cash gate aligned with trade floor unless operator explicitly overrides.
if [ -n "${MIN_TRADE_USD:-}" ] && [ -z "${MIN_CASH_TO_BUY:-}" ]; then
    export MIN_CASH_TO_BUY="$(awk "BEGIN { v=${MIN_TRADE_USD}; c=v-0.5; if (c<1.0) c=1.0; printf \"%.2f\", c }")"
fi

    echo "🪵 Log profile: ${NIJA_LOG_PROFILE:-normal}"
    if [ -n "${NIJA_LOG_LEVEL:-}" ]; then
        echo "   Log level override: ${NIJA_LOG_LEVEL}"
    fi
    if [ -n "${NIJA_STARTUP_BUFFER_MAX_LINES:-}" ]; then
        echo "   Startup buffer max lines per flush override: ${NIJA_STARTUP_BUFFER_MAX_LINES}"
    fi
    echo ""

# Helper function to exit gracefully for configuration errors
exit_config_error() {
    echo ""
    local _hold_on_config_error=true
    local _hold_raw
    _hold_raw=$(printf "%s" "${NIJA_HOLD_ON_CONFIG_ERROR:-true}" | tr '[:upper:]' '[:lower:]')
    if [ "${_hold_raw}" = "0" ] || [ "${_hold_raw}" = "false" ] || [ "${_hold_raw}" = "no" ] || [ "${_hold_raw}" = "off" ]; then
        _hold_on_config_error=false
    fi

    if [ "$WAIT_FOR_CONFIG" = "true" ] || [ "${_hold_on_config_error}" = "true" ]; then
        echo "⏸️  Configuration incomplete - entering wait mode"
        echo ""
        echo "   🎯 This prevents restart loops while waiting for configuration"
        echo ""
        echo "   Health endpoint will report:"
        echo "   • Status: BLOCKED (HTTP 503)"
        echo "   • State:  awaiting_configuration"
        echo "   • Action: Set credentials and restart"
        echo ""
        echo "   Query the health endpoint:"
        echo "     curl http://localhost:\${PORT:-8080}/healthz"
        echo ""
        if [ "$WAIT_FOR_CONFIG" != "true" ]; then
            echo "   Override behaviour with NIJA_HOLD_ON_CONFIG_ERROR=false to exit immediately instead."
            echo ""
        fi
        echo "   Expected response:"
        echo "     {"
        echo "       \"status\": \"blocked\","
        echo "       \"state\": \"awaiting_configuration\","
        echo "       \"message\": \"<reason-specific configuration block>\","
        echo "       \"config_status\": \"<missing_redis_for_writer_lock|missing_credentials>\","
        echo "       \"required\": { ... }"
        echo "     }"
        echo "   Note: query /healthz for the exact required fields in this deployment."
        echo ""
        echo "   Once configured, restart and health will return:"
        echo "     {\"status\": \"ready\", \"state\": \"configured\"} (HTTP 200)"
        echo ""
        # Start health server in wait mode and keep container running
        echo "🌐 Starting config-aware health server..."
        $PY -u config_health_server.py
        # If health server exits, exit with 0 to prevent restart loop
        exit 0
    else
        echo "⚠️  Configuration error - exiting with failure (exit code 1)"
        echo "    The container will not restart automatically."
        echo "    Please configure credentials and manually restart the deployment."
        echo ""
        exit 1
    fi
}

_resolve_redis_url() {
    _strip_wrapping_quotes() {
        # Remove one level of wrapping single/double quotes from full values.
        local _raw="${1:-}"
        if [ "${#_raw}" -ge 2 ] && [ "${_raw#\"}" != "${_raw}" ] && [ "${_raw%\"}" != "${_raw}" ]; then
            _raw="${_raw#\"}"
            _raw="${_raw%\"}"
        elif [ "${#_raw}" -ge 2 ] && [ "${_raw#\'}" != "${_raw}" ] && [ "${_raw%\'}" != "${_raw}" ]; then
            _raw="${_raw#\'}"
            _raw="${_raw%\'}"
        fi
        printf "%s" "${_raw}"
    }

    if [ -n "${NIJA_REDIS_URL:-}" ]; then
        _strip_wrapping_quotes "${NIJA_REDIS_URL}"
        return 0
    fi
    if [ -n "${REDIS_URL:-}" ]; then
        _strip_wrapping_quotes "${REDIS_URL}"
        return 0
    fi
    if [ -n "${REDIS_PRIVATE_URL:-}" ]; then
        _strip_wrapping_quotes "${REDIS_PRIVATE_URL}"
        return 0
    fi
    if [ -n "${REDIS_PUBLIC_URL:-}" ]; then
        _strip_wrapping_quotes "${REDIS_PUBLIC_URL}"
        return 0
    fi

    # Component fallback: synthesize URL similarly to runtime resolver.
    local _host _port _password _db
    _host="${RAILWAY_TCP_PROXY_DOMAIN:-${REDIS_HOST:-${REDISHOST:-}}}"
    _port="${RAILWAY_TCP_PROXY_PORT:-${REDIS_PORT:-${REDISPORT:-}}}"
    _password="${REDIS_PASSWORD:-${REDISPASSWORD:-${REDIS_TOKEN:-}}}"
    _db="${REDIS_DB:-${REDIS_DATABASE:-0}}"

    _host="$(_strip_wrapping_quotes "${_host}")"
    _port="$(_strip_wrapping_quotes "${_port}")"
    _password="$(_strip_wrapping_quotes "${_password}")"
    _db="$(_strip_wrapping_quotes "${_db}")"

    if [ -n "${_host}" ] && [ -n "${_port}" ]; then
        if printf "%s" "${_port}" | grep -Eq '^[0-9]+$'; then
            if [ -n "${_password}" ]; then
                printf "%s" "redis://default:${_password}@${_host}:${_port}/${_db}"
            else
                printf "%s" "redis://${_host}:${_port}/${_db}"
            fi
            return 0
        fi
        return 1
    fi
    return 1
}

_resolve_redis_url_source() {
    if [ -n "${NIJA_REDIS_URL:-}" ]; then
        printf "%s" "NIJA_REDIS_URL"
        return 0
    fi
    if [ -n "${REDIS_URL:-}" ]; then
        printf "%s" "REDIS_URL"
        return 0
    fi
    if [ -n "${REDIS_PRIVATE_URL:-}" ]; then
        printf "%s" "REDIS_PRIVATE_URL"
        return 0
    fi
    if [ -n "${REDIS_PUBLIC_URL:-}" ]; then
        printf "%s" "REDIS_PUBLIC_URL"
        return 0
    fi
    if [ -n "${RAILWAY_TCP_PROXY_DOMAIN:-}" ] && [ -n "${RAILWAY_TCP_PROXY_PORT:-}" ]; then
        printf "%s" "RAILWAY_TCP_PROXY_DOMAIN+RAILWAY_TCP_PROXY_PORT"
        return 0
    fi
    if [ -n "${REDIS_HOST:-${REDISHOST:-}}" ] && [ -n "${REDIS_PORT:-${REDISPORT:-}}" ]; then
        printf "%s" "REDIS_HOST+REDIS_PORT"
        return 0
    fi
    return 1
}

_validate_redis_url_or_exit() {
    # Skip Redis URL validation when the distributed-lock bypass is active;
    # Redis is not required in that mode so an invalid/missing URL is harmless.
    if [ "${_UNSAFE_BYPASS:-false}" = "true" ]; then
        return 0
    fi

    local _redis_url
    local _redis_source
    local _has_proxy_fallback=false
    _redis_url="$(_resolve_redis_url 2>/dev/null || true)"
    _redis_source="$(_resolve_redis_url_source 2>/dev/null || true)"
    if [ -z "${_redis_url}" ]; then
        return 0
    fi

    if [ -n "${RAILWAY_TCP_PROXY_DOMAIN:-}" ] && [ -n "${RAILWAY_TCP_PROXY_PORT:-}" ]; then
        _has_proxy_fallback=true
    elif [ -n "${REDIS_PUBLIC_URL:-}" ] && ! printf "%s" "${REDIS_PUBLIC_URL}" | grep -q "\.railway\.internal"; then
        _has_proxy_fallback=true
    elif [ -n "${REDIS_HOST:-${REDISHOST:-}}" ] && [ -n "${REDIS_PORT:-${REDISPORT:-}}" ] \
        && ! printf "%s" "${REDIS_HOST:-${REDISHOST:-}}" | grep -q "\.railway\.internal"; then
        _has_proxy_fallback=true
    fi

    if printf "%s" "${_redis_url}" | grep -q "\.railway\.internal" && [ "${_has_proxy_fallback}" != "true" ]; then
        echo ""
        echo "❌ CRITICAL: ${_redis_source:-Redis URL} points to Railway internal networking only"
        echo ""
        echo "Detected: ${_redis_source:-Redis URL}=***@*.railway.internal"
        echo "No public Redis proxy fallback is configured."
        echo ""
        echo "Internal Railway hostnames work only within compatible private networking contexts."
        echo "In this deployment, the distributed writer lock cannot reach Redis and will fail-closed."
        echo ""
        echo "🔧 SOLUTION:"
        echo "   1. Railway → Redis service → Connect"
        echo "   2. Copy the PUBLIC proxy URL (maglev.proxy.rlwy.net:PORT)"
        echo "   3. Set NIJA_REDIS_URL to that public URL"
        echo "      OR set RAILWAY_TCP_PROXY_DOMAIN + RAILWAY_TCP_PROXY_PORT + REDIS_PASSWORD"
        echo "   4. Redeploy"
        echo ""
        exit_config_error
    fi

    case "${_redis_url}" in
        *YOUR_REDIS_*|*YOUR_REDIS_PORT*|*YOUR_REDIS_HOST*|*YOUR_REDIS_PASSWORD*|*example.com*|*changeme*)
            echo ""
            echo "❌ CRITICAL: ${_redis_source:-Redis URL} contains placeholder values"
            echo ""
            echo "Distributed writer lock is enabled, but the Redis URL is still a template."
            echo ""
            echo "🔧 SOLUTION:"
            echo "   1. Open Railway → Service → Variables"
            echo "   2. Replace ${_redis_source:-the Redis URL variable} with the real Railway Redis connection URL"
            echo "   3. Remove any placeholder text such as YOUR_REDIS_PORT"
            echo "   4. Redeploy the service"
            echo ""
            exit_config_error
            ;;
    esac

    if ! "$PY" - "${_redis_url}" <<'PY' >/dev/null 2>&1
import sys
from urllib.parse import urlparse

raw = sys.argv[1].strip()
parsed = urlparse(raw)
if parsed.scheme not in {"redis", "rediss"}:
    raise SystemExit(1)
if not parsed.hostname:
    raise SystemExit(1)
try:
    port = parsed.port
except ValueError:
    raise SystemExit(1)
if port is None or port <= 0:
    raise SystemExit(1)
raise SystemExit(0)
PY
    then
        echo ""
        echo "❌ CRITICAL: ${_redis_source:-Redis URL} is not a valid Redis connection URL"
        echo ""
        echo "Expected format: redis://[default:<password>@]<host>:<port>[/db] or rediss://[default:<password>@]<host>:<port>[/db]"
        echo "Tip: remove wrapping quotes if present, e.g. NIJA_REDIS_URL=redis://default:<password>@<host>:<port>/0"
        echo ""
        echo "🔧 SOLUTION:"
        echo "   1. Open Railway → Redis service → Connect"
        echo "   2. Copy the full Redis URL"
        echo "   3. Paste that value into ${_redis_source:-NIJA_REDIS_URL}"
        echo "   4. Redeploy the service"
        echo ""
        exit_config_error
    fi
}

_log_redis_lock_source_hint() {
    local _redis_url
    local _redis_source
    local _component_host
    local _component_port
    local _component_source
    local _endpoint

    _redis_url="$(_resolve_redis_url 2>/dev/null || true)"
    _redis_source="$(_resolve_redis_url_source 2>/dev/null || true)"

    if [ -n "${_redis_url}" ]; then
        _endpoint=$("$PY" - "${_redis_url}" <<'PY' 2>/dev/null
import sys
from urllib.parse import urlparse

raw = sys.argv[1].strip()
parsed = urlparse(raw)
host = parsed.hostname or "<unknown-host>"
port = parsed.port
if port is None:
    print(host)
else:
    print(f"{host}:{port}")
PY
)
        if [ -z "${_endpoint}" ]; then
            _endpoint="<unparseable-endpoint>"
        fi
        echo "🔐 Writer-lock Redis source: ${_redis_source:-unknown} (${_endpoint})"
        return 0
    fi

    _component_host="${RAILWAY_TCP_PROXY_DOMAIN:-${REDIS_HOST:-${REDISHOST:-}}}"
    _component_port="${RAILWAY_TCP_PROXY_PORT:-${REDIS_PORT:-${REDISPORT:-}}}"
    _component_source=""

    if [ -n "${RAILWAY_TCP_PROXY_DOMAIN:-}" ] && [ -n "${RAILWAY_TCP_PROXY_PORT:-}" ]; then
        _component_source="RAILWAY_TCP_PROXY_DOMAIN+RAILWAY_TCP_PROXY_PORT"
    elif [ -n "${REDIS_HOST:-${REDISHOST:-}}" ] && [ -n "${REDIS_PORT:-${REDISPORT:-}}" ]; then
        _component_source="REDIS_HOST+REDIS_PORT"
    fi

    if [ -n "${_component_source}" ]; then
        echo "🔐 Writer-lock Redis source: ${_component_source} (${_component_host}:${_component_port})"
        echo "   Runtime will synthesize Redis URL from component variables if URL vars are unset."
    else
        echo "🔐 Writer-lock Redis source: none configured"
    fi
}

# Prefer workspace venv Python, fallback to system python3
PY=""
if [ -x ./.venv/bin/python ]; then
    PY="./.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PY="$(command -v python3)"
fi

if [ -z "$PY" ]; then
    echo "❌ No Python interpreter found (venv or system)"
    echo "   Ensure .venv exists or install python3"
    exit 127
fi

_validate_redis_url_or_exit
_log_redis_lock_source_hint

_disable_nonce_ceiling_jump() {
    local _truthy="1|true|yes|enabled|on"
    local _jump_raw="${NIJA_NONCE_CEILING_JUMP:-}"
    local _jump
    _jump=$(printf "%s" "${_jump_raw}" | tr '[:upper:]' '[:lower:]')
    if printf "%s" "${_jump}" | grep -Eq "^(${_truthy})$"; then
        echo "⚠️  NIJA_NONCE_CEILING_JUMP=${NIJA_NONCE_CEILING_JUMP} detected — forcing NIJA_NONCE_CEILING_JUMP=0"
        echo "   Ceiling jumps are disabled to prevent irreversible nonce drift."
        export NIJA_NONCE_CEILING_JUMP=0
    fi
}

_maybe_force_nonce_resync() {
    local _truthy="1|true|yes|enabled|on"
    local _force_raw="${NIJA_FORCE_NONCE_RESYNC:-}"
    local _force
    _force=$(printf "%s" "${_force_raw}" | tr '[:upper:]' '[:lower:]')
    if ! printf "%s" "${_force}" | grep -Eq "^(${_truthy})$"; then
        return 0
    fi

    echo ""
    echo "🔄 NIJA_FORCE_NONCE_RESYNC enabled — clearing nonce state before startup"

    # Local nonce persistence reset (safe if files do not exist).
    rm -f /app/data/kraken_nonce.state*
    rm -f /app/bot/../data/kraken_nonce.state*
    rm -f "${_SCRIPT_DIR}/data/kraken_nonce.state"*

    # Redis nonce key cleanup (best effort).
    # Supports either NIJA_REDIS_URL or standard REDIS_URL variants.
    local _redis_url="${NIJA_REDIS_URL:-${REDIS_URL:-${REDIS_PRIVATE_URL:-${REDIS_PUBLIC_URL:-}}}}"
    if [ -n "${_redis_url}" ] && command -v redis-cli >/dev/null 2>&1; then
        if redis-cli -u "${_redis_url}" DEL kraken_nonce >/dev/null 2>&1; then
            echo "   ✅ Redis key reset: kraken_nonce"
        else
            echo "   ⚠️  Could not delete Redis key: kraken_nonce"
        fi
        if redis-cli -u "${_redis_url}" DEL nonce_lock >/dev/null 2>&1; then
            echo "   ✅ Redis key reset: nonce_lock"
        else
            echo "   ⚠️  Could not delete Redis key: nonce_lock"
        fi
        if redis-cli -u "${_redis_url}" DEL nija:kraken:nonce >/dev/null 2>&1; then
            echo "   ✅ Redis key reset: nija:kraken:nonce"
        fi
        local _scanned_nonce_keys
        for _nonce_pattern in \
            'kraken_nonce*' \
            'nija:kraken:nonce*' \
            'nija:kraken:writer:owner:*' \
            'nija:kraken:writer:lease_version:*' \
            'nija:kraken:writer:version_counter:*' \
            'nija:kraken:writer:fingerprint:*'; do
            _scanned_nonce_keys=$(redis-cli -u "${_redis_url}" --scan --pattern "${_nonce_pattern}" 2>/dev/null || true)
            if [ -n "${_scanned_nonce_keys}" ]; then
                while IFS= read -r _nonce_key; do
                    [ -z "${_nonce_key}" ] && continue
                    if redis-cli -u "${_redis_url}" DEL "${_nonce_key}" >/dev/null 2>&1; then
                        echo "   ✅ Redis key reset: ${_nonce_key}"
                    fi
                done <<EOF
${_scanned_nonce_keys}
EOF
            fi
        done
        echo "   ℹ️  Writer-lock keys (nija:writer_lock*) are NOT auto-deleted during resync."
        echo "      Clear them manually only after confirming no live writer instance exists."
    elif [ -n "${_redis_url}" ]; then
        # Railway images may not include redis-cli; use Python Redis client as fallback.
        local _py_output
        _py_output=$(REDIS_URL="${_redis_url}" "${PY}" - <<'PY'
import os
import sys

url = os.environ.get("REDIS_URL", "").strip()
if not url:
    print("SKIP|Redis URL missing")
    raise SystemExit(0)

try:
    from bot.redis_runtime import connect_redis_with_fallback, clear_nonce_state_safe
except Exception as exc:
    print(f"SKIP|redis runtime helper unavailable: {exc}")
    raise SystemExit(0)

try:
    client, _effective_url = connect_redis_with_fallback(
        url=url,
        decode_responses=True,
        socket_timeout=5,
        socket_connect_timeout=5,
        retries=5,
        delay_s=2.0,
        log=lambda msg: print(f"INFO|{msg}"),
    )
except Exception as exc:
    print(f"SKIP|Redis preflight ping failed: {exc}")
    raise SystemExit(0)


patterns = [
    "kraken_nonce*",
    "nija:kraken:nonce*",
    "nija:kraken:writer:owner:*",
    "nija:kraken:writer:lease_version:*",
    "nija:kraken:writer:version_counter:*",
    "nija:kraken:writer:fingerprint:*",
]
explicit_keys = {"kraken_nonce", "nonce_lock", "nija:kraken:nonce"}
deleted = clear_nonce_state_safe(
    client,
    patterns=patterns,
    explicit_keys=explicit_keys,
    timeout_s=5,
    log=lambda msg: print(f"INFO|{msg}"),
)

print(f"SUMMARY|deleted={deleted}")
PY
)
        if [ -n "${_py_output}" ]; then
            while IFS= read -r _line; do
                [ -z "${_line}" ] && continue
                case "${_line}" in
                    DEL\|*)
                        echo "   ✅ Redis key reset: ${_line#DEL|}"
                        ;;
                    SUMMARY\|*)
                        echo "   ℹ️  Python nonce-key cleanup: ${_line#SUMMARY|}"
                        ;;
                    SKIP\|*)
                        echo "   ℹ️  Redis key reset skipped: ${_line#SKIP|}"
                        ;;
                    *)
                        echo "   ℹ️  ${_line}"
                        ;;
                esac
            done <<EOF
${_py_output}
EOF
        fi
        echo "   ℹ️  Writer-lock keys (nija:writer_lock*) are NOT auto-deleted during resync."
        echo "      Clear them manually only after confirming no live writer instance exists."
    else
        echo "   ℹ️  Redis key reset skipped (redis-cli not available or Redis URL not set)"
    fi

    echo "✅ Force nonce resync preflight complete"
    echo ""
}

_disable_nonce_ceiling_jump

_maybe_force_clear_writer_lock() {
    local _truthy="1|true|yes|enabled|on"
    local _force_raw="${NIJA_FORCE_CLEAR_WRITER_LOCK:-}"
    local _force
    _force=$(printf "%s" "${_force_raw}" | tr '[:upper:]' '[:lower:]')
    if ! printf "%s" "${_force}" | grep -Eq "^(${_truthy})$"; then
        return 0
    fi

    echo ""
    echo "🧹 NIJA_FORCE_CLEAR_WRITER_LOCK enabled — clearing stale writer lock keys before startup"

    local _redis_url
    _redis_url="$(_resolve_redis_url 2>/dev/null || true)"
    if [ -z "${_redis_url}" ]; then
        echo "   ⚠️  Redis URL not configured; cannot clear writer lock keys"
        return 0
    fi

    local _py_output
    _py_output=$(REDIS_URL="${_redis_url}" "${PY}" - <<'PY'
import os

url = os.environ.get("REDIS_URL", "").strip()
if not url:
    print("SKIP|Redis URL missing")
    raise SystemExit(0)

try:
    from bot.redis_runtime import connect_redis_with_fallback, clear_nonce_state_safe
except Exception as exc:
    print(f"SKIP|redis runtime helper unavailable: {exc}")
    raise SystemExit(0)

try:
    client, _effective_url = connect_redis_with_fallback(
        url=url,
        decode_responses=True,
        socket_timeout=5,
        socket_connect_timeout=5,
        retries=5,
        delay_s=2.0,
        log=lambda msg: print(f"INFO|{msg}"),
    )
except Exception as exc:
    print(f"SKIP|Redis preflight ping failed: {exc}")
    raise SystemExit(0)


patterns = [
    "nija:writer_lock*",
    "nija:writer_lock_meta*",
    "nija:writer_fence*",
]
explicit_keys = {"nija:writer_lock"}
deleted = clear_nonce_state_safe(
    client,
    patterns=patterns,
    explicit_keys=explicit_keys,
    timeout_s=5,
    log=lambda msg: print(f"INFO|{msg}"),
)

print(f"SUMMARY|deleted={deleted}")
PY
)

    if [ -n "${_py_output}" ]; then
        while IFS= read -r _line; do
            [ -z "${_line}" ] && continue
            case "${_line}" in
                DEL\|*)
                    echo "   ✅ Redis key reset: ${_line#DEL|}"
                    ;;
                SUMMARY\|*)
                    echo "   ℹ️  Writer-lock cleanup: ${_line#SUMMARY|}"
                    ;;
                SKIP\|*)
                    echo "   ℹ️  Writer-lock cleanup skipped: ${_line#SKIP|}"
                    ;;
                *)
                    echo "   ℹ️  ${_line}"
                    ;;
            esac
        done <<EOF
${_py_output}
EOF
    fi
    echo "✅ Writer lock cleanup preflight complete"
    echo ""
}

_maybe_force_clear_writer_lock

$PY --version 2>&1

# Temporary kill-switch for nonce reset while diagnosing startup blocks.
if [ "${NIJA_SKIP_NONCE_RESET:-0}" = "1" ]; then
    echo "SKIPPING NONCE RESET"
else
    echo "BEFORE NONCE RESET"
    _maybe_force_nonce_resync
    echo "AFTER NONCE RESET"
fi

if [ "${NIJA_STARTUP_DRY_RUN:-0}" = "1" ]; then
    echo "DRY RUN: startup nonce/redis checks complete; exiting before broker initialization"
    exit 0
fi

# Ensure Python version output is flushed
sleep 0.05

# Test Coinbase module (OPTIONAL - secondary broker)
$PY -c "from coinbase.rest import RESTClient; print('✅ Coinbase REST client available')" 2>&1 || {
    echo "⚠️  Coinbase REST client not available (this is OK - Coinbase is the secondary broker)"
}

# Ensure output is flushed
sleep 0.05

# Test Kraken module (REQUIRED - Kraken is PRIMARY broker)
# CRITICAL: Kraken Platform credentials MUST be set
if [ -n "${KRAKEN_PLATFORM_API_KEY}" ] && [ -n "${KRAKEN_PLATFORM_API_SECRET}" ]; then
    $PY -c "import krakenex; import pykrakenapi; print('✅ Kraken SDK (krakenex + pykrakenapi) available')" 2>&1 || {
        echo ""
        echo "❌ CRITICAL: Kraken Master credentials are set but Kraken SDK is NOT installed"
        echo ""
        echo "The Kraken SDK (krakenex + pykrakenapi) is required when Kraken credentials are configured."
        echo ""
        echo "🔧 SOLUTION:"
        echo "   1. Verify railway.json uses 'builder': 'DOCKERFILE' (not NIXPACKS)"
        echo "   2. Trigger a fresh deployment (not just restart):"
        echo "      Railway: Settings → 'Redeploy'"
        echo "      Render: Manual Deploy → 'Clear build cache & deploy'"
        echo ""
        echo "   The Dockerfile includes explicit installation of krakenex and pykrakenapi."
        echo "   If using NIXPACKS/Railway buildpack instead of Docker, the installation may fail silently."
        echo ""
        echo "📖 See SOLUTION_KRAKEN_LIBRARY_NOT_INSTALLED.md for detailed troubleshooting"
        echo ""
        exit_config_error
    }
else
    # CRITICAL: Kraken credentials are REQUIRED as primary broker
    echo ""
    echo "❌ CRITICAL: Kraken Platform credentials are REQUIRED"
    echo ""
    echo "Kraken is the primary broker."
    echo "You MUST configure Kraken credentials to use this bot."
    echo ""
    echo "🔧 SOLUTION:"
    echo "   1. Get API credentials from https://www.kraken.com/u/security/api"
    echo "   2. Set environment variables:"
    echo "      export KRAKEN_PLATFORM_API_KEY='<your-api-key>'"
    echo "      export KRAKEN_PLATFORM_API_SECRET='<your-api-secret>'"
    echo "   3. Restart the bot"
    echo ""
    echo "📖 See .env.example for detailed setup instructions"
    echo ""
    exit_config_error
fi

# Ensure all Python test output is flushed before continuing
sleep 0.05

# Source build-time git metadata written by inject_git_metadata.sh (Docker build)
# This makes GIT_BRANCH / GIT_COMMIT / GIT_COMMIT_SHORT available when the image
# was built with proper --build-arg values (e.g. via railway.json buildArgs).
if [ -f ".env.build" ]; then
    . .env.build
fi

BRANCH_VAL=${GIT_BRANCH}
COMMIT_VAL=${GIT_COMMIT_SHORT:-${GIT_COMMIT}}

# Populate branch/commit from git if not provided
if ([ -z "$BRANCH_VAL" ] || [ "$BRANCH_VAL" = "unknown" ]) && command -v git >/dev/null 2>&1; then
    BRANCH_VAL=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
fi
if ([ -z "$COMMIT_VAL" ] || [ "$COMMIT_VAL" = "unknown" ]) && command -v git >/dev/null 2>&1; then
    COMMIT_VAL=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
fi

# Fallback: use Railway-provided runtime environment variables (always available in Railway deployments)
if ([ -z "$BRANCH_VAL" ] || [ "$BRANCH_VAL" = "unknown" ]) && [ -n "$RAILWAY_GIT_BRANCH" ]; then
    BRANCH_VAL="$RAILWAY_GIT_BRANCH"
fi
if ([ -z "$COMMIT_VAL" ] || [ "$COMMIT_VAL" = "unknown" ]) && [ -n "$RAILWAY_GIT_COMMIT_SHA" ]; then
    COMMIT_VAL="${RAILWAY_GIT_COMMIT_SHA:0:7}"
fi

echo "Branch: ${BRANCH_VAL:-unknown}"
echo "Commit: ${COMMIT_VAL:-unknown}"

# RISK CHECK: Warn if git metadata is unknown
if [ "${BRANCH_VAL:-unknown}" = "unknown" ] || [ "${COMMIT_VAL:-unknown}" = "unknown" ]; then
    echo ""
    echo "⚠️  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "⚠️  RISK: Running with UNKNOWN git metadata"
    echo "⚠️  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "⚠️  Cannot verify which code version is running!"
    echo "⚠️  Branch: ${BRANCH_VAL:-unknown}"
    echo "⚠️  Commit: ${COMMIT_VAL:-unknown}"
    echo "⚠️  "
    echo "⚠️  This is DANGEROUS in production - you cannot trace issues to code."
    echo "⚠️  "
    echo "⚠️  RECOMMENDED: Set GIT_BRANCH and GIT_COMMIT in your deployment:"
    echo "⚠️    export GIT_BRANCH=\$(git rev-parse --abbrev-ref HEAD)"
    echo "⚠️    export GIT_COMMIT=\$(git rev-parse --short HEAD)"
    echo "⚠️  "
    echo "⚠️  Or use inject_git_metadata.sh during build process."
    echo "⚠️  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
fi

# Ensure git info output is flushed
sleep 0.05

# Explicitly allow counting Consumer USD unless overridden
export ALLOW_CONSUMER_USD="${ALLOW_CONSUMER_USD:-true}"
echo "ALLOW_CONSUMER_USD=${ALLOW_CONSUMER_USD}"

# Load environment from .env if present (so bot can run live without manual exports)
if [ -f ./.env ]; then
    echo ""
    echo "🧩 Loading environment variables from .env"
    set -a
    . ./.env
    set +a
fi

# Normalize Coinbase disable intent before Python starts so all downstream
# layers see consistent flags even if only ENABLE_COINBASE is provided.
_ENABLE_COINBASE_RAW="$(printf "%s" "${ENABLE_COINBASE:-}" | tr '[:upper:]' '[:lower:]')"
if [ "${_ENABLE_COINBASE_RAW}" = "0" ] || [ "${_ENABLE_COINBASE_RAW}" = "false" ] || [ "${_ENABLE_COINBASE_RAW}" = "no" ] || [ "${_ENABLE_COINBASE_RAW}" = "off" ]; then
    export ENABLE_COINBASE_TRADING="false"
    export NIJA_DISABLE_COINBASE="true"
    echo "⏭️  Coinbase explicitly disabled via ENABLE_COINBASE=${ENABLE_COINBASE}; forcing ENABLE_COINBASE_TRADING=false and NIJA_DISABLE_COINBASE=true"
fi

# Debug: Show credential status for ALL exchanges
echo ""
echo "🔍 EXCHANGE CREDENTIAL STATUS:"
echo "   ────────────────────────────────────────────────────────"

# Kraken - Platform (PRIMARY BROKER)
echo "   📊 KRAKEN (Platform) - PRIMARY BROKER:"
if [ -n "${KRAKEN_PLATFORM_API_KEY}" ] && [ -n "${KRAKEN_PLATFORM_API_SECRET}" ]; then
    echo "      ✅ Configured (Key: ${#KRAKEN_PLATFORM_API_KEY} chars, Secret: ${#KRAKEN_PLATFORM_API_SECRET} chars)"
else
    echo "      ❌ Not configured (REQUIRED)"
fi

# Coinbase - Platform (SECONDARY BROKER)
echo "   📊 COINBASE (Platform) - SECONDARY BROKER:"
if [ "${NIJA_DISABLE_COINBASE:-false}" = "true" ] || [ "${ENABLE_COINBASE_TRADING:-true}" = "false" ]; then
    echo "      ⏭️  Disabled by env (NIJA_DISABLE_COINBASE=${NIJA_DISABLE_COINBASE:-false}, ENABLE_COINBASE_TRADING=${ENABLE_COINBASE_TRADING:-true})"
elif [ -n "${COINBASE_API_KEY}" ] && [ -n "${COINBASE_API_SECRET}" ]; then
    echo "      ✅ Configured (Key: ${#COINBASE_API_KEY} chars, Secret: ${#COINBASE_API_SECRET} chars)"
else
    echo "      ⚠️  Not configured (optional secondary broker)"
fi

# Kraken - User #1 (Daivon)
echo "   👤 KRAKEN (User #1: Daivon):"
if [ -n "${KRAKEN_USER_DAIVON_API_KEY}" ] && [ -n "${KRAKEN_USER_DAIVON_API_SECRET}" ]; then
    echo "      ✅ Configured (Key: ${#KRAKEN_USER_DAIVON_API_KEY} chars, Secret: ${#KRAKEN_USER_DAIVON_API_SECRET} chars)"
else
    echo "      ❌ Not configured"
fi

# Kraken - User #2 (Tania)
echo "   👤 KRAKEN (User #2: Tania):"
if [ -n "${KRAKEN_USER_TANIA_API_KEY}" ] && [ -n "${KRAKEN_USER_TANIA_API_SECRET}" ]; then
    echo "      ✅ Configured (Key: ${#KRAKEN_USER_TANIA_API_KEY} chars, Secret: ${#KRAKEN_USER_TANIA_API_SECRET} chars)"
else
    echo "      ❌ Not configured"
fi

# OKX
echo "   📊 OKX (Master):"
if [ -n "${OKX_API_KEY}" ] && [ -n "${OKX_API_SECRET}" ] && [ -n "${OKX_PASSPHRASE}" ]; then
    echo "      ✅ Configured (Key: ${#OKX_API_KEY} chars, Secret: ${#OKX_API_SECRET} chars)"
else
    echo "      ❌ Not configured"
fi

# Binance
echo "   📊 BINANCE (Master):"
if [ -n "${BINANCE_API_KEY}" ] && [ -n "${BINANCE_API_SECRET}" ]; then
    echo "      ✅ Configured (Key: ${#BINANCE_API_KEY} chars, Secret: ${#BINANCE_API_SECRET} chars)"
else
    echo "      ❌ Not configured"
fi

# Alpaca - Master
echo "   📊 ALPACA (Master):"
if [ -n "${ALPACA_API_KEY}" ] && [ -n "${ALPACA_API_SECRET}" ]; then
    echo "      ✅ Configured (Key: ${#ALPACA_API_KEY} chars, Secret: ${#ALPACA_API_SECRET} chars, Paper: ${ALPACA_PAPER:-true})"
else
    echo "      ❌ Not configured"
fi

# Alpaca - User #2 (Tania)
echo "   👤 ALPACA (User #2: Tania):"
if [ -n "${ALPACA_USER_TANIA_API_KEY}" ] && [ -n "${ALPACA_USER_TANIA_API_SECRET}" ]; then
    echo "      ✅ Configured (Key: ${#ALPACA_USER_TANIA_API_KEY} chars, Secret: ${#ALPACA_USER_TANIA_API_SECRET} chars, Paper: ${ALPACA_USER_TANIA_PAPER:-true})"
else
    echo "      ❌ Not configured"
fi

echo "   ────────────────────────────────────────────────────────"
echo ""
echo "🔧 Trading Guards:"
echo "   MIN_TRADE_USD=${MIN_TRADE_USD:-3.50}"
echo "   MIN_CASH_TO_BUY=${MIN_CASH_TO_BUY:-3.00}"
echo "   MINIMUM_TRADING_BALANCE=${MINIMUM_TRADING_BALANCE:-1.00}"
echo ""

# ═══════════════════════════════════════════════════════════════════════
# CRITICAL: Trading Mode Verification (Testing vs. Live)
# ═══════════════════════════════════════════════════════════════════════
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🎯 TRADING MODE VERIFICATION"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Helper function to check if value is truthy (true, 1, yes)
is_truthy() {
    local val="${1:-false}"
    [ "$val" = "true" ] || [ "$val" = "1" ] || [ "$val" = "yes" ]
}

# Check mode flags (DRY_RUN takes highest priority)
DRY_RUN_MODE_VAL="${DRY_RUN_MODE:-false}"
PAPER_MODE_VAL="${PAPER_MODE:-false}"
LIVE_CAPITAL_VERIFIED_VAL="${LIVE_CAPITAL_VERIFIED:-false}"

echo "   DRY_RUN_MODE: ${DRY_RUN_MODE_VAL}"
echo "   PAPER_MODE: ${PAPER_MODE_VAL}"
echo "   LIVE_CAPITAL_VERIFIED: ${LIVE_CAPITAL_VERIFIED_VAL}"
echo ""

# Determine actual mode and warn accordingly (DRY_RUN > LIVE > PAPER)
if is_truthy "${DRY_RUN_MODE_VAL}"; then
    echo "   🟡 MODE: DRY RUN (FULL SIMULATION)"
    echo "   ✅ SAFEST MODE - No real orders on any exchange"
    echo "   ✅ All exchanges in simulation mode"
    echo "   ✅ No real money at risk"
    echo "   ✅ All trading is simulated in-memory"
    echo ""
    echo "   This mode is perfect for:"
    echo "      • Testing strategy logic"
    echo "      • Validating exchange configurations"
    echo "      • Reviewing startup banners and validation"
    echo "      • Operator sign-off before going live"
    echo ""
    echo "   To enable live trading after validation:"
    echo "      export DRY_RUN_MODE=false"
    echo "      export LIVE_CAPITAL_VERIFIED=true"
    echo ""
    echo "   ℹ️  Multi-exchange trading: verify credentials for each exchange you want:"
    echo "      KRAKEN_PLATFORM_API_KEY / KRAKEN_PLATFORM_API_SECRET  (primary broker)"
    echo "      OKX_API_KEY / OKX_API_SECRET / OKX_PASSPHRASE         (optional)"
    echo "      BINANCE_API_KEY / BINANCE_API_SECRET                  (optional)"
    echo "      ALPACA_API_KEY / ALPACA_API_SECRET                    (optional)"
elif is_truthy "${LIVE_CAPITAL_VERIFIED_VAL}"; then
    echo "   🔴 MODE: LIVE TRADING"
    echo "   ⚠️  REAL MONEY AT RISK"
    echo "   ⚠️  This bot will execute real trades with real capital"
    echo "   ⚠️  Ensure this is INTENTIONAL"
    echo ""
    echo "   To disable live trading:"
    echo "      export LIVE_CAPITAL_VERIFIED=false"
    echo ""
    echo "   To test safely first:"
    echo "      export DRY_RUN_MODE=true"
elif is_truthy "${PAPER_MODE_VAL}"; then
    echo "   📝 MODE: PAPER TRADING"
    echo "   ℹ️  Simulated trading only, no real money"
else
    echo "   ⚠️  MODE: UNCLEAR"
    echo "   ⚠️  No mode flags explicitly set"
    echo "   ⚠️  Bot behavior may be unpredictable"
    echo ""
    echo "   Recommended: Set one of the following:"
    echo "      export DRY_RUN_MODE=true           # For full simulation (safest)"
    echo "      export PAPER_MODE=true             # For paper trading"
    echo "      export LIVE_CAPITAL_VERIFIED=true  # For live trading (use with caution)"
fi

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# ═══════════════════════════════════════════════════════════════════════
# GUARD 1: Block live trading when git metadata is unknown
# Untraceable code cannot be audited or safely rolled back.
# ═══════════════════════════════════════════════════════════════════════
if is_truthy "${LIVE_CAPITAL_VERIFIED_VAL}" && ! is_truthy "${DRY_RUN_MODE_VAL}"; then
    if [ "${BRANCH_VAL:-unknown}" = "unknown" ] || [ "${COMMIT_VAL:-unknown}" = "unknown" ]; then
        if ! is_truthy "${ALLOW_UNTRACEABLE_CODE:-false}"; then
            echo ""
            echo "❌ BLOCKED: Live trading requires traceable git metadata."
            echo "   Branch: ${BRANCH_VAL:-unknown}  Commit: ${COMMIT_VAL:-unknown}"
            echo ""
            echo "   Options:"
            echo "     1. Set git metadata:     bash inject_git_metadata.sh"
            echo "     2. Test safely first:    export DRY_RUN_MODE=true"
            echo "     3. Override (emergency): export ALLOW_UNTRACEABLE_CODE=true"
            echo ""
            exit 1
        fi
        echo "⚠️  WARNING: ALLOW_UNTRACEABLE_CODE=true — git metadata check bypassed"
    fi
fi

# ═══════════════════════════════════════════════════════════════════════
# GUARD 2: Confirm that live trading is intentional
# ═══════════════════════════════════════════════════════════════════════
if is_truthy "${LIVE_CAPITAL_VERIFIED_VAL}" && ! is_truthy "${DRY_RUN_MODE_VAL}"; then
    if is_truthy "${LIVE_TRADING_CONFIRMED:-false}"; then
        echo "✅ Live trading confirmed (LIVE_TRADING_CONFIRMED=true)"
    elif [ -t 0 ]; then
        echo ""
        echo "╔══════════════════════════════════════════════════════════════════════════════╗"
        echo "║  ⚠️  LIVE TRADING — OPERATOR CONFIRMATION REQUIRED                           ║"
        echo "╚══════════════════════════════════════════════════════════════════════════════╝"
        echo ""
        echo "   🔴 REAL MONEY AT RISK. Live orders will be placed on exchanges."
        echo "   Branch: ${BRANCH_VAL:-unknown}  Commit: ${COMMIT_VAL:-unknown}"
        echo ""
        read -p "   Type 'yes' to confirm live trading: " -r
        echo ""
        if [[ ! $REPLY =~ ^[Yy][Ee][Ss]$ ]]; then
            echo "❌ Live trading not confirmed. Exiting."
            echo "   To test safely: export DRY_RUN_MODE=true"
            exit 0
        fi
        echo "✅ Live trading confirmed by operator."
    else
        echo "✅ Live trading approved: LIVE_CAPITAL_VERIFIED=true in non-interactive session."
    fi
fi

# Kraken credentials are REQUIRED (primary broker); Coinbase credentials are OPTIONAL (secondary broker)
if [ -z "${KRAKEN_PLATFORM_API_KEY}" ] || [ -z "${KRAKEN_PLATFORM_API_SECRET}" ]; then
    echo ""
    echo "⚠️  MISSING KRAKEN CREDENTIALS — LIVE MODE REQUIRES API KEY + SECRET"
    echo ""
    echo "Kraken is the primary broker. Coinbase can be connected as a secondary broker."
    echo "Set these environment variables, then re-run:"
    echo "   export KRAKEN_PLATFORM_API_KEY='<your-api-key>'"
    echo "   export KRAKEN_PLATFORM_API_SECRET='<your-api-secret>'"
    echo ""
    echo "Alternatively, place them in .env (now auto-loaded on start)."
    echo ""
    echo "📖 See .env.example for detailed setup instructions"
    echo ""
    exit_config_error
fi

# Enforce live mode explicitly
export PAPER_MODE=false

# Log monitoring guidance — watch for execution errors and trade rejections
echo ""
echo "📋 LOG MONITORING: Logs stream to stdout and nija.log"
echo "   Key patterns to watch:"
echo "      ❌ ORDER REJECTED / EXECUTION ERROR — trade could not be placed"
echo "      ⚠️  API ERROR / RATE LIMITED       — connectivity or throttling issues"
echo "      ⚠️  INSUFFICIENT FUNDS             — balance too low for trade"
echo ""

echo "🔄 Starting live trading bot..."
echo "Working directory: $(pwd)"
echo "Bot file exists: $(test -f ./bot.py && echo 'YES' || echo 'NO')"

if [ ! -f "./bot.py" ]; then
    echo "❌ Entrypoint file missing: ./bot.py"
    echo "   Verify Railway start command and repository working directory."
    exit 1
fi

# Sleep briefly to ensure all bash output is flushed before Python starts
# This prevents log message interleaving between bash and Python stdout
sleep 0.1

# Startup guard: show first lines of bot.py to detect stale images
if [ -f bot.py ]; then
    echo "--- bot.py (head) ---"
    head -n 10 bot.py || true
    echo "----------------------"

    # Fail-fast: detect stale cached images
    if head -n 1 bot.py | grep -q "NEW BOT.PY IS RUNNING"; then
        echo "❌ Detected stale cached image: RuntimeError banner present in bot.py"
        echo "👉 Delete the Render service and redeploy from the main branch."
        exit 2
    fi
    if head -n 10 bot.py | grep -q "from nija_strategy"; then
        echo "❌ Detected stale cached image: old import 'nija_strategy' in bot.py"
        echo "👉 Delete the Render service and redeploy from the main branch."
        exit 2
    fi
fi

# Start the canonical Python entrypoint with unbuffered output.
# `set -e` would terminate the script immediately on non-zero exit, so
# temporarily disable it to capture and classify the bot exit status.
set +e
$PY -u main.py
status=$?
set -e

# Treat SIGTERM (143) as graceful to avoid restart loops during platform stop/redeploy
if [ "$status" -eq 0 ]; then
    exit 0
fi
if [ "$status" -eq 143 ]; then
    echo "⚠️ Bot received SIGTERM (143). Treating as graceful stop."
    exit 0
fi
if [ "$status" -eq 42 ]; then
    echo "⚠️ Bot exited due to distributed writer lock contention (42)."
    echo "   Another writer is already active; treating as safe fail-closed stop."
    exit 0
fi

echo "❌ Bot crashed! Exit code: $status"

# Print actionable diagnostics from the rotating runtime log to avoid
# blind restart loops with only an exit code in Railway logs.
if [ -f "./nija.log" ]; then
    echo "----- nija.log tail (last 200 lines) -----"
    tail -n 200 "./nija.log" || true
    echo "----- end nija.log tail -----"
fi

if [ -f "./data/nija.log" ]; then
    echo "----- data/nija.log tail (last 200 lines) -----"
    tail -n 200 "./data/nija.log" || true
    echo "----- end data/nija.log tail -----"
fi

exit 1
