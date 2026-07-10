from __future__ import annotations

import contextvars
from types import SimpleNamespace

from bot import dispatch_scope_bridge_safety_patch as bridge_patch
from bot import execution_entry_timeout_guard_patch as timeout_patch


def test_execute_entry_runs_inline_and_preserves_authority_context():
    authority = contextvars.ContextVar("authority", default="missing")

    class Engine:
        def execute_entry(self, symbol, side, position_size):
            return authority.get()

    module = SimpleNamespace(ExecutionEngine=Engine, __name__="bot.execution_engine")
    assert timeout_patch._patch_module(module) is True

    token = authority.set("dispatch-enabled")
    try:
        result = module.ExecutionEngine().execute_entry("APT-USDT", "buy", 27.56)
    finally:
        authority.reset(token)

    assert result == "dispatch-enabled"


def test_dispatch_scope_bridge_is_disabled_by_default(monkeypatch):
    module = SimpleNamespace(
        _dispatch_scope_only_block=lambda decision: True,
        __name__="bot.dispatch_scope_bridge_patch",
    )
    monkeypatch.delenv("NIJA_ALLOW_DISPATCH_SCOPE_BRIDGE", raising=False)

    assert bridge_patch._patch(module) is True
    assert module._dispatch_scope_only_block(SimpleNamespace()) is False

    monkeypatch.setenv("NIJA_ALLOW_DISPATCH_SCOPE_BRIDGE", "true")
    assert module._dispatch_scope_only_block(SimpleNamespace()) is True
