from __future__ import annotations

from types import SimpleNamespace

import bot.runtime_capital_publication_scheduling_v165_patch as v165


def test_headroom_uses_effective_pipeline_deadline_and_cadence(monkeypatch):
    monkeypatch.setattr(v165, "_freshness_ttl_seconds", lambda: 90.0)
    monkeypatch.setattr(v165, "_effective_pipeline_deadline_seconds", lambda: 80.0)
    manager = SimpleNamespace(capital_watchdog_interval_s=10.0)

    # 80s effective coordinator deadline + 10s cadence would equal the TTL,
    # so preserve five seconds of immutable-validity margin and start at 85s.
    assert v165._required_headroom_seconds(manager) == 85.0


def test_headroom_does_not_overreserve_for_fast_pipeline(monkeypatch):
    monkeypatch.setattr(v165, "_freshness_ttl_seconds", lambda: 90.0)
    monkeypatch.setattr(v165, "_effective_pipeline_deadline_seconds", lambda: 40.0)
    manager = SimpleNamespace(capital_watchdog_interval_s=5.0)

    assert v165._required_headroom_seconds(manager) == 45.0


def test_watchdog_cadence_is_bounded():
    assert v165._watchdog_cadence_seconds(SimpleNamespace(capital_watchdog_interval_s=0.1)) == 1.0
    assert v165._watchdog_cadence_seconds(SimpleNamespace(capital_watchdog_interval_s=30.0)) == 10.0


def test_v137_headroom_patch_delegates_to_v165(monkeypatch):
    class FakeV137:
        @staticmethod
        def _refresh_headroom_seconds(manager):
            return 12.0

    fake = FakeV137()
    monkeypatch.setattr(v165, "_v137", lambda: fake)
    monkeypatch.setattr(v165, "_required_headroom_seconds", lambda manager: 77.0)

    assert v165._patch_v137_headroom() is True
    assert fake._refresh_headroom_seconds(SimpleNamespace()) == 77.0
    assert getattr(fake._refresh_headroom_seconds, v165._PATCH_ATTR, False) is True


def test_headroom_never_extends_ttl(monkeypatch):
    monkeypatch.setattr(v165, "_freshness_ttl_seconds", lambda: 60.0)
    monkeypatch.setattr(v165, "_effective_pipeline_deadline_seconds", lambda: 55.0)
    manager = SimpleNamespace(capital_watchdog_interval_s=10.0)

    assert v165._required_headroom_seconds(manager) == 55.0
