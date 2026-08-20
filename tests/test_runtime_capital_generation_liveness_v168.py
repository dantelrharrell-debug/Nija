from __future__ import annotations

from types import SimpleNamespace

import bot.runtime_capital_generation_liveness_v168_patch as v168


class FakeThread:
    def __init__(self, name: str, alive: bool = True):
        self.name = name
        self._alive = alive

    def is_alive(self):
        return self._alive


def test_quarantine_and_absolute_limits_are_strict(monkeypatch):
    monkeypatch.setenv("NIJA_CAPITAL_RETIRED_GENERATION_QUARANTINE_MAX", "20")
    assert v168._quarantine_limit() == 2
    assert v168._absolute_runtime_thread_limit() == 3

    monkeypatch.setenv("NIJA_CAPITAL_RETIRED_GENERATION_QUARANTINE_MAX", "0")
    assert v168._quarantine_limit() == 1
    assert v168._absolute_runtime_thread_limit() == 2


def test_capacity_separates_two_retired_threads_from_empty_canonical_lane(monkeypatch):
    monkeypatch.setattr(
        v168.threading,
        "enumerate",
        lambda: [
            FakeThread("capital-runtime-refresh-v142-g57"),
            FakeThread("capital-runtime-refresh-v142-g59"),
            FakeThread("TradingLoop"),
        ],
    )
    fake_v142 = SimpleNamespace(_generation_state=lambda: (60, True))
    monkeypatch.setattr(v168, "_v142", lambda: fake_v142)

    manager = SimpleNamespace(
        _capital_coordinator=SimpleNamespace(_nija_v142_flight_generation=59)
    )
    status = v168._capacity_snapshot(manager)

    assert status["live_generations"] == [57, 59]
    assert status["retired_generations"] == [57, 59]
    assert status["active_physical_generations"] == []
    assert status["retired_count"] == 2
    assert status["absolute_limit"] == 3
    assert v168._already_generation_fenced(manager._capital_coordinator) is True


def _rollover_fixture(monkeypatch, *, live_generations: list[int], active_generation: int):
    old = SimpleNamespace(_nija_v142_flight_generation=59)
    replacement = SimpleNamespace(_nija_v142_flight_generation=0)
    manager = SimpleNamespace(_capital_coordinator=old)
    calls = {"v164": 0, "v142": 0}

    def legacy(manager_arg, *, expected_old=None, reason: str):
        calls["v142"] += 1
        assert manager_arg is manager
        assert expected_old is old
        manager._capital_coordinator = replacement
        return replacement

    def v164_wrapper(manager_arg, *, expected_old=None, reason: str):
        calls["v164"] += 1
        return old

    setattr(v164_wrapper, "_nija_runtime_capital_publication_liveness_v164", True)
    setattr(v164_wrapper, "__wrapped__", legacy)

    fake_v142 = SimpleNamespace(
        _rollover_coordinator=v164_wrapper,
        _generation_state=lambda: (active_generation, True),
    )
    fake_v164 = SimpleNamespace(
        _PATCH_ATTR="_nija_runtime_capital_publication_liveness_v164"
    )
    monkeypatch.setattr(v168, "_v142", lambda: fake_v142)
    monkeypatch.setattr(v168, "_v164", lambda: fake_v164)
    monkeypatch.setattr(
        v168.threading,
        "enumerate",
        lambda: [
            FakeThread(f"capital-runtime-refresh-v142-g{generation}")
            for generation in live_generations
        ],
    )
    return fake_v142, manager, old, replacement, calls


def test_two_retired_alive_generations_release_one_canonical_lane(monkeypatch):
    fake_v142, manager, old, replacement, calls = _rollover_fixture(
        monkeypatch,
        live_generations=[57, 59],
        active_generation=60,
    )

    assert v168._patch_rollover_capacity() is True
    result = fake_v142._rollover_coordinator(
        manager,
        expected_old=old,
        reason="coordinator_timeout_flag",
    )

    assert result is replacement
    assert manager._capital_coordinator is replacement
    assert calls == {"v164": 0, "v142": 1}


def test_three_alive_generations_block_a_fourth_worker(monkeypatch):
    fake_v142, manager, old, _replacement, calls = _rollover_fixture(
        monkeypatch,
        live_generations=[57, 59, 61],
        active_generation=62,
    )

    assert v168._patch_rollover_capacity() is True
    result = fake_v142._rollover_coordinator(
        manager,
        expected_old=old,
        reason="coordinator_timeout_flag",
    )

    assert result is old
    assert manager._capital_coordinator is old
    assert calls == {"v164": 1, "v142": 0}


def test_unfenced_current_generation_preserves_v164_policy(monkeypatch):
    fake_v142, manager, old, _replacement, calls = _rollover_fixture(
        monkeypatch,
        live_generations=[59],
        active_generation=59,
    )

    assert v168._patch_rollover_capacity() is True
    result = fake_v142._rollover_coordinator(
        manager,
        expected_old=old,
        reason="manual_probe",
    )

    assert result is old
    assert calls == {"v164": 1, "v142": 0}


def test_v167_installs_v168(monkeypatch):
    import bot.runtime_refresh_demand_v167_patch as v167

    fake_v168 = SimpleNamespace(install=lambda: True)
    real_import = v167.importlib.import_module

    def fake_import(name: str, *args, **kwargs):
        if name == "bot.runtime_capital_generation_liveness_v168_patch":
            return fake_v168
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(v167.importlib, "import_module", fake_import)
    assert v167._install_v168_generation_liveness() is True
