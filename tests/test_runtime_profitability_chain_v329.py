from __future__ import annotations

import os


def test_canonical_profitability_chain_requires_v329(monkeypatch):
    from bot import runtime_all_in_profitability_authority_v324_patch as chain

    calls = []
    monkeypatch.setattr(chain._core, "install_import_hook", lambda: True)

    ready_envs = {
        "bot.runtime_kraken_short_margin_profit_v325_patch": "NIJA_RUNTIME_KRAKEN_SHORT_MARGIN_PROFIT_V325_READY",
        "bot.runtime_kraken_short_terminal_integrity_v326_patch": "NIJA_RUNTIME_KRAKEN_SHORT_TERMINAL_V326_READY",
        "bot.runtime_execution_cost_routing_v327_patch": "NIJA_RUNTIME_EXECUTION_COST_ROUTING_V327_READY",
        "bot.runtime_confirmed_fill_profitability_v328_patch": "NIJA_RUNTIME_CONFIRMED_FILL_PROFITABILITY_V328_READY",
        "bot.runtime_authoritative_fee_ledger_v329_patch": "NIJA_RUNTIME_AUTHORITATIVE_FEE_LEDGER_V329_READY",
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


def test_canonical_profitability_chain_fails_closed_when_v329_not_ready(monkeypatch):
    from bot import runtime_all_in_profitability_authority_v324_patch as chain

    monkeypatch.setattr(chain._core, "install_import_hook", lambda: True)

    def fake_install(module_name: str, ready_env: str) -> bool:
        return module_name != "bot.runtime_authoritative_fee_ledger_v329_patch"

    monkeypatch.setattr(chain, "_install_required", fake_install)

    assert chain.install_import_hook() is False
    assert os.environ["NIJA_CANONICAL_PROFITABILITY_CHAIN_READY"] == "0"
