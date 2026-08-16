from __future__ import annotations

import sys
from types import ModuleType


def test_terminal_writer_loss_halt_uses_canonical_seak_signature(monkeypatch):
    import bot.terminal_writer_loss_seak_v118_patch as patch

    calls: list[str] = []

    class FakeSEAK:
        def emergency_halt(self, reason: str = "emergency halt") -> None:
            calls.append(reason)

    seak_mod = ModuleType("bot.single_execution_authority_kernel")
    seak_mod.get_seak = lambda: FakeSEAK()
    monkeypatch.setitem(sys.modules, "bot.single_execution_authority_kernel", seak_mod)

    latch_mod = ModuleType("bot.terminal_writer_loss_latch")

    def old_halt(reason: str) -> None:
        raise AssertionError(reason)

    latch_mod._halt_seak_on_terminal_loss = old_halt
    monkeypatch.setitem(sys.modules, "bot.terminal_writer_loss_latch", latch_mod)

    assert patch._patch_terminal_latch() is True
    latch_mod._halt_seak_on_terminal_loss("core_thread_dead")

    assert calls == ["terminal_writer_loss:core_thread_dead"]


def test_terminal_writer_loss_patch_is_idempotent(monkeypatch):
    import bot.terminal_writer_loss_seak_v118_patch as patch

    latch_mod = ModuleType("bot.terminal_writer_loss_latch")
    latch_mod._halt_seak_on_terminal_loss = lambda reason: None
    monkeypatch.setitem(sys.modules, "bot.terminal_writer_loss_latch", latch_mod)

    assert patch._patch_terminal_latch() is True
    first = latch_mod._halt_seak_on_terminal_loss
    assert patch._patch_terminal_latch() is True
    assert latch_mod._halt_seak_on_terminal_loss is first
