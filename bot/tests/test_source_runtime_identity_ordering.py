from __future__ import annotations

import sys
from types import ModuleType

import source_runtime_guard_bootstrap as bootstrap


def test_canonical_downstream_risk_alias_points_to_same_module(monkeypatch):
    module = ModuleType("bot.downstream_risk_governor_equity_repair_patch")
    module._MARKER = "20260714-downstream-risk-v2"
    calls = []

    def install():
        calls.append("installed")

    module.install = install
    monkeypatch.setattr(bootstrap.importlib, "import_module", lambda name: module)
    monkeypatch.delitem(sys.modules, "nija_downstream_risk_governor_equity_repair_patch", raising=False)
    monkeypatch.delitem(sys.modules, "bot.downstream_risk_governor_equity_repair_patch", raising=False)

    bootstrap._install_canonical_downstream_risk()

    assert calls == ["installed"]
    assert sys.modules["bot.downstream_risk_governor_equity_repair_patch"] is module
    assert sys.modules["nija_downstream_risk_governor_equity_repair_patch"] is module


def test_canonical_downstream_risk_rejects_wrong_release(monkeypatch):
    module = ModuleType("bot.downstream_risk_governor_equity_repair_patch")
    module._MARKER = "old-release"
    module.install = lambda: None
    monkeypatch.setattr(bootstrap.importlib, "import_module", lambda name: module)

    try:
        bootstrap._install_canonical_downstream_risk()
    except RuntimeError as exc:
        assert "downstream_risk_marker_mismatch" in str(exc)
    else:
        raise AssertionError("wrong downstream risk release was accepted")
