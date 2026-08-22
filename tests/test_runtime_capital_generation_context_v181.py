from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from bot import capital_authority as ca
from bot import capital_publication_liveness_v142_patch as v142
from bot import runtime_capital_generation_context_v181_patch as v181
from bot import runtime_release_manifest_patch as manifest


def _install_chain(monkeypatch):
    calls: list[tuple[object, str]] = []

    def base_publish(self, snapshot, writer_id):
        calls.append((snapshot, writer_id))
        return str(writer_id) == str(self._AUTHORIZED_WRITER_ID)

    monkeypatch.setattr(ca.CapitalAuthority, "publish_snapshot", base_publish)
    monkeypatch.setattr(v142, "_ACTIVE_GENERATION", 18)
    monkeypatch.setattr(v142, "_NEXT_GENERATION", 18)
    monkeypatch.setattr(v142, "_ROLLOVER_OCCURRED", True)
    try:
        delattr(v142._LOCAL, "refresh_generation")
    except AttributeError:
        pass

    assert v142._patch_publication_generation_fence()
    assert v181._patch_publication_context()
    return calls


def _authority():
    authority = object.__new__(ca.CapitalAuthority)
    authority._AUTHORIZED_WRITER_ID = "mabm_capital_refresh_coordinator"
    return authority


def test_current_canonical_worker_can_restore_missing_generation(monkeypatch) -> None:
    calls = _install_chain(monkeypatch)
    coordinator = SimpleNamespace(
        _nija_v142_flight_thread=threading.current_thread(),
        _nija_v142_flight_generation=18,
        _nija_v142_flight_timed_out=False,
        _in_flight=True,
    )
    monkeypatch.setattr(
        v142,
        "_canonical_manager",
        lambda: SimpleNamespace(_capital_coordinator=coordinator),
    )

    authority = _authority()
    snapshot = SimpleNamespace(real_capital=347.23)

    assert authority.publish_snapshot(snapshot, "mabm_capital_refresh_coordinator") is True
    assert calls == [(snapshot, "mabm_capital_refresh_coordinator")]
    assert not hasattr(v142._LOCAL, "refresh_generation")


def test_retired_generation_remains_rejected(monkeypatch) -> None:
    calls = _install_chain(monkeypatch)
    coordinator = SimpleNamespace(
        _nija_v142_flight_thread=threading.current_thread(),
        _nija_v142_flight_generation=17,
        _nija_v142_flight_timed_out=False,
        _in_flight=True,
    )
    monkeypatch.setattr(
        v142,
        "_canonical_manager",
        lambda: SimpleNamespace(_capital_coordinator=coordinator),
    )

    assert _authority().publish_snapshot(
        SimpleNamespace(), "mabm_capital_refresh_coordinator"
    ) is False
    assert calls == []


def test_timed_out_current_generation_remains_rejected(monkeypatch) -> None:
    calls = _install_chain(monkeypatch)
    coordinator = SimpleNamespace(
        _nija_v142_flight_thread=threading.current_thread(),
        _nija_v142_flight_generation=18,
        _nija_v142_flight_timed_out=True,
        _in_flight=True,
    )
    monkeypatch.setattr(
        v142,
        "_canonical_manager",
        lambda: SimpleNamespace(_capital_coordinator=coordinator),
    )

    assert _authority().publish_snapshot(
        SimpleNamespace(), "mabm_capital_refresh_coordinator"
    ) is False
    assert calls == []


def test_detached_or_unknown_worker_remains_rejected(monkeypatch) -> None:
    calls = _install_chain(monkeypatch)
    coordinator = SimpleNamespace(
        _nija_v142_flight_thread=threading.Thread(target=lambda: None),
        _nija_v142_flight_generation=18,
        _nija_v142_flight_timed_out=False,
        _in_flight=True,
    )
    monkeypatch.setattr(
        v142,
        "_canonical_manager",
        lambda: SimpleNamespace(_capital_coordinator=coordinator),
    )

    assert _authority().publish_snapshot(
        SimpleNamespace(), "mabm_capital_refresh_coordinator"
    ) is False
    assert calls == []


def test_unauthorized_writer_is_not_promoted(monkeypatch) -> None:
    calls = _install_chain(monkeypatch)
    coordinator = SimpleNamespace(
        _nija_v142_flight_thread=threading.current_thread(),
        _nija_v142_flight_generation=18,
        _nija_v142_flight_timed_out=False,
        _in_flight=True,
    )
    monkeypatch.setattr(
        v142,
        "_canonical_manager",
        lambda: SimpleNamespace(_capital_coordinator=coordinator),
    )

    snapshot = SimpleNamespace()
    assert _authority().publish_snapshot(snapshot, "not-authorized") is False
    assert calls == [(snapshot, "not-authorized")]
    assert not hasattr(v142._LOCAL, "refresh_generation")


def test_exact_v181_detection_ignores_wraps_copied_marker(monkeypatch) -> None:
    _install_chain(monkeypatch)
    exact = v181._find_exact_v181_publication_wrapper(ca.CapitalAuthority.publish_snapshot)
    assert exact is not None

    def unrelated_outer(*args, **kwargs):
        return exact(*args, **kwargs)

    unrelated_outer.__name__ = "publish_snapshot_v181"
    setattr(unrelated_outer, v181._PATCH_ATTR, True)
    setattr(unrelated_outer, "__wrapped__", exact)
    assert v181._is_exact_v181_publication_wrapper(unrelated_outer) is False
    assert v181._find_exact_v181_publication_wrapper(unrelated_outer) is exact


def test_canonical_preterminal_sync_generation_is_borrowed_only_after_rollover(monkeypatch) -> None:
    coordinator = SimpleNamespace(
        _in_flight=False,
        _nija_v142_flight_timed_out=False,
        _nija_v142_flight_thread=None,
    )
    monkeypatch.setattr(v142, "_ACTIVE_GENERATION", 23)
    monkeypatch.setattr(v142, "_NEXT_GENERATION", 23)
    monkeypatch.setattr(v142, "_ROLLOVER_OCCURRED", True)
    monkeypatch.setattr(v142, "_canonical_manager", lambda: SimpleNamespace(_capital_coordinator=coordinator))
    monkeypatch.setattr(v142, "_runtime_terminal", lambda _coordinator: False)
    try:
        delattr(v142._LOCAL, "refresh_generation")
    except AttributeError:
        pass

    generation, reason, local = v181._canonical_sync_generation_v187(coordinator)
    assert generation == 23
    assert reason == "canonical_preterminal_sync_after_rollover"
    assert local is v142._LOCAL

    monkeypatch.setattr(v142, "_runtime_terminal", lambda _coordinator: True)
    generation, reason, _ = v181._canonical_sync_generation_v187(coordinator)
    assert generation is None
    assert reason == "runtime_terminal_worker_path"


def test_effective_kraken_readiness_requires_current_complete_canonical_truth(monkeypatch) -> None:
    status = SimpleNamespace(
        accepted=True,
        stale=False,
        expiry=datetime.now(timezone.utc) + timedelta(seconds=60),
    )
    snapshot = SimpleNamespace(
        real_capital=342.28,
        broker_count=3,
        expected_brokers=3,
        broker_balances={"kraken": 247.16, "coinbase": 95.12, "okx": 0.0},
    )
    authority = SimpleNamespace(
        get_snapshot_publication_status=lambda: status,
        get_typed_snapshot=lambda: snapshot,
        expected_brokers=3,
    )
    monkeypatch.setattr(ca, "get_capital_authority", lambda: authority)

    kraken = SimpleNamespace(
        connected=True,
        get_last_pricing_coverage=lambda: 1.0,
    )
    manager = SimpleNamespace(
        _platform_brokers={SimpleNamespace(value="kraken"): kraken},
        _capital_bootstrap_fsm=SimpleNamespace(state=SimpleNamespace(value="READY")),
    )

    from bot import runtime_kraken_aggregate_valuation_confidence_v184_patch as v184
    monkeypatch.setattr(v184, "_aggregate_proof_status", lambda _broker: (True, "authenticated_tradebalance_equity", 247.16, 1.0))

    valid, detail = v181._validated_effective_kraken_readiness_v187(manager)
    assert valid is True
    assert detail["real_capital"] == 342.28
    assert detail["kraken_capital"] == 247.16
    assert detail["effective_coverage"] == 1.0

    status.stale = True
    valid, detail = v181._validated_effective_kraken_readiness_v187(manager)
    assert valid is False
    assert detail["reason"] == "canonical_publication_not_current"


def test_release_manifest_and_safety_environment_are_preserved(monkeypatch) -> None:
    monkeypatch.setattr(manifest, "_REQUIRED_FLAGS", dict(manifest._REQUIRED_FLAGS))
    monkeypatch.setenv("NIJA_EMERGENCY_STOP", "1")
    monkeypatch.setenv("NIJA_NONCE_READY", "0")
    monkeypatch.setenv("NIJA_RUNTIME_EXECUTION_AUTHORITY", "0")

    assert v181._patch_release_manifest()
    assert manifest._REQUIRED_FLAGS["runtime_capital_generation_context_v181"] == (
        "NIJA_RUNTIME_CAPITAL_GENERATION_CONTEXT_V181_READY"
    )
    assert manifest._REQUIRED_FLAGS["runtime_capital_generation_coverage_v187"] == (
        "NIJA_RUNTIME_CAPITAL_GENERATION_COVERAGE_V187_READY"
    )
    assert v181._find_v142_publication_wrapper(lambda: None) is None

    assert __import__("os").environ["NIJA_EMERGENCY_STOP"] == "1"
    assert __import__("os").environ["NIJA_NONCE_READY"] == "0"
    assert __import__("os").environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] == "0"
