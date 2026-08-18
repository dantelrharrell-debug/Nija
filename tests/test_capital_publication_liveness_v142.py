from __future__ import annotations

import os
import threading
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from bot import capital_publication_liveness_v142_patch as v142


def test_runtime_pipeline_deadline_never_reaches_publication_ttl(monkeypatch) -> None:
    monkeypatch.setattr(v142, "_freshness_ttl_seconds", lambda: 90.0)
    monkeypatch.setattr(v142, "_fetch_budget_seconds", lambda: 45.0)
    monkeypatch.setenv("NIJA_CAPITAL_RUNTIME_PIPELINE_DEADLINE_S", "999")

    assert v142._runtime_pipeline_deadline_seconds() == 80.0
    assert v142._runtime_pipeline_deadline_seconds() < 90.0


def test_readiness_truth_keeps_hydration_and_connectivity_separate_from_freshness(monkeypatch) -> None:
    import preactivation_readiness_convergence_v16_patch as v16

    def stale_capital_proof():
        return (
            {
                "broker_connected": False,
                "balance_hydrated": False,
                "authority_ready": True,
                "capital_ready": False,
                "risk_ready": True,
                "strategy_ready": True,
                "execution_ready": True,
                "nonce_ready": True,
                "bootstrap_ready": True,
            },
            {
                "capital": {
                    "hydrated": True,
                    "stale": True,
                    "real": 240.07,
                    "registered": 2,
                }
            },
        )

    monkeypatch.setattr(v16, "_collect_proofs", stale_capital_proof)
    monkeypatch.setattr(
        v142,
        "_canonical_broker_connectivity",
        lambda: (
            True,
            {
                "reason": "ok",
                "policy": "optional",
                "registered": ["coinbase", "kraken", "okx"],
                "connected": ["coinbase", "kraken", "okx"],
            },
        ),
    )

    assert v142._patch_readiness_truth()
    proofs, details = v16._collect_proofs()

    assert proofs["broker_connected"] is True
    assert proofs["balance_hydrated"] is True
    assert proofs["capital_ready"] is False
    assert details["v142_readiness_truth"]["capital_stale"] is True


def test_retired_generation_cannot_publish_or_poison_current_status(monkeypatch) -> None:
    from bot import capital_authority as ca

    calls: list[tuple[object, str]] = []

    def permissive_publish(self, snapshot, writer_id):
        calls.append((snapshot, writer_id))
        return True

    monkeypatch.setattr(ca.CapitalAuthority, "publish_snapshot", permissive_publish)
    monkeypatch.setattr(v142, "_ACTIVE_GENERATION", 8)
    monkeypatch.setattr(v142, "_NEXT_GENERATION", 8)
    monkeypatch.setattr(v142, "_ROLLOVER_OCCURRED", True)
    v142._LOCAL.refresh_generation = 7

    assert v142._patch_publication_generation_fence()
    authority = object.__new__(ca.CapitalAuthority)
    authority._AUTHORIZED_WRITER_ID = "mabm_capital_refresh_coordinator"

    assert (
        authority.publish_snapshot(
            SimpleNamespace(),
            "mabm_capital_refresh_coordinator",
        )
        is False
    )
    assert calls == []

    delattr(v142._LOCAL, "refresh_generation")


def test_untracked_inflight_is_replaced_once_publication_expired(monkeypatch) -> None:
    from bot import capital_publication_deadline_v137_patch as v137

    now = datetime.now(timezone.utc)
    authority = SimpleNamespace(
        get_snapshot_publication_status=lambda: SimpleNamespace(
            accepted=True,
            stale=False,
            reason="accepted",
            timestamp=now - timedelta(seconds=91),
            expiry=now - timedelta(seconds=1),
        )
    )
    old = SimpleNamespace(_in_flight=True)
    replacement = SimpleNamespace(_in_flight=False)
    manager = SimpleNamespace(_capital_coordinator=old)

    monkeypatch.setattr(v142, "_authority", lambda: authority)

    def rollover(target_manager, *, expected_old=None, reason):
        assert expected_old is old
        assert "untracked" in reason
        target_manager._capital_coordinator = replacement
        return replacement

    monkeypatch.setattr(v142, "_rollover_coordinator", rollover)

    current, _meta = v137._publication_meta(authority, now=now)
    assert current is False
    assert v142._coordinator_in_flight_v142(manager) is False
    assert manager._capital_coordinator is replacement


def test_rollover_reuses_canonical_fsm_objects_and_hydration(monkeypatch) -> None:
    from bot import capital_flow_state_machine as flow

    bus = flow.get_capital_event_bus()
    boot = flow.get_capital_bootstrap_fsm()
    runtime = flow.get_capital_runtime_fsm()
    old = flow.CapitalRefreshCoordinator(bus, boot, runtime)
    old._in_flight = True
    old._nija_v142_flight_generation = 3
    old._nija_v142_flight_started_monotonic = 1.0
    old._nija_v142_flight_trigger = "stuck-test"
    old._nija_v142_flight_thread = threading.Thread(target=lambda: None)

    manager = SimpleNamespace(
        _capital_coordinator=old,
        _capital_event_bus=bus,
        _capital_bootstrap_fsm=boot,
        _capital_runtime_fsm=runtime,
    )
    monkeypatch.setattr(v142, "_authority", lambda: SimpleNamespace(is_hydrated=True))

    replacement = v142._rollover_coordinator(
        manager,
        expected_old=old,
        reason="test_stuck_runtime_refresh",
    )

    assert replacement is manager._capital_coordinator
    assert replacement is not old
    assert replacement._bus is bus
    assert replacement._boot is boot
    assert replacement._runtime is runtime
    assert replacement.balance_hydrated is True
    assert replacement.balance_hydrated_event.is_set()


def test_release_manifest_requires_v140_v141_and_v142(monkeypatch) -> None:
    from bot import runtime_release_manifest_patch as manifest

    monkeypatch.setattr(manifest, "_REQUIRED_FLAGS", dict(manifest._REQUIRED_FLAGS))
    monkeypatch.setattr(manifest, "_INSTALLERS", tuple(manifest._INSTALLERS))
    monkeypatch.setattr(manifest, "DECLARED_RELEASE_ID", str(manifest.DECLARED_RELEASE_ID))

    assert v142._patch_release_manifest()

    assert manifest.DECLARED_RELEASE_ID == "20260818-runtime-convergence-v142"
    assert manifest.RELEASE_ID == "20260818-runtime-convergence-v142"
    assert manifest._REQUIRED_FLAGS["runtime_killswitch_authority_liveness_v140"] == (
        "NIJA_RUNTIME_KILLSWITCH_AUTHORITY_LIVENESS_V140_READY"
    )
    assert manifest._REQUIRED_FLAGS["stalled_writer_capital_freshness_v141"] == (
        "NIJA_STALLED_WRITER_CAPITAL_FRESHNESS_V141_INSTALLED"
    )
    assert manifest._REQUIRED_FLAGS["capital_publication_liveness_v142"] == (
        "NIJA_CAPITAL_PUBLICATION_LIVENESS_V142_READY"
    )
    assert (
        "bot.capital_publication_liveness_v142_patch",
        "install_import_hook",
    ) in manifest._INSTALLERS


def test_liveness_patch_does_not_clear_or_grant_safety_environment(monkeypatch) -> None:
    monkeypatch.setenv("NIJA_EMERGENCY_STOP", "1")
    monkeypatch.setenv("NIJA_NONCE_READY", "0")
    monkeypatch.setenv("NIJA_RUNTIME_EXECUTION_AUTHORITY", "0")

    v142._runtime_pipeline_deadline_seconds()

    assert os.environ["NIJA_EMERGENCY_STOP"] == "1"
    assert os.environ["NIJA_NONCE_READY"] == "0"
    assert os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] == "0"
