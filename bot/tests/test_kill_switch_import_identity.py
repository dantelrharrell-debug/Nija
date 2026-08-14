from __future__ import annotations

import importlib
import sys


def test_legacy_kill_switch_import_reuses_canonical_module():
    canonical = importlib.import_module("bot.kill_switch")

    # Exercise the compatibility path as a fresh legacy import.
    sys.modules.pop("kill_switch", None)
    legacy = importlib.import_module("kill_switch")

    assert legacy is canonical
    assert sys.modules["kill_switch"] is sys.modules["bot.kill_switch"]
    assert legacy.get_kill_switch is canonical.get_kill_switch


def test_legacy_and_canonical_imports_share_singleton():
    canonical = importlib.import_module("bot.kill_switch")
    legacy = importlib.import_module("kill_switch")

    assert legacy.get_kill_switch() is canonical.get_kill_switch()
