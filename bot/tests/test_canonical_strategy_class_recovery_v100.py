from __future__ import annotations

import os
import sys
import threading
import time
import types
import unittest
from unittest import mock

from bot import canonical_strategy_class_recovery_v100_patch as v100


class CanonicalStrategyClassRecoveryV100Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.saved_modules = {
            name: sys.modules.get(name)
            for name in ("bot.trading_strategy", "trading_strategy")
        }
        self.saved_timeout = os.environ.get("NIJA_STRATEGY_CLASS_RECOVERY_TIMEOUT_S")
        self.saved_poll = os.environ.get("NIJA_STRATEGY_CLASS_RECOVERY_POLL_S")
        os.environ["NIJA_STRATEGY_CLASS_RECOVERY_TIMEOUT_S"] = "0.5"
        os.environ["NIJA_STRATEGY_CLASS_RECOVERY_POLL_S"] = "0.01"
        v100._RELOAD_ATTEMPTED.clear()
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
        v100._RELOAD_ATTEMPTED.clear()

    def test_waits_for_real_class_from_initializing_module(self) -> None:
        module = types.ModuleType("bot.trading_strategy")
        module.__file__ = "/app/bot/trading_strategy.py"
        module.__spec__ = types.SimpleNamespace(_initializing=True)
        sys.modules["bot.trading_strategy"] = module

        class TradingStrategy:
            pass

        def publish_class() -> None:
            time.sleep(0.05)
            module.TradingStrategy = TradingStrategy
            module.__spec__._initializing = False

        worker = threading.Thread(target=publish_class, daemon=True)
        worker.start()
        resolved = v100._bounded_strategy_class(lambda: None)
        worker.join(timeout=1.0)

        self.assertIs(resolved, TradingStrategy)
        self.assertEqual(v100._RELOAD_ATTEMPTED, set())

    def test_reloads_stale_partial_module_once(self) -> None:
        module = types.ModuleType("bot.trading_strategy")
        module.__file__ = "/app/bot/trading_strategy.py"
        module.__spec__ = types.SimpleNamespace(_initializing=False)
        sys.modules["bot.trading_strategy"] = module

        class TradingStrategy:
            pass

        reload_calls = []

        def fake_reload(candidate):
            reload_calls.append(candidate)
            candidate.TradingStrategy = TradingStrategy
            return candidate

        with mock.patch.object(v100.importlib, "reload", side_effect=fake_reload):
            resolved = v100._bounded_strategy_class(lambda: None)

        self.assertIs(resolved, TradingStrategy)
        self.assertEqual(reload_calls, [module])

    def test_unrecoverable_module_remains_fail_closed(self) -> None:
        module = types.ModuleType("bot.trading_strategy")
        module.__file__ = "/app/bot/trading_strategy.py"
        module.__spec__ = types.SimpleNamespace(_initializing=False)
        sys.modules["bot.trading_strategy"] = module
        os.environ["NIJA_STRATEGY_CLASS_RECOVERY_TIMEOUT_S"] = "0.08"

        with mock.patch.object(v100.importlib, "reload", side_effect=ImportError("still broken")):
            resolved = v100._bounded_strategy_class(lambda: None)

        self.assertIsNone(resolved)
        self.assertFalse(hasattr(module, "TradingStrategy"))

    def test_patch_wraps_strategy_publication_without_marking_readiness(self) -> None:
        publication = types.ModuleType("bot.strategy_publication_patch")
        publication._strategy_class = lambda: None
        self.assertTrue(v100._patch_publication_module(publication))
        self.assertTrue(getattr(publication._strategy_class, v100._PATCH_ATTR, False))
        self.assertNotIn("NIJA_RUNTIME_EXECUTION_AUTHORITY", publication.__dict__)


if __name__ == "__main__":
    unittest.main()
