from __future__ import annotations

import importlib
import sys
import types
import unittest
from unittest.mock import patch

from bot import canonical_core_import_handoff_v125_patch as v125


class CanonicalCoreImportHandoffV125Tests(unittest.TestCase):
    def test_target_set_contains_step3_modules(self) -> None:
        self.assertIn("bot.nija_core_loop", v125._TARGETS)
        self.assertIn("bot.startup_coordinator", v125._TARGETS)
        self.assertIn("bot.entrypoint_writer_authority", v125._TARGETS)

    def test_resolve_target_reapplies_core_safety(self) -> None:
        core = types.ModuleType("bot.nija_core_loop")
        with patch.object(v125, "_canonical_import", return_value=core), patch.object(
            v125, "_reapply_core_safety", return_value=True
        ) as safety:
            self.assertIs(core, v125._resolve_target("bot.nija_core_loop"))
        safety.assert_called_once_with(core)

    def test_resolve_target_fails_closed_when_core_safety_reapply_fails(self) -> None:
        core = types.ModuleType("bot.nija_core_loop")
        with patch.object(v125, "_canonical_import", return_value=core), patch.object(
            v125, "_reapply_core_safety", return_value=False
        ):
            with self.assertRaisesRegex(RuntimeError, "core_safety_reapply_failed"):
                v125._resolve_target("bot.nija_core_loop")

    def test_builtin_target_import_uses_resolver(self) -> None:
        original = __import__
        module = types.ModuleType("bot.startup_coordinator")
        try:
            self.assertTrue(v125._patch_builtin_import())
            with patch.object(v125, "_resolve_target", return_value=module) as resolve:
                imported = __import__("bot.startup_coordinator", fromlist=("get_startup_coordinator",))
            self.assertIs(imported, module)
            resolve.assert_called_once_with("bot.startup_coordinator")
        finally:
            import builtins
            builtins.__import__ = original

    def test_importlib_target_import_uses_resolver(self) -> None:
        original = importlib.import_module
        module = types.ModuleType("bot.nija_core_loop")
        try:
            self.assertTrue(v125._patch_import_module())
            with patch.object(v125, "_resolve_target", return_value=module) as resolve:
                imported = importlib.import_module("bot.nija_core_loop")
            self.assertIs(imported, module)
            resolve.assert_called_once_with("bot.nija_core_loop")
        finally:
            importlib.import_module = original

    def test_strategy_helper_returns_none_on_publication_failure(self) -> None:
        bot_main = types.ModuleType("bot.bot_main")
        bot_main._publish_canonical_strategy_for_runtime = lambda broker: object()
        bot_main._fail_closed_strategy_publication = lambda detail: None
        publication = types.ModuleType("bot.strategy_publication_patch")
        publication.publish_canonical_strategy = lambda explicit_broker=None: (None, "timeout")
        publication.start_monitor = lambda: None

        def canonical(name: str):
            if name == "bot.bot_main":
                return bot_main
            if name == "bot.strategy_publication_patch":
                return publication
            raise AssertionError(name)

        with patch.object(v125, "_canonical_import", side_effect=canonical), patch.object(
            v125, "_resolve_target", side_effect=canonical
        ):
            self.assertTrue(v125._patch_strategy_publication_helper())
            self.assertIsNone(bot_main._publish_canonical_strategy_for_runtime(object()))


if __name__ == "__main__":
    unittest.main()
