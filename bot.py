#!/usr/bin/env python3
"""
NIJA Trading Bot - Main Entry Point
Runs the complete APEX v7.1 strategy with Coinbase Advanced Trade API
Railway deployment: Force redeploy with position size fix ($5 minimum)
"""

import json
import os
import sys
import time
import logging
import socket
import secrets
import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
import signal
import threading
import subprocess

# ── HF Scalping Mode — import early so cycle interval is available ─────────
# When HF_SCALP_MODE=1 the cycle interval drops from 150 s → 30 s and all
# entry filters are tightened.  Falls back silently if the module is absent.
try:
    from bot.hf_scalping_mode import get_hf_scalping_mode as _get_hf_scalping_mode_bot
    _hf_bot = _get_hf_scalping_mode_bot()
except Exception:
    try:
        from hf_scalping_mode import get_hf_scalping_mode as _get_hf_scalping_mode_bot
        _hf_bot = _get_hf_scalping_mode_bot()
    except Exception:
        _hf_bot = None

# ── Module-level singletons — persist across startup retry attempts ────────────
# These are populated after first successful initialisation and reused by the
# supervisor-loop-only restart path so TradingStrategy is never created twice.
_initialized_state: dict = {}
_initialized_state_lock = threading.RLock()

# Single-owner bootstrap kernel lock.
# Only one bootstrap execution sequence may run at a time.  The BotStartup
# thread acquires this non-blocking before entering the retry loop.  If another
# concurrent call sneaks in (e.g. a second spawn from an unexpected code path)
# it is rejected immediately instead of racing through shared init state.
_BOOTSTRAP_SINGLE_OWNER_LOCK = threading.Lock()


@dataclass
class _ExternalWatchdogRestartState:
    requested: bool = False
    reason: str = ""


_external_watchdog_restart = _ExternalWatchdogRestartState()
_external_watchdog_restart_lock = threading.Lock()


def _request_external_watchdog_restart(reason: str) -> None:
    """Flag that the main supervisor must exit for an external watchdog restart."""
    with _external_watchdog_restart_lock:
        _external_watchdog_restart.requested = True
        _external_watchdog_restart.reason = str(reason)


def _consume_external_watchdog_restart_reason() -> str:
    """Return pending external-restart reason and clear the pending flag."""
    with _external_watchdog_restart_lock:
        if not _external_watchdog_restart.requested:
            return ""
        reason = str(_external_watchdog_restart.reason).strip()
        _external_watchdog_restart.requested = False
        _external_watchdog_restart.reason = ""
        return reason


def _is_fatal_nonce_restart_error(exc: Exception) -> bool:
    """Return True for fatal nonce RuntimeErrors that must be externally restarted.

    Triggers on:
      - ``RuntimeError: nonce not authorized``
      - ``RuntimeError: Invalid nonce spike detected``

    These indicate nonce state/auth desync that should not be retried in-process.
    Exiting lets the external watchdog restart with a clean runtime state.
    """
    if not isinstance(exc, RuntimeError):
        return False
    msg = str(exc).lower()
    return (
        "nonce not authorized" in msg
        or "invalid nonce spike detected" in msg
    )

# Import broker types for error reporting
try:
    from bot.broker_manager import BrokerType
except ImportError:
    # Fallback if running from different directory
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))
    from broker_manager import BrokerType

# Constants for error formatting
# Separator length of 63 matches the width of the error message
# "🚨 KRAKEN MASTER CREDENTIALS ARE SET BUT CONNECTION FAILED" (61 chars + 2 spaces padding)
ERROR_SEPARATOR = "═" * 63

# Configuration error heartbeat interval (seconds)
# When configuration errors prevent trading, the bot stays alive to report status
# and updates its heartbeat at this interval
CONFIG_ERROR_HEARTBEAT_INTERVAL = 60

# Heartbeat update interval (seconds) for Railway health check responsiveness
# Background thread updates heartbeat at this frequency to ensure health checks
# always get fresh data (Railway checks every ~30s, this is faster)
HEARTBEAT_INTERVAL_SECONDS = 10

# Keep-alive loop sleep interval (seconds)
# When trading loops exit, the keep-alive loop sleeps for this duration between status logs
# Note: Heartbeat is updated by dedicated background thread, not by this loop
KEEP_ALIVE_SLEEP_INTERVAL_SECONDS = 300

# Synthetic price used only for startup market-readiness probe.
_MARKET_GATE_PROBE_PRICE = 100.0

# EMERGENCY STOP CHECK
# Note: Uses print() instead of logger because logger is not yet initialized
if os.path.exists('EMERGENCY_STOP'):
    print("\n" + "┏" + "━" * 78 + "┓")
    print("┃ 🚨 EXIT POINT - EMERGENCY STOP FILE DETECTED                             ┃")
    print(f"┃ Exit Code: {0:<67} ┃")
    print(f"┃ PID: {os.getpid():<71} ┃")
    print("┣" + "━" * 78 + "┫")
    print("┃ Bot is disabled. See EMERGENCY_STOP file for details.                   ┃")
    print("┃ Delete EMERGENCY_STOP file to resume trading.                           ┃")
    print("┃ This is an intentional shutdown (not a crash).                          ┃")
    print("┗" + "━" * 78 + "┛")
    print("")
    sys.exit(0)

# ── Process lock — prevent multiple bot instances ─────────────────────────────
# Only ONE process should ever touch the Kraken API key.  A second instance
# would generate its own nonce sequence, immediately desyncing from the first
# and producing continuous "EAPI:Invalid nonce" errors on both.
_PID_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "nija.pid")

# Keywords that identify a NIJA bot process in /proc/<pid>/cmdline.
# Used to distinguish a genuinely-running duplicate from PID reuse in a new container.
_NIJA_CMDLINE_MARKERS = (
    "bot.py", "trading_strategy.py", "nija_core_loop.py",
    "tradingview_webhook.py",
)


def _is_nija_process(pid: int) -> bool:
    """Return True only when *pid* belongs to a NIJA bot process.

    Reads ``/proc/<pid>/cmdline`` (Linux) and checks for known NIJA entry-point
    names.  Falls back to ``True`` (conservative / block startup) when the proc
    filesystem is unavailable so the existing safety guarantee is preserved on
    non-Linux platforms.
    """
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as _cf:
            cmdline = _cf.read().replace(b"\x00", b" ").decode("utf-8", errors="replace")
        return any(marker in cmdline for marker in _NIJA_CMDLINE_MARKERS)
    except (FileNotFoundError, ProcessLookupError):
        # PID disappeared between os.kill check and /proc read — treat as gone.
        return False
    except (PermissionError, OSError):
        # /proc unavailable or not accessible — fall back to conservative assumption.
        return True


def _read_pid_file_meta(path: str) -> dict:
    """Read JSON metadata written on line 2+ of *path* (empty dict on any error)."""
    try:
        with open(path, "r", encoding="utf-8") as _mf:
            lines = [ln.strip() for ln in _mf.readlines() if ln.strip()]
        if len(lines) >= 2:
            return json.loads(lines[1])
    except Exception:
        pass
    return {}
_distributed_writer_lock_client = None
_distributed_writer_lock_key = ""
_distributed_writer_lock_token = ""
_distributed_writer_lock_stop = threading.Event()
_distributed_writer_lock_thread = None


def _writer_lock_scope() -> str:
    """Return a stable, non-secret scope id for the current Kraken key."""
    _raw = (
        os.environ.get("KRAKEN_PLATFORM_API_KEY", "").strip()
        or os.environ.get("KRAKEN_API_KEY", "").strip()
        or "default"
    )
    return hashlib.sha256(_raw.encode("utf-8")).hexdigest()[:16]


def _release_distributed_process_lock() -> None:
    """Release distributed single-writer lock iff this process still owns it."""
    global _distributed_writer_lock_client, _distributed_writer_lock_key, _distributed_writer_lock_token
    if not _distributed_writer_lock_client or not _distributed_writer_lock_key or not _distributed_writer_lock_token:
        return
    try:
        _distributed_writer_lock_client.eval(
            """
            if redis.call('GET', KEYS[1]) == ARGV[1] then
                return redis.call('DEL', KEYS[1])
            end
            return 0
            """,
            1,
            _distributed_writer_lock_key,
            _distributed_writer_lock_token,
        )
    except Exception:
        pass
    finally:
        _distributed_writer_lock_client = None
        _distributed_writer_lock_key = ""
        _distributed_writer_lock_token = ""


def _distributed_writer_lock_heartbeat(ttl_s: int) -> None:
    """Keep the distributed writer lock alive; fail closed if ownership is lost."""
    _interval = max(10, ttl_s // 3)
    _failure_streak = 0
    while not _distributed_writer_lock_stop.wait(_interval):
        try:
            _result = _distributed_writer_lock_client.eval(
                """
                if redis.call('GET', KEYS[1]) == ARGV[1] then
                    return redis.call('EXPIRE', KEYS[1], tonumber(ARGV[2]))
                end
                return 0
                """,
                1,
                _distributed_writer_lock_key,
                _distributed_writer_lock_token,
                str(ttl_s),
            )
            if int(_result or 0) != 1:
                print(
                    "\n🚫 Distributed single-writer lock lost; "
                    "another NIJA writer may be active. Exiting for safety."
                )
                _distributed_writer_lock_stop.set()
                _release_distributed_process_lock()
                os._exit(1)
            _failure_streak = 0
        except Exception as _hb_exc:
            _failure_streak += 1
            if _failure_streak >= 3:
                print(
                    f"\n🚫 Distributed lock heartbeat failed 3x ({_hb_exc}); "
                    "exiting to preserve single-writer invariant."
                )
                _distributed_writer_lock_stop.set()
                _release_distributed_process_lock()
                os._exit(1)


def _acquire_distributed_process_lock() -> None:
    """Acquire cross-deployment single-writer lock via Redis when configured."""
    global _distributed_writer_lock_client, _distributed_writer_lock_key, _distributed_writer_lock_token
    global _distributed_writer_lock_thread
    _redis_url = os.environ.get("NIJA_REDIS_URL", "").strip() or os.environ.get("REDIS_URL", "").strip()
    if not _redis_url:
        print("⚠️ Distributed single-writer lock disabled (NIJA_REDIS_URL/REDIS_URL not set).")
        return
    try:
        import redis  # local import to avoid hard startup dependency when Redis isn't used
        _ttl_s = max(30, int(os.environ.get("NIJA_WRITER_LOCK_TTL_S", "90")))
        _scope = _writer_lock_scope()
        _lock_key = os.environ.get("NIJA_WRITER_LOCK_KEY", "").strip() or f"nija:writer_lock:{_scope}"
        _token = f"{socket.gethostname()}:{os.getpid()}:{secrets.token_hex(8)}"
        _client = redis.Redis.from_url(
            _redis_url,
            decode_responses=True,
            socket_connect_timeout=3,
            socket_timeout=3,
        )
        try:
            _client.ping()
        except Exception as _ping_exc:
            raise RuntimeError(
                f"Redis connectivity check failed for distributed writer lock: {_ping_exc}"
            ) from _ping_exc
        _acquired = _client.set(_lock_key, _token, nx=True, ex=_ttl_s)
        if not _acquired:
            _holder = _client.get(_lock_key) or "<unknown-holder>"
            print("\n" + "┏" + "━" * 78 + "┓")
            print("┃ 🚫 DUPLICATE DEPLOYMENT BLOCKED                                           ┃")
            print("┃ Another NIJA writer already holds the distributed runtime lock.          ┃")
            print("┃ Single-writer invariant violated by deployment topology.                 ┃")
            print(f"┃ Lock key: {_lock_key[-58:]:<58} ┃")
            print(f"┃ Holder:   {_holder[:58]:<58} ┃")
            print("┗" + "━" * 78 + "┛\n")
            sys.exit(1)
        _distributed_writer_lock_client = _client
        _distributed_writer_lock_key = _lock_key
        _distributed_writer_lock_token = _token
        _distributed_writer_lock_stop.clear()
        _distributed_writer_lock_thread = threading.Thread(
            target=_distributed_writer_lock_heartbeat,
            args=(_ttl_s,),
            daemon=True,
            name="DistributedWriterLockHeartbeat",
        )
        _distributed_writer_lock_thread.start()
        print(f"🔒 Distributed writer lock acquired — key={_lock_key}")
    except Exception as _lock_exc:
        print(f"❌ Failed to acquire distributed single-writer lock: {_lock_exc}")
        print("   Exiting fail-closed to preserve one-writer invariant.")
        sys.exit(1)


def _acquire_process_lock() -> None:
    """
    Write PID file and abort if another bot instance is already running.

    Stale PID files (process no longer exists or belongs to a non-NIJA process)
    are silently overwritten so a clean restart after a crash or a container
    redeploy always succeeds.

    In containerised deployments (Docker / Railway) the same PID number can be
    re-assigned to a completely different process in the new container.  To
    prevent a false-positive "DUPLICATE INSTANCE BLOCKED" we cross-check:

    1. Is the PID alive?           (os.kill signal-0)
    2. Is it actually a NIJA bot?  (_is_nija_process — reads /proc/<pid>/cmdline)
    3. Does the saved fingerprint  (_read_pid_file_meta — hostname/container)
       match the current host?

    If any check fails the stored PID is treated as stale and overwritten.
    """
    os.makedirs(os.path.dirname(_PID_FILE), exist_ok=True)

    if os.path.exists(_PID_FILE):
        try:
            with open(_PID_FILE) as _pf:
                _first_line = _pf.readline().strip()
            _old_pid = int(_first_line)
            os.kill(_old_pid, 0)   # signal 0 = "does this PID exist?"

            # PID exists — but verify it's genuinely a NIJA process, not a
            # recycled PID from a different container / system process.
            if not _is_nija_process(_old_pid):
                print(
                    f"⚠️  PID {_old_pid} in lock file is not a NIJA process "
                    "(likely PID reuse after container restart) — overwriting stale lock."
                )
                raise ProcessLookupError  # treat as stale

            # Cross-check the saved container fingerprint so we don't block a
            # restart caused by a previous deployment on a different host.
            _meta = _read_pid_file_meta(_PID_FILE)
            _saved_container = _meta.get("container_id", "")
            _saved_hostname   = _meta.get("hostname", "")
            _current_hostname = socket.gethostname()
            # Use empty string when HOSTNAME is missing so the comparison is
            # explicit — an unknown current container never falsely matches.
            _current_container = os.environ.get("HOSTNAME", "").strip()
            if (
                _saved_container
                and _current_container  # skip check when current container is unknown
                and _saved_container != _current_container
            ):
                print(
                    f"⚠️  Lock file container ({_saved_container}) ≠ current container "
                    f"({_current_container}) — overwriting stale cross-container lock."
                )
                raise ProcessLookupError  # treat as stale
            if (
                _saved_hostname
                and _saved_hostname != _current_hostname
            ):
                print(
                    f"⚠️  Lock file hostname ({_saved_hostname}) ≠ current hostname "
                    f"({_current_hostname}) — overwriting stale cross-host lock."
                )
                raise ProcessLookupError  # treat as stale

            # Process is alive, is a NIJA bot, and belongs to this host — block.
            print("\n" + "┏" + "━" * 78 + "┓")
            print(f"┃ 🚫 DUPLICATE INSTANCE BLOCKED                                             ┃")
            print(f"┃ Another NIJA bot is already running (PID {_old_pid:<33}) ┃")
            print(f"┃ Only ONE process may hold the API key at a time.                         ┃")
            print(f"┃ Stop the running bot first:  kill {_old_pid:<44} ┃")
            print(f"┃ Then remove the lock:        rm {_PID_FILE[-40:]:<42} ┃")
            print("┗" + "━" * 78 + "┛\n")
            sys.exit(1)
        except (ProcessLookupError, ValueError, OSError):
            # Stale PID file — the previous process is gone; safe to overwrite.
            pass

    # Write PID + fingerprint metadata so future instances can cross-check.
    _pid_meta = {
        "pid": os.getpid(),
        "hostname": socket.gethostname(),
        "container_id": os.environ.get("HOSTNAME", "").strip() or "unknown",
        "started_at": time.time(),
    }
    with open(_PID_FILE, "w") as _pf:
        _pf.write(f"{os.getpid()}\n")
        _pf.write(json.dumps(_pid_meta, sort_keys=True) + "\n")

    import atexit
    atexit.register(_release_process_lock)
    _acquire_distributed_process_lock()
    print(f"🔒 Process lock acquired (PID {os.getpid()}) — {_PID_FILE}")


def _release_process_lock() -> None:
    """Remove the PID file on clean exit."""
    _distributed_writer_lock_stop.set()
    _release_distributed_process_lock()
    try:
        if os.path.exists(_PID_FILE):
            with open(_PID_FILE) as _pf:
                _stored = int(_pf.readline().strip())
            if _stored == os.getpid():
                os.remove(_PID_FILE)
    except Exception:
        pass


_acquire_process_lock()


def _start_health_server():
    """
    Start HTTP health server with Railway-optimized liveness endpoint.
    
    CRITICAL for Railway deployment:
    - /health and /healthz ALWAYS return 200 OK (stateless, < 50ms)
    - No dependencies on bot state, locks, or initialization
    - Binds immediately before any Kraken connections or user loading
    
    This prevents Railway from killing the container during startup.
    
    Other endpoints:
    - /ready or /readiness - Readiness probe (is service ready to handle traffic?)
    - /status - Detailed status information for operators
    """
    try:
        # Resolve port with a safe default if env is missing
        port_env = os.getenv("PORT", "")
        default_port = 8080
        try:
            port = int(port_env) if port_env else default_port
        except Exception:
            port = default_port
        from http.server import BaseHTTPRequestHandler, HTTPServer
        import json

        class HealthHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                try:
                    # Railway liveness probe - ALWAYS returns 200 OK (stateless, no checks)
                    # No logging. No conditionals. No imports. Dumb and fast wins.
                    # This ensures Railway never kills the container during startup
                    if self.path in ("/health", "/healthz"):
                        self.send_response(200)
                        self.send_header("Content-Type", "text/plain")
                        self.end_headers()
                        self.wfile.write(b"ok")
                    
                    # Readiness probe - returns 200 only if ready, 503 if not ready/config error
                    elif self.path in ("/ready", "/readiness"):
                        try:
                            from bot.health_check import get_health_manager
                            health_manager = get_health_manager()
                            status, http_code = health_manager.get_readiness_status()
                            self.send_response(http_code)
                            self.send_header("Content-Type", "application/json")
                            self.end_headers()
                            self.wfile.write(json.dumps(status).encode())
                        except Exception:
                            # If health manager not ready, return not ready
                            self.send_response(503)
                            self.send_header("Content-Type", "application/json")
                            self.end_headers()
                            self.wfile.write(json.dumps({"status": "not_ready", "reason": "initializing"}).encode())
                    
                    # Detailed status for operators and debugging
                    elif self.path in ("/status", "/"):
                        try:
                            from bot.health_check import get_health_manager
                            health_manager = get_health_manager()
                            status = health_manager.get_detailed_status()
                            self.send_response(200)
                            self.send_header("Content-Type", "application/json")
                            self.end_headers()
                            self.wfile.write(json.dumps(status, indent=2).encode())
                        except Exception:
                            # If health manager not ready, return basic status
                            self.send_response(200)
                            self.send_header("Content-Type", "application/json")
                            self.end_headers()
                            self.wfile.write(json.dumps({"status": "initializing"}, indent=2).encode())
                    
                    # Prometheus metrics endpoint
                    elif self.path == "/metrics":
                        try:
                            from bot.health_check import get_health_manager
                            health_manager = get_health_manager()
                            metrics = health_manager.get_prometheus_metrics()
                            self.send_response(200)
                            self.send_header("Content-Type", "text/plain; version=0.0.4")
                            self.end_headers()
                            self.wfile.write(metrics.encode())
                        except Exception:
                            # Return minimal metrics if health manager not ready
                            self.send_response(200)
                            self.send_header("Content-Type", "text/plain; version=0.0.4")
                            self.end_headers()
                            self.wfile.write(b"# Initializing\nnija_up 1\n")
                    
                    else:
                        self.send_response(404)
                        self.send_header("Content-Type", "application/json")
                        self.end_headers()
                        self.wfile.write(json.dumps({
                            "error": "Not found",
                            "available_endpoints": ["/health", "/healthz", "/ready", "/readiness", "/status", "/metrics"]
                        }).encode())
                except Exception as e:
                    try:
                        self.send_response(500)
                        self.send_header("Content-Type", "application/json")
                        self.end_headers()
                        self.wfile.write(json.dumps({"error": str(e)}).encode())
                    except Exception:
                        pass
            
            def log_message(self, format, *args):
                # Silence default HTTP server logging to reduce noise
                return

        server = HTTPServer(("0.0.0.0", port), HealthHandler)
        t = threading.Thread(target=server.serve_forever, daemon=True, name="HealthServer")
        t.start()
        print(f"🌐 Health server listening on port {port} (Railway-optimized)")
        print(f"   📍 Liveness:  http://0.0.0.0:{port}/health (ALWAYS returns 200 OK)")
        print(f"   📍 Readiness: http://0.0.0.0:{port}/ready")
        print(f"   📍 Status:    http://0.0.0.0:{port}/status")
        print(f"   📍 Metrics:   http://0.0.0.0:{port}/metrics")
    except Exception as e:
        print(f"❌ Health server failed to start: {e}")

# Load .env and verify the result at runtime
_dotenv_loaded = False
try:
    from dotenv import load_dotenv
    from pathlib import Path as _Path
    _env_path = _Path(__file__).parent / ".env"
    if _env_path.exists():
        load_dotenv(str(_env_path))
        _dotenv_loaded = True
    else:
        # No .env file — env vars must be injected by the platform (e.g. Railway)
        load_dotenv()  # still call so any inline env exports are picked up
except ImportError:
    pass  # dotenv not available, env vars should be set externally

# Setup paths (must come before _verify_env so trading_state_machine is importable)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

# ── Bootstrap FSM — best-effort import ───────────────────────────────────────
# Imported here so transitions are available throughout the module.  All usage
# is wrapped in try/except so a missing or broken module never stops the bot.
try:
    from bot.bootstrap_state_machine import (
        BootstrapState as _BootstrapState,
        get_bootstrap_fsm as _get_bootstrap_fsm,
    )
    _BOOTSTRAP_FSM_AVAILABLE = True
except ImportError:
    _get_bootstrap_fsm = None  # type: ignore[assignment]
    _BootstrapState = None     # type: ignore[assignment]
    _BOOTSTRAP_FSM_AVAILABLE = False


def _bfsm_transition(state, reason: str = "") -> None:
    """Best-effort bootstrap FSM transition.  Never raises; never blocks."""
    if not _BOOTSTRAP_FSM_AVAILABLE:
        return
    try:
        _get_bootstrap_fsm().transition(state, reason)
    except Exception as _bfsm_err:
        try:
            import logging as _lg
            _lg.getLogger("nija.bootstrap_fsm").debug(
                "bootstrap FSM transition to %s failed (non-fatal): %s", state, _bfsm_err
            )
        except Exception:
            pass


# Verify critical environment variables are present
def _verify_env() -> None:
    """Warn loudly if required runtime variables are absent after .env loading."""
    import logging as _log
    _ev = _log.getLogger("nija.env")
    _ev.info("=" * 60)
    if _dotenv_loaded:
        _ev.info("✅ .env file loaded from disk")
    else:
        _ev.info("ℹ️  No .env file on disk — relying on platform environment variables")

    _required = {
        "COINBASE_API_KEY":    "Coinbase API key",
        "COINBASE_API_SECRET": "Coinbase API secret",
        "LIVE_CAPITAL_VERIFIED": "Live-trading safety gate",
    }
    _missing = [name for name in _required if not os.getenv(name)]
    if _missing:
        for name in _missing:
            _ev.warning("⚠️  Missing required env var: %s (%s)", name, _required[name])
        _ev.warning(
            "⚠️  Set the above variables in your .env file (local) "
            "or in the Railway Variables tab (production)."
        )
    else:
        _ev.info("✅ All required environment variables are present")

    # Kraken platform credentials must BOTH be present or BOTH absent.
    # A partial configuration (key without secret, or vice versa) causes the
    # platform-first gate to mark Kraken as failed at startup, which permanently
    # blocks user accounts from connecting for the lifetime of the process.
    kraken_api_key    = os.getenv("KRAKEN_PLATFORM_API_KEY") or os.getenv("KRAKEN_API_KEY")
    kraken_api_secret = os.getenv("KRAKEN_PLATFORM_API_SECRET") or os.getenv("KRAKEN_API_SECRET")
    if bool(kraken_api_key) != bool(kraken_api_secret):
        _ev.warning(
            "⚠️  Kraken credentials are INCOMPLETE — set BOTH "
            "KRAKEN_PLATFORM_API_KEY and KRAKEN_PLATFORM_API_SECRET "
            "(or leave both empty to disable Kraken). "
            "A partial config causes the platform-first gate to block ALL user accounts."
        )
    elif kraken_api_key and kraken_api_secret:
        _ev.info("✅ Kraken platform credentials detected")
    _lcv = os.getenv("LIVE_CAPITAL_VERIFIED", "false").lower().strip()
    if _lcv in ("true", "1", "yes", "enabled"):
        try:
            from trading_state_machine import get_state_machine
            _sm = get_state_machine()
            if _sm.maybe_auto_activate():
                _ev.info("✅ Trading state machine: auto-transitioned to LIVE_ACTIVE")
            else:
                _ev.info("ℹ️  Trading state machine: auto-activate skipped (already active or gate blocked)")
        except Exception as _sm_err:
            _ev.warning("⚠️  Could not auto-activate state machine: %s", _sm_err)
    else:
        _ev.info(
            "🔒 LIVE_CAPITAL_VERIFIED is not 'true' — live trading remains OFF. "
            "Set LIVE_CAPITAL_VERIFIED=true in .env to enable."
        )
    _ev.info("=" * 60)

_verify_env()


# Import after path setup
from trading_strategy import TradingStrategy

# Setup logging - configure ONCE to prevent duplicates
LOG_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), 'nija.log'))

# Remove any existing handlers first
root = logging.getLogger()
if root.handlers:
    for handler in list(root.handlers):
        root.removeHandler(handler)

# Get nija logger
logger = logging.getLogger("nija")
logger.setLevel(logging.INFO)
logger.propagate = False  # Prevent propagation to root logger

# Single formatter with consistent timestamp format
formatter = logging.Formatter(
    '%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# Add handlers only if not already present
if not logger.hasHandlers():
    file_handler = RotatingFileHandler(LOG_FILE, maxBytes=2*1024*1024, backupCount=2)
    file_handler.setFormatter(formatter)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    # Ensure immediate flushing to prevent log message interleaving
    console_handler.flush = lambda: sys.stdout.flush()
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

# ── A. Startup Event Buffer ───────────────────────────────────────────────────
# Intercepts the console handler during startup so all log records are batched
# and flushed once per phase.  The file handler keeps writing immediately —
# nothing is lost.  Eliminates Railway log-throttle bursts.
_startup_buffer = None
try:
    from bot.startup_event_buffer import install_startup_buffer as _install_seb
    for _h in list(logger.handlers):
        if isinstance(_h, logging.StreamHandler) and getattr(_h, "stream", None) is sys.stdout:
            _startup_buffer = _install_seb(logger, _h)
            break
    if _startup_buffer is None:
        print("⚠️  Startup event buffer: no stdout handler found — buffer inactive")
except Exception as _seb_err:
    print(f"⚠️  Startup event buffer unavailable (non-fatal): {_seb_err}")

# ── B. Phase Gate  +  C. Init-Once Registry ───────────────────────────────────
# Import the hard-gate enforcement layer.  A minimal fallback class is used
# when the module is unavailable so bot.py never crashes due to missing infra.
try:
    from bot.startup_phase_gate import Phase as _Phase, advance_phase as _advance_phase
    from bot.init_once_guard import check_init_once as _check_init_once
    _PHASE_GATE_AVAILABLE = True
except Exception as _pg_err:
    print(f"⚠️  Phase gate / init-once guard unavailable (non-fatal): {_pg_err}")
    _PHASE_GATE_AVAILABLE = False

    class _Phase:  # type: ignore[no-redef]
        ENV_VALIDATION = BROKER_REGISTRY = CAPITAL_BRAIN = 0
        STRATEGY_ENGINE = EXECUTION_LAYER = LIVE_ENABLE = 0

    def _advance_phase(*_a, **_kw) -> None:  # type: ignore[misc]
        pass

    def _check_init_once(_n: str) -> bool:  # type: ignore[misc]
        return True


def _log_lifecycle_banner(title, details=None):
    """
    Log a visual lifecycle banner for major state transitions.
    
    Args:
        title: The main title to display
        details: Optional list of detail strings to include
    """
    logger.info("")
    logger.info("╔" + "═" * 78 + "╗")
    logger.info(f"║ {title:^76} ║")
    if details:
        logger.info("╠" + "═" * 78 + "╣")
        for detail in details:
            logger.info(f"║ {detail:76} ║")
    logger.info("╚" + "═" * 78 + "╝")
    logger.info("")


def _log_exit_point(reason, exit_code=0, details=None):
    """
    Log a visual exit point marker before sys.exit().
    
    Args:
        reason: Why the process is exiting
        exit_code: The exit code (0 = success, 1 = error)
        details: Optional list of detail strings
    """
    icon = "✅" if exit_code == 0 else "❌"
    logger.info("")
    logger.info("┏" + "━" * 78 + "┓")
    logger.info(f"┃ {icon} EXIT POINT - {reason:68} ┃")
    logger.info(f"┃ Exit Code: {exit_code:<67} ┃")
    logger.info(f"┃ PID: {os.getpid():<71} ┃")
    if details:
        logger.info("┣" + "━" * 78 + "┫")
        for detail in details:
            logger.info(f"┃ {detail:76} ┃")
    logger.info("┗" + "━" * 78 + "┛")
    logger.info("")


def _get_thread_status():
    """Get status of all running threads for visual verification."""
    threads = threading.enumerate()
    status = []
    status.append(f"Total Threads: {len(threads)}")
    for thread in threads:
        daemon_marker = "🔹" if thread.daemon else "🔸"
        alive_marker = "✅" if thread.is_alive() else "❌"
        status.append(f"  {daemon_marker} {alive_marker} {thread.name} (ID: {thread.ident})")
    return status


def _handle_signal(sig, frame):
    """Handle shutdown signals (SIGTERM, SIGINT) with visual logging."""
    _release_process_lock()
    _bfsm_transition(_BootstrapState.SHUTDOWN, f"signal {sig} received") if _BOOTSTRAP_FSM_AVAILABLE else None
    signal_name = signal.Signals(sig).name if hasattr(signal, 'Signals') else str(sig)
    _log_exit_point(
        f"Signal {signal_name} received",
        exit_code=0,
        details=[
            "Graceful shutdown initiated by signal handler",
            "This is an expected exit (not a crash)",
            *_get_thread_status()
        ]
    )
    sys.exit(0)


def _log_kraken_connection_error_header(error_msg):
    """
    Log Kraken Master connection error header with consistent formatting.

    Args:
        error_msg: The error message to display, or None if no specific error
    """
    logger.error("")
    logger.error(f"      {ERROR_SEPARATOR}")
    logger.error(f"      🚨 KRAKEN PLATFORM CREDENTIALS ARE SET BUT CONNECTION FAILED")
    logger.error(f"      {ERROR_SEPARATOR}")
    if error_msg:
        logger.error(f"      ❌ Error: {error_msg}")
    else:
        logger.error("      ❌ No specific error message was captured")
    logger.error("")


def _log_memory_usage():
    """
    Log lightweight memory usage at startup.
    
    Logs RSS (Resident Set Size) and VMS (Virtual Memory Size) in a single line.
    Optionally warns if memory usage exceeds 70% of available system memory.
    """
    try:
        import psutil
        
        # Get current process memory info
        process = psutil.Process(os.getpid())
        mem_info = process.memory_info()
        
        # RSS: Resident Set Size (physical memory used)
        # VMS: Virtual Memory Size (total virtual memory)
        rss_mb = mem_info.rss / (1024 * 1024)  # Convert to MB
        vms_mb = mem_info.vms / (1024 * 1024)  # Convert to MB
        
        # Get system memory for percentage calculation
        system_mem = psutil.virtual_memory()
        total_mb = system_mem.total / (1024 * 1024)
        percent_used = (mem_info.rss / system_mem.total) * 100
        
        # Single line log with RSS and VMS
        logger.info(f"💾 Memory: RSS={rss_mb:.1f}MB, VMS={vms_mb:.1f}MB ({percent_used:.1f}% of {total_mb:.0f}MB system)")
        
        # Optional: warn if memory usage is at 70% of system memory
        if percent_used >= 70.0:
            logger.warning(f"⚠️  High memory usage: {percent_used:.1f}% (threshold: 70%)")
            
    except ImportError:
        # psutil not available - use basic resource module as fallback
        try:
            import resource
            usage = resource.getrusage(resource.RUSAGE_SELF)
            # maxrss is in KB on Linux, bytes on macOS
            import platform
            if platform.system() == 'Darwin':  # macOS
                rss_mb = usage.ru_maxrss / (1024 * 1024)
            else:  # Linux
                rss_mb = usage.ru_maxrss / 1024
            logger.info(f"💾 Memory: RSS={rss_mb:.1f}MB (psutil not available, limited info)")
        except Exception as e:
            logger.debug(f"Could not log memory usage: {e}")
    except Exception as e:
        logger.debug(f"Error logging memory usage: {e}")


def _start_trader_thread(independent_trader, broker_type, broker):
    """
    Wrap a single broker's trading loop in a self-healing daemon thread.

    The inner runner calls ``run_broker_trading_loop`` in a loop so that if
    the function ever returns unexpectedly (fatal crash escaping the inner
    guard), the thread automatically restarts after a 5-second back-off.
    The stop_flag is the single clean-shutdown mechanism.

    Returns:
        tuple: (threading.Thread, threading.Event) – thread and its stop flag.
    """
    broker_name = broker_type.value
    stop_flag = threading.Event()

    def _runner():
        logger.info("🚀 [Orchestrator] Trader thread started for %s", broker_name.upper())
        while not stop_flag.is_set():
            try:
                independent_trader.run_broker_trading_loop(broker_type, broker, stop_flag)
            except Exception as _loop_err:
                if stop_flag.is_set():
                    break
                logger.error(
                    "💥 [Orchestrator] Trader crashed for %s: %s — restarting in 5s",
                    broker_name.upper(),
                    _loop_err,
                    exc_info=True,
                )
                stop_flag.wait(5)
        logger.info("🛑 [Orchestrator] Trader thread stopped for %s", broker_name.upper())

    t = threading.Thread(target=_runner, daemon=True, name=f"Trader-{broker_name}")
    t.start()
    return t, stop_flag


def _start_single_broker_thread(strategy, cycle_secs):
    """
    Wrap ``strategy.run_cycle()`` in a self-healing daemon thread.

    Used as a fallback when ``independent_trader`` is unavailable or when no
    funded platform brokers are detected.  Any exception from ``run_cycle``
    is caught, logged, and retried after 10 seconds so the thread never dies
    silently.

    Returns:
        tuple: (threading.Thread, threading.Event) – thread and its stop flag.
    """
    stop_flag = threading.Event()

    def _is_live_active() -> bool:
        """Return True if the trading state machine is in LIVE_ACTIVE state."""
        try:
            from bot.trading_state_machine import get_state_machine as _gsm, TradingState as _TS
            return _gsm().get_current_state() == _TS.LIVE_ACTIVE
        except Exception:
            try:
                from trading_state_machine import get_state_machine as _gsm, TradingState as _TS  # type: ignore[import]
                return _gsm().get_current_state() == _TS.LIVE_ACTIVE
            except Exception:
                return False  # fail-closed: block execution if state machine is unavailable

    def _try_recover_state_machine() -> None:
        """Attempt to drive the trading state machine from OFF → LIVE_ACTIVE.

        Called when the LIVE_ACTIVE assertion fails so the missing trigger
        (maybe_auto_activate) is fired from inside the execution loop instead
        of waiting for an external supervisor to notice the stuck state.
        All errors are swallowed — this is a best-effort recovery call.
        """
        try:
            from bot.trading_state_machine import get_state_machine as _gsm_r
        except ImportError as _ie:
            logger.debug("_try_recover_state_machine: bot.trading_state_machine unavailable (%s), trying fallback", _ie)
            try:
                from trading_state_machine import get_state_machine as _gsm_r  # type: ignore[import]
            except ImportError:
                return
        try:
            _gsm_r().maybe_auto_activate()
        except Exception as _act_err:
            logger.debug("_try_recover_state_machine: maybe_auto_activate failed (%s)", _act_err)

    def _runner():
        logger.info(
            "🚀 [Orchestrator] Single-broker trading thread started (%ds cadence)",
            cycle_secs,
        )
        cycle = 0
        while not stop_flag.is_set():
            try:
                cycle += 1
                logger.info("🔁 [Orchestrator] Single-broker cycle #%d", cycle)
                # FIX 3: EXECUTION LOOP ASSERTION — prevent silent startup stalls.
                # If LIVE_ACTIVE is not confirmed the cycle is skipped and retried
                # after the normal back-off so the thread never silently stalls.
                assert _is_live_active(), "Execution loop started without LIVE_ACTIVE"
                strategy.run_cycle()
                stop_flag.wait(cycle_secs)
            except AssertionError as _assert_err:
                if stop_flag.is_set():
                    break
                logger.error(
                    "❌ [Orchestrator] Single-broker cycle #%d LIVE_ACTIVE assertion failed: %s"
                    " — attempting state machine recovery then retrying in 10s",
                    cycle,
                    _assert_err,
                )
                # Missing trigger fix: fire maybe_auto_activate() so the state
                # machine can advance from OFF → LIVE_ACTIVE without waiting for
                # an external supervisor call.
                _try_recover_state_machine()
                stop_flag.wait(10)
            except Exception as _cycle_err:
                if stop_flag.is_set():
                    break
                logger.error(
                    "❌ [Orchestrator] Single-broker cycle #%d error: %s — retrying in 10s",
                    cycle,
                    _cycle_err,
                    exc_info=True,
                )
                stop_flag.wait(10)
        logger.info("🛑 [Orchestrator] Single-broker trading thread stopped")

    t = threading.Thread(target=_runner, daemon=True, name="Trader-SingleBroker")
    t.start()
    return t, stop_flag


def _is_truthy_env(var_name: str, default: str = "false") -> bool:
    """Return True when an env var is set to a truthy string."""
    return os.environ.get(var_name, default).strip().lower() in ("1", "true", "yes", "on")


def _coinbase_sdk_is_available() -> bool:
    """Return True if Coinbase SDK import path is available."""
    try:
        import importlib.util as _iutil
        return _iutil.find_spec("coinbase.rest") is not None
    except Exception:
        return False


def _resolve_kraken_startup_credentials() -> tuple:
    """Resolve Kraken startup credentials from supported sources in priority order.

    Returns:
        tuple[str | None, str | None]: (key, secret)
    """
    key = (
        os.getenv("KRAKEN_PLATFORM_API_KEY")
        or os.getenv("KRAKEN_USER_TANIA_GILBERT_API_KEY")
        or os.getenv("KRAKEN_API_KEY")
    )
    secret = (
        os.getenv("KRAKEN_PLATFORM_API_SECRET")
        or os.getenv("KRAKEN_USER_TANIA_GILBERT_API_SECRET")
        or os.getenv("KRAKEN_API_SECRET")
    )
    return key, secret


def _verify_startup_truth_conditions(
    strategy,
    active_threads: dict,
    *,
    kraken_credentials_valid: bool,
) -> None:
    """
    Enforce startup truth conditions before entering supervised loop.
    Raises RuntimeError when any required condition is not met.
    """
    # Condition A — Kraken credentials valid (loaded + structurally valid)
    if not kraken_credentials_valid:
        raise RuntimeError(
            "Condition A failed: Kraken credentials are not valid/loaded. "
            "Set valid KRAKEN_PLATFORM_API_KEY/KRAKEN_PLATFORM_API_SECRET (or legacy pair)."
        )

    # Condition A — Kraken operational (connection succeeded and no permission cache failure)
    _kraken_connected = False
    _mam = getattr(strategy, "multi_account_manager", None)
    if _mam and hasattr(_mam, "platform_brokers"):
        for _bt, _broker in (_mam.platform_brokers or {}).items():
            _name = getattr(_bt, "value", str(_bt)).lower()
            if _name == "kraken" and bool(getattr(_broker, "connected", False)):
                _kraken_connected = True
                break
    if not _kraken_connected:
        raise RuntimeError(
            "Condition A failed: Kraken broker is not operational. "
            "Verify API key permissions include query + trade."
        )

    try:
        from bot.broker_manager import KrakenBroker as _KB
        if "PLATFORM" in getattr(_KB, "_permission_failed_accounts", set()):
            raise RuntimeError(
                "Condition A failed: Kraken PLATFORM permission check previously failed. "
                "Fix API key permissions (query + trade)."
            )
    except RuntimeError:
        raise
    except Exception:
        pass

    # Required by new requirement: BrokerManager initialized
    if getattr(strategy, "broker_manager", None) is None:
        raise RuntimeError("Startup verification failed: BrokerManager did not initialize.")

    # Condition B — threads alive
    _dead_threads = [
        _key for _key, _entry in (active_threads or {}).items()
        if not (_entry.get("thread") is not None and _entry["thread"].is_alive())
    ]
    if _dead_threads:
        raise RuntimeError(
            f"Condition B failed: trader thread(s) not alive immediately after startup: {_dead_threads}"
        )

    # Condition B — FSM must be RUNNING_SUPERVISED (implies not in retry state)
    if _BOOTSTRAP_FSM_AVAILABLE:
        _state = _get_bootstrap_fsm().state
        if _state != _BootstrapState.RUNNING_SUPERVISED:
            raise RuntimeError(
                f"Condition B failed: bootstrap FSM state is {_state}, expected RUNNING_SUPERVISED."
            )

    # New requirement — relaxed market gates must pass
    _mrg = getattr(strategy, "market_readiness_gate", None)
    if _mrg is None:
        raise RuntimeError("Startup verification failed: MarketReadinessGate not initialized.")
    try:
        _mode, _conditions, _details = _mrg.check_market_readiness(
            atr=float(_mrg.AGGRESSIVE_ATR_MIN),
            current_price=_MARKET_GATE_PROBE_PRICE,
            adx=float(_mrg.AGGRESSIVE_ADX_MIN),
            volume_percentile=float(_mrg.AGGRESSIVE_VOLUME_PERCENTILE_MIN),
            spread_pct=float(_mrg.AGGRESSIVE_SPREAD_MAX),
            entry_score=float(getattr(_mrg, "CAUTIOUS_MIN_SCORE", 45.0)),
        )
    except Exception as _gate_err:
        raise RuntimeError(f"Startup verification failed: market readiness gate probe error: {_gate_err}")
    _mode_value = getattr(_mode, "value", str(_mode)).lower()
    if _mode_value == "idle":
        raise RuntimeError(
            f"Startup verification failed: relaxed market gate probe returned IDLE ({_details.get('message')})."
        )


def _rerun_supervisor_loop(state: dict) -> None:
    """
    Re-enter the supervisor loop using a previously initialised bot state.

    Called by ``_run_bot_startup_and_trading()`` when the module-level
    ``_initialized_state`` is already populated — i.e. on a *retry* after the
    supervisor loop crashed.  This avoids recreating ``TradingStrategy`` and
    re-connecting all brokers on every restart.

    Args:
        state: dict with keys ``strategy``, ``active_threads``,
               ``use_independent_trading``, and ``health_manager``.
    """
    from bot.health_check import get_health_manager

    strategy = state["strategy"]
    _active_threads = state["active_threads"]
    use_independent_trading = state["use_independent_trading"]
    health_manager = get_health_manager()

    logger.info(
        "♻️  Re-entering supervisor loop — init already completed "
        "(%d active thread(s))",
        len(_active_threads),
    )

    # Cache the state machine once at loop entry so the per-cycle health check
    # does not repeat the import on every iteration.
    _sl_sm = None
    _sl_off = None
    try:
        from bot.trading_state_machine import get_state_machine as _gsm_sl, TradingState as _TS_sl
        _sl_sm = _gsm_sl()
        _sl_off = _TS_sl.OFF
    except Exception as _sl_import_err:
        logger.debug("_rerun_supervisor_loop: trading_state_machine unavailable (%s)", _sl_import_err)

    _orch_cycle = 0
    while True:
        try:
            _orch_cycle += 1
            health_manager.heartbeat()

            # ── State machine health step ─────────────────────────────────────
            # Ensure OFF → LIVE_ACTIVE is never silently missed during the
            # supervisor loop lifetime.  If the state machine somehow falls back
            # to OFF (e.g. a concurrent reset between bootstrap and here), firing
            # maybe_auto_activate() here recovers it on the next supervision
            # cycle without waiting for an external trigger.  All errors are
            # swallowed so a failed step never stalls the supervisor loop.
            if _sl_sm is not None and _sl_off is not None:
                try:
                    if _sl_sm.get_current_state() == _sl_off:
                        logger.info(
                            "[Supervisor] State machine is OFF — calling maybe_auto_activate() to recover"
                        )
                        _sl_sm.maybe_auto_activate()
                except Exception as _sl_step_err:
                    logger.debug("_rerun_supervisor_loop: state machine step failed (%s)", _sl_step_err)

            # ── Adopt threads started by the connection monitor ───────────────
            # The connection monitor in IndependentBrokerTrader can start new
            # platform threads after a broker that was offline at boot comes
            # back online.  Those threads live in independent_trader.broker_threads
            # but are not initially tracked here.  Adopt them so the supervisor
            # can restart them if they die.
            if use_independent_trading and strategy.independent_trader:
                _ibt = strategy.independent_trader
                for _cm_bname, _cm_t in list(_ibt.broker_threads.items()):
                    if _cm_bname not in _active_threads and _cm_t.is_alive():
                        _cm_bt = _ibt.broker_thread_types.get(_cm_bname)
                        _cm_broker = None
                        if _cm_bt is not None:
                            try:
                                _cm_broker = _ibt._get_platform_broker_source().get(_cm_bt)
                            except Exception:
                                pass
                        _active_threads[_cm_bname] = {
                            "thread": _cm_t,
                            "stop_flag": _ibt.stop_flags.get(_cm_bname, threading.Event()),
                            "broker_type": _cm_bt,
                            "broker": _cm_broker,
                            "mode": "platform",
                        }
                        logger.info(
                            "📌 [Orchestrator] Adopted connection-monitor thread '%s' into supervisor",
                            _cm_bname.upper(),
                        )

            for _bname, _entry in list(_active_threads.items()):
                _t = _entry["thread"]
                _sf = _entry["stop_flag"]
                if not _t.is_alive() and not _sf.is_set():
                    logger.critical(
                        "💥 [Orchestrator] Trader thread '%s' DIED — restarting…",
                        _bname.upper(),
                    )
                    if _entry["mode"] == "platform":
                        _new_t, _new_sf = _start_trader_thread(
                            strategy.independent_trader,
                            _entry["broker_type"],
                            _entry["broker"],
                        )
                    elif _entry["mode"] == "user":
                        _new_sf = threading.Event()
                        _new_t = threading.Thread(
                            target=strategy.independent_trader.run_user_broker_trading_loop,
                            args=(
                                _entry["user_id"],
                                _entry["broker_type"],
                                _entry["broker"],
                                _new_sf,
                            ),
                            name=f"Trader-{_bname}",
                            daemon=True,
                        )
                        _new_t.start()
                    else:
                        _hf_secs = (
                            _hf_bot.get_cycle_interval()
                            if _hf_bot is not None
                            else 150
                        )
                        _new_t, _new_sf = _start_single_broker_thread(strategy, _hf_secs)
                    _entry["thread"] = _new_t
                    _entry["stop_flag"] = _new_sf
                    logger.info(
                        "   ✅ [Orchestrator] Restarted trader for '%s'",
                        _bname.upper(),
                    )

            if _orch_cycle % 18 == 0:
                _alive = sum(
                    1 for _e in _active_threads.values() if _e["thread"].is_alive()
                )
                logger.info(
                    "💓 [Orchestrator] %d/%d threads alive (supervisor cycle %d)",
                    _alive,
                    len(_active_threads),
                    _orch_cycle,
                )
                if use_independent_trading and strategy.independent_trader:
                    strategy.log_multi_broker_status()

            time.sleep(10)

        except KeyboardInterrupt:
            for _entry in _active_threads.values():
                _entry["stop_flag"].set()
            for _entry in _active_threads.values():
                _entry["thread"].join(timeout=5)
            raise
        except Exception as _orch_err:
            logger.error(
                "❌ [Orchestrator] Supervisor loop error: %s — continuing",
                _orch_err,
                exc_info=True,
            )
            time.sleep(10)


def _run_bot_startup_and_trading_with_retry():
    """
    Bootstrap kernel entry point — retries on transient failures.

    Enforces the single-owner invariant: only one instance of this function
    may be executing at any time.  A concurrent call (e.g. a stale code path
    spawning a second BotStartup thread) is rejected immediately so it can
    never race through shared initialisation state.

    Claims FSM bootstrap ownership so that any other thread attempting to
    drive the FSM forward will produce an observable warning log.

    Retries indefinitely with exponential backoff (capped at 60 s) so that
    transient errors (Kraken nonce, network blip, etc.) never kill the thread
    permanently.  Only a clean KeyboardInterrupt stops the loop.
    """
    # ── Single-owner bootstrap kernel ────────────────────────────────────────
    if not _BOOTSTRAP_SINGLE_OWNER_LOCK.acquire(blocking=False):
        logger.error(
            "[Bootstrap] Concurrent bootstrap execution detected — "
            "another bootstrap kernel sequence is already running on this process. "
            "This indicates a bug: BotStartup should never be spawned twice. "
            "Rejecting this call."
        )
        return
    try:
        # Claim FSM ownership: from this point forward, only this thread should
        # drive the bootstrap FSM forward.  Non-owner transitions will be
        # logged as warnings so races are immediately visible.
        if _BOOTSTRAP_FSM_AVAILABLE:
            _get_bootstrap_fsm().claim_bootstrap_ownership()

        import time

        _INITIAL_DELAY_SECONDS = 5
        _BACKOFF_MULTIPLIER = 2
        _MAX_BACKOFF_EXPONENT = 6   # caps delay at 5 * 2^6 = 320 → clamped to _MAX_DELAY
        _MAX_DELAY = 60             # seconds — keeps retries responsive
        _MAX_CONNECTION_ATTEMPTS = 3  # FIX 4: anti-loop kill switch

        attempt = 0
        connection_attempts = 0

        while True:
            try:
                # Attempt to start the bot
                _run_bot_startup_and_trading()
                # Normal exit — supervisor loop inside returned cleanly
                return

            except KeyboardInterrupt:
                # Clean shutdown — do not retry
                logger.info("Received KeyboardInterrupt — stopping startup thread")
                raise

            except Exception as e:
                if _is_fatal_nonce_restart_error(e):
                    logger.critical(
                        "🚨 Fatal nonce authorization/desync error detected: %s",
                        e,
                        exc_info=True,
                    )
                    logger.critical(
                        "🚨 Requesting clean process exit so external watchdog can restart service"
                    )
                    # Bootstrap FSM: fatal nonce → EXTERNAL_RESTART_REQUIRED (I9)
                    _bfsm_transition(
                        _BootstrapState.EXTERNAL_RESTART_REQUIRED,
                        f"fatal nonce error: {e}",
                    )
                    _request_external_watchdog_restart(str(e))
                    raise
                attempt += 1
                connection_attempts += 1  # FIX 4: track connection attempts

                # FIX 4: anti-loop kill switch — abort if connection keeps looping
                if connection_attempts > _MAX_CONNECTION_ATTEMPTS:
                    logger.critical(
                        "🚨 CONNECTION LOOP DETECTED — FORCING EXIT after %d attempts",
                        connection_attempts,
                    )
                    break

                # Bootstrap FSM: transient failure → BOOT_FAILED_RETRY so the next
                # attempt can enter PLATFORM_CONNECTING cleanly.  Skip reset when
                # full init already completed (fast-path supervisor restart scenario).
                if _BOOTSTRAP_FSM_AVAILABLE:
                    print("INIT_LOCK_ATTEMPT", flush=True)
                    _acquired = _initialized_state_lock.acquire(timeout=5)
                    if not _acquired:
                        raise RuntimeError("DEADLOCK: _initialized_state_lock not acquired")
                    try:
                        print("INIT_LOCK_ACQUIRED", flush=True)
                        _init_done = (
                            _initialized_state.get("strategy") is not None
                            and "active_threads" in _initialized_state
                        )
                    finally:
                        _initialized_state_lock.release()
                    if not _init_done:
                        _get_bootstrap_fsm().reset_for_retry(
                            f"attempt #{attempt} failed: {e}"
                        )

                delay = min(
                    _MAX_DELAY,
                    _INITIAL_DELAY_SECONDS * (_BACKOFF_MULTIPLIER ** min(attempt - 1, _MAX_BACKOFF_EXPONENT)),
                )
                logger.error(
                    "💥 [Startup] Attempt #%d failed: %s — retrying in %ds",
                    attempt, e, delay, exc_info=True,
                )
                time.sleep(delay)

    finally:
        _BOOTSTRAP_SINGLE_OWNER_LOCK.release()


def _run_bot_startup_and_trading():
    """
    Background thread: Initialize bot and run trading loops.
    
    This function runs in a background thread while the main thread
    keeps the health server responsive to Railway.
    
    Contains:
    - Kraken connection
    - User loading  
    - Balance fetching
    - Trading loop initialization

    On a retry after the supervisor loop crashes, the module-level
    ``_initialized_state`` singleton is used to skip re-initialisation and
    jump straight to ``_rerun_supervisor_loop()``.
    """
    global _initialized_state

    # ── FAST PATH: init already done — skip straight to supervisor loop ────
    # Requires full state (strategy + active_threads) to be present so that a
    # retry after a partial-init failure falls through and finishes setup instead
    # of calling _rerun_supervisor_loop with an incomplete state dict.
    print("INIT_LOCK_ATTEMPT", flush=True)
    _acquired = _initialized_state_lock.acquire(timeout=5)
    if not _acquired:
        raise RuntimeError("DEADLOCK: _initialized_state_lock not acquired")
    try:
        print("INIT_LOCK_ACQUIRED", flush=True)
        _state_copy = dict(_initialized_state)
    finally:
        _initialized_state_lock.release()
    if _state_copy.get("strategy") is not None and "active_threads" in _state_copy:
        logger.critical("⚠️ BYPASSING INIT — FORCING RUN LOOP")
        logger.info(
            "♻️  Startup already completed — skipping re-init, "
            "re-entering supervisor loop"
        )
        _rerun_supervisor_loop(_state_copy)
        return

    # TEMPORARY OPERATIONAL HOTFIX:
    # Disable Coinbase completely so startup/trading depends only on Kraken readiness.
    # TODO: Remove this forced disable once Kraken-only validation phase is complete.
    if not _is_truthy_env("NIJA_DISABLE_COINBASE", "false"):
        os.environ["NIJA_DISABLE_COINBASE"] = "true"
        logger.warning("⛔ TEMPORARY MODE: Coinbase disabled (NIJA_DISABLE_COINBASE=true)")

    # ── Bootstrap FSM: acknowledge ENV_VERIFIED on first run ─────────────────
    # Environment variables were verified at module import; health server was
    # bound in main().  Advance the FSM to ENV_VERIFIED so the startup thread
    # can drive subsequent transitions.  On retry the FSM is already in
    # BOOT_FAILED_RETRY (set by the retry wrapper) — skip early-state transitions.
    if _BOOTSTRAP_FSM_AVAILABLE:
        _current_boot_state = _get_bootstrap_fsm().state
        if _current_boot_state == _BootstrapState.HEALTH_BOUND:
            _bfsm_transition(
                _BootstrapState.ENV_VERIFIED,
                "startup thread active; environment verified at module load",
            )

    # ── FIX 3: CONNECTION PHASE GUARD — can only run once ───────────────────
    # If a previous attempt completed the connection/credential-check phase,
    # skip it entirely on retry so we never loop back through broker init.
    print("INIT_LOCK_ATTEMPT", flush=True)
    _acquired = _initialized_state_lock.acquire(timeout=5)
    if not _acquired:
        raise RuntimeError("DEADLOCK: _initialized_state_lock not acquired")
    try:
        print("INIT_LOCK_ACQUIRED", flush=True)
        _connection_already_complete = _initialized_state.get("connection_complete", False)
    finally:
        _initialized_state_lock.release()
    _resolved_kraken_key, _resolved_kraken_secret = _resolve_kraken_startup_credentials()
    _kraken_credentials_valid = bool(_resolved_kraken_key and _resolved_kraken_secret)
    _coinbase_sdk_available = _coinbase_sdk_is_available()
    try:
        # Import here to ensure logging is set up
        from bot.health_check import get_health_manager
        health_manager = get_health_manager()

        # FIX 3: Hard guard — connection/credential phase runs at most once.
        # If a previous attempt already completed this phase, skip it entirely.
        if _connection_already_complete:
            logger.info("♻️  Connection phase already complete — skipping credential checks")
            # Restore the credential flags stored during the first run so that
            # later sections (broker connection diagnostics at ~line 1226) still work.
            print("INIT_LOCK_ATTEMPT", flush=True)
            _acquired = _initialized_state_lock.acquire(timeout=5)
            if not _acquired:
                raise RuntimeError("DEADLOCK: _initialized_state_lock not acquired")
            try:
                print("INIT_LOCK_ACQUIRED", flush=True)
                _cred_snap = dict(_initialized_state)
            finally:
                _initialized_state_lock.release()
            kraken_platform_configured = _cred_snap.get("kraken_platform_configured", False)
            coinbase_configured = _cred_snap.get("coinbase_configured", False)
            exchanges_configured = _cred_snap.get("exchanges_configured", 0)
            _kraken_credentials_valid = _cred_snap.get("kraken_credentials_valid", False)
            _coinbase_sdk_available = _cred_snap.get("coinbase_sdk_available", _coinbase_sdk_available)
        else:
            logger.info("=" * 70)
            logger.info("🧵 STARTUP THREAD: Beginning bot initialization")
            logger.info("=" * 70)
            logger.info("While this thread initializes, health server remains responsive")
            logger.info("")
            
            # Get git metadata - try env vars first, then git commands
            git_branch = os.getenv("GIT_BRANCH", "")
            git_commit = os.getenv("GIT_COMMIT", "")

            # Fallback to git commands if env vars not set
            if not git_branch:
                try:
                    git_branch = subprocess.check_output(
                        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                        cwd=os.path.dirname(__file__),
                        stderr=subprocess.DEVNULL,
                        timeout=5
                    ).decode().strip()
                except Exception:
                    git_branch = "unknown"

            if not git_commit:
                try:
                    git_commit = subprocess.check_output(
                        ["git", "rev-parse", "--short", "HEAD"],
                        cwd=os.path.dirname(__file__),
                        stderr=subprocess.DEVNULL,
                        timeout=5
                    ).decode().strip()
                except Exception:
                    git_commit = "unknown"

            logger.info("=" * 70)
            logger.info("NIJA TRADING BOT - APEX v7.2.0")
            logger.info("NIJA TRADING BOT - APEX v7.2")
            logger.info("🏷 Version: 7.2.0 — Independent Trading Only")
            logger.info("Branch:          %s", git_branch)
            logger.info("Commit:          %s", git_commit)

            # Build timestamp: prefer env var injected by CI/Docker, else record startup time
            build_timestamp = os.getenv("BUILD_TIMESTAMP") or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            logger.info("Build timestamp: %s", build_timestamp)

            # Risk mode: derive human-readable label from RISK_PROFILE env var
            _risk_profile = os.getenv("RISK_PROFILE", "AUTO").upper()
            _risk_label_map = {
                "STARTER":  "small-account / STARTER ($50–$99)",
                "SAVER":    "small-account / SAVER ($100–$249)",
                "INVESTOR": "INVESTOR ($250–$999)",
                "INCOME":   "1K mode / INCOME ($1k–$4.9k)",
                "LIVABLE":  "LIVABLE ($5k–$24.9k)",
                "BALLER":   "BALLER ($25k+)",
                "AUTO":     "AUTO (balance-based tier selection)",
            }
            risk_mode_label = _risk_label_map.get(_risk_profile, _risk_profile)
            logger.info("Risk mode:       %s", risk_mode_label)

            # Max positions and allocation % from env vars
            try:
                _max_positions = int(os.getenv("MAX_CONCURRENT_POSITIONS", "5"))
            except ValueError:
                _max_positions = 5
            # MAX_TRADE_PERCENT is a decimal fraction (e.g., 0.10 = 10%)
            _alloc_pct = float(os.getenv("MAX_TRADE_PERCENT", "0.10")) * 100
            logger.info("Max positions:   %d", _max_positions)
            logger.info(f"Allocation %:    {_alloc_pct:.0f}%")

            logger.info("=" * 70)
            logger.info(f"Python version: {sys.version.split()[0]}")
            logger.info(f"Log file: {LOG_FILE}")
            logger.info(f"Working directory: {os.getcwd()}")
            if _startup_buffer:
                _startup_buffer.flush_phase("INIT")

            # ═══════════════════════════════════════════════════════════════════════
            # CRITICAL: Startup Validation (addresses subtle risks)
            # ═══════════════════════════════════════════════════════════════════════
            # Validates:
            # 1. Git metadata (branch/commit must be known)
            # 2. Exchange configuration (warns about disabled exchanges)
            # 3. Trading mode (testing vs. live must be explicit)
            _validation_critical_failure = False
            _validation_failure_reason = ""
            try:
                from bot.startup_validation import run_all_validations, display_validation_results
                validation_result = run_all_validations(git_branch, git_commit)
                display_validation_results(validation_result)
                if validation_result.critical_failure:
                    _validation_critical_failure = True
                    _validation_failure_reason = validation_result.failure_reason
            except Exception as e:
                logger.error(f"⚠️  Startup validation failed to run: {e}", exc_info=True)
                logger.warning("   Continuing startup without validation (NOT RECOMMENDED)")

            # Raise OUTSIDE the try/except so the retry wrapper catches it, not this handler
            if _validation_critical_failure:
                logger.error("=" * 70)
                logger.error("❌ STARTUP VALIDATION FAILED - will retry")
                logger.error("=" * 70)
                health_manager.mark_configuration_error(_validation_failure_reason)
                _log_exit_point("Startup validation failed", exit_code=1)
                raise RuntimeError(f"Critical startup validation failure (will retry): {_validation_failure_reason}")

            # Validation passed — advance bootstrap FSM.
            # Retry path must move BOOT_FAILED_RETRY -> PLATFORM_CONNECTING.
            if _BOOTSTRAP_FSM_AVAILABLE and _get_bootstrap_fsm().state == _BootstrapState.BOOT_FAILED_RETRY:
                _bfsm_transition(
                    _BootstrapState.PLATFORM_CONNECTING,
                    "startup_validation passed during retry; re-enter platform connecting",
                )
            else:
                _bfsm_transition(
                    _BootstrapState.STARTUP_VALIDATED,
                    "startup_validation passed all pre-flight checks",
                )

            # Display financial disclaimers (App Store compliance)
            try:
                from bot.financial_disclaimers import display_startup_disclaimers, log_compliance_notice
                display_startup_disclaimers()
                log_compliance_notice()
            except ImportError:
                # Fallback if disclaimers module not available
                logger.warning("=" * 70)
                logger.warning("⚠️  RISK WARNING: Trading involves substantial risk of loss")
                logger.warning("   Only trade with money you can afford to lose")
                logger.warning("=" * 70)
            
            # Display feature flag banner
            try:
                from bot.startup_diagnostics import display_feature_flag_banner
                display_feature_flag_banner()
            except Exception as e:
                logger.warning(f"⚠️  Could not display feature flag banner: {e}")
            
            # Verify trading capability
            try:
                from bot.startup_diagnostics import verify_trading_capability
                capability_ok, issues = verify_trading_capability()
                if not capability_ok:
                    logger.warning("⚠️  Trading capability verification found issues")
                    logger.warning("   Bot may not function correctly")
            except Exception as e:
                logger.warning(f"⚠️  Could not verify trading capability: {e}")

            # ── B: Phase 0 → 1 (ENV_VALIDATION complete; broker registry may begin) ─
            _advance_phase(_Phase.BROKER_REGISTRY, reason="startup validation and feature-flag checks passed")
            if _startup_buffer:
                _startup_buffer.flush_phase("ENV_VALIDATION")

            # ═══════════════════════════════════════════════════════════════════════
            # CREDENTIAL VALIDATION — run before any broker connection attempt
            # ═══════════════════════════════════════════════════════════════════════
            # Validates that all configured broker credentials are present, non-empty,
            # and structurally correct.  Logs actionable errors for any issues found
            # so operators can fix them before the bot wastes time on failed connections.
            # ═══════════════════════════════════════════════════════════════════════
            logger.info("=" * 70)
            logger.info("🔐 CREDENTIAL VALIDATION")
            logger.info("=" * 70)
            
            # Check if credentials validator exists
            import importlib.util as _iutil
            _cv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "validate_broker_credentials.py")
            _live_capital_verified = os.getenv('LIVE_CAPITAL_VERIFIED', 'false').lower() in ('true', '1', 'yes')
            
            if not os.path.isfile(_cv_path):
                if _live_capital_verified:
                    # HARD FAIL: Do not allow live capital mode without credential validation
                    logger.critical("=" * 70)
                    logger.critical("❌ FATAL: CREDENTIAL VALIDATION DISABLED IN LIVE CAPITAL MODE")
                    logger.critical("=" * 70)
                    logger.critical("LIVE_CAPITAL_VERIFIED=true but validate_broker_credentials.py is MISSING")
                    logger.critical("")
                    logger.critical("This is a critical safety violation. Silent credential skipping in")
                    logger.critical("live capital mode is how systems enter false-ready states.")
                    logger.critical("")
                    logger.critical("Action required:")
                    logger.critical("  1. Restore validate_broker_credentials.py to bot/ directory")
                    logger.critical("  2. OR set LIVE_CAPITAL_VERIFIED=false to disable live trading")
                    logger.critical("  3. Re-run bot startup")
                    logger.critical("=" * 70)
                    sys.exit(1)
                else:
                    logger.info("ℹ️  validate_broker_credentials.py not found — skipping external validation")
            
            try:
                if os.path.isfile(_cv_path):
                    _cv_spec = _iutil.spec_from_file_location(
                        "validate_broker_credentials",
                        _cv_path,
                    )
                    if _cv_spec and _cv_spec.loader:
                        _cv_mod = _iutil.module_from_spec(_cv_spec)
                        _cv_spec.loader.exec_module(_cv_mod)

                        _cv_results = [v() for v in [
                            _cv_mod._validate_kraken_platform,
                            _cv_mod._validate_coinbase,
                            _cv_mod._validate_alpaca,
                            _cv_mod._validate_binance,
                            _cv_mod._validate_okx,
                        ]]

                        _cv_configured = sum(1 for r in _cv_results if r["configured"])
                        _cv_errors     = sum(1 for r in _cv_results if r["configured"] and not r["valid"])
                        _cv_by_broker = {r.get("broker", "").lower(): r for r in _cv_results}
                        _kraken_credentials_valid = _kraken_credentials_valid and bool(
                            (_cv_by_broker.get("kraken (platform)") or {}).get("valid", False)
                        )

                        for _r in _cv_results:
                            if not _r["configured"]:
                                logger.info("   ⚪ %-22s not configured (skipped)", _r["broker"])
                                continue
                            if _r["valid"]:
                                logger.info("   ✅ %-22s credentials look valid", _r["broker"])
                            else:
                                logger.error("   ❌ %-22s CREDENTIAL ERRORS:", _r["broker"])
                                for _issue in _r["issues"]:
                                    logger.error("      → %s", _issue)
                            for _warn in _r.get("warnings", []):
                                logger.warning("      ⚠️  %s", _warn)

                        if _cv_configured == 0:
                            logger.error("=" * 70)
                            logger.error("❌ CREDENTIAL VALIDATION: No broker credentials configured")
                            logger.error("   The bot cannot trade without at least one broker.")
                            logger.error("   See CREDENTIAL_SETUP.md for step-by-step instructions.")
                            logger.error("=" * 70)
                        elif _cv_errors > 0:
                            logger.warning("=" * 70)
                            logger.warning(
                                "⚠️  CREDENTIAL VALIDATION: %d broker(s) have credential errors",
                                _cv_errors,
                            )
                            logger.warning("   These brokers will likely fail to connect.")
                            logger.warning("   Common fixes:")
                            logger.warning("     • Kraken 'EAPI:Invalid nonce'  → run reset_kraken_nonce.py")
                            logger.warning("     • Coinbase 401 Unauthorized    → check PEM newlines in secret")
                            logger.warning("     • Missing credentials          → see CREDENTIAL_SETUP.md")
                            logger.warning("=" * 70)
                        else:
                            logger.info("✅ CREDENTIAL VALIDATION: All configured brokers passed")
            except Exception as _cv_err:
                logger.warning("⚠️  Credential validation error (non-fatal): %s", _cv_err)

            if _startup_buffer:
                _startup_buffer.flush_phase("CREDENTIALS")

            _startup_blockers = []
            _resolved_kraken_key, _resolved_kraken_secret = _resolve_kraken_startup_credentials()
            if not _resolved_kraken_key or not _resolved_kraken_secret:
                _startup_blockers.append(
                    "Missing Kraken credentials (all sources exhausted): "
                    "set one valid key/secret pair from "
                    "KRAKEN_PLATFORM_API_KEY/KRAKEN_PLATFORM_API_SECRET, "
                    "KRAKEN_USER_TANIA_GILBERT_API_KEY/KRAKEN_USER_TANIA_GILBERT_API_SECRET, "
                    "or KRAKEN_API_KEY/KRAKEN_API_SECRET."
                )

            import importlib.util as _iutil
            _kraken_sdk_missing = (
                _iutil.find_spec("krakenex") is None or _iutil.find_spec("pykrakenapi") is None
            )
            if _kraken_credentials_valid and _kraken_sdk_missing:
                _startup_blockers.append(
                    "Missing modules: Kraken SDK not installed (requires krakenex + pykrakenapi)."
                )

            _coinbase_disabled = _is_truthy_env("NIJA_DISABLE_COINBASE", "false")
            if not _coinbase_disabled and not _coinbase_sdk_available:
                _startup_blockers.append(
                    "Missing modules: Coinbase SDK not installed while Coinbase is enabled "
                    "(install coinbase-advanced-py or set NIJA_DISABLE_COINBASE=true)."
                )

            if _startup_blockers:
                raise RuntimeError("Hard startup blockers detected: " + " | ".join(_startup_blockers))

            # ═══════════════════════════════════════════════════════════════════════
            # KRAKEN PRE-CONNECTION NONCE RESET
            # ═══════════════════════════════════════════════════════════════════════
            # Jump the global Kraken nonce forward before any connection attempt.
            # This clears any "burned" nonce window left by a previous session and
            # prevents "EAPI:Invalid nonce" errors on the very first API call.
            # ═══════════════════════════════════════════════════════════════════════
            _kraken_creds_present = bool(
                (os.getenv("KRAKEN_PLATFORM_API_KEY") or os.getenv("KRAKEN_API_KEY"))
                and (os.getenv("KRAKEN_PLATFORM_API_SECRET") or os.getenv("KRAKEN_API_SECRET"))
            )
            if _kraken_creds_present:
                logger.info("=" * 70)
                logger.info("⚡ KRAKEN PRE-CONNECTION NONCE RESET")
                logger.info("=" * 70)
                try:
                    from bot.global_kraken_nonce import (
                        get_global_nonce_manager,
                        jump_global_kraken_nonce_forward,
                    )

                    # ── Sentinel A0.1: entering nonce-manager init ──────────────
                    logger.critical("A0.1 before nonce manager")

                    from concurrent.futures import ThreadPoolExecutor, TimeoutError as _FuturesTimeoutError

                    with ThreadPoolExecutor(max_workers=1) as _ex:
                        _future = _ex.submit(get_global_nonce_manager)
                        try:
                            _nonce_mgr = _future.result(timeout=10)
                        except _FuturesTimeoutError:
                            raise RuntimeError("Nonce init hung (>10s)")

                    # ── Sentinel A0.2: nonce manager obtained ───────────────────
                    logger.critical("A0.2 after nonce manager")

                    # Jump 60 seconds forward (in milliseconds) to skip any nonces
                    # Kraken may still have cached from the previous session.
                    _jump_ms  = 60 * 1000  # 60 seconds in milliseconds
                    _new_nonce = jump_global_kraken_nonce_forward(_jump_ms)

                    # ── Sentinel A0.3 / B5: nonce reset complete ────────────────
                    logger.critical("B5 after nonce lock / nonce-jump complete")

                    logger.info(
                        "   ✅ Global Kraken nonce jumped +60 s → %s (prevents stale-nonce errors)",
                        _new_nonce,
                    )
                except ImportError:
                    logger.warning("   ⚠️  global_kraken_nonce module not available — skipping pre-reset")
                except Exception as _nonce_err:
                    logger.warning("   ⚠️  Nonce pre-reset failed (non-fatal): %s", _nonce_err)

            # Portfolio override visibility at startup
            portfolio_id = os.environ.get("COINBASE_RETAIL_PORTFOLIO_ID")
            if portfolio_id:
                logger.info("🔧 Portfolio override in use: %s", portfolio_id)
            else:
                logger.info("🔧 Portfolio override in use: <none>")

            # Pre-flight check: Verify at least one exchange is configured
            logger.info("=" * 70)
            logger.info("🔍 PRE-FLIGHT: Checking Exchange Credentials")
            logger.info("=" * 70)

            exchanges_configured = 0
            exchange_status = []

            # Check Coinbase
            coinbase_configured = bool(
                os.getenv("COINBASE_API_KEY") and os.getenv("COINBASE_API_SECRET")
            )
            if coinbase_configured:
                exchanges_configured += 1
                exchange_status.append("✅ Coinbase")
            else:
                exchange_status.append("❌ Coinbase")

            # Check Kraken Platform
            # Prefer platform keys; legacy KRAKEN_API_* pair remains supported for backward compatibility.
            kraken_platform_configured = bool(
                (os.getenv("KRAKEN_PLATFORM_API_KEY") or os.getenv("KRAKEN_API_KEY"))
                and (os.getenv("KRAKEN_PLATFORM_API_SECRET") or os.getenv("KRAKEN_API_SECRET"))
            )
            if kraken_platform_configured:
                exchanges_configured += 1
                exchange_status.append("✅ Kraken (Platform)")
            else:
                exchange_status.append("❌ Kraken (Platform)")

            # Check OKX
            if os.getenv("OKX_API_KEY") and os.getenv("OKX_API_SECRET") and os.getenv("OKX_PASSPHRASE"):
                exchanges_configured += 1
                exchange_status.append("✅ OKX")
            else:
                exchange_status.append("❌ OKX")

            # Check Binance
            if os.getenv("BINANCE_API_KEY") and os.getenv("BINANCE_API_SECRET"):
                exchanges_configured += 1
                exchange_status.append("✅ Binance")
            else:
                exchange_status.append("❌ Binance")

            # Check Alpaca Platform
            if os.getenv("ALPACA_API_KEY") and os.getenv("ALPACA_API_SECRET"):
                exchanges_configured += 1
                exchange_status.append("✅ Alpaca (Platform)")
            else:
                exchange_status.append("❌ Alpaca (Platform)")

            # D: single structured snapshot instead of N per-exchange log lines
            try:
                from bot.startup_event_buffer import StartupSnapshot as _ExSnap
                _ex_snap = _ExSnap("Exchange Credentials")
                _ex_snap.record("coinbase", coinbase_configured)
                _ex_snap.record("kraken_platform", kraken_platform_configured)
                _ex_snap.record("okx", bool(os.getenv("OKX_API_KEY") and os.getenv("OKX_API_SECRET")))
                _ex_snap.record("binance", bool(os.getenv("BINANCE_API_KEY") and os.getenv("BINANCE_API_SECRET")))
                _ex_snap.record("alpaca", bool(os.getenv("ALPACA_API_KEY") and os.getenv("ALPACA_API_SECRET")))
                _ex_snap.emit(logger)
            except ImportError:
                for status in exchange_status:
                    logger.info(f"   {status}")
            if exchanges_configured == 0:
                logger.warning("⚠️  No exchange credentials configured")
            logger.info("Total exchanges configured: %d", exchanges_configured)
            logger.info("=" * 70)

            if exchanges_configured == 0:
                logger.error("=" * 70)
                logger.error("❌ FATAL: NO EXCHANGE CREDENTIALS CONFIGURED")
                logger.error("=" * 70)
                logger.error("")
                logger.error("At least one exchange must be configured to run the bot.")
                logger.error("Configure credentials for at least ONE of:")
                logger.error("  • Coinbase")
                logger.error("  • Kraken")
                logger.error("  • OKX")
                logger.error("  • Binance")
                logger.error("  • Alpaca")
                logger.error("")
                logger.error("How to configure:")
                logger.error("1. Edit .env file and add your credentials")
                logger.error("2. Or set environment variables in your deployment platform:")
                logger.error("")
                logger.error("Railway: Settings → Variables → Add")
                logger.error("Render:  Dashboard → Service → 'Manual Deploy' → 'Deploy latest commit'")
                logger.error("")
                logger.error("For detailed help, see:")
                logger.error("  • SOLUTION_ENABLE_EXCHANGES.md")
                logger.error("  • RESTART_DEPLOYMENT.md")
                logger.error("  • Run: python3 diagnose_env_vars.py")
                logger.error("=" * 70)
                logger.error("Exiting - No trading possible without credentials")
                
                # Mark as configuration error for health checks
                health_manager.mark_configuration_error("No exchange credentials configured")

                # Bootstrap FSM: no credentials → CONFIG_ERROR_KEEPALIVE terminal state
                _bfsm_transition(
                    _BootstrapState.CONFIG_ERROR_KEEPALIVE,
                    "no exchange credentials configured",
                )

                # Health server already started at beginning of main()
                logger.info("Health server already running - will report configuration error status")
                
                _log_lifecycle_banner(
                    "⚠️  ENTERING CONFIG ERROR KEEP-ALIVE MODE",
                    [
                        "No exchange credentials configured - cannot trade",
                        "Process will stay alive for health monitoring",
                        "Container will NOT restart automatically",
                        f"Heartbeat interval: {CONFIG_ERROR_HEARTBEAT_INTERVAL}s",
                        "Configure credentials and manually restart deployment",
                        *_get_thread_status()
                    ]
                )
                
                try:
                    loop_count = 0
                    while True:
                        time.sleep(CONFIG_ERROR_HEARTBEAT_INTERVAL)
                        health_manager.heartbeat()
                        loop_count += 1
                        
                        # Log status every 10 iterations (10 minutes at 60s interval)
                        if loop_count % 10 == 0:
                            logger.info(f"⏱️  Config error keep-alive: {loop_count * CONFIG_ERROR_HEARTBEAT_INTERVAL}s elapsed")
                except KeyboardInterrupt:
                    _log_exit_point(
                        "Configuration error keep-alive interrupted",
                        exit_code=0,
                        details=[
                            "KeyboardInterrupt in config error keep-alive loop",
                            "No exchange credentials were configured",
                            *_get_thread_status()
                        ]
                    )
                    sys.exit(0)
            elif exchanges_configured < 2:
                # Can be suppressed by setting SUPPRESS_SINGLE_EXCHANGE_WARNING=true
                suppress_warning = os.getenv("SUPPRESS_SINGLE_EXCHANGE_WARNING", "false").lower() in ("true", "1", "yes")
                if not suppress_warning:
                    logger.warning("=" * 70)
                    logger.warning("⚠️  SINGLE EXCHANGE TRADING")
                    logger.warning("=" * 70)
                    logger.warning(f"Only {exchanges_configured} exchange configured. Consider enabling more for:")
                    logger.warning("  • Better diversification")
                    logger.warning("  • Reduced API rate limiting")
                    logger.warning("  • More resilient trading")
                    logger.warning("")
                    logger.warning("See MULTI_EXCHANGE_TRADING_GUIDE.md for setup instructions")
                    logger.warning("To suppress this warning, set SUPPRESS_SINGLE_EXCHANGE_WARNING=true")
                    logger.warning("=" * 70)
                logger.warning(f"⚠️  Single exchange trading ({exchanges_configured} exchange configured). Consider enabling more exchanges for better diversification and resilience.")
                logger.info("📖 See MULTI_EXCHANGE_TRADING_GUIDE.md for setup instructions")

            # Save credential flags so retries can restore them without re-running checks
            print("INIT_LOCK_ATTEMPT", flush=True)
            _acquired = _initialized_state_lock.acquire(timeout=5)
            if not _acquired:
                raise RuntimeError("DEADLOCK: _initialized_state_lock not acquired")
            try:
                print("INIT_LOCK_ACQUIRED", flush=True)
                _initialized_state["connection_complete"] = True
                _initialized_state["kraken_platform_configured"] = kraken_platform_configured
                _initialized_state["coinbase_configured"] = coinbase_configured
                _initialized_state["exchanges_configured"] = exchanges_configured
                _initialized_state["kraken_credentials_valid"] = _kraken_credentials_valid
                _initialized_state["coinbase_sdk_available"] = _coinbase_sdk_available
            finally:
                _initialized_state_lock.release()

            logger.critical("✅ CONNECTION PHASE COMPLETE — MOVING TO INIT")
            logger.critical("🔥 SENTINEL A: entered INIT section")
            print("INIT_A1 RAW STDERR", flush=True)
            if _startup_buffer:
                _startup_buffer.flush_phase("PREFLIGHT")

        # ═══════════════════════════════════════════════════════════════════════
        # BOT INITIALIZATION - This is where Kraken connection happens
        # ═══════════════════════════════════════════════════════════════════════
        
        logger.critical("B2 entered preflight_continue (BOT INIT SECTION)")

        try:
            logger.info("🧵 STARTUP THREAD: Initializing trading strategy...")
            logger.info("   This is where Kraken connection will be established")
            logger.info("   Main thread health server remains responsive during this")
            logger.info("PORT env: %s", os.getenv("PORT") or "<unset>")

            print("RAW1 after SENTINEL A", flush=True)
            # ── Bootstrap FSM invariant guards + MODE_GATED + PLATFORM_CONNECTING ─
            print("RAW2 before bootstrap fsm", flush=True)
            if _BOOTSTRAP_FSM_AVAILABLE:
                _boot_fsm = _get_bootstrap_fsm()
                # I1: process lock must be held
                try:
                    _boot_fsm.assert_invariant_i1_single_writer()
                except Exception as _inv_err:
                    logger.warning("⚠️  Bootstrap invariant I1 violation: %s", _inv_err)
                # I2: health server must be bound before blocking I/O
                try:
                    _boot_fsm.assert_invariant_i2_liveness_first()
                except Exception as _inv_err:
                    logger.warning("⚠️  Bootstrap invariant I2 violation: %s", _inv_err)
                # Advance FSM: STARTUP_VALIDATED → MODE_GATED → PLATFORM_CONNECTING
                # On retry the FSM is already in BOOT_FAILED_RETRY; skip MODE_GATED.
                _cur = _boot_fsm.state
                if _cur == _BootstrapState.STARTUP_VALIDATED:
                    _bfsm_transition(
                        _BootstrapState.MODE_GATED,
                        "trading state machine mode confirmed",
                    )
                _bfsm_transition(
                    _BootstrapState.PLATFORM_CONNECTING,
                    "TradingStrategy broker connection starting",
                )

            logger.critical("🔥 INIT_A2: after Bootstrap FSM, before _initialized_state_lock")
            # STEP 2 — initialize strategy ONCE.
            # If a previous attempt created TradingStrategy but crashed before
            # the full state (including active_threads) was stored, reuse the
            # existing instance rather than reconnecting all brokers again.
            # TradingStrategy holds broker connections but does not retain
            # partially-executed trades or corrupt state on init failure, so
            # reusing it is safe — thread setup simply picks up where it left off.
            print("RAW3 before init lock", flush=True)
            print("INIT_LOCK_ATTEMPT", flush=True)
            _acquired = _initialized_state_lock.acquire(timeout=5)
            if not _acquired:
                raise RuntimeError("DEADLOCK: _initialized_state_lock not acquired")
            try:
                print("INIT_LOCK_ACQUIRED", flush=True)
                _existing_strategy = _initialized_state.get("strategy")
            finally:
                _initialized_state_lock.release()
            logger.critical("🔥 INIT_A3: after _initialized_state_lock, before phase gate")
            if _existing_strategy is not None:
                logger.info("♻️  Reusing existing TradingStrategy instance from previous attempt")
                strategy = _existing_strategy
            else:
                # ── B: enforce ordering — env must be validated before broker init ──
                # Non-blocking observable check: warn and continue with degraded
                # readiness rather than hard-raising.  The phase may not have
                # propagated yet when a retry reuses the same singleton, or when
                # the advance() fired before this listener was attached.
                if _PHASE_GATE_AVAILABLE:
                    from bot.startup_phase_gate import get_phase_gate as _get_pg, Phase as _PhaseCheck
                    if not _get_pg().is_at_least(_PhaseCheck.BROKER_REGISTRY):
                        logger.warning(
                            "[PhaseGate] BROKER_REGISTRY phase not reached yet — "
                            "continuing with degraded readiness"
                        )
                # ── C: guard against duplicate TradingStrategy creation ─────────────
                if not _check_init_once("trading_strategy"):
                    raise RuntimeError(
                        "init_once_guard: TradingStrategy creation attempted more than once — "
                        "likely a retry-loop bug."
                    )
                logger.critical("🔥 INIT_A4: before TradingStrategy()")
                logger.critical("🚀 CREATING TradingStrategy INSTANCE")
                logger.critical("B2 before TradingStrategy()")
                strategy = TradingStrategy()
                logger.critical("B3 after TradingStrategy()")
                if strategy is None:
                    raise RuntimeError(
                        "FATAL: TradingStrategy() returned None — "
                        "strategy failed to initialize.  Check broker credentials "
                        "and apex strategy import."
                    )
                print("INIT_LOCK_ATTEMPT", flush=True)
                _acquired = _initialized_state_lock.acquire(timeout=5)
                if not _acquired:
                    raise RuntimeError("DEADLOCK: _initialized_state_lock not acquired")
                try:
                    print("INIT_LOCK_ACQUIRED", flush=True)
                    _initialized_state["strategy"] = strategy
                finally:
                    _initialized_state_lock.release()
                logger.critical("🔥 INIT_A5: after TradingStrategy()")
                logger.critical("🧠 STATE STORED — entering supervisor mode")
                logger.critical("B3 after connect_brokers (TradingStrategy created)")

            # Bootstrap FSM: broker(s) connected → PLATFORM_READY
            _bfsm_transition(
                _BootstrapState.PLATFORM_READY,
                "TradingStrategy initialized; platform broker(s) connected",
            )
            # ── B: Phase 1 → 2 (brokers registered; capital brain may begin) ────────
            _advance_phase(_Phase.CAPITAL_BRAIN, reason="TradingStrategy initialised; platform brokers connected")

            # ── MICRO_PLATFORM tier floor validation ─────────────────────────
            # Confirm that the sizing module's MICRO_PLATFORM minimum position
            # floor is set to 40 %.  A mismatch here causes under-sized positions
            # that cannot clear execution fees on small accounts.
            try:
                from bot.risk.sizing import MICRO_PLATFORM_MIN_POSITION_PCT as _mp_pct
                _expected_mp = 0.40
                if abs(_mp_pct - _expected_mp) > 1e-6:
                    logger.error(
                        "❌ TIER FLOOR MISMATCH: MICRO_PLATFORM_MIN_POSITION_PCT=%.2f "
                        "(expected %.2f) — update bot/risk/sizing.py",
                        _mp_pct, _expected_mp,
                    )
                else:
                    logger.info(
                        "✅ MICRO_PLATFORM tier floor: %.0f%% (correct)", _mp_pct * 100
                    )
            except ImportError:
                logger.warning("⚠️  Could not verify MICRO_PLATFORM tier floor — bot/risk/sizing.py not found")

            # AUDIT USER BALANCES - Show all user balances regardless of trading status
            # This runs BEFORE trading starts to ensure visibility even if users aren't actively trading
            logger.info("=" * 70)
            logger.info("🔍 AUDITING USER ACCOUNT BALANCES")
            logger.info("=" * 70)
            if hasattr(strategy, 'multi_account_manager') and strategy.multi_account_manager:
                strategy.multi_account_manager.audit_user_accounts()
            else:
                logger.warning("   ⚠️  Multi-account manager not available - skipping balance audit")

            # STARTUP BALANCE CONFIRMATION - Display live capital for legal/operational protection
            logger.info("")
            logger.info("=" * 70)
            logger.info("💰 LIVE CAPITAL CONFIRMED:")
            logger.info("=" * 70)
            if hasattr(strategy, 'multi_account_manager') and strategy.multi_account_manager:
                try:
                    manager = strategy.multi_account_manager

                    # Get all balances
                    all_balances = manager.get_all_balances()

                    # Platform account total
                    platform_total = sum(all_balances.get('platform', {}).values())
                    logger.info(f"   Platform: ${platform_total:,.2f}")

                    # User accounts - specifically Daivon and Tania
                    users_balances = all_balances.get('users', {})

                    # Find Daivon's balance
                    daivon_total = 0.0
                    for user_id, balances in users_balances.items():
                        if 'daivon' in user_id.lower():
                            daivon_total = sum(balances.values())
                            break
                    logger.info(f"   Daivon: ${daivon_total:,.2f}")

                    # Find Tania's balance
                    tania_total = 0.0
                    for user_id, balances in users_balances.items():
                        if 'tania' in user_id.lower():
                            tania_total = sum(balances.values())
                            break
                    logger.info(f"   Tania: ${tania_total:,.2f}")

                    # Show grand total
                    grand_total = platform_total + daivon_total + tania_total
                    logger.info("")
                    logger.info(f"   🏦 TOTAL CAPITAL UNDER MANAGEMENT: ${grand_total:,.2f}")
                except Exception as e:
                    logger.error(f"   ⚠️  Error fetching balances: {e}")
                    logger.error("   ⚠️  Continuing with startup - balances will be shown in trade logs")
            else:
                logger.warning("   ⚠️  Multi-account manager not available - cannot confirm balances")
            logger.info("=" * 70)

            # Independent trading mode - all accounts trade using same logic
            logger.info("=" * 70)
            logger.info("🔄 INDEPENDENT TRADING MODE ENABLED (NO COPY TRADING)")
            logger.info("=" * 70)
            logger.info("   ✅ Each account trades INDEPENDENTLY using NIJA strategy")
            logger.info("   ✅ Same strategy logic, but executed independently per account")
            logger.info("   ✅ Same risk management rules for all accounts")
            logger.info("   ✅ Position sizing scaled by account balance")
            logger.info("   ❌ NO trade copying or mirroring between accounts")
            logger.info("   ℹ️  All accounts evaluate signals and execute independently")
            logger.info("=" * 70)

            # Log clear trading readiness status
            logger.info("=" * 70)
            logger.info("📊 TRADING READINESS STATUS")
            logger.info("=" * 70)

            # Check which master brokers are connected
            connected_platform_brokers = []
            failed_platform_brokers = []

            if hasattr(strategy, 'multi_account_manager') and strategy.multi_account_manager:
                for broker_type, broker in strategy.multi_account_manager.platform_brokers.items():
                    if broker and broker.connected:
                        broker_name = broker_type.value
                        logger.info(f"✅ BROKER CONNECTED: {broker_name}")
                        connected_platform_brokers.append(broker_type.value.upper())

            # CRITICAL FIX: Check for brokers with credentials configured but failed to connect
            # This catches cases where credentials are set but connection failed due to:
            # - SDK not installed (krakenex/pykrakenapi missing)
            # - Permission errors (API key lacks required permissions)
            # - Nonce errors (timing issues)
            # - Network errors
            # Check if Kraken was expected but didn't connect
            if kraken_platform_configured and 'KRAKEN' not in connected_platform_brokers:
                failed_platform_brokers.append('KRAKEN')

            # Check if Coinbase was expected but didn't connect
            if (
                coinbase_configured
                and not _is_truthy_env("NIJA_DISABLE_COINBASE", "false")
                and 'COINBASE' not in connected_platform_brokers
            ):
                failed_platform_brokers.append('COINBASE')

            # Track if Kraken credentials were not configured at all
            kraken_not_configured = not kraken_platform_configured

            if connected_platform_brokers:
                logger.info("✅ Connected Platform Exchanges:")
                for exchange in connected_platform_brokers:
                    logger.info(f"   ✅ {exchange}")
                logger.info("")
                
                # Show failures if any
                if failed_platform_brokers:
                    logger.info("")
                    logger.warning("⚠️  Expected but NOT Connected:")
                    for exchange in failed_platform_brokers:
                        logger.warning(f"   ❌ {exchange}")
                        if exchange == 'KRAKEN':
                            # Try to get the specific error from the failed broker instance
                            error_msg = None
                            if hasattr(strategy, 'failed_brokers') and BrokerType.KRAKEN in strategy.failed_brokers:
                                failed_broker = strategy.failed_brokers[BrokerType.KRAKEN]
                                if hasattr(failed_broker, 'last_connection_error') and failed_broker.last_connection_error:
                                    error_msg = failed_broker.last_connection_error

                            if error_msg:
                                _log_kraken_connection_error_header(error_msg)
                                # Check for SDK import errors
                                is_sdk_error = any(pattern in error_msg.lower() for pattern in [
                                    "sdk import error",
                                    "modulenotfounderror",
                                    "no module named 'krakenex'",
                                    "no module named 'pykrakenapi'",
                                ])
                                if is_sdk_error:
                                    logger.error("")
                                    logger.error("      ❌ KRAKEN SDK NOT INSTALLED")
                                    logger.error("      The Kraken libraries (krakenex/pykrakenapi) are missing!")
                                    logger.error("")
                                    logger.error("      🔧 IMMEDIATE FIX REQUIRED:")
                                    logger.error("      1. Verify your deployment platform is using the Dockerfile")
                                    logger.error("")
                                elif "permission" in error_msg.lower():
                                    logger.error("      → Fix: Enable required permissions at https://www.kraken.com/u/security/api")
                                elif "nonce" in error_msg.lower():
                                    logger.error("      → Fix: Wait 1-2 minutes and restart the bot")
                                else:
                                    logger.error("      → Verify credentials at https://www.kraken.com/u/security/api")
                        elif exchange == 'COINBASE':
                            logger.warning("      Coinbase credentials are set but connection failed.")
                            logger.warning("      Common causes:")
                            logger.warning("        • Invalid API key or secret format")
                            logger.warning("        • API key lacks required permissions")
                            logger.warning("        • Account balance check failed (see logs above)")
                            logger.warning("      → Run: python test_v2_balance.py for a detailed diagnosis")
                            logger.warning("      → See README.md → '🔐 Coinbase API Setup' for help")

                logger.info("")
                logger.info(f"📈 Trading will occur on {len(connected_platform_brokers)} exchange(s)")
                logger.info("💡 Each exchange operates independently")
                logger.info("🛡️  Failures on one exchange won't affect others")
            else:
                logger.warning("⚠️  NO PLATFORM EXCHANGES CONNECTED")
                logger.warning("Bot is running in MONITOR MODE (no trades will execute)")
                logger.warning("")
                logger.warning("To enable trading:")
                logger.warning("   1. Run: python3 validate_all_env_vars.py")
                logger.warning("   2. Configure at least one platform exchange")
                logger.warning("   3. Restart the bot")
                
                # Update health status - exchanges configured but none connected
                health_manager.update_exchange_status(connected=0, expected=exchanges_configured)

            logger.info("=" * 70)
            logger.info("⛔ STARTUP INVARIANT: BLOCK TRADING UNTIL TOTAL CAPITAL > $0")
            logger.info("=" * 70)
            CAPITAL_GATE_INTERVAL_S = 15
            CAPITAL_GATE_LOG_EVERY_N_CHECKS = 4
            capital_gate_checks = 0

            # Bootstrap FSM: entering capital gate → CAPITAL_REFRESHING
            _bfsm_transition(
                _BootstrapState.CAPITAL_REFRESHING,
                "waiting for startup capital > $0",
            )

            # ── BOOTSTRAP MASTER SEQUENCE (single authority) ──────────────────
            # Explicitly drive the single-authority capital refresh so that the
            # CapitalAuthority singleton is hydrated before the capital gate
            # polling loop begins.  This eliminates the race condition where
            # dependent systems see INITIALIZING state because no coordinator
            # call has fired yet.
            #
            #   mabm.refresh_capital_authority(trigger="BOOTSTRAP_START")
            #   while not ca.is_hydrated:
            #       time.sleep(0.1)
            #   startup_lock.clear()   ← finalize_bootstrap_ready() equivalent
            _bms_mabm = getattr(strategy, "multi_account_manager", None)
            logger.critical("🔥 A3: before CapitalAuthority fetch")
            _bms_ca = None
            try:
                from bot.capital_authority import get_capital_authority as _get_ca_bms
                _bms_ca = _get_ca_bms()
            except Exception as _bms_import_err:
                logger.warning("[Bootstrap] Failed to import bot.capital_authority: %s", _bms_import_err)
                try:
                    from capital_authority import get_capital_authority as _get_ca_bms  # type: ignore[assignment]
                    _bms_ca = _get_ca_bms()
                except Exception as _bms_import_err2:
                    logger.warning("[Bootstrap] Failed to import capital_authority: %s", _bms_import_err2)
            _bms_refresh_ok = False
            if _bms_mabm is not None:
                # ── Broker-registration gates ──────────────────────────────────
                # Never call refresh_capital_authority() until real brokers exist.
                # Without these gates the seed path publishes a snapshot whose only
                # entry is the "__bootstrap_seed__" phantom, hydrating the Brain
                # before any real broker is present — the root cause of the bug.
                _bms_gate_start = time.monotonic()
                _bms_gate_timeout = 30.0
                while not _bms_mabm.has_registered_brokers():
                    if time.monotonic() - _bms_gate_start >= _bms_gate_timeout:
                        logger.warning(
                            "[Bootstrap] Timeout waiting for broker registration (%.0fs) — proceeding",
                            _bms_gate_timeout,
                        )
                        break
                    time.sleep(0.1)
                while not _bms_mabm.has_attempted_connections():
                    if time.monotonic() - _bms_gate_start >= _bms_gate_timeout:
                        logger.warning(
                            "[Bootstrap] Timeout waiting for connection attempts (%.0fs) — proceeding",
                            _bms_gate_timeout,
                        )
                        break
                    time.sleep(0.1)
                # ── END broker-registration gates ──────────────────────────────
                # ── B: enforce ordering — capital brain requires brokers registered ─
                # Non-blocking observable check: warn and continue with degraded
                # readiness rather than hard-raising.  The phase may not have
                # propagated yet when a retry reuses the same singleton, or when
                # the advance() fired before this listener was attached.
                if _PHASE_GATE_AVAILABLE:
                    from bot.startup_phase_gate import get_phase_gate as _get_pg2, Phase as _PhaseCheck2
                    if not _get_pg2().is_at_least(_PhaseCheck2.CAPITAL_BRAIN):
                        logger.warning(
                            "[PhaseGate] CAPITAL_BRAIN phase not reached yet — "
                            "continuing with degraded readiness"
                        )
                try:
                    logger.critical("🔥 A4: before nonce-related call")
                    _bms_mabm.refresh_capital_authority(trigger="BOOTSTRAP_START")
                    logger.info("[Bootstrap] BOOTSTRAP_START capital refresh triggered")
                    logger.critical("B4 after authority.refresh (refresh_capital_authority returned)")
                    _bms_refresh_ok = True
                except Exception as _bms_err:
                    logger.warning("[Bootstrap] BOOTSTRAP_START refresh error: %s", _bms_err)
            if _bms_ca is not None and _bms_refresh_ok:
                # 60 s covers typical cold-start broker API latency; the capital gate
                # polling loop below handles the case where we proceed without hydration.
                _bms_hydrate_start = time.monotonic()
                _bms_hydrate_timeout = 60.0
                while not _bms_ca.is_hydrated:
                    if time.monotonic() - _bms_hydrate_start >= _bms_hydrate_timeout:
                        logger.warning(
                            "[Bootstrap] Capital hydration timeout (%.0fs) — proceeding",
                            _bms_hydrate_timeout,
                        )
                        break
                    time.sleep(0.1)
                if _bms_ca.is_hydrated:
                    logger.info("[Bootstrap] CapitalAuthority hydrated — releasing startup lock")
                    if _bms_mabm is not None:
                        try:
                            _bms_mabm.finalize_bootstrap_ready()
                        except Exception as _bms_fbr_err:
                            logger.warning("[Bootstrap] finalize_bootstrap_ready error: %s", _bms_fbr_err)
            # ── END BOOTSTRAP MASTER SEQUENCE ─────────────────────────────────
            # ── B: Phase 2 → 3 (capital brain hydrated; strategy engine ready) ──
            _advance_phase(_Phase.STRATEGY_ENGINE, reason="CapitalAuthority hydrated; capital data available")
            if _startup_buffer:
                _startup_buffer.flush_phase("BROKER_REGISTRY")

            def _get_startup_total_capital() -> float:
                _mam = getattr(strategy, "multi_account_manager", None)
                if _mam and hasattr(_mam, "get_all_balances"):
                    _all_balances = _mam.get_all_balances()
                    _platform_raw = _all_balances.get("platform") or {}
                    _users_raw = _all_balances.get("users") or {}
                    _platform_total = sum(_platform_raw.values())
                    _users_total = sum(
                        sum((_user_balances or {}).values())
                        for _user_balances in _users_raw.values()
                    )
                    logger.debug(
                        "[CapGate] path=MAM  platform=%s platform_total=%.4f  "
                        "users=%s users_total=%.4f",
                        _platform_raw,
                        _platform_total,
                        {u: dict(v or {}) for u, v in _users_raw.items()},
                        _users_total,
                    )
                    return float(_platform_total + _users_total)
                _bm = getattr(strategy, "broker_manager", None)
                if _bm and hasattr(_bm, "get_total_balance"):
                    _bm_total = float(_bm.get_total_balance())
                    logger.debug(
                        "[CapGate] path=BM  broker_manager=%s  total=%.4f",
                        type(_bm).__name__,
                        _bm_total,
                    )
                    return _bm_total
                logger.debug(
                    "[CapGate] path=NONE  multi_account_manager=%s  broker_manager=%s",
                    type(getattr(strategy, "multi_account_manager", None)).__name__,
                    type(getattr(strategy, "broker_manager", None)).__name__,
                )
                return 0.0

            logger.critical("🔥 A5: before SENTINEL B")
            logger.critical("🔥 SENTINEL B: entering capital gate")
            _capital_gate_deadline = time.time() + 60
            while True:
                logger.critical("🔥 SENTINEL C: capital loop iteration")
                try:
                    _total_capital = _get_startup_total_capital()
                except Exception as _cap_gate_err:
                    logger.warning(
                        "⚠️ Startup capital invariant check failed: %s",
                        _cap_gate_err,
                    )
                    _total_capital = 0.0

                ca = _bms_ca
                # Per-pass diagnostic — tells exactly which field is stuck
                if ca is not None:
                    logger.warning(
                        "[CapGate] hydrated=%s state=%s total=%s ready=%s",
                        ca.is_hydrated,
                        ca.state,
                        ca.total_capital,
                        ca.is_ready(),
                    )

                # ── Blocker-2 self-heal: retry capital refresh if CA is not yet
                # hydrated.  The initial BOOTSTRAP_START call may have returned
                # "pending" when broker_map was still empty (brokers registered
                # but no balance payload yet).  Without retrying here the CA
                # never hydrates and the gate always times out after 60 s.
                if ca is not None and not ca.is_hydrated and _bms_mabm is not None:
                    try:
                        _bms_mabm.refresh_capital_authority(trigger="BOOTSTRAP_START")
                        logger.info("[CapGate] Retried BOOTSTRAP_START capital refresh")
                    except Exception as _retry_err:
                        logger.debug("[CapGate] BOOTSTRAP_START retry error (non-fatal): %s", _retry_err)

                if ca and ca.is_ready():
                    logger.critical(
                        "✅ CAPITAL GATE PASSED — CA hydrated with registered broker balances"
                    )
                    logger.info("🚀 SYSTEM READY — TRADING ENABLED")
                    logger.info("💰 Startup total capital: $%.2f", _total_capital)
                    # Bootstrap FSM: capital confirmed → CAPITAL_READY
                    _bfsm_transition(
                        _BootstrapState.CAPITAL_READY,
                        f"startup capital confirmed: ${_total_capital:.2f}",
                    )
                    break

                if time.time() > _capital_gate_deadline:
                    raise RuntimeError(
                        "INIT FAILED: CapitalAuthority never became ready"
                    )

                capital_gate_checks += 1
                _should_log_gate = (
                    capital_gate_checks == 1
                    or capital_gate_checks % CAPITAL_GATE_LOG_EVERY_N_CHECKS == 0
                )
                if _should_log_gate:
                    logger.warning(
                        "⏳ Trading loop blocked: waiting for total capital > $0 "
                        "(current=$%.2f, check=#%d, next check in %ds)",
                        _total_capital,
                        capital_gate_checks,
                        CAPITAL_GATE_INTERVAL_S,
                    )
                    # ── Diagnostic: report the exact execution path that returned $0 ──
                    _diag_mam = getattr(strategy, "multi_account_manager", None)
                    _diag_bm = getattr(strategy, "broker_manager", None)
                    logger.warning(
                        "[CapGate-Diag] multi_account_manager=%s  broker_manager=%s",
                        type(_diag_mam).__name__ if _diag_mam is not None else "None",
                        type(_diag_bm).__name__ if _diag_bm is not None else "None",
                    )
                    if _diag_mam is not None:
                        try:
                            _diag_balances = _diag_mam.get_all_balances()
                            logger.warning(
                                "[CapGate-Diag] MAM.get_all_balances()=%s",
                                _diag_balances,
                            )
                        except Exception as _diag_bal_err:
                            logger.warning(
                                "[CapGate-Diag] MAM.get_all_balances() raised: %s",
                                _diag_bal_err,
                            )
                        _diag_has_reg = getattr(_diag_mam, "has_registered_brokers", None)
                        _diag_has_conn = getattr(_diag_mam, "has_attempted_connections", None)
                        logger.warning(
                            "[CapGate-Diag] MAM.has_registered_brokers=%s  "
                            "MAM.has_attempted_connections=%s",
                            _diag_has_reg() if callable(_diag_has_reg) else _diag_has_reg,
                            _diag_has_conn() if callable(_diag_has_conn) else _diag_has_conn,
                        )
                    if _diag_bm is not None:
                        try:
                            logger.warning(
                                "[CapGate-Diag] BM.get_total_balance()=%.4f",
                                float(_diag_bm.get_total_balance()),
                            )
                        except Exception as _diag_bm_err:
                            logger.warning(
                                "[CapGate-Diag] BM.get_total_balance() raised: %s",
                                _diag_bm_err,
                            )
                    # ── Diagnostic: CapitalAuthority hydration state ──────────────
                    if _bms_ca is not None:
                        try:
                            logger.warning(
                                "[CapGate-Diag] CapitalAuthority.is_hydrated=%s  "
                                "state=%s  total_capital=%.4f",
                                _bms_ca.is_hydrated,
                                getattr(_bms_ca, "state", "N/A"),
                                float(getattr(_bms_ca, "total_capital", 0) or 0),
                            )
                        except Exception as _diag_ca_err:
                            logger.warning(
                                "[CapGate-Diag] CapitalAuthority probe raised: %s",
                                _diag_ca_err,
                            )
                    # ── Diagnostic: trading state machine current state ───────────
                    try:
                        from bot.trading_state_machine import get_state_machine as _get_tsm_diag
                        _tsm_diag = _get_tsm_diag()
                        logger.warning(
                            "[CapGate-Diag] TradingStateMachine.state=%s",
                            _tsm_diag.get_current_state().value,
                        )
                    except Exception as _diag_tsm_err:
                        logger.warning(
                            "[CapGate-Diag] TradingStateMachine probe raised: %s",
                            _diag_tsm_err,
                        )
                time.sleep(3)
            logger.info("=" * 70)
            # ── B: Phase 3 → 4 (strategy engine ready; execution layer may begin) ──
            _advance_phase(_Phase.EXECUTION_LAYER, reason="startup capital confirmed; strategy engine ready")
            if _startup_buffer:
                _startup_buffer.flush_phase("CAPITAL_BRAIN")

            # ── CONNECTION → INIT HANDOFF: activate trading state machine ──────────
            # maybe_auto_activate() was attempted at module-load time (inside
            # _verify_env) but CapitalAuthority was not yet hydrated, so Gate 2
            # (CA_READY) blocked the OFF → LIVE_ACTIVE transition.  Now that the
            # capital gate has confirmed CapitalAuthority is_ready() and IS
            # hydrated, retry the transition so trading threads are allowed to execute.
            # Without this call the state machine stays in OFF forever and no trades
            # are ever placed — the state machine handoff failure described in FIX #1.
            from bot.trading_state_machine import get_state_machine as _get_tsm_init
            _tsm_init = _get_tsm_init()
            if _tsm_init.maybe_auto_activate():
                logger.critical(
                    "✅ INIT PHASE: state machine transitioned to LIVE_ACTIVE"
                )
                logger.critical("B6 after activate_trading (maybe_auto_activate succeeded)")
            else:
                # Diagnose which gate blocked the transition so the root cause is
                # surfaced immediately rather than buried in a generic retry loop.
                _lcv_val = os.environ.get("LIVE_CAPITAL_VERIFIED", "").lower().strip()
                _tsm_state = _tsm_init.get_current_state().value
                if _lcv_val not in ("true", "1", "yes", "enabled"):
                    raise RuntimeError(
                        "INIT FAILED: LIVE_CAPITAL_VERIFIED is not set to 'true'. "
                        f"Current value: {_lcv_val!r}. "
                        "Set LIVE_CAPITAL_VERIFIED=true in your environment to enable live trading. "
                        f"(TradingStateMachine state: {_tsm_state})"
                    )
                raise RuntimeError(
                    f"INIT FAILED: maybe_auto_activate() blocked after CA_READY "
                    f"(TradingStateMachine state: {_tsm_state}, "
                    f"LIVE_CAPITAL_VERIFIED={_lcv_val!r}). "
                    "Check logs for _capital_readiness_gate details."
                )
            # ── END CONNECTION → INIT HANDOFF ────────────────────────────────────

            # ═══════════════════════════════════════════════════════════════════════
            # BULLETPROOF TRADING ORCHESTRATOR
            # ═══════════════════════════════════════════════════════════════════════
            # Architecture:
            #   1. Detect funded platform + user brokers.
            #   2. Start a self-healing daemon thread per broker via
            #      _start_trader_thread / _start_single_broker_thread.
            #   3. Supervisor loop checks thread health every 10 s and restarts
            #      any thread that dies unexpectedly.
            #   4. NEVER exits silently — process stays alive until SIGTERM/SIGINT.
            #
            # Bug fixed: previously, when strategy.independent_trader was None
            # (init failure) but MULTI_BROKER_INDEPENDENT=true (the default),
            # NEITHER the independent loop NOR the single-broker fallback would
            # run — sending the bot directly to the keep-alive loop with zero
            # trading activity.
            # ═══════════════════════════════════════════════════════════════════════

            # ── Bootstrap FSM invariant guards before launching trading threads ──
            if _BOOTSTRAP_FSM_AVAILABLE:
                _boot_fsm = _get_bootstrap_fsm()
                # I4: capital bootstrap must be READY
                try:
                    _boot_fsm.assert_invariant_i4_capital_gate()
                except Exception as _inv_err:
                    logger.warning("⚠️  Bootstrap invariant I4 violation: %s", _inv_err)
                # I7: EMERGENCY_STOP blocks thread launch
                try:
                    _boot_fsm.assert_invariant_i7_emergency_safety()
                except Exception as _inv_err:
                    logger.warning("⚠️  Bootstrap invariant I7 violation: %s", _inv_err)
                _bfsm_transition(
                    _BootstrapState.THREADS_STARTING,
                    "spawning trading worker threads",
                )

            # ── LIVE_ACTIVE guard: no state machine → no threads ──────────────────
            from bot.trading_state_machine import get_state_machine as _get_tsm_assert, TradingState as _TradingState
            assert _get_tsm_assert().get_current_state() == _TradingState.LIVE_ACTIVE, (
                "INIT FAILED: state machine is not LIVE_ACTIVE before thread launch"
            )

            use_independent_trading = (
                os.getenv("MULTI_BROKER_INDEPENDENT", "true").lower() in ["true", "1", "yes"]
                and strategy.independent_trader is not None
            )

            # _active_threads: broker_key → {thread, stop_flag, broker_type, broker, mode, ...}
            _active_threads: dict = {}

            if use_independent_trading:
                logger.info("=" * 70)
                logger.info("🚀 STARTING INDEPENDENT MULTI-BROKER TRADING MODE")
                logger.info("=" * 70)
                logger.info("   Each broker trades in its own self-healing daemon thread.")
                logger.info("   The supervisor restarts any thread that dies unexpectedly.")
                logger.info("=" * 70)

                # Detect funded platform brokers
                _funded = strategy.independent_trader.detect_funded_brokers()
                _broker_source = strategy.independent_trader._get_platform_broker_source()

                # Register all platform brokers with the failure manager
                try:
                    if strategy.independent_trader.broker_failure_manager and _broker_source:
                        _equal_alloc = 1.0 / max(len(_broker_source), 1)
                        for _bt, _br in _broker_source.items():
                            strategy.independent_trader.broker_failure_manager.register_broker(
                                _bt.value, initial_allocation=_equal_alloc
                            )
                        strategy.independent_trader.broker_failure_manager.log_active_dead_banner()
                except Exception as _reg_err:
                    logger.debug("Failure manager registration skipped: %s", _reg_err)

                # Start a self-healing thread for each funded, connected platform broker
                _platform_stagger = 0
                for _broker_type, _broker in _broker_source.items():
                    _bname = _broker_type.value
                    if _bname not in _funded:
                        logger.info("   ⏭️  %s — not funded, skipping", _bname.upper())
                        continue
                    if not _broker.connected:
                        logger.warning("   ⚠️  %s — not connected, skipping", _bname.upper())
                        continue
                    # Stagger starts to prevent simultaneous API bursts
                    if _platform_stagger > 0:
                        logger.info(
                            "   ⏳ Staggering: 10s before starting %s…", _bname.upper()
                        )
                        time.sleep(10)
                    _t, _sf = _start_trader_thread(
                        strategy.independent_trader, _broker_type, _broker
                    )
                    _active_threads[_bname] = {
                        "thread": _t,
                        "stop_flag": _sf,
                        "broker_type": _broker_type,
                        "broker": _broker,
                        "mode": "platform",
                    }
                    logger.info(
                        "   ✅ Self-healing trader thread started for %s", _bname.upper()
                    )
                    _platform_stagger += 1

                # Start user broker threads (individually wrapped for self-healing)
                try:
                    _funded_users = strategy.independent_trader.detect_funded_user_brokers()
                except Exception as _fu_err:
                    logger.warning("Could not detect funded user brokers: %s", _fu_err)
                    _funded_users = {}

                if _funded_users and strategy.multi_account_manager:
                    logger.info("=" * 70)
                    logger.info("👤 STARTING USER BROKER THREADS")
                    logger.info("=" * 70)
                    for _uid, _user_brokers in strategy.multi_account_manager.user_brokers.items():
                        if _uid not in _funded_users:
                            continue
                        for _ubt, _ubr in _user_brokers.items():
                            _ubname = f"{_uid}_{_ubt.value}"
                            # Respect per-user independent_trading flag
                            _ucfg = strategy.multi_account_manager.user_configs.get(_uid)
                            if not (_ucfg and _ucfg.independent_trading):
                                logger.info(
                                    "   ⏭️  %s — independent_trading not enabled", _ubname
                                )
                                continue
                            if _ubt.value not in _funded_users.get(_uid, {}):
                                continue
                            if not _ubr.connected:
                                logger.warning(
                                    "   ⚠️  %s — not connected, skipping", _ubname
                                )
                                continue
                            _user_sf = threading.Event()
                            _user_t = threading.Thread(
                                target=strategy.independent_trader.run_user_broker_trading_loop,
                                args=(_uid, _ubt, _ubr, _user_sf),
                                name=f"Trader-{_ubname}",
                                daemon=True,
                            )
                            _user_t.start()
                            _active_threads[_ubname] = {
                                "thread": _user_t,
                                "stop_flag": _user_sf,
                                "broker_type": _ubt,
                                "broker": _ubr,
                                "mode": "user",
                                "user_id": _uid,
                            }
                            logger.info("   ✅ User trader thread started: %s", _ubname)

                if not _active_threads:
                    logger.warning(
                        "⚠️  No funded/connected brokers — falling back to single-broker mode"
                    )
                    use_independent_trading = False

                # Start connection monitor for brokers that couldn't connect at boot
                try:
                    strategy.independent_trader.start_connection_monitor()
                except Exception as _cm_err:
                    logger.debug("Connection monitor start skipped: %s", _cm_err)

            if not use_independent_trading:
                # Single-broker fallback: run strategy.run_cycle() in a self-healing thread
                _hf_cycle_secs = _hf_bot.get_cycle_interval() if _hf_bot is not None else 150
                _hf_label = (
                    f"HF scalping ({_hf_cycle_secs}s)"
                    if (_hf_bot is not None and _hf_bot.enabled)
                    else "2.5 minute"
                )
                logger.info(
                    "🚀 Starting single-broker trading thread (%s cadence)…", _hf_label
                )
                _t, _sf = _start_single_broker_thread(strategy, _hf_cycle_secs)
                _active_threads["__single_broker__"] = {
                    "thread": _t,
                    "stop_flag": _sf,
                    "broker_type": None,
                    "broker": None,
                    "mode": "single",
                }
                logger.info("   ✅ Self-healing single-broker thread started")

            # ── FIX 2: RUNTIME START CONFIRMATION ──────────────────────────────────
            # Emit the definitive "RUNTIME MODE ACTIVE" log ONLY when all three
            # conditions are met: LIVE_ACTIVE state, CA_READY, and execution engine
            # initialized.  This provides an unambiguous proof that the trading loop
            # has actually begun; its absence in logs means a stall occurred.
            try:
                from bot.trading_state_machine import get_state_machine as _gsm, TradingState as _TS
                _sm_state = _gsm().get_current_state()
            except Exception:
                try:
                    from trading_state_machine import get_state_machine as _gsm, TradingState as _TS
                    _sm_state = _gsm().get_current_state()
                except Exception:
                    _sm_state = None
                    _TS = None

            _ca_ready_flag = False
            try:
                from bot.capital_authority import get_capital_authority as _gca
                _ca_ready_flag = _gca().is_ready()
            except Exception:
                try:
                    from capital_authority import get_capital_authority as _gca  # type: ignore[import]
                    _ca_ready_flag = _gca().is_ready()
                except Exception:
                    _ca_ready_flag = False  # fail-closed: block confirmation if CA unavailable

            _exec_engine_ready = (
                hasattr(strategy, "execution_engine")
                and strategy.execution_engine is not None
            )

            if (
                _sm_state is not None
                and _TS is not None
                and _sm_state == _TS.LIVE_ACTIVE
                and _ca_ready_flag
                and _exec_engine_ready
            ):
                logger.info(
                    "✅ RUNTIME MODE ACTIVE — market loop starting "
                    "(CA_READY=True, LIVE_ACTIVE=True, execution_engine=initialized)"
                )
            else:
                logger.warning(
                    "⚠️ RUNTIME START: one or more readiness conditions not met — "
                    "LIVE_ACTIVE=%s CA_READY=%s execution_engine=%s",
                    _sm_state == _TS.LIVE_ACTIVE if (_sm_state and _TS) else "unknown",
                    _ca_ready_flag,
                    _exec_engine_ready,
                )

            # ═══════════════════════════════════════════════════════════════════════
            # SUPERVISOR LOOP — monitors every 10 s, restarts dead threads
            # ═══════════════════════════════════════════════════════════════════════

            # Persist initialised state (thread-safe) so a supervisor-loop crash
            # can be retried WITHOUT recreating TradingStrategy or reconnecting brokers.
            print("INIT_LOCK_ATTEMPT", flush=True)
            _acquired = _initialized_state_lock.acquire(timeout=5)
            if not _acquired:
                raise RuntimeError("DEADLOCK: _initialized_state_lock not acquired")
            try:
                print("INIT_LOCK_ACQUIRED", flush=True)
                _initialized_state = {
                    "strategy": strategy,
                    "active_threads": _active_threads,
                    "use_independent_trading": use_independent_trading,
                    "health_manager": health_manager,
                }
            finally:
                _initialized_state_lock.release()
            logger.critical(f"STATE CHECK: {_initialized_state}")
            logger.critical("🧠 STATE STORED — entering supervisor mode")

            _log_lifecycle_banner(
                "🔒 ORCHESTRATOR ACTIVE",
                [
                    f"{len(_active_threads)} trader thread(s) running",
                    "Supervisor checks thread health every 10s",
                    "Dead threads are restarted automatically",
                    "Process will never exit silently",
                    *_get_thread_status(),
                ],
            )

            # STEP 3 — ALWAYS run trading loop via the shared supervisor.
            # Delegates to _rerun_supervisor_loop so the supervisor logic lives
            # in exactly one place and retries (fast-path) use the same code.
            print("INIT_LOCK_ATTEMPT", flush=True)
            _acquired = _initialized_state_lock.acquire(timeout=5)
            if not _acquired:
                raise RuntimeError("DEADLOCK: _initialized_state_lock not acquired")
            try:
                print("INIT_LOCK_ACQUIRED", flush=True)
                _state_for_supervisor = dict(_initialized_state)
            finally:
                _initialized_state_lock.release()
            # Bootstrap FSM: all threads live → RUNNING_SUPERVISED
            _bfsm_transition(
                _BootstrapState.RUNNING_SUPERVISED,
                f"{len(_active_threads)} trader thread(s) started; supervisor loop active",
            )
            logger.info("🚀 FSM STATE: RUNNING_SUPERVISED")

            # FIX OPTION A: Force activation check AFTER INIT completes.
            # maybe_auto_activate() was called earlier (during the capital gate
            # phase) but the full bootstrap (threads started, _initialized_state
            # populated) had not yet completed at that point.  Any race condition
            # or concurrent reset between that call and here would leave the state
            # machine in OFF / EMERGENCY_STOP with no recovery path.  Calling
            # force_post_init_state_machine_step() ensures the trading state machine
            # is checked — and re-activated if needed — once the bootstrap sequence
            # is truly complete.
            try:
                from bot.self_healing_startup import force_post_init_state_machine_step
                force_post_init_state_machine_step()
                logger.critical(
                    "✅ POST-INIT: state machine step complete after bootstrap"
                )
            except Exception as _post_init_sm_err:
                logger.critical(
                    "[BOOT] post-init state machine step failed: %s",
                    _post_init_sm_err,
                )

            # Enforce startup truth conditions before supervised execution.
            _verify_startup_truth_conditions(
                strategy,
                _active_threads,
                kraken_credentials_valid=_kraken_credentials_valid,
            )

            # ── B: Phase 4 → 5 (execution layer live; live trading enabled) ─────────
            _advance_phase(_Phase.LIVE_ENABLE, reason="trading threads running; supervisor loop starting")
            # ── A: flush remaining startup output; restore per-line console logging ──
            if _startup_buffer:
                _startup_buffer.flush_phase("EXECUTION_LAYER")
                _startup_buffer.uninstall()

            _rerun_supervisor_loop(_state_for_supervisor)

        except RuntimeError as e:
            if "Broker connection failed" in str(e):
                _log_exit_point(
                    "Broker Connection Failed",
                    exit_code=1,
                    details=[
                        "RuntimeError: Broker connection failed",
                        "Credentials not found or invalid",
                        *_get_thread_status()
                    ]
                )
                raise
            else:
                _log_exit_point(
                    "Fatal Initialization Error",
                    exit_code=1,
                    details=[
                        f"RuntimeError: {str(e)}",
                        "Bot initialization failed",
                        *_get_thread_status()
                    ]
                )
                logger.error(f"Fatal error initializing bot: {e}", exc_info=True)
                raise
        except Exception as e:
            _log_exit_point(
                "Unhandled Fatal Error in Startup Thread",
                exit_code=1,
                details=[
                    f"Exception Type: {type(e).__name__}",
                    f"Error: {str(e)}",
                    "An unexpected error occurred in startup thread",
                    *_get_thread_status()
                ]
            )
            logger.exception(f"❌ Startup thread crashed: {e}")
            raise
            
    except Exception as e:
        logger.exception(f"🧵 ❌ Fatal error in startup thread outer handler: {e}")
        raise
    finally:
        # A: Guarantee the startup buffer is uninstalled on every exit path
        # (success, error, KeyboardInterrupt) so no records are silently lost
        # after startup completes or fails.  uninstall() is idempotent.
        if _startup_buffer:
            _startup_buffer.uninstall()


def main():
    """Main entry point for NIJA trading bot - Railway optimized"""
    
    # ═══════════════════════════════════════════════════════════════════════
    # CRITICAL: START HEALTH SERVER FIRST (Railway requirement)
    # ═══════════════════════════════════════════════════════════════════════
    # Health server MUST bind BEFORE:
    # - Kraken connections
    # - User loading  
    # - Any sleeps or loops
    # - Even logging setup
    #
    # This prevents Railway from killing the container during startup.
    # The /health endpoint ALWAYS returns 200 OK regardless of bot state.
    print("=" * 70)
    print("🌐 STARTING HEALTH SERVER (Railway requirement)")
    print("=" * 70)
    _start_health_server()
    print("✅ Health server started - Railway will not kill this container")
    print("=" * 70)
    print("")

    # Advance bootstrap FSM: BOOT_INIT → LOCK_ACQUIRED → HEALTH_BOUND
    # (process lock was acquired at module import; health server is now bound)
    if _BOOTSTRAP_FSM_AVAILABLE:
        _bfsm_transition(_BootstrapState.LOCK_ACQUIRED, "process lock acquired at module load")
        _bfsm_transition(_BootstrapState.HEALTH_BOUND, "health server bound")
    
    # Small delay to ensure health server is fully bound
    time.sleep(0.2)
    
    # Now setup logging (after health server is running)
    # Log process startup
    _log_lifecycle_banner(
        "🚀 NIJA TRADING BOT STARTUP",
        [
            f"Process ID: {os.getpid()}",
            f"Python Version: {sys.version.split()[0]}",
            f"Working Directory: {os.getcwd()}",
            "Health server: ✅ RUNNING (started before initialization)",
            "Initializing lifecycle management..."
        ]
    )
    
    # Log memory usage at startup (lightweight - single line)
    _log_memory_usage()
    
    # Graceful shutdown handlers to avoid non-zero exits on platform terminations
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)
    logger.info("✅ Signal handlers registered (SIGTERM, SIGINT)")

    # Initialize health check manager early
    from bot.health_check import get_health_manager
    health_manager = get_health_manager()
    logger.info("✅ Health check manager initialized")
    
    # Start dedicated heartbeat thread for Railway health checks
    # This ensures heartbeat is updated frequently (every 10 seconds)
    # regardless of trading loop timing (150 seconds)
    # Critical for Railway health check responsiveness (~30 second intervals)
    def heartbeat_worker():
        """Background thread that updates heartbeat at regular intervals"""
        thread_id = threading.get_ident()
        logger.info(f"🧵 Heartbeat thread started (ID: {thread_id}, Interval: {HEARTBEAT_INTERVAL_SECONDS}s)")
        
        heartbeat_count = 0
        while True:
            try:
                health_manager.heartbeat()
                heartbeat_count += 1
                
                # Log every 60 heartbeats (10 minutes at 10s interval) for visibility
                if heartbeat_count % 60 == 0:
                    logger.debug(f"🧵 Heartbeat thread alive - {heartbeat_count} heartbeats sent")
                
                time.sleep(HEARTBEAT_INTERVAL_SECONDS)
            except Exception as e:
                logger.error(f"🧵 ❌ Error in heartbeat worker thread (ID: {thread_id}): {e}", exc_info=True)
                time.sleep(HEARTBEAT_INTERVAL_SECONDS)
    
    heartbeat_thread = threading.Thread(target=heartbeat_worker, daemon=True, name="HeartbeatWorker")
    heartbeat_thread.start()
    
    # Wait briefly to ensure thread actually starts
    time.sleep(0.1)
    
    _log_lifecycle_banner(
        "✅ BACKGROUND THREADS STARTED",
        [
            f"HeartbeatWorker: Thread ID {heartbeat_thread.ident}",
            f"Update Interval: {HEARTBEAT_INTERVAL_SECONDS} seconds",
            f"Thread is alive: {heartbeat_thread.is_alive()}",
            "Health checks will be responsive to Railway (~30s check interval)"
        ]
    )

    # ═══════════════════════════════════════════════════════════════════════
    # RAILWAY PATTERN: Spawn startup thread, main thread supervises
    # ═══════════════════════════════════════════════════════════════════════
    # Main thread stays in idle loop to keep health server responsive
    # Startup thread handles all bot initialization:
    # - Kraken connection
    # - User loading
    # - Balance fetching
    # - Trading loop
    
    logger.info("=" * 70)
    logger.info("🚀 SPAWNING STARTUP THREAD")
    logger.info("=" * 70)
    logger.info("Main thread will supervise while startup thread initializes bot")
    logger.info("Health server remains responsive during initialization")
    logger.info("=" * 70)
    
    startup_thread = threading.Thread(
        target=_run_bot_startup_and_trading_with_retry,  # single-owner kernel, always with retry
        daemon=False,  # NOT daemon - we want this to keep running
        name="BotStartup"
    )
    startup_thread.start()
    
    # Wait briefly to ensure thread starts
    time.sleep(0.2)
    
    _log_lifecycle_banner(
        "✅ STARTUP THREAD SPAWNED",
        [
            f"BotStartup: Thread ID {startup_thread.ident}",
            f"Thread is alive: {startup_thread.is_alive()}",
            "Bot initialization is now running in background",
            "Main thread entering supervisor mode..."
        ]
    )
    
    # ═══════════════════════════════════════════════════════════════════════
    # SUPERVISOR LOOP - Main thread stays here forever
    # ═══════════════════════════════════════════════════════════════════════
    # This keeps the process alive and health server responsive
    # while the startup thread does all the work
    
    _log_lifecycle_banner(
        "🔒 ENTERING SUPERVISOR MODE (observer-only)",
        [
            "Main thread observes background threads — does NOT restart them",
            "Bootstrap kernel (BotStartup) owns all retry logic internally",
            "Health server: ✅ Running (always responds to Railway)",
            "Heartbeat thread: ✅ Running (updates every 10s)",
            "Startup thread: ✅ Running (bootstrap kernel active)",
            f"Status logging every {KEEP_ALIVE_SLEEP_INTERVAL_SECONDS}s",
            "To shutdown: Use SIGTERM or SIGINT (handled by signal handlers)"
        ]
    )
    
    supervisor_cycle = 0
    while True:
        try:
            supervisor_cycle += 1

            restart_reason = _consume_external_watchdog_restart_reason()
            if restart_reason:
                # Bootstrap FSM: fatal condition requiring external restart
                _bfsm_transition(
                    _BootstrapState.EXTERNAL_RESTART_REQUIRED,
                    f"external watchdog restart: {restart_reason}",
                )
                _bfsm_transition(_BootstrapState.SHUTDOWN, "process exiting for external restart")
                _log_exit_point(
                    "External Watchdog Restart Requested",
                    exit_code=1,
                    details=[
                        "Fatal nonce condition requires clean external restart",
                        f"Reason: {restart_reason}",
                        *_get_thread_status(),
                    ],
                )
                raise RuntimeError(f"External watchdog restart requested: {restart_reason}")

            # Observer-only: BotStartup owns its own retry loop via the single-
            # owner kernel.  If the thread exits it means the kernel itself
            # terminated (clean shutdown, fatal nonce, or connection-loop
            # kill-switch).  Spawning a second BotStartup here would create a
            # concurrent bootstrap sequence — exactly the race we eliminated.
            # Instead, exit and let the external watchdog restart the process
            # with a clean slate.
            if not startup_thread.is_alive():
                logger.critical(
                    "💥 [Supervisor] Bootstrap kernel (BotStartup) thread has exited — "
                    "terminating process so an external process manager (Railway, systemd, "
                    "Docker restart policy) can restart with a clean state. "
                    "If no external watchdog is configured the process will stay stopped."
                )
                if _BOOTSTRAP_FSM_AVAILABLE:
                    _bfsm_transition(
                        _BootstrapState.SHUTDOWN,
                        "bootstrap kernel thread exited",
                    )
                _release_process_lock()
                sys.exit(1)
            
            # Log periodic status
            if supervisor_cycle % 12 == 0:  # Every hour at 300s intervals
                logger.info(f"💓 Supervisor status check #{supervisor_cycle // 12}")
                logger.info("🧵 Thread Status Report:")
                logger.info(f"   Health server: ✅ Running")
                logger.info(f"   Heartbeat thread: {'✅ Alive' if heartbeat_thread.is_alive() else '❌ Dead'}")
                logger.info(f"   Startup thread: {'✅ Alive' if startup_thread.is_alive() else '❌ Dead'}")
                for status_line in _get_thread_status():
                    logger.info(f"   {status_line}")
            
            time.sleep(KEEP_ALIVE_SLEEP_INTERVAL_SECONDS)
            
        except KeyboardInterrupt:
            _log_lifecycle_banner(
                "⚠️  SUPERVISOR INTERRUPTED",
                [
                    "KeyboardInterrupt received in supervisor loop",
                    "Shutting down gracefully...",
                    *_get_thread_status()
                ]
            )
            logger.info("Waiting for startup thread to finish...")
            startup_thread.join(timeout=10)
            break
        except RuntimeError as e:
            if "External watchdog restart requested:" in str(e):
                logger.critical("🚨 Exiting main supervisor for external watchdog restart")
                raise
            logger.error(f"❌ RuntimeError in supervisor loop: {e}", exc_info=True)
            logger.warning("Recovering from supervisor loop runtime error...")
            time.sleep(10)
        except Exception as e:
            logger.error(f"❌ Error in supervisor loop: {e}", exc_info=True)
            logger.warning("Recovering from supervisor loop error...")
            time.sleep(10)
    
    logger.info("✅ Main supervisor exiting gracefully")
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.critical(f"💥 FATAL ERROR — BOT CRASHED: {e}", exc_info=True)
        sys.exit(1)
