"""Canonical execution readiness must be a literal bool, not truthy input."""
import sys
import types
from unittest.mock import patch

from unittest import TestCase

from bot import runtime_execution_authority_proof_gate_v361_patch as v361
from bot import runtime_stale_live_execution_proof_v362_patch as v362


class CanonicalExecutionReadyBoolTests(TestCase):
    """Verify that both authority guards require literal boolean readiness."""

    def test_execution_proof_guards_reject_truthy_nonbooleans(self) -> None:
        """Reject non-boolean inputs and false readiness."""
        for value in ("true", "1", 1, ["ready"], {"ready": True}, None, False):
            readiness = types.ModuleType("bot.readiness_table")
            readiness.snapshot = lambda value=value: {"execution_ready": value}
            with patch.dict(sys.modules, {"bot.readiness_table": readiness}):
                for module in (v361, v362):
                    with self.subTest(module=module.__name__, value=value):
                        ok, _ = module._canonical_execution_ready()
                        self.assertIs(ok, False)

    def test_execution_proof_guards_accept_literal_true_only(self) -> None:
        """Accept literal True in both guards."""
        readiness = types.ModuleType("bot.readiness_table")
        readiness.snapshot = lambda: {"execution_ready": True}
        with patch.dict(sys.modules, {"bot.readiness_table": readiness}):
            self.assertIs(v361._canonical_execution_ready()[0], True)
            self.assertIs(v362._canonical_execution_ready()[0], True)
