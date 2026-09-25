from __future__ import annotations

from types import SimpleNamespace

from bot import runtime_liveness_position_sync_v431_patch as v431


class _Thread:
    def __init__(self, alive: bool):
        self._alive = alive

    def is_alive(self) -> bool:
        return self._alive


def test_v431_blocks_rollover_while_old_runtime_worker_is_alive(monkeypatch):
    old = SimpleNamespace(_nija_v142_flight_thread=_Thread(True))
    manager = SimpleNamespace(_capital_coordinator=old)
    calls = []

    def original(manager, *, expected_old=None, reason):
        calls.append((manager, expected_old, reason))
        return "replacement"

    fake_v142 = SimpleNamespace(_rollover_coordinator=original)
    monkeypatch.setattr(v431.importlib, "import_module", lambda name: fake_v142)

    assert v431._patch_capital_single_generation() is True
    result = fake_v142._rollover_coordinator(
        manager, expected_old=old, reason="timeout"
    )

    assert result is old
    assert calls == []


def test_v431_allows_existing_rollover_after_worker_unwinds(monkeypatch):
    old = SimpleNamespace(_nija_v142_flight_thread=_Thread(False))
    manager = SimpleNamespace(_capital_coordinator=old)

    def original(manager, *, expected_old=None, reason):
        return "replacement"

    fake_v142 = SimpleNamespace(_rollover_coordinator=original)
    monkeypatch.setattr(v431.importlib, "import_module", lambda name: fake_v142)

    assert v431._patch_capital_single_generation() is True
    assert (
        fake_v142._rollover_coordinator(
            manager, expected_old=old, reason="owner_dead"
        )
        == "replacement"
    )


def test_v431_position_recovery_uses_existing_v108_dispatch(monkeypatch):
    manager = object()
    seen = {}

    def dispatch(received, *, trigger):
        seen["manager"] = received
        seen["trigger"] = trigger
        return 1

    fake_v108 = SimpleNamespace(dispatch_platform_position_sync=dispatch)
    monkeypatch.setattr(v431, "_canonical_manager", lambda: manager)
    monkeypatch.setattr(
        v431.importlib,
        "import_module",
        lambda name: fake_v108 if name == "bot.platform_position_sync_v108_patch" else None,
    )

    assert v431._position_recovery_pulse() == 1
    assert seen == {"manager": manager, "trigger": "runtime_liveness_v431"}


def test_v431_position_recovery_fails_closed_without_manager(monkeypatch):
    monkeypatch.setattr(v431, "_canonical_manager", lambda: None)
    assert v431._position_recovery_pulse() == 0
