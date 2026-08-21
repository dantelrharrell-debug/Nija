from __future__ import annotations

import threading
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


def test_release_manifest_and_safety_environment_are_preserved(monkeypatch) -> None:
    monkeypatch.setattr(manifest, "_REQUIRED_FLAGS", dict(manifest._REQUIRED_FLAGS))
    monkeypatch.setenv("NIJA_EMERGENCY_STOP", "1")
    monkeypatch.setenv("NIJA_NONCE_READY", "0")
    monkeypatch.setenv("NIJA_RUNTIME_EXECUTION_AUTHORITY", "0")

    assert v181._patch_release_manifest()
    assert manifest._REQUIRED_FLAGS["runtime_capital_generation_context_v181"] == (
        "NIJA_RUNTIME_CAPITAL_GENERATION_CONTEXT_V181_READY"
    )
    assert v181._find_v142_publication_wrapper(lambda: None) is None

    assert __import__("os").environ["NIJA_EMERGENCY_STOP"] == "1"
    assert __import__("os").environ["NIJA_NONCE_READY"] == "0"
    assert __import__("os").environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] == "0"
