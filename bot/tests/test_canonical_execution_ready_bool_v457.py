"""Canonical execution readiness must be a literal bool, not truthy input."""
import sys
import types
from unittest.mock import patch

from bot import runtime_execution_authority_proof_gate_v361_patch as v361
from bot import runtime_stale_live_execution_proof_v362_patch as v362


def test_execution_proof_guards_reject_truthy_nonbooleans():
    for value in ("true", "1", 1, ["ready"], {"ready": True}, None, False):
        readiness = types.ModuleType("bot.readiness_table")
        readiness.snapshot = lambda value=value: {"execution_ready": value}
        with patch.dict(sys.modules, {"bot.readiness_table": readiness}):
            for module in (v361, v362):
                ok, _ = module._canonical_execution_ready()
                assert ok is False, (module.__name__, value)


def test_execution_proof_guards_accept_literal_true_only():
    readiness = types.ModuleType("bot.readiness_table")
    readiness.snapshot = lambda: {"execution_ready": True}
    with patch.dict(sys.modules, {"bot.readiness_table": readiness}):
        assert v361._canonical_execution_ready()[0] is True
        assert v362._canonical_execution_ready()[0] is True
