from __future__ import annotations

from bot import production_runtime_convergence_v88_patch as v88


def test_critical_liveness_monitor_starts_before_supervision(monkeypatch) -> None:
    events: list[str] = []

    class FakeThread:
        def __init__(self, *, target, name: str, daemon: bool) -> None:
            self.target = target
            self.name = name
            self.daemon = daemon

        def start(self) -> None:
            events.append(f"thread:{self.name}")

    monkeypatch.setattr(v88.threading, "Thread", FakeThread)
    monkeypatch.setattr(v88, "_install_stale_startup_log_filter", lambda: events.append("filter"))
    monkeypatch.setattr(v88, "_install_kraken_user_supervision", lambda: events.append("supervision") or True)
    monkeypatch.setattr(v88, "_try_patch_loaded", lambda: events.append("patch_loaded") or True)
    monkeypatch.setattr(v88, "_MONITOR_STARTED", False)
    monkeypatch.setattr(v88, "_CRITICAL_LIVENESS_MONITOR_STARTED", False)

    assert v88.install_import_hook() is True

    assert events.index("thread:CriticalKrakenLivenessV420") < events.index("supervision")
    assert events.index("supervision") < events.index("thread:ProductionRuntimeConvergenceV88")
