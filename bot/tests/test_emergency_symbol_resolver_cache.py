from __future__ import annotations

import time
from unittest.mock import MagicMock

from bot.emergency_symbol_resolver import (
    DelistedAssetRegistry,
    EmergencySymbolResolver,
    SymbolStatus,
    notify_exchange_metadata_refresh,
)


def _api_without_prices() -> MagicMock:
    api = MagicMock()
    api.query_public.return_value = {"result": {}}
    return api


def setup_function():
    registry = DelistedAssetRegistry.get_instance()
    registry._delisted.clear()


def test_delisted_symbol_is_cached_and_skips_re_resolve():
    api = _api_without_prices()
    resolver = EmergencySymbolResolver(api)

    for _ in range(resolver.FAILURES_BEFORE_DELISTED):
        resolver.resolve("AIR-USD")

    call_count_after_delist = api.query_public.call_count
    result = resolver.resolve("AIR-USD")

    assert result.status == SymbolStatus.DELISTED
    assert api.query_public.call_count == call_count_after_delist


def test_delisted_symbol_rechecks_after_refresh_window_or_metadata_refresh():
    api = _api_without_prices()
    resolver = EmergencySymbolResolver(api)
    symbol = "AIR-USD"

    for _ in range(resolver.FAILURES_BEFORE_DELISTED):
        resolver.resolve(symbol)

    registry = DelistedAssetRegistry.get_instance()
    registry._delisted[symbol]["last_checked"] = time.time() - resolver.DELISTED_CACHE_REFRESH_SECONDS - 5
    call_count_before_ttl_recheck = api.query_public.call_count
    ttl_result = resolver.resolve(symbol)
    assert ttl_result.status == SymbolStatus.DELISTED
    assert api.query_public.call_count > call_count_before_ttl_recheck

    call_count_before_metadata_recheck = api.query_public.call_count
    notify_exchange_metadata_refresh()
    metadata_result = resolver.resolve(symbol)
    assert metadata_result.status == SymbolStatus.DELISTED
    assert api.query_public.call_count > call_count_before_metadata_recheck
