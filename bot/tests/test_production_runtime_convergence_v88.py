from __future__ import annotations

import logging
import sys
import types

from bot import production_runtime_convergence_v88_patch as v88


def test_generic_execute_false_counts_are_classified_separately() -> None:
    assert v88._only_generic_execution_false_counts({"execute_action_returned_false": 5}) is True
    assert v88._only_generic_execution_false_counts({"returned_false_or_none": 2}) is True
    assert v88._only_generic_execution_false_counts({"execute_action_returned_none": 1}) is True


def test_real_rejection_reason_is_never_reclassified() -> None:
    assert v88._only_generic_execution_false_counts({"exchange_rejected": 1}) is False
    assert v88._only_generic_execution_false_counts({
        "execute_action_returned_false": 5,
        "exchange_rejected": 1,
    }) is False


def test_clear_generic_counts_preserves_real_rejections() -> None:
    tsm = types.SimpleNamespace(
        _EXECUTION_CIRCUIT_BREAKER_LOCK=__import__("threading").Lock(),
        _EXECUTION_CIRCUIT_BREAKER_COUNTS={
            "execute_action_returned_false": 5,
            "exchange_rejected": 1,
        },
        _EXECUTION_CIRCUIT_BREAKER_TRIPPED=True,
        _EXECUTION_CIRCUIT_BREAKER_REASON="exchange_rejected",
    )
    assert v88._clear_generic_execution_false_counts(tsm) == {}
    assert tsm._EXECUTION_CIRCUIT_BREAKER_COUNTS["exchange_rejected"] == 1
    assert tsm._EXECUTION_CIRCUIT_BREAKER_TRIPPED is True


def test_stale_startup_filter_only_hides_expired_live_active_message() -> None:
    filt = v88._StaleStartupSuppressionFilter()

    stale = logging.LogRecord(
        "nija.final_production_activation_repair_v58",
        logging.CRITICAL,
        __file__,
        1,
        "WRITER_RELEASE_SUPPRESSED_DURING_CANONICAL_STARTUP elapsed_s=2951.1 timeout_s=360.0 state=LIVE_ACTIVE",
        (),
        None,
    )
    current = logging.LogRecord(
        "nija.final_production_activation_repair_v58",
        logging.CRITICAL,
        __file__,
        1,
        "WRITER_RELEASE_SUPPRESSED_DURING_CANONICAL_STARTUP elapsed_s=120.0 timeout_s=360.0 state=LIVE_ACTIVE",
        (),
        None,
    )
    non_live = logging.LogRecord(
        "nija.final_production_activation_repair_v58",
        logging.CRITICAL,
        __file__,
        1,
        "WRITER_RELEASE_SUPPRESSED_DURING_CANONICAL_STARTUP elapsed_s=2951.1 timeout_s=360.0 state=LIVE_PENDING_CONFIRMATION",
        (),
        None,
    )

    assert filt.filter(stale) is False
    assert filt.filter(current) is True
    assert filt.filter(non_live) is True


def _liveness_module(name: str, result: bool | Exception, calls: list[str]) -> types.ModuleType:
    module = types.ModuleType(name)

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
        monkeypatch.setitem(sys.modules, name, _liveness_module(name, outcome, calls))

    assert v88._install_critical_kraken_liveness() is False
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
        monkeypatch.setitem(sys.modules, name, _liveness_module(name, outcome, calls))

    assert v88._install_critical_kraken_liveness() is False
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
        monkeypatch.setitem(sys.modules, name, _liveness_module(name, True, calls))

    assert v88._install_critical_kraken_liveness() is True
    assert calls == list(names)


def test_critical_liveness_honors_full_suite_defer_guard(monkeypatch) -> None:
    monkeypatch.setenv("NIJA_DEFER_RUNTIME_SITE_HOOKS", "1")
    calls: list[str] = []
    name = "bot.runtime_authoritative_position_coverage_v285_patch"
    monkeypatch.setitem(sys.modules, name, _liveness_module(name, True, calls))

    assert v88._install_critical_kraken_liveness() is False
    assert calls == []
