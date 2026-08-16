from __future__ import annotations

import builtins
from pathlib import Path
from types import ModuleType

from bot import canonical_import_shield_v123_patch as v123


def test_shield_active_detects_process_compactor(monkeypatch):
    original = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        return original(name, globals, locals, fromlist, level)

    setattr(fake_import, "_nija_import_chain_compactor", "test")
    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert v123._shield_active() is True


def test_release_manifest_attests_v123(monkeypatch):
    import sys

    fake = ModuleType("bot.runtime_release_manifest_patch")
    fake._REQUIRED_FLAGS = {}
    fake.RELEASE_ID = "old"
    monkeypatch.setitem(sys.modules, "bot.runtime_release_manifest_patch", fake)

    assert v123._patch_release_manifest_if_loaded() is True
    assert fake._REQUIRED_FLAGS["canonical_import_shield_v123"] == (
        "NIJA_CANONICAL_IMPORT_SHIELD_V123_INSTALLED"
    )
    assert fake.RELEASE_ID == "20260816-runtime-convergence-v123"


def test_canonical_entrypoint_installs_v123_before_fast_guard_bundle():
    source = Path("bot/bot.py").read_text(encoding="utf-8")
    call = source.index("if not _install_canonical_import_shield_v123():")
    bundle = source.index("if not _install_guards(\n        _FAST_PATH_INSTALLERS", call)
    assert call < bundle


def test_v98_attests_v123_in_canonical_convergence_chain():
    source = Path("bot/position_sync_timeout_v98_patch.py").read_text(encoding="utf-8")
    assert '("canonical_import_shield_v123_patch", "V123")' in source
    assert "canonical_import_shield_v123=true" in source
