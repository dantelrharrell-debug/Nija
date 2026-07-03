import logging
import sys
from types import ModuleType, SimpleNamespace

from bot import phase3_fallback_hold_skip_patch as patch


def test_try_patch_loaded_only_targets_core_loop_modules(monkeypatch):
    calls: list[str] = []

    apex_module = ModuleType("bot.nija_apex_strategy_v71")
    apex_module.NijaCoreLoop = type("NijaCoreLoop", (), {})

    core_module = ModuleType("bot.nija_core_loop")
    core_module.NijaCoreLoop = type("NijaCoreLoop", (), {})

    monkeypatch.delitem(sys.modules, "nija_core_loop", raising=False)
    monkeypatch.setitem(sys.modules, "bot.nija_apex_strategy_v71", apex_module)
    monkeypatch.setitem(sys.modules, "bot.nija_core_loop", core_module)
    monkeypatch.setattr(patch, "_install_on_module", lambda module: calls.append(module.__name__) or True)

    assert patch._try_patch_loaded() is True
    assert calls == ["bot.nija_core_loop"]


def test_phase3_file_source_patch_uses_core_loop_globals_for_env_truthy(tmp_path, monkeypatch):
    source = '''
class NijaCoreLoop:
    def _phase3_scan_and_enter(self):
        blocked = 0
        _funnel = {}
        class Sig:
            symbol = "BTC/USD"
        for sig in [Sig()]:
            analysis = {
                "action": "hold",
                "blocked_before_execute_action": True,
                "reason": "fallback should skip",
            }
            force_enabled = _env_truthy("FORCE_TRADE")
            success = self.apex.execute_action(analysis, sig.symbol)
            return force_enabled, blocked, success
        return False, blocked, None
'''
    module_path = tmp_path / "nija_core_loop.py"
    module_path.write_text(source, encoding="utf-8")

    module = ModuleType("bot.nija_core_loop")
    module.__file__ = str(module_path)
    module.logger = logging.getLogger("nija.core_loop.test")
    module._env_truthy = lambda name, default=False: True

    class RuntimeCoreLoop:
        def _phase3_scan_and_enter(self):  # intentionally has globals without _env_truthy
            raise AssertionError("original should be replaced")

    module.NijaCoreLoop = RuntimeCoreLoop
    monkeypatch.setattr(patch, "_PATCHED_CLASSES", set())

    assert patch._patch_core_loop_phase3(module, RuntimeCoreLoop, label="bot.nija_core_loop") is True

    instance = RuntimeCoreLoop()
    instance.apex = SimpleNamespace(
        execute_action=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("hold skip must not execute")
        )
    )

    force_enabled, blocked, success = instance._phase3_scan_and_enter()

    assert force_enabled is False
    assert blocked == 1
    assert success is None
