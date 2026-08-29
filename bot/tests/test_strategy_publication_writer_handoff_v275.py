from types import SimpleNamespace

import bot.runtime_heartbeat_marker_convergence_v238_patch as v238


def test_install_time_rearm_does_not_arm_publication(monkeypatch):
    calls = {"start": 0}

    publication = SimpleNamespace(
        start_monitor=lambda: calls.__setitem__("start", calls["start"] + 1) or True
    )
    v203 = SimpleNamespace(
        _already_published_strategy=lambda _publication: None,
        _ensure_heartbeat_scheduler=lambda _strategy: True,
    )

    def fake_import(name):
        if name == "bot.runtime_existing_strategy_heartbeat_rearm_v203_patch":
            return v203
        if name == "bot.strategy_publication_patch":
            return publication
        raise AssertionError(name)

    monkeypatch.setattr(v238.importlib, "import_module", fake_import)

    ready, detail = v238._rearm_genuine_heartbeat()

    assert ready is False
    assert detail == "strategy_not_published"
    assert calls["start"] == 0


def test_writer_rearm_arms_existing_publication_monitor(monkeypatch):
    calls = {"start": 0}

    def start_monitor():
        calls["start"] += 1
        return True

    publication = SimpleNamespace(start_monitor=start_monitor)
    v203 = SimpleNamespace(
        _already_published_strategy=lambda _publication: None,
        _ensure_heartbeat_scheduler=lambda _strategy: True,
    )

    def fake_import(name):
        if name == "bot.runtime_existing_strategy_heartbeat_rearm_v203_patch":
            return v203
        if name == "bot.strategy_publication_patch":
            return publication
        raise AssertionError(name)

    monkeypatch.setattr(v238.importlib, "import_module", fake_import)

    ready, detail = v238._rearm_genuine_heartbeat(allow_publication_arm=True)

    assert ready is False
    assert detail == "strategy_not_published:publication_monitor_armed"
    assert calls["start"] == 1


def test_existing_strategy_rearms_scheduler_without_starting_publication(monkeypatch):
    strategy = object()
    calls = {"ensure": 0, "start": 0}

    publication = SimpleNamespace(
        start_monitor=lambda: calls.__setitem__("start", calls["start"] + 1) or True
    )

    def ensure(candidate):
        assert candidate is strategy
        calls["ensure"] += 1
        return True

    v203 = SimpleNamespace(
        _already_published_strategy=lambda _publication: strategy,
        _ensure_heartbeat_scheduler=ensure,
    )

    def fake_import(name):
        if name == "bot.runtime_existing_strategy_heartbeat_rearm_v203_patch":
            return v203
        if name == "bot.strategy_publication_patch":
            return publication
        raise AssertionError(name)

    monkeypatch.setattr(v238.importlib, "import_module", fake_import)

    ready, detail = v238._rearm_genuine_heartbeat(allow_publication_arm=True)

    assert ready is True
    assert detail == "scheduler_alive"
    assert calls["ensure"] == 1
    assert calls["start"] == 0


def test_publication_start_failure_stays_fail_closed(monkeypatch):
    publication = SimpleNamespace(start_monitor=lambda: False)
    v203 = SimpleNamespace(
        _already_published_strategy=lambda _publication: None,
        _ensure_heartbeat_scheduler=lambda _strategy: True,
    )

    def fake_import(name):
        if name == "bot.runtime_existing_strategy_heartbeat_rearm_v203_patch":
            return v203
        if name == "bot.strategy_publication_patch":
            return publication
        raise AssertionError(name)

    monkeypatch.setattr(v238.importlib, "import_module", fake_import)

    ready, detail = v238._rearm_genuine_heartbeat(allow_publication_arm=True)

    assert ready is False
    assert detail == "strategy_not_published:publication_monitor_not_armed"
