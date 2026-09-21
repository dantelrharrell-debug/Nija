from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from bot import trading_state_machine as tsm


def test_state_persistence_serializes_atomic_replaces(tmp_path, monkeypatch):
    machine = object.__new__(tsm.TradingStateMachine)
    machine._state_file = str(tmp_path / ".nija_trading_state.json")
    machine._current_state = tsm.TradingState.OFF
    machine._state_history = []

    original_replace = tsm.os.replace
    active = 0
    max_active = 0
    guard = threading.Lock()

    def observed_replace(src, dst):
        nonlocal active, max_active
        with guard:
            active += 1
            max_active = max(max_active, active)
        try:
            time.sleep(0.005)
            return original_replace(src, dst)
        finally:
            with guard:
                active -= 1

    monkeypatch.setattr(tsm.os, "replace", observed_replace)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: machine._persist_state(), range(24)))

    payload = json.loads((tmp_path / ".nija_trading_state.json").read_text())
    assert payload["current_state"] == "OFF"
    assert max_active == 1
    assert list(tmp_path.glob("*.tmp")) == []
