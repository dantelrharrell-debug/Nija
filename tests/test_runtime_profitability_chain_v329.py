from __future__ import annotations

import os


def test_canonical_profitability_chain_requires_v337(monkeypatch):
    from bot import runtime_all_in_profitability_authority_v324_patch as chain

    calls = []
    monkeypatch.setattr(chain._core, "install_import_hook", lambda: True)

    ready_envs = {
        "bot.runtime_kraken_short_margin_profit_v325_patch": "NIJA_RUNTIME_KRAKEN_SHORT_MARGIN_PROFIT_V325_READY",
        "bot.runtime_kraken_short_terminal_integrity_v326_patch": "NIJA_RUNTIME_KRAKEN_SHORT_TERMINAL_V326_READY",
        "bot.runtime_execution_cost_routing_v327_patch": "NIJA_RUNTIME_EXECUTION_COST_ROUTING_V327_READY",
        "bot.runtime_confirmed_fill_profitability_v328_patch": "NIJA_RUNTIME_CONFIRMED_FILL_PROFITABILITY_V328_READY",
        "bot.runtime_authoritative_fee_ledger_v329_patch": "NIJA_RUNTIME_AUTHORITATIVE_FEE_LEDGER_V329_READY",
        "bot.runtime_capital_recycling_exit_v330_patch": "NIJA_RUNTIME_CAPITAL_RECYCLING_EXIT_V330_READY",
        "bot.runtime_universal_exit_broker_rebinding_v331_patch": "NIJA_RUNTIME_UNIVERSAL_EXIT_BROKER_REBINDING_V331_READY",
        "bot.runtime_exit_jit_conflict_recovery_v332_patch": "NIJA_RUNTIME_EXIT_JIT_CONFLICT_RECOVERY_V332_READY",
        "bot.runtime_exit_market_price_convergence_v333_patch": "NIJA_RUNTIME_EXIT_MARKET_PRICE_CONVERGENCE_V333_READY",
        "bot.runtime_canonical_exit_submission_v334_patch": "NIJA_RUNTIME_CANONICAL_EXIT_SUBMISSION_V334_READY",
        "bot.runtime_exit_capability_semantics_v335_patch": "NIJA_RUNTIME_EXIT_CAPABILITY_SEMANTICS_V335_READY",
        "bot.runtime_exit_submission_failure_truth_v336_patch": "NIJA_RUNTIME_EXIT_SUBMISSION_FAILURE_TRUTH_V336_READY",
        "bot.runtime_protective_exit_authority_bridge_v337_patch": "NIJA_RUNTIME_PROTECTIVE_EXIT_AUTHORITY_BRIDGE_V337_READY",
    }

    def fake_install(module_name: str, ready_env: str) -> bool:
        calls.append((module_name, ready_env))
        assert ready_envs[module_name] == ready_env
        return True

    monkeypatch.setattr(chain, "_install_required", fake_install)
    monkeypatch.delenv("NIJA_CANONICAL_PROFITABILITY_CHAIN_READY", raising=False)

    assert chain.install_import_hook() is True
    assert [name for name, _ in calls] == list(ready_envs)
    assert os.environ["NIJA_CANONICAL_PROFITABILITY_CHAIN_READY"] == "1"


def test_canonical_profitability_chain_fails_closed_when_v337_not_ready(monkeypatch):
    from bot import runtime_all_in_profitability_authority_v324_patch as chain

    monkeypatch.setattr(chain._core, "install_import_hook", lambda: True)

    def fake_install(module_name: str, ready_env: str) -> bool:
        return module_name != "bot.runtime_protective_exit_authority_bridge_v337_patch"

    monkeypatch.setattr(chain, "_install_required", fake_install)

    assert chain.install_import_hook() is False
    assert os.environ["NIJA_CANONICAL_PROFITABILITY_CHAIN_READY"] == "0"
