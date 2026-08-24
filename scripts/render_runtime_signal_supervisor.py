#!/usr/bin/env python3
"""Render PID-1 signal supervisor for NIJA's shell/Python runtime chain.

Render starts ``scripts/render_entrypoint.sh``.  That script eventually reaches
``start.sh``, which deliberately keeps a shell recovery loop around the canonical
Python launcher.  Bash defers trapped signals while it waits for a foreground
child, so a platform SIGTERM can reach the shell without promptly reaching the
Python process that owns the Redis writer lease.

This supervisor sits outside that chain and starts the existing production
bootstrap in its own process group.  SIGTERM/SIGINT are forwarded to the whole
runtime group immediately.  The canonical Python signal handler then performs
its existing fail-closed shutdown and exact-owner compare/delete writer release.

Safety contract:
* never reads, deletes, steals, or rewrites a Redis writer lock;
* never grants writer, nonce, execution, broker, risk, or readiness authority;
* never changes trading state or submits an order;
* preserves the existing shell recovery/health behavior on ordinary exits;
* uses SIGKILL only after a bounded platform-shutdown grace window, leaving the
  Redis TTL as the existing fallback if graceful release cannot finish.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from typing import Optional

LOGGER = logging.getLogger("nija.render_signal_supervisor")
MARKER = "20260824-render-signal-forwarding-v208"
ROOT = Path(__file__).resolve().parents[1]


def _grace_seconds() -> float:
    try:
        value = float(os.environ.get("NIJA_RENDER_SIGNAL_FORWARD_GRACE_S", "20") or "20")
    except (TypeError, ValueError):
        value = 20.0
    # Keep this below render.yaml maxShutdownDelaySeconds=60 while allowing the
    # Python runtime enough time to stop its heartbeats and compare-delete only
    # its own writer lease.
    return max(2.0, min(45.0, value))


def forward_signal(child: Optional[subprocess.Popen[bytes]], signum: int) -> bool:
    """Forward *signum* to the supervised runtime process group."""

    if child is None or child.poll() is not None:
        return False
    try:
        os.killpg(child.pid, signum)
    except ProcessLookupError:
        return False
    except Exception as exc:
        LOGGER.warning(
            "RENDER_SIGNAL_FORWARD_V208_FAILED marker=%s signal=%s child_pid=%s error=%s:%s",
            MARKER,
            signum,
            child.pid,
            type(exc).__name__,
            exc,
        )
        return False

    LOGGER.critical(
        "RENDER_SIGNAL_FORWARD_V208_FORWARDED marker=%s signal=%s child_pid=%s "
        "process_group=true writer_lock_mutated=false authority_granted=false "
        "safety_gates_bypassed=false",
        MARKER,
        signum,
        child.pid,
    )
    return True


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    command = ["bash", str(ROOT / "scripts" / "production_bootstrap.sh"), *args]
    child: Optional[subprocess.Popen[bytes]] = None
    termination_signal = 0
    termination_started = 0.0

    def _handle(signum: int, _frame) -> None:
        nonlocal termination_signal, termination_started
        if termination_signal == 0:
            termination_signal = signum
            termination_started = time.monotonic()
        forward_signal(child, signum)

    signal.signal(signal.SIGTERM, _handle)
    signal.signal(signal.SIGINT, _handle)

    LOGGER.critical(
        "RENDER_SIGNAL_FORWARD_V208_READY marker=%s parent_pid=%s grace_s=%.1f "
        "runtime_process_group=true writer_lock_mutated=false authority_granted=false "
        "safety_gates_bypassed=false",
        MARKER,
        os.getpid(),
        _grace_seconds(),
    )

    try:
        child = subprocess.Popen(
            command,
            cwd=str(ROOT),
            start_new_session=True,
        )
    except Exception as exc:
        LOGGER.critical(
            "RENDER_SIGNAL_FORWARD_V208_START_FAILED marker=%s error=%s:%s",
            MARKER,
            type(exc).__name__,
            exc,
        )
        return 78

    while child.poll() is None:
        if termination_signal:
            # The handler has already forwarded TERM/INT to the whole runtime
            # group.  Give bot_main's existing signal/finally path a bounded
            # chance to stop heartbeat renewal and compare-delete its own lock.
            if (time.monotonic() - termination_started) >= _grace_seconds():
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                    LOGGER.critical(
                        "RENDER_SIGNAL_FORWARD_V208_GRACE_EXHAUSTED marker=%s child_pid=%s "
                        "action=kill_process_group redis_ttl_fallback=true "
                        "writer_lock_force_deleted=false safety_gates_bypassed=false",
                        MARKER,
                        child.pid,
                    )
                except ProcessLookupError:
                    pass
                except Exception as exc:
                    LOGGER.warning(
                        "RENDER_SIGNAL_FORWARD_V208_KILL_FAILED marker=%s child_pid=%s error=%s:%s",
                        MARKER,
                        child.pid,
                        type(exc).__name__,
                        exc,
                    )
                break
        time.sleep(0.1)

    try:
        status = int(child.wait(timeout=5.0))
    except subprocess.TimeoutExpired:
        status = 137
    except Exception:
        status = 1

    if termination_signal:
        LOGGER.critical(
            "RENDER_SIGNAL_FORWARD_V208_PLATFORM_STOP_COMPLETE marker=%s signal=%s "
            "child_status=%s action=graceful_platform_stop",
            MARKER,
            termination_signal,
            status,
        )
        # Platform-requested termination is not a runtime crash.  The child has
        # already had the opportunity to run canonical writer release, with TTL
        # remaining the fallback if it could not.
        return 0

    return status


if __name__ == "__main__":
    raise SystemExit(main())
