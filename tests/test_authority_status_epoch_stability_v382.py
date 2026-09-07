from __future__ import annotations

from bot import authority_status_epoch_stability_v382_patch as patch
from bot.startup_coordinator import StartupCoordinator, StartupCoordinatorState


def _prime_live_commit(coordinator: StartupCoordinator) -> None:
    coordinator.reset_for_testing()
    with coordinator._lock:
        coordinator._runtime.coordinator_state = StartupCoordinatorState.LIVE_COMMITTED
        coordinator._runtime.authority_ready = True
        coordinator._runtime.authority_status = {"source": "authority_heartbeat"}
        coordinator._runtime.authority_version = 7
        coordinator._runtime.global_epoch = 11
        coordinator._runtime.last_committed_snapshot_version = 425
        coordinator._runtime._activation_committed = True
        coordinator._runtime._last_commit_fingerprint = ("proof", 425)


def test_status_metadata_change_preserves_live_commit() -> None:
    original = StartupCoordinator.record_authority
    try:
        assert patch._patch_startup_coordinator() is True
        coordinator = StartupCoordinator()
        _prime_live_commit(coordinator)

        coordinator.record_authority(
            ready=True,
            status={"current_state": "LIVE_ACTIVE"},
        )

        assert coordinator._runtime.authority_ready is True
        assert coordinator._runtime.authority_status == {"current_state": "LIVE_ACTIVE"}
        assert coordinator._runtime.authority_version == 8
        assert coordinator._runtime.global_epoch == 11
        assert coordinator._runtime.last_committed_snapshot_version == 425
        assert coordinator._runtime._activation_committed is True
        assert coordinator._runtime._last_commit_fingerprint == ("proof", 425)
    finally:
        StartupCoordinator.record_authority = original


def test_real_authority_loss_still_revokes_commit() -> None:
    original = StartupCoordinator.record_authority
    try:
        assert patch._patch_startup_coordinator() is True
        coordinator = StartupCoordinator()
        _prime_live_commit(coordinator)

        coordinator.record_authority(
            ready=False,
            status={"source": "authority_heartbeat", "reason": "lease_lost"},
        )

        assert coordinator._runtime.authority_ready is False
        assert coordinator._runtime.authority_version == 8
        assert coordinator._runtime.global_epoch == 12
        assert coordinator._runtime.last_committed_snapshot_version == 0
        assert coordinator._runtime._activation_committed is False
        assert coordinator._runtime._last_commit_fingerprint is None
    finally:
        StartupCoordinator.record_authority = original
