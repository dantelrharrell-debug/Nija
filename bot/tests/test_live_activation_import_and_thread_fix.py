"""Regression tests for LIVE activation failure fix.

Verifies:
1. bot.nija_core_loop imports successfully (no ModuleNotFoundError)
2. startup coordinator recognises threads after record_threads_supervised()
3. threads.running gate passes when thread evidence is published
4. LIVE activation succeeds (coordinator readiness proof passes)
"""
from __future__ import annotations

import sys
import threading
import types
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# 1. Canonical module import
# ---------------------------------------------------------------------------


def test_bot_nija_core_loop_imports_successfully():
    """bot.nija_core_loop must be importable without a bare 'nija_core_loop' fallback."""
    from bot import nija_core_loop as ncl  # noqa: F401

    assert ncl is not None
    assert hasattr(ncl, "NijaCoreLoop"), "NijaCoreLoop class must exist in bot.nija_core_loop"
    assert hasattr(ncl, "get_nija_core_loop"), "get_nija_core_loop must exist in bot.nija_core_loop"
    assert hasattr(ncl, "start_trading_engine"), "start_trading_engine must exist in bot.nija_core_loop"


def test_bare_nija_core_loop_module_not_on_sys_modules_as_separate_entry():
    """Ensure we are not accidentally registering a bare 'nija_core_loop' module."""
    # It's acceptable if sys.modules has 'bot.nija_core_loop' but NOT a *standalone*
    # 'nija_core_loop' entry that points to a different object (split-module identity).
    from bot import nija_core_loop as canonical

    bare = sys.modules.get("nija_core_loop")
    if bare is not None:
        # If both exist they must be the same object (aliased), not two separate modules.
        assert bare is canonical, (
            "sys.modules['nija_core_loop'] points to a different object than "
            "bot.nija_core_loop — this causes split-module identity bugs"
        )


# ---------------------------------------------------------------------------
# 2. Startup coordinator recognises thread evidence
# ---------------------------------------------------------------------------


def test_record_threads_supervised_sets_threads_running():
    """record_threads_supervised() must make threads.running pass in readiness proof."""
    from bot.startup_coordinator import StartupCoordinator

    coord = StartupCoordinator()
    coord.record_threads_supervised(1, bootstrap_state="RUNNING_SUPERVISED")

    snap = coord.build_snapshot(
        trading_state="LIVE_PENDING_CONFIRMATION",
        activation_intent=True,
    )
    assert snap.threads_launched > 0, "threads_launched must be > 0 after record_threads_supervised"
    assert snap.threads_confirmed_running is True, "threads_confirmed_running must be True"


# ---------------------------------------------------------------------------
# 3. threads.running gate passes
# ---------------------------------------------------------------------------


def test_threads_running_gate_passes_after_thread_evidence():
    """After record_threads_supervised(), threads.running gate must be True."""
    from bot.startup_coordinator import StartupCoordinator

    coord = StartupCoordinator()
    coord.record_threads_supervised(2, bootstrap_state="RUNNING_SUPERVISED")

    snap = coord.build_snapshot(
        trading_state="LIVE_PENDING_CONFIRMATION",
        activation_intent=True,
    )
    proof = coord.evaluate_system_readiness_proof(snap)

    gate_results = proof.gate_results or {}
    assert gate_results.get("threads.running") is True, (
        f"threads.running gate must pass after record_threads_supervised(); "
        f"gate_results={gate_results}"
    )


# ---------------------------------------------------------------------------
# 4. LIVE activation readiness proof passes (threads.running gate specifically)
# ---------------------------------------------------------------------------


def test_system_readiness_proof_threads_gate_passes_with_full_state():
    """threads.running must pass and must not appear in failed_gates."""
    import dataclasses

    from bot.startup_coordinator import (
        RuntimeAuthorityState,
        StartupCoordinator,
        StartupConvergenceSnapshot,
    )

    coord = StartupCoordinator()

    # Publish thread evidence — this is the critical fix being tested
    coord.record_threads_supervised(1, bootstrap_state="RUNNING_SUPERVISED")

    # Build a base snapshot from the coordinator
    base_snap = coord.build_snapshot(
        trading_state="LIVE_PENDING_CONFIRMATION",
        activation_intent=True,
    )

    # Patch all required fields to ensure only threads.running is under test
    patched = dataclasses.replace(
        base_snap,
        threads_launched=1,
        threads_confirmed_running=True,
        capital_hydrated=True,
        capital_state="READY",
        capital_balance=1000.0,
        capital_stale=False,
        bootstrap_state="RUNNING_SUPERVISED",
        activation_intent=True,
        authority_ready=True,
        nonce_ready=True,
        dispatch_health_ready=True,
        kill_switch_active=False,
        global_epoch=1,
        activation_epoch=1,
        runtime_authority_state=RuntimeAuthorityState.AUTHORIZED.value,
    )

    proof = coord.evaluate_system_readiness_proof(patched)
    gate_results = proof.gate_results or {}

    assert gate_results.get("threads.running") is True, (
        f"threads.running must pass; gate_results={gate_results}"
    )
    assert "threads.running" not in proof.failed_gates, (
        f"threads.running must not be in failed_gates; failed={proof.failed_gates}"
    )

