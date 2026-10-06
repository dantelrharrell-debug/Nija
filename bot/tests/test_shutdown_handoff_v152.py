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

def test_completed_bot_main_shutdown_event_is_not_reused(monkeypatch) -> None:
    """A finished main() must not poison a later writer-authority object."""
    shutdown = threading.Event()
    shutdown.set()
    bot_main = ModuleType("bot.bot_main")
    bot_main._shutdown_event = shutdown
    bot_main._main_active = False
    monkeypatch.setitem(sys.modules, "bot.bot_main", bot_main)

    bootstrap = ModuleType("bot.bootstrap_utils")
    bootstrap.get_shutdown_event = lambda: shutdown
    monkeypatch.setitem(sys.modules, "bot.bootstrap_utils", bootstrap)

    assert authority._process_shutdown_requested() is False


def test_active_bot_main_shutdown_event_remains_authoritative(monkeypatch) -> None:
    """Real shutdown during an active canonical main lifecycle stays fail-closed."""
    shutdown = threading.Event()
    shutdown.set()
    bot_main = ModuleType("bot.bot_main")
    bot_main._shutdown_event = shutdown
    bot_main._main_active = True
    monkeypatch.setitem(sys.modules, "bot.bot_main", bot_main)

    assert authority._process_shutdown_requested() is True
