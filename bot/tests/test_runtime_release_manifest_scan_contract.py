from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace


BOT_DIR = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location(
        "runtime_release_manifest_scan_contract_under_test",
        BOT_DIR / "runtime_release_manifest_patch.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_scan_release_contract_accepts_current_module_marker(monkeypatch):
    module = _load()
    fake_scan = SimpleNamespace(_MARKER="20260714a")
    original_import = module.importlib.import_module

    def fake_import(name: str):
        if name == "scan_wrapper_convergence_repair_patch":
            return fake_scan
        return original_import(name)

    monkeypatch.setattr(module.importlib, "import_module", fake_import)
    expected = module._expected_scan_wrapper_release()
    assert expected == "20260714a"
    assert module._scan_release_compatible("20260714a", expected) is True


def test_scan_release_contract_rejects_missing_or_stale_release():
    module = _load()
    assert module._scan_release_compatible("", "20260714a") is False
    assert module._scan_release_compatible("20260713-scan-wrapper-v2", "20260714a") is False
    assert module._scan_release_compatible("20260714a", "20260714a") is True
