"""
Tests for the global broker state registry (bot/broker_registry.py).

Validates:
1. Default registry starts empty
2. Dict-style access auto-creates inner BrokerStateDict
3. Setting a value persists and is readable
4. broker_registry["kraken"]["platform"] = True canonical pattern works
5. get_state / set_state helpers work correctly
6. is_platform() convenience method works
7. reset() clears one broker or all brokers
8. get_all_states() returns a plain-dict snapshot
9. Thread safety – concurrent writes do not corrupt state
10. BrokerStateDict.update() triggers callbacks and timestamps
"""

import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from broker_registry import BrokerRegistry, BrokerStateDict, broker_registry as _global_registry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_registry(**kwargs) -> BrokerRegistry:
    """Return a fresh, isolated BrokerRegistry for each test."""
    return BrokerRegistry(**kwargs)


# ---------------------------------------------------------------------------
# BrokerStateDict tests
# ---------------------------------------------------------------------------

def test_broker_state_dict_set_and_get():
    """BrokerStateDict stores values and updates last_modified."""
    state = BrokerStateDict("kraken")
    assert state.last_modified is None

    state["platform"] = True
    assert state["platform"] is True
    assert state.last_modified is not None
    print("✅ test_broker_state_dict_set_and_get passed")


def test_broker_state_dict_delete():
    """Deleting a key removes it and updates last_modified."""
    state = BrokerStateDict("kraken")
    state["connected"] = True
    prev_ts = state.last_modified
    time.sleep(0.001)  # ensure timestamp advances

    del state["connected"]
    assert "connected" not in state
    assert state.last_modified >= prev_ts
    print("✅ test_broker_state_dict_delete passed")


def test_broker_state_dict_update():
    """BrokerStateDict.update() triggers __setitem__ and fires callbacks."""
    fired = []

    def on_change(broker, key, value):
        fired.append((broker, key, value))

    state = BrokerStateDict("coinbase", on_change=on_change)
    state.update({"platform": False, "connected": True})

    assert state["platform"] is False
    assert state["connected"] is True
    assert ("coinbase", "platform", False) in fired
    assert ("coinbase", "connected", True) in fired
    print("✅ test_broker_state_dict_update passed")


def test_broker_state_dict_on_change_callback():
    """on_change callback fires with correct arguments on every set."""
    events = []

    def callback(broker, key, val):
        events.append((broker, key, val))

    state = BrokerStateDict("kraken", on_change=callback)
    state["platform"] = True
    state["connected"] = False

    assert events == [("kraken", "platform", True), ("kraken", "connected", False)]
    print("✅ test_broker_state_dict_on_change_callback passed")


# ---------------------------------------------------------------------------
# BrokerRegistry tests
# ---------------------------------------------------------------------------

def test_registry_starts_empty():
    """Fresh registry should be empty."""
    reg = make_registry()
    assert len(reg) == 0
    assert reg.get_all_states() == {}
    print("✅ test_registry_starts_empty passed")


def test_dict_style_access_creates_inner_dict():
    """Accessing an unknown broker key auto-creates a BrokerStateDict."""
    reg = make_registry()
    inner = reg["kraken"]
    assert isinstance(inner, BrokerStateDict)
    assert "kraken" in reg
    print("✅ test_dict_style_access_creates_inner_dict passed")


def test_canonical_pattern_kraken_platform_true():
    """broker_registry['kraken']['platform'] = True — the core requirement."""
    reg = make_registry()
    reg["kraken"]["platform"] = True

    assert reg["kraken"]["platform"] is True
    assert reg.is_platform("kraken") is True
    print("✅ test_canonical_pattern_kraken_platform_true passed")


def test_multiple_brokers_are_isolated():
    """State for one broker does not bleed into another."""
    reg = make_registry()
    reg["kraken"]["platform"] = True
    reg["coinbase"]["platform"] = False

    assert reg["kraken"]["platform"] is True
    assert reg["coinbase"]["platform"] is False
    print("✅ test_multiple_brokers_are_isolated passed")


def test_set_state_and_get_state_helpers():
    """set_state / get_state helpers work as an alternative to dict syntax."""
    reg = make_registry()
    reg.set_state("kraken", "platform", True)
    reg.set_state("kraken", "connected", False)

    assert reg.get_state("kraken", "platform") is True
    assert reg.get_state("kraken", "connected") is False
    assert reg.get_state("kraken", "missing_key", "default") == "default"
    print("✅ test_set_state_and_get_state_helpers passed")


def test_get_state_on_unknown_broker_returns_default():
    """get_state should not raise for unknown brokers."""
    reg = make_registry()
    result = reg.get_state("nonexistent", "platform", None)
    assert result is None
    print("✅ test_get_state_on_unknown_broker_returns_default passed")


def test_is_platform_false_by_default():
    """is_platform returns False when the key is absent."""
    reg = make_registry()
    assert reg.is_platform("kraken") is False
    print("✅ test_is_platform_false_by_default passed")


def test_is_platform_true_after_set():
    """is_platform returns True once platform key is set to truthy value."""
    reg = make_registry()
    reg["kraken"]["platform"] = True
    assert reg.is_platform("kraken") is True
    print("✅ test_is_platform_true_after_set passed")


def test_reset_single_broker():
    """reset(broker_name) clears only that broker's state."""
    reg = make_registry()
    reg["kraken"]["platform"] = True
    reg["coinbase"]["connected"] = True

    reg.reset("kraken")
    assert reg["kraken"] == {}
    assert reg["coinbase"]["connected"] is True
    print("✅ test_reset_single_broker passed")


def test_reset_all():
    """reset() with no argument clears all broker states."""
    reg = make_registry()
    reg["kraken"]["platform"] = True
    reg["coinbase"]["connected"] = True

    reg.reset()
    assert len(reg) == 0
    print("✅ test_reset_all passed")


def test_get_all_states_returns_snapshot():
    """get_all_states() returns a plain dict snapshot."""
    reg = make_registry()
    reg["kraken"]["platform"] = True
    reg["coinbase"]["connected"] = False

    snapshot = reg.get_all_states()
    assert isinstance(snapshot, dict)
    assert snapshot["kraken"] == {"platform": True}
    assert snapshot["coinbase"] == {"connected": False}

    # Mutating the snapshot does not affect the registry
    snapshot["kraken"]["platform"] = False
    assert reg["kraken"]["platform"] is True
    print("✅ test_get_all_states_returns_snapshot passed")


def test_summary_string_contains_broker_names():
    """summary() should mention broker names and their state keys."""
    reg = make_registry()
    reg["kraken"]["platform"] = True
    summary = reg.summary()
    assert "kraken" in summary
    assert "platform" in summary
    print("✅ test_summary_string_contains_broker_names passed")


def test_on_change_callback_fires_from_registry():
    """Registry-level on_change callback is forwarded to BrokerStateDict."""
    events = []

    def callback(broker, key, val):
        events.append((broker, key, val))

    reg = make_registry(on_change=callback)
    reg["kraken"]["platform"] = True

    assert ("kraken", "platform", True) in events
    print("✅ test_on_change_callback_fires_from_registry passed")


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------

def test_concurrent_writes_are_safe():
    """Many threads writing to different broker keys must not corrupt state."""
    reg = make_registry()
    errors = []

    def writer(broker, count):
        try:
            for i in range(count):
                reg[broker][f"key_{i}"] = i
        except Exception as exc:
            errors.append(exc)

    threads = [
        threading.Thread(target=writer, args=(f"broker_{n}", 50))
        for n in range(8)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Thread errors: {errors}"
    # Every broker should have 50 keys
    for n in range(8):
        broker = f"broker_{n}"
        assert len(reg[broker]) == 50, f"{broker} has {len(reg[broker])} keys"
    print("✅ test_concurrent_writes_are_safe passed")


# ---------------------------------------------------------------------------
# Module-level singleton smoke test
# ---------------------------------------------------------------------------

def test_global_singleton_is_broker_registry_instance():
    """The module-level ``broker_registry`` export is a BrokerRegistry."""
    assert isinstance(_global_registry, BrokerRegistry)
    print("✅ test_global_singleton_is_broker_registry_instance passed")


def test_global_singleton_supports_canonical_pattern():
    """Smoke-test the module-level singleton with the canonical pattern."""
    # Use a unique key to avoid cross-test pollution
    _global_registry["_test_kraken"]["platform"] = True
    assert _global_registry["_test_kraken"]["platform"] is True
    # Clean up
    _global_registry.reset("_test_kraken")
    print("✅ test_global_singleton_supports_canonical_pattern passed")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    test_broker_state_dict_set_and_get()
    test_broker_state_dict_delete()
    test_broker_state_dict_update()
    test_broker_state_dict_on_change_callback()
    test_registry_starts_empty()
    test_dict_style_access_creates_inner_dict()
    test_canonical_pattern_kraken_platform_true()
    test_multiple_brokers_are_isolated()
    test_set_state_and_get_state_helpers()
    test_get_state_on_unknown_broker_returns_default()
    test_is_platform_false_by_default()
    test_is_platform_true_after_set()
    test_reset_single_broker()
    test_reset_all()
    test_get_all_states_returns_snapshot()
    test_summary_string_contains_broker_names()
    test_on_change_callback_fires_from_registry()
    test_concurrent_writes_are_safe()
    test_global_singleton_is_broker_registry_instance()
    test_global_singleton_supports_canonical_pattern()

    print("\n🎉 All broker_registry tests passed!")
