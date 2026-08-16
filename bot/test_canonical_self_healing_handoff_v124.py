from __future__ import annotations

import os
import types
import unittest
from unittest.mock import patch

from bot import canonical_self_healing_handoff_v124_patch as v124


class _Broker:
    def __init__(self, connected: bool = True) -> None:
        self.connected = connected


class CanonicalSelfHealingHandoffV124Tests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_authority = os.environ.get("NIJA_RUNTIME_EXECUTION_AUTHORITY")
        self._old_active = os.environ.get("NIJA_EXECUTION_ACTIVE")

    def tearDown(self) -> None:
        if self._old_authority is None:
            os.environ.pop("NIJA_RUNTIME_EXECUTION_AUTHORITY", None)
        else:
            os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] = self._old_authority
        if self._old_active is None:
            os.environ.pop("NIJA_EXECUTION_ACTIVE", None)
        else:
            os.environ["NIJA_EXECUTION_ACTIVE"] = self._old_active

    def _module_with_original(self):
        module = types.ModuleType("bot.bot_main_test_v124")
        calls = []

        def original():
            calls.append("original")
            return False, None, "legacy"

        module._run_self_healing_startup = original
        return module, calls

    def test_fast_handoff_skips_legacy_and_stays_fail_closed(self) -> None:
        module, calls = self._module_with_original()
        broker = _Broker()
        self.assertTrue(v124._patch_bot_main(module))
        with patch.object(
            v124,
            "_fast_handoff_proof",
            return_value=(True, broker, "kraken", "proofs_ready"),
        ):
            os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] = "1"
            os.environ["NIJA_EXECUTION_ACTIVE"] = "true"
            result = module._run_self_healing_startup()

        self.assertEqual((True, broker, "kraken"), result)
        self.assertEqual([], calls)
        self.assertEqual("0", os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"])
        self.assertEqual("false", os.environ["NIJA_EXECUTION_ACTIVE"])

    def test_failed_proof_runs_original_self_healing(self) -> None:
        module, calls = self._module_with_original()
        self.assertTrue(v124._patch_bot_main(module))
        with patch.object(
            v124,
            "_fast_handoff_proof",
            return_value=(False, None, "", "readiness_false:nonce_ready"),
        ):
            result = module._run_self_healing_startup()

        self.assertEqual((False, None, "legacy"), result)
        self.assertEqual(["original"], calls)

    def test_patch_bot_main_is_idempotent(self) -> None:
        module, _ = self._module_with_original()
        self.assertTrue(v124._patch_bot_main(module))
        first = module._run_self_healing_startup
        self.assertTrue(v124._patch_bot_main(module))
        self.assertIs(first, module._run_self_healing_startup)

    def test_connected_broker_prefers_kraken(self) -> None:
        manager = types.SimpleNamespace(
            platform_brokers={
                "coinbase": _Broker(),
                "kraken": _Broker(),
            }
        )
        broker, name = v124._connected_broker(manager)
        self.assertIs(broker, manager.platform_brokers["kraken"])
        self.assertEqual("kraken", name)

    def test_position_sync_not_a_pre_core_handoff_requirement(self) -> None:
        self.assertNotIn("position_sync_ready", v124._REQUIRED_READINESS)
        self.assertIn("nonce_ready", v124._REQUIRED_READINESS)
        self.assertIn("risk_ready", v124._REQUIRED_READINESS)


if __name__ == "__main__":
    unittest.main()
