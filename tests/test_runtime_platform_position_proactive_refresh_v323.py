from __future__ import annotations

from types import ModuleType, SimpleNamespace

from bot import runtime_platform_position_sync_isolation_v320_patch as v320


def _fake_v285(*, age_s: float, original_candidates=None):
    module = ModuleType("fake_v285")
    broker = SimpleNamespace(connected=True)
    candidates = list(original_candidates or [])

    module._platform_candidates = lambda _manager: list(candidates)
    module._snapshot_status = lambda _broker: (
        True,
        "authoritative_position_snapshot_current",
        (),
        age_s,
        7,
    )
    module._refresh_interval_s = lambda: 49.5
    module._connected = lambda item: bool(getattr(item, "connected", False))
    module._label = lambda value: str(value).lower()
    return module, broker


def test_v323_adds_current_platform_snapshot_at_refresh_interval() -> None:
    module, broker = _fake_v285(age_s=50.0)
    manager = SimpleNamespace(platform_brokers={"coinbase": broker})

    assert v320._patch_v285_platform_refresh(module) is True
    assert module._platform_candidates(manager) == [("coinbase", broker)]


def test_v323_does_not_refresh_young_current_snapshot() -> None:
    module, broker = _fake_v285(age_s=40.0)
    manager = SimpleNamespace(platform_brokers={"coinbase": broker})

    assert v320._patch_v285_platform_refresh(module) is True
    assert module._platform_candidates(manager) == []


def test_v323_preserves_existing_unready_candidate_without_duplication() -> None:
    broker = SimpleNamespace(connected=True)
    module, _ = _fake_v285(age_s=70.0, original_candidates=[("kraken", broker)])
    manager = SimpleNamespace(platform_brokers={"kraken": broker})

    assert v320._patch_v285_platform_refresh(module) is True
    assert module._platform_candidates(manager) == [("kraken", broker)]


def test_v323_does_not_include_disconnected_platform_broker() -> None:
    module, broker = _fake_v285(age_s=70.0)
    broker.connected = False
    manager = SimpleNamespace(platform_brokers={"okx": broker})

    assert v320._patch_v285_platform_refresh(module) is True
    assert module._platform_candidates(manager) == []


def test_v323_patch_is_idempotent() -> None:
    module, broker = _fake_v285(age_s=70.0)
    manager = SimpleNamespace(platform_brokers={"coinbase": broker})

    assert v320._patch_v285_platform_refresh(module) is True
    first = module._platform_candidates
    assert v320._patch_v285_platform_refresh(module) is True
    assert module._platform_candidates is first
    assert module._platform_candidates(manager) == [("coinbase", broker)]
