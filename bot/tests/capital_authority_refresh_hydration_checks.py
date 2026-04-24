import os
import sys
import time
from importlib import import_module
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from capital_authority import CapitalAuthority, STARTUP_LOCK, CAPITAL_HYDRATED_EVENT, reset_capital_authority_singleton


def _reset_state():
    """Reset module-level singleton and startup lock between tests."""
    reset_capital_authority_singleton(clear_disk_cache=True)


class _StubBroker:
    def __init__(self, balance: float):
        self._balance = balance

    def get_account_balance(self):
        return self._balance


class _StubBrokerKey:
    def __init__(self, value: str):
        self.value = value


class _StubBrokerManagerBootstrap:
    """Stub that simulates the bootstrap startup window (no primary hydration)."""

    def __init__(self, platform_brokers):
        self.platform_brokers = platform_brokers
        self.refresh_calls = 0
        # Active startup window so fallback-hydration assertions are not fatal.
        self._capital_bootstrap_barrier_started_at = time.monotonic()
        self.capital_startup_invariant_timeout_s = 60.0

    def has_registered_sources(self) -> bool:
        # Return False to trigger the refresh_registry() fallback-hydration path.
        return False

    def refresh_registry(self):
        self.refresh_calls += 1


class _StubBrokerManagerReady:
    """Stub that simulates a fully-ready broker manager (primary hydration done)."""

    def __init__(self, platform_brokers):
        self.platform_brokers = platform_brokers
        # No active startup window.
        self._capital_bootstrap_barrier_started_at = None
        self.capital_startup_invariant_timeout_s = 0.0

    def has_registered_sources(self) -> bool:
        # Return True to skip the fallback-hydration path and signal that the
        # registry is already fully hydrated.
        return True

    def refresh_registry(self):
        pass  # not called on the primary path


def _patch_get_broker_manager(stub_manager):
    patchers = []
    target_modules = ("bot.multi_account_broker_manager", "multi_account_broker_manager")
    for module_name in target_modules:
        try:
            import_module(module_name)
        except ModuleNotFoundError:
            continue
        patcher = patch(f"{module_name}.get_broker_manager", return_value=stub_manager)
        try:
            patcher.start()
            patchers.append(patcher)
        except Exception:
            for active in patchers:
                active.stop()
            raise
    return patchers


def check_refresh_hydrates_from_registry_when_broker_map_empty():
    """During the startup window, an empty broker_map triggers refresh_registry()
    then defers (returns early) — balances remain zero until sources are available."""
    _reset_state()
    manager = _StubBrokerManagerBootstrap(
        {
            _StubBrokerKey("kraken"): _StubBroker(123.45),
            "coinbase": _StubBroker(67.89),
        }
    )
    authority = CapitalAuthority()
    patchers = _patch_get_broker_manager(manager)
    try:
        # _bypass_startup_lock=True: unit tests exercise the internal refresh
        # logic directly; bypassing the startup lock is correct here.
        authority.refresh({}, _bypass_startup_lock=True)
    finally:
        for patcher in patchers:
            patcher.stop()

    # Verify refresh_registry() was invoked BEFORE the startup-window early
    # return (proving the hydration attempt happens regardless of deferral).
    assert manager.refresh_calls == 1, (
        f"Expected refresh_registry() to be called exactly once before early return; "
        f"got {manager.refresh_calls}"
    )
    # Balances remain zero: CA returned early (startup-window deferral) before
    # iterating the effective_broker_map — the registry was queried but no
    # balance was fetched or stored.
    assert authority.get_raw_per_broker("kraken") == 0.0
    assert authority.get_raw_per_broker("coinbase") == 0.0


def check_refresh_hydration_skips_none_brokers():
    """None entries in the broker_map are skipped; non-None entries are fetched."""
    _reset_state()
    manager = _StubBrokerManagerReady(
        {
            _StubBrokerKey("kraken"): None,
            "coinbase": _StubBroker(50.0),
        }
    )
    authority = CapitalAuthority()
    patchers = _patch_get_broker_manager(manager)
    try:
        # Pass broker_map directly with the same entries as the registry.
        authority.refresh(
            {_StubBrokerKey("kraken"): None, "coinbase": _StubBroker(50.0)},
            _bypass_startup_lock=True,
        )
    finally:
        for patcher in patchers:
            patcher.stop()

    assert authority.get_raw_per_broker("kraken") == 0.0
    assert authority.get_raw_per_broker("coinbase") == 50.0


def check_refresh_prefers_explicit_broker_map_over_registry_hydration():
    """Explicit broker_map is used as-is; registry brokers NOT in the map are excluded."""
    _reset_state()
    manager = _StubBrokerManagerReady({_StubBrokerKey("kraken"): _StubBroker(999.0)})
    authority = CapitalAuthority()
    patchers = _patch_get_broker_manager(manager)
    try:
        authority.refresh({"coinbase": _StubBroker(25.0)}, _bypass_startup_lock=True)
    finally:
        for patcher in patchers:
            patcher.stop()

    assert authority.get_raw_per_broker("coinbase") == 25.0
    assert authority.get_raw_per_broker("kraken") == 0.0


def check_refresh_hydrates_zero_balance():
    """A refresh with confirmed zero balances should hydrate the authority."""
    _reset_state()
    manager = _StubBrokerManagerReady({"coinbase": _StubBroker(0.0)})
    authority = CapitalAuthority()
    patchers = _patch_get_broker_manager(manager)
    try:
        authority.refresh({"coinbase": _StubBroker(0.0)}, _bypass_startup_lock=True)
    finally:
        for patcher in patchers:
            patcher.stop()

    assert authority.is_hydrated is True
    assert authority.is_ready() is True
    assert authority.get_raw_per_broker("coinbase") == 0.0
    assert CAPITAL_HYDRATED_EVENT.is_set() is True


if __name__ == "__main__":
    check_refresh_hydrates_from_registry_when_broker_map_empty()
    check_refresh_hydration_skips_none_brokers()
    check_refresh_prefers_explicit_broker_map_over_registry_hydration()
    check_refresh_hydrates_zero_balance()
    print("✅ capital_authority_refresh_hydration_checks passed")
