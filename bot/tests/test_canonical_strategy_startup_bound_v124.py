from __future__ import annotations

import queue
import threading
import time
from types import ModuleType

import bot.canonical_strategy_startup_bound_v124_patch as v124


def _call_with_timeout(fn, *args, timeout_seconds=1.0, **kwargs):
    q = queue.Queue(maxsize=1)

    def runner():
        try:
            q.put(("result", fn(*args, **kwargs)))
        except BaseException as exc:
            q.put(("error", exc))

    threading.Thread(target=runner, daemon=True).start()
    try:
        kind, payload = q.get(timeout=timeout_seconds)
    except queue.Empty:
        return None, TimeoutError("timed out")
    if kind == "error":
        return None, payload
    return payload, None


def test_symbol_discovery_is_time_bounded(monkeypatch):
    strategy_module = ModuleType("fake_trading_strategy")

    class TradingStrategy:
        @staticmethod
        def _broker_key_from_obj(_broker):
            return "kraken"

        @staticmethod
        def _dedupe_symbols(products):
            return list(dict.fromkeys(products))

        def _discover_broker_symbols(self, broker):
            return broker.get_available_markets()

    class BlockingBroker:
        def get_available_markets(self):
            time.sleep(0.5)
            return ["BTC-USD"]

        def get_all_products(self):
            time.sleep(0.5)
            return ["ETH-USD"]

    strategy_module.TradingStrategy = TradingStrategy
    strategy_module.call_with_timeout = _call_with_timeout
    monkeypatch.setenv("NIJA_SYMBOL_DISCOVERY_TIMEOUT_S", "0.1")

    assert v124._patch_symbol_discovery(strategy_module)
    started = time.monotonic()
    result = TradingStrategy()._discover_broker_symbols(BlockingBroker())
    elapsed = time.monotonic() - started

    # Both catalog probes are bounded at 0.1s rather than inheriting their
    # 0.5s blocking duration. No symbols are fabricated after timeout.
    assert elapsed < 0.35
    assert result == []


def test_wiring_hydration_removes_unbounded_first_attempt(monkeypatch):
    wiring_module = ModuleType("fake_wiring")

    def needs(_strategy):
        return True

    def hydrate(_strategy, broker=None, reason="runtime"):
        time.sleep(0.5)
        return True

    def old_bounded(_strategy, broker=None, reason="runtime"):
        return hydrate(_strategy, broker=broker, reason=reason)

    wiring_module._needs_hydration = needs
    wiring_module._hydrate_strategy_wiring = hydrate
    wiring_module._bounded_hydrate_strategy_wiring = old_bounded
    monkeypatch.setenv("NIJA_TRADING_STRATEGY_WIRING_TIMEOUT_S", "0.1")

    assert v124._patch_wiring_bound(wiring_module)
    started = time.monotonic()
    ready = wiring_module._bounded_hydrate_strategy_wiring(object(), reason="test")
    elapsed = time.monotonic() - started

    assert elapsed < 0.3
    assert ready is False


def test_complete_publication_is_bounded_and_late_publish_is_suppressed(monkeypatch):
    publication_module = ModuleType("fake_publication")
    published = []

    def publish(strategy):
        published.append(strategy)

    def publish_canonical_strategy(*args, **kwargs):
        time.sleep(1.2)
        publication_module._publish(object())
        return object(), "late"

    publication_module._publish = publish
    publication_module.publish_canonical_strategy = publish_canonical_strategy
    # The production clamp has a 1s minimum. Make the original operation exceed it.
    monkeypatch.setenv("NIJA_CANONICAL_STRATEGY_PUBLICATION_TIMEOUT_S", "1")

    assert v124._patch_publication_bound(publication_module)
    started = time.monotonic()
    strategy, detail = publication_module.publish_canonical_strategy()
    elapsed = time.monotonic() - started

    assert elapsed < 1.15
    assert strategy is None
    assert detail == "publication_timeout_v124"

    # Let the original worker reach its attempted publish. The guard must keep
    # a post-deadline strategy from becoming visible/readiness-producing.
    time.sleep(0.35)
    assert published == []


def test_release_manifest_attests_v124(monkeypatch):
    manifest = ModuleType("bot.runtime_release_manifest_patch")
    manifest._REQUIRED_FLAGS = {}
    manifest.RELEASE_ID = "old"
    monkeypatch.setitem(__import__("sys").modules, "bot.runtime_release_manifest_patch", manifest)

    assert v124._patch_release_manifest()
    assert manifest._REQUIRED_FLAGS["canonical_strategy_startup_bound_v124"] == (
        "NIJA_CANONICAL_STRATEGY_STARTUP_BOUND_V124_INSTALLED"
    )
    assert manifest.RELEASE_ID == "20260816-runtime-convergence-v124"


def test_v98_orders_v124_before_strategy_recovery():
    source = open("bot/position_sync_timeout_v98_patch.py", encoding="utf-8").read()
    assert source.index("canonical_strategy_startup_bound_v124_patch") < source.index(
        "startup_strategy_import_cycle_v104_patch"
    )
    assert "canonical_strategy_startup_bound_v124=true" in source
