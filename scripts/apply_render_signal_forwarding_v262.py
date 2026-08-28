#!/usr/bin/env python3
"""Apply Render SIGTERM forwarding to NIJA's shell supervisor (v262).

Render sends SIGTERM to the service process during zero-downtime replacement.
NIJA's start.sh historically ran the canonical Python runtime as a foreground
child while trapping TERM in the shell. Bash defers that trap while waiting for
the foreground child, so the Python writer process could continue renewing its
Redis lease until Render's final SIGKILL. A replacement instance then remained
fail-closed in writer standby even though the old deployment was already being
retired.

This patch keeps the shell supervisor and isolated liveness server intact, but
runs the canonical Python runtime as an explicitly tracked child. The TERM/INT
trap immediately forwards SIGTERM to that exact child and the shell performs a
second wait if the first wait was interrupted by the trap. The existing Python
SIGTERM handler remains responsible for stopping core work, quiescing writer
renewal, and compare-deleting only its own Redis lease.

No Redis lock is stolen or force-cleared. No writer, nonce, kill-switch, risk,
capital, ECEL, order, fill, or activation gate is bypassed.
"""
from __future__ import annotations

from pathlib import Path

MARKER = "20260828-render-signal-forwarding-v262"
ROOT = Path(__file__).resolve().parents[1]
START_SH = ROOT / "start.sh"

_OLD_TRAP = '''_RENDER_RUNTIME_TERMINATION_REQUESTED=false
_record_runtime_termination_request() {
    _RENDER_RUNTIME_TERMINATION_REQUESTED=true
    _cleanup_pid_lock
}
trap '_cleanup_pid_lock' EXIT
trap '_record_runtime_termination_request' INT TERM
'''

_NEW_TRAP = '''_RENDER_RUNTIME_TERMINATION_REQUESTED=false
_RENDER_RUNTIME_CHILD_PID=""
_record_runtime_termination_request() {
    _RENDER_RUNTIME_TERMINATION_REQUESTED=true
    _cleanup_pid_lock
    if [ -n "${_RENDER_RUNTIME_CHILD_PID:-}" ] \
        && kill -0 "${_RENDER_RUNTIME_CHILD_PID}" 2>/dev/null; then
        echo "🛑 RENDER_RUNTIME_SIGNAL_FORWARDED marker=20260828-render-signal-forwarding-v262 signal=TERM child_pid=${_RENDER_RUNTIME_CHILD_PID} writer_lock_force_clear=false"
        kill -TERM "${_RENDER_RUNTIME_CHILD_PID}" 2>/dev/null || true
    fi
}
trap '_cleanup_pid_lock' EXIT
trap '_record_runtime_termination_request' INT TERM
'''

_OLD_LAUNCH = '''while true; do
    set +e
    NIJA_DEFER_RUNTIME_SITE_HOOKS=1 $PY -u scripts/canonical_runtime_launcher_v26.py
    status=$?
    echo "🧭 STARTUP_HANDOFF_RUNTIME_EXIT status=${status}"
    set -e

    # Bash defers a trapped SIGTERM while it waits for the foreground Python
    # runtime.  Record that platform intent before classifying the child's
    # status so a native abort during interpreter teardown cannot start a new
    # runtime inside an instance Render is deliberately replacing.
    if [ "${_RENDER_RUNTIME_TERMINATION_REQUESTED}" = "true" ]; then
'''

_NEW_LAUNCH = '''while true; do
    set +e
    NIJA_DEFER_RUNTIME_SITE_HOOKS=1 $PY -u scripts/canonical_runtime_launcher_v26.py &
    _RENDER_RUNTIME_CHILD_PID=$!
    echo "🧭 RENDER_RUNTIME_CHILD_TRACKED marker=20260828-render-signal-forwarding-v262 child_pid=${_RENDER_RUNTIME_CHILD_PID}"
    wait "${_RENDER_RUNTIME_CHILD_PID}"
    status=$?

    # A trapped SIGTERM interrupts Bash's first wait. The trap has already
    # forwarded TERM to the exact Python child, so wait again while that child
    # runs NIJA's existing graceful shutdown and exact Redis compare-delete.
    if [ "${_RENDER_RUNTIME_TERMINATION_REQUESTED}" = "true" ] \
        && kill -0 "${_RENDER_RUNTIME_CHILD_PID}" 2>/dev/null; then
        echo "🛑 RENDER_RUNTIME_CHILD_GRACEFUL_WAIT marker=20260828-render-signal-forwarding-v262 child_pid=${_RENDER_RUNTIME_CHILD_PID}"
        wait "${_RENDER_RUNTIME_CHILD_PID}"
        status=$?
    fi
    _RENDER_RUNTIME_CHILD_PID=""
    echo "🧭 STARTUP_HANDOFF_RUNTIME_EXIT status=${status}"
    set -e

    # Platform termination intent is authoritative: never start an in-process
    # runtime recovery after Render has asked this instance to retire.
    if [ "${_RENDER_RUNTIME_TERMINATION_REQUESTED}" = "true" ]; then
'''


def apply(path: Path = START_SH) -> bool:
    source = path.read_text(encoding="utf-8")

    already_ready = (
        "RENDER_RUNTIME_SIGNAL_FORWARDED marker=20260828-render-signal-forwarding-v262" in source
        and "_RENDER_RUNTIME_CHILD_PID=$!" in source
        and 'wait "${_RENDER_RUNTIME_CHILD_PID}"' in source
    )
    if already_ready:
        print(
            f"RENDER_SIGNAL_FORWARDING_V262_READY marker={MARKER} already_applied=true "
            "writer_lock_force_clear=false safety_gates_bypassed=false"
        )
        return True

    if _OLD_TRAP not in source:
        raise RuntimeError("v262 trap anchor missing; refusing ambiguous start.sh rewrite")
    if _OLD_LAUNCH not in source:
        raise RuntimeError("v262 runtime launch anchor missing; refusing ambiguous start.sh rewrite")

    updated = source.replace(_OLD_TRAP, _NEW_TRAP, 1)
    updated = updated.replace(_OLD_LAUNCH, _NEW_LAUNCH, 1)

    required = (
        "_RENDER_RUNTIME_CHILD_PID=\"\"",
        "_RENDER_RUNTIME_CHILD_PID=$!",
        "RENDER_RUNTIME_SIGNAL_FORWARDED marker=20260828-render-signal-forwarding-v262",
        'kill -TERM "${_RENDER_RUNTIME_CHILD_PID}"',
        'wait "${_RENDER_RUNTIME_CHILD_PID}"',
        "Platform termination intent is authoritative",
    )
    missing = [token for token in required if token not in updated]
    if missing:
        raise RuntimeError(f"v262 output verification failed: missing={missing}")

    path.write_text(updated, encoding="utf-8")
    print(
        f"RENDER_SIGNAL_FORWARDING_V262_READY marker={MARKER} already_applied=false "
        "tracked_child=true sigterm_forwarded=true second_wait=true "
        "writer_lock_force_clear=false safety_gates_bypassed=false"
    )
    return True


if __name__ == "__main__":
    apply()
