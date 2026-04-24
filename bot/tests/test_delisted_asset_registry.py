"""
Tests for DelistedAssetRegistry - persistent registry for invalid/delisted symbols.

Validates:
1. New registry starts empty
2. Symbols can be registered with flags
3. is_registered() returns correct results
4. Flags are persisted and reloaded correctly (restart simulation)
5. Flags are never downgraded (True stays True on subsequent register calls)
6. remove() works correctly
7. mark_sell_attempted() / mark_permanent_dust() convenience helpers
8. get_stats() returns correct counts
"""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from delisted_asset_registry import DelistedAssetRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_registry(tmp_dir: str) -> DelistedAssetRegistry:
    return DelistedAssetRegistry(registry_file=os.path.join(tmp_dir, "delisted_asset_registry.json"))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_empty_on_first_run():
    """New registry should be empty."""
    with tempfile.TemporaryDirectory() as tmp:
        reg = make_registry(tmp)
        assert not reg.is_registered("BTC-USD")
        assert reg.all_symbols() == {}
        stats = reg.get_stats()
        assert stats["total"] == 0
    print("✅ test_empty_on_first_run passed")


def test_register_new_symbol():
    """Registering a new symbol should persist it with correct flags."""
    with tempfile.TemporaryDirectory() as tmp:
        reg = make_registry(tmp)
        reg.register("XYZ-USD", permanent_dust=False, sell_attempted=False)

        assert reg.is_registered("XYZ-USD")
        entry = reg.get("XYZ-USD")
        assert entry is not None
        assert entry["permanent_dust"] is False
        assert entry["sell_attempted"] is False
        assert "timestamp" in entry
    print("✅ test_register_new_symbol passed")


def test_flags_persisted_across_restart():
    """Registry should reload flags from disk after 'restart'."""
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "delisted_asset_registry.json")

        # First "session"
        reg1 = DelistedAssetRegistry(registry_file=path)
        reg1.register("ABC-USD", permanent_dust=True, sell_attempted=True)
        reg1.register("DEF-USD", permanent_dust=False, sell_attempted=True)

        # Second "session" (simulate restart)
        reg2 = DelistedAssetRegistry(registry_file=path)
        assert reg2.is_registered("ABC-USD")
        entry_abc = reg2.get("ABC-USD")
        assert entry_abc["permanent_dust"] is True
        assert entry_abc["sell_attempted"] is True

        assert reg2.is_registered("DEF-USD")
        entry_def = reg2.get("DEF-USD")
        assert entry_def["permanent_dust"] is False
        assert entry_def["sell_attempted"] is True

        assert not reg2.is_registered("NOTHERE-USD")
    print("✅ test_flags_persisted_across_restart passed")


def test_flags_never_downgraded():
    """Once a flag is True, a subsequent register() call must not set it back to False."""
    with tempfile.TemporaryDirectory() as tmp:
        reg = make_registry(tmp)
        reg.register("SYM-USD", permanent_dust=True, sell_attempted=False)

        # Attempt to 'downgrade' by calling register again with False flags
        reg.register("SYM-USD", permanent_dust=False, sell_attempted=False)

        entry = reg.get("SYM-USD")
        assert entry["permanent_dust"] is True, "permanent_dust should stay True"
        assert entry["sell_attempted"] is False
    print("✅ test_flags_never_downgraded passed")


def test_flag_upgrade_persisted():
    """Upgrading a flag (False -> True) should be written to disk."""
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "delisted_asset_registry.json")

        reg1 = DelistedAssetRegistry(registry_file=path)
        reg1.register("UPG-USD", permanent_dust=False, sell_attempted=False)

        # Upgrade sell_attempted
        reg1.register("UPG-USD", sell_attempted=True)

        reg2 = DelistedAssetRegistry(registry_file=path)
        entry = reg2.get("UPG-USD")
        assert entry["sell_attempted"] is True
    print("✅ test_flag_upgrade_persisted passed")


def test_remove_symbol():
    """Removed symbols should no longer be registered."""
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "delisted_asset_registry.json")

        reg = DelistedAssetRegistry(registry_file=path)
        reg.register("REM-USD")
        assert reg.is_registered("REM-USD")

        reg.remove("REM-USD")
        assert not reg.is_registered("REM-USD")

        # Persist and reload
        reg2 = DelistedAssetRegistry(registry_file=path)
        assert not reg2.is_registered("REM-USD")
    print("✅ test_remove_symbol passed")


def test_mark_convenience_methods():
    """mark_sell_attempted() and mark_permanent_dust() should work correctly."""
    with tempfile.TemporaryDirectory() as tmp:
        reg = make_registry(tmp)
        reg.register("CONV-USD")

        reg.mark_sell_attempted("CONV-USD")
        assert reg.get("CONV-USD")["sell_attempted"] is True
        assert reg.get("CONV-USD")["permanent_dust"] is False

        reg.mark_permanent_dust("CONV-USD")
        assert reg.get("CONV-USD")["permanent_dust"] is True
    print("✅ test_mark_convenience_methods passed")


def test_get_stats():
    """get_stats() should return accurate counts."""
    with tempfile.TemporaryDirectory() as tmp:
        reg = make_registry(tmp)
        reg.register("A-USD", permanent_dust=True, sell_attempted=True)
        reg.register("B-USD", permanent_dust=False, sell_attempted=True)
        reg.register("C-USD", permanent_dust=False, sell_attempted=False)

        stats = reg.get_stats()
        assert stats["total"] == 3
        assert stats["permanent_dust"] == 1
        assert stats["sell_attempted"] == 2
    print("✅ test_get_stats passed")


def test_json_file_structure():
    """The JSON file should have expected top-level keys."""
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "delisted_asset_registry.json")
        reg = DelistedAssetRegistry(registry_file=path)
        reg.register("X-USD")

        with open(path) as f:
            data = json.load(f)

        assert "updated_at" in data
        assert "count" in data
        assert "symbols" in data
        assert "X-USD" in data["symbols"]
        entry = data["symbols"]["X-USD"]
        assert "timestamp" in entry
        assert "permanent_dust" in entry
        assert "sell_attempted" in entry
    print("✅ test_json_file_structure passed")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("DELISTED ASSET REGISTRY TESTS")
    print("=" * 70 + "\n")

    try:
        test_empty_on_first_run()
        test_register_new_symbol()
        test_flags_persisted_across_restart()
        test_flags_never_downgraded()
        test_flag_upgrade_persisted()
        test_remove_symbol()
        test_mark_convenience_methods()
        test_get_stats()
        test_json_file_structure()

        print("\n" + "=" * 70)
        print("✅ ALL TESTS PASSED")
        print("=" * 70)

    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        import traceback
        print(f"\n❌ TEST ERROR: {e}")
        traceback.print_exc()
        sys.exit(1)
