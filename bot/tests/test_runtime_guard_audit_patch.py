from __future__ import annotations

import bot.runtime_guard_audit_patch as audit


def test_ready_when_all_mandatory_guards_are_true():
    env = {name: "1" for name in audit._REQUIRED}
    ready, missing = audit._ready(env)
    assert ready is True
    assert missing == []


def test_missing_guard_is_reported():
    env = {name: "1" for name in audit._REQUIRED}
    env[audit._REQUIRED[1]] = "0"
    ready, missing = audit._ready(env)
    assert ready is False
    assert missing == [audit._REQUIRED[1]]
