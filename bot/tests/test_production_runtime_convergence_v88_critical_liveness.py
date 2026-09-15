from __future__ import annotations

import sys
from types import ModuleType

from bot import production_runtime_convergence_v88_patch as subject


def _module(name: str, result: bool | Exception, calls: list[str]) -> ModuleType:
    module = ModuleType(name)

    def install_import_hook() -> bool:
        calls.append(name)
        if isinstance(result, Exception):
            raise result
        return result

    module.install_import_hook = install_import_hook  # type: ignore[attr-defined]
    return module


def _enable_runtime_hooks(monkeypatch) -> None:
    monkeypatch.delenv("NIJA_DEFER_RUNTIME_SITE_HOOKS", raising=False)


def test_critical_liveness_attempts_every_module_when_one_is_pending(monkeypatch) -> None:
    _enable_runtime_hooks(monkeypatch)
    calls: list[str] = []
    outcomes = {
        "bot.runtime_authoritative_position_coverage_v285_patch": False,
        "bot.runtime_kraken_position_refresh_liveness_v286_patch": True,
        "bot.runtime_kraken_platform_balance_capital_feed_v415_patch": True,
    }
    for name, outcome in outcomes.items():
        monkeypatch.setitem(sys.modules, name, _module(name, outcome, calls))

    assert subject._install_critical_kraken_liveness() is False
    assert calls == list(outcomes)


def test_critical_liveness_isolates_module_exception(monkeypatch) -> None:
    _enable_runtime_hooks(monkeypatch)
    calls: list[str] = []
    outcomes: dict[str, bool | Exception] = {
        "bot.runtime_authoritative_position_coverage_v285_patch": RuntimeError("not ready"),
        "bot.runtime_kraken_position_refresh_liveness_v286_patch": True,
        "bot.runtime_kraken_platform_balance_capital_feed_v415_patch": True,
    }
    for name, outcome in outcomes.items():
        monkeypatch.setitem(sys.modules, name, _module(name, outcome, calls))

    assert subject._install_critical_kraken_liveness() is False
    assert calls == list(outcomes)


def test_critical_liveness_reports_ready_only_when_all_ready(monkeypatch) -> None:
    _enable_runtime_hooks(monkeypatch)
    calls: list[str] = []
    names = (
        "bot.runtime_authoritative_position_coverage_v285_patch",
        "bot.runtime_kraken_position_refresh_liveness_v286_patch",
        "bot.runtime_kraken_platform_balance_capital_feed_v415_patch",
    )
    for name in names:
        monkeypatch.setitem(sys.modules, name, _module(name, True, calls))

    assert subject._install_critical_kraken_liveness() is True
    assert calls == list(names)


def test_critical_liveness_honors_full_suite_defer_guard(monkeypatch) -> None:
    monkeypatch.setenv("NIJA_DEFER_RUNTIME_SITE_HOOKS", "1")
    calls: list[str] = []
    name = "bot.runtime_authoritative_position_coverage_v285_patch"
    monkeypatch.setitem(sys.modules, name, _module(name, True, calls))

    assert subject._install_critical_kraken_liveness() is False
    assert calls == []
