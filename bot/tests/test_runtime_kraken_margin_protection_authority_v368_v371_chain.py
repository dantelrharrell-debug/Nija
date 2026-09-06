from __future__ import annotations

import os

from bot import runtime_kraken_margin_protection_authority_v368_patch as v368


def test_v368_ready_requires_v371_full_protection(monkeypatch):
    monkeypatch.setenv("NIJA_RUNTIME_KRAKEN_MARGIN_PROTECTION_TRUTH_V367_READY", "1")
    monkeypatch.setattr(v368, "_patch_software_protection_status", lambda: True)
    monkeypatch.setattr(v368, "_patch_margin_coverage_broker_scope", lambda: True)
    monkeypatch.setattr(v368, "_patch_account_brokers_authenticated_read_fallback", lambda: True)
    monkeypatch.setattr(v368, "_register_manifest", lambda: True)
    monkeypatch.setattr(v368, "_install_full_protection_v371", lambda: False)
    monkeypatch.setattr(v368, "_wake_runtime", lambda: None)

    assert v368.install_import_hook() is False
    assert os.environ["NIJA_RUNTIME_KRAKEN_MARGIN_PROTECTION_AUTHORITY_V368_READY"] == "0"


def test_v368_ready_when_authority_and_v371_are_ready(monkeypatch):
    monkeypatch.setenv("NIJA_RUNTIME_KRAKEN_MARGIN_PROTECTION_TRUTH_V367_READY", "1")
    monkeypatch.setattr(v368, "_patch_software_protection_status", lambda: True)
    monkeypatch.setattr(v368, "_patch_margin_coverage_broker_scope", lambda: True)
    monkeypatch.setattr(v368, "_patch_account_brokers_authenticated_read_fallback", lambda: True)
    monkeypatch.setattr(v368, "_register_manifest", lambda: True)
    monkeypatch.setattr(v368, "_install_full_protection_v371", lambda: True)
    monkeypatch.setattr(v368, "_wake_runtime", lambda: None)

    assert v368.install_import_hook() is True
    assert os.environ["NIJA_RUNTIME_KRAKEN_MARGIN_PROTECTION_AUTHORITY_V368_READY"] == "1"
