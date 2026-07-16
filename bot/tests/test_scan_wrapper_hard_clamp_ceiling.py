from __future__ import annotations

import os
from types import ModuleType

from bot import scan_wrapper_hard_clamp_patch as clamp


def _chain(depth: int):
    def base(self=None):
        return None

    current = base
    for index in range(depth - 1):
        previous = current

        def wrapper(self=None, _previous=previous):
            return _previous(self)

        wrapper.__wrapped__ = previous
        wrapper.__name__ = f"wrapper_{index}"
        current = wrapper
    return current


def test_legacy_24_depth_default_migrates_to_64(monkeypatch):
    monkeypatch.setenv("NIJA_MAX_SCAN_WRAPPER_DEPTH", "24")
    assert clamp._normalise_depth_ceiling() == 64
    assert os.environ["NIJA_MAX_SCAN_WRAPPER_DEPTH"] == "64"


def test_stable_32_layer_chain_is_accepted(monkeypatch):
    monkeypatch.setenv("NIJA_MAX_SCAN_WRAPPER_DEPTH", "64")
    module = ModuleType("bot.nija_core_loop")

    class NijaCoreLoop:
        run_scan_phase = _chain(32)

    module.NijaCoreLoop = NijaCoreLoop
    assert clamp._collapse_core(module) is False
    chain, cycle = clamp._walk(module.NijaCoreLoop.run_scan_phase)
    assert len(chain) == 32
    assert cycle is False


def test_64_remains_hard_maximum(monkeypatch):
    monkeypatch.setenv("NIJA_MAX_SCAN_WRAPPER_DEPTH", "200")
    assert clamp._normalise_depth_ceiling() == 64
