from __future__ import annotations

from types import ModuleType, SimpleNamespace

from bot import capital_refresh_reentrancy_v106_patch as v106


def _make_module(*, hydrated: bool, total: float, balances: dict[str, float] | None = None):
    module = ModuleType("test_mabm_v106")
    snapshot = SimpleNamespace(
        total_capital=total,
        broker_balances=balances or {},
    )
    authority = SimpleNamespace(
        hydrated=hydrated,
        total_capital=total,
        snapshot=snapshot,
    )
    module.get_capital_authority = lambda: authority

    class Manager:
        def __init__(self) -> None:
            self.calls = 0
            self.nested = None

        def refresh_capital_authority(self, trigger: str = "manual"):
            self.calls += 1
            if trigger == "outer":
                self.nested = self.refresh_capital_authority("nested")
            return {
                "ready": 1.0,
                "total_capital": total,
                "valid_brokers": float(len(balances or {})),
            }

    module.MultiAccountBrokerManager = Manager
    return module, Manager


def test_nested_refresh_is_suppressed_and_reuses_authoritative_snapshot():
    module, manager_cls = _make_module(
        hydrated=True,
        total=466.92,
        balances={"kraken": 226.84, "coinbase": 95.12, "okx": 144.96},
    )

    assert v106._patch_module(module) is True
    manager = manager_cls()
    outer = manager.refresh_capital_authority("outer")

    assert manager.calls == 1
    assert outer["ready"] == 1.0
    assert manager.nested["reentrant"] == 1.0
    assert manager.nested["ready"] == 1.0
    assert manager.nested["total_capital"] == 466.92
    assert manager.nested["valid_brokers"] == 3.0
    assert manager.nested["kraken_capital"] == 226.84


def test_nested_refresh_fails_closed_when_authoritative_snapshot_is_not_ready():
    module, manager_cls = _make_module(hydrated=False, total=0.0)

    assert v106._patch_module(module) is True
    manager = manager_cls()
    manager.refresh_capital_authority("outer")

    assert manager.calls == 1
    assert manager.nested["reentrant"] == 1.0
    assert manager.nested["ready"] == 0.0
    assert manager.nested["pending"] == 1.0
    assert manager.nested["total_capital"] == 0.0


def test_guard_depth_is_released_after_exception():
    module = ModuleType("test_mabm_v106_exception")
    module.get_capital_authority = lambda: SimpleNamespace(hydrated=False, total_capital=0.0)

    class Manager:
        def __init__(self) -> None:
            self.calls = 0

        def refresh_capital_authority(self, trigger: str = "manual"):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("boom")
            return {"ready": 0.0, "total_capital": 0.0, "valid_brokers": 0.0}

    module.MultiAccountBrokerManager = Manager
    assert v106._patch_module(module) is True

    manager = Manager()
    try:
        manager.refresh_capital_authority("first")
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected RuntimeError")

    result = manager.refresh_capital_authority("second")
    assert manager.calls == 2
    assert result["ready"] == 0.0
