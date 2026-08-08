from __future__ import annotations

import importlib.util
import os
import sys
import types
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "writer_recovery_monitor_cleanup_v49_patch.py"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class Monitor:
    def __init__(self):
        self.stop_calls = 0

    def stop(self):
        self.stop_calls += 1


def _bot_main(monitor):
    mod = types.ModuleType("bot.bot_main")
    mod._authority_heartbeat_monitor = monitor
    return mod


def _v39(result=True):
    mod = types.ModuleType("nija_production_readiness_v39_prebot")
    mod._assert_writer_authority = lambda: result
    return mod


def teardown_function(_fn):
    for name in ("bot.bot_main", "bot_main", "nija_production_readiness_v39_prebot"):
        sys.modules.pop(name, None)
    os.environ.pop("NIJA_RUNTIME_EXECUTION_AUTHORITY", None)
    os.environ.pop("NIJA_EXECUTION_ACTIVE", None)


def test_failed_verify_stops_and_clears_recovery_monitor():
    patch = _load("v49_test_failed")
    monitor = Monitor()
    bot_main = _bot_main(monitor)
    v39 = _v39(False)
    sys.modules["bot.bot_main"] = bot_main
    assert patch._patch_v39(v39) is True

    assert v39._assert_writer_authority() is False
    assert monitor.stop_calls == 1
    assert bot_main._authority_heartbeat_monitor is None
    assert os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] == "0"
    assert os.environ["NIJA_EXECUTION_ACTIVE"] == "false"


def test_successful_verify_leaves_monitor_running():
    patch = _load("v49_test_success")
    monitor = Monitor()
    bot_main = _bot_main(monitor)
    v39 = _v39(True)
    sys.modules["bot.bot_main"] = bot_main
    assert patch._patch_v39(v39) is True

    assert v39._assert_writer_authority() is True
    assert monitor.stop_calls == 0
    assert bot_main._authority_heartbeat_monitor is monitor


def test_patch_is_idempotent():
    patch = _load("v49_test_idempotent")
    v39 = _v39(False)
    assert patch._patch_v39(v39) is True
    first = v39._assert_writer_authority
    assert patch._patch_v39(v39) is True
    assert v39._assert_writer_authority is first


def test_failed_verify_without_monitor_remains_fail_closed():
    patch = _load("v49_test_no_monitor")
    bot_main = _bot_main(None)
    v39 = _v39(False)
    sys.modules["bot.bot_main"] = bot_main
    assert patch._patch_v39(v39) is True

    assert v39._assert_writer_authority() is False
    assert os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] == "0"
    assert os.environ["NIJA_EXECUTION_ACTIVE"] == "false"
