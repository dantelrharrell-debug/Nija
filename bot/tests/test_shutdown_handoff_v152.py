from __future__ import annotations

import sys
import threading
from types import ModuleType
from unittest.mock import MagicMock

from bot import entrypoint_writer_authority as authority


def test_process_shutdown_detects_canonical_bot_main_event(monkeypatch) -> None:
    shutdown = threading.Event()
    shutdown.set()
    bot_main = ModuleType("bot.bot_main")
    bot_main._shutdown_event = shutdown
    monkeypatch.setitem(sys.modules, "bot.bot_main", bot_main)
    monkeypatch.delenv("NIJA_PROCESS_EXIT_REQUESTED", raising=False)

    assert authority._process_shutdown_requested() is True


def test_shutdown_race_quiesces_before_writer_or_core_mutation(monkeypatch) -> None:
    runtime = authority.EntrypointWriterAuthority()
    runtime._heartbeat_tick = MagicMock(side_effect=AssertionError("heartbeat must not run"))
    runtime._release_owned_lock_for_reelection = MagicMock()
    monkeypatch.setattr(authority, "_process_shutdown_requested", lambda: True)

    runtime._heartbeat_loop()

    runtime._heartbeat_tick.assert_not_called()
    runtime._release_owned_lock_for_reelection.assert_not_called()
    assert runtime.lost is False


def test_tick_quiesces_if_shutdown_arrives_after_loop_probe(monkeypatch) -> None:
    runtime = authority.EntrypointWriterAuthority()
    runtime._release_owned_lock_for_reelection = MagicMock()
    monkeypatch.setattr(authority, "_process_shutdown_requested", lambda: True)

    ok, reason = runtime._heartbeat_tick()

    assert (ok, reason) == (True, "shutdown_requested")
    runtime._release_owned_lock_for_reelection.assert_not_called()
    assert runtime.lost is False
