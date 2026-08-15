from __future__ import annotations

import importlib


def test_default_timeout_is_widened_without_env(monkeypatch):
    monkeypatch.delenv("NIJA_POSITION_FETCH_TIMEOUT_S", raising=False)
    module = importlib.import_module("bot.position_sync_timeout_v98_patch")
    assert module._timeout_s_v98() == 12.0


def test_explicit_timeout_override_is_preserved(monkeypatch):
    monkeypatch.setenv("NIJA_POSITION_FETCH_TIMEOUT_S", "7.5")
    module = importlib.import_module("bot.position_sync_timeout_v98_patch")
    assert module._timeout_s_v98() == 7.5


def test_invalid_timeout_falls_back_to_safe_default(monkeypatch):
    monkeypatch.setenv("NIJA_POSITION_FETCH_TIMEOUT_S", "not-a-number")
    module = importlib.import_module("bot.position_sync_timeout_v98_patch")
    assert module._timeout_s_v98() == 12.0


def test_install_patches_v95_timeout_only(monkeypatch):
    monkeypatch.delenv("NIJA_POSITION_FETCH_TIMEOUT_S", raising=False)
    v95 = importlib.import_module("bot.position_sync_core_handoff_v95_patch")
    v98 = importlib.import_module("bot.position_sync_timeout_v98_patch")

    monkeypatch.setattr(v98, "_INSTALLED", False)
    assert v98.install() is True
    assert v95._timeout_s() == 12.0
    assert v95.position_sync_status is not None
