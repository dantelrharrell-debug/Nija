from types import SimpleNamespace

from bot import runtime_kraken_health_user_refresh_v384_patch as v384


class ConcreteKrakenBroker:
    def __init__(self):
        self.connected = True

    def _kraken_api_call(self, method, params):
        return {"error": [], "result": {}}


class DelegatingKrakenProxy:
    def __init__(self, inner):
        self._broker = inner
        self.connected = False

    # The production bug: a proxy can expose a delegated private call and still
    # not be the authoritative concrete adapter.
    def _kraken_api_call(self, method, params):
        raise Exception("stale wrapper should not own authoritative private read")


def test_deepest_known_proxy_prefers_concrete_adapter_over_delegated_wrapper():
    concrete = ConcreteKrakenBroker()
    proxy = DelegatingKrakenProxy(concrete)

    assert v384._deepest_known_proxy(proxy) is concrete


def test_deepest_known_proxy_cycle_fails_closed():
    left = SimpleNamespace()
    right = SimpleNamespace()
    left._broker = right
    right._broker = left

    assert v384._deepest_known_proxy(left) is None


def test_patch_v366_unwrap_replaces_early_stop_behavior(monkeypatch):
    concrete = ConcreteKrakenBroker()
    proxy = DelegatingKrakenProxy(concrete)
    fake_v366 = SimpleNamespace(_unwrap=lambda broker: broker)

    monkeypatch.setattr(v384, "_v366", lambda: fake_v366)

    assert v384._patch_v366_unwrap() is True
    assert fake_v366._unwrap(proxy) is concrete
    assert getattr(fake_v366._unwrap, v384._PATCH_ATTR, False) is True


def test_coverage_scope_is_outermost_and_marks_v367_contract(monkeypatch):
    observed = []

    def base_coverage(account, broker):
        observed.append((account, v384._BROKER_SCOPE.get()))
        return [], []

    fake_v366 = SimpleNamespace(margin_coverage_rows=base_coverage)
    fake_v367 = SimpleNamespace(_PATCH_ATTR="_nija_v367_kraken_margin_protection_truth")

    monkeypatch.setattr(v384, "_v366", lambda: fake_v366)
    monkeypatch.setattr(v384, "_v367", lambda: fake_v367)

    broker = ConcreteKrakenBroker()
    assert v384._ensure_coverage_scope() is True
    fake_v366.margin_coverage_rows("user:test:kraken", broker)

    assert observed == [("user:test:kraken", broker)]
    assert getattr(fake_v366.margin_coverage_rows, v384._PATCH_ATTR, False) is True
    assert getattr(fake_v366.margin_coverage_rows, fake_v367._PATCH_ATTR, False) is True


def test_v367_reassert_guard_reapplies_outer_scope(monkeypatch):
    calls = []

    def base_coverage(account, broker):
        calls.append(v384._BROKER_SCOPE.get())
        return [], []

    fake_v366 = SimpleNamespace(margin_coverage_rows=base_coverage)

    def original_patch():
        return True

    fake_v367 = SimpleNamespace(
        _PATCH_ATTR="_nija_v367_kraken_margin_protection_truth",
        _patch_v366_coverage=original_patch,
    )

    monkeypatch.setattr(v384, "_v366", lambda: fake_v366)
    monkeypatch.setattr(v384, "_v367", lambda: fake_v367)

    assert v384._patch_v367_reassert() is True
    assert fake_v367._patch_v366_coverage() is True

    broker = ConcreteKrakenBroker()
    fake_v366.margin_coverage_rows("platform:kraken", broker)
    assert calls == [broker]
