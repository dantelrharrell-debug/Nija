import os
import sys
from importlib import import_module
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from capital_authority import CapitalAuthority


class _StubBroker:
    def __init__(self, balance: float):
        self._balance = balance

    def get_account_balance(self):
        return self._balance


class _StubBrokerKey:
    def __init__(self, value: str):
        self.value = value


class _StubBrokerManager:
    def __init__(self, platform_brokers):
        self.platform_brokers = platform_brokers
        self.refresh_calls = 0

    def refresh_registry(self):
        self.refresh_calls += 1


def _patch_get_broker_manager(stub_manager: _StubBrokerManager):
    patchers = []
    target_modules = ("bot.multi_account_broker_manager", "multi_account_broker_manager")
    for module_name in target_modules:
        try:
            import_module(module_name)
            patcher = patch(f"{module_name}.get_broker_manager", return_value=stub_manager)
            patcher.start()
            patchers.append(patcher)
        except ModuleNotFoundError:
            continue
    return patchers


def check_refresh_hydrates_from_registry_when_broker_map_empty():
    manager = _StubBrokerManager(
        {
            _StubBrokerKey("kraken"): _StubBroker(123.45),
            "coinbase": _StubBroker(67.89),
        }
    )
    authority = CapitalAuthority()
    patchers = _patch_get_broker_manager(manager)
    try:
        authority.refresh({})
    finally:
        for patcher in patchers:
            patcher.stop()

    assert manager.refresh_calls == 1
    assert authority.get_raw_per_broker("kraken") == 123.45
    assert authority.get_raw_per_broker("coinbase") == 67.89


def check_refresh_hydration_skips_none_brokers():
    manager = _StubBrokerManager(
        {
            _StubBrokerKey("kraken"): None,
            "coinbase": _StubBroker(50.0),
        }
    )
    authority = CapitalAuthority()
    patchers = _patch_get_broker_manager(manager)
    try:
        authority.refresh({})
    finally:
        for patcher in patchers:
            patcher.stop()

    assert authority.get_raw_per_broker("kraken") == 0.0
    assert authority.get_raw_per_broker("coinbase") == 50.0


def check_refresh_prefers_explicit_broker_map_over_registry_hydration():
    manager = _StubBrokerManager({_StubBrokerKey("kraken"): _StubBroker(999.0)})
    authority = CapitalAuthority()
    patchers = _patch_get_broker_manager(manager)
    try:
        authority.refresh({"coinbase": _StubBroker(25.0)})
    finally:
        for patcher in patchers:
            patcher.stop()

    assert authority.get_raw_per_broker("coinbase") == 25.0
    assert authority.get_raw_per_broker("kraken") == 0.0


if __name__ == "__main__":
    check_refresh_hydrates_from_registry_when_broker_map_empty()
    check_refresh_hydration_skips_none_brokers()
    check_refresh_prefers_explicit_broker_map_over_registry_hydration()
    print("✅ capital_authority_refresh_hydration_checks passed")
