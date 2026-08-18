from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
BOT = ROOT / "bot"

# Avoid importing bot.__init__ in this focused unit test.
fake_bot = types.ModuleType("bot")
fake_bot.__path__ = [str(BOT)]  # type: ignore[attr-defined]
sys.modules.setdefault("bot", fake_bot)

v144_spec = importlib.util.spec_from_file_location(
    "bot.runtime_quality_hardening_v144_patch",
    BOT / "runtime_quality_hardening_v144_patch.py",
)
assert v144_spec is not None and v144_spec.loader is not None
v144 = importlib.util.module_from_spec(v144_spec)
sys.modules["bot.runtime_quality_hardening_v144_patch"] = v144
v144_spec.loader.exec_module(v144)
setattr(fake_bot, "runtime_quality_hardening_v144_patch", v144)

classifier_spec = importlib.util.spec_from_file_location(
    "bot.runtime_quality_hardening_v144_entry_classifier_patch",
    BOT / "runtime_quality_hardening_v144_entry_classifier_patch.py",
)
assert classifier_spec is not None and classifier_spec.loader is not None
classifier = importlib.util.module_from_spec(classifier_spec)
classifier_spec.loader.exec_module(classifier)


class StrictEntryClassifierTests(unittest.TestCase):
    def test_long_entry_increases_exposure(self) -> None:
        request = SimpleNamespace(side="buy", intent_type="entry", reduce_only=False)
        self.assertTrue(classifier._entry_increases_exposure(request))

    def test_short_entry_increases_exposure(self) -> None:
        request = SimpleNamespace(side="short", intent_type="entry", reduce_only=False)
        self.assertTrue(classifier._entry_increases_exposure(request))

    def test_sell_entry_increases_exposure_without_reduce_semantics(self) -> None:
        request = SimpleNamespace(side="sell", intent_type="entry", reduce_only=False)
        self.assertTrue(classifier._entry_increases_exposure(request))

    def test_reduce_only_always_bypasses_entry_block(self) -> None:
        request = SimpleNamespace(side="buy", intent_type="entry", reduce_only=True)
        self.assertFalse(classifier._entry_increases_exposure(request))

    def test_explicit_exit_bypasses_entry_block(self) -> None:
        request = SimpleNamespace(side="sell", intent_type="exit", reduce_only=False)
        self.assertFalse(classifier._entry_increases_exposure(request))

    def test_install_replaces_v144_classifier(self) -> None:
        original_install = v144.install_import_hook
        try:
            v144.install_import_hook = lambda: True
            self.assertTrue(classifier.install_import_hook())
            short_request = SimpleNamespace(side="short", intent_type="entry", reduce_only=False)
            self.assertTrue(v144._entry_increases_exposure(short_request))
        finally:
            v144.install_import_hook = original_install


if __name__ == "__main__":
    unittest.main()
