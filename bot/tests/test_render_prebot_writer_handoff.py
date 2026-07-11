from __future__ import annotations

import prebot_writer_authority_fail_closed as guard


def _reset_env(monkeypatch) -> None:
    for name in (
        "NIJA_RUNTIME_EXECUTION_AUTHORITY",
        "NIJA_RUNTIME_TRADING_STATE",
        "NIJA_WRITER_LEASE_ACQUIRED",
        "NIJA_WRITER_HEARTBEAT_ACTIVE",
        "NIJA_PREBOT_WRITER_AUTHORITY_READY",
        "NIJA_PREBOT_WRITER_AUTHORITY_DEFERRED",
        "NIJA_PREBOT_WRITER_AUTHORITY_DEFER_MARKER",
    ):
        monkeypatch.delenv(name, raising=False)


def test_render_pth_defers_without_acquiring_or_granting_authority(monkeypatch) -> None:
    _reset_env(monkeypatch)
    calls: list[str] = []
    monkeypatch.setattr(guard.bootstrap, "_target_process", lambda: True)
    monkeypatch.setattr(guard.bootstrap, "_is_render_runtime", lambda: True)
    monkeypatch.setattr(
        guard.bootstrap,
        "install",
        lambda: calls.append("acquire") or None,
    )

    assert guard.install(defer_if_render=True) is None

    assert calls == []
    assert guard.os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] == "0"
    assert guard.os.environ["NIJA_RUNTIME_TRADING_STATE"] == "OFF"
    assert guard.os.environ["NIJA_WRITER_LEASE_ACQUIRED"] == "0"
    assert guard.os.environ["NIJA_PREBOT_WRITER_AUTHORITY_READY"] == "0"
    assert guard.os.environ["NIJA_PREBOT_WRITER_AUTHORITY_DEFERRED"] == "1"
    assert guard.os.environ["NIJA_PREBOT_WRITER_AUTHORITY_DEFER_MARKER"] == "20260711a"


def test_source_bootstrap_call_acquires_after_render_pth_deferral(monkeypatch) -> None:
    _reset_env(monkeypatch)
    calls: list[str] = []
    monkeypatch.setattr(guard.bootstrap, "_target_process", lambda: True)
    monkeypatch.setattr(guard.bootstrap, "_is_render_runtime", lambda: True)
    monkeypatch.setattr(
        guard.bootstrap,
        "install",
        lambda: calls.append("acquire") or None,
    )

    guard.install(defer_if_render=True)
    guard.install()

    assert calls == ["acquire"]


def test_non_render_provider_keeps_early_acquisition(monkeypatch) -> None:
    _reset_env(monkeypatch)
    calls: list[str] = []
    monkeypatch.setattr(guard.bootstrap, "_target_process", lambda: True)
    monkeypatch.setattr(guard.bootstrap, "_is_render_runtime", lambda: False)
    monkeypatch.setattr(
        guard.bootstrap,
        "install",
        lambda: calls.append("acquire") or None,
    )

    guard.install(defer_if_render=True)

    assert calls == ["acquire"]
