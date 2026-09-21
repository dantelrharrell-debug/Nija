from types import SimpleNamespace

from bot import runtime_live_safety_convergence_v404_patch as v404


def test_v422_refresh_tick_requires_exact_writer_proof(monkeypatch):
    calls = []

    fake_v86 = SimpleNamespace(
        _writer_proof=lambda: (False, "writer_not_current"),
    )
    fake_v285 = SimpleNamespace(
        _canonical_manager=lambda: object(),
        _refresh_one_user_v390=lambda _manager: calls.append("refresh") or "unexpected",
    )

    def fake_import(name):
        if name == "bot.kraken_all_account_supervision_v86":
            return fake_v86
        if name == "bot.runtime_authoritative_position_coverage_v285_patch":
            return fake_v285
        raise AssertionError(name)

    monkeypatch.setattr(v404.importlib, "import_module", fake_import)

    assert v404._user_refresh_liveness_tick_v422() == "writer_unready:writer_not_current"
    assert calls == []


def test_v422_refresh_tick_dispatches_existing_v390_path_only(monkeypatch):
    manager = object()
    calls = []

    fake_v86 = SimpleNamespace(
        _writer_proof=lambda: (True, "exact_writer_renewal_proof"),
    )
    fake_v285 = SimpleNamespace(
        _canonical_manager=lambda: manager,
        _refresh_one_user_v390=lambda observed: calls.append(observed)
        or "user:daivon_frazier:kraken:refresh_dispatched",
    )

    def fake_import(name):
        if name == "bot.kraken_all_account_supervision_v86":
            return fake_v86
        if name == "bot.runtime_authoritative_position_coverage_v285_patch":
            return fake_v285
        raise AssertionError(name)

    monkeypatch.setattr(v404.importlib, "import_module", fake_import)

    result = v404._user_refresh_liveness_tick_v422()
    assert result == "user:daivon_frazier:kraken:refresh_dispatched"
    assert calls == [manager]
