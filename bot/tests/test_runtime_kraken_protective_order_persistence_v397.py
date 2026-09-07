from types import SimpleNamespace

from bot import runtime_kraken_protective_order_persistence_v397_patch as v397


def test_guard_blocks_cleanup_when_any_exposure_exists(monkeypatch):
    calls = []
    fake_v380 = SimpleNamespace(_cleanup_orphans=lambda account, broker, active: calls.append((account, active)) or ("x",))
    monkeypatch.setattr(v397, "_v380", lambda: fake_v380)
    v397._EMPTY_STREAK.clear()
    assert v397.install() is True
    assert fake_v380._cleanup_orphans("platform:kraken", object(), {"ETHUSD:BTNL"}) == ()
    assert calls == []


def test_guard_requires_three_consecutive_empty_proofs(monkeypatch):
    calls = []
    fake_v380 = SimpleNamespace(_cleanup_orphans=lambda account, broker, active: calls.append(account) or ("order-1",))
    monkeypatch.setattr(v397, "_v380", lambda: fake_v380)
    v397._EMPTY_STREAK.clear()
    assert v397.install() is True
    fn = fake_v380._cleanup_orphans
    assert fn("platform:kraken", object(), set()) == ()
    assert fn("platform:kraken", object(), set()) == ()
    assert calls == []
    assert fn("platform:kraken", object(), set()) == ("order-1",)
    assert calls == ["platform:kraken"]


def test_nonempty_exposure_resets_empty_streak(monkeypatch):
    calls = []
    fake_v380 = SimpleNamespace(_cleanup_orphans=lambda account, broker, active: calls.append(account) or ("order-1",))
    monkeypatch.setattr(v397, "_v380", lambda: fake_v380)
    v397._EMPTY_STREAK.clear()
    assert v397.install() is True
    fn = fake_v380._cleanup_orphans
    assert fn("platform:kraken", object(), set()) == ()
    assert fn("platform:kraken", object(), set()) == ()
    assert fn("platform:kraken", object(), {"ETHUSD:BTNL"}) == ()
    assert fn("platform:kraken", object(), set()) == ()
    assert calls == []
