from __future__ import annotations

import os
import sys
import threading
import time
import types
import unittest
from unittest import mock

from bot import canonical_strategy_class_recovery_v102_patch as v102


class CanonicalStrategyClassRecoveryV102Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.saved_modules = {
            name: sys.modules.get(name)
            for name in ("bot.trading_strategy", "trading_strategy")
        }
        self.saved_timeout = os.environ.get("NIJA_STRATEGY_CLASS_RECOVERY_TIMEOUT_S")
        self.saved_poll = os.environ.get("NIJA_STRATEGY_CLASS_RECOVERY_POLL_S")
        os.environ["NIJA_STRATEGY_CLASS_RECOVERY_TIMEOUT_S"] = "0.4"
        os.environ["NIJA_STRATEGY_CLASS_RECOVERY_POLL_S"] = "0.01"
        v102._RELOAD_ATTEMPTED.clear()
        sys.modules.pop("bot.trading_strategy", None)
        sys.modules.pop("trading_strategy", None)

    def tearDown(self) -> None:
        for name, module in self.saved_modules.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module
        if self.saved_timeout is None:
            os.environ.pop("NIJA_STRATEGY_CLASS_RECOVERY_TIMEOUT_S", None)
        else:
            os.environ["NIJA_STRATEGY_CLASS_RECOVERY_TIMEOUT_S"] = self.saved_timeout
        if self.saved_poll is None:
            os.environ.pop("NIJA_STRATEGY_CLASS_RECOVERY_POLL_S", None)
        else:
            os.environ["NIJA_STRATEGY_CLASS_RECOVERY_POLL_S"] = self.saved_poll
        v102._RELOAD_ATTEMPTED.clear()

    def test_active_import_is_observed_without_reentering_importlib(self) -> None:
        module = types.ModuleType("bot.trading_strategy")
        module.__file__ = "/app/bot/trading_strategy.py"
        module.__spec__ = types.SimpleNamespace(_initializing=True)
        sys.modules["bot.trading_strategy"] = module

        class TradingStrategy:
            pass

        def finish_import() -> None:
            time.sleep(0.05)
            module.TradingStrategy = TradingStrategy
            module.__spec__._initializing = False

        worker = threading.Thread(target=finish_import, daemon=True)
        worker.start()
        with mock.patch.object(v102.importlib, "import_module", side_effect=AssertionError("must not re-enter importlib")):
            resolved = v102._passive_strategy_class()
        worker.join(timeout=1.0)
        self.assertIs(resolved, TradingStrategy)

    def test_stale_partial_module_reloads_once(self) -> None:
        module = types.ModuleType("bot.trading_strategy")
        module.__file__ = "/app/bot/trading_strategy.py"
        module.__spec__ = types.SimpleNamespace(_initializing=False)
        sys.modules["bot.trading_strategy"] = module

        class TradingStrategy:
            pass

        calls = []

        def fake_reload(target):
            calls.append(target)
            target.TradingStrategy = TradingStrategy
            return target

        with mock.patch.object(v102.importlib, "reload", side_effect=fake_reload):
            resolved = v102._passive_strategy_class()

        self.assertIs(resolved, TradingStrategy)
        self.assertEqual(calls, [module])

    def test_unrecoverable_active_import_remains_fail_closed(self) -> None:
        module = types.ModuleType("bot.trading_strategy")
        module.__file__ = "/app/bot/trading_strategy.py"
        module.__spec__ = types.SimpleNamespace(_initializing=True)
        sys.modules["bot.trading_strategy"] = module
        os.environ["NIJA_STRATEGY_CLASS_RECOVERY_TIMEOUT_S"] = "0.05"

        with mock.patch.object(v102.importlib, "import_module", side_effect=AssertionError("must not re-enter importlib")):
            resolved = v102._passive_strategy_class()

        self.assertIsNone(resolved)
        self.assertTrue(module.__spec__._initializing)

    def test_patch_replaces_v100_style_resolver_without_calling_it(self) -> None:
        publication = types.ModuleType("bot.strategy_publication_patch")
        calls = []

        def old_resolver():
            calls.append("old")
            raise AssertionError("superseded resolver must not be called")

        publication._strategy_class = old_resolver
        self.assertTrue(v102._patch_publication(publication))

        strategy_module = types.ModuleType("bot.trading_strategy")
        strategy_module.__spec__ = types.SimpleNamespace(_initializing=False)

        class TradingStrategy:
            pass

        strategy_module.TradingStrategy = TradingStrategy
        sys.modules["bot.trading_strategy"] = strategy_module

        self.assertIs(publication._strategy_class(), TradingStrategy)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
